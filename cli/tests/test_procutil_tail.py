import subprocess

import pytest

from rona_cli import procutil


def test_tail_last_50_of_10000(tmp_path):
    path = tmp_path / "log.txt"
    path.write_text("".join(f"line {i}\n" for i in range(10_000)), encoding="utf-8")
    assert procutil.tail_lines(path, 50) == [f"line {i}" for i in range(9_950, 10_000)]


def test_tail_short_missing_and_no_trailing_newline(tmp_path):
    path = tmp_path / "log.txt"
    path.write_text("a\nb\nc", encoding="utf-8")
    assert procutil.tail_lines(path, 50) == ["a", "b", "c"]
    assert procutil.tail_lines(path, 2) == ["b", "c"]
    assert procutil.tail_lines(tmp_path / "none.txt", 5) == []


@pytest.mark.parametrize("block", [1, 2, 3, 5, 7, 16])
def test_tail_multibyte_across_blocks(tmp_path, block):
    path = tmp_path / "log.txt"
    lines = [f"çğş satır {i} İıÖü" for i in range(40)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert procutil.tail_lines(path, 7, block_size=block) == lines[-7:]


def test_spawn_detached_closes_log_handle(tmp_path, monkeypatch):
    seen = {}

    def fake_popen(cmd, **kwargs):
        seen["stdout"] = kwargs["stdout"]
        assert not kwargs["stdout"].closed
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    procutil.spawn_detached(["x"], tmp_path, tmp_path / "out.log")
    assert seen["stdout"].closed
