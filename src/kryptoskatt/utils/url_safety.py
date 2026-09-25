"""Guard against server-side request forgery (SSRF) for user-supplied URLs.

A user-configured explorer URL is fetched by the server, so it must never
point at the server's own network (database, cloud metadata, localhost).
Checked both when the URL is saved and right before it is fetched, the latter
so a hostname re-pointed to an internal address (DNS rebinding) is caught.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    pass


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_global and not addr.is_multicast


def validate_public_https_url(url: str, resolve: bool = True) -> str:
    """Return the normalised URL, or raise UnsafeURLError.

    Requires https, no credentials, a hostname, and (when ``resolve``) that
    every address the hostname resolves to is a public internet address.
    """
    url = (url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UnsafeURLError("URL must start with https://")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeURLError("URL must contain a hostname and no credentials")
    if parsed.port not in (None, 443):
        raise UnsafeURLError("Only the standard HTTPS port (443) is allowed")
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if literal and not _is_public(host):
        raise UnsafeURLError("URL points to a private or reserved address")
    if resolve and not literal:
        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise UnsafeURLError(f"Hostname does not resolve: {host}") from exc
        if not infos or not all(_is_public(str(info[4][0])) for info in infos):
            raise UnsafeURLError("URL resolves to a private or reserved address")
    return url
