import sys
from types import SimpleNamespace

from rona_cli.commands.edit import prompt as edit_prompt

from .helpers import make_root


def _write_backend_env(root, port, token="test-token"):
    (root / "backend" / ".env").write_text(
        f"AUTH_TOKEN={token}\nPORT={port}\nHOST=127.0.0.1\n", encoding="utf-8"
    )


def _args(root, **overrides):
    defaults = {
        "root": str(root),
        "json": False,
        "id": None,
        "default": False,
        "file": None,
        "yes": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _prompt_payload(**overrides):
    payload = {
        "id": "user",
        "filename": "user.md",
        "group": "main",
        "customized": False,
        "default_changed": None,
        "updated_at": None,
        "size_bytes": 4,
        "required_placeholders": [],
        "required_nonempty": False,
        "content": "old\n",
        "default_content": "old\n",
        "version": "v1",
        "default_version": "v1",
    }
    payload.update(overrides)
    return payload


def test_list_prints_ids_and_markers(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET",
        "/api/prompts",
        200,
        {
            "prompts": [
                {
                    "id": "user",
                    "filename": "user.md",
                    "group": "main",
                    "customized": True,
                    "default_changed": True,
                    "updated_at": "2026-01-01T00:00:00Z",
                    "size_bytes": 10,
                    "required_placeholders": [],
                    "required_nonempty": False,
                },
                {
                    "id": "persona",
                    "filename": "persona.md",
                    "group": "main",
                    "customized": False,
                    "default_changed": None,
                    "updated_at": None,
                    "size_bytes": 20,
                    "required_placeholders": ["PRIMARY_LANGUAGE_RULE"],
                    "required_nonempty": False,
                },
            ],
            "placeholders": [],
            "max_bytes": 65536,
        },
    )
    code = edit_prompt._cmd_list(_args(root))
    assert code == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    user_line = next(line for line in lines if line.startswith("user"))
    persona_line = next(line for line in lines if line.startswith("persona"))
    assert "main" in user_line
    assert edit_prompt.i18n.t("prompt.customized_marker") in user_line
    assert edit_prompt.i18n.t("prompt.default_changed_marker") in user_line
    assert edit_prompt.i18n.t("prompt.customized_marker") not in persona_line
    assert edit_prompt.i18n.t("prompt.default_changed_marker") not in persona_line


def test_list_json_mode_prints_raw_payload(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    payload = {"prompts": [], "placeholders": [], "max_bytes": 65536}
    fake_api.set_route("GET", "/api/prompts", 200, payload)
    code = edit_prompt._cmd_list(_args(root, json=True))
    assert code == 0
    import json

    assert json.loads(capsys.readouterr().out) == payload


def test_show_default(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET",
        "/api/prompts/user",
        200,
        _prompt_payload(content="custom content\n", default_content="default content\n"),
    )
    code = edit_prompt._cmd_show(_args(root, id="user", default=True))
    assert code == 0
    out = capsys.readouterr().out
    assert "default content" in out
    assert "custom content" not in out


def test_show_without_default_prints_content(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET",
        "/api/prompts/user",
        200,
        _prompt_payload(content="custom content\n", default_content="default content\n"),
    )
    code = edit_prompt._cmd_show(_args(root, id="user"))
    assert code == 0
    out = capsys.readouterr().out
    assert "custom content" in out
    assert "default content" not in out


def test_edit_from_file_puts_base_version(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("GET", "/api/prompts/user", 200, _prompt_payload())
    fake_api.set_route(
        "PUT",
        "/api/prompts/user",
        200,
        _prompt_payload(content="new\n", customized=True, version="v2", warnings=[]),
    )
    file_path = tmp_path / "x.md"
    file_path.write_text("new\n", encoding="utf-8")

    code = edit_prompt._cmd_edit(_args(root, id="user", file=str(file_path)))
    assert code == 0
    put_request = next(r for r in fake_api.requests if r["method"] == "PUT")
    assert put_request["body"] == {"content": "new\n", "base_version": "v1"}
    # --file is the user's own file: it must be left alone, not deleted.
    assert file_path.exists()


def test_edit_with_editor_changes_puts(tmp_path, fake_api, monkeypatch):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("GET", "/api/prompts/user", 200, _prompt_payload())
    fake_api.set_route(
        "PUT",
        "/api/prompts/user",
        200,
        _prompt_payload(content="old\nedited\n", customized=True, version="v2", warnings=[]),
    )

    draft_path = tmp_path / "draft.md"
    monkeypatch.setattr(
        edit_prompt, "_write_temp_prompt", lambda prompt_id, content: _seed(draft_path, content)
    )
    monkeypatch.setattr(
        edit_prompt.env,
        "_editor_command",
        lambda wait=False: [
            sys.executable,
            "-c",
            "import pathlib,sys; p = pathlib.Path(sys.argv[1]); "
            "p.write_text(p.read_text(encoding='utf-8') + 'edited\\n', "
            "encoding='utf-8', newline='\\n')",
        ],
    )

    code = edit_prompt._cmd_edit(_args(root, id="user"))
    assert code == 0
    put_request = next(r for r in fake_api.requests if r["method"] == "PUT")
    assert put_request["body"] == {"content": "old\nedited\n", "base_version": "v1"}
    # Saved successfully -> the temp draft is cleaned up.
    assert not draft_path.exists()


def test_edit_unchanged_skips_put(tmp_path, fake_api, monkeypatch):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("GET", "/api/prompts/user", 200, _prompt_payload())

    draft_path = tmp_path / "draft.md"
    monkeypatch.setattr(
        edit_prompt, "_write_temp_prompt", lambda prompt_id, content: _seed(draft_path, content)
    )
    monkeypatch.setattr(
        edit_prompt.env,
        "_editor_command",
        lambda wait=False: [sys.executable, "-c", "pass"],
    )

    code = edit_prompt._cmd_edit(_args(root, id="user"))
    assert code == 0
    assert not any(r["method"] == "PUT" for r in fake_api.requests)
    assert not draft_path.exists()


def test_edit_conflict_exit_1_keeps_draft(tmp_path, fake_api, monkeypatch):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("GET", "/api/prompts/user", 200, _prompt_payload())
    fake_api.set_route("PUT", "/api/prompts/user", 409, {"detail": "stale base_version"})

    draft_path = tmp_path / "draft.md"
    monkeypatch.setattr(
        edit_prompt, "_write_temp_prompt", lambda prompt_id, content: _seed(draft_path, content)
    )
    monkeypatch.setattr(
        edit_prompt.env,
        "_editor_command",
        lambda wait=False: [
            sys.executable,
            "-c",
            "import pathlib,sys; p = pathlib.Path(sys.argv[1]); "
            "p.write_text(p.read_text(encoding='utf-8') + 'edited\\n', "
            "encoding='utf-8', newline='\\n')",
        ],
    )

    code = edit_prompt._cmd_edit(_args(root, id="user"))
    assert code == 1
    # The draft must survive a failed save -- losing the user's edits
    # because the PUT failed would be worse than a stray temp file.
    assert draft_path.exists()
    assert draft_path.read_text(encoding="utf-8") == "old\nedited\n"


def test_edit_422_exit_1_keeps_draft(tmp_path, fake_api, monkeypatch):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("GET", "/api/prompts/user", 200, _prompt_payload())
    fake_api.set_route("PUT", "/api/prompts/user", 422, {"detail": "missing placeholder"})

    file_path = tmp_path / "bad.md"
    file_path.write_text("bad content\n", encoding="utf-8")

    code = edit_prompt._cmd_edit(_args(root, id="user", file=str(file_path)))
    assert code == 1
    assert file_path.exists()


def test_reset_yes_deletes(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("DELETE", "/api/prompts/user", 200, _prompt_payload())
    code = edit_prompt._cmd_reset(_args(root, id="user", yes=True))
    assert code == 0
    assert fake_api.requests[0]["method"] == "DELETE"


def test_reset_asks_for_confirmation_and_aborts_on_no(tmp_path, fake_api, monkeypatch):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    monkeypatch.setattr(edit_prompt.ui, "confirm", lambda *a, **k: False)
    code = edit_prompt._cmd_reset(_args(root, id="user"))
    assert code == 1
    assert fake_api.requests == []


def _seed(path, content):
    path.write_text(content, encoding="utf-8", newline="\n")
    return path
