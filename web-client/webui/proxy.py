from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from webui import i18n
from webui.config import get_settings

settings = get_settings()

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
    "te",
    "trailer",
    "proxy-authenticate",
    "proxy-authorization",
}

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.backend_url,
            timeout=httpx.Timeout(connect=2.0, read=45.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            follow_redirects=False,
            trust_env=False,
        )
    return _client


def _request_headers(request: Request) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in request.headers.items():
        lower = key.lower()
        if lower in _HOP_BY_HOP or lower in ("host", "authorization", "accept-encoding"):
            continue
        result[lower] = value
    result["authorization"] = f"Bearer {settings.auth_token}"
    return result


def _response_headers(response: httpx.Response) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in response.headers.items():
        lower = key.lower()
        if lower in _HOP_BY_HOP or lower in ("content-length", "content-type"):
            continue
        result[lower] = value
    return result


def _error_response(status_code: int, detail: str) -> Response:
    return Response(
        content=f'{{"detail": "{detail}"}}',
        status_code=status_code,
        media_type="application/json",
    )


async def proxy_request(request: Request, backend_path: str) -> Response:
    client = get_client()
    headers = _request_headers(request)
    body = await request.body()
    upstream = client.build_request(
        request.method,
        backend_path,
        params=request.query_params,
        headers=headers,
        content=body,
    )
    try:
        response = await client.send(upstream, stream=True)
    except httpx.ConnectError:
        return _error_response(502, i18n.t("webui.backend_unreachable"))
    except httpx.TimeoutException:
        return _error_response(504, i18n.t("webui.backend_timeout"))

    media_type = response.headers.get("content-type", "")
    response_headers = _response_headers(response)

    if "text/event-stream" in media_type:
        response_headers["cache-control"] = "no-store"
        response_headers["x-accel-buffering"] = "no"

        async def body_stream():
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()

        return StreamingResponse(
            body_stream(),
            status_code=response.status_code,
            media_type=media_type,
            headers=response_headers,
        )

    content = await response.aread()
    await response.aclose()
    return Response(
        content=content,
        status_code=response.status_code,
        headers=response_headers,
        media_type=media_type,
    )


async def backend_health() -> dict[str, Any]:
    client = get_client()
    try:
        response = await client.get(
            "/health",
            headers={"authorization": f"Bearer {settings.auth_token}"},
            timeout=2.0,
        )
    except httpx.HTTPError as exc:
        return {"up": False, "detail": str(exc)}
    if response.status_code == 200:
        return {"up": True, "detail": response.json()}
    return {"up": False, "detail": i18n.t("webui.backend_status_code", code=response.status_code)}
