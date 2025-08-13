import os
import pytest
from zipfile import ZipFile

from http_range_reader import HTTPRangeReader

ZIP_URL = os.getenv("ZIP_URL")

pytestmark = pytest.mark.skipif(not ZIP_URL, reason="set ZIP_URL env var to run network test")


def test_list_and_read_member():
    rdr = HTTPRangeReader(ZIP_URL, prefetch=True)
    with rdr:
        with ZipFile(rdr) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            assert infos, "zip must contain files"
            target = infos[0].filename
            data = zf.read(target)
            assert len(data) == zf.getinfo(target).file_size
