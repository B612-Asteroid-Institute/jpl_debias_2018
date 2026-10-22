# jpl-debias-2018

> [!CAUTION]
> **PUBLIC REDISTRIBUTION IS BLOCKED.** The JPL archive contains no explicit
> license, and this repository contains no applicable JPL/Caltech authorization
> to reproduce or publicly redistribute the exact bundled data bytes. Do not
> push this candidate to a public source repository, publish it to PyPI, upload
> release artifacts, or create a public release until explicit authorization
> has been obtained and reviewed. See [`NOTICE`](NOTICE).

`jpl-debias-2018` is a data-only Python package containing the JPL Solar
System Dynamics EFCC18 astrometric catalog-debias table. It follows the same
installed-resource convention as the Asteroid Institute kernel packages:
import the package, then pass its exported filesystem path to the consumer.

The package contains no orbit-determination implementation, has no runtime
dependencies, performs no network access at import or runtime, and does not
recompute data identity at import. The candidate retains the table byte-for-byte as obtained from JPL; provenance
does not itself grant redistribution rights.

## Data identity

| Field | Value |
|---|---|
| Upstream archive | <https://ssd.jpl.nasa.gov/ftp/ssd/debias/debias_2018.tgz> |
| Archive SHA-256 | `288132cefea7f1bdf0989782db1173948dd7dfef7da31910be90b16b73cfea6c` |
| Archive size | 9,852,628 bytes |
| Archive last-modified | 2023-03-01 22:24:39 UTC |
| `bias.dat` SHA-256 | `ef6a50830bb83d8b1161e7acb391eed988ea9708e9fbcccc0c834da6109476e3` |
| `bias.dat` size | 37,161,151 bytes |
| Upstream `BIAS_VERSION` | 3.0 (2018-09-21) |
| Archive correction | 2023-03-01 catalog-code correction |
| HEALPix geometry | NSIDE 64, NPIX 49,152 |
| Catalogs | 26 |

The complete machine-readable record is packaged as
`jpl_debias_2018/SOURCE_MANIFEST.json`. The March 2023 upstream update corrected
the UCAC-5 catalog code in comments and headers from `W` to `Y`; the numerical
table is identified by the hash above.

## Installation

Only after applicable redistribution authorization is documented and a reviewed release is published:

```bash
python -m pip install jpl-debias-2018
```

Before publication, install a reviewed wheel directly:

```bash
python -m pip install ./jpl_debias_2018-2023.3.1.1-py3-none-any.whl
```

Pip installs wheels unpacked. Zip-importing this package is deliberately not
supported because a real filesystem path is part of the public contract.

## Python/native use

```python
import jpl_debias_2018

jpl_debias_2018.bias_dat
# '/.../site-packages/jpl_debias_2018/bias.dat'

native_od.load_efcc18_bias_dat(
    jpl_debias_2018.bias_dat,
    expected_sha256=jpl_debias_2018.BIAS_DAT_SHA256,
)
```

`bias_dat` is an absolute `str` path. It can be passed directly across PyO3,
C FFI, subprocess, or CLI boundaries just like `naif_de440.de440`.

## Standalone Rust use

The Rust implementation receives a path; it does not need to know about
Python packaging and must not import or discover Python packages. Deployment
can obtain the path from an installed wheel:

```bash
BIAS_DAT="$(python -c 'import jpl_debias_2018; print(jpl_debias_2018.bias_dat)')"
cargo run --release -- --efcc18-bias-dat "$BIAS_DAT"
```

Or unpack the wheel as a data artifact and pass the contained file without a
Python runtime:

```bash
python -m zipfile -e jpl_debias_2018-2023.3.1.1-py3-none-any.whl ./od-data
cargo run --release -- \
  --efcc18-bias-dat ./od-data/jpl_debias_2018/bias.dat \
  --efcc18-bias-sha256 ef6a50830bb83d8b1161e7acb391eed988ea9708e9fbcccc0c834da6109476e3
```

The Rust client should validate the expected SHA-256 at its data-ingress
boundary, then parse the file with Core's `Efcc18BiasTable::parse_bias_dat`.
It should not download the table during OD.

## What the table contains

For every one of 49,152 equal-area sky tiles and each of 26 MPC star-catalog
codes, the table supplies:

- RA cos(Dec) position correction at J2000, arcseconds;
- Dec position correction at J2000, arcseconds;
- RA cos(Dec) proper-motion correction, milliarcseconds/year;
- Dec proper-motion correction, milliarcseconds/year.

The upstream README is preserved unmodified in the wheel as
`UPSTREAM_README.txt`. It explains how the corrections are applied and cites
Eggl et al. (2020, *Icarus*) for the method.

## Reproducible maintenance

Normal builds use the committed immutable data and never contact JPL. To
verify a separately downloaded authority before copying it into the package:

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  -o /tmp/debias_2018.tgz \
  https://ssd.jpl.nasa.gov/ftp/ssd/debias/debias_2018.tgz
python tools/refresh_data.py --archive /tmp/debias_2018.tgz --check-only
```

To replace the packaged files with the already-verified known authority:

```bash
python tools/refresh_data.py --archive /tmp/debias_2018.tgz
```

`--download` is an explicit maintainer-only alternative. The script checks
the archive hash and all member hashes and sizes before writing anything. If
JPL changes the archive, it fails closed. Review the upstream changes first,
then deliberately update the expected manifest and tests in the same commit;
do not weaken or bypass the hash gate.

The release source has a checked exact inventory. After intentional source
changes, regenerate it, inspect the diff, and commit it with the change:

```bash
python tools/update_source_inventory.py
```

Official artifacts must be built from a clean commit through the deterministic
builder, never with a bare `python -m build` release command:

```bash
python tools/build_release.py
python tools/verify_artifacts.py dist/*.whl dist/*.tar.gz
python -m twine check dist/*
python tools/check_reproducible_builds.py
```

The final command clones the clean commit twice, builds independently, and
requires byte-identical wheel and sdist SHA-256 values. The builder pins the
backend, fixes `SOURCE_DATE_EPOCH`, canonicalizes ZIP and tar/gzip metadata,
validates every inventoried source and packaged identity file, and rejects
dirty source by default. The artifact verifier enforces the exact artifact
filenames, complete ordered metadata headers and values, generated egg-info
bytes, archive member and directory sets, and canonical container bytes. It
does not provide a weaker payload-only verification mode.

CI is pinned, read-only, artifact-only, and has no PyPI publisher credentials
or publication job. Because its artifacts contain the blocked data bytes, the
public repository and its workflows must not be initialized until applicable
redistribution authorization is documented.

## Licensing and attribution

There is deliberately **no distribution-wide license expression**. The MIT
terms in [`LICENSE`](LICENSE) apply only to Institute-authored packaging code
and documentation. They do not apply to or relicense `bias.dat` or the
upstream README. The JPL archive supplied no explicit license, and no
applicable redistribution authorization is present. [`NOTICE`](NOTICE) and
the packaged `SOURCE_MANIFEST.json` record this fail-closed status.
