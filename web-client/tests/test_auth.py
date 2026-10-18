"""Dashboard login: password hashing, session cookie, route protection."""

import time

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import webui.server as server_module
from conftest import PASSWORD, SESSION_SECRET, TEST_AUTH_TOKEN
from webui import auth, envwrite, proxy
from webui.config import Settings

# Shared with cli/tests/test_webauth.py -- the two implementations must agree.
VECTOR_PASSWORD = "correct horse battery staple"
VECTOR_SALT = bytes(range(16))
VECTOR_HASH = "scrypt$32768$8$1$AAECAwQFBgcICQoLDA0ODw$eo40JB24mNWRdcaWU4xBdGepdf_laQaEJfFhiNMVnFg"


@pytest.fixture(autouse=True)
def fake_proxy(monkeypatch):
    async def fake_proxy_request(request, backend_path):
        return JSONResponse({"proxied": backend_path})

    monkeypatch.setattr(proxy, "proxy_request", fake_proxy_request)


def _login(client, password=PASSWORD):
    return client.post("/auth/login", json={"password": password})


# -- hashing ---------------------------------------------------------------------


def test_hash_format_and_roundtrip(password_hash):
    scheme, n, r, p, salt, digest = password_hash.split("$")
    assert (scheme, n, r, p) == ("scrypt", "32768", "8", "1")
    assert "=" not in salt + digest
    assert auth.verify_password(PASSWORD, password_hash)
    assert not auth.verify_password("wrong password", password_hash)


def test_hash_uses_fresh_salt(password_hash):
    assert auth.hash_password(PASSWORD) != password_hash


def test_fixed_vector():
    assert auth.hash_password(VECTOR_PASSWORD, salt=VECTOR_SALT) == VECTOR_HASH
    assert auth.verify_password(VECTOR_PASSWORD, VECTOR_HASH)


@pytest.mark.parametrize(
    "stored",
    ["", "garbage", "scrypt$1$2$3", "bcrypt$32768$8$1$AAEC$AAEC", "scrypt$x$8$1$AAEC$AAEC",
     "scrypt$32768$8$1$!!$!!", "scrypt$32768$8$1$AAEC$", "scrypt$99999999999$8$1$AAEC$AAEC"],
)
def test_malformed_hash_is_false(stored):
    assert auth.verify_password(PASSWORD, stored) is False


# -- env writer ------------------------------------------------------------------


@pytest.mark.parametrize("value", ["a\nB=1", "a\rb", "a\x00b"])
def test_envwrite_rejects_line_injection(tmp_path, value):
    path = tmp_path / ".env"
    with pytest.raises(envwrite.EnvValueError):
        envwrite.write_env_updates(path, {"KEY": value})
    assert not path.exists()


def test_envwrite_rejects_bad_key(tmp_path):
    with pytest.raises(envwrite.EnvValueError):
        envwrite.write_env_updates(tmp_path / ".env", {"BAD KEY": "x"})


def test_envwrite_replaces_in_place_and_keeps_backup(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# c\nA=1\nB=2\n", encoding="utf-8")
    envwrite.write_env_updates(path, {"A": "9", "C": "3"})
    assert path.read_text(encoding="utf-8") == "# c\nA=9\nB=2\nC=3\n"
    assert path.with_suffix(".bak").read_text(encoding="utf-8") == "# c\nA=1\nB=2\n"


# -- protection ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/x"),
        ("post", "/chat"),
        ("post", "/chat/stream"),
        ("get", "/health"),
        ("get", "/host/server"),
        ("get", "/host/packages/available"),
        ("post", "/host/packages/install"),
    ],
)
def test_protected_routes_need_a_session(client, method, path):
    kwargs = {"json": {}} if method == "post" else {}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 401
    assert response.json()["code"] == "login_required"


def test_public_routes_stay_reachable(client, monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<html lang=\"tr\"><head></head></html>", encoding="utf-8")
    monkeypatch.setattr(server_module, "DIST_DIR", tmp_path)
    monkeypatch.setattr(server_module, "_index_html_cache", None)
    app_client = TestClient(server_module.create_app(), base_url="http://localhost")
    assert app_client.get("/auth/status").status_code == 200
    assert app_client.get("/host/healthz").status_code == 200
    assert app_client.get("/").status_code == 200


def test_healthz_exposes_nothing_sensitive(client):
    assert set(client.get("/host/healthz").json()) == {
        "service", "pid", "uptime_seconds", "frontend_stale"
    }


def test_status_reports_state(client):
    assert client.get("/auth/status").json() == {"authenticated": False, "password_set": True}
    _login(client)
    assert client.get("/auth/status").json() == {"authenticated": True, "password_set": True}


# -- login -----------------------------------------------------------------------


def test_login_sets_strict_httponly_cookie_and_unlocks(client):
    response = _login(client)
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("rona_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie or "SameSite=Strict" in cookie
    assert "Path=/" in cookie
    assert f"Max-Age={30 * 86400}" in cookie
    assert "Secure" not in cookie
    protected = client.get("/api/x")
    assert protected.status_code == 200
    assert protected.json() == {"proxied": "/api/x"}


def test_wrong_password_is_401(client):
    response = _login(client, "nope nope nope")
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_password"
    assert "set-cookie" not in response.headers


def test_sixth_failure_is_rate_limited(client):
    for _ in range(5):
        assert _login(client, "nope nope nope").status_code == 401
    response = _login(client, "nope nope nope")
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "too_many_attempts"
    assert 0 < body["retry_after"] <= 300
    assert response.headers["retry-after"] == str(body["retry_after"])
    # Even the right password is refused while locked out.
    assert _login(client).status_code == 429


def test_success_clears_the_failure_counter(client):
    for _ in range(4):
        _login(client, "nope nope nope")
    assert _login(client).status_code == 200
    for _ in range(5):
        assert _login(client, "nope nope nope").status_code == 401


def test_failures_expire_after_the_window(client, monkeypatch):
    for _ in range(5):
        _login(client, "nope nope nope")
    assert _login(client).status_code == 429
    real_time = time.time
    monkeypatch.setattr(auth.time, "time", lambda: real_time() + auth.FAILURE_WINDOW_SECONDS + 5)
    assert _login(client).status_code == 200


def test_failure_table_is_bounded(monkeypatch):
    monkeypatch.setattr(auth, "_MAX_TRACKED_CLIENTS", 10)
    now = time.time()
    for index in range(50):
        auth._record_failure(f"10.0.0.{index}", now)
    assert len(auth._failures) <= 10


def test_login_when_no_password_is_409(client, env_path):
    env_path.write_text("", encoding="utf-8")
    response = _login(client)
    assert response.status_code == 409
    assert response.json()["code"] == "password_not_set"
    assert client.get("/auth/status").json() == {"authenticated": False, "password_set": False}
    assert client.get("/api/x").status_code == 401


def test_secure_flag_follows_forwarded_proto(client):
    plain = _login(client)
    assert "Secure" not in plain.headers["set-cookie"]
    forwarded = client.post(
        "/auth/login", json={"password": PASSWORD}, headers={"X-Forwarded-Proto": "https"}
    )
    assert "Secure" in forwarded.headers["set-cookie"]


@pytest.mark.parametrize(("mode", "expected"), [("true", True), ("false", False)])
def test_secure_flag_can_be_forced(client, monkeypatch, mode, expected):
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: Settings(_env_file=None, auth_token=TEST_AUTH_TOKEN, web_cookie_secure=mode),
    )
    headers = {"X-Forwarded-Proto": "https"} if mode == "false" else {}
    response = client.post("/auth/login", json={"password": PASSWORD}, headers=headers)
    assert ("Secure" in response.headers["set-cookie"]) is expected


# -- session validity ------------------------------------------------------------


def test_tampered_signature_is_rejected(authed_client):
    token = authed_client.cookies.get("rona_session")
    payload, _, signature = token.partition(".")
    authed_client.cookies.set("rona_session", f"{payload}.{'A' * len(signature)}")
    assert authed_client.get("/api/x").status_code == 401


def test_tampered_payload_is_rejected(authed_client):
    token = authed_client.cookies.get("rona_session")
    _, _, signature = token.partition(".")
    forged = auth._b64(b'{"exp":9999999999,"pv":"0000000000000000"}')
    authed_client.cookies.set("rona_session", f"{forged}.{signature}")
    assert authed_client.get("/api/x").status_code == 401


def test_expired_session_is_rejected(client, password_hash):
    token = auth.make_session_token(
        password_hash, SESSION_SECRET, days=1, now=time.time() - 3 * 86400
    )
    client.cookies.set("rona_session", token)
    assert client.get("/api/x").status_code == 401


def test_session_from_another_secret_is_rejected(client, password_hash):
    client.cookies.set(
        "rona_session", auth.make_session_token(password_hash, "other-secret", days=1)
    )
    assert client.get("/api/x").status_code == 401


def test_garbage_cookie_is_rejected(client):
    for value in ("", "x", "a.b", "....", "e30.e30"):
        client.cookies.set("rona_session", value)
        assert client.get("/api/x").status_code == 401


def test_logout_clears_the_cookie(authed_client):
    response = authed_client.post("/auth/logout", json={})
    assert response.status_code == 200
    assert "rona_session=" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert authed_client.get("/api/x").status_code == 401


def test_logout_without_session_is_fine(client):
    assert client.post("/auth/logout", json={}).status_code == 200


def test_credentials_are_reread_when_env_changes(authed_client, env_path):
    assert authed_client.get("/api/x").status_code == 200
    env_path.write_text(
        f"WEB_PASSWORD_HASH={auth.hash_password('another long password')}\n"
        f"WEB_SESSION_SECRET={SESSION_SECRET}\n",
        encoding="utf-8",
    )
    # Bump mtime explicitly: coarse filesystem timestamps could tie.
    stat = env_path.stat()
    import os

    os.utime(env_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert authed_client.get("/api/x").status_code == 401


def test_environment_overrides_env_file(client, monkeypatch):
    monkeypatch.setenv("WEB_PASSWORD_HASH", auth.hash_password("from the environment"))
    assert _login(client).status_code == 401
    assert _login(client, "from the environment").status_code == 200


def test_missing_session_secret_uses_ephemeral_key(client, env_path, password_hash, caplog):
    env_path.write_text(f"WEB_PASSWORD_HASH={password_hash}\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="uvicorn.error"):
        assert _login(client).status_code == 200
        assert client.get("/api/x").status_code == 200
    assert sum("WEB_SESSION_SECRET" in record.getMessage() for record in caplog.records) == 1


# -- password change -------------------------------------------------------------


def test_change_password_rotates_everything(authed_client, env_path):
    old_cookie = authed_client.cookies.get("rona_session")
    old_env = envwrite.read_env_file(env_path)

    response = authed_client.post(
        "/auth/password", json={"current": PASSWORD, "new": "a brand new password"}
    )
    assert response.status_code == 200

    new_env = envwrite.read_env_file(env_path)
    assert new_env["WEB_PASSWORD_HASH"] != old_env["WEB_PASSWORD_HASH"]
    assert new_env["WEB_SESSION_SECRET"] != old_env["WEB_SESSION_SECRET"]
    assert auth.verify_password("a brand new password", new_env["WEB_PASSWORD_HASH"])

    new_cookie = authed_client.cookies.get("rona_session")
    assert new_cookie != old_cookie
    assert authed_client.get("/api/x").status_code == 200  # fresh cookie works

    authed_client.cookies.set("rona_session", old_cookie)
    assert authed_client.get("/api/x").status_code == 401  # old one is dead

    authed_client.cookies.clear()
    assert _login(authed_client).status_code == 401
    assert _login(authed_client, "a brand new password").status_code == 200


def test_change_password_rejects_short_new_password(authed_client, env_path):
    before = env_path.read_text(encoding="utf-8")
    response = authed_client.post("/auth/password", json={"current": PASSWORD, "new": "abc"})
    assert response.status_code == 400
    assert response.json()["code"] == "password_too_short"
    assert env_path.read_text(encoding="utf-8") == before


def test_change_password_rejects_wrong_current(authed_client, env_path):
    before = env_path.read_text(encoding="utf-8")
    response = authed_client.post(
        "/auth/password", json={"current": "wrong wrong wrong", "new": "a brand new password"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_password"
    assert env_path.read_text(encoding="utf-8") == before


def test_change_password_requires_a_session(client):
    response = client.post(
        "/auth/password", json={"current": PASSWORD, "new": "a brand new password"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "login_required"


# -- startup guard ---------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.5", "::1", "[::1]", "localhost"])
def test_loopback_hosts(host):
    assert auth.is_loopback_host(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "::", "example.com"])
def test_non_loopback_hosts(host):
    assert not auth.is_loopback_host(host)


def test_public_host_without_password_refuses_to_start(env_path, monkeypatch, tmp_path):
    env_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(server_module, "PID_PATH", tmp_path / "webui.pid")
    monkeypatch.setattr(
        server_module,
        "settings",
        Settings(_env_file=None, auth_token=TEST_AUTH_TOKEN, web_host="0.0.0.0"),
    )
    with pytest.raises(RuntimeError, match="0.0.0.0"):
        with TestClient(server_module.create_app(), base_url="http://localhost"):
            pass


def test_public_host_with_password_starts(monkeypatch, tmp_path):
    monkeypatch.setattr(server_module, "PID_PATH", tmp_path / "webui.pid")
    monkeypatch.setattr(
        server_module,
        "settings",
        Settings(_env_file=None, auth_token=TEST_AUTH_TOKEN, web_host="0.0.0.0"),
    )
    with TestClient(server_module.create_app(), base_url="http://localhost"):
        pass


def test_loopback_without_password_only_warns(env_path, caplog):
    env_path.write_text("", encoding="utf-8")
    with caplog.at_level("WARNING", logger="uvicorn.error"):
        auth.check_startup("127.0.0.1")
    assert any("rona web password" in record.getMessage() for record in caplog.records)


# -- settings --------------------------------------------------------------------


def test_auth_token_needs_32_characters():
    with pytest.raises(ValueError):
        Settings(_env_file=None, auth_token="short")


def test_cookie_secure_setting_is_validated():
    assert Settings(_env_file=None, auth_token="t" * 32, web_cookie_secure="TRUE").web_cookie_secure == "true"
    with pytest.raises(ValueError, match="web_cookie_secure"):
        Settings(_env_file=None, auth_token="t" * 32, web_cookie_secure="maybe")
