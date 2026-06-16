"""SSRF guard for user-supplied outbound URLs.

User-configurable explorer URLs (custom chains) are fetched server-side. An
unvalidated URL would let an authenticated user point the server at internal
services or cloud metadata endpoints (SSRF), e.g. http://169.254.169.254/ or
http://localhost:6379/.

``validate_outbound_url`` enforces an http(s) scheme and rejects hosts that
resolve to private, loopback, link-local or otherwise non-public IP ranges.
DNS is resolved at validation time so hostnames that point at internal IPs are
also rejected; re-validating immediately before each request (defence in depth)
additionally narrows the window for DNS-rebinding.
"""

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """Raised when a URL is not safe to fetch from the server."""


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:169.254.169.254) before classifying.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_outbound_url(url: str) -> str:
    """Return ``url`` unchanged if it is safe to fetch, else raise ``UnsafeURLError``.

    A URL is considered safe when:
      * its scheme is http or https, and
      * every IP address its host resolves to is a public, routable address.
    """
    if not url or not isinstance(url, str):
        raise UnsafeURLError("URL saknas")

    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(
            f"Ogiltigt schema '{parsed.scheme or '(saknas)'}' — endast http/https tillåts"
        )

    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL saknar värdnamn")

    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Kunde inte slå upp värdnamnet '{host}'") from exc

    if not infos:
        raise UnsafeURLError(f"Kunde inte slå upp värdnamnet '{host}'")

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as exc:
            raise UnsafeURLError(f"Ogiltig IP-adress: {addr}") from exc
        if _ip_is_blocked(ip):
            raise UnsafeURLError(
                f"URL pekar på en icke-publik adress ({addr}) och tillåts inte"
            )

    return url
