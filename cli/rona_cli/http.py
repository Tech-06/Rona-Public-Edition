"""Minimal stdlib HTTP client for the Rona backend and web-client APIs.

No third-party dependencies on purpose -- the CLI must keep working even
right after a fresh install, before anything beyond the stdlib is available.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from rona_cli import i18n


class ApiError(RuntimeError):
    """Raised for any HTTP-level failure: refused connection, timeout, non-2xx."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def build_query(path: str, params: dict[str, Any]) -> str:
    """Append ``?a=b&c=d`` to ``path`` for every non-``None`` value in
    ``params``. Shared by every command that filters a GET endpoint."""
    filtered = {k: v for k, v in params.items() if v is not None}
    if not filtered:
        return path
    return f"{path}?{urllib.parse.urlencode(filtered)}"


@dataclass
class Client:
    base_url: str
    token: str | None = None
    timeout: float = 10.0
    extra_headers: dict[str, str] = field(default_factory=dict)

    def _headers(self) -> dict[str, str]:
        # Without an explicit User-Agent, urllib sends "Python-urllib/3.x",
        # which several providers' bot-protection (Cloudflare in particular,
        # HTTP 403 "error code: 1010") blocks outright -- even though the
        # exact same request succeeds once the backend makes it through the
        # openai SDK, which sends its own SDK User-Agent. `rona edit model
        # --test`'s whole point is "does this key/model work the way the
        # backend will actually use it", so it needs to look like a normal
        # client too, not like a bare Python script probing the API.
        headers = {"Content-Type": "application/json", "User-Agent": "Rona/0.1"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        headers.update(self.extra_headers)
        return headers

    def request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        timeout: float | None = None,
    ) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}"
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                body = resp.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"HTTP {exc.code}: {detail}", status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise ApiError(i18n.t("http.connection_failed", reason=exc.reason)) from exc
        except TimeoutError as exc:
            raise ApiError(i18n.t("http.timeout")) from exc

    def get(self, path: str, timeout: float | None = None) -> Any:
        return self.request("GET", path, timeout=timeout)

    def post(self, path: str, payload: Any = None, timeout: float | None = None) -> Any:
        return self.request("POST", path, payload=payload if payload is not None else {}, timeout=timeout)

    def put(self, path: str, payload: Any = None, timeout: float | None = None) -> Any:
        return self.request("PUT", path, payload=payload if payload is not None else {}, timeout=timeout)

    def delete(self, path: str, timeout: float | None = None) -> Any:
        return self.request("DELETE", path, payload={}, timeout=timeout)

    def stream_lines(self, path: str, timeout: float | None = None) -> Iterator[str]:
        """Yield decoded lines from a long-lived GET response as they
        arrive (used for `GET /api/logs`'s SSE stream). The caller is
        responsible for interpreting SSE framing (`data: ...`, blank lines,
        `: ping` comments) -- this just gets bytes off the wire without
        buffering the whole response first.
        """
        url = f"{self.base_url.rstrip('/')}{path}"
        req = urllib.request.Request(url, method="GET", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                for raw_line in resp:
                    yield raw_line.decode("utf-8", errors="replace").rstrip("\n")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"HTTP {exc.code}: {detail}", status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise ApiError(i18n.t("http.connection_failed", reason=exc.reason)) from exc
        except TimeoutError as exc:
            raise ApiError(i18n.t("http.timeout")) from exc
