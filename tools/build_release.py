#!/usr/bin/env python3
"""Build canonical wheel and sdist artifacts from a clean inventoried source."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verify_artifacts import (  # noqa: E402
    BUILD_EPOCH,
    SDIST_NAME,
    WHEEL_NAME,
    _canonical_sdist_bytes,
    _canonical_wheel_bytes,
    validate_source_tree,
    verify_artifacts,
)


def _require_clean(root: Path) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        raise RuntimeError(f"release source must be clean:\n{result.stdout}")


def _canonicalize_wheel(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise RuntimeError("raw wheel contains duplicate members")
        contents = {info.filename: archive.read(info) for info in infos}
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(_canonical_wheel_bytes(contents))
    temporary.replace(destination)


def _canonicalize_sdist(source: Path, destination: Path) -> None:
    contents: dict[str, bytes] = {}
    modes: dict[str, int] = {}
    with tarfile.open(source, mode="r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise RuntimeError("raw sdist contains duplicate members")
        for member in members:
            if member.isdir():
                continue
            if not member.isfile():
                raise RuntimeError(f"raw sdist contains special member {member.name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"could not read raw sdist member {member.name}")
            contents[member.name] = extracted.read()
            modes[member.name] = 0o755 if member.mode & 0o111 else 0o644
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(_canonical_sdist_bytes(contents, modes))
    temporary.replace(destination)


def build(root: Path, output_dir: Path, *, allow_dirty: bool = False) -> list[Path]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    validate_source_tree(root)
    if not allow_dirty:
        _require_clean(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.iterdir():
        if old.is_file():
            old.unlink()
        elif old.is_dir():
            shutil.rmtree(old)

    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = str(BUILD_EPOCH)
    with tempfile.TemporaryDirectory(prefix="jpl-debias-build-") as temporary_directory:
        raw_dir = Path(temporary_directory)
        subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(raw_dir), str(root)],
            check=True,
            env=environment,
        )
        raw_wheels = list(raw_dir.glob("*.whl"))
        raw_sdists = list(raw_dir.glob("*.tar.gz"))
        if len(raw_wheels) != 1 or len(raw_sdists) != 1:
            raise RuntimeError("build did not produce exactly one wheel and one sdist")
        wheel = output_dir / raw_wheels[0].name
        sdist = output_dir / raw_sdists[0].name
        _canonicalize_wheel(raw_wheels[0], wheel)
        _canonicalize_sdist(raw_sdists[0], sdist)

    expected_names = {WHEEL_NAME, SDIST_NAME}
    artifacts = sorted(output_dir.iterdir())
    if {artifact.name for artifact in artifacts} != expected_names:
        raise RuntimeError("canonical artifact names do not match the release contract")
    verify_artifacts(artifacts, root)
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="development only; official artifact builds must use clean source",
    )
    args = parser.parse_args()
    for artifact in build(args.source_root, args.output_dir, allow_dirty=args.allow_dirty):
        print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
