from __future__ import annotations

import copy
import gzip
import io
import json
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from tools import verify_artifacts as verifier

ROOT = Path(__file__).parents[1]


def _wheel_members() -> dict[str, bytes]:
    members = {
        wheel_name: (ROOT / source).read_bytes()
        for source, wheel_name in verifier.PACKAGE_SOURCE_TO_WHEEL.items()
    }
    prefix = verifier.DIST_INFO
    members[f"{prefix}/licenses/LICENSE"] = (ROOT / "LICENSE").read_bytes()
    members[f"{prefix}/licenses/NOTICE"] = (ROOT / "NOTICE").read_bytes()
    members[f"{prefix}/METADATA"] = verifier._expected_metadata_bytes(ROOT)
    members[f"{prefix}/WHEEL"] = verifier.EXPECTED_WHEEL_BYTES
    members[f"{prefix}/top_level.txt"] = b"jpl_debias_2018\n"
    record_path = f"{prefix}/RECORD"
    members[record_path] = b""
    members[record_path] = verifier._canonical_record(members, record_path)
    return members


def _rehash_record(members: dict[str, bytes]) -> None:
    record_path = f"{verifier.DIST_INFO}/RECORD"
    members[record_path] = b""
    members[record_path] = verifier._canonical_record(members, record_path)


def _sdist_members() -> dict[str, bytes]:
    return verifier._expected_sdist_members(ROOT)


def _mutate(members: dict[str, bytes], path: str, replacement: bytes) -> dict[str, bytes]:
    mutated = members.copy()
    mutated[path] = replacement
    return mutated


def _write_canonical_wheel(directory: Path, members: dict[str, bytes]) -> Path:
    path = directory / verifier.WHEEL_NAME
    path.write_bytes(verifier._canonical_wheel_bytes(members))
    return path


def _write_sdist_with_extra_directory(directory: Path) -> Path:
    relative = _sdist_members()
    full = {f"{verifier.SDIST_ROOT}/{name}": contents for name, contents in relative.items()}
    modes = verifier._expected_sdist_file_modes(ROOT, set(relative))
    path = directory / verifier.SDIST_NAME
    with (
        path.open("wb") as raw,
        gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=verifier.BUILD_EPOCH
        ) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as archive,
    ):
        names = (
            verifier._directory_names(list(full))
            | set(full)
            | {f"{verifier.SDIST_ROOT}/unapproved-empty"}
        )
        for name in sorted(names):
            info = tarfile.TarInfo(name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = verifier.BUILD_EPOCH
            if name not in full:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                archive.addfile(info)
            else:
                contents = full[name]
                info.type = tarfile.REGTYPE
                info.mode = modes[name]
                info.size = len(contents)
                archive.addfile(info, io.BytesIO(contents))
    return path


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
    "mutation",
    [
        lambda value: value.replace(b"Name: jpl-debias-2018", b"Name: forged"),
        lambda value: value.replace(b"License-Expression: MIT", b"License-Expression: GPL-3.0"),
        lambda value: value.replace(
            b"License-Expression: MIT", b"License-Expression: MIT\nLicense-Expression: MIT"
        ),
        lambda value: value.replace(
            b"Keywords: astronomy,astrometry,asteroids,catalog,debiasing,JPL",
            b"Keywords: FORGED-UNATTESTED",
        ),
        lambda value: value.replace(
            b"Keywords: astronomy,astrometry,asteroids,catalog,debiasing,JPL",
            b"Keywords: astronomy,astrometry,asteroids,catalog,debiasing,JPL\nX-Forged: yes",
        ),
        lambda value: value.replace(
            b"Keywords: astronomy,astrometry,asteroids,catalog,debiasing,JPL",
            b"Keywords: astronomy,astrometry,asteroids,catalog,debiasing,JPL\nKeywords: duplicate",
        ),
        lambda value: value.replace(b"Dynamic: license-file", b"Dynamic: other"),
        lambda value: value + b"forged description",
    ],
)
def test_wheel_rejects_complete_metadata_mutations(mutation: Callable[[bytes], bytes]) -> None:
    members = _wheel_members()
    path = f"{verifier.DIST_INFO}/METADATA"
    members[path] = mutation(members[path])
    _rehash_record(members)
    with pytest.raises(verifier.VerificationError, match="metadata"):
        verifier._validate_wheel_members(members, ROOT)


def test_record_rehashed_keywords_wheel_is_rejected(tmp_path: Path) -> None:
    members = _wheel_members()
    metadata_path = f"{verifier.DIST_INFO}/METADATA"
    members[metadata_path] = members[metadata_path].replace(
        b"Keywords: astronomy,astrometry,asteroids,catalog,debiasing,JPL",
        b"Keywords: FORGED-UNATTESTED",
    )
    _rehash_record(members)
    wheel = _write_canonical_wheel(tmp_path, members)
    with pytest.raises(verifier.VerificationError, match="metadata"):
        verifier.verify_wheel(wheel, ROOT)


def test_wheel_rejects_noncanonical_container_and_filename(tmp_path: Path) -> None:
    members = _wheel_members()
    noncanonical = tmp_path / verifier.WHEEL_NAME
    with zipfile.ZipFile(noncanonical, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in reversed(list(members)):
            archive.writestr(name, members[name])
    with pytest.raises(verifier.VerificationError, match="canonical ZIP"):
        verifier.verify_wheel(noncanonical, ROOT)

    renamed = tmp_path / "renamed.whl"
    renamed.write_bytes(verifier._canonical_wheel_bytes(members))
    with pytest.raises(verifier.VerificationError, match="filename"):
        verifier.verify_wheel(renamed, ROOT)


def test_valid_sdist_contract() -> None:
    verifier._validate_sdist_members(_sdist_members(), ROOT)


@pytest.mark.parametrize(
    ("path", "mutation"),
    [
        (f"{verifier.EGG_INFO}/requires.txt", lambda value: value + b"requests\n"),
        (
            f"{verifier.EGG_INFO}/SOURCES.txt",
            lambda value: value + b"\ntools/verify_artifacts.py",
        ),
        (
            "PKG-INFO",
            lambda value: value.replace(
                b"Keywords: astronomy,astrometry,asteroids,catalog,debiasing,JPL",
                b"Keywords: FORGED-UNATTESTED",
            ),
        ),
        (
            f"{verifier.EGG_INFO}/PKG-INFO",
            lambda value: value.replace(b"License-Expression: MIT", b"License-Expression: GPL-3.0"),
        ),
        (
            f"{verifier.EGG_INFO}/PKG-INFO",
            lambda value: value.replace(
                b"Dynamic: license-file", b"Dynamic: license-file\nX-Forged: yes"
            ),
        ),
    ],
)
def test_sdist_rejects_exact_generated_file_mutations(
    path: str, mutation: Callable[[bytes], bytes]
) -> None:
    members = _sdist_members()
    members[path] = mutation(members[path])
    with pytest.raises(verifier.VerificationError, match="exact contract"):
        verifier._validate_sdist_members(members, ROOT)


def test_sdist_rejects_extra_directory(tmp_path: Path) -> None:
    path = _write_sdist_with_extra_directory(tmp_path)
    with pytest.raises(verifier.VerificationError, match="directory set"):
        verifier.verify_sdist(path, ROOT)


def test_sdist_rejects_noncanonical_metadata(tmp_path: Path) -> None:
    relative = _sdist_members()
    full = {f"{verifier.SDIST_ROOT}/{name}": contents for name, contents in relative.items()}
    modes = verifier._expected_sdist_file_modes(ROOT, set(relative))
    first = next(name for name in sorted(full) if name.endswith(".py"))
    modes[first] = 0o777
    path = tmp_path / verifier.SDIST_NAME
    path.write_bytes(verifier._canonical_sdist_bytes(full, modes))
    with pytest.raises(verifier.VerificationError, match="canonical tar/gzip"):
        verifier.verify_sdist(path, ROOT)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["resources"]["bias.dat"].update(line_count=1),
        lambda value: value["resources"]["bias.dat"].update(bias_version_date="1900-01-01"),
        lambda value: value["resources"]["bias.dat"].update(catalog_codes=["x"]),
        lambda value: value["redistribution"].update(status="blocked"),
        lambda value: value["redistribution"].update(public_redistribution_authorized=False),
        lambda value: value["redistribution"].update(data_license="forged"),
        lambda value: value["redistribution"].update(authorization_reference="forged"),
        lambda value: value["redistribution"].update(reason="forged"),
        lambda value: value["redistribution"].update(code_and_documentation_license="forged"),
        lambda value: value.update(unexpected=True),
    ],
)
def test_manifest_rejects_every_reported_semantic_survivor(
    mutation: Callable[[dict[str, object]], None],
) -> None:
    manifest = copy.deepcopy(verifier.EXPECTED_DATA_MANIFEST)
    mutation(manifest)
    contents = (json.dumps(manifest, indent=2) + "\n").encode()
    with pytest.raises(verifier.VerificationError, match="schema/value"):
        verifier._validate_data_manifest_bytes(
            contents,
            (ROOT / verifier.BIAS_PATH).read_bytes(),
            (ROOT / verifier.UPSTREAM_README_PATH).read_bytes(),
        )


def test_release_artifact_set_is_exact(tmp_path: Path) -> None:
    wheel = _write_canonical_wheel(tmp_path, _wheel_members())
    with pytest.raises(verifier.VerificationError, match="artifact set"):
        verifier.verify_artifacts([wheel], ROOT)


def test_sdist_rejects_renamed_artifact_before_parsing(tmp_path: Path) -> None:
    renamed = tmp_path / "renamed.tar.gz"
    renamed.write_bytes(b"not-an-archive")
    with pytest.raises(verifier.VerificationError, match="filename"):
        verifier.verify_sdist(renamed, ROOT)
