from __future__ import annotations

import hashlib
import json
from importlib import metadata, resources
from pathlib import Path
from typing import Any

import jpl_debias_2018 as data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest() -> dict[str, Any]:
    resource = resources.files("jpl_debias_2018").joinpath("SOURCE_MANIFEST.json")
    return json.loads(resource.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_public_path_is_absolute_real_file() -> None:
    path = Path(data.bias_dat)
    assert path.is_absolute()
    assert path.is_file()
    assert path.name == "bias.dat"
    assert path.parent.name == "jpl_debias_2018"


def test_bias_dat_has_exact_immutable_identity() -> None:
    path = Path(data.bias_dat)
    assert path.stat().st_size == data.BIAS_DAT_SIZE_BYTES == 37_161_151
    assert _sha256(path) == data.BIAS_DAT_SHA256


def test_bias_dat_header_and_shape() -> None:
    lines = Path(data.bias_dat).read_text(encoding="ascii").splitlines()
    assert len(lines) == 49_175
    assert lines[0] == "! BIAS_VERSION= 3.0 (September 21, 2018)"
    assert lines[1] == "! NSIDE= 64 "
    assert lines[2] == "! NPIX= 49152 "
    assert lines[4] == "! a b c d e g i j l m n o p q r t u v w L N Q R S U Y"
    numeric_rows = [line for line in lines if line and not line.startswith("!")]
    assert len(numeric_rows) == data.NPIX
    assert len(numeric_rows[0].split()) == len(data.CATALOG_CODES) * 4
    assert len(numeric_rows[-1].split()) == len(data.CATALOG_CODES) * 4


def test_manifest_agrees_with_public_constants_and_files() -> None:
    manifest = _manifest()
    assert manifest["schema_version"] == 1
    assert manifest["package_version"] == data.__version__
    assert manifest["source"] == {
        "url": data.SOURCE_URL,
        "archive_name": "debias_2018.tgz",
        "archive_size_bytes": data.SOURCE_ARCHIVE_SIZE_BYTES,
        "archive_sha256": data.SOURCE_ARCHIVE_SHA256,
        "http_last_modified": data.SOURCE_ARCHIVE_LAST_MODIFIED,
    }
    bias = manifest["resources"]["bias.dat"]
    assert bias["sha256"] == data.BIAS_DAT_SHA256
    assert bias["size_bytes"] == data.BIAS_DAT_SIZE_BYTES
    assert bias["bias_version"] == data.BIAS_VERSION
    assert bias["nside"] == data.NSIDE
    assert bias["npix"] == data.NPIX
    assert tuple(bias["catalog_codes"]) == data.CATALOG_CODES


def test_upstream_readme_identity() -> None:
    resource = resources.files("jpl_debias_2018").joinpath("UPSTREAM_README.txt")
    assert resource.is_file()
    contents = resource.read_bytes()
    assert len(contents) == 1_606
    assert hashlib.sha256(contents).hexdigest() == (
        "946823b4ca7b7a9f79a3feff3410f587ed1dd2662f5296ee379980ec3f759dec"
    )
    assert b"UPDATE, March 1, 2023" in contents


def test_distribution_has_no_runtime_dependencies() -> None:
    distribution = metadata.distribution("jpl-debias-2018")
    requirements = distribution.requires or []
    assert all("extra ==" in requirement for requirement in requirements)
    assert metadata.version("jpl-debias-2018") == data.__version__
