from installer import state


def test_write_then_read_round_trip(tmp_path, monkeypatch):
    fake_state_file = tmp_path / "home" / ".rona" / "config.json"
    monkeypatch.setattr(state, "state_file", lambda: fake_state_file)

    root = tmp_path / "rona-checkout"
    state.write_state(root, {"cli": True, "backend": True, "web": False})

    data = state.read_state()
    assert data["root"] == str(root)
    assert data["components"] == {"cli": True, "backend": True, "web": False}
    assert "installed_at" in data
    assert data["version"] == state.__version__


def test_read_state_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "state_file", lambda: tmp_path / "no-such-file.json")
    assert state.read_state() is None


def test_read_state_corrupt_json_returns_none(tmp_path, monkeypatch):
    fake_state_file = tmp_path / "config.json"
    fake_state_file.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(state, "state_file", lambda: fake_state_file)
    assert state.read_state() is None
