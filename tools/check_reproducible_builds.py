#!/usr/bin/env python3
"""Require byte-identical wheel and sdist builds from two independent clones."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_clone(source: Path, destination: Path) -> dict[str, str]:
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", "--local", str(source), str(destination)],
        check=True,
    )
    expected_head = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    actual_head = subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual_head != expected_head:
        raise RuntimeError(f"clone HEAD mismatch: expected {expected_head}, got {actual_head}")
    subprocess.run(
        [sys.executable, "tools/build_release.py"],
        cwd=destination,
        check=True,
    )
    return {path.name: _sha256(path) for path in sorted((destination / "dist").iterdir())}


def check(source: Path) -> dict[str, str]:
    source = source.resolve()
    status = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise RuntimeError(f"reproducibility gate requires clean source:\n{status}")
    with tempfile.TemporaryDirectory(prefix="jpl-debias-repro-") as temporary_directory:
        temporary = Path(temporary_directory)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(_build_clone, source, temporary / "clone-a")
            second = executor.submit(_build_clone, source, temporary / "clone-b")
            first_hashes = first.result()
            second_hashes = second.result()
    if first_hashes != second_hashes:
        raise RuntimeError(f"clean builds differ:\nfirst={first_hashes}\nsecond={second_hashes}")
    return first_hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    args = parser.parse_args()
    for name, digest in sorted(check(args.source_root).items()):
        print(f"{digest}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
