# HTTP Range Reader

[![CI](https://img.shields.io/github/actions/workflow/status/RevEngine3r/http-range-reader/ci.yml?branch=main)](https://github.com/RevEngine3r/http-range-reader/actions)
[![PyPI](https://img.shields.io/pypi/v/http-range-reader.svg)](https://pypi.org/project/http-range-reader/)
[![Python](https://img.shields.io/pypi/pyversions/http-range-reader.svg)](https://pypi.org/project/http-range-reader/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Minimal, production-ready **HTTP byte-range reader** that behaves like a read-only file object. It supports **2‑chunk LRU caching**, **parallel prefetch**, and clean **random access** into large remote files (think: ZIP archives, tarballs, parquet splits, ISO images) without downloading the whole object.

> Python **3.9+**. Transport: `requests` (HTTP/1.1).

## Features
- Single-file, zero-deps (runtime) except `requests`
- 2-chunk LRU (current + previous) to reduce re-fetches on back-seeks
- Background prefetch of the next chunk for smooth sequential reads
- `If-Range` with `ETag`/`Last-Modified` to prevent mixing chunks after remote updates
- Graceful fallback when servers ignore `Range` (200 OK)
- Works anywhere a **file-like** object works (`zipfile`, `tarfile`, `PIL.Image.open`, etc.)

## Install
```bash
pip install http-range-reader
```
*(or use directly by copying `src/http_range_reader/reader.py` into your project)*

## Quickstart
```python
from zipfile import ZipFile
from http_range_reader import HTTPRangeReader

url = "https://github.com/psf/requests/archive/refs/heads/main.zip"
rdr = HTTPRangeReader(url, chunk_size=1024*1024, prefetch=True)

with rdr:
    with ZipFile(rdr) as zf:
        print(len(rdr), "bytes over HTTP")
        print("first 5 entries:")
        for info in zf.infolist()[:5]:
            print("-", info.filename, info.file_size)
        data = zf.read(zf.infolist()[0].filename)
        print("read", len(data), "bytes from first member")
```

## When to use this
- You need **random access** into large objects over HTTP
- You want to avoid full downloads and keep **RAM small**
- You can rely on standard HTTP servers/CDNs that support **Range requests**

## FAQ
**Does it cache the whole file?** No. It caches at most **two chunks** at a time.

**HTTP/2 or HTTP/3?** Default transport is `requests` (HTTP/1.1). You can swap your own transport if needed.

**Thread safety?** Intended for single-reader usage. The internal executor is only for prefetching.

## CLI demo
```bash
python -m examples.http_zip_demo --url https://github.com/psf/requests/archive/refs/heads/main.zip --list 10
```

## Roadmap
- Optional `httpx` transport (HTTP/2)
- Adaptive prefetch sizing
- Multi-range coalescing (multipart/byteranges) when beneficial

## License
[MIT](LICENSE)
