"""Tests for the dashboard's per-package configuration and action endpoints.

Packages are created directly under the real ``toolbox/custom/`` directory
(the only place Python's import system can find them as
``toolbox.custom.<id>.<module>``) and always cleaned up, both on disk and in
``sys.modules``, the way test_custom_packages.py does it.
"""

import json
import shutil
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from toolbox import packages, registry

CUSTOM_DIR = packages.CUSTOM_DIR


def _purge_module_cache(package_id: str) -> None:
    prefix = f"toolbox.custom.{package_id}"
    for name in [n for n in sys.modules if n == prefix or n.startswith(prefix + ".")]:
        del sys.modules[name]


@pytest.fixture
def client():
    import app.dashboard as dashboard_module

    application = FastAPI()
    application.include_router(dashboard_module.router)
    return TestClient(application)


@pytest.fixture
def fixture_package(tmp_path, monkeypatch):
    """Install a throwaway package with config and an action."""
    created: list[str] = []
    fake_env = tmp_path / ".env"
    fake_env.write_text("EXISTING_KEY=leave_me_alone\n", encoding="utf-8")
    monkeypatch.setattr(packages, "ENV_PATH", fake_env)

    def make(package_id: str, manifest_extra: dict, files: dict[str, str] | None = None):
        pkg_dir = CUSTOM_DIR / package_id
        pkg_dir.mkdir(parents=True)
        created.append(package_id)
        manifest = {
            "id": package_id,
            "version": "1.0.0",
            "kind": "tool",
            "name": package_id,
            "description": "fixture",
        }
        manifest.update(manifest_extra)
        (pkg_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (pkg_dir / "tools.json").write_text(json.dumps({"tools": []}), encoding="utf-8")
        for name, content in (files or {}).items():
            (pkg_dir / name).write_text(content, encoding="utf-8")
        registry.reload_registry()
        return pkg_dir

    try:
        yield make
    finally:
        for package_id in created:
            shutil.rmtree(CUSTOM_DIR / package_id, ignore_errors=True)
            _purge_module_cache(package_id)
        registry.reload_registry()


ACTION_SOURCE = (
    "def step(config, params, state):\n"
    "    if state is None:\n"
    "        return {'status': 'input_required', 'message': 'paste it',\n"
    "                'fields': [{'key': 'code', 'label': 'Code'}],\n"
    "                'state': {'seen': params.get('who')}}\n"
    "    return {'status': 'ok', 'message': f\"{state['seen']}:{params['code']}\"}\n"
    "\n"
    "def local_only(config, params, state):\n"
    "    return {'status': 'ok', 'message': 'ran'}\n"
)


def test_package_status_exposes_field_metadata_but_hides_cli_only_actions(
    client, fixture_package
):
    fixture_package(
        "dash_pkg",
        {
            "config": [
                {"key": "api_key", "target": "env", "env_var": "DASH_PKG_KEY", "secret": True},
                {"key": "accounts", "type": "list", "target": "config", "required": False},
            ],
            "actions": [
                {"id": "step", "label": "Step", "handler": ".actions:step",
                 "params": [{"key": "who", "required": False}]},
                {"id": "local_only", "handler": ".actions:local_only", "cli_only": True},
            ],
        },
        {"actions.py": ACTION_SOURCE},
    )

    body = client.get("/api/packages").json()
    pkg = next(p for p in body["packages"] if p["id"] == "dash_pkg")

    assert [f["key"] for f in pkg["config_fields"]] == ["api_key", "accounts"]
    assert pkg["config_fields"][0]["secret"] is True
    # Metadata only: /packages never carries values at all.
    assert all("value" not in f for f in pkg["config_fields"])
    # A cli_only action would block a request far longer than it may take, so
    # it is left out rather than shown and then refused.
    assert [a["id"] for a in pkg["actions"]] == ["step"]


def test_package_config_round_trip_never_returns_the_secret(client, fixture_package):
    fixture_package(
        "dash_cfg",
        {
            "config": [
                {"key": "api_key", "target": "env", "env_var": "DASH_CFG_KEY", "secret": True},
                {"key": "accounts", "type": "list", "target": "config", "required": False},
            ]
        },
    )

    before = {f["key"]: f for f in client.get("/api/packages/dash_cfg/config").json()["fields"]}
    assert before["api_key"]["set"] is False

    response = client.put(
        "/api/packages/dash_cfg/config",
        json={"api_key": "s3cret", "accounts": ["work", "home"]},
    )
    assert response.status_code == 200
    assert response.json()["restart_required"] is True

    after = {f["key"]: f for f in client.get("/api/packages/dash_cfg/config").json()["fields"]}
    assert after["accounts"]["value"] == ["work", "home"]
    assert after["api_key"]["set"] is True
    assert after["api_key"]["value"] is None
    assert "s3cret" not in response.text
    assert "s3cret" not in client.get("/api/packages/dash_cfg/config").text

    import os

    os.environ.pop("DASH_CFG_KEY", None)


def test_package_config_rejects_an_unknown_field(client, fixture_package):
    fixture_package("dash_strict", {"config": []})
    assert client.put("/api/packages/dash_strict/config", json={"nope": 1}).status_code == 400


def test_unknown_package_is_404(client):
    assert client.get("/api/packages/not_installed/config").status_code == 404
    assert (
        client.post("/api/packages/not_installed/actions/step", json={}).status_code == 404
    )


def test_action_multi_step_round_trips_state_over_two_requests(client, fixture_package):
    """The whole point of the JSON state: the dashboard can run the two halves
    as two separate requests with nothing held open in between."""
    fixture_package(
        "dash_act",
        {
            "actions": [
                {"id": "step", "handler": ".actions:step",
                 "params": [{"key": "who", "required": False}]}
            ]
        },
        {"actions.py": ACTION_SOURCE},
    )

    first = client.post(
        "/api/packages/dash_act/actions/step", json={"params": {"who": "ada"}}
    ).json()
    assert first["status"] == "input_required"
    assert [f["key"] for f in first["fields"]] == ["code"]
    assert first["state"] == {"seen": "ada"}

    second = client.post(
        "/api/packages/dash_act/actions/step",
        json={"params": {"code": "xyz"}, "state": first["state"]},
    ).json()
    assert second["status"] == "ok"
    assert second["message"] == "ada:xyz"


def test_cli_only_action_is_refused_over_http(client, fixture_package):
    fixture_package(
        "dash_local",
        {"actions": [{"id": "local_only", "handler": ".actions:local_only", "cli_only": True}]},
        {"actions.py": ACTION_SOURCE},
    )

    response = client.post("/api/packages/dash_local/actions/local_only", json={})
    assert response.status_code == 400
    assert "terminal" in response.json()["detail"]


def test_unknown_action_is_a_400_naming_what_exists(client, fixture_package):
    fixture_package(
        "dash_noact",
        {"actions": [{"id": "step", "handler": ".actions:step"}]},
        {"actions.py": ACTION_SOURCE},
    )

    response = client.post("/api/packages/dash_noact/actions/nope", json={})
    assert response.status_code == 400
    assert "step" in response.json()["detail"]


def test_package_status_lists_dependents_and_problems(client, fixture_package):
    fixture_package("dash_base", {"version": "1.0.0"})
    fixture_package("dash_leaf", {"requires": ["dash_base>=2.0"]})

    body = client.get("/api/packages").json()
    by_id = {p["id"]: p for p in body["packages"]}

    # dash_leaf depends on dash_base, so dash_base's dependents list it.
    assert by_id["dash_base"]["dependents"] == ["dash_leaf"]
    assert by_id["dash_leaf"]["dependents"] == []

    # dash_base is only at 1.0.0, dash_leaf wants >=2.0 -- a warning, not a
    # failure to load.
    assert by_id["dash_leaf"]["requirement_problems"]
    assert "dash_base" in by_id["dash_leaf"]["requirement_problems"][0]
    assert by_id["dash_base"]["requirement_problems"] == []

    connections = client.get("/api/connections").json()
    conn_by_id = {p["id"]: p for p in connections["packages"]}
    assert conn_by_id["dash_base"]["dependents"] == ["dash_leaf"]


def test_reload_endpoint_picks_up_changed_code(client, fixture_package):
    fixture_package(
        "dash_reload",
        {"actions": [{"id": "step", "handler": ".actions:step"}]},
        {
            "actions.py": (
                "def step(config, params, state):\n"
                "    return {'status': 'ok', 'message': 'v1'}\n"
            )
        },
    )

    first = client.post("/api/packages/dash_reload/actions/step", json={})
    assert first.json()["message"] == "v1"

    # Simulate what toolbox.manager does after an install/update: the
    # package's files on disk change underneath the running process. The
    # replacement source is a different length than the original -- a
    # stale sys.modules entry (same file path, same mtime resolution) would
    # otherwise still satisfy Python's cache and never re-read the file.
    (packages.CUSTOM_DIR / "dash_reload" / "actions.py").write_text(
        "def step(config, params, state):\n"
        "    return {'status': 'ok', 'message': 'v2, now with a longer message'}\n",
        encoding="utf-8",
    )

    response = client.post("/api/packages/reload")
    assert response.status_code == 200
    body = response.json()
    assert body["purged_modules"] >= 1
    assert "dash_reload" in {p["id"] for p in body["packages"]}

    second = client.post("/api/packages/dash_reload/actions/step", json={})
    assert second.json()["message"] == "v2, now with a longer message"


def test_reload_returns_requirement_warnings(client, fixture_package):
    fixture_package("dash_rbase", {"version": "1.0.0"})
    fixture_package("dash_rleaf", {"requires": ["dash_rbase>=2.0"]})

    response = client.post("/api/packages/reload")
    assert response.status_code == 200
    body = response.json()

    assert any(
        "dash_rleaf" in w and "dash_rbase" in w for w in body["warnings"]
    )


# --- file config fields -----------------------------------------------------

import base64
import os
import sys as _sys

FILE_FIELD_MANIFEST = {
    "config": [
        {"key": "credentials", "target": "file", "dest_filename": "credentials.json"},
        {"key": "note", "target": "config", "required": False},
    ]
}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _upload(client, package_id, key="credentials", data=b'{"a": 1}', filename="x.json"):
    return client.post(
        f"/api/packages/{package_id}/config/file",
        json={"key": key, "filename": filename, "content_b64": _b64(data)},
    )


def test_config_put_rejects_a_path_for_a_file_field_and_copies_nothing(
    client, fixture_package, tmp_path
):
    pkg_dir = fixture_package("dash_file_path", FILE_FIELD_MANIFEST)
    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY", encoding="utf-8")

    response = client.put(
        "/api/packages/dash_file_path/config", json={"credentials": str(secret)}
    )

    assert response.status_code == 400
    assert not (pkg_dir / "credentials.json").exists()
    assert not any(p.read_text(errors="ignore") == "PRIVATE KEY" for p in pkg_dir.iterdir() if p.is_file())


def test_config_put_still_works_for_other_fields_after_a_file_was_uploaded(
    client, fixture_package
):
    pkg_dir = fixture_package("dash_file_mix", FILE_FIELD_MANIFEST)
    assert _upload(client, "dash_file_mix").status_code == 200
    # The stored file's path is merged back by configure_installed; it must
    # not trip the no-paths rule.
    response = client.put("/api/packages/dash_file_mix/config", json={"note": "hi"})
    assert response.status_code == 200
    assert (pkg_dir / "credentials.json").is_file()


def test_manager_path_for_file_field_still_works(fixture_package, tmp_path):
    from toolbox import manager

    pkg_dir = fixture_package("dash_file_cli", FILE_FIELD_MANIFEST)
    source = tmp_path / "creds.json"
    source.write_text('{"ok": true}', encoding="utf-8")

    manager.configure_installed("dash_file_cli", {"credentials": str(source)})

    assert json.loads((pkg_dir / "credentials.json").read_text()) == {"ok": True}

    other = tmp_path / "other.json"
    other.write_text("{}", encoding="utf-8")
    with pytest.raises(manager.ManagerError):
        manager.configure_installed(
            "dash_file_cli", {"credentials": str(other)}, allow_file_paths=False
        )


def test_upload_writes_manifest_named_file_ignoring_client_filename(client, fixture_package):
    pkg_dir = fixture_package("dash_up", FILE_FIELD_MANIFEST)

    response = _upload(client, "dash_up", data=b'{"client_id": "x"}', filename="../../evil.json")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "field": "credentials"}
    assert json.loads((pkg_dir / "credentials.json").read_text()) == {"client_id": "x"}
    assert not (CUSTOM_DIR.parent.parent / "evil.json").exists()
    assert not list(pkg_dir.glob("*.tmp"))
    if _sys.platform != "win32":
        assert (pkg_dir / "credentials.json").stat().st_mode & 0o777 == 0o600
    cfg = {f["key"]: f for f in client.get("/api/packages/dash_up/config").json()["fields"]}
    assert cfg["credentials"]["set"] is True


def test_upload_over_one_mib_is_413(client, fixture_package):
    pkg_dir = fixture_package("dash_big", FILE_FIELD_MANIFEST)
    big = json.dumps({"x": "a" * (1024 * 1024)}).encode()
    assert _upload(client, "dash_big", data=big).status_code == 413
    assert not (pkg_dir / "credentials.json").exists()


def test_upload_rejects_bad_base64_and_non_json(client, fixture_package):
    fixture_package("dash_bad", FILE_FIELD_MANIFEST)
    bad = client.post(
        "/api/packages/dash_bad/config/file",
        json={"key": "credentials", "filename": "a.json", "content_b64": "!!not base64!!"},
    )
    assert bad.status_code == 400
    assert _upload(client, "dash_bad", data=b"not json at all").status_code == 400
    assert _upload(client, "dash_bad", data=b"\xff\xfe\x00").status_code == 400


def test_upload_unknown_key_non_file_field_or_missing_package(client, fixture_package):
    fixture_package("dash_keys", FILE_FIELD_MANIFEST)
    assert _upload(client, "dash_keys", key="nope").status_code == 404
    assert _upload(client, "dash_keys", key="note").status_code == 404
    assert _upload(client, "not_installed").status_code == 404


def test_upload_is_409_while_the_manager_lock_is_held(client, fixture_package):
    from toolbox import manager

    fixture_package("dash_busy", FILE_FIELD_MANIFEST)
    with manager._exclusive_lock():
        # Same process re-locking: flock on a second fd conflicts on POSIX and
        # msvcrt locking does on Windows.
        response = _upload(client, "dash_busy")
    assert response.status_code == 409
