"""Server-side request forgery (SSRF) protection.

Every outbound request made on behalf of an investigation passes through
:func:`validate_url`, which:

* allows only ``http``/``https`` and an allow-list of ports,
* rejects credentials embedded in URLs,
* resolves the hostname and rejects any address that is not globally routable
  (loopback, RFC1918, link-local, CGNAT, multicast, reserved, ULA, cloud
  metadata, IPv4-mapped IPv6 variants of those, ...).

The resolved address is returned so the HTTP client can *pin* the connection to
it, which defeats DNS-rebinding between validation and connection.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

Resolver = Callable[[str], list[str]]

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
    "instance-data",
}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".corp")


class SSRFError(ValueError):
    """Raised when a URL targets a non-public destination."""


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    scheme: str
    host: str
    port: int
    address: str  # pinned IP address


def system_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({str(info[4][0]) for info in infos})


def is_public_address(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_address(str(ip.ipv4_mapped))
        if ip.sixtofour is not None:
            return is_public_address(str(ip.sixtofour))
        if ip.teredo is not None:
            return False
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
        return False  # carrier-grade NAT
    return ip.is_global


def validate_url(
    url: str,
    *,
    allowed_ports: list[int] | tuple[int, ...] = (80, 443),
    resolver: Resolver = system_resolver,
) -> ValidatedURL:
    if len(url) > 2048:
        raise SSRFError("URL too long")
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise SSRFError(f"scheme '{scheme}' not allowed")
    if parts.username or parts.password:
        raise SSRFError("credentials in URL are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise SSRFError("URL has no host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise SSRFError("invalid port") from exc
    if port not in allowed_ports:
        raise SSRFError(f"port {port} not allowed")
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise SSRFError(f"host '{host}' is not a public host")

    # Literal IP address?
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        try:
            host.encode("idna")
        except UnicodeError as exc:
            raise SSRFError("invalid hostname") from exc
        try:
            addresses = resolver(host)
        except OSError as exc:
            raise SSRFError(f"could not resolve host '{host}'") from exc
    if not addresses:
        raise SSRFError(f"host '{host}' did not resolve")
    for addr in addresses:
        if not is_public_address(addr):
            raise SSRFError(f"host '{host}' resolves to non-public address {addr}")
    return ValidatedURL(url=url, scheme=scheme, host=host, port=port, address=addresses[0])
