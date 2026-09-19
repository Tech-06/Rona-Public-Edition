from types import SimpleNamespace

from rona_cli import envio
from rona_cli.commands.edit import model as edit_model

from .helpers import make_root


def _args(root, **overrides):
    defaults = {
        "root": str(root),
        "json": False,
        "target": "flash",
        "name": None,
        "url": None,
        "key": None,
        "headers": None,
        "test": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _write_env(root, **values):
    (root / "backend" / ".env").write_text(
        "\n".join(f"{k}={v}" for k, v in values.items()) + "\n", encoding="utf-8"
    )


def test_non_interactive_writes_only_given_fields(tmp_path, capsys):
    root = make_root(tmp_path)
    _write_env(
        root,
        FLASH_MODEL="old-model",
        FLASH_MODEL_URL="http://old",
        FLASH_MODEL_API="old-key",
    )
    code = edit_model._cmd(_args(root, name="new-model"))
    assert code == 0
    env = envio.read_env_file(root / "backend" / ".env")
    assert env["FLASH_MODEL"] == "new-model"
    assert env["FLASH_MODEL_URL"] == "http://old"
    assert env["FLASH_MODEL_API"] == "old-key"


def test_writes_headers_as_normalized_json(tmp_path):
    root = make_root(tmp_path)
    _write_env(root, FLASH_MODEL="m", FLASH_MODEL_URL="http://x", FLASH_MODEL_API="k")
    code = edit_model._cmd(_args(root, headers='{"x-foo": "bar"}'))
    assert code == 0
    env = envio.read_env_file(root / "backend" / ".env")
    assert env["FLASH_MODEL_HEADERS"] == '{"x-foo": "bar"}'


def test_invalid_headers_json_fails_without_writing(tmp_path, capsys):
    root = make_root(tmp_path)
    _write_env(root, FLASH_MODEL="m", FLASH_MODEL_URL="http://x", FLASH_MODEL_API="k")
    original = (root / "backend" / ".env").read_text(encoding="utf-8")
    code = edit_model._cmd(_args(root, headers="not-json"))
    assert code == 1
    assert (root / "backend" / ".env").read_text(encoding="utf-8") == original


def test_test_flag_success_then_writes(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_env(root, FLASH_MODEL="m", FLASH_MODEL_URL="http://old", FLASH_MODEL_API="old-key")
    fake_api.set_route("POST", "/chat/completions", 200, {})
    code = edit_model._cmd(
        _args(root, url=f"http://127.0.0.1:{fake_api.port}", key="new-key", test=True)
    )
    assert code == 0
    env = envio.read_env_file(root / "backend" / ".env")
    assert env["FLASH_MODEL_API"] == "new-key"


def test_test_flag_failure_in_json_mode_aborts_without_writing(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_env(root, FLASH_MODEL="m", FLASH_MODEL_URL="http://old", FLASH_MODEL_API="old-key")
    original = (root / "backend" / ".env").read_text(encoding="utf-8")
    fake_api.set_route("POST", "/chat/completions", 500, {"error": "boom"})
    code = edit_model._cmd(
        _args(
            root,
            json=True,
            url=f"http://127.0.0.1:{fake_api.port}",
            key="bad-key",
            test=True,
        )
    )
    assert code == 1
    assert (root / "backend" / ".env").read_text(encoding="utf-8") == original


def test_embedding_target_only_touches_name_and_key(tmp_path):
    root = make_root(tmp_path)
    _write_env(root, FLASH_MODEL="m", FLASH_MODEL_URL="http://x", FLASH_MODEL_API="k")
    code = edit_model._cmd(
        _args(root, target="embedding", name="embedding-001", key="google-key")
    )
    assert code == 0
    env = envio.read_env_file(root / "backend" / ".env")
    assert env["EMBEDDING_MODEL_NAME"] == "embedding-001"
    assert env["GOOGLE_API_KEY"] == "google-key"
    assert env["FLASH_MODEL"] == "m"  # untouched by the embedding edit


def test_json_mode_with_no_fields_does_not_prompt(tmp_path):
    root = make_root(tmp_path)
    _write_env(root, FLASH_MODEL="m", FLASH_MODEL_URL="http://x", FLASH_MODEL_API="k")
    # If this accidentally tried input(), pytest's captured stdin would
    # raise OSError/EOFError -- reaching a return code at all is the proof
    # it took the non-interactive branch.
    code = edit_model._cmd(_args(root, json=True))
    assert code == 0


def test_unknown_root_returns_error(tmp_path):
    code = edit_model._cmd(_args(tmp_path / "does-not-exist"))
    assert code == 1
