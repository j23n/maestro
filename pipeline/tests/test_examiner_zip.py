"""The examiner export's zip format, read by an independent reader (docs/12 § Final check export).

`fixtures/export/stored-zip-golden.zip` holds the bytes the app's `StoredZip` writes for five entries; the App
tests (`FinalCheckTests`) check that the Swift writer still produces exactly these bytes, and this test checks that
Python's `zipfile` reads them as a valid archive with the expected names, contents, dates and attributes.
"""

from __future__ import annotations

import stat
import zipfile
import zlib
from pathlib import Path

EXPECTED = {
    "README.txt": b"Italiano: final A1 check\n",
    "responses.json": b'{"schema": 1}\n',
    "writing/è.txt": b"Nome: Anna\n",
    "speaking/fin.speaking.01-e1.m4a": bytes([0x00, 0x00, 0x00, 0x18, 0x66, 0x74, 0x79, 0x70, 0xFF]),
    "empty.txt": b"",
}


def test_pythons_zipfile_reads_the_swift_writers_archive(root: Path) -> None:
    path = root / "fixtures" / "export" / "stored-zip-golden.zip"
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None  # every CRC matches
        infos = z.infolist()
        assert [i.filename for i in infos] == list(EXPECTED)
        for info in infos:
            assert z.read(info) == EXPECTED[info.filename]
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.flag_bits & 0x800  # UTF-8 names
            assert info.date_time == (2026, 10, 6, 9, 30, 0)  # the check's local time (UTC+2)
            stored_crc = info.CRC
            assert stored_crc == zlib.crc32(EXPECTED[info.filename])
            assert info.create_system == 3  # Unix, so the mode below applies
            mode = info.external_attr >> 16
            assert stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o644
            assert not info.is_dir()
    assert path.stat().st_size == 617
