#!/usr/bin/env python3
"""Regenerate the exact release-source inventory.

The inventory deliberately excludes its own bytes to avoid a recursive hash.
Its exact bytes are nevertheless compared across source, sdist, and wheel by
the artifact verifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import TypedDict

INVENTORY_PATH = Path("src/jpl_debias_2018/SOURCE_INVENTORY.json")


class FileIdentity(TypedDict):
    size_bytes: int
    sha256: str
    git_mode: str


def _source_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    paths = [Path(os.fsdecode(item)) for item in result.stdout.split(b"\0") if item]
    return sorted(path for path in paths if path != INVENTORY_PATH)


def _identity(path: Path) -> FileIdentity:
    contents = path.read_bytes()
    executable = bool(path.stat().st_mode & 0o111)
    return {
        "size_bytes": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
        "git_mode": "100755" if executable else "100644",
    }


def update(root: Path) -> Path:
    root = root.resolve()
    files = {path.as_posix(): _identity(root / path) for path in _source_paths(root)}
    inventory = {
        "schema_version": 1,
        "self_path": INVENTORY_PATH.as_posix(),
        "self_identity": (
            "excluded to avoid a recursive hash; artifact verifier compares exact bytes"
        ),
        "files": files,
    }
    destination = root / INVENTORY_PATH
    destination.write_text(
        json.dumps(inventory, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    destination = update(args.root)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
