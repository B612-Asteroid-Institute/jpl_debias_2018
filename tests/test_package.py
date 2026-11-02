from __future__ import annotations

import hashlib
import json
import tomllib
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
    source = manifest["source"]
    assert source["url"] == data.SOURCE_URL
    assert source["archive_name"] == "debias_2018.tgz"
    assert source["archive_size_bytes"] == data.SOURCE_ARCHIVE_SIZE_BYTES
    assert source["archive_sha256"] == data.SOURCE_ARCHIVE_SHA256
    assert source["http_last_modified"] == data.SOURCE_ARCHIVE_LAST_MODIFIED
    assert source["archive_members"]["bias.dat"]["sha256"] == data.BIAS_DAT_SHA256
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


def test_redistribution_and_distribution_license_are_explicit() -> None:
    redistribution = _manifest()["redistribution"]
    assert redistribution["status"] == "authorized"
    assert redistribution["public_redistribution_authorized"] is True
    assert redistribution["data_license"] is None
    assert redistribution["authorization_reference"] == (
        "Asteroid Institute distribution approval, 2026-10-26"
    )
    assert redistribution["code_and_documentation_license"] == "MIT"

    distribution = metadata.distribution("jpl-debias-2018")
    assert distribution.metadata.get_all("License") is None
    assert distribution.metadata.get_all("License-Expression") == ["MIT"]
    assert set(distribution.metadata.get_all("License-File") or []) == {"LICENSE", "NOTICE"}


def test_public_mirror_language_attribution_and_ci_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    notice = (root / "NOTICE").read_text(encoding="utf-8")
    workflow = (root / ".github/workflows/build_test.yml").read_text(encoding="utf-8")
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    license_expression = pyproject["project"]["license"]
    assert license_expression == "MIT"
    assert (
        f'assert distribution.metadata.get("License-Expression") == "{license_expression}"'
        in workflow
    )
    assert 'distribution.metadata.get("License-Expression") is None' not in workflow

    policy_paths = [
        root / "README.md",
        root / "LICENSE",
        root / "NOTICE",
        root / "pyproject.toml",
        root / "src/jpl_debias_2018/SOURCE_MANIFEST.json",
        root / "tools/refresh_data.py",
        root / "tools/verify_artifacts.py",
        *sorted((root / ".github").rglob("*.yml")),
        *sorted((root / ".github").rglob("*.yaml")),
    ]
    policy_text = "\n".join(path.read_text(encoding="utf-8") for path in policy_paths)
    assert "PUBLIC REDISTRIBUTION IS BLOCKED" not in policy_text
    assert "PUBLIC REDISTRIBUTION BLOCKED" not in policy_text
    assert "redistribution authorization is present" not in policy_text
    assert "This is not an official JPL package" in readme
    assert "installable via `pip`" in readme
    acknowledgment = (
        "data provided and maintained by the NASA Jet\n"
        "Propulsion Laboratory, California Institute of Technology"
    )
    assert acknowledgment in readme
    assert acknowledgment in notice
    assert "does not claim Institute\nauthorship" in notice


def test_ci_uses_standard_build_test_and_trusted_publish_workflows() -> None:
    root = Path(__file__).resolve().parents[1]
    build_test = (root / ".github/workflows/build_test.yml").read_text(encoding="utf-8")
    publish = (root / ".github/workflows/build_test_publish.yml").read_text(encoding="utf-8")

    assert "pull_request:" in build_test
    assert "push:" in build_test
    assert "workflow_call:" in build_test
    assert "python tools/check_reproducible_builds.py" in build_test
    assert "python tools/build_release.py" in build_test
    assert "python tools/verify_artifacts.py" in build_test

    assert "workflow_dispatch:" in publish
    assert "workflow_call:" in publish
    assert "uses: ./.github/workflows/build_test.yml" in publish
    assert "id-token: write" in publish
    assert "environment: pypi" in publish
    assert "pypa/gh-action-pypi-publish@" in publish
    assert "packages-dir: dist/" in publish
    assert "tools/build_release.py" not in publish
    assert "curl " not in publish
    assert "wget " not in publish
