"""Fetching custom tool packages from the Rona Tools catalog.

A *catalog* is any location that publishes an ``index.json`` listing
available packages, plus the package directories themselves. This module
only knows how to read a catalog and copy one package's files onto local
disk (into a caller-supplied destination directory, normally a temp dir that
``toolbox.manager`` then validates before moving it into
``toolbox/custom/<id>/``). It does not know about tools.json, manifests,
pip, or config -- that is ``toolbox.packages`` / ``toolbox.manager``'s job.

Three backends, selected by a source spec string:

    local:<path>            a catalog checked out on local disk (dev/offline)
    git:<url>[#<ref>]        sparse-checkout of a git repo (the default);
                               only the requested package's directory is
                               fetched, never a full clone
    https:<base-url>         fallback for hosts where git isn't available:
                               fetches "<base-url>/index.json" and
                               "<base-url>/<package-path>.tar.gz" over plain
                               HTTP(S)

``index.json`` shape (at the catalog root)::

    {
      "catalog_version": 1,
      "packages": [
        {
          "id": "deepl_translate",
          "version": "0.1.0",
          "name": "DeepL Ceviri",
          "description": "...",
          "path": "packages/deepl_translate"   // optional, defaults to
                                                 // "packages/<id>"
        }
      ]
    }
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tarfile
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("uvicorn.error")

DEFAULT_CATALOG_SOURCE = "git:https://github.com/Tech-06/Rona-Tools.git"

_GIT_TIMEOUT_SECONDS = 120
_HTTP_TIMEOUT_SECONDS = 30


class SourceError(Exception):
    """Raised for any problem reading a catalog or fetching a package."""


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    version: str
    name: str
    description: str
    path: str


def _parse_index(raw: str, *, origin: str) -> list[CatalogEntry]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceError(f"{origin}: index.json is not valid JSON: {exc}") from exc
    packages = data.get("packages")
    if not isinstance(packages, list):
        raise SourceError(f"{origin}: index.json 'packages' must be a list")
    entries = []
    for item in packages:
        if not isinstance(item, dict) or "id" not in item:
            raise SourceError(f"{origin}: invalid package entry in index.json: {item!r}")
        pkg_id = item["id"]
        entries.append(
            CatalogEntry(
                id=pkg_id,
                version=item.get("version", ""),
                name=item.get("name", pkg_id),
                description=item.get("description", ""),
                path=item.get("path", f"packages/{pkg_id}"),
            )
        )
    return entries


def _copy_package_dir(src: Path, dest_dir: Path) -> None:
    if not src.is_dir():
        raise SourceError(f"package directory not found: {src}")
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(src, dest_dir)


class CatalogSource(ABC):
    """A place packages can be fetched from."""

    @abstractmethod
    def fetch_index(self) -> list[CatalogEntry]:
        """Return every package the catalog currently publishes."""

    @abstractmethod
    def fetch_package(self, entry: CatalogEntry, dest_dir: Path) -> None:
        """Write the package's files into dest_dir (created fresh)."""

    def find_entry(self, package_id: str) -> CatalogEntry:
        for entry in self.fetch_index():
            if entry.id == package_id:
                return entry
        raise SourceError(f"package '{package_id}' not found in catalog")


class LocalSource(CatalogSource):
    """A catalog checked out on local disk -- used for development/offline
    testing (e.g. pointing at a working copy of the Rona Tools repo)."""

    def __init__(self, root: Path):
        self.root = root

    def fetch_index(self) -> list[CatalogEntry]:
        index_path = self.root / "index.json"
        if not index_path.is_file():
            raise SourceError(f"{self.root}: index.json not found")
        return _parse_index(index_path.read_text(encoding="utf-8"), origin=str(self.root))

    def fetch_package(self, entry: CatalogEntry, dest_dir: Path) -> None:
        _copy_package_dir(self.root / entry.path, dest_dir)


class GitSource(CatalogSource):
    """Sparse-checkout of a git repository: only index.json (top-level
    files) and, on demand, a single package's directory are ever fetched --
    never a full clone of the catalog."""

    def __init__(self, url: str, ref: str = "main"):
        self.url = url
        self.ref = ref

    def _run(self, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                args,
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise SourceError("git is not installed or not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise SourceError(f"git command timed out: {' '.join(args)}") from exc
        except subprocess.CalledProcessError as exc:
            raise SourceError(
                f"git command failed: {' '.join(args)}\n{exc.stderr}"
            ) from exc

    def _sparse_clone(self, tmp: Path, sparse_paths: list[str]) -> None:
        self._run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "--depth",
                "1",
                "--branch",
                self.ref,
                self.url,
                str(tmp),
            ]
        )
        self._run(["git", "sparse-checkout", "init", "--cone"], cwd=tmp)
        if sparse_paths:
            self._run(["git", "sparse-checkout", "set", *sparse_paths], cwd=tmp)
        self._run(["git", "checkout", self.ref], cwd=tmp)

    def fetch_index(self) -> list[CatalogEntry]:
        with tempfile.TemporaryDirectory(prefix="rona-tools-catalog-") as tmp_name:
            tmp = Path(tmp_name)
            self._sparse_clone(tmp, [])  # cone mode always checks out root files
            index_path = tmp / "index.json"
            if not index_path.is_file():
                raise SourceError(f"{self.url}: index.json not found at repo root")
            return _parse_index(index_path.read_text(encoding="utf-8"), origin=self.url)

    def fetch_package(self, entry: CatalogEntry, dest_dir: Path) -> None:
        with tempfile.TemporaryDirectory(prefix="rona-tools-pkg-") as tmp_name:
            tmp = Path(tmp_name)
            self._sparse_clone(tmp, [entry.path])
            _copy_package_dir(tmp / entry.path, dest_dir)


class HttpsTarballSource(CatalogSource):
    """Fallback for environments without a usable git binary: fetches
    index.json and per-package ``.tar.gz`` archives over plain HTTP(S)."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str) -> bytes:
        import httpx

        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = httpx.get(url, timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourceError(f"failed to fetch {url}: {exc}") from exc
        return response.content

    def fetch_index(self) -> list[CatalogEntry]:
        raw = self._get("index.json").decode("utf-8")
        return _parse_index(raw, origin=self.base_url)

    def fetch_package(self, entry: CatalogEntry, dest_dir: Path) -> None:
        archive_bytes = self._get(f"{entry.path}.tar.gz")
        with tempfile.TemporaryDirectory(prefix="rona-tools-tar-") as tmp_name:
            tmp = Path(tmp_name)
            archive_path = tmp / "package.tar.gz"
            archive_path.write_bytes(archive_bytes)
            extract_dir = tmp / "extracted"
            extract_dir.mkdir()
            with tarfile.open(archive_path) as tar:
                _safe_extract(tar, extract_dir)
            # Archives may either contain the package's files at their root,
            # or be wrapped in a single top-level directory -- support both.
            candidates = [extract_dir] + [p for p in extract_dir.iterdir() if p.is_dir()]
            source_dir = next(
                (c for c in candidates if (c / "manifest.json").is_file()), None
            )
            if source_dir is None:
                raise SourceError(
                    f"{entry.path}.tar.gz did not contain a manifest.json"
                )
            _copy_package_dir(source_dir, dest_dir)


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract, rejecting members that would escape dest (path traversal)."""
    if hasattr(tarfile, "data_filter"):
        tar.extractall(dest, filter="data")
        return
    dest_resolved = dest.resolve()
    for member in tar.getmembers():
        member_path = (dest_resolved / member.name).resolve()
        if dest_resolved not in member_path.parents and member_path != dest_resolved:
            raise SourceError(f"unsafe path in archive: {member.name}")
    tar.extractall(dest)  # noqa: S202 -- members validated above


def parse_source(spec: str) -> CatalogSource:
    """Build a CatalogSource from a spec string.

    Examples:
        "local:D:/Projects/Rona Tools"
        "git:https://github.com/Tech-06/Rona-Tools.git"
        "git:https://github.com/Tech-06/Rona-Tools.git#some-branch"
        "https:https://example.com/rona-tools-catalog"
    """
    if ":" not in spec:
        raise SourceError(
            f"invalid source spec {spec!r}: expected 'local:', 'git:' or 'https:' prefix"
        )
    scheme, _, rest = spec.partition(":")
    if scheme == "local":
        return LocalSource(Path(rest))
    if scheme == "git":
        url, sep, ref = rest.partition("#")
        return GitSource(url, ref if sep else "main")
    if scheme == "https":
        return HttpsTarballSource(rest)
    raise SourceError(f"unknown source scheme '{scheme}:' in {spec!r}")
