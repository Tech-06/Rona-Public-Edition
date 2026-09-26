"""Tests for toolbox.versions: parsing/comparing dotted-integer versions and
pip-like requirement strings used in package manifests' ``requires`` lists.
"""

import pytest

from toolbox.versions import (
    Requirement,
    Specifier,
    Version,
    VersionError,
    is_newer,
    parse_requirement,
    parse_version,
)


def test_parse_simple_and_padded_equality():
    assert Version.parse("2") == Version.parse("2.0") == Version.parse("2.0.0")
    assert Version.parse("2.1") != Version.parse("2.1.1")
    assert str(Version.parse("2.10")) == "2.10"
    assert str(parse_version("1.2.3")) == "1.2.3"


def test_ordering():
    assert Version.parse("1.9") < Version.parse("1.10")
    assert Version.parse("2.0") > Version.parse("1.99")
    assert Version.parse("2.0") >= Version.parse("2")
    assert Version.parse("2.0") <= Version.parse("2.0.0")
    versions = sorted(
        [Version.parse("1.10"), Version.parse("1.2"), Version.parse("1.1.0")]
    )
    assert versions[0] == Version.parse("1.1.0")
    assert versions[1] == Version.parse("1.2")
    assert versions[2] == Version.parse("1.10")


def test_version_hash_consistent_with_equality():
    assert hash(Version.parse("2")) == hash(Version.parse("2.0")) == hash(Version.parse("2.0.0"))
    assert {Version.parse("2"), Version.parse("2.0")} == {Version.parse("2.0.0")}


def test_invalid_version_raises():
    with pytest.raises(VersionError):
        Version.parse("1.a")
    with pytest.raises(VersionError):
        Version.parse("")
    with pytest.raises(VersionError):
        Version.parse("1.")


@pytest.mark.parametrize(
    "op, satisfied, unsatisfied",
    [
        ("==", "2.0", "2.1"),
        ("!=", "2.1", "2.0"),
        (">=", "2.0", "1.9"),
        ("<=", "2.0", "2.1"),
        (">", "2.1", "2.0"),
        ("<", "1.9", "2.0"),
    ],
)
def test_each_operator(op, satisfied, unsatisfied):
    spec = Specifier(op=op, version=Version.parse("2.0"), raw="2.0")
    assert spec.contains(Version.parse(satisfied))
    assert not spec.contains(Version.parse(unsatisfied))


def test_compatible_release():
    spec = parse_requirement("x~=2.1").specifiers[0]
    assert spec.contains(Version.parse("2.1"))
    assert spec.contains(Version.parse("2.5"))
    assert not spec.contains(Version.parse("3.0"))
    assert not spec.contains(Version.parse("2.0"))

    spec2 = parse_requirement("x~=2.1.3").specifiers[0]
    assert spec2.contains(Version.parse("2.1.3"))
    assert spec2.contains(Version.parse("2.1.9"))
    assert not spec2.contains(Version.parse("2.2"))
    assert not spec2.contains(Version.parse("2.1.2"))


def test_compatible_release_needs_two_components():
    spec = Specifier(op="~=", version=Version.parse("2"), raw="2")
    with pytest.raises(VersionError):
        spec.contains(Version.parse("2.5"))


def test_parse_requirement_bare_and_ranges():
    req = parse_requirement("google_auth")
    assert req.name == "google_auth"
    assert req.specifiers == ()
    assert str(req) == "google_auth"

    req2 = parse_requirement("google_auth>=2.0")
    assert req2.name == "google_auth"
    assert [str(s) for s in req2.specifiers] == [">=2.0"]
    assert str(req2) == "google_auth>=2.0"

    req3 = parse_requirement("google_auth>=2.0,<3")
    assert [str(s) for s in req3.specifiers] == [">=2.0", "<3"]
    assert str(req3) == "google_auth>=2.0,<3"
    assert req3.is_satisfied_by("2.5")
    assert not req3.is_satisfied_by("3.0")
    assert not req3.is_satisfied_by("1.9")


def test_parse_requirement_normalizes_whitespace():
    req = parse_requirement("  google_auth >= 2.0 , < 3  ")
    assert req.name == "google_auth"
    assert [str(s) for s in req.specifiers] == [">=2.0", "<3"]


@pytest.mark.parametrize(
    "text",
    ["Google", "x>=", "x>=1.a", "x=>1", "x>=1,", "x==1.*"],
)
def test_invalid_requirements_raise(text):
    with pytest.raises(VersionError):
        parse_requirement(text)


def test_unparseable_version_never_satisfies():
    req = parse_requirement("x>=2.0")
    assert not req.is_satisfied_by(None)
    assert not req.is_satisfied_by("not-a-version")
    assert not req.is_satisfied_by("")

    bare = parse_requirement("x")
    assert bare.is_satisfied_by(None) is True  # no constraint -> always True


def test_is_newer():
    assert is_newer("2.1", "2.0")
    assert not is_newer("2.0", "2.1")
    assert not is_newer("2.0", "2.0")
    assert not is_newer("not-a-version", "2.0")
    assert not is_newer("2.0", "not-a-version")


def test_requirement_dataclass_direct_construction():
    req = Requirement(name="x", specifiers=(Specifier(op=">=", version=Version.parse("1"), raw="1"),))
    assert req.is_satisfied_by("1.0")
    assert not req.is_satisfied_by("0.9")
