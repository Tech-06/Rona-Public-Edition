"""Hardening of toolbox.sources: catalog entry validation, https/size/digest
checks for tarballs, git commit/ref pins and the tar extraction fallback.

Offline like test_sources.py (local git repos, a loopback HTTP server); the
fixtures are shared with that module.
"""

import dataclasses
import functools
import hashlib
import http.server
import io
import json
import shutil
import tarfile
import threading

import pytest
from test_sources import _git, _write_sample_catalog, git_repo  # noqa: F401

from toolbox import sources
from toolbox.sources import (
    GitSource,
    HttpsTarballSource,
    SourceError,
    _parse_index,
    _safe_extract,
    parse_source,
)

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _index(**entry):
    entry.setdefault("id", "sample_tool")
    return json.dumps({"catalog_version": 2, "packages": [entry]})


# ---------------------------------------------------------------------------
# Catalog entry validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "/etc/passwd",
        "C:/Windows",
        "C:\\Windows",
        "../x",
        "a/../../b",
        "a/..",
        "a\\b",
        "a//b",
        "a/",
        "./a",
        "",
        "\\\\server\\share",
    ],
)
def test_index_rejects_unsafe_entry_path(bad_path):
    with pytest.raises(SourceError, match="invalid path"):
        _parse_index(_index(path=bad_path), origin="t")


def test_index_accepts_normal_nested_path():
    entry = _parse_index(_index(path="packages/group/sample_tool"), origin="t")[0]
    assert entry.path == "packages/group/sample_tool"


@pytest.mark.parametrize("bad_id", ["Bad-Id", "../x", "x/y", "1abc", "", "a b", 5, None])
def test_index_rejects_bad_entry_id(bad_id):
    with pytest.raises(SourceError, match="invalid package id"):
        _parse_index(_index(id=bad_id), origin="t")


@pytest.mark.parametrize("field,value", [("commit", "abc123"), ("sha256", "zz" * 32)])
def test_index_rejects_malformed_pins(field, value):
    with pytest.raises(SourceError, match=field):
        _parse_index(_index(**{field: value}), origin="t")


def test_index_reads_pins_lowercased():
    entry = _parse_index(_index(commit="A" * 40, sha256="B" * 64), origin="t")[0]
    assert entry.commit == "a" * 40
    assert entry.sha256 == "b" * 64


# ---------------------------------------------------------------------------
# https tarball source: scheme, digest, size
# ---------------------------------------------------------------------------


def test_http_non_loopback_rejected():
    with pytest.raises(SourceError, match="non-https"):
        HttpsTarballSource("http://example.com/catalog")


def test_parse_source_rejects_plain_http_non_loopback():
    with pytest.raises(SourceError, match="non-https"):
        parse_source("https:http://example.com/catalog")
    with pytest.raises(SourceError):
        parse_source("https:ftp://example.com/catalog")


def test_http_loopback_allowed():
    for host in ("127.0.0.1:8000", "localhost:8000", "[::1]:8000"):
        HttpsTarballSource(f"http://{host}/catalog")


@pytest.fixture
def served(tmp_path):
    """Serve a sample catalog (+ tarball) from loopback; yields (url, archive)."""
    served_dir = tmp_path / "served"
    pkg_dir = _write_sample_catalog(served_dir)
    archive_path = served_dir / "packages" / "sample_tool.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(pkg_dir, arcname=".")
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(served_dir)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", archive_path
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_sha256_match_installs(served, tmp_path):
    url, archive = served
    source = HttpsTarballSource(url)
    entry = dataclasses.replace(
        source.find_entry("sample_tool"),
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    dest = tmp_path / "out" / "sample_tool"
    source.fetch_package(entry, dest)
    assert (dest / "manifest.json").is_file()


def test_sha256_mismatch_fails_before_extracting(served, tmp_path, monkeypatch):
    url, _ = served
    source = HttpsTarballSource(url)
    entry = dataclasses.replace(source.find_entry("sample_tool"), sha256="0" * 64)

    def boom(*a, **k):
        raise AssertionError("archive must not be opened on a digest mismatch")

    monkeypatch.setattr(sources, "_safe_extract", boom)
    dest = tmp_path / "out" / "sample_tool"
    with pytest.raises(SourceError, match="sha256 mismatch"):
        source.fetch_package(entry, dest)
    assert not dest.exists()


def test_oversized_download_aborted(served, tmp_path, monkeypatch):
    url, _ = served
    source = HttpsTarballSource(url)
    entry = source.find_entry("sample_tool")
    monkeypatch.setattr(sources, "_MAX_DOWNLOAD_BYTES", 64)
    with pytest.raises(SourceError, match="exceeds"):
        source.fetch_package(entry, tmp_path / "out" / "sample_tool")


def test_corrupt_archive_is_a_source_error(served, tmp_path):
    url, archive = served
    archive.write_bytes(b"not a tarball")
    source = HttpsTarballSource(url)
    with pytest.raises(SourceError, match="unusable archive"):
        source.fetch_package(source.find_entry("sample_tool"), tmp_path / "out" / "x")


# ---------------------------------------------------------------------------
# git: commit pins and ref pins
# ---------------------------------------------------------------------------


def _commit(repo, message):
    _git(
        ["-c", "user.name=t", "-c", "user.email=t@example.com", "add", "-A"], cwd=repo
    )
    _git(
        ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-m", message],
        cwd=repo,
    )
    import subprocess

    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def two_commits(git_repo):  # noqa: F811
    import subprocess

    first = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    (git_repo / "packages" / "sample_tool" / "v2_marker.txt").write_text("v2")
    second = _commit(git_repo, "second")
    return git_repo, first, second


@needs_git
def test_git_entry_commit_pin_checks_out_that_commit(two_commits, tmp_path):
    repo, first, second = two_commits
    source = GitSource(str(repo), ref="main")
    entry = dataclasses.replace(source.find_entry("sample_tool"), commit=first)
    dest = tmp_path / "out" / "sample_tool"
    source.fetch_package(entry, dest)
    assert (dest / "manifest.json").is_file()
    assert not (dest / "v2_marker.txt").exists()

    # Unpinned still means latest main.
    latest = tmp_path / "out" / "latest"
    source.fetch_package(source.find_entry("sample_tool"), latest)
    assert (latest / "v2_marker.txt").is_file()


@needs_git
def test_git_entry_wrong_commit_fails(two_commits, tmp_path):
    repo, _, _ = two_commits
    source = GitSource(str(repo), ref="main")
    entry = dataclasses.replace(source.find_entry("sample_tool"), commit="a" * 40)
    with pytest.raises(SourceError):
        source.fetch_package(entry, tmp_path / "out" / "sample_tool")


@needs_git
def test_git_source_pinned_to_sha(two_commits, tmp_path):
    repo, first, _ = two_commits
    source = GitSource(str(repo), ref=first)
    entry = source.find_entry("sample_tool")
    dest = tmp_path / "out" / "sample_tool"
    source.fetch_package(entry, dest)
    assert not (dest / "v2_marker.txt").exists()


@needs_git
def test_git_source_pinned_to_tag(two_commits, tmp_path):
    repo, first, _ = two_commits
    _git(["tag", "v1", first], cwd=repo)
    source = GitSource(str(repo), ref="v1")
    dest = tmp_path / "out" / "sample_tool"
    source.fetch_package(source.find_entry("sample_tool"), dest)
    assert not (dest / "v2_marker.txt").exists()


def test_parse_source_at_ref_forms():
    sha = "c" * 40
    src = parse_source(f"github:Tech-06/Rona-Tools@{sha}")
    assert isinstance(src, GitSource)
    assert src.url == "https://github.com/Tech-06/Rona-Tools.git"
    assert src.ref == sha

    assert parse_source("github:Tech-06/Rona-Tools").ref == "main"

    src = parse_source("git:https://example.com/r.git@v1.2")
    assert (src.url, src.ref) == ("https://example.com/r.git", "v1.2")

    src = parse_source(f"git:https://example.com/r.git#{sha}")
    assert (src.url, src.ref) == ("https://example.com/r.git", sha)

    # scp-style URLs and userinfo are not mistaken for an @ref.
    src = parse_source("git:git@github.com:Tech-06/Rona-Tools.git")
    assert (src.url, src.ref) == ("git@github.com:Tech-06/Rona-Tools.git", "main")
    src = parse_source("git:https://user@example.com/r.git")
    assert (src.url, src.ref) == ("https://user@example.com/r.git", "main")


def test_parse_source_rejects_bad_github_and_option_like_refs():
    with pytest.raises(SourceError):
        parse_source("github:not-a-repo")
    with pytest.raises(SourceError):
        parse_source("git:--upload-pack=evil")
    with pytest.raises(SourceError):
        parse_source("git:https://example.com/r.git#--evil")


# ---------------------------------------------------------------------------
# tar extraction fallback (interpreters without tarfile.data_filter)
# ---------------------------------------------------------------------------


def _archive(tmp_path, members):
    """members: list of (TarInfo, bytes|None)."""
    path = tmp_path / "a.tar"
    with tarfile.open(path, "w") as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return path


def _file(name, data=b"x", mode=0o644):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    return info, data


def _special(name, type_, linkname=""):
    info = tarfile.TarInfo(name)
    info.type = type_
    info.linkname = linkname
    return info, None


@pytest.fixture
def no_data_filter(monkeypatch):
    monkeypatch.delattr(tarfile, "data_filter", raising=False)
    assert not hasattr(tarfile, "data_filter")
    # Newer interpreters' extractall() looks the missing name up as its default
    # filter; an old interpreter has no filter machinery at all, which is the
    # situation being simulated, so give extractall() a neutral default.
    if hasattr(tarfile.TarFile, "extraction_filter"):
        monkeypatch.setattr(
            tarfile.TarFile, "extraction_filter", staticmethod(tarfile.fully_trusted_filter)
        )


@pytest.mark.parametrize(
    "member",
    [
        _special("link", tarfile.SYMTYPE, "/etc/passwd"),
        _special("hard", tarfile.LNKTYPE, "other"),
        _special("dev", tarfile.CHRTYPE),
        _special("blk", tarfile.BLKTYPE),
        _special("fifo", tarfile.FIFOTYPE),
        _file("/abs/evil.txt"),
        _file("../evil.txt"),
        _file("ok/../../evil.txt"),
        _file("C:/evil.txt"),
    ],
    ids=["symlink", "hardlink", "chr", "blk", "fifo", "absolute", "dotdot", "nested", "drive"],
)
def test_fallback_rejects_unsafe_member(no_data_filter, tmp_path, member):
    archive = _archive(tmp_path, [_file("good.txt"), member])
    dest = tmp_path / "dest"
    dest.mkdir()
    with tarfile.open(archive) as tar, pytest.raises(SourceError):
        _safe_extract(tar, dest)
    assert not (tmp_path / "evil.txt").exists()


def test_fallback_extracts_normal_archive_and_strips_setid(no_data_filter, tmp_path):
    archive = _archive(
        tmp_path,
        [
            _special("pkg", tarfile.DIRTYPE),
            _file("pkg/manifest.json", b"{}", mode=0o6755),
        ],
    )
    dest = tmp_path / "dest"
    dest.mkdir()
    with tarfile.open(archive) as tar:
        _safe_extract(tar, dest)
    target = dest / "pkg" / "manifest.json"
    assert target.read_bytes() == b"{}"
    if hasattr(target.stat(), "st_mode"):
        assert target.stat().st_mode & 0o6000 == 0


def test_data_filter_path_still_used_when_available(tmp_path):
    if not hasattr(tarfile, "data_filter"):
        pytest.skip("interpreter has no data filter")
    archive = _archive(tmp_path, [_file("../evil.txt")])
    dest = tmp_path / "dest"
    dest.mkdir()
    with tarfile.open(archive) as tar, pytest.raises(tarfile.TarError):
        _safe_extract(tar, dest)


def test_entry_path_starting_with_dash_is_rejected():
    for bad in ("-rf", "--no-cone/pkg"):
        with pytest.raises(SourceError, match="'-'"):
            sources._validate_entry_path(bad, origin="o", pkg_id="p")
    assert sources._validate_entry_path("packages/-ok", origin="o", pkg_id="p")


def test_sparse_checkout_set_separates_paths_with_double_dash(git_repo, tmp_path, monkeypatch):  # noqa: F811
    calls = []
    real = GitSource._run

    def spy(self, args, cwd=None):
        calls.append(list(args))
        return real(self, args, cwd=cwd)

    monkeypatch.setattr(GitSource, "_run", spy)
    GitSource(url=str(git_repo), ref="main")._sparse_clone(tmp_path / "clone", ["packages"])
    setcall = next(c for c in calls if c[:3] == ["git", "sparse-checkout", "set"])
    assert setcall[3] == "--"
