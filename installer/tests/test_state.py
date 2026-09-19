import json

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


def test_write_state_with_language_sets_it(tmp_path, monkeypatch):
    fake_state_file = tmp_path / "home" / ".rona" / "config.json"
    monkeypatch.setattr(state, "state_file", lambda: fake_state_file)

    state.write_state(tmp_path / "root", {"cli": True, "backend": False, "web": False}, language="en")

    assert state.read_state()["language"] == "en"


def test_write_state_without_language_preserves_existing_value(tmp_path, monkeypatch):
    fake_state_file = tmp_path / "home" / ".rona" / "config.json"
    monkeypatch.setattr(state, "state_file", lambda: fake_state_file)
    state.write_state(tmp_path / "root", {"cli": True}, language="en")

    # A later write that doesn't pass language (e.g. `rona edit lang`'s own
    # writer, which only ever touches the "language" key) must not get
    # wiped by a write_state() call that has nothing to say about it.
    state.write_state(tmp_path / "root", {"cli": True, "backend": True})

    assert state.read_state()["language"] == "en"
    assert state.read_state()["components"] == {"cli": True, "backend": True}


def test_write_state_preserves_unknown_existing_fields(tmp_path, monkeypatch):
    fake_state_file = tmp_path / "home" / ".rona" / "config.json"
    fake_state_file.parent.mkdir(parents=True)
    fake_state_file.write_text(
        json.dumps({"language": "en", "custom_field": "keep-me"}), encoding="utf-8"
    )
    monkeypatch.setattr(state, "state_file", lambda: fake_state_file)

    state.write_state(tmp_path / "root", {"cli": True})

    data = state.read_state()
    assert data["language"] == "en"
    assert data["custom_field"] == "keep-me"
    assert data["components"] == {"cli": True}


def test_write_state_corrupt_existing_file_is_replaced_cleanly(tmp_path, monkeypatch):
    fake_state_file = tmp_path / "home" / ".rona" / "config.json"
    fake_state_file.parent.mkdir(parents=True)
    fake_state_file.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(state, "state_file", lambda: fake_state_file)

    state.write_state(tmp_path / "root", {"cli": True}, language="tr")

    data = state.read_state()
    assert data["components"] == {"cli": True}
    assert data["language"] == "tr"
