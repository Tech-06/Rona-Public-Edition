import asyncio
import logging

import pytest

import graph.nodes as nodes
from app.logging_config import REDACTED, RedactingFilter, redact
from graph.nodes import _run_tool_call


@pytest.mark.parametrize(
    "secret",
    [
        "sk-abcdefghijklmnop1234",
        "AIza" + "a" * 35,
        "Bearer abcdefgh12345678",
        "ya29.a0AfH6SMBxyz-_123",
        "1//" + "a" * 25,
        "xoxb-1234-abcd-EFGH",
    ],
)
def test_plain_secret_patterns_are_redacted(secret):
    out = redact(f"before {secret} after")
    assert secret not in out
    assert REDACTED in out and out.startswith("before ") and out.endswith(" after")


@pytest.mark.parametrize("key", ["password", "api_key", "token", "secret"])
def test_keyed_json_values_keep_key(key):
    out = redact('{"%s": "hunter2", "other": "visible"}' % key)
    assert "hunter2" not in out
    assert f'"{key}": "{REDACTED}"' in out
    assert '"other": "visible"' in out


def test_filter_redacts_message_and_args():
    record = logging.LogRecord(
        "x", logging.INFO, "f", 1, "key=%s", ("sk-abcdefghijklmnop1234",), None
    )
    assert RedactingFilter().filter(record) is True
    assert "sk-abcdefghijklmnop1234" not in record.getMessage()


def test_filter_never_raises():
    record = logging.LogRecord("x", logging.INFO, "f", 1, "%d", ("not-a-number",), None)
    assert RedactingFilter().filter(record) is True


def test_info_tool_log_has_no_full_body(caplog, monkeypatch):
    monkeypatch.setattr(nodes, "has_tool", lambda name: False)
    call = {
        "id": "c1",
        "function": {
            "name": "send_email",
            "arguments": '{"to": "a@b.c", "body": "SECRET-BODY-xxxxxxxx"}',
        },
    }
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        asyncio.run(_run_tool_call(call, confirmation={}))
    assert "a@b.c" in caplog.text
    assert "SECRET-BODY" not in caplog.text
