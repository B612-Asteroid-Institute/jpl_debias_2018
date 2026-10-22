from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path
from typing import Any

import pytest

from tools import refresh_data


def _archive(entries: list[tuple[str, bytes, str]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, contents, kind in entries:
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            if kind == "file":
                archive.addfile(member, io.BytesIO(contents))
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = "elsewhere"
                member.size = 0
                archive.addfile(member)
            else:  # pragma: no cover - test helper contract
                raise AssertionError(kind)
    return output.getvalue()


def _contract(archive: bytes, members: dict[str, bytes]) -> refresh_data.ArchiveContract:
    return refresh_data.ArchiveContract(
        url="https://example.invalid/data.tgz",
        size=len(archive),
        sha256=hashlib.sha256(archive).hexdigest(),
        members={
            name: refresh_data.MemberSpec(
                size=len(contents),
                sha256=hashlib.sha256(contents).hexdigest(),
                installed_name=name,
            )
            for name, contents in members.items()
        },
    )


def test_validated_members_accepts_only_exact_regular_inventory() -> None:
    expected = {"a.dat": b"alpha", "b.txt": b"beta"}
    archive = _archive([(name, value, "file") for name, value in expected.items()])
    assert refresh_data._validated_members(archive, _contract(archive, expected)) == expected


@pytest.mark.parametrize("unsafe", ["../bias.dat", "/bias.dat", "a/../../bias.dat", "a\\bias.dat"])
def test_validated_members_rejects_unsafe_names(unsafe: str) -> None:
    expected = {unsafe: b"payload"}
    archive = _archive([(unsafe, b"payload", "file")])
    with pytest.raises(ValueError, match="unsafe"):
        refresh_data._validated_members(archive, _contract(archive, expected))


def test_validated_members_rejects_duplicate_names() -> None:
    archive = _archive([("bias.dat", b"first", "file"), ("bias.dat", b"second", "file")])
    contract = _contract(archive, {"bias.dat": b"second"})
    with pytest.raises(ValueError, match="duplicate"):
        refresh_data._validated_members(archive, contract)


def test_validated_members_rejects_links() -> None:
    archive = _archive([("bias.dat", b"", "symlink")])
    contract = _contract(archive, {"bias.dat": b""})
    with pytest.raises(ValueError, match="regular file"):
        refresh_data._validated_members(archive, contract)


def test_validated_members_rejects_missing_or_extra_members() -> None:
    archive = _archive([("bias.dat", b"value", "file"), ("extra", b"x", "file")])
    contract = _contract(archive, {"bias.dat": b"value"})
    with pytest.raises(ValueError, match="member set mismatch"):
        refresh_data._validated_members(archive, contract)


def test_validated_members_rejects_archive_hash_mutation() -> None:
    expected = {"bias.dat": b"value"}
    archive = _archive([("bias.dat", b"value", "file")])
    contract = _contract(archive, expected)
    mutated = archive[:-1] + bytes([archive[-1] ^ 1])
    with pytest.raises(ValueError, match="SHA-256"):
        refresh_data._validated_members(mutated, contract)


class RecordingBytesIO(io.BytesIO):
    requested: list[int]

    def __init__(self, contents: bytes) -> None:
        super().__init__(contents)
        self.requested = []

    def read(self, size: int | None = -1) -> bytes:
        requested = -1 if size is None else size
        self.requested.append(requested)
        return super().read(size)


def test_bounded_reader_requests_expected_size_plus_one() -> None:
    stream = RecordingBytesIO(b"1234")
    assert refresh_data._read_exactly_bounded(stream, 4, "test") == b"1234"
    assert stream.requested == [5]


@pytest.mark.parametrize("contents", [b"123", b"12345"])
def test_bounded_reader_rejects_short_and_excess(contents: bytes) -> None:
    with pytest.raises(ValueError, match="expected size"):
        refresh_data._read_exactly_bounded(io.BytesIO(contents), 4, "test")


class FakeResponse(RecordingBytesIO):
    def __init__(
        self,
        contents: bytes,
        *,
        url: str,
        content_length: str | None = None,
        status: int = 200,
    ) -> None:
        super().__init__(contents)
        self._url = url
        self.status = status
        self.headers: dict[str, str] = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def _download_contract(contents: bytes) -> refresh_data.ArchiveContract:
    return refresh_data.ArchiveContract(
        url="https://example.invalid/data.tgz",
        size=len(contents),
        sha256=hashlib.sha256(contents).hexdigest(),
        members={},
    )


def test_download_is_bounded_and_checks_declared_length(monkeypatch: pytest.MonkeyPatch) -> None:
    contents = b"authority"
    contract = _download_contract(contents)
    response = FakeResponse(
        contents,
        url=contract.url,
        content_length=str(len(contents)),
    )
    monkeypatch.setattr(refresh_data, "_urlopen", lambda *_a, **_kw: response)
    assert refresh_data._download(contract) == contents
    assert response.requested == [len(contents) + 1]


def test_download_rejects_excess_body_even_with_matching_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contents = b"authority"
    contract = _download_contract(contents)
    response = FakeResponse(
        contents + b"x",
        url=contract.url,
        content_length=str(len(contents)),
    )
    monkeypatch.setattr(refresh_data, "_urlopen", lambda *_a, **_kw: response)
    with pytest.raises(ValueError, match="exceeds"):
        refresh_data._download(contract)


def test_download_rejects_length_or_redirect_before_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contents = b"authority"
    contract = _download_contract(contents)
    bad_length = FakeResponse(contents, url=contract.url, content_length="999")
    monkeypatch.setattr(refresh_data, "_urlopen", lambda *_a, **_kw: bad_length)
    with pytest.raises(ValueError, match="Content-Length mismatch"):
        refresh_data._download(contract)
    assert bad_length.requested == []

    redirect = FakeResponse(contents, url="https://attacker.invalid/data.tgz")
    monkeypatch.setattr(refresh_data, "_urlopen", lambda *_a, **_kw: redirect)
    with pytest.raises(ValueError, match="redirected"):
        refresh_data._download(contract)
    assert redirect.requested == []


def test_atomic_refresh_writes_only_packaged_members(tmp_path: Path) -> None:
    archive = (Path(__file__).parents[1] / ".." / "upstream" / "debias_2018.tgz").resolve()
    if not archive.is_file():
        pytest.skip("retained upstream archive is outside a clean clone")
    members = refresh_data._validated_members(archive.read_bytes())
    for archive_name, spec in refresh_data.KNOWN_AUTHORITY.members.items():
        if spec.installed_name is not None:
            refresh_data._write_atomically(tmp_path / spec.installed_name, members[archive_name])
    assert {path.name for path in tmp_path.iterdir()} == {"bias.dat", "UPSTREAM_README.txt"}
