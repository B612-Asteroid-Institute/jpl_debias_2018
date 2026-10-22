#!/usr/bin/env python3
"""Verify exact source, scientific identity, and canonical release artifacts."""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
import os
import subprocess
import tarfile
import time
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, cast

DISTRIBUTION = "jpl-debias-2018"
PACKAGE = "jpl_debias_2018"
VERSION = "2023.3.1.1"
DIST_INFO = f"{PACKAGE}-{VERSION}.dist-info"
EGG_INFO = f"src/{PACKAGE}.egg-info"
SDIST_ROOT = f"{PACKAGE}-{VERSION}"
WHEEL_NAME = f"{PACKAGE}-{VERSION}-py3-none-any.whl"
SDIST_NAME = f"{PACKAGE}-{VERSION}.tar.gz"
BUILD_EPOCH = 1_677_709_479  # Upstream archive Last-Modified.
INVENTORY_PATH = f"src/{PACKAGE}/SOURCE_INVENTORY.json"
DATA_MANIFEST_PATH = f"src/{PACKAGE}/SOURCE_MANIFEST.json"
BIAS_PATH = f"src/{PACKAGE}/bias.dat"
UPSTREAM_README_PATH = f"src/{PACKAGE}/UPSTREAM_README.txt"

ARCHIVE_SHA256 = "288132cefea7f1bdf0989782db1173948dd7dfef7da31910be90b16b73cfea6c"
BIAS_SHA256 = "ef6a50830bb83d8b1161e7acb391eed988ea9708e9fbcccc0c834da6109476e3"
BIAS_SIZE = 37_161_151
README_SHA256 = "946823b4ca7b7a9f79a3feff3410f587ed1dd2662f5296ee379980ec3f759dec"
README_SIZE = 1_606
TILES_SHA256 = "ccb313f0f04f49f0158b915b7ca997b91bba50192a808ba590a32e99a91eefa6"
CATALOG_CODES = [
    "a",
    "b",
    "c",
    "d",
    "e",
    "g",
    "i",
    "j",
    "l",
    "m",
    "n",
    "o",
    "p",
    "q",
    "r",
    "t",
    "u",
    "v",
    "w",
    "L",
    "N",
    "Q",
    "R",
    "S",
    "U",
    "Y",
]

PACKAGE_SOURCE_TO_WHEEL = {
    f"src/{PACKAGE}/SOURCE_INVENTORY.json": f"{PACKAGE}/SOURCE_INVENTORY.json",
    f"src/{PACKAGE}/SOURCE_MANIFEST.json": f"{PACKAGE}/SOURCE_MANIFEST.json",
    f"src/{PACKAGE}/UPSTREAM_README.txt": f"{PACKAGE}/UPSTREAM_README.txt",
    f"src/{PACKAGE}/__init__.py": f"{PACKAGE}/__init__.py",
    f"src/{PACKAGE}/bias.dat": f"{PACKAGE}/bias.dat",
    f"src/{PACKAGE}/py.typed": f"{PACKAGE}/py.typed",
}

EXPECTED_DATA_MANIFEST: dict[str, Any] = {
    "schema_version": 1,
    "distribution": DISTRIBUTION,
    "package_version": VERSION,
    "source": {
        "url": "https://ssd.jpl.nasa.gov/ftp/ssd/debias/debias_2018.tgz",
        "archive_name": "debias_2018.tgz",
        "archive_size_bytes": 9_852_628,
        "archive_sha256": ARCHIVE_SHA256,
        "http_last_modified": "2023-03-01T22:24:39Z",
        "archive_members": {
            "README.txt": {
                "size_bytes": README_SIZE,
                "sha256": README_SHA256,
                "packaged_as": "UPSTREAM_README.txt",
            },
            "bias.dat": {
                "size_bytes": BIAS_SIZE,
                "sha256": BIAS_SHA256,
                "packaged_as": "bias.dat",
            },
            "tiles.dat": {
                "size_bytes": 1_622_072,
                "sha256": TILES_SHA256,
                "packaged_as": None,
            },
        },
    },
    "resources": {
        "bias.dat": {
            "size_bytes": BIAS_SIZE,
            "sha256": BIAS_SHA256,
            "line_count": 49_175,
            "bias_version": "3.0",
            "bias_version_date": "2018-09-21",
            "archive_update_date": "2023-03-01",
            "nside": 64,
            "npix": 49_152,
            "catalog_codes": CATALOG_CODES,
        },
        "UPSTREAM_README.txt": {
            "archive_member": "README.txt",
            "size_bytes": README_SIZE,
            "sha256": README_SHA256,
        },
    },
    "redistribution": {
        "status": "blocked",
        "public_redistribution_authorized": False,
        "data_license": None,
        "authorization_reference": None,
        "code_and_documentation_license": "MIT (scoped by LICENSE)",
        "reason": (
            "The upstream archive contains no explicit license and this repository contains no "
            "applicable JPL/Caltech authorization for public "
            "redistribution of the exact data bytes."
        ),
    },
}

EXPECTED_METADATA_HEADERS = (
    "Metadata-Version: 2.4",
    "Name: jpl-debias-2018",
    "Version: 2023.3.1.1",
    "Summary: JPL EFCC18 astrometric catalog-debias reference data",
    "Author-email: B612 Asteroid Institute <info@b612foundation.org>",
    "Project-URL: Homepage, https://github.com/B612-Asteroid-Institute/jpl_debias_2018",
    "Project-URL: Repository, https://github.com/B612-Asteroid-Institute/jpl_debias_2018",
    "Project-URL: Upstream data, https://ssd.jpl.nasa.gov/ftp/ssd/debias/debias_2018.tgz",
    "Keywords: astronomy,astrometry,asteroids,catalog,debiasing,JPL",
    "Classifier: Development Status :: 4 - Beta",
    "Classifier: Intended Audience :: Science/Research",
    "Classifier: Programming Language :: Python :: 3",
    "Classifier: Programming Language :: Python :: 3 :: Only",
    "Classifier: Programming Language :: Python :: 3.11",
    "Classifier: Programming Language :: Python :: 3.12",
    "Classifier: Programming Language :: Python :: 3.13",
    "Classifier: Topic :: Scientific/Engineering :: Astronomy",
    "Classifier: Typing :: Typed",
    "Requires-Python: >=3.11",
    "Description-Content-Type: text/markdown",
    "License-File: LICENSE",
    "License-File: NOTICE",
    "Provides-Extra: test",
    'Requires-Dist: mypy>=1.10; extra == "test"',
    'Requires-Dist: pytest>=8; extra == "test"',
    'Requires-Dist: ruff>=0.8; extra == "test"',
    "Provides-Extra: build",
    'Requires-Dist: build==1.6.1; extra == "build"',
    'Requires-Dist: twine==7.0.0; extra == "build"',
    "Dynamic: license-file",
)
EXPECTED_WHEEL_BYTES = (
    b"Wheel-Version: 1.0\n"
    b"Generator: setuptools (84.2.1)\n"
    b"Root-Is-Purelib: true\n"
    b"Tag: py3-none-any\n\n"
)
EXPECTED_REQUIRES_BYTES = (
    b"\n[build]\nbuild==1.6.1\ntwine==7.0.0\n\n[test]\nmypy>=1.10\npytest>=8\nruff>=0.8\n"
)


class VerificationError(ValueError):
    """Artifact or source does not satisfy the release contract."""


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _load_json(contents: bytes, label: str) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise VerificationError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        parsed = json.loads(contents, object_pairs_hook=no_duplicates)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise VerificationError(f"{label}: invalid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise VerificationError(f"{label}: top-level JSON value must be an object")
    return cast(dict[str, Any], parsed)


def _identity(contents: bytes) -> tuple[int, str]:
    return len(contents), _sha256(contents)


def _verify_identity(contents: bytes, size: int, digest: str, label: str) -> None:
    actual_size, actual_digest = _identity(contents)
    if actual_size != size:
        raise VerificationError(f"{label}: expected {size} bytes, got {actual_size}")
    if actual_digest != digest:
        raise VerificationError(f"{label}: expected SHA-256 {digest}, got {actual_digest}")


def _expected_manifest_bytes() -> bytes:
    return (json.dumps(EXPECTED_DATA_MANIFEST, indent=2) + "\n").encode("utf-8")


def _validate_data_manifest_bytes(
    manifest_bytes: bytes, bias_bytes: bytes, upstream_readme_bytes: bytes
) -> None:
    # Loading first gives explicit duplicate-key/JSON failures. Exact canonical bytes then
    # pin every recursive key, type, value, order, and representation.
    _load_json(manifest_bytes, "SOURCE_MANIFEST.json")
    if manifest_bytes != _expected_manifest_bytes():
        raise VerificationError("SOURCE_MANIFEST.json: exact schema/value mismatch")
    _verify_identity(bias_bytes, BIAS_SIZE, BIAS_SHA256, "bias.dat")
    _verify_identity(upstream_readme_bytes, README_SIZE, README_SHA256, "UPSTREAM_README.txt")
    lines = bias_bytes.splitlines()
    expected_header = [
        b"! BIAS_VERSION= 3.0 (September 21, 2018)",
        b"! NSIDE= 64 ",
        b"! NPIX= 49152 ",
        b"! Catalogs in this file (MPC designation):",
        b"! " + " ".join(CATALOG_CODES).encode("ascii"),
    ]
    if len(lines) != 49_175 or lines[:5] != expected_header:
        raise VerificationError("bias.dat: scientific header/line-count mismatch")


def _git_index(root: Path) -> dict[str, str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--stage", "-z"],
        check=True,
        capture_output=True,
    )
    indexed: dict[str, str] = {}
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, _object_id, stage = metadata.decode("ascii").split()
        if stage != "0":
            raise VerificationError("source index contains unresolved stages")
        path = os.fsdecode(raw_path)
        if path in indexed:
            raise VerificationError(f"source index contains duplicate path: {path}")
        indexed[path] = mode
    return indexed


def _validate_inventory_object(
    inventory: dict[str, Any], root: Path, indexed: Mapping[str, str]
) -> dict[str, dict[str, Any]]:
    if set(inventory) != {"schema_version", "self_path", "self_identity", "files"}:
        raise VerificationError("SOURCE_INVENTORY.json: exact top-level schema mismatch")
    if (
        inventory.get("schema_version") != 1
        or inventory.get("self_path") != INVENTORY_PATH
        or inventory.get("self_identity")
        != "excluded to avoid a recursive hash; artifact verifier compares exact bytes"
    ):
        raise VerificationError("SOURCE_INVENTORY.json: header mismatch")
    files = inventory.get("files")
    if not isinstance(files, dict):
        raise VerificationError("SOURCE_INVENTORY.json: files must be an object")
    expected_paths = set(indexed) - {INVENTORY_PATH}
    if set(files) != expected_paths:
        raise VerificationError(
            "SOURCE_INVENTORY.json: path set mismatch: "
            f"missing={sorted(expected_paths - set(files))}, "
            f"unexpected={sorted(set(files) - expected_paths)}"
        )
    typed_files = cast(dict[str, dict[str, Any]], files)
    for relative, expected in typed_files.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise VerificationError(f"source inventory path is not a regular file: {relative}")
        contents = path.read_bytes()
        size, digest = _identity(contents)
        if expected != {"size_bytes": size, "sha256": digest, "git_mode": indexed[relative]}:
            raise VerificationError(f"SOURCE_INVENTORY.json: stale identity for {relative}")
    return typed_files


def validate_source_tree(root: Path) -> dict[str, dict[str, Any]]:
    root = root.resolve()
    indexed = _git_index(root)
    if INVENTORY_PATH not in indexed:
        raise VerificationError(f"source index does not contain {INVENTORY_PATH}")
    inventory = _load_json((root / INVENTORY_PATH).read_bytes(), "SOURCE_INVENTORY.json")
    files = _validate_inventory_object(inventory, root, indexed)
    _validate_data_manifest_bytes(
        (root / DATA_MANIFEST_PATH).read_bytes(),
        (root / BIAS_PATH).read_bytes(),
        (root / UPSTREAM_README_PATH).read_bytes(),
    )
    return files


def _expected_metadata_bytes(root: Path) -> bytes:
    return ("\n".join(EXPECTED_METADATA_HEADERS) + "\n\n").encode() + (
        root / "README.md"
    ).read_bytes()


def _verify_metadata(contents: bytes, root: Path, label: str) -> None:
    if contents != _expected_metadata_bytes(root):
        raise VerificationError(
            f"{label}: exact metadata headers/order/multiplicity/description mismatch"
        )


def _verify_wheel_metadata(contents: bytes) -> None:
    if contents != EXPECTED_WHEEL_BYTES:
        raise VerificationError("WHEEL: exact metadata mismatch")


def _record_digest(contents: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).rstrip(b"=")
    return "sha256=" + encoded.decode("ascii")


def _record_order(record_path: str) -> list[str]:
    return [
        *PACKAGE_SOURCE_TO_WHEEL.values(),
        f"{DIST_INFO}/licenses/LICENSE",
        f"{DIST_INFO}/licenses/NOTICE",
        f"{DIST_INFO}/METADATA",
        f"{DIST_INFO}/WHEEL",
        f"{DIST_INFO}/top_level.txt",
        record_path,
    ]


def _canonical_record(members: Mapping[str, bytes], record_path: str) -> bytes:
    if set(members) != set(_record_order(record_path)):
        raise VerificationError("RECORD: cannot construct identity for unexpected member set")
    rows = []
    for path in _record_order(record_path):
        if path == record_path:
            rows.append(f"{path},,")
        else:
            contents = members[path]
            rows.append(f"{path},{_record_digest(contents)},{len(contents)}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _verify_record(record: bytes, members: Mapping[str, bytes], record_path: str) -> None:
    try:
        rows = list(csv.reader(io.StringIO(record.decode("utf-8"))))
    except (UnicodeDecodeError, csv.Error) as error:
        raise VerificationError(f"RECORD: invalid CSV: {error}") from error
    if any(len(row) != 3 for row in rows):
        raise VerificationError("RECORD: every row must have three fields")
    if record != _canonical_record(members, record_path):
        raise VerificationError("RECORD: exact ordered path/hash/size identity mismatch")


def _safe_archive_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and "\\" not in name
        and not path.is_absolute()
        and name == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _validate_wheel_members(members: Mapping[str, bytes], root: Path) -> None:
    validate_source_tree(root)
    metadata_path = f"{DIST_INFO}/METADATA"
    wheel_path = f"{DIST_INFO}/WHEEL"
    top_level_path = f"{DIST_INFO}/top_level.txt"
    record_path = f"{DIST_INFO}/RECORD"
    license_path = f"{DIST_INFO}/licenses/LICENSE"
    notice_path = f"{DIST_INFO}/licenses/NOTICE"
    expected = set(_record_order(record_path))
    if set(members) != expected:
        raise VerificationError(
            f"wheel member set mismatch: missing={sorted(expected - set(members))}, "
            f"unexpected={sorted(set(members) - expected)}"
        )
    for source, wheel_name in PACKAGE_SOURCE_TO_WHEEL.items():
        if members[wheel_name] != (root / source).read_bytes():
            raise VerificationError(f"wheel member differs from source: {wheel_name}")
    if members[license_path] != (root / "LICENSE").read_bytes():
        raise VerificationError("wheel LICENSE differs from source")
    if members[notice_path] != (root / "NOTICE").read_bytes():
        raise VerificationError("wheel NOTICE differs from source")
    _validate_data_manifest_bytes(
        members[f"{PACKAGE}/SOURCE_MANIFEST.json"],
        members[f"{PACKAGE}/bias.dat"],
        members[f"{PACKAGE}/UPSTREAM_README.txt"],
    )
    _verify_metadata(members[metadata_path], root, "METADATA")
    _verify_wheel_metadata(members[wheel_path])
    if members[top_level_path] != b"jpl_debias_2018\n":
        raise VerificationError("top_level.txt mismatch")
    _verify_record(members[record_path], members, record_path)


def _canonical_wheel_bytes(members: Mapping[str, bytes]) -> bytes:
    destination = io.BytesIO()
    timestamp = time.gmtime(BUILD_EPOCH)[:6]
    with zipfile.ZipFile(
        destination,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.flag_bits = 0x800
            archive.writestr(info, members[name])
    return destination.getvalue()


def _read_wheel(path: Path) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise VerificationError(f"{path}: duplicate ZIP members")
            unsafe = [name for name in names if not _safe_archive_name(name)]
            if unsafe:
                raise VerificationError(f"{path}: unsafe ZIP members: {unsafe}")
            return {info.filename: archive.read(info) for info in infos}
    except zipfile.BadZipFile as error:
        raise VerificationError(f"{path}: invalid wheel ZIP: {error}") from error


def verify_wheel(path: Path, root: Path) -> None:
    if path.name != WHEEL_NAME:
        raise VerificationError(f"wheel filename mismatch: expected {WHEEL_NAME}, got {path.name}")
    members = _read_wheel(path)
    _validate_wheel_members(members, root)
    if path.read_bytes() != _canonical_wheel_bytes(members):
        raise VerificationError("wheel container is not the exact canonical ZIP")


def _generated_sdist_paths() -> set[str]:
    return {
        "PKG-INFO",
        "setup.cfg",
        f"{EGG_INFO}/PKG-INFO",
        f"{EGG_INFO}/SOURCES.txt",
        f"{EGG_INFO}/dependency_links.txt",
        f"{EGG_INFO}/requires.txt",
        f"{EGG_INFO}/top_level.txt",
    }


def _expected_sources_entries(source_paths: set[str]) -> list[str]:
    root_order = [
        ".gitattributes",
        ".gitignore",
        "LICENSE",
        "MANIFEST.in",
        "NOTICE",
        "README.md",
        "pyproject.toml",
    ]
    entries = [path for path in root_order if path in source_paths]
    entries.extend(sorted(path for path in source_paths if path.startswith(".github/")))
    entries.extend(sorted(path for path in source_paths if path.startswith(f"src/{PACKAGE}/")))
    entries.extend(
        [
            f"{EGG_INFO}/PKG-INFO",
            f"{EGG_INFO}/SOURCES.txt",
            f"{EGG_INFO}/dependency_links.txt",
            f"{EGG_INFO}/requires.txt",
            f"{EGG_INFO}/top_level.txt",
        ]
    )
    entries.extend(sorted(path for path in source_paths if path.startswith("tests/")))
    entries.extend(sorted(path for path in source_paths if path.startswith("tools/")))
    consumed = set(entries) - {
        f"{EGG_INFO}/PKG-INFO",
        f"{EGG_INFO}/SOURCES.txt",
        f"{EGG_INFO}/dependency_links.txt",
        f"{EGG_INFO}/requires.txt",
        f"{EGG_INFO}/top_level.txt",
    }
    if consumed != source_paths:
        raise VerificationError(
            "sdist SOURCES.txt policy does not classify exact source paths: "
            f"missing={sorted(source_paths - consumed)}, "
            f"unexpected={sorted(consumed - source_paths)}"
        )
    return entries


def _expected_sdist_members(root: Path) -> dict[str, bytes]:
    inventory = validate_source_tree(root)
    source_paths = set(inventory) | {INVENTORY_PATH}
    members = {relative: (root / relative).read_bytes() for relative in source_paths}
    metadata = _expected_metadata_bytes(root)
    members["PKG-INFO"] = metadata
    members[f"{EGG_INFO}/PKG-INFO"] = metadata
    members["setup.cfg"] = b"[egg_info]\ntag_build = \ntag_date = 0\n\n"
    members[f"{EGG_INFO}/dependency_links.txt"] = b"\n"
    members[f"{EGG_INFO}/requires.txt"] = EXPECTED_REQUIRES_BYTES
    members[f"{EGG_INFO}/top_level.txt"] = b"jpl_debias_2018\n"
    members[f"{EGG_INFO}/SOURCES.txt"] = "\n".join(_expected_sources_entries(source_paths)).encode(
        "utf-8"
    )
    return members


def _validate_sdist_members(members: Mapping[str, bytes], root: Path) -> None:
    expected = _expected_sdist_members(root)
    if set(members) != set(expected):
        raise VerificationError(
            f"sdist member set mismatch: missing={sorted(set(expected) - set(members))}, "
            f"unexpected={sorted(set(members) - set(expected))}"
        )
    for relative, expected_bytes in expected.items():
        if members[relative] != expected_bytes:
            raise VerificationError(f"sdist member differs from exact contract: {relative}")
    _validate_data_manifest_bytes(
        members[DATA_MANIFEST_PATH], members[BIAS_PATH], members[UPSTREAM_README_PATH]
    )
    _verify_metadata(members["PKG-INFO"], root, "sdist PKG-INFO")
    _verify_metadata(members[f"{EGG_INFO}/PKG-INFO"], root, "sdist egg-info PKG-INFO")


def _directory_names(file_names: Sequence[str]) -> set[str]:
    directories: set[str] = set()
    for name in file_names:
        path = PurePosixPath(name)
        for parent in path.parents:
            if parent.as_posix() != ".":
                directories.add(parent.as_posix())
    return directories


def _canonical_sdist_bytes(
    full_members: Mapping[str, bytes], file_modes: Mapping[str, int]
) -> bytes:
    if set(full_members) != set(file_modes):
        raise VerificationError("canonical sdist mode/member sets differ")
    directories = _directory_names(list(full_members))
    raw = io.BytesIO()
    with (
        gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=BUILD_EPOCH
        ) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as archive,
    ):
        for name in sorted(directories | set(full_members)):
            info = tarfile.TarInfo(name)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = BUILD_EPOCH
            if name in directories:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.size = 0
                archive.addfile(info)
            else:
                contents = full_members[name]
                info.type = tarfile.REGTYPE
                info.mode = file_modes[name]
                info.size = len(contents)
                archive.addfile(info, fileobj=io.BytesIO(contents))
    return raw.getvalue()


def _expected_sdist_file_modes(root: Path, relative_names: set[str]) -> dict[str, int]:
    indexed = _git_index(root)
    result: dict[str, int] = {}
    for relative in relative_names:
        mode = 0o755 if indexed.get(relative) == "100755" else 0o644
        result[f"{SDIST_ROOT}/{relative}"] = mode
    return result


def _read_sdist(path: Path) -> tuple[dict[str, bytes], set[str]]:
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            tar_members = archive.getmembers()
            names = [member.name for member in tar_members]
            if len(names) != len(set(names)):
                raise VerificationError(f"{path}: duplicate tar members")
            unsafe = [name for name in names if not _safe_archive_name(name)]
            if unsafe:
                raise VerificationError(f"{path}: unsafe tar members: {unsafe}")
            roots = {PurePosixPath(name).parts[0] for name in names}
            if roots != {SDIST_ROOT}:
                raise VerificationError(f"{path}: unexpected sdist root: {roots}")
            result: dict[str, bytes] = {}
            directories: set[str] = set()
            for member in tar_members:
                relative = PurePosixPath(member.name).relative_to(SDIST_ROOT).as_posix()
                if relative == ".":
                    relative = ""
                if member.isdir():
                    directories.add(relative)
                    continue
                if not member.isfile():
                    raise VerificationError(f"{path}: non-regular tar member: {member.name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise VerificationError(f"{path}: unreadable tar member: {member.name}")
                result[relative] = extracted.read()
            return result, directories
    except (tarfile.TarError, OSError) as error:
        raise VerificationError(f"{path}: invalid sdist tar/gzip: {error}") from error


def verify_sdist(path: Path, root: Path) -> None:
    if path.name != SDIST_NAME:
        raise VerificationError(f"sdist filename mismatch: expected {SDIST_NAME}, got {path.name}")
    members, directories = _read_sdist(path)
    _validate_sdist_members(members, root)
    full_members = {f"{SDIST_ROOT}/{name}": contents for name, contents in members.items()}
    expected_directories = {
        "" if name == SDIST_ROOT else PurePosixPath(name).relative_to(SDIST_ROOT).as_posix()
        for name in _directory_names(list(full_members))
    }
    if directories != expected_directories:
        raise VerificationError(
            "sdist directory set mismatch: "
            f"missing={sorted(expected_directories - directories)}, "
            f"unexpected={sorted(directories - expected_directories)}"
        )
    modes = _expected_sdist_file_modes(root, set(members))
    if path.read_bytes() != _canonical_sdist_bytes(full_members, modes):
        raise VerificationError("sdist container is not the exact canonical tar/gzip")


def verify_artifacts(artifacts: Sequence[Path], source_root: Path) -> None:
    source_root = source_root.resolve()
    validate_source_tree(source_root)
    by_name = {artifact.name: artifact for artifact in artifacts}
    expected_names = {WHEEL_NAME, SDIST_NAME}
    if len(artifacts) != 2 or set(by_name) != expected_names:
        raise VerificationError(
            f"release artifact set mismatch: expected={sorted(expected_names)}, "
            f"got={sorted(artifact.name for artifact in artifacts)}"
        )
    verify_wheel(by_name[WHEEL_NAME], source_root)
    print(f"verified {by_name[WHEEL_NAME]}")
    verify_sdist(by_name[SDIST_NAME], source_root)
    print(f"verified {by_name[SDIST_NAME]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    verify_artifacts(args.artifacts, args.source_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
