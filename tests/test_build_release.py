from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

from tools import build_release


def _raw_wheel(
    path: Path, *, reverse: bool, timestamp: tuple[int, int, int, int, int, int]
) -> None:
    items = [("package/b.txt", b"beta"), ("package/a.txt", b"alpha")]
    if reverse:
        items.reverse()
    with zipfile.ZipFile(path, "w") as archive:
        for name, contents in items:
            info = zipfile.ZipInfo(name, timestamp)
            info.external_attr = (0o100600 if reverse else 0o100644) << 16
            archive.writestr(info, contents)


def _raw_sdist(path: Path, *, reverse: bool, timestamp: int) -> None:
    items = [("root/b.txt", b"beta"), ("root/a.txt", b"alpha")]
    if reverse:
        items.reverse()
    with tarfile.open(path, "w:gz") as archive:
        root = tarfile.TarInfo("root")
        root.type = tarfile.DIRTYPE
        root.mtime = timestamp
        root.uid = timestamp % 1000
        archive.addfile(root)
        for name, contents in items:
            info = tarfile.TarInfo(name)
            info.size = len(contents)
            info.mtime = timestamp
            info.uid = timestamp % 1000
            archive.addfile(info, io.BytesIO(contents))


def test_wheel_canonicalization_is_byte_reproducible(tmp_path: Path) -> None:
    raw_a, raw_b = tmp_path / "raw-a.whl", tmp_path / "raw-b.whl"
    out_a, out_b = tmp_path / "out-a.whl", tmp_path / "out-b.whl"
    _raw_wheel(raw_a, reverse=False, timestamp=(2024, 1, 1, 0, 0, 0))
    _raw_wheel(raw_b, reverse=True, timestamp=(2026, 1, 1, 0, 0, 0))
    build_release._canonicalize_wheel(raw_a, out_a)
    build_release._canonicalize_wheel(raw_b, out_b)
    assert out_a.read_bytes() == out_b.read_bytes()


def test_sdist_canonicalization_is_byte_reproducible(tmp_path: Path) -> None:
    raw_a, raw_b = tmp_path / "raw-a.tar.gz", tmp_path / "raw-b.tar.gz"
    out_a, out_b = tmp_path / "out-a.tar.gz", tmp_path / "out-b.tar.gz"
    _raw_sdist(raw_a, reverse=False, timestamp=1_700_000_000)
    _raw_sdist(raw_b, reverse=True, timestamp=1_800_000_000)
    build_release._canonicalize_sdist(raw_a, out_a)
    build_release._canonicalize_sdist(raw_b, out_b)
    assert out_a.read_bytes() == out_b.read_bytes()
