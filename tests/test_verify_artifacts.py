from __future__ import annotations

from pathlib import Path

import pytest

from tools import verify_artifacts as verifier

ROOT = Path(__file__).parents[1]


def _metadata() -> bytes:
    headers = [
        "Metadata-Version: 2.4",
        "Name: jpl-debias-2018",
        "Version: 2023.3.1.1",
        "Summary: JPL EFCC18 astrometric catalog-debias reference data",
        "Author-email: B612 Asteroid Institute <info@b612foundation.org>",
        "Project-URL: Homepage, https://github.com/B612-Asteroid-Institute/jpl_debias_2018",
        "Project-URL: Repository, https://github.com/B612-Asteroid-Institute/jpl_debias_2018",
        "Project-URL: Upstream data, https://ssd.jpl.nasa.gov/ftp/ssd/debias/debias_2018.tgz",
        "Keywords: astronomy,astrometry,asteroids,catalog,debiasing,JPL",
        *(f"Classifier: {value}" for value in sorted(verifier.EXPECTED_CLASSIFIERS)),
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
    ]
    return ("\n".join(headers) + "\n\n" + (ROOT / "README.md").read_text()).encode()


def _wheel_members() -> dict[str, bytes]:
    members = {
        wheel_name: (ROOT / source).read_bytes()
        for source, wheel_name in verifier.PACKAGE_SOURCE_TO_WHEEL.items()
    }
    prefix = verifier.DIST_INFO
    members[f"{prefix}/licenses/LICENSE"] = (ROOT / "LICENSE").read_bytes()
    members[f"{prefix}/licenses/NOTICE"] = (ROOT / "NOTICE").read_bytes()
    members[f"{prefix}/METADATA"] = _metadata()
    members[f"{prefix}/WHEEL"] = (
        b"Wheel-Version: 1.0\n"
        b"Generator: setuptools (84.2.1)\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n\n"
    )
    members[f"{prefix}/top_level.txt"] = b"jpl_debias_2018\n"
    record_path = f"{prefix}/RECORD"
    members[record_path] = b""
    rows = []
    for path, contents in sorted(members.items()):
        if path == record_path:
            rows.append(f"{path},,")
        else:
            rows.append(f"{path},{verifier._record_digest(contents)},{len(contents)}")
    members[record_path] = ("\n".join(rows) + "\n").encode()
    return members


def _sdist_members() -> dict[str, bytes]:
    inventory = verifier.validate_source_tree(ROOT)
    source_paths = set(inventory) | {verifier.INVENTORY_PATH}
    members = {path: (ROOT / path).read_bytes() for path in source_paths}
    members["PKG-INFO"] = _metadata()
    members[f"{verifier.EGG_INFO}/PKG-INFO"] = members["PKG-INFO"]
    members["setup.cfg"] = b"[egg_info]\ntag_build = \ntag_date = 0\n\n"
    members[f"{verifier.EGG_INFO}/dependency_links.txt"] = b"\n"
    members[f"{verifier.EGG_INFO}/requires.txt"] = (
        b"[test]\nmypy>=1.10\npytest>=8\nruff>=0.8\n\n[build]\nbuild==1.6.1\ntwine==7.0.0\n"
    )
    members[f"{verifier.EGG_INFO}/top_level.txt"] = b"jpl_debias_2018\n"
    sources_path = f"{verifier.EGG_INFO}/SOURCES.txt"
    members[sources_path] = b""
    expected = set(members)
    members[sources_path] = (
        "\n".join(sorted(expected - {"PKG-INFO", "setup.cfg"})) + "\n"
    ).encode()
    return members


def _mutate(members: dict[str, bytes], path: str, replacement: bytes) -> dict[str, bytes]:
    mutated = members.copy()
    mutated[path] = replacement
    return mutated


def test_valid_wheel_contract() -> None:
    verifier._validate_wheel_members(_wheel_members(), ROOT)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        ("jpl_debias_2018/SOURCE_MANIFEST.json", b"{}\n"),
        ("jpl_debias_2018/SOURCE_INVENTORY.json", b"{}\n"),
        ("jpl_debias_2018/__init__.py", b"bias_dat = '/tmp/forged'\n"),
        ("jpl_debias_2018/bias.dat", b"corrupt"),
        (f"{verifier.DIST_INFO}/licenses/LICENSE", b"forged"),
        (f"{verifier.DIST_INFO}/licenses/NOTICE", b"forged"),
    ],
)
def test_wheel_rejects_identity_file_mutations(path: str, replacement: bytes) -> None:
    with pytest.raises(verifier.VerificationError):
        verifier._validate_wheel_members(_mutate(_wheel_members(), path, replacement), ROOT)


@pytest.mark.parametrize(
    "metadata_mutation",
    [
        lambda value: value.replace(b"Name: jpl-debias-2018", b"Name: forged"),
        lambda value: value.replace(b"Version: 2023.3.1.1", b"Version: 9.9.9"),
        lambda value: value.replace(
            b"Requires-Python: >=3.11",
            b"Requires-Python: >=3.11\nRequires-Dist: requests",
        ),
        lambda value: value.replace(
            b"Description-Content-Type: text/markdown",
            b"Description-Content-Type: text/markdown\nLicense-Expression: MIT",
        ),
        lambda value: value + b"forged description",
    ],
)
def test_wheel_rejects_metadata_mutations(metadata_mutation: object) -> None:
    members = _wheel_members()
    path = f"{verifier.DIST_INFO}/METADATA"
    mutate = metadata_mutation
    assert callable(mutate)
    members[path] = mutate(members[path])
    with pytest.raises(verifier.VerificationError):
        verifier._validate_wheel_members(members, ROOT)


def test_wheel_rejects_stale_record() -> None:
    members = _wheel_members()
    members[f"{verifier.DIST_INFO}/RECORD"] += b"forged,,\n"
    with pytest.raises(verifier.VerificationError, match="RECORD"):
        verifier._validate_wheel_members(members, ROOT)


def test_wheel_rejects_unexpected_member() -> None:
    members = _wheel_members()
    members["unexpected"] = b"x"
    with pytest.raises(verifier.VerificationError, match="member set"):
        verifier._validate_wheel_members(members, ROOT)


def test_semantic_manifest_validation_rejects_stale_data_identity() -> None:
    manifest = (
        (ROOT / verifier.DATA_MANIFEST_PATH)
        .read_bytes()
        .replace(verifier.BIAS_SHA256.encode(), b"0" * 64, 1)
    )
    with pytest.raises(verifier.VerificationError, match="archive member inventory"):
        verifier._validate_data_manifest_bytes(
            manifest,
            (ROOT / verifier.BIAS_PATH).read_bytes(),
            (ROOT / verifier.UPSTREAM_README_PATH).read_bytes(),
        )


def test_valid_sdist_contract() -> None:
    verifier._validate_sdist_members(_sdist_members(), ROOT)


def test_sdist_rejects_manifest_and_inventory_mutations() -> None:
    for path in (verifier.DATA_MANIFEST_PATH, verifier.INVENTORY_PATH):
        members = _sdist_members()
        members[path] = b"{}\n"
        with pytest.raises(verifier.VerificationError):
            verifier._validate_sdist_members(members, ROOT)


def test_sdist_rejects_uninventoried_member() -> None:
    members = _sdist_members()
    members["hidden-payload"] = b"x"
    with pytest.raises(verifier.VerificationError, match="member set"):
        verifier._validate_sdist_members(members, ROOT)
