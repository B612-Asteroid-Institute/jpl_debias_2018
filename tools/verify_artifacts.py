#!/usr/bin/env python3
"""Verify that release artifacts contain the attested data bytes."""

from __future__ import annotations

import argparse
import hashlib
import tarfile
import zipfile
from pathlib import Path

BIAS_SHA256 = "ef6a50830bb83d8b1161e7acb391eed988ea9708e9fbcccc0c834da6109476e3"
BIAS_SIZE = 37_161_151
README_SHA256 = "946823b4ca7b7a9f79a3feff3410f587ed1dd2662f5296ee379980ec3f759dec"
README_SIZE = 1_606


def _verify(contents: bytes, expected_size: int, expected_hash: str, label: str) -> None:
    if len(contents) != expected_size:
        raise ValueError(f"{label}: expected {expected_size} bytes, got {len(contents)}")
    actual_hash = hashlib.sha256(contents).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(f"{label}: expected SHA-256 {expected_hash}, got {actual_hash}")


def _wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        prefix = "jpl_debias_2018/"
        bias_name = prefix + "bias.dat"
        readme_name = prefix + "UPSTREAM_README.txt"
        if bias_name not in names or readme_name not in names:
            raise ValueError(f"{path}: required package data missing")
        _verify(archive.read(bias_name), BIAS_SIZE, BIAS_SHA256, f"{path}:{bias_name}")
        _verify(archive.read(readme_name), README_SIZE, README_SHA256, f"{path}:{readme_name}")
        forbidden = [name for name in names if name.endswith((".tgz", ".tar", ".tar.gz"))]
        if forbidden:
            raise ValueError(f"{path}: source archive must not be packaged: {forbidden}")


def _sdist(path: Path) -> None:
    with tarfile.open(path, mode="r:gz") as archive:
        names = archive.getnames()
        bias_names = [name for name in names if name.endswith("/src/jpl_debias_2018/bias.dat")]
        readme_names = [
            name for name in names if name.endswith("/src/jpl_debias_2018/UPSTREAM_README.txt")
        ]
        if len(bias_names) != 1 or len(readme_names) != 1:
            raise ValueError(f"{path}: required package data missing or duplicated")
        bias = archive.extractfile(bias_names[0])
        readme = archive.extractfile(readme_names[0])
        if bias is None or readme is None:
            raise ValueError(f"{path}: could not read required package data")
        _verify(bias.read(), BIAS_SIZE, BIAS_SHA256, f"{path}:{bias_names[0]}")
        _verify(readme.read(), README_SIZE, README_SHA256, f"{path}:{readme_names[0]}")
        forbidden = [name for name in names if name.endswith("debias_2018.tgz")]
        if forbidden:
            raise ValueError(f"{path}: source archive must not be packaged: {forbidden}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    for artifact in args.artifacts:
        if artifact.suffix == ".whl":
            _wheel(artifact)
        elif artifact.name.endswith(".tar.gz"):
            _sdist(artifact)
        else:
            raise ValueError(f"unsupported artifact: {artifact}")
        print(f"verified {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
