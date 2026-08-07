import gzip
from pathlib import Path

from mupgpatch.inspect import inspect_image


def test_detects_gzip_and_size(tmp_path: Path):
    f = tmp_path / "blob.bin"
    f.write_bytes(gzip.compress(b"hello world" * 100))
    report = inspect_image(f, use_external=False)
    assert report.size == f.stat().st_size
    names = [name for _, name in report.signatures]
    assert "gzip" in names


def test_detects_squashfs_magic(tmp_path: Path):
    f = tmp_path / "fs.img"
    f.write_bytes(b"hsqs" + b"\x00" * 64)
    report = inspect_image(f, use_external=False)
    assert any(name.startswith("squashfs") for _, name in report.signatures)


def test_extracts_version_strings(tmp_path: Path):
    f = tmp_path / "fw.mupg"
    f.write_bytes(b"\x00\x01garbage version=1.00.93 build\x00\x02more 2.5.1 text")
    report = inspect_image(f, use_external=False)
    joined = " ".join(report.ascii_version_strings)
    assert "1.00.93" in joined
    assert "2.5.1" in joined


def test_entropy_low_for_zeros(tmp_path: Path):
    f = tmp_path / "zeros.bin"
    f.write_bytes(b"\x00" * 4096)
    report = inspect_image(f, use_external=False)
    assert report.entropy < 0.1


def test_summary_is_string(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"PK\x03\x04" + b"\x00" * 32)
    report = inspect_image(f, use_external=False)
    assert isinstance(report.summary(), str)
    assert "zip" in report.summary()
