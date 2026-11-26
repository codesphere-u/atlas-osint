"""Thin async DNS helper (dnspython) so adapters can be tested with a fake resolver."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import dns.asyncresolver
import dns.exception
import dns.resolver

DnsResolver = Callable[[str, str], Awaitable[list[str]]]


class DnsLookupError(Exception):
    pass


async def resolve(name: str, rdtype: str) -> list[str]:
    """Return record values as text. NXDOMAIN/NoAnswer -> empty list; other failures raise."""
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = 8.0
    try:
        answer = await resolver.resolve(name, rdtype)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except (dns.exception.Timeout, dns.resolver.NoNameservers) as exc:
        raise DnsLookupError(f"{rdtype} lookup failed for {name}: {type(exc).__name__}") from exc
    out = []
    for rdata in answer:
        if rdtype == "TXT":
            out.append(b"".join(rdata.strings).decode("utf-8", errors="replace"))
        else:
            out.append(rdata.to_text())
    return out
