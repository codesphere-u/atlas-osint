"""SSRF-safe, size-limited, rate-limited asynchronous HTTP client for collectors."""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import httpx

from shared.ratelimit import AsyncRateLimiter
from shared.ssrf import Resolver, SSRFError, system_resolver, validate_url

MAX_REDIRECTS = 5


class ResponseTooLarge(Exception):
    pass


@dataclass
class SafeResponse:
    status_code: int
    url: str
    headers: httpx.Headers
    content: bytes
    elapsed_ms: int
    redirects: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class SafeHttpClient:
    """Wraps :class:`httpx.AsyncClient` with SSRF validation and DNS pinning.

    * Redirects are followed manually and every hop is re-validated.
    * When ``pin_dns`` is true the TCP connection is made to the validated IP
      while TLS SNI/certificate verification and the Host header still use the
      original hostname, preventing DNS-rebinding attacks.
    * Responses are streamed and aborted once ``max_bytes`` is exceeded.
    """

    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float = 15.0,
        max_bytes: int = 5_000_000,
        allowed_ports: list[int] | tuple[int, ...] = (80, 443),
        pin_dns: bool = True,
        resolver: Resolver = system_resolver,
        rate_limiter: AsyncRateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.max_bytes = max_bytes
        self.allowed_ports = allowed_ports
        # When an egress proxy is configured the proxy performs DNS resolution, so pinning to a locally
        # resolved IP is both ineffective and breaks TLS through CONNECT. URLs are still validated; the proxy
        # must enforce egress restrictions in that deployment model (see SECURITY.md).
        proxies = urllib.request.getproxies()
        self.via_proxy = bool(proxies.get("https") or proxies.get("http"))
        self.pin_dns = pin_dns and not self.via_proxy
        self.resolver = resolver
        self.rate_limiter = rate_limiter or AsyncRateLimiter()
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": user_agent},
        )

    async def __aenter__(self) -> SafeHttpClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
        rate_key: str | None = None,
        rate: tuple[int, float] | None = None,
        max_bytes: int | None = None,
        follow_redirects: bool = True,
    ) -> SafeResponse:
        if rate_key and rate:
            await self.rate_limiter.acquire(rate_key, rate[0], rate[1])
        target = str(httpx.URL(url, params=params)) if params else url
        limit = max_bytes or self.max_bytes
        redirects: list[str] = []
        started = time.monotonic()
        for _ in range(MAX_REDIRECTS + 1):
            validated = validate_url(target, allowed_ports=self.allowed_ports, resolver=self.resolver)
            req_headers = {**(headers or {})}
            extensions: dict[str, Any] = {}
            send_url = httpx.URL(target)
            if self.pin_dns and validated.host != validated.address:
                host_hdr = validated.host
                default_port = 443 if validated.scheme == "https" else 80
                if validated.port != default_port:
                    host_hdr = f"{host_hdr}:{validated.port}"
                req_headers["Host"] = host_hdr
                ip_host = f"[{validated.address}]" if ":" in validated.address else validated.address
                send_url = send_url.copy_with(host=ip_host.strip("[]"))
                if validated.scheme == "https":
                    extensions["sni_hostname"] = validated.host
            request = self._client.build_request(
                method, send_url, headers=req_headers, json=json_body, extensions=extensions
            )
            response = await self._client.send(request, stream=True)
            try:
                if follow_redirects and response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise SSRFError("redirect without location")
                    target = urljoin(target, location)
                    redirects.append(target)
                    if response.status_code == 303:
                        method, json_body = "GET", None
                    continue
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > limit:
                        raise ResponseTooLarge(f"response exceeded {limit} bytes")
                    chunks.append(chunk)
                return SafeResponse(
                    status_code=response.status_code,
                    url=target,
                    headers=response.headers,
                    content=b"".join(chunks),
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    redirects=redirects,
                )
            finally:
                await response.aclose()
        raise SSRFError("too many redirects")

    async def get(self, url: str, **kwargs: Any) -> SafeResponse:
        return await self.request("GET", url, **kwargs)

    async def head(self, url: str, **kwargs: Any) -> SafeResponse:
        return await self.request("HEAD", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> SafeResponse:
        return await self.request("POST", url, **kwargs)
