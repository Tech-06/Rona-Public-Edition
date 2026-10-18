from installer import envgen
from rona_cli import envio

LONG_TOKEN = "t" * 40


def test_materialize_env_copies_example_with_comments_intact(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("# a helpful comment\nAUTH_TOKEN=\nFLASH_MODEL=\n", encoding="utf-8")
    env_path = tmp_path / ".env"

    envgen.materialize_env(example, env_path)

    text = env_path.read_text(encoding="utf-8")
    assert "# a helpful comment" in text
    assert "AUTH_TOKEN=" in text


def test_materialize_env_does_not_overwrite_existing_file(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("AUTH_TOKEN=\n", encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text("AUTH_TOKEN=already-set\nFLASH_MODEL_API=secret\n", encoding="utf-8")

    envgen.materialize_env(example, env_path)

    text = env_path.read_text(encoding="utf-8")
    assert "already-set" in text
    assert "secret" in text


def test_materialize_env_creates_empty_file_when_example_missing(tmp_path):
    env_path = tmp_path / ".env"
    envgen.materialize_env(tmp_path / "does-not-exist.example", env_path)
    assert env_path.exists()
    assert env_path.read_text(encoding="utf-8") == ""


def test_ensure_auth_token_generates_when_absent(tmp_path):
    root = tmp_path / "root"
    (root / "backend").mkdir(parents=True)
    (root / "web-client").mkdir(parents=True)
    (root / "backend" / ".env").write_text("", encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")

    token = envgen.ensure_auth_token(root, install_web=True)

    assert len(token) > 20
    assert envio.read_env_file(root / "backend" / ".env")["AUTH_TOKEN"] == token
    assert envio.read_env_file(root / "web-client" / ".env")["AUTH_TOKEN"] == token


def test_ensure_auth_token_reuses_existing_backend_token(tmp_path):
    root = tmp_path / "root"
    (root / "backend").mkdir(parents=True)
    (root / "web-client").mkdir(parents=True)
    (root / "backend" / ".env").write_text(f"AUTH_TOKEN={LONG_TOKEN}\n", encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")

    token = envgen.ensure_auth_token(root, install_web=True)

    assert token == LONG_TOKEN
    assert envio.read_env_file(root / "web-client" / ".env")["AUTH_TOKEN"] == LONG_TOKEN


def test_ensure_auth_token_skips_web_when_not_installing_it(tmp_path):
    root = tmp_path / "root"
    (root / "backend").mkdir(parents=True)
    (root / "web-client").mkdir(parents=True)
    (root / "backend" / ".env").write_text("", encoding="utf-8")
    (root / "web-client" / ".env").write_text("UNRELATED=1\n", encoding="utf-8")

    envgen.ensure_auth_token(root, install_web=False)

    assert "AUTH_TOKEN" not in envio.read_env_file(root / "web-client" / ".env")


def _make_root(tmp_path, backend_env: str):
    root = tmp_path / "root"
    (root / "backend").mkdir(parents=True)
    (root / "web-client").mkdir(parents=True)
    (root / "backend" / ".env").write_text(backend_env, encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")
    return root


def test_ensure_auth_token_replaces_short_existing_token(tmp_path):
    root = _make_root(tmp_path, "AUTH_TOKEN=short\n")

    token = envgen.ensure_auth_token(root, install_web=True)

    assert token != "short"
    assert len(token) >= envgen.MIN_TOKEN_LENGTH
    assert envio.read_env_file(root / "backend" / ".env")["AUTH_TOKEN"] == token
    assert envio.read_env_file(root / "web-client" / ".env")["AUTH_TOKEN"] == token


def test_ensure_auth_token_keeps_long_existing_token(tmp_path):
    root = _make_root(tmp_path, f"AUTH_TOKEN={LONG_TOKEN}\n")
    assert envgen.ensure_auth_token(root, install_web=False) == LONG_TOKEN


def test_ensure_auth_token_adds_host_and_reload_when_absent(tmp_path):
    root = _make_root(tmp_path, "")
    envgen.ensure_auth_token(root, install_web=False)
    values = envio.read_env_file(root / "backend" / ".env")
    assert values["HOST"] == "127.0.0.1"
    assert values["RELOAD"] == "false"


def test_ensure_auth_token_preserves_existing_host_and_reload(tmp_path):
    root = _make_root(tmp_path, "HOST=0.0.0.0\nRELOAD=true\n")
    envgen.ensure_auth_token(root, install_web=False)
    values = envio.read_env_file(root / "backend" / ".env")
    assert values["HOST"] == "0.0.0.0"
    assert values["RELOAD"] == "true"
