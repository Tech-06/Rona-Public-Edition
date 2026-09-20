"""Tests for toolbox.sources: parsing source specs and fetching a catalog
via each backend (local disk, git sparse-checkout, https tarball).

The git and https tests are fully offline: git is exercised against a
throwaway local repository (cloned over the filesystem, not the network),
and https is exercised against a `ThreadingHTTPServer` bound to localhost.
"""

import functools
import http.server
import json
import shutil
import subprocess
import tarfile
import threading
from pathlib import Path

import pytest

from toolbox.sources import (
    CatalogEntry,
    GitSource,
    HttpsTarballSource,
    LocalSource,
    SourceError,
    _parse_index,
    parse_source,
)

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary not available"
)


def _write_sample_catalog(root, package_id="sample_tool"):
    """Lay out a minimal catalog: index.json + packages/<id>/manifest.json."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.json").write_text(
        json.dumps(
            {
                "catalog_version": 1,
                "packages": [
                    {
                        "id": package_id,
                        "version": "0.1.0",
                        "name": "Sample Tool",
                        "description": "a fixture package",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    pkg_dir = root / "packages" / package_id
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "manifest.json").write_text(
        json.dumps({"id": package_id, "version": "0.1.0", "name": package_id}),
        encoding="utf-8",
    )
    (pkg_dir / "tools.json").write_text(json.dumps({"tools": []}), encoding="utf-8")
    (pkg_dir / f"{package_id}.py").write_text(
        f"def {package_id}():\n    return {{'success': True}}\n", encoding="utf-8"
    )
    return pkg_dir


# ---------------------------------------------------------------------------
# parse_source
# ---------------------------------------------------------------------------


def test_parse_local_source():
    source = parse_source("local:D:/some/catalog")
    assert isinstance(source, LocalSource)
    assert source.root == Path("D:/some/catalog")


def test_parse_git_source_default_ref():
    source = parse_source("git:https://example.com/repo.git")
    assert isinstance(source, GitSource)
    assert source.url == "https://example.com/repo.git"
    assert source.ref == "main"


def test_parse_git_source_explicit_ref():
    source = parse_source("git:https://example.com/repo.git#dev")
    assert isinstance(source, GitSource)
    assert source.url == "https://example.com/repo.git"
    assert source.ref == "dev"


def test_parse_https_source():
    source = parse_source("https:https://example.com/catalog")
    assert isinstance(source, HttpsTarballSource)
    assert source.base_url == "https://example.com/catalog"


def test_parse_unknown_scheme_raises():
    with pytest.raises(SourceError):
        parse_source("ftp:something")


def test_parse_missing_colon_raises():
    with pytest.raises(SourceError):
        parse_source("garbage")


# ---------------------------------------------------------------------------
# LocalSource
# ---------------------------------------------------------------------------


def test_local_source_fetch_index_and_package(tmp_path):
    catalog = tmp_path / "catalog"
    _write_sample_catalog(catalog)

    source = LocalSource(catalog)
    entries = source.fetch_index()
    assert len(entries) == 1
    assert entries[0] == CatalogEntry(
        id="sample_tool",
        version="0.1.0",
        name="Sample Tool",
        description="a fixture package",
        path="packages/sample_tool",
    )

    dest = tmp_path / "installed" / "sample_tool"
    source.fetch_package(entries[0], dest)
    assert (dest / "manifest.json").is_file()
    assert (dest / "sample_tool.py").is_file()


def test_local_source_missing_index_raises(tmp_path):
    source = LocalSource(tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    with pytest.raises(SourceError):
        source.fetch_index()


def test_find_entry_unknown_package_raises(tmp_path):
    catalog = tmp_path / "catalog"
    _write_sample_catalog(catalog)
    source = LocalSource(catalog)
    with pytest.raises(SourceError):
        source.find_entry("does_not_exist")


# ---------------------------------------------------------------------------
# GitSource (against a throwaway local repo, no network)
# ---------------------------------------------------------------------------


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    _write_sample_catalog(repo)
    _git(["init", "-b", "main"], cwd=repo)
    _git(["-c", "user.name=test", "-c", "user.email=test@example.com", "add", "-A"], cwd=repo)
    _git(
        ["-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "init"],
        cwd=repo,
    )
    return repo


def test_git_source_fetch_index(git_repo):
    source = GitSource(str(git_repo), ref="main")
    entries = source.fetch_index()
    assert len(entries) == 1
    assert entries[0].id == "sample_tool"


def test_git_source_fetch_package_only_sparse_checks_out_that_path(git_repo, tmp_path):
    source = GitSource(str(git_repo), ref="main")
    entry = source.find_entry("sample_tool")
    dest = tmp_path / "installed" / "sample_tool"
    source.fetch_package(entry, dest)
    assert (dest / "manifest.json").is_file()
    assert (dest / "sample_tool.py").is_file()


def test_git_source_bad_url_raises_source_error(tmp_path):
    source = GitSource(str(tmp_path / "does-not-exist"), ref="main")
    with pytest.raises(SourceError):
        source.fetch_index()


def test_git_source_missing_git_binary_raises(monkeypatch, git_repo):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    source = GitSource(str(git_repo), ref="main")

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SourceError, match="git is not installed"):
        source.fetch_index()


# ---------------------------------------------------------------------------
# HttpsTarballSource (against a local ThreadingHTTPServer, no network)
# ---------------------------------------------------------------------------


@pytest.fixture
def http_catalog_server(tmp_path):
    served_dir = tmp_path / "served"
    pkg_dir = _write_sample_catalog(served_dir)

    # Package archives are served as <path>.tar.gz next to the (unused, for
    # this backend) raw package directory.
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
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_https_tarball_source_fetch_index(http_catalog_server):
    source = HttpsTarballSource(http_catalog_server)
    entries = source.fetch_index()
    assert len(entries) == 1
    assert entries[0].id == "sample_tool"


def test_https_tarball_source_fetch_package(http_catalog_server, tmp_path):
    source = HttpsTarballSource(http_catalog_server)
    entry = source.find_entry("sample_tool")
    dest = tmp_path / "installed" / "sample_tool"
    source.fetch_package(entry, dest)
    assert (dest / "manifest.json").is_file()
    assert (dest / "sample_tool.py").is_file()


def test_https_tarball_source_404_raises(http_catalog_server):
    source = HttpsTarballSource(http_catalog_server + "/does-not-exist")
    with pytest.raises(SourceError):
        source.fetch_index()


def test_index_carries_kind_and_requires():
    entries = _parse_index(
        json.dumps(
            {
                "catalog_version": 2,
                "packages": [
                    {"id": "dep", "kind": "library", "requires": []},
                    {"id": "leaf", "requires": ["dep"]},
                ],
            }
        ),
        origin="test",
    )
    by_id = {e.id: e for e in entries}
    assert by_id["dep"].kind == "library"
    assert by_id["dep"].requires == ()
    assert by_id["leaf"].kind == "tool"
    assert by_id["leaf"].requires == ("dep",)


def test_index_without_requires_reads_as_unknown_not_empty():
    """An older catalog says nothing about dependencies. Reading that as "()"
    would let the manager promise an install pulls in nothing else."""
    entries = _parse_index(
        json.dumps({"catalog_version": 1, "packages": [{"id": "old"}]}), origin="test"
    )
    assert entries[0].requires is None
