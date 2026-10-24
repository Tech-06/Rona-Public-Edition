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
    git:<url>@<ref>          same, ``@`` form for a ref without '/' or ':'
    github:<owner>/<repo>[@<ref>]   shorthand for the GitHub https URL
    https:<base-url>         fallback for hosts where git isn't available:
                               fetches "<base-url>/index.json" and
                               "<base-url>/<package-path>.tar.gz" over HTTPS
                               (plain http only for loopback, i.e. tests)

``<ref>`` is a branch, a tag or a full 40-hex commit SHA. Pinning the source
to a SHA (or tag) is what keeps a moved/compromised ``main`` from changing
what gets installed; without a pin the latest ``main`` is used.

``index.json`` shape (at the catalog root)::

    {
      "catalog_version": 2,
      "packages": [
        {
          "id": "deepl_translate",
          "version": "0.1.0",
          "name": "DeepL Ceviri",
          "description": "...",
          "kind": "tool",                      // optional, "tool" | "library"
          "requires": [],                      // optional, package ids
          "path": "packages/deepl_translate",  // optional, defaults to
                                                 // "packages/<id>"; must be a
                                                 // relative POSIX path
          "commit": "<40-hex sha>",            // optional, git sources: the
                                                 // exact commit to install
          "sha256": "<64-hex digest>"          // optional, https sources: the
                                                 // tarball's digest
        }
      ]
    }

``requires`` is a *copy* of the authoritative value in each package's own
manifest.json. Mirroring it into the index is what lets the manager tell a
user "this will also install google_auth" before anything is downloaded;
the manifest still wins once the package is actually fetched.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tarfile
import tempfile
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urljoin, urlparse

from toolbox import versions
from toolbox.packages import _PACKAGE_ID_PATTERN

logger = logging.getLogger("uvicorn.error")

DEFAULT_CATALOG_SOURCE = "git:https://github.com/Tech-06/Rona-Tools.git"

_GIT_TIMEOUT_SECONDS = 120
_HTTP_TIMEOUT_SECONDS = 30
# A package tarball is a handful of small source files; anything near this
# size is not one. Streamed and counted so a hostile server can't make us
# buffer gigabytes.
_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
_MAX_INDEX_BYTES = 5 * 1024 * 1024
_MAX_REDIRECTS = 5
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_SHA1_RE = re.compile(r"[0-9a-fA-F]{40}")
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


class SourceError(Exception):
    """Raised for any problem reading a catalog or fetching a package."""


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    version: str
    name: str
    description: str
    path: str
    kind: str = "tool"
    # ``None`` means the catalog didn't declare dependencies at all, which is
    # not the same as ``()`` ("declared, and there are none"). A plan built
    # from an index predating the key has to admit it may be incomplete
    # rather than promise there is nothing else to install. Each entry may
    # carry a pip-like version constraint (see toolbox.versions), e.g.
    # "google_auth", "google_auth>=2.0", "google_auth>=2.0,<3" -- normalized
    # by _parse_index the same way toolbox.packages normalizes a manifest's
    # own requires list.
    requires: tuple[str, ...] | None = None
    # Optional integrity pins, honoured by the backend they apply to: a git
    # commit for GitSource, a tarball digest for HttpsTarballSource.
    commit: str | None = None
    sha256: str | None = None

    def requirements(self) -> tuple["versions.Requirement", ...] | None:
        if self.requires is None:
            return None
        return tuple(versions.parse_requirement(r) for r in self.requires)


def _validate_entry_path(path: object, *, origin: str, pkg_id: str) -> str:
    """A catalog entry's ``path`` is joined onto a temp dir / URL, so it must
    stay a plain relative POSIX path -- no absolute paths, drive letters,
    backslashes, ``..`` or empty segments."""
    problem = None
    if not isinstance(path, str) or not path:
        problem = "must be a non-empty string"
    elif "\\" in path or ":" in path or "\0" in path:
        problem = "must not contain backslashes, drive letters or NUL"
    elif path.startswith("/") or PurePosixPath(path).is_absolute():
        problem = "must be relative"
    elif any(seg in ("", ".", "..") for seg in path.split("/")):
        problem = "must not contain empty, '.' or '..' segments"
    elif path.startswith("-"):
        # Handed to git as an argument; a leading '-' would read as an option.
        problem = "must not start with '-'"
    if problem:
        raise SourceError(f"{origin}: package '{pkg_id}': invalid path {path!r}: {problem}")
    return path


def _resolve_inside(base: Path, rel: str) -> Path:
    """``base / rel``, refusing a result that (through a symlink in the
    fetched tree) lands outside ``base``."""
    target = (base / rel).resolve()
    base_resolved = base.resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise SourceError(f"package path {rel!r} escapes the catalog checkout")
    return target


def _check_url(url: str) -> None:
    """https only; plain http solely for loopback (local test servers)."""
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and (parsed.hostname or "") in _LOOPBACK_HOSTS:
        return
    raise SourceError(f"refusing non-https URL: {url}")


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
        if not isinstance(pkg_id, str) or not re.fullmatch(
            _PACKAGE_ID_PATTERN, pkg_id
        ):
            raise SourceError(f"{origin}: invalid package id in index.json: {pkg_id!r}")
        entry_path = _validate_entry_path(
            item.get("path", f"packages/{pkg_id}"), origin=origin, pkg_id=pkg_id
        )
        commit = item.get("commit")
        if commit is not None and not (
            isinstance(commit, str) and _SHA1_RE.fullmatch(commit)
        ):
            raise SourceError(
                f"{origin}: package '{pkg_id}': 'commit' must be a 40-hex SHA"
            )
        sha256 = item.get("sha256")
        if sha256 is not None and not (
            isinstance(sha256, str) and _SHA256_RE.fullmatch(sha256)
        ):
            raise SourceError(
                f"{origin}: package '{pkg_id}': 'sha256' must be a 64-hex digest"
            )
        raw_requires = item.get("requires")
        requires: tuple[str, ...] | None = None
        if isinstance(raw_requires, list):
            normalized_requires = []
            for dep in raw_requires:
                dep_str = str(dep)
                try:
                    req = versions.parse_requirement(dep_str)
                except versions.VersionError as exc:
                    raise SourceError(
                        f"{origin}: package '{pkg_id}': invalid requires entry "
                        f"{dep!r}: {exc}"
                    ) from exc
                normalized_requires.append(str(req))
            requires = tuple(normalized_requires)
        entries.append(
            CatalogEntry(
                id=pkg_id,
                version=item.get("version", ""),
                name=item.get("name", pkg_id),
                description=item.get("description", ""),
                path=entry_path,
                kind=item.get("kind", "tool"),
                requires=requires,
                commit=commit.lower() if commit else None,
                sha256=sha256.lower() if sha256 else None,
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
        _copy_package_dir(_resolve_inside(self.root, entry.path), dest_dir)


class GitSource(CatalogSource):
    """Sparse-checkout of a git repository: only index.json (top-level
    files) and, on demand, a single package's directory are ever fetched --
    never a full clone of the catalog."""

    def __init__(self, url: str, ref: str = "main"):
        # A leading '-' would be parsed by git as an option (--upload-pack=...).
        if not url or url.startswith("-") or not ref or ref.startswith("-"):
            raise SourceError(f"invalid git source: url={url!r} ref={ref!r}")
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

    def _sparse_clone(
        self, tmp: Path, sparse_paths: list[str], commit: str | None = None
    ) -> None:
        # A pin (the entry's commit, or a source ref that is itself a SHA)
        # can't be fetched with --depth 1 --branch, so those take the
        # history-bearing (still blob-less) route and are verified afterwards.
        ref_is_sha = bool(_SHA1_RE.fullmatch(self.ref))
        pin = commit or (self.ref.lower() if ref_is_sha else None)
        clone = ["git", "clone", "--filter=blob:none", "--no-checkout"]
        if pin is None:
            clone += ["--depth", "1"]
        if not ref_is_sha:
            clone += ["--branch", self.ref]
        self._run([*clone, "--", self.url, str(tmp)])
        self._run(["git", "sparse-checkout", "init", "--cone"], cwd=tmp)
        if sparse_paths:
            self._run(["git", "sparse-checkout", "set", "--", *sparse_paths], cwd=tmp)
        self._run(["git", "checkout", pin or self.ref], cwd=tmp)
        if pin is not None:
            head = self._run(["git", "rev-parse", "HEAD"], cwd=tmp).stdout.strip().lower()
            if head != pin:
                raise SourceError(f"checked out {head}, expected pinned commit {pin}")

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
            self._sparse_clone(tmp, [entry.path], entry.commit)
            _copy_package_dir(_resolve_inside(tmp, entry.path), dest_dir)


class HttpsTarballSource(CatalogSource):
    """Fallback for environments without a usable git binary: fetches
    index.json and per-package ``.tar.gz`` archives over HTTPS (plain HTTP
    only for loopback hosts, which exist for tests)."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        _check_url(self.base_url)

    def _get(self, path: str, max_bytes: int) -> bytes:
        import httpx

        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            # Redirects are followed by hand so each hop can be re-checked:
            # an https URL must not be able to bounce us onto plain http.
            for _ in range(_MAX_REDIRECTS + 1):
                _check_url(url)
                with httpx.stream(
                    "GET", url, timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=False
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise SourceError(f"redirect without Location from {url}")
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise SourceError(f"{url}: download exceeds {max_bytes} bytes")
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise SourceError(f"{url}: download exceeds {max_bytes} bytes")
                        chunks.append(chunk)
                    return b"".join(chunks)
            raise SourceError(f"too many redirects fetching {url}")
        except httpx.HTTPError as exc:
            raise SourceError(f"failed to fetch {url}: {exc}") from exc

    def fetch_index(self) -> list[CatalogEntry]:
        raw = self._get("index.json", _MAX_INDEX_BYTES).decode("utf-8")
        return _parse_index(raw, origin=self.base_url)

    def fetch_package(self, entry: CatalogEntry, dest_dir: Path) -> None:
        archive_bytes = self._get(f"{entry.path}.tar.gz", _MAX_DOWNLOAD_BYTES)
        # Verify before the archive is ever opened, let alone extracted.
        if entry.sha256 is not None:
            digest = hashlib.sha256(archive_bytes).hexdigest()
            if digest != entry.sha256:
                raise SourceError(
                    f"{entry.path}.tar.gz: sha256 mismatch "
                    f"(expected {entry.sha256}, got {digest})"
                )
        with tempfile.TemporaryDirectory(prefix="rona-tools-tar-") as tmp_name:
            tmp = Path(tmp_name)
            archive_path = tmp / "package.tar.gz"
            archive_path.write_bytes(archive_bytes)
            extract_dir = tmp / "extracted"
            extract_dir.mkdir()
            try:
                with tarfile.open(archive_path) as tar:
                    _safe_extract(tar, extract_dir)
            except tarfile.TarError as exc:
                raise SourceError(f"{entry.path}.tar.gz: unusable archive: {exc}") from exc
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
    """Extract, rejecting members that would escape dest or that aren't plain
    files/directories."""
    if hasattr(tarfile, "data_filter"):
        tar.extractall(dest, filter="data")
        return
    # Interpreters without the "data" filter (< 3.11.4): do its job by hand.
    # Links are refused outright (their targets are what escape dest), as are
    # devices and fifos; setuid/setgid bits are cleared.
    dest_resolved = dest.resolve()
    safe_members = []
    for member in tar.getmembers():
        if not (member.isfile() or member.isdir()):
            raise SourceError(f"unsupported member type in archive: {member.name}")
        name = member.name
        if (
            name.startswith(("/", "\\"))
            or PureWindowsPath(name).anchor
            or ".." in PurePosixPath(name.replace("\\", "/")).parts
        ):
            raise SourceError(f"unsafe path in archive: {name}")
        member_path = (dest_resolved / name).resolve()
        if dest_resolved not in member_path.parents and member_path != dest_resolved:
            raise SourceError(f"unsafe path in archive: {name}")
        member.mode &= ~0o6000
        safe_members.append(member)
    with warnings.catch_warnings():
        # 3.12+ warns about the missing filter; this path only runs where the
        # filter doesn't exist, but tests simulate it on newer interpreters.
        warnings.simplefilter("ignore", DeprecationWarning)
        tar.extractall(dest, members=safe_members)


_GITHUB_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def parse_source(spec: str) -> CatalogSource:
    """Build a CatalogSource from a spec string.

    Examples:
        "local:D:/Projects/Rona Tools"
        "git:https://github.com/Tech-06/Rona-Tools.git"
        "git:https://github.com/Tech-06/Rona-Tools.git#some-branch"
        "git:https://github.com/Tech-06/Rona-Tools.git#<40-hex-sha>"
        "git:https://github.com/Tech-06/Rona-Tools.git@v1.2"
        "github:Tech-06/Rona-Tools@<sha-or-tag>"
        "https:https://example.com/rona-tools-catalog"
    """
    if ":" not in spec:
        raise SourceError(
            f"invalid source spec {spec!r}: expected 'local:', 'git:', "
            "'github:' or 'https:' prefix"
        )
    scheme, _, rest = spec.partition(":")
    if scheme == "local":
        return LocalSource(Path(rest))
    if scheme == "git":
        url, sep, ref = rest.partition("#")
        if not sep:
            # "...repo.git@v1": only when what follows '@' can't be part of a
            # URL or scp-style "git@host:path" (no '/' or ':'), so those keep
            # working and a ref containing '/' must use '#'.
            head, at, tail = rest.rpartition("@")
            if at and head and tail and "/" not in tail and ":" not in tail:
                url, sep, ref = head, at, tail
        return GitSource(url, ref if sep else "main")
    if scheme == "github":
        repo, _, ref = rest.partition("@")
        if not _GITHUB_REPO_RE.fullmatch(repo):
            raise SourceError(f"invalid github source {spec!r}: expected owner/repo")
        repo = repo.removesuffix(".git")
        return GitSource(f"https://github.com/{repo}.git", ref or "main")
    if scheme == "https":
        return HttpsTarballSource(rest)
    raise SourceError(f"unknown source scheme '{scheme}:' in {spec!r}")
