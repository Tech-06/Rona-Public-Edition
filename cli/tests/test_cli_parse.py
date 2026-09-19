import io

import pytest

from rona_cli.cli import _ensure_utf8_streams, build_parser, main


def test_no_subcommand_prints_help_and_returns_1(capsys):
    assert main([]) == 1
    captured = capsys.readouterr()
    assert "usage: rona" in captured.out


def test_version_flag_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "rona" in captured.out


def test_root_and_json_accepted_before_subcommand():
    args = build_parser().parse_args(["--root", "/tmp/x", "--json", "status"])
    assert args.root == "/tmp/x"
    assert args.json is True
    assert args.command == "status"


def test_root_and_json_accepted_after_subcommand():
    args = build_parser().parse_args(["status", "--root", "/tmp/x", "--json"])
    assert args.root == "/tmp/x"
    assert args.json is True


def test_json_defaults_to_false_when_omitted():
    args = build_parser().parse_args(["status"])
    assert args.json is False
    assert args.root is None


def test_server_requires_a_subcommand():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["server"])


def test_server_start_parses_and_carries_global_flags():
    args = build_parser().parse_args(["server", "start", "--json"])
    assert args.command == "server"
    assert args.server_command == "start"
    assert args.json is True
    assert callable(args.func)


def test_web_status_parses():
    args = build_parser().parse_args(["web", "status"])
    assert args.command == "web"
    assert args.web_command == "status"
    assert callable(args.func)


def test_unknown_subcommand_errors(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["not-a-real-command"])


def test_ensure_utf8_streams_reconfigures_text_streams(monkeypatch, tmp_path):
    # A real console-backed TextIOWrapper (e.g. cp1252 on a stock Windows
    # terminal) can't encode Turkish text -- this must switch it to utf-8
    # without raising, so Turkish output never crashes the CLI.
    raw = (tmp_path / "out.txt").open("wb")
    wrapper = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr("sys.stdout", wrapper)
    monkeypatch.setattr("sys.stderr", wrapper)
    _ensure_utf8_streams()
    assert wrapper.encoding.lower().replace("-", "") == "utf8"
    wrapper.close()


def test_ensure_utf8_streams_ignores_non_text_streams(monkeypatch):
    monkeypatch.setattr("sys.stdout", object())
    monkeypatch.setattr("sys.stderr", object())
    _ensure_utf8_streams()  # must not raise
