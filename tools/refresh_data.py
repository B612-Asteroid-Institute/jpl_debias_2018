#!/usr/bin/env python3
"""Fail-closed maintainer tool for refreshing the committed JPL authority."""

from __future__ import annotations

import argparse
import hashlib
import io
import tarfile
import tempfile
import urllib.request
from pathlib import Path

SOURCE_URL = "https://ssd.jpl.nasa.gov/ftp/ssd/debias/debias_2018.tgz"
ARCHIVE_SHA256 = "288132cefea7f1bdf0989782db1173948dd7dfef7da31910be90b16b73cfea6c"
ARCHIVE_SIZE = 9_852_628
EXPECTED_MEMBERS = {
    "bias.dat": (
        37_161_151,
        "ef6a50830bb83d8b1161e7acb391eed988ea9708e9fbcccc0c834da6109476e3",
    ),
    "README.txt": (
        1_606,
        "946823b4ca7b7a9f79a3feff3410f587ed1dd2662f5296ee379980ec3f759dec",
    ),
}


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _validated_members(archive: bytes) -> dict[str, bytes]:
    if len(archive) != ARCHIVE_SIZE:
        raise ValueError(f"archive size mismatch: expected {ARCHIVE_SIZE}, got {len(archive)}")
    actual_archive_hash = _sha256(archive)
    if actual_archive_hash != ARCHIVE_SHA256:
        raise ValueError(
            f"archive SHA-256 mismatch: expected {ARCHIVE_SHA256}, got {actual_archive_hash}"
        )

    validated: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for name, (expected_size, expected_hash) in EXPECTED_MEMBERS.items():
            member = tar.getmember(name)
            if not member.isfile():
                raise ValueError(f"archive member is not a regular file: {name}")
            extracted = tar.extractfile(member)
            if extracted is None:
                raise ValueError(f"could not read archive member: {name}")
            contents = extracted.read()
            if len(contents) != expected_size:
                raise ValueError(
                    f"{name} size mismatch: expected {expected_size}, got {len(contents)}"
                )
            actual_hash = _sha256(contents)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"{name} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
                )
            validated[name] = contents
    return validated


def _download() -> bytes:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "jpl-debias-2018-maintainer/2023.3.1.1"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return bytes(response.read())


def _write_atomically(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(contents)
        stream.flush()
    temporary.replace(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path, help="previously downloaded debias_2018.tgz")
    source.add_argument(
        "--download",
        action="store_true",
        help="explicitly download the fixed HTTPS source (maintainer use only)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("src/jpl_debias_2018"),
        help="package data directory",
    )
    parser.add_argument("--check-only", action="store_true", help="validate without writing")
    return parser


def main() -> int:
    args = _parser().parse_args()
    archive = _download() if args.download else args.archive.read_bytes()
    members = _validated_members(archive)
    if not args.check_only:
        _write_atomically(args.output_dir / "bias.dat", members["bias.dat"])
        _write_atomically(args.output_dir / "UPSTREAM_README.txt", members["README.txt"])
    print(f"validated archive sha256={ARCHIVE_SHA256}")
    for name, (_, digest) in EXPECTED_MEMBERS.items():
        action = "validated" if args.check_only else "installed"
        print(f"{action} {name} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
