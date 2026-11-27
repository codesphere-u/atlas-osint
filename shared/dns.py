"""Async DNS resolution with two interchangeable backends.

* ``system`` – the host's resolvers via dnspython (default).
* ``doh`` – DNS-over-HTTPS JSON API (RFC 8484 companion JSON format used by Google Public DNS and Cloudflare).
  Use it where outbound port 53 is filtered or where resolvers only answer some record types: otherwise a
  filtered network would make ATLAS wrongly report "no SPF / no DMARC / no MX".

Adapters receive the resolver through ``CollectionContext.extra["dns_resolver"]`` so tests can inject a fake.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import dns.asyncresolver
import dns.exception
import dns.resolver
import httpx

DnsResolver = Callable[[str, str], Awaitable[list[str]]]

RRTYPE_CODES = {
    "A": 1,
    "NS": 2,
    "CNAME": 5,
    "SOA": 6,
    "MX": 15,
    "TXT": 16,
    "AAAA": 28,
    "DS": 43,
    "DNSKEY": 48,
    "CAA": 257,
}


class DnsLookupError(Exception):
    pass


async def resolve_system(name: str, rdtype: str) -> list[str]:
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


def _unquote_txt(data: str) -> str:
    """Cloudflare returns TXT data as quoted segments ("a" "b"); Google returns it unquoted."""
    data = data.strip()
    if not data.startswith('"'):
        return data
    parts, buf, inside, escape = [], [], False, False
    for ch in data:
        if escape:
            buf.append(ch)
            escape = False
        elif ch == "\\":
            escape = True
        elif ch == '"':
            if inside:
                parts.append("".join(buf))
                buf = []
            inside = not inside
        elif inside:
            buf.append(ch)
    return "".join(parts)


def parse_doh_answer(payload: dict, name: str, rdtype: str) -> list[str]:
    status = payload.get("Status")
    if status == 3:  # NXDOMAIN
        return []
    if status != 0:
        raise DnsLookupError(f"{rdtype} lookup failed for {name}: DoH status {status}")
    code = RRTYPE_CODES.get(rdtype)
    out = []
    for ans in payload.get("Answer") or []:
        if code is not None and ans.get("type") != code:
            continue  # skip CNAME chain entries
        data = str(ans.get("data", ""))
        out.append(_unquote_txt(data) if rdtype == "TXT" else data)
    return out


def make_doh_resolver(url: str, timeout: float = 8.0, client: httpx.AsyncClient | None = None) -> DnsResolver:
    async def resolve_doh(name: str, rdtype: str) -> list[str]:
        params = {"name": name, "type": rdtype}
        headers = {"Accept": "application/dns-json"}
        try:
            if client is not None:
                resp = await client.get(url, params=params, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=timeout) as c:
                    resp = await c.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise DnsLookupError(f"{rdtype} lookup failed for {name}: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise DnsLookupError(f"{rdtype} lookup failed for {name}: DoH HTTP {resp.status_code}")
        try:
            return parse_doh_answer(resp.json(), name, rdtype)
        except ValueError as exc:
            raise DnsLookupError(f"{rdtype} lookup failed for {name}: invalid DoH response") from exc

    return resolve_doh


async def resolve(name: str, rdtype: str) -> list[str]:
    """Default resolver used by adapters: honours ``ATLAS_DNS_RESOLVER``."""
    from shared.config import get_settings

    settings = get_settings()
    if settings.dns_resolver == "doh":
        return await make_doh_resolver(settings.doh_url)(name, rdtype)
    return await resolve_system(name, rdtype)
