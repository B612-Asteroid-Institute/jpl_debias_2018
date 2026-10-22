#!/usr/bin/env python3
"""Verify exact source inventory, package identity, metadata, and data bytes."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import subprocess
import tarfile
import zipfile
from collections.abc import Mapping, Sequence
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, cast

DISTRIBUTION = "jpl-debias-2018"
PACKAGE = "jpl_debias_2018"
VERSION = "2023.3.1.1"
DIST_INFO = f"{PACKAGE}-{VERSION}.dist-info"
EGG_INFO = f"src/{PACKAGE}.egg-info"
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

PACKAGE_SOURCE_TO_WHEEL = {
    f"src/{PACKAGE}/SOURCE_INVENTORY.json": f"{PACKAGE}/SOURCE_INVENTORY.json",
    f"src/{PACKAGE}/SOURCE_MANIFEST.json": f"{PACKAGE}/SOURCE_MANIFEST.json",
    f"src/{PACKAGE}/UPSTREAM_README.txt": f"{PACKAGE}/UPSTREAM_README.txt",
    f"src/{PACKAGE}/__init__.py": f"{PACKAGE}/__init__.py",
    f"src/{PACKAGE}/bias.dat": f"{PACKAGE}/bias.dat",
    f"src/{PACKAGE}/py.typed": f"{PACKAGE}/py.typed",
}

EXPECTED_CLASSIFIERS = {
    "Development Status :: 4 - Beta",
    "Intended Audience :: Science/Research",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering :: Astronomy",
    "Typing :: Typed",
}
EXPECTED_PROJECT_URLS = {
    "Homepage, https://github.com/B612-Asteroid-Institute/jpl_debias_2018",
    "Repository, https://github.com/B612-Asteroid-Institute/jpl_debias_2018",
    "Upstream data, https://ssd.jpl.nasa.gov/ftp/ssd/debias/debias_2018.tgz",
}
EXPECTED_REQUIRES_DIST = {
    'mypy>=1.10; extra == "test"',
    'pytest>=8; extra == "test"',
    'ruff>=0.8; extra == "test"',
    'build==1.6.1; extra == "build"',
    'twine==7.0.0; extra == "build"',
}


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


def _validate_data_manifest_bytes(
    manifest_bytes: bytes, bias_bytes: bytes, upstream_readme_bytes: bytes
) -> None:
    manifest = _load_json(manifest_bytes, "SOURCE_MANIFEST.json")
    if manifest.get("schema_version") != 1:
        raise VerificationError("SOURCE_MANIFEST.json: unsupported schema_version")
    if manifest.get("distribution") != DISTRIBUTION:
        raise VerificationError("SOURCE_MANIFEST.json: distribution mismatch")
    if manifest.get("package_version") != VERSION:
        raise VerificationError("SOURCE_MANIFEST.json: package version mismatch")

    source = manifest.get("source")
    if not isinstance(source, dict):
        raise VerificationError("SOURCE_MANIFEST.json: source must be an object")
    expected_source_scalars = {
        "url": "https://ssd.jpl.nasa.gov/ftp/ssd/debias/debias_2018.tgz",
        "archive_name": "debias_2018.tgz",
        "archive_size_bytes": 9_852_628,
        "archive_sha256": ARCHIVE_SHA256,
        "http_last_modified": "2023-03-01T22:24:39Z",
    }
    for key, expected in expected_source_scalars.items():
        if source.get(key) != expected:
            raise VerificationError(f"SOURCE_MANIFEST.json: source.{key} mismatch")
    expected_archive_members = {
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
    }
    if source.get("archive_members") != expected_archive_members:
        raise VerificationError("SOURCE_MANIFEST.json: archive member inventory mismatch")

    resources = manifest.get("resources")
    if not isinstance(resources, dict):
        raise VerificationError("SOURCE_MANIFEST.json: resources must be an object")
    bias = resources.get("bias.dat")
    readme = resources.get("UPSTREAM_README.txt")
    if not isinstance(bias, dict) or not isinstance(readme, dict):
        raise VerificationError("SOURCE_MANIFEST.json: required resources missing")
    if bias.get("size_bytes") != BIAS_SIZE or bias.get("sha256") != BIAS_SHA256:
        raise VerificationError("SOURCE_MANIFEST.json: bias.dat identity mismatch")
    if bias.get("bias_version") != "3.0" or bias.get("nside") != 64 or bias.get("npix") != 49_152:
        raise VerificationError("SOURCE_MANIFEST.json: bias.dat scientific metadata mismatch")
    if readme != {
        "archive_member": "README.txt",
        "size_bytes": README_SIZE,
        "sha256": README_SHA256,
    }:
        raise VerificationError("SOURCE_MANIFEST.json: upstream README identity mismatch")

    redistribution = manifest.get("redistribution")
    if not isinstance(redistribution, dict):
        raise VerificationError("SOURCE_MANIFEST.json: redistribution status missing")
    if redistribution.get("status") != "blocked":
        raise VerificationError("SOURCE_MANIFEST.json: public redistribution must remain blocked")
    if redistribution.get("public_redistribution_authorized") is not False:
        raise VerificationError("SOURCE_MANIFEST.json: authorization must fail closed")
    if redistribution.get("data_license") is not None:
        raise VerificationError("SOURCE_MANIFEST.json: must not invent a data license")
    if redistribution.get("authorization_reference") is not None:
        raise VerificationError("SOURCE_MANIFEST.json: authorization reference must be absent")

    _verify_identity(bias_bytes, BIAS_SIZE, BIAS_SHA256, "bias.dat")
    _verify_identity(upstream_readme_bytes, README_SIZE, README_SHA256, "UPSTREAM_README.txt")


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
    if inventory.get("schema_version") != 1 or inventory.get("self_path") != INVENTORY_PATH:
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
        if expected != {
            "size_bytes": size,
            "sha256": digest,
            "git_mode": indexed[relative],
        }:
            raise VerificationError(f"SOURCE_INVENTORY.json: stale identity for {relative}")
    return typed_files


def validate_source_tree(root: Path) -> dict[str, dict[str, Any]]:
    root = root.resolve()
    indexed = _git_index(root)
    if INVENTORY_PATH not in indexed:
        raise VerificationError(f"source index does not contain {INVENTORY_PATH}")
    inventory_bytes = (root / INVENTORY_PATH).read_bytes()
    inventory = _load_json(inventory_bytes, "SOURCE_INVENTORY.json")
    files = _validate_inventory_object(inventory, root, indexed)
    _validate_data_manifest_bytes(
        (root / DATA_MANIFEST_PATH).read_bytes(),
        (root / BIAS_PATH).read_bytes(),
        (root / UPSTREAM_README_PATH).read_bytes(),
    )
    return files


def _message(contents: bytes, label: str) -> Message:
    try:
        return BytesParser(policy=policy.default).parsebytes(contents)
    except Exception as error:
        raise VerificationError(f"{label}: invalid RFC 822 metadata: {error}") from error


def _one(message: Message, name: str, expected: str, label: str) -> None:
    values = message.get_all(name, [])
    if values != [expected]:
        raise VerificationError(f"{label}: {name} mismatch: {values!r}")


def _verify_metadata(contents: bytes, root: Path, label: str) -> None:
    message = _message(contents, label)
    _one(message, "Metadata-Version", "2.4", label)
    _one(message, "Name", DISTRIBUTION, label)
    _one(message, "Version", VERSION, label)
    _one(message, "Summary", "JPL EFCC18 astrometric catalog-debias reference data", label)
    _one(message, "Author-email", "B612 Asteroid Institute <info@b612foundation.org>", label)
    _one(message, "Requires-Python", ">=3.11", label)
    _one(message, "Description-Content-Type", "text/markdown", label)
    if message.get_all("License", []) or message.get_all("License-Expression", []):
        raise VerificationError(f"{label}: distribution-wide license claim is forbidden")
    if set(message.get_all("License-File", [])) != {"LICENSE", "NOTICE"}:
        raise VerificationError(f"{label}: scoped license/notice files mismatch")
    if set(message.get_all("Classifier", [])) != EXPECTED_CLASSIFIERS:
        raise VerificationError(f"{label}: classifiers mismatch")
    if set(message.get_all("Project-URL", [])) != EXPECTED_PROJECT_URLS:
        raise VerificationError(f"{label}: project URLs mismatch")
    if set(message.get_all("Provides-Extra", [])) != {"build", "test"}:
        raise VerificationError(f"{label}: extras mismatch")
    if set(message.get_all("Requires-Dist", [])) != EXPECTED_REQUIRES_DIST:
        raise VerificationError(f"{label}: dependency metadata mismatch")
    if set(message.get_all("Dynamic", [])) - {"license-file"}:
        raise VerificationError(f"{label}: unexpected dynamic metadata")
    payload = message.get_payload()
    if not isinstance(payload, str) or payload != (root / "README.md").read_text(encoding="utf-8"):
        raise VerificationError(f"{label}: long description differs from README.md")


def _verify_wheel_metadata(contents: bytes) -> None:
    message = _message(contents, "WHEEL")
    _one(message, "Wheel-Version", "1.0", "WHEEL")
    _one(message, "Generator", "setuptools (84.2.1)", "WHEEL")
    _one(message, "Root-Is-Purelib", "true", "WHEEL")
    _one(message, "Tag", "py3-none-any", "WHEEL")
    allowed = {"Wheel-Version", "Generator", "Root-Is-Purelib", "Tag"}
    unexpected = set(message.keys()) - allowed
    if unexpected:
        raise VerificationError(f"WHEEL: unexpected fields: {sorted(unexpected)}")


def _record_digest(contents: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).rstrip(b"=")
    return "sha256=" + encoded.decode("ascii")


def _verify_record(record: bytes, members: Mapping[str, bytes], record_path: str) -> None:
    rows = list(csv.reader(io.StringIO(record.decode("utf-8"))))
    if any(len(row) != 3 for row in rows):
        raise VerificationError("RECORD: every row must have three fields")
    by_path: dict[str, tuple[str, str]] = {}
    for path, digest, size in rows:
        if path in by_path:
            raise VerificationError(f"RECORD: duplicate path {path}")
        by_path[path] = (digest, size)
    if set(by_path) != set(members):
        raise VerificationError("RECORD: path set differs from wheel members")
    for path, contents in members.items():
        digest, size = by_path[path]
        if path == record_path:
            if digest or size:
                raise VerificationError("RECORD: self row must have empty hash and size")
        elif digest != _record_digest(contents) or size != str(len(contents)):
            raise VerificationError(f"RECORD: stale identity for {path}")


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
    expected = set(PACKAGE_SOURCE_TO_WHEEL.values()) | {
        metadata_path,
        wheel_path,
        top_level_path,
        record_path,
        license_path,
        notice_path,
    }
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
    _validate_wheel_members(_read_wheel(path), root)


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


def _validate_sdist_members(members: Mapping[str, bytes], root: Path) -> None:
    inventory = validate_source_tree(root)
    source_paths = set(inventory) | {INVENTORY_PATH}
    expected = source_paths | _generated_sdist_paths()
    if set(members) != expected:
        raise VerificationError(
            f"sdist member set mismatch: missing={sorted(expected - set(members))}, "
            f"unexpected={sorted(set(members) - expected)}"
        )
    for relative in source_paths:
        if members[relative] != (root / relative).read_bytes():
            raise VerificationError(f"sdist member differs from source: {relative}")
    _validate_data_manifest_bytes(
        members[DATA_MANIFEST_PATH], members[BIAS_PATH], members[UPSTREAM_README_PATH]
    )
    _verify_metadata(members["PKG-INFO"], root, "sdist PKG-INFO")
    if members[f"{EGG_INFO}/PKG-INFO"] != members["PKG-INFO"]:
        raise VerificationError("sdist PKG-INFO copies differ")
    if members["setup.cfg"] != b"[egg_info]\ntag_build = \ntag_date = 0\n\n":
        raise VerificationError("sdist setup.cfg mismatch")
    if members[f"{EGG_INFO}/dependency_links.txt"] != b"\n":
        raise VerificationError("sdist dependency_links.txt mismatch")
    if members[f"{EGG_INFO}/top_level.txt"] != b"jpl_debias_2018\n":
        raise VerificationError("sdist top_level.txt mismatch")
    source_lines = set(members[f"{EGG_INFO}/SOURCES.txt"].decode("utf-8").splitlines())
    if source_lines != expected - {"PKG-INFO", "setup.cfg"}:
        raise VerificationError("sdist SOURCES.txt does not attest the exact file set")
    requires = members[f"{EGG_INFO}/requires.txt"].decode("utf-8")
    for requirement in ("build==1.6.1", "twine==7.0.0", "mypy>=1.10", "pytest>=8", "ruff>=0.8"):
        if requires.count(requirement) != 1:
            raise VerificationError(f"sdist requires.txt mismatch for {requirement}")


def _read_sdist(path: Path) -> dict[str, bytes]:
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
            expected_root = f"{PACKAGE}-{VERSION}"
            if roots != {expected_root}:
                raise VerificationError(f"{path}: unexpected sdist root: {roots}")
            result: dict[str, bytes] = {}
            for member in tar_members:
                if member.isdir():
                    continue
                if not member.isfile():
                    raise VerificationError(f"{path}: non-regular tar member: {member.name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise VerificationError(f"{path}: unreadable tar member: {member.name}")
                relative = PurePosixPath(member.name).relative_to(expected_root).as_posix()
                result[relative] = extracted.read()
            return result
    except tarfile.TarError as error:
        raise VerificationError(f"{path}: invalid sdist tar: {error}") from error


def verify_sdist(path: Path, root: Path) -> None:
    _validate_sdist_members(_read_sdist(path), root)


def verify_artifacts(artifacts: Sequence[Path], source_root: Path) -> None:
    source_root = source_root.resolve()
    validate_source_tree(source_root)
    for artifact in artifacts:
        if artifact.suffix == ".whl":
            verify_wheel(artifact, source_root)
        elif artifact.name.endswith(".tar.gz"):
            verify_sdist(artifact, source_root)
        else:
            raise VerificationError(f"unsupported artifact: {artifact}")
        print(f"verified {artifact}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    verify_artifacts(args.artifacts, args.source_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
