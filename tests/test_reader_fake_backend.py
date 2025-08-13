import io
import os
import types
from http_range_reader.reader import HTTPRangeReader


class FakeRangeReader(HTTPRangeReader):
    """Subclass that fakes network I/O using an in-memory bytes object."""
    def __init__(self, data: bytes, chunk_size=1024):
        # Bypass parent init; set up minimal state
        self.url = "mem://fake"
        self.chunk_size = int(chunk_size)
        self.timeout = 0
        self._external_session = True
        self.s = None  # unused
        self._base_headers = {}
        self.pos = 0
        self.size = len(data)
        self._accept_ranges = True
        self._etag = None
        self._last_modified = None
        self._lru = {}
        self.cache = b""
        self.cache_start = 0
        self.cache_end = 0
        self._prefetch_enabled = False
        self._prefetch_pool = None
        self._next_future = None
        self._lock = types.SimpleNamespace(__enter__=lambda s: None, __exit__=lambda s,a,b,c: None)
        self._data = data

    def _range_get(self, start: int, end: int) -> bytes:
        # emulate 206 inclusive range
        end_inclusive = min(end, self.size - 1)
        if start >= self.size:
            return b""
        return self._data[start : end_inclusive + 1]

    def _init_remote(self):
        pass  # already initialized above


def test_sequential_then_backseek():
    data = b"abcdefghijklmnopqrstuvwxyz" * 100
    r = FakeRangeReader(data, chunk_size=64)
    # read first 80 bytes (cross chunk), then seek back into previous chunk
    a = r.read(80)
    assert len(a) == 80
    pos_mid = r.tell() - 10
    r.seek(pos_mid)
    b = r.read(20)
    assert b == data[pos_mid : pos_mid + 20]


def test_len_and_seek_clamp():
    data = b"0123456789"
    r = FakeRangeReader(data, chunk_size=4)
    assert len(r) == 10
    r.seek(999999)
    assert r.tell() == len(r)
    r.seek(-5)
    assert r.tell() == 0
