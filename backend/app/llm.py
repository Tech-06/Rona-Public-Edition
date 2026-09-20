import asyncio
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings

settings = get_settings()

# The OpenAI SDK refuses to construct a client with an empty api_key, and
# these clients are built at import time -- so a blank key took the entire
# backend down before it could serve anything, with the reason buried in
# whatever happened to be capturing stdout.
#
# A blank key is not a mistake here. A gateway reached through
# FLASH_MODEL_URL may authenticate on a custom header instead of a bearer
# token, which is the whole reason *_MODEL_HEADERS exists and why the
# installer's wizard accepts an empty key. Give the SDK a placeholder so
# the import succeeds: a provider that genuinely wants a bearer token
# rejects the call itself, at the point of use, with its own message --
# which is a far better failure than a backend that will not boot.
_PLACEHOLDER_API_KEY = "no-api-key"

default_headers = {"User-Agent": f"{settings.app_name}/0.1"}
default_headers.update(settings.flash_model_headers)

client = AsyncOpenAI(
    base_url=settings.flash_model_url,
    api_key=settings.flash_model_api or _PLACEHOLDER_API_KEY,
    default_headers=default_headers,
    timeout=settings.llm_timeout_seconds,
    max_retries=1,
)

pro_client: AsyncOpenAI | None = None
if settings.pro_configured:
    pro_headers = {"User-Agent": f"{settings.app_name}/0.1"}
    pro_headers.update(settings.pro_model_headers)
    pro_client = AsyncOpenAI(
        base_url=settings.pro_model_url,
        api_key=settings.pro_model_api or _PLACEHOLDER_API_KEY,
        default_headers=pro_headers,
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
    )


async def _accumulate_stream(stream) -> dict[str, Any]:
    content_parts: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        if delta.content:
            content_parts.append(delta.content)
        for tool_call in delta.tool_calls or []:
            entry = tool_calls.setdefault(
                tool_call.index,
                {
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                },
            )
            if tool_call.id:
                entry["id"] = tool_call.id
            if tool_call.function:
                if tool_call.function.name:
                    entry["function"]["name"] += tool_call.function.name
                if tool_call.function.arguments:
                    entry["function"]["arguments"] += tool_call.function.arguments
    message: dict[str, Any] = {"role": "assistant"}
    content = "".join(content_parts)
    if content:
        message["content"] = content
    if tool_calls:
        message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
    return message


async def chat_completion(
    messages: list[dict],
    conversation_id: str | None = None,
    tools: list[dict] | None = None,
    tier: str = "flash",
    timeout: float | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    if tier == "pro":
        if pro_client is None:
            raise RuntimeError(
                "PRO model is not configured. "
                "Set PRO_MODEL, PRO_MODEL_URL and PRO_MODEL_API."
            )
        active_client = pro_client
        model = settings.pro_model
        session_headers = settings.pro_model_headers
    else:
        active_client = client
        model = settings.flash_model
        session_headers = settings.flash_model_headers
    extra_headers = None
    if conversation_id and "x-opencode-session" in session_headers:
        extra_headers = {"x-opencode-session": conversation_id}
    kwargs: dict[str, Any] = {}
    if tools:
        kwargs["tools"] = tools
    if timeout is not None:
        kwargs["timeout"] = timeout
    if stream:
        kwargs["stream"] = True
        wall_timeout = timeout if timeout is not None else settings.llm_timeout_seconds
        async with asyncio.timeout(wall_timeout):
            response = await active_client.chat.completions.create(
                model=model,
                messages=messages,
                extra_headers=extra_headers,
                **kwargs,
            )
            return await _accumulate_stream(response)
    response = await active_client.chat.completions.create(
        model=model,
        messages=messages,
        extra_headers=extra_headers,
        **kwargs,
    )
    return response.choices[0].message.model_dump(exclude_none=True)
