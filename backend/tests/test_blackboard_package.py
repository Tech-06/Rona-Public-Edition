"""Tests for the blackboard custom tool package.

All fixture data below is synthetic: shaped exactly like what a live
discovery session against a real Blackboard Ultra tenant returned (see the
package's own module docstrings for what was learned that way), but with
made-up course names, IDs, grades and text. None of it is anyone's real
academic data -- that distinction matters because, unlike
``toolbox/custom/*`` itself, this test file is a tracked part of the repo.

Runs entirely offline: no test here talks to a real Blackboard server.
``bb_client``'s HTTP layer is exercised through ``httpx.MockTransport``, and
``bb_session``/``bb_config`` are pointed at a temp directory instead of the
real package directory.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from bs4 import BeautifulSoup

from toolbox.custom.blackboard import (
    bb_auth,
    bb_client,
    bb_config,
    bb_session,
)
from toolbox.custom.blackboard import (
    blackboard_tool as bt,
)

BASE_URL = "https://example.blackboard.com"


# ---------------------------------------------------------------------------
# bb_session -- cookie storage and the path-scoped dedup fix
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_session_file(tmp_path, monkeypatch):
    """Every test in this file gets its own session.json/config.json/.env,
    never the real ones -- otherwise a real backend/.env sitting next to
    this checkout (TRIGGER_TIMEZONE, say) would leak into what's supposed
    to be a fully offline test."""
    monkeypatch.setattr(bb_session, "SESSION_FILE", tmp_path / "session.json")
    monkeypatch.setattr(bb_config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(bb_config, "_ENV_PATH", tmp_path / "nonexistent.env")
    bb_client.clear_cache()
    yield
    bb_client.clear_cache()


def test_session_round_trip():
    cookies = [{"name": "JSESSIONID", "value": "abc", "domain": "x", "path": "/"}]
    assert bb_session.load_session(BASE_URL) is None

    bb_session.save_session(BASE_URL, cookies)
    loaded = bb_session.load_session(BASE_URL)
    assert loaded == cookies

    info = bb_session.session_info()
    assert info["base_url"] == BASE_URL
    assert info["cookie_count"] == 1

    assert bb_session.clear_session() is True
    assert bb_session.load_session(BASE_URL) is None
    assert bb_session.clear_session() is False  # nothing left to delete


def test_session_scoped_to_its_own_base_url():
    """A session saved for one institution must never be handed to another."""
    bb_session.save_session(BASE_URL, [{"name": "a", "value": "1", "path": "/"}])
    assert bb_session.load_session("https://other.blackboard.com") is None


def test_cookies_to_jar_prefers_root_path_on_name_collision():
    """Observed live: Blackboard's own consent page scopes a second
    JSESSIONID to a narrow path, separate from the root-scoped one every
    API call actually needs. Root must win regardless of ordering."""
    narrow_first = [
        {"name": "JSESSIONID", "value": "narrow", "path": "/webapps/privacy-disclosure"},
        {"name": "JSESSIONID", "value": "root", "path": "/"},
        {"name": "BbRouter", "value": "xyz", "path": "/"},
    ]
    root_first = list(reversed(narrow_first))

    for cookies in (narrow_first, root_first):
        jar = bb_session.cookies_to_jar(cookies)
        assert jar["JSESSIONID"] == "root"
        assert jar["BbRouter"] == "xyz"


def test_cookies_to_jar_skips_unnamed_entries():
    assert bb_session.cookies_to_jar([{"value": "no-name"}]) == {}


def test_session_expires_at_parses_the_bbrouter_expiry_field():
    bb_session.save_session(
        BASE_URL,
        [
            {
                "name": "BbRouter",
                "value": "expires:1790000000,id:abc,timeout:10800,xsrf:xyz",
                "path": "/",
            }
        ],
    )
    assert bb_session.session_expires_at(BASE_URL) == 1790000000.0


def test_session_expires_at_none_when_unknowable():
    assert bb_session.session_expires_at(BASE_URL) is None  # no session at all

    bb_session.save_session(BASE_URL, [{"name": "JSESSIONID", "value": "x", "path": "/"}])
    assert bb_session.session_expires_at(BASE_URL) is None  # no BbRouter cookie

    bb_session.save_session(
        BASE_URL, [{"name": "BbRouter", "value": "id:abc,timeout:10800", "path": "/"}]
    )
    assert bb_session.session_expires_at(BASE_URL) is None  # no 'expires' field

    bb_session.save_session(
        BASE_URL,
        [{"name": "BbRouter", "value": "expires:not-a-number,id:abc", "path": "/"}],
    )
    assert bb_session.session_expires_at(BASE_URL) is None  # 'expires' isn't numeric


# ---------------------------------------------------------------------------
# bb_config
# ---------------------------------------------------------------------------


def test_load_config_defaults_and_normalization(monkeypatch):
    monkeypatch.delenv("BB_PASSWORD", raising=False)
    monkeypatch.delenv("TRIGGER_TIMEZONE", raising=False)
    bb_config.CONFIG_FILE.write_text(
        json.dumps({"base_url": f"{BASE_URL}/"}), encoding="utf-8"
    )
    config = bb_config.load_config()
    assert config["base_url"] == BASE_URL  # trailing slash stripped
    assert config["auth_mode"] == "direct"  # default
    assert config["timezone"] == "UTC"  # no TRIGGER_TIMEZONE set -> UTC fallback
    assert bb_config.is_configured(config) is True


def test_load_config_falls_back_to_trigger_timezone(monkeypatch):
    monkeypatch.setenv("TRIGGER_TIMEZONE", "Europe/Istanbul")
    bb_config.CONFIG_FILE.write_text(json.dumps({"base_url": BASE_URL}), encoding="utf-8")
    config = bb_config.load_config()
    assert config["timezone"] == "Europe/Istanbul"


def test_load_config_rejects_unknown_auth_mode(monkeypatch):
    bb_config.CONFIG_FILE.write_text(
        json.dumps({"base_url": BASE_URL, "auth_mode": "carrier-pigeon"}), encoding="utf-8"
    )
    assert bb_config.load_config()["auth_mode"] == "direct"


def test_not_configured_without_base_url():
    assert bb_config.is_configured({"base_url": ""}) is False
    assert bb_config.not_configured_error()["success"] is False


def _config(**overrides) -> dict:
    base = {
        "base_url": BASE_URL,
        "auth_mode": "sso",  # no auto-reauth credentials -- keeps these tests offline
        "username": "",
        "password": "",
        "timezone": "UTC",
        "cache_ttl": 300,
    }
    base.update(overrides)
    return base


def _install_mock_client(handler) -> None:
    """Point *this event loop's* bb_client connection pool at a MockTransport.

    bb_client keeps its client and locks per event loop (see its _LoopState)
    because both bind to the loop they are first used on, so tests have to
    reach into the running loop's state rather than a module-level global.
    Must be called from inside an async test -- there is no loop to key on
    otherwise.
    """
    bb_client._state().client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )


def _install_session():
    bb_session.save_session(BASE_URL, [{"name": "JSESSIONID", "value": "tok", "path": "/"}])


# ---------------------------------------------------------------------------
# bb_auth -- the headless HTTP login path, its MFA detection, and the
# cookie-consent fix
# ---------------------------------------------------------------------------


def _login_page_html(nonce: str | None = "test-nonce-001") -> str:
    """A synthetic stand-in for bbLogin.jsp's rendered markup -- just enough
    of it for _extract_nonce/_login_http to work with."""
    nonce_input = (
        f'<input type="hidden" name="{bb_auth._NONCE_FIELD}" value="{nonce}">'
        if nonce
        else ""
    )
    return f"<html><body><form>{nonce_input}</form></body></html>"


# The rendered fields bbLogin.jsp emits once MFA is actually active.
_RENDERED_MFA_HTML = """
<html><body>
<input id="totp-verification-input" type="text">
<input type="hidden" name="showMFAVerification" value="true">
</body></html>
"""

# The same template, unsubstituted -- bbLogin.jsp ships this markup on
# every tenant, MFA or not. _is_rendered_mfa_prompt must not mistake it
# for a real challenge, or every non-MFA account would fail login_direct.
_INERT_MFA_TEMPLATE_HTML = """
<html><body>
<input id="totp-verification-input" type="text">
<input type="hidden" name="showMFAVerification" value="$showMFAVerification">
</body></html>
"""


def _mock_client_factory(handler):
    """Route bb_auth's own httpx.Client(...) calls -- both _login_http's
    and validate_cookies' -- through a MockTransport instead of the
    network. Patching bb_auth.httpx.Client patches the shared httpx
    module object, so this also redirects validate_cookies during the
    same test, which is exactly what's wanted since _login_http calls it
    internally to judge success.

    The *real* httpx.Client class is captured here, before monkeypatch
    replaces the attribute -- calling ``httpx.Client(...)`` from inside
    the factory itself would otherwise resolve through the very same
    patched, shared module object and recurse forever.
    """
    real_client_cls = httpx.Client

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return real_client_cls(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def test_extract_nonce_finds_value_and_returns_none_without_one():
    assert bb_auth._extract_nonce(_login_page_html("abc123nonce")) == "abc123nonce"
    assert bb_auth._extract_nonce("<html><body>no nonce here</body></html>") is None


def test_is_rendered_mfa_prompt_distinguishes_real_challenge_from_template():
    real = BeautifulSoup(_RENDERED_MFA_HTML, "html.parser")
    template = BeautifulSoup(_INERT_MFA_TEMPLATE_HTML, "html.parser")
    assert bb_auth._is_rendered_mfa_prompt(real) is True
    assert bb_auth._is_rendered_mfa_prompt(template) is False


def test_login_http_success_saves_a_working_session(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == bb_auth._LOGIN_PATH:
            if request.method == "GET":
                return httpx.Response(200, text=_login_page_html())
            return httpx.Response(
                200,
                headers=[
                    ("set-cookie", "BbRouter=expires:9999999999,id:sess-1; Path=/"),
                    ("set-cookie", "JSESSIONID=sess-jsid; Path=/"),
                ],
            )
        if request.url.path == "/learn/api/v1/users/me":
            return httpx.Response(200, json={"id": "_1_1"})
        return httpx.Response(404)

    monkeypatch.setattr(bb_auth.httpx, "Client", _mock_client_factory(handler))
    config = _config(username="test-student", password="fake-pw")
    result = bb_auth._login_http(config)

    assert result == {"success": True, "message": "logged in and session saved"}
    loaded = bb_session.load_session(BASE_URL)
    assert loaded is not None
    names = {c["name"] for c in loaded}
    assert {"BbRouter", "JSESSIONID"}.issubset(names)


def test_login_http_sends_nonce_and_expected_form_fields(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == bb_auth._LOGIN_PATH:
            if request.method == "GET":
                return httpx.Response(200, text=_login_page_html("the-nonce-value"))
            captured["body"] = request.content.decode()
            return httpx.Response(200, text="<html></html>")
        if request.url.path == "/learn/api/v1/users/me":
            return httpx.Response(401)
        return httpx.Response(404)

    monkeypatch.setattr(bb_auth.httpx, "Client", _mock_client_factory(handler))
    bb_auth._login_http(_config(username="test-student", password="fake-pw"))

    from urllib.parse import parse_qs

    form = parse_qs(captured["body"], keep_blank_values=True)
    assert form["user_id"] == ["test-student"]
    assert form["password"] == ["fake-pw"]
    assert form["login"] == ["Login"]
    assert form["action"] == ["login"]
    assert form["new_loc"] == [""]
    assert form[bb_auth._NONCE_FIELD] == ["the-nonce-value"]


def test_login_http_sends_consent_cookie_on_the_very_first_request(monkeypatch):
    """Phase 1's whole point: Blackboard's "Privacy, cookies and terms of
    use" lightbox is not a real consent flow, just a cookie check -- so the
    consent cookie has to already be on the client before the *first*
    request goes out (the GET of the login page itself). Setting it any
    later would be too late to stop the modal from rendering on a live
    tenant and swallowing the login form."""
    first_request_cookie_header = {}

    def handler(request: httpx.Request) -> httpx.Response:
        cookie_header = request.headers.get("cookie", "")
        first_request_cookie_header.setdefault("value", cookie_header)
        if request.url.path == bb_auth._LOGIN_PATH:
            if request.method == "GET":
                return httpx.Response(200, text=_login_page_html())
            return httpx.Response(200, text="<html></html>")
        if request.url.path == "/learn/api/v1/users/me":
            return httpx.Response(200, json={"id": "_1_1"})
        return httpx.Response(404)

    monkeypatch.setattr(bb_auth.httpx, "Client", _mock_client_factory(handler))
    bb_auth._login_http(_config(username="test-student", password="fake-pw"))

    assert f"{bb_auth.CONSENT_COOKIE_NAME}=true" in first_request_cookie_header["value"]


def test_login_http_rejected_credentials_reports_specific_error_and_saves_nothing(
    monkeypatch,
):
    error_html = (
        '<html><body><div id="loginError">'
        "the username or password you entered is incorrect"
        "</div></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == bb_auth._LOGIN_PATH:
            if request.method == "GET":
                return httpx.Response(200, text=_login_page_html())
            return httpx.Response(200, text=error_html)
        if request.url.path == "/learn/api/v1/users/me":
            return httpx.Response(401)
        return httpx.Response(404)

    monkeypatch.setattr(bb_auth.httpx, "Client", _mock_client_factory(handler))
    result = bb_auth._login_http(_config(username="test-student", password="wrong"))

    assert result["success"] is False
    assert "incorrect" in result["error"]
    assert result["error"] != "credentials were rejected or the login form changed"
    assert bb_session.load_session(BASE_URL) is None


def test_login_http_mfa_short_circuits_login_direct_before_browser_fallback(
    monkeypatch,
):
    """Pins two things at once: _login_http must recognize a *rendered* MFA
    challenge (not the always-present inert template markup -- see
    test_is_rendered_mfa_prompt_distinguishes_real_challenge_from_template)
    and flag it as mfa_required, and login_direct must treat that flag as
    final -- never falling through to the much slower Playwright-backed
    _login_browser, which would only hit the exact same MFA wall again."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == bb_auth._LOGIN_PATH:
            if request.method == "GET":
                return httpx.Response(200, text=_login_page_html())
            return httpx.Response(200, text=_RENDERED_MFA_HTML)
        if request.url.path == "/learn/api/v1/users/me":
            return httpx.Response(401)
        return httpx.Response(404)

    monkeypatch.setattr(bb_auth.httpx, "Client", _mock_client_factory(handler))
    config = _config(username="test-student", password="fake-pw")

    http_result = bb_auth._login_http(config)
    assert http_result == {
        "success": False,
        "error": bb_auth._MFA_ERROR,
        "mfa_required": True,
    }

    def fake_login_browser(cfg):
        raise AssertionError(
            "MFA should short-circuit before the browser fallback runs"
        )

    monkeypatch.setattr(bb_auth, "_login_browser", fake_login_browser)
    result = bb_auth.login_direct(config)
    assert result == http_result


# ---------------------------------------------------------------------------
# bb_client -- pagination, caching, and the ambiguous-403 classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_all_results_follows_paging(monkeypatch):
    _install_session()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "cursor=2" in str(request.url):
            return httpx.Response(200, json={"results": [{"id": "b"}], "paging": {}})
        return httpx.Response(
            200,
            json={
                "results": [{"id": "a"}],
                "paging": {"nextPage": "/learn/api/v1/things?cursor=2"},
            },
        )

    _install_mock_client(handler)
    results = await bb_client.get_all_results(_config(), "/learn/api/v1/things")
    assert [r["id"] for r in results] == ["a", "b"]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_get_json_uses_cache_on_second_call(monkeypatch):
    _install_session()
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json={"ok": True})

    _install_mock_client(handler)
    config = _config()
    await bb_client.get_json(config, "/learn/api/v1/x")
    await bb_client.get_json(config, "/learn/api/v1/x")
    assert call_count["n"] == 1  # second call served from cache


@pytest.mark.asyncio
async def test_403_with_working_session_is_permission_denied_not_reauth(monkeypatch):
    """The core Phase 3 finding: a 403 on one resource while `users/me`
    keeps answering 200 means "no permission here", not "session dead" --
    it must not trigger a re-login attempt."""
    _install_session()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/users/me"):
            return httpx.Response(200, json={"id": "_1_1"})
        return httpx.Response(403, json={"status": 403})

    _install_mock_client(handler)
    with pytest.raises(bb_client.PermissionDeniedError):
        await bb_client.get_json(_config(), "/learn/api/v1/courses/_1_1/gradebook/columns")


@pytest.mark.asyncio
async def test_403_with_dead_session_raises_session_expired(monkeypatch):
    _install_session()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"status": 403})  # users/me fails too

    _install_mock_client(handler)
    # auth_mode "sso" has no credentials to auto-reauth with -> clean SessionExpiredError,
    # not an attempted headless login.
    with pytest.raises(bb_client.SessionExpiredError):
        await bb_client.get_json(_config(), "/learn/api/v1/courses/_1_1/gradebook/columns")


@pytest.mark.asyncio
async def test_404_becomes_blackboard_error_not_raw_httpx_exception(monkeypatch):
    _install_session()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    _install_mock_client(handler)
    with pytest.raises(bb_client.BlackboardError):
        await bb_client.get_json(_config(), "/learn/api/v1/courses/_bad_1/contents/ROOT/children")


@pytest.mark.asyncio
async def test_no_session_raises_session_expired_without_any_request(monkeypatch):
    calls = []
    _install_mock_client(lambda r: calls.append(r) or httpx.Response(200)
    )
    with pytest.raises(bb_client.SessionExpiredError):
        await bb_client.get_json(_config(), "/learn/api/v1/users/me")
    assert not calls


@pytest.mark.asyncio
async def test_ensure_fresh_session_refreshes_before_expiry_but_not_when_far_off(
    monkeypatch,
):
    """Pins the proactive-refresh behaviour added to _request: a session
    whose own BbRouter expiry says it is already dead (or dying within
    _REFRESH_MARGIN_SECONDS) must be renewed before the request is even
    sent -- read entirely off the locally stored timestamp, not by waiting
    for the server to first bounce a 302/401 (that reactive path is
    monkeypatched to blow up here, so this test fails loudly if the
    proactive check doesn't actually short-circuit it). A session with a
    comfortably-future expiry must be left alone instead of renewed on
    every single call."""
    config = _config(auth_mode="direct", username="test-student", password="fake-pw")
    login_calls = []

    def fake_login_direct(cfg):
        login_calls.append(cfg)
        bb_session.save_session(
            BASE_URL,
            [
                {
                    "name": "BbRouter",
                    "value": f"expires:{time.time() + 10800:.0f},id:new",
                    "path": "/",
                }
            ],
        )
        return {"success": True, "message": "logged in and session saved"}

    monkeypatch.setattr(bb_auth, "login_direct", fake_login_direct)

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("reactive re-auth should not run here")

    monkeypatch.setattr(bb_client, "_reauth_and_retry", _fail_if_called)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    _install_mock_client(handler)

    past_expiry = time.time() - 10
    bb_session.save_session(
        BASE_URL,
        [
            {
                "name": "BbRouter",
                "value": f"expires:{past_expiry:.0f},id:old",
                "path": "/",
            }
        ],
    )
    result = await bb_client.get_json(config, "/learn/api/v1/users/me", use_cache=False)
    assert result == {"ok": True}
    assert len(login_calls) == 1  # renewed proactively, before the request went out

    result = await bb_client.get_json(config, "/learn/api/v1/users/me", use_cache=False)
    assert result == {"ok": True}
    assert len(login_calls) == 1  # the fresh expiry saved just above is left alone


@pytest.mark.asyncio
async def test_request_auto_logs_in_with_no_session_regardless_of_auth_mode_label(
    monkeypatch,
):
    """Two deliberate behaviours pinned down together: a fresh install with
    no session yet logs itself in on the very first tool call instead of
    raising SessionExpiredError, and that auto-login keys off username and
    password being present -- not off auth_mode literally being "direct"
    (see _has_direct_credentials). Someone can leave auth_mode on its
    "sso" default, fill in credentials anyway, and still get automatic
    login/renewal."""
    config = _config(auth_mode="sso", username="test-student", password="fake-pw")
    assert bb_session.load_session(BASE_URL) is None

    login_calls = []

    def fake_login_direct(cfg):
        login_calls.append(cfg)
        bb_session.save_session(
            BASE_URL,
            [
                {
                    "name": "BbRouter",
                    "value": f"expires:{time.time() + 10800:.0f},id:new",
                    "path": "/",
                }
            ],
        )
        return {"success": True, "message": "logged in and session saved"}

    monkeypatch.setattr(bb_auth, "login_direct", fake_login_direct)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    _install_mock_client(handler)

    result = await bb_client.get_json(config, "/learn/api/v1/users/me", use_cache=False)
    assert result == {"ok": True}
    assert len(login_calls) == 1


def test_client_state_is_per_event_loop():
    """bb_client's connection pool and locks used to be module-level
    singletons, which silently bound them to whichever event loop touched
    them first. A second asyncio.run() then died with "Event loop is
    closed" -- found for real while verifying the tools from a script, not
    hypothetically. Each loop must now get its own client and its own locks,
    since httpx clients and asyncio locks both refuse to cross loops.
    """
    states = []

    async def grab():
        states.append(bb_client._state())

    asyncio.run(grab())
    asyncio.run(grab())

    first, second = states
    assert first is not second
    assert first.login_lock is not second.login_lock
    assert first.client_lock is not second.client_lock


# ---------------------------------------------------------------------------
# blackboard_tool -- the parsing fixes found live
# ---------------------------------------------------------------------------


def test_plain_text_handles_both_body_shapes():
    # The dict shape -- what /learn/api/v1/.../announcements actually
    # returns. get_text(separator="\n") inserts a newline at tag
    # boundaries, so nested inline markup like <b> splits the text.
    assert bt._plain_text({"rawText": "<p>Hi <b>there</b></p>"}) == "Hi \nthere"
    # A plain string, as some other endpoints use.
    assert bt._plain_text("<p>Plain</p>") == "Plain"
    assert bt._plain_text(None) == ""
    assert bt._plain_text({}) == ""


def test_summarize_content_item_extracts_file_and_grading_info():
    item = {
        "id": "_100_1",
        "title": "Week 1 Slides",
        "contentHandler": "resource/x-bb-file",
        "description": "",
        "contentDetail": {
            "resource/x-bb-file": {
                "file": {
                    "permanentUrl": "/bbcswebdav/pid-100/xid-1",
                    "fileName": "slides.pdf",
                    "fileSize": 12345,
                    "mimeType": "application/pdf",
                }
            }
        },
    }
    from zoneinfo import ZoneInfo

    summary = bt._summarize_content_item(item, BASE_URL, ZoneInfo("UTC"))
    assert summary["type"] == "file"
    assert summary["has_children"] is False
    assert summary["file"]["download_url"] == f"{BASE_URL}/bbcswebdav/pid-100/xid-1"
    assert summary["file"]["name"] == "slides.pdf"


def test_summarize_content_item_folder_has_children_true():
    from zoneinfo import ZoneInfo

    item = {"id": "_1_1", "title": "Lectures", "contentHandler": "resource/x-bb-folder"}
    summary = bt._summarize_content_item(item, BASE_URL, ZoneInfo("UTC"))
    assert summary["has_children"] is True
    assert "file" not in summary


def test_summarize_content_item_grading_column_due_date_and_points():
    from zoneinfo import ZoneInfo

    item = {
        "id": "_2_1",
        "title": "HW 1",
        "contentHandler": "resource/x-bb-assignment",
        "contentDetail": {
            "resource/x-bb-assignment": {
                "gradingColumn": {
                    "dueDate": "2026-01-15T20:59:00.000Z",
                    "possible": 100.0,
                    "id": "_col_1",
                }
            }
        },
    }
    summary = bt._summarize_content_item(item, BASE_URL, ZoneInfo("UTC"))
    assert summary["points_possible"] == 100.0
    assert summary["due_date"] == "2026-01-15T20:59:00+00:00"


def test_friendly_type_maps_known_and_unknown_handlers():
    assert bt._friendly_type("resource/x-bb-folder") == "folder"
    assert bt._friendly_type("resource/x-bb-bltiplacement-Pearson LTI1.3") == "external_tool"
    assert bt._friendly_type(None) == "unknown"
    assert bt._friendly_type("resource/something-new") == "resource/something-new"


@pytest.mark.asyncio
async def test_load_favorite_course_ids_parses_the_json_string_value(monkeypatch):
    """The real bug: this endpoint returns {"value": "<json-encoded
    string>"}, not a {"results": [...]} list like everything else."""

    async def fake_get_json(config, path, params=None, *, use_cache=True):
        return {"value": json.dumps({"_1_1": True, "_2_1": False}), "key": "favorite.courses"}

    monkeypatch.setattr(bb_client, "get_json", fake_get_json)
    favorites = await bt._load_favorite_course_ids(_config())
    assert favorites == {"_1_1"}


@pytest.mark.asyncio
async def test_load_favorite_course_ids_tolerates_garbage(monkeypatch):
    async def fake_get_json(config, path, params=None, *, use_cache=True):
        return {"value": "not json"}

    monkeypatch.setattr(bb_client, "get_json", fake_get_json)
    assert await bt._load_favorite_course_ids(_config()) == set()


@pytest.mark.asyncio
async def test_bb_get_assignments_filters_by_real_item_source_type(monkeypatch):
    """Confirmed live: every gradable calendar item reports itemSourceType
    'blackboard.platform.gradebook2.GradableItem' -- the draft's three
    guessed type strings never matched anything."""
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    async def fake_get_json(config, path, params=None, *, use_cache=True):
        return {
            "results": [
                {
                    "itemSourceId": "_g1_1",
                    "itemSourceType": "blackboard.platform.gradebook2.GradableItem",
                    "calendarId": "_c1_1",
                    "title": "HW 1",
                    "startDate": recent,
                    "endDate": recent,
                },
                {
                    "itemSourceId": "_g2_1",
                    "itemSourceType": "blackboard.platform.calendar.CourseMeeting",
                    "calendarId": "_c1_1",
                    "title": "Lecture (not gradable)",
                    "startDate": recent,
                    "endDate": recent,
                },
            ],
            "paging": {},
        }

    monkeypatch.setattr(bb_client, "get_json", fake_get_json)
    monkeypatch.setattr(bb_config, "load_config", lambda: _config())

    result = await bt.bb_get_assignments()
    assert result["success"] is True
    titles = [a["title"] for a in result["assignments"]]
    assert titles == ["HW 1"]  # the non-gradable calendar item is excluded
    assert result["assignments"][0]["status"] == "overdue"  # due date is in the past


@pytest.mark.asyncio
async def test_calendar_items_enforces_the_window_and_dedupes(monkeypatch):
    """The calendar endpoint's paging.nextPage carries only `until` and
    drops `since`, so following it walks back through years of history and
    re-covers the first page as it goes. Measured live: a 28-day window
    gave 15 items on page 1 and 307 on page 2, back to 2022. The window has
    to be enforced here, and the echoes de-duplicated, or a caller asking
    for two weeks gets four years with everything listed twice.
    """
    now = datetime.now(timezone.utc)
    inside = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    ancient = "2022-10-24T09:00:00.000Z"
    in_window = {
        "itemSourceId": "_g1_1",
        "itemSourceType": bt._GRADABLE_ITEM_TYPE,
        "calendarId": "_c1_1",
        "title": "In window",
        "startDate": inside,
        "endDate": inside,
    }
    out_of_window = {
        "itemSourceId": "_old_1",
        "itemSourceType": bt._GRADABLE_ITEM_TYPE,
        "calendarId": "_c1_1",
        "title": "Years ago",
        "startDate": ancient,
        "endDate": ancient,
    }
    pages = [
        {"results": [in_window], "paging": {"nextPage": "/page2"}},
        # Page 2 has no `since`: it repeats page 1 and drags in history.
        {"results": [in_window, out_of_window], "paging": {}},
    ]
    calls = []

    async def fake_get_json(config, path, params=None, *, use_cache=True):
        calls.append(path)
        return pages[min(len(calls) - 1, len(pages) - 1)]

    monkeypatch.setattr(bb_client, "get_json", fake_get_json)
    monkeypatch.setattr(bb_config, "load_config", lambda: _config())

    result = await bt.bb_get_assignments(days_back=14, days_ahead=14)
    assert result["success"] is True
    titles = [a["title"] for a in result["assignments"]]
    assert titles == ["In window"]  # no duplicate, and nothing from 2022


def test_is_container_uses_the_api_flag_not_the_handler_name():
    """Ultra "lessons" are containers too, and the only reliable signal is
    contentDetail's own isFolder -- matching on the handler name missed
    them, so opening a lesson came back with an empty body and looked like
    a failure when there was simply never any text to return."""
    lesson = {
        "contentHandler": "resource/x-bb-lesson",
        "contentDetail": {"resource/x-bb-lesson": {"isLesson": True, "isFolder": True}},
    }
    folder = {
        "contentHandler": "resource/x-bb-folder",
        "contentDetail": {"resource/x-bb-folder": {"isFolder": True}},
    }
    a_file = {
        "contentHandler": "resource/x-bb-file",
        "contentDetail": {"resource/x-bb-file": {"file": {"fileName": "x.pdf"}}},
    }
    assert bt._is_container(lesson) is True
    assert bt._is_container(folder) is True
    assert bt._is_container(a_file) is False
    # No contentDetail at all -- fall back to the handler name.
    assert bt._is_container({"contentHandler": "resource/x-bb-folder"}) is True


@pytest.mark.asyncio
async def test_bb_get_item_lists_children_for_a_container(monkeypatch):
    """A lesson has no body of its own, so returning only its empty text
    reads as a broken tool. It must list what's inside instead."""
    lesson = {
        "id": "_lesson_1",
        "title": "Week 1",
        "contentHandler": "resource/x-bb-lesson",
        "body": {"rawText": ""},
        "contentDetail": {"resource/x-bb-lesson": {"isFolder": True}},
    }
    child = {
        "id": "_file_1",
        "title": "Slides",
        "contentHandler": "resource/x-bb-file",
        "contentDetail": {
            "resource/x-bb-file": {
                "file": {"permanentUrl": "/bbcswebdav/x", "fileName": "slides.pdf"}
            }
        },
    }

    async def fake_get_json(config, path, params=None, *, use_cache=True):
        return lesson

    async def fake_get_all_results(config, path, params=None, *, max_items=1000, use_cache=True):
        assert path.endswith("/children")
        return [child]

    monkeypatch.setattr(bb_client, "get_json", fake_get_json)
    monkeypatch.setattr(bb_client, "get_all_results", fake_get_all_results)
    monkeypatch.setattr(bb_config, "load_config", lambda: _config())

    result = await bt.bb_get_item("_c_1", "_lesson_1")
    assert result["success"] is True
    assert result["item"]["type"] == "lesson"
    assert result["item"]["has_children"] is True
    assert [c["title"] for c in result["item"]["children"]] == ["Slides"]


@pytest.mark.asyncio
async def test_bb_get_assignment_detail_accepts_a_gradebook_column_id(monkeypatch):
    """bb_get_assignments hands out gradebook column ids, bb_get_course_content
    hands out content ids, and the contents endpoint answers a flat 403 for
    the former -- which is exactly how this failed in real use. Either id
    must now resolve, by following a column's own contentId."""
    content = {
        "id": "_content_1",
        "title": "HW 1",
        "contentHandler": "resource/x-bb-assignment",
        "body": {"rawText": "<p>Do the thing</p>"},
        "contentDetail": {
            "resource/x-bb-assignment": {
                "gradingColumn": {"id": "_col_1", "possible": 100.0, "gradesReleased": True}
            }
        },
    }

    async def fake_get_json(config, path, params=None, *, use_cache=True):
        if path.endswith("/contents/_col_1"):
            raise bb_client.PermissionDeniedError("403 -- that's a column, not content")
        if path.endswith("/gradebook/columns/_col_1"):
            return {"contentId": "_content_1", "columnName": "HW 1", "possible": 100.0}
        if path.endswith("/contents/_content_1"):
            return content
        if path.endswith("/attempts"):
            return {"lookup": {"_g_1": [{"userId": "_u_1", "status": "COMPLETED",
                                         "displayGrade": {"score": 88.0}}]}}
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(bb_client, "get_json", fake_get_json)
    monkeypatch.setattr(bb_config, "load_config", lambda: _config())

    result = await bt.bb_get_assignment_detail("_c_1", "_col_1")
    assert result["success"] is True
    assert result["item"]["title"] == "HW 1"
    assert result["item"]["submission"]["score"] == 88.0


@pytest.mark.asyncio
async def test_bb_get_grades_extracts_score_from_attempts_lookup(monkeypatch):
    """The real shape found live: {"lookup": {"<gradeId>": [<attempt>]}},
    not a flat per-user record."""

    async def fake_get_json(config, path, params=None, *, use_cache=True):
        if path.endswith("/users/me"):
            return {"id": "_140068_1"}
        return {
            "lookup": {
                "_grade_1": [
                    {
                        "userId": "_140068_1",
                        "status": "COMPLETED",
                        "displayGrade": {"score": 91.5},
                        "attemptDate": "2026-01-10T10:00:00.000Z",
                        "attemptLastGradedDate": "2026-01-11T10:00:00.000Z",
                    }
                ]
            },
            "permissions": {},
        }

    async def fake_get_all_results(config, path, params=None, *, max_items=1000, use_cache=True):
        return [
            {"id": "_col_1", "columnName": "Homework 1", "possible": 100.0, "gradesReleased": True},
            {"id": "_col_2", "columnName": "Homework 2 (ungraded)", "possible": 100.0, "gradesReleased": False},
        ]

    async def fake_get_json_ungraded_aware(config, path, params=None, *, use_cache=True):
        if path.endswith("/users/me"):
            return {"id": "_140068_1"}
        if "_col_2" in path:
            return {"lookup": {}, "permissions": {}}
        return await fake_get_json(config, path, params, use_cache=use_cache)

    monkeypatch.setattr(bb_client, "get_json", fake_get_json_ungraded_aware)
    monkeypatch.setattr(bb_client, "get_all_results", fake_get_all_results)
    monkeypatch.setattr(bb_config, "load_config", lambda: _config())

    result = await bt.bb_get_grades("_course_1")
    assert result["success"] is True
    assert len(result["grades"]) == 1  # ungraded column excluded by default
    assert result["grades"][0]["score"] == 91.5
    assert result["grades"][0]["name"] == "Homework 1"

    result_all = await bt.bb_get_grades("_course_1", include_ungraded=True)
    assert len(result_all["grades"]) == 2
    ungraded = next(g for g in result_all["grades"] if g["name"] == "Homework 2 (ungraded)")
    assert ungraded["score"] is None


@pytest.mark.asyncio
async def test_bb_get_grades_reports_gradebook_403_as_clean_error(monkeypatch):
    async def fake_get_json(config, path, params=None, *, use_cache=True):
        return {"id": "_140068_1"}

    async def fake_get_all_results(config, path, params=None, *, max_items=1000, use_cache=True):
        raise bb_client.PermissionDeniedError("no permission")

    monkeypatch.setattr(bb_client, "get_json", fake_get_json)
    monkeypatch.setattr(bb_client, "get_all_results", fake_get_all_results)
    monkeypatch.setattr(bb_config, "load_config", lambda: _config())

    result = await bt.bb_get_grades("_course_1")
    assert result["success"] is False
    assert "gradebook" in result["error"] or "grades" in result["error"]


@pytest.mark.asyncio
async def test_tools_report_not_configured_cleanly(monkeypatch):
    monkeypatch.setattr(bb_config, "load_config", lambda: _config(base_url=""))
    result = await bt.bb_get_courses()
    assert result["success"] is False
    assert "not configured" in result["error"].lower()
