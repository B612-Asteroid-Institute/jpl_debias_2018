#!/usr/bin/env python3
"""Fail-closed maintainer tool for verifying the fixed JPL authority.

This tool is for local verification only. It does not grant redistribution
rights and must not be used by package import, installation, or OD runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import tarfile
import tempfile
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Protocol, cast

SOURCE_URL = "https://ssd.jpl.nasa.gov/ftp/ssd/debias/debias_2018.tgz"


@dataclass(frozen=True)
class MemberSpec:
    """Expected identity and optional installed name for one archive member."""

    size: int
    sha256: str
    installed_name: str | None


@dataclass(frozen=True)
class ArchiveContract:
    """Complete immutable contract for one accepted upstream archive."""

    url: str
    size: int
    sha256: str
    members: Mapping[str, MemberSpec]


_urlopen = urllib.request.urlopen


KNOWN_AUTHORITY = ArchiveContract(
    url=SOURCE_URL,
    size=9_852_628,
    sha256="288132cefea7f1bdf0989782db1173948dd7dfef7da31910be90b16b73cfea6c",
    members=MappingProxyType(
        {
            "README.txt": MemberSpec(
                size=1_606,
                sha256="946823b4ca7b7a9f79a3feff3410f587ed1dd2662f5296ee379980ec3f759dec",
                installed_name="UPSTREAM_README.txt",
            ),
            "bias.dat": MemberSpec(
                size=37_161_151,
                sha256="ef6a50830bb83d8b1161e7acb391eed988ea9708e9fbcccc0c834da6109476e3",
                installed_name="bias.dat",
            ),
            "tiles.dat": MemberSpec(
                size=1_622_072,
                sha256="ccb313f0f04f49f0158b915b7ca997b91bba50192a808ba590a32e99a91eefa6",
                installed_name=None,
            ),
        }
    ),
)


class Readable(Protocol):
    """Bounded byte-stream interface used by archive and HTTP readers."""

    def read(self, size: int = -1) -> bytes: ...


class DownloadResponse(Readable, Protocol):
    """Subset of HTTPResponse used by the bounded downloader."""

    headers: Mapping[str, str]
    status: int

    def geturl(self) -> str: ...


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and "\\" not in name
        and not path.is_absolute()
        and name == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _read_exactly_bounded(stream: Readable, expected_size: int, label: str) -> bytes:
    """Read at most expected size + 1 and reject short or excessive input."""
    contents = stream.read(expected_size + 1)
    if len(contents) != expected_size:
        relation = "exceeds" if len(contents) > expected_size else "is shorter than"
        raise ValueError(
            f"{label} {relation} expected size {expected_size}: read {len(contents)} bytes"
        )
    return contents


def _validated_members(
    archive: bytes, contract: ArchiveContract = KNOWN_AUTHORITY
) -> dict[str, bytes]:
    if len(archive) != contract.size:
        raise ValueError(f"archive size mismatch: expected {contract.size}, got {len(archive)}")
    actual_archive_hash = _sha256(archive)
    if actual_archive_hash != contract.sha256:
        raise ValueError(
            f"archive SHA-256 mismatch: expected {contract.sha256}, got {actual_archive_hash}"
        )

    validated: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        members = tar.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            duplicates = sorted(name for name in set(names) if names.count(name) > 1)
            raise ValueError(f"archive contains duplicate members: {duplicates}")
        unsafe = sorted(name for name in names if not _safe_member_name(name))
        if unsafe:
            raise ValueError(f"archive contains unsafe member names: {unsafe}")
        expected_names = set(contract.members)
        actual_names = set(names)
        if actual_names != expected_names:
            raise ValueError(
                "archive member set mismatch: "
                f"missing={sorted(expected_names - actual_names)}, "
                f"unexpected={sorted(actual_names - expected_names)}"
            )

        for member in members:
            spec = contract.members[member.name]
            if not member.isfile():
                raise ValueError(f"archive member is not a regular file: {member.name}")
            if member.size != spec.size:
                raise ValueError(
                    f"{member.name} declared size mismatch: expected {spec.size}, got {member.size}"
                )
            extracted = tar.extractfile(member)
            if extracted is None:
                raise ValueError(f"could not read archive member: {member.name}")
            contents = _read_exactly_bounded(extracted, spec.size, member.name)
            actual_hash = _sha256(contents)
            if actual_hash != spec.sha256:
                raise ValueError(
                    f"{member.name} SHA-256 mismatch: expected {spec.sha256}, got {actual_hash}"
                )
            validated[member.name] = contents
    return validated


def _download(contract: ArchiveContract = KNOWN_AUTHORITY) -> bytes:
    request = urllib.request.Request(
        contract.url,
        headers={"User-Agent": "jpl-debias-2018-maintainer/2023.3.1.1"},
    )
    with _urlopen(request, timeout=60) as raw_response:
        response = cast(DownloadResponse, raw_response)
        if response.status != 200:
            raise ValueError(f"download returned HTTP status {response.status}")
        if response.geturl() != contract.url:
            raise ValueError(f"download redirected to unexpected URL: {response.geturl()}")
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError as error:
                raise ValueError(f"invalid Content-Length: {content_length!r}") from error
            if declared_length != contract.size:
                raise ValueError(
                    f"Content-Length mismatch: expected {contract.size}, got {declared_length}"
                )
        return _read_exactly_bounded(response, contract.size, "download")


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
        for archive_name, spec in KNOWN_AUTHORITY.members.items():
            if spec.installed_name is not None:
                _write_atomically(args.output_dir / spec.installed_name, members[archive_name])
    print(f"validated archive sha256={KNOWN_AUTHORITY.sha256}")
    for name, spec in KNOWN_AUTHORITY.members.items():
        action = "validated" if args.check_only or spec.installed_name is None else "installed"
        print(f"{action} {name} sha256={spec.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
