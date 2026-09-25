import pytest

from kryptoskatt.utils.url_safety import UnsafeURLError, validate_public_https_url


@pytest.mark.parametrize("url", [
    "http://example.com",
    "https://127.0.0.1/api",
    "https://10.0.0.5",
    "https://169.254.169.254/latest/meta-data",
    "https://[::1]/",
    "https://user:pw@example.com",
    "https://example.com:5432",
    "file:///etc/passwd",
    "",
])
def test_rejects_unsafe(url):
    with pytest.raises(UnsafeURLError):
        validate_public_https_url(url, resolve=False)


def test_rejects_hostname_resolving_to_private(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("10.1.2.3", 443))])
    with pytest.raises(UnsafeURLError):
        validate_public_https_url("https://evil.example")


def test_accepts_public(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 443))])
    assert validate_public_https_url("https://explorer.example/api/") == "https://explorer.example/api"
