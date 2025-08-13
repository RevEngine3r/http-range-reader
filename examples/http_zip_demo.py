#!/usr/bin/env python3
"""Quick demo: list files in a remote ZIP and read one member."""
import argparse
import binascii
import time
from zipfile import ZipFile

from http_range_reader import HTTPRangeReader


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--member")
    ap.add_argument("--chunk-size", type=int, default=1024 * 1024)
    ap.add_argument("--no-prefetch", action="store_true")
    ap.add_argument("--list", type=int)
    args = ap.parse_args()

    rdr = HTTPRangeReader(args.url, chunk_size=args.chunk_size, prefetch=not args.no_prefetch)

    with rdr:
        with ZipFile(rdr) as zf:
            infos = zf.infolist()
            print(f"Archive size: {len(rdr)} bytes; entries: {len(infos)}")
            if args.list:
                for i, info in enumerate(infos[: args.list], 1):
                    kind = "/" if info.is_dir() else ""
                    print(f"[{i:3}] {info.filename}{kind}  {info.file_size} bytes")
                return
            target = args.member or next(i.filename for i in infos if not i.is_dir())
            print("Reading:", target)
            t0 = time.time()
            data = zf.read(target)
            dt = time.time() - t0
            crc_calc = binascii.crc32(data) & 0xFFFFFFFF
            print(f"Read {len(data)} bytes in {dt:.3f}s, CRC32={crc_calc:08x}")


if __name__ == "__main__":
    main()
