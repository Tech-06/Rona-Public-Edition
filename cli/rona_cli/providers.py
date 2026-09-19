"""Direct connectivity checks against an LLM provider or Google's embedding
API -- used by `rona edit model ... --test` and the installer's wizard.
Deliberately bypasses the backend entirely (raw HTTP via `rona_cli.http`,
no `openai`/`google-genai` SDK dependency) so a model/key can be verified
even before the backend has ever been configured or started.
"""

from __future__ import annotations

import json

from rona_cli import http, i18n

GOOGLE_EMBED_BASE_URL = "https://generativelanguage.googleapis.com"


def test_chat_model(
    url: str, api_key: str, model: str, headers: dict[str, str] | None = None
) -> tuple[bool, str]:
    """POST a one-token ping to an OpenAI-compatible `/chat/completions`
    endpoint (the same shape `app/llm.py` uses via the `openai` SDK)."""
    if not url or not api_key or not model:
        return False, i18n.t("providers.chat_missing_fields")
    client = http.Client(
        base_url=url, token=api_key, timeout=15.0, extra_headers=headers or {}
    )
    try:
        client.post(
            "/chat/completions",
            {"model": model, "messages": [{"role": "user", "content": "ping"}]},
        )
    except http.ApiError as exc:
        return False, str(exc)
    return True, "ok"


def _normalize_embedding_model(model: str) -> str:
    return model if model.startswith("models/") else f"models/{model}"


def test_embedding(api_key: str, model: str) -> tuple[bool, str]:
    """POST a one-word embedding request to the Gemini REST API."""
    if not api_key or not model:
        return False, i18n.t("providers.embedding_missing_fields")
    normalized = _normalize_embedding_model(model)
    client = http.Client(base_url=GOOGLE_EMBED_BASE_URL, timeout=15.0)
    try:
        client.post(
            f"/v1beta/{normalized}:embedContent?key={api_key}",
            {"content": {"parts": [{"text": "ping"}]}},
        )
    except http.ApiError as exc:
        return False, str(exc)
    return True, "ok"


def parse_headers(raw: str | None) -> dict[str, str]:
    """Parse the `--headers` JSON string the same way `app/config.py`'s
    `parse_model_headers` validator does for `FLASH_MODEL_HEADERS`."""
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(i18n.t("providers.headers_invalid_json", exc=exc)) from exc
    if not isinstance(parsed, dict):
        # A ValueError (not TypeError) on purpose: every caller catches
        # ValueError uniformly for "the --headers string was bad", whether
        # that's invalid JSON or valid JSON of the wrong shape.
        raise ValueError(i18n.t("providers.headers_not_object"))  # noqa: TRY004
    return {str(k): str(v) for k, v in parsed.items()}
