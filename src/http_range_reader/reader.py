import io
import re
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from collections import OrderedDict
from typing import Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class HTTPRangeReader(io.RawIOBase):
    """
    HTTP byte-range reader with:
      • 2-chunk LRU cache (current + previous)
      • Parallel prefetch of the next chunk (single worker)
      • Robust size detection and range validation
      • If-Range with ETag/Last-Modified
      • Retries + connection pooling (requests.Session)

    Python: 3.9+
    Thread safety: not guaranteed; intended for one reader at a time.
    """

    def __init__(
        self,
        url: str,
        chunk_size: int = 1024 * 1024,
        session: Optional[requests.Session] = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        user_agent: str = "HTTPRangeReader/2.0",
        prefetch: bool = True,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")

        self.url = url
        self.chunk_size = int(chunk_size)
        self.timeout = timeout

        # Session & retries
        self._external_session = session is not None
        self.s = session or requests.Session()
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=max_retries,
                connect=max_retries,
                read=max_retries,
                backoff_factor=backoff,
                status_forcelist=(500, 502, 503, 504),
                allowed_methods=("HEAD", "GET"),
                raise_on_status=False,
            )
        )
        self.s.mount("http://", adapter)
        self.s.mount("https://", adapter)
        self._base_headers = {"User-Agent": user_agent}

        # Stream state
        self.pos = 0
        self.size = 0
        self._accept_ranges = False
        self._etag = None
        self._last_modified = None

        # 2-chunk LRU {chunk_start: bytes}
        self._lru: "OrderedDict[int, bytes]" = OrderedDict()

        # Current window (compat with simple reader logic)
        self.cache = b""
        self.cache_start = 0
        self.cache_end = 0

        # Prefetch infra
        self._prefetch_enabled = prefetch
        self._prefetch_pool: Optional[ThreadPoolExecutor] = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="hrr-prefetch")
            if self._prefetch_enabled
            else None
        )
        self._next_future: Optional[Future] = None
        self._lock = threading.Lock()

        self._init_remote()

    # io.RawIOBase
    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            new_pos = offset
        elif whence == io.SEEK_CUR:
            new_pos = self.pos + offset
        elif whence == io.SEEK_END:
            new_pos = self.size + offset
        else:
            raise ValueError("Invalid whence")
        if new_pos < 0:
            new_pos = 0
        elif new_pos > self.size:
            new_pos = self.size
        self.pos = new_pos
        return self.pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        out = bytearray()
        remaining = n
        while remaining > 0 and self.pos < self.size:
            if not (self.cache_start <= self.pos < self.cache_end):
                self._fetch_chunk(self.pos)
            offset = self.pos - self.cache_start
            available = self.cache_end - self.pos
            to_read = available if available < remaining else remaining
            out += self.cache[offset:offset + to_read]
            self.pos += to_read
            remaining -= to_read
        return bytes(out)

    def readinto(self, b) -> int:
        mv = memoryview(b)
        n = len(mv)
        if n == 0:
            return 0
        data = self.read(n)
        mv[: len(data)] = data
        return len(data)

    def close(self) -> None:
        try:
            with self._lock:
                if self._next_future is not None:
                    try:
                        self._next_future.cancel()
                    except Exception:
                        pass
                    self._next_future = None
                if self._prefetch_pool is not None:
                    self._prefetch_pool.shutdown(wait=False, cancel_futures=True)
            if not self._external_session:
                self.s.close()
        finally:
            super().close()

    # internals
    def _init_remote(self) -> None:
        h = self.s.head(self.url, headers=self._base_headers, timeout=self.timeout)
        h.raise_for_status()
        cl = h.headers.get("Content-Length")
        if cl:
            try:
                self.size = int(cl)
            except ValueError:
                self.size = 0
        self._accept_ranges = h.headers.get("Accept-Ranges", "").lower() == "bytes"
        self._etag = h.headers.get("ETag")
        self._last_modified = h.headers.get("Last-Modified")
        if self.size <= 0 or not self._accept_ranges:
            headers = {**self._base_headers, "Range": "bytes=0-0"}
            r = self.s.get(self.url, headers=headers, timeout=self.timeout)
            r.raise_for_status()
            if r.status_code == 206:
                cr = r.headers.get("Content-Range")
                if cr:
                    m = re.match(r"bytes\s+\d+-\d+/(\d+)", cr)
                    if m:
                        self.size = int(m.group(1))
                self._accept_ranges = True
            elif r.status_code == 200:
                self._accept_ranges = False
                self.size = len(r.content)
                self._install_chunk(0, r.content)
            else:
                r.raise_for_status()
        if self.size <= 0:
            raise ValueError("Unable to determine remote size")
        if not self._accept_ranges and self.cache_end == 0:
            raise ValueError("Server does not support HTTP byte ranges")

    def _chunk_bounds(self, pos: int) -> Tuple[int, int]:
        start = (pos // self.chunk_size) * self.chunk_size
        end = min(start + self.chunk_size - 1, self.size - 1)
        return start, end

    def _headers_for_range(self, start: int, end: int) -> dict:
        headers = {**self._base_headers, "Range": f"bytes={start}-{end}"}
        if self._etag:
            headers["If-Range"] = self._etag
        elif self._last_modified:
            headers["If-Range"] = self._last_modified
        return headers

    def _range_get(self, start: int, end: int) -> bytes:
        r = self.s.get(self.url, headers=self._headers_for_range(start, end), timeout=self.timeout)
        if r.status_code == 416:
            return b""
        r.raise_for_status()
        if r.status_code == 200:
            body = r.content
            self.size = max(self.size, len(body))
            return body
        return r.content

    def _install_chunk(self, start: int, blob: bytes) -> None:
        self.cache = blob
        self.cache_start = start
        self.cache_end = start + len(blob)
        with self._lock:
            self._lru[start] = blob
            self._lru.move_to_end(start)
            while len(self._lru) > 2:
                self._lru.popitem(last=False)

    def _fetch_chunk(self, pos: int) -> None:
        start, end = self._chunk_bounds(pos)
        # warmed next?
        with self._lock:
            future = self._next_future
        if future is not None and future.done():
            try:
                nstart, nblob = future.result()
                if nstart == start:
                    self._install_chunk(nstart, nblob)
                    self._queue_prefetch(self.cache_end)
                    with self._lock:
                        self._next_future = None
                    return
            except Exception:
                with self._lock:
                    self._next_future = None
        # LRU hit?
        with self._lock:
            hit = self._lru.get(start)
            if hit is not None:
                self._lru.move_to_end(start)
        if hit is not None:
            self._install_chunk(start, hit)
            self._queue_prefetch(self.cache_end)
            return
        # fetch
        blob = self._range_get(start, end)
        if start == 0 and not self._accept_ranges and len(blob) == self.size:
            self._install_chunk(0, blob)
            return
        if not blob:
            self._install_chunk(self.size, b"")
            return
        self._install_chunk(start, blob)
        self._queue_prefetch(self.cache_end)

    def _queue_prefetch(self, next_pos: int) -> None:
        if not self._prefetch_enabled or self._prefetch_pool is None:
            return
        nstart, nend = self._chunk_bounds(next_pos)
        if nstart >= self.size:
            return
        with self._lock:
            if self._next_future is not None and not self._next_future.done():
                tgt = getattr(self._next_future, "_target_start", None)
                if tgt == nstart:
                    return
                try:
                    self._next_future.cancel()
                except Exception:
                    pass
            def _task(start: int, end: int):
                blob = self._range_get(start, end)
                return start, blob
            f = self._prefetch_pool.submit(_task, nstart, nend)
            setattr(f, "_target_start", nstart)
            self._next_future = f

    def __len__(self) -> int:
        return self.size
