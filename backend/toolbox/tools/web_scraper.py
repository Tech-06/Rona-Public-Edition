import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx
from bs4 import BeautifulSoup

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)

_MAX_REDIRECTS = 5
_MAX_BODY_BYTES = 2_000_000
_ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
_BLOCKED_NETWORKS = (ipaddress.ip_network("100.64.0.0/10"),)


def _is_blocked_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    if (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_reserved
        or parsed.is_multicast
        or parsed.is_unspecified
    ):
        return True
    return any(parsed in network for network in _BLOCKED_NETWORKS)


def _resolve_checked(url: str) -> tuple[str | None, str | None]:
    """Validate the URL and resolve its host exactly once.

    Returns (error, pinned_ip). Every address the resolver returned must be
    public, otherwise a mixed answer could be used to smuggle in an internal
    one; the first address is then the one the request is pinned to.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return f"Unsupported URL scheme: {parts.scheme!r}", None
    if not parts.hostname:
        return "URL has no hostname", None
    if parts.username is not None or parts.password is not None:
        return "URLs with embedded credentials are not allowed", None
    try:
        resolved = socket.getaddrinfo(parts.hostname, None)
    except OSError as exc:
        return f"Could not resolve host {parts.hostname!r}: {exc}", None
    addresses = [info[4][0] for info in resolved]
    if not addresses:
        return f"Could not resolve host {parts.hostname!r}", None
    for address in addresses:
        if _is_blocked_address(address):
            return f"Blocked address for host {parts.hostname!r}", None
    return None, addresses[0]


def _blocked_reason(url: str) -> str | None:
    return _resolve_checked(url)[0]


class _PinnedBackend(httpcore.NetworkBackend):
    """Connects to a pre-validated IP whatever hostname the request names.

    The hostname is still used by httpcore for the Host header and for TLS
    SNI/certificate verification (start_tls gets the origin host, not the
    address), so HTTPS stays properly verified while DNS is never consulted
    a second time. That closes the check-then-connect rebinding gap.
    """

    def __init__(self, pinned_ip: str) -> None:
        self._pinned_ip = pinned_ip
        self._inner = httpcore.SyncBackend()

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return self._inner.connect_tcp(
            self._pinned_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("Unix sockets are not allowed")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


class _PinnedTransport(httpx.HTTPTransport):
    def __init__(self, pinned_ip: str) -> None:
        super().__init__(trust_env=False)
        # No public hook to swap the backend on an HTTPTransport; the pool is
        # a plain httpcore.ConnectionPool (no proxy since trust_env=False).
        self._pool._network_backend = _PinnedBackend(pinned_ip)


def _transport_factory(pinned_ip: str) -> httpx.BaseTransport:
    # Module-level seam so tests can swap in httpx.MockTransport.
    return _PinnedTransport(pinned_ip)


def _looks_like_html(head: bytes) -> bool:
    return b"<" in head[:512].lower() and any(
        marker in head[:1024].lower() for marker in (b"<html", b"<!doctype html", b"<head", b"<body")
    )


def _content_type_allowed(value: str | None, head: bytes) -> bool:
    if not value:
        return _looks_like_html(head)
    return value.split(";", 1)[0].strip().lower() in _ALLOWED_CONTENT_TYPES


def _fetch(client: httpx.Client, url: str) -> tuple[bytes, str, bool] | dict:
    """Stream one response; returns (body, encoding, truncated) or an error dict."""
    with client.stream("GET", url, timeout=10.0) as response:
        if response.is_redirect:
            return {"redirect": response.headers.get("location") or ""}
        response.raise_for_status()
        body = bytearray()
        truncated = False
        checked = False
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if not checked:
                checked = True
                if not _content_type_allowed(response.headers.get("content-type"), bytes(body)):
                    return {
                        "success": False,
                        "error": "Unsupported content type: "
                        f"{response.headers.get('content-type') or 'unknown'}",
                    }
            if len(body) >= _MAX_BODY_BYTES:
                del body[_MAX_BODY_BYTES:]
                truncated = True
                break
        if not checked and not _content_type_allowed(response.headers.get("content-type"), b""):
            return {"success": False, "error": "Unsupported content type"}
        return bytes(body), response.charset_encoding or "utf-8", truncated


def web_scraper(url: str) -> dict:
    try:
        current_url = url
        fetched = None
        for _ in range(_MAX_REDIRECTS + 1):
            reason, pinned_ip = _resolve_checked(current_url)
            if reason:
                return {"success": False, "error": reason}
            headers = {"User-Agent": _USER_AGENT}
            with httpx.Client(
                headers=headers,
                follow_redirects=False,
                trust_env=False,
                transport=_transport_factory(pinned_ip),
            ) as client:
                fetched = _fetch(client, current_url)
            if isinstance(fetched, tuple):
                break
            if "redirect" not in fetched:
                return fetched
            if not fetched["redirect"]:
                return {"success": False, "error": "Redirect without a Location header"}
            current_url = urljoin(current_url, fetched["redirect"])
        else:
            return {"success": False, "error": "Too many redirects"}

        body, encoding, truncated = fetched
        try:
            html = body.decode(encoding, errors="replace")
        except LookupError:
            html = body.decode("utf-8", errors="replace")

        soup = BeautifulSoup(html, "html.parser")
        for script_or_style in soup(["script", "style"]):
            script_or_style.extract()

        text = soup.get_text(separator="\n")
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = "\n".join(chunk for chunk in chunks if chunk)

        result = {
            "success": True,
            "title": soup.title.string if soup.title else "",
            "content": text[:5000],
        }
        if truncated:
            result["truncated"] = True
        return result
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
