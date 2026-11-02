"""Installed paths and immutable identity for the JPL EFCC18 debias table.

Importing this module performs no network access and does not hash the bundled
file. ``bias_dat`` is an absolute filesystem path from an unpacked wheel or
source installation, ready to pass to a native Python extension or standalone
Rust process.
"""

from importlib.resources import files
from pathlib import Path
from typing import Final

__version__: Final = "2023.3.1.1"

SOURCE_URL: Final = "https://ssd.jpl.nasa.gov/ftp/ssd/debias/debias_2018.tgz"
SOURCE_ARCHIVE_SHA256: Final = "288132cefea7f1bdf0989782db1173948dd7dfef7da31910be90b16b73cfea6c"
SOURCE_ARCHIVE_SIZE_BYTES: Final = 9_852_628
SOURCE_ARCHIVE_LAST_MODIFIED: Final = "2023-03-01T22:24:39Z"

BIAS_VERSION: Final = "3.0"
BIAS_VERSION_DATE: Final = "2018-09-21"
ARCHIVE_UPDATE_DATE: Final = "2023-03-01"
BIAS_DAT_SHA256: Final = "ef6a50830bb83d8b1161e7acb391eed988ea9708e9fbcccc0c834da6109476e3"
BIAS_DAT_SIZE_BYTES: Final = 37_161_151
NSIDE: Final = 64
NPIX: Final = 49_152
CATALOG_CODES: Final = (
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
)

_resource = files(__package__).joinpath("bias.dat")
if not isinstance(_resource, Path):
    raise RuntimeError(
        "jpl_debias_2018 must be installed as an unpacked wheel or filesystem package "
        "before bias.dat can be passed to native code"
    )
if not _resource.is_file():
    raise RuntimeError(f"packaged JPL EFCC18 data is missing: {_resource}")

# Lower-case name intentionally matches the established Institute kernel-data
# package API (for example, ``naif_de440.de440``).
bias_dat: Final[str] = str(_resource.resolve())

__all__ = [
    "ARCHIVE_UPDATE_DATE",
    "BIAS_DAT_SHA256",
    "BIAS_DAT_SIZE_BYTES",
    "BIAS_VERSION",
    "BIAS_VERSION_DATE",
    "CATALOG_CODES",
    "NPIX",
    "NSIDE",
    "SOURCE_ARCHIVE_LAST_MODIFIED",
    "SOURCE_ARCHIVE_SHA256",
    "SOURCE_ARCHIVE_SIZE_BYTES",
    "SOURCE_URL",
    "__version__",
    "bias_dat",
]
