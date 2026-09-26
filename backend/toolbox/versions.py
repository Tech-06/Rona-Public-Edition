"""Pip-like version constraints for toolbox package ``requires`` entries.

A package's manifest.json (and a catalog's index.json) list *bare* package
ids in ``requires`` today, e.g. ``"google_auth"``. This module adds an
optional pip-like version constraint on top of that: ``"google_auth>=2.0"``,
``"google_auth>=2.0,<3"``, ``"x~=2.1"``. It is deliberately stdlib-only (no
``packaging`` dependency) since the constraint language it needs to support
is a small subset: plain dotted-integer versions (``2``, ``2.0``, ``2.1.3``
-- no pre-releases, no wildcards) and the comparison operators
``==``, ``!=``, ``>=``, ``<=``, ``>``, ``<``, ``~=``.

Three layers, cheapest to richest:

    Version        a parsed dotted-integer version, comparable and hashable
                    with zero-padding so ``2 == 2.0 == 2.0.0``.
    Specifier       one operator + version, e.g. ``>=2.0``.
    Requirement     a package name plus zero or more (AND-ed) specifiers,
                    e.g. ``google_auth>=2.0,<3``.

``toolbox.packages`` and ``toolbox.sources`` use ``parse_requirement`` to
validate and normalize every ``requires`` entry they read from disk;
``toolbox.manager`` only ever needs a requirement's ``.name`` (dependency
resolution and install/upgrade *by version* is a separate concern handled
elsewhere).
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*")
_SPEC_RE = re.compile(r"^\s*(~=|==|!=|>=|<=|>|<)\s*(\d+(?:\.\d+)*)\s*$")


class VersionError(ValueError):
    """Raised for a malformed version string or a malformed requires entry."""


@functools.total_ordering
@dataclass(frozen=True)
class Version:
    """A dotted-integer version, e.g. ``2.1.3``.

    Compares and hashes with zero-padding on the shorter side, so
    ``Version.parse("2") == Version.parse("2.0") == Version.parse("2.0.0")``
    -- but ``str()`` preserves whatever precision was actually written.
    """

    parts: tuple[int, ...]

    @staticmethod
    def parse(text: str) -> "Version":
        stripped = text.strip()
        if not _VERSION_RE.match(stripped):
            raise VersionError(f"invalid version: {text!r}")
        return Version(tuple(int(p) for p in stripped.split(".")))

    def _padded(self, other: "Version") -> tuple[tuple[int, ...], tuple[int, ...]]:
        length = max(len(self.parts), len(other.parts))
        a = self.parts + (0,) * (length - len(self.parts))
        b = other.parts + (0,) * (length - len(other.parts))
        return a, b

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        a, b = self._padded(other)
        return a == b

    def __lt__(self, other: "Version") -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        a, b = self._padded(other)
        return a < b

    def __hash__(self) -> int:
        # Trailing zeros stripped so 2 == 2.0 == 2.0.0 hash equal too.
        stripped = list(self.parts)
        while len(stripped) > 1 and stripped[-1] == 0:
            stripped.pop()
        return hash(tuple(stripped))

    def __str__(self) -> str:
        return ".".join(str(p) for p in self.parts)


def parse_version(text: str) -> Version:
    return Version.parse(text)


def is_newer(candidate: str, current: str) -> bool:
    """True if both strings parse as versions and ``candidate`` > ``current``.

    Anything unparseable (either side) comes back False rather than raising
    -- this is meant for "is there an upgrade available?" checks that must
    never crash on a weird version string.
    """
    try:
        candidate_v = Version.parse(candidate)
        current_v = Version.parse(current)
    except VersionError:
        return False
    return candidate_v > current_v


@dataclass(frozen=True)
class Specifier:
    """One operator + version, e.g. the ``>=2.0`` in ``google_auth>=2.0``."""

    op: str  # one of "==","!=",">=","<=",">","<","~="
    version: Version
    raw: str  # original version text, e.g. "2.1"

    def contains(self, v: Version) -> bool:
        if self.op == "==":
            return v == self.version
        if self.op == "!=":
            return v != self.version
        if self.op == ">=":
            return v >= self.version
        if self.op == "<=":
            return v <= self.version
        if self.op == ">":
            return v > self.version
        if self.op == "<":
            return v < self.version
        # "~=": PEP 440-like compatible release. ~=2.1 means >=2.1,<3;
        # ~=2.1.3 means >=2.1.3,<2.2 -- the last component is free to vary,
        # everything before it is pinned.
        parts = self.version.parts
        if len(parts) < 2:
            raise VersionError(
                f"~= requires at least two version components: {self.raw!r}"
            )
        upper = Version(parts[:-2] + (parts[-2] + 1,))
        return v >= self.version and v < upper

    def __str__(self) -> str:
        return f"{self.op}{self.raw}"


@dataclass(frozen=True)
class Requirement:
    """A package name plus zero or more AND-ed version specifiers."""

    name: str
    specifiers: tuple[Specifier, ...]

    def is_satisfied_by(self, version: str | None) -> bool:
        if not self.specifiers:
            return True
        if version is None:
            return False
        try:
            v = Version.parse(version)
        except VersionError:
            return False
        return all(spec.contains(v) for spec in self.specifiers)

    def __str__(self) -> str:
        if not self.specifiers:
            return self.name
        return self.name + ",".join(str(spec) for spec in self.specifiers)


def parse_requirement(text: str) -> Requirement:
    """Parse one ``requires`` entry, e.g. ``"google_auth>=2.0,<3"``.

    Raises ``VersionError`` with a clear reason for anything malformed: an
    uppercase/invalid name, a missing or malformed version, an unknown
    operator, an empty specifier (a trailing comma), or a wildcard.
    """
    original = text
    stripped = text.strip()
    match = _NAME_RE.match(stripped)
    if not match:
        raise VersionError(
            f"invalid requires entry {original!r}: package name must start with a "
            "lowercase letter and contain only lowercase letters, digits and "
            "underscores"
        )
    name = match.group(0)
    rest = stripped[match.end():]
    if not rest:
        return Requirement(name=name, specifiers=())

    specifiers: list[Specifier] = []
    for chunk in rest.split(","):
        spec_match = _SPEC_RE.match(chunk)
        if not spec_match:
            raise VersionError(
                f"invalid requires entry {original!r}: bad version specifier "
                f"{chunk.strip()!r}"
            )
        op, version_text = spec_match.group(1), spec_match.group(2)
        version = Version.parse(version_text)
        specifiers.append(Specifier(op=op, version=version, raw=version_text))
    return Requirement(name=name, specifiers=tuple(specifiers))
