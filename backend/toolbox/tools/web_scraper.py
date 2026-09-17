import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)

_MAX_REDIRECTS = 5
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


def _blocked_reason(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return f"Unsupported URL scheme: {parts.scheme!r}"
    if not parts.hostname:
        return "URL has no hostname"
    try:
        resolved = socket.getaddrinfo(parts.hostname, None)
    except OSError as exc:
        return f"Could not resolve host {parts.hostname!r}: {exc}"
    for info in resolved:
        if _is_blocked_address(info[4][0]):
            return f"Blocked address for host {parts.hostname!r}"
    return None


def web_scraper(url: str) -> dict:
    try:
        current_url = url
        response = None
        for _ in range(_MAX_REDIRECTS + 1):
            reason = _blocked_reason(current_url)
            if reason:
                return {"success": False, "error": reason}
            headers = {"User-Agent": _USER_AGENT}
            with httpx.Client(headers=headers, follow_redirects=False) as client:
                response = client.get(current_url, timeout=10.0)
            if not response.is_redirect:
                break
            location = response.headers.get("location")
            if not location:
                return {"success": False, "error": "Redirect without a Location header"}
            current_url = urljoin(current_url, location)
        else:
            return {"success": False, "error": "Too many redirects"}

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        for script_or_style in soup(["script", "style"]):
            script_or_style.extract()

        text = soup.get_text(separator="\n")
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = "\n".join(chunk for chunk in chunks if chunk)

        return {
            "success": True,
            "title": soup.title.string if soup.title else "",
            "content": text[:5000],
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
