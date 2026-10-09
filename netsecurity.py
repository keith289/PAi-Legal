"""Network boundary checks shared by PAi Legal's local integrations."""
from __future__ import annotations

import ipaddress
import urllib.parse


def require_loopback_url(value: str, label: str = "Local service") -> str:
    """Validate that an HTTP endpoint resolves syntactically to loopback.

    Hostnames other than literal ``localhost`` are rejected to avoid DNS
    rebinding. Production integrations must not silently turn a local feature
    into a remote disclosure channel through an environment variable or a
    writable provider manifest.
    """
    url = str(value or "").strip().rstrip("/")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{label} URL is invalid")
    host = parsed.hostname.lower()
    if host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError
        except ValueError as exc:
            raise ValueError(f"{label} must use a loopback address") from exc
    return url


def bearer_headers(token: str) -> dict[str, str]:
    value = str(token or "").strip()
    return {"Authorization": f"Bearer {value}"} if value else {}
