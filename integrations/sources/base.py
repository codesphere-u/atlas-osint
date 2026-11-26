"""Source adapter contract.

A *source adapter* knows how to query exactly one information source. Adapters
are plugins: they declare everything ATLAS needs to know about the source
(category, access method, authentication, rate limits, legal restrictions,
data fields, freshness, reliability and citation format) in a
:class:`SourceMetadata` object, and implement :meth:`SourceAdapter.collect`.

The core engine never needs to change when a source is added. See
``docs/writing-source-adapters.md``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from shared.config import Settings
from shared.http import ResponseTooLarge, SafeHttpClient, SafeResponse
from shared.ssrf import SSRFError
from shared.types import (
    AccessMethod,
    AdapterResult,
    AdapterStatus,
    Evidence,
    EvidenceKind,
    Finding,
    Identifier,
    IdentifierType,
    LinkedIdentifier,
    MatchType,
    Reliability,
    SourceCategory,
    SubjectKind,
    utcnow,
)

log = logging.getLogger("atlas.sources")


class AuthRequirement(BaseModel):
    required: bool = False
    kind: str = "none"  # none | api_key | bearer | user_agent_contact
    settings_fields: list[str] = Field(default_factory=list)  # Settings attribute names
    optional: bool = False  # credential improves limits but is not required
    how_to_obtain: str | None = None


class RateLimit(BaseModel):
    requests: int
    per_seconds: float
    notes: str | None = None


class LegalInfo(BaseModel):
    terms_url: str | None = None
    license: str | None = None
    restrictions: str
    robots_txt_respected: bool = True
    contains_personal_data: bool = False
    requires_subject_consent: bool = False  # e.g. breach-notification lookups for individuals
    active_probe: bool = False  # touches infrastructure of the target -> requires authorised scope


class SourceMetadata(BaseModel):
    name: str  # stable slug, e.g. "github"
    display_name: str
    description: str
    category: SourceCategory
    input_types: list[IdentifierType]
    access_method: AccessMethod
    homepage: str
    auth: AuthRequirement = Field(default_factory=AuthRequirement)
    rate_limit: RateLimit
    legal: LegalInfo
    fields: list[str]  # attribute keys this adapter may emit (data minimisation contract)
    freshness: str  # e.g. "real-time", "daily", "static dataset (library release)"
    reliability: Reliability
    citation_format: str = '{display_name}. "{title}". {url}. Retrieved {collected_at}.'
    default_enabled: bool = True
    timeout_seconds: float = 20.0
    version: str = "1.0"


class AuthorizationScope(BaseModel):
    """The subset of an investigation's authorisation record adapters may consult."""

    subject_kind: SubjectKind
    consent_obtained: bool = False
    legal_basis: str
    authorized_domains: list[str] = Field(default_factory=list)

    def domain_in_scope(self, domain: str) -> bool:
        domain = domain.lower().rstrip(".")
        return any(domain == d or domain.endswith("." + d) for d in self.authorized_domains)


@dataclass
class CollectionContext:
    http: SafeHttpClient
    settings: Settings
    scope: AuthorizationScope
    investigation_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def secret(self, name: str) -> str | None:
        value = getattr(self.settings, name, None)
        if value is None:
            return None
        return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)


class SourceError(Exception):
    def __init__(self, status: AdapterStatus, message: str, http_status: int | None = None):
        super().__init__(message)
        self.status = status
        self.http_status = http_status


class SourceAdapter(ABC):
    meta: ClassVar[SourceMetadata]

    # ----------------------------------------------------------------- policy
    def supports(self, identifier: Identifier) -> bool:
        return identifier.type in self.meta.input_types

    def configuration_status(self, settings: Settings) -> tuple[bool, str]:
        auth = self.meta.auth
        if not auth.required:
            return True, "no credentials required" if not auth.settings_fields else "optional credentials"
        missing = [f for f in auth.settings_fields if getattr(settings, f, None) in (None, "")]
        if missing:
            return False, "missing configuration: " + ", ".join(f"ATLAS_{m.upper()}" for m in missing)
        return True, "configured"

    def authorization_check(self, identifier: Identifier, scope: AuthorizationScope) -> str | None:
        """Return a reason string when the investigation's authorisation does not cover this source."""
        if self.meta.legal.requires_subject_consent and scope.subject_kind == SubjectKind.INDIVIDUAL:
            if not (scope.consent_obtained or scope.legal_basis == "self"):
                return "source requires documented consent of the individual"
        if self.meta.legal.active_probe:
            domain = _identifier_domain(identifier)
            if domain is None or not scope.domain_in_scope(domain):
                return "active probing requires the target domain to be in the authorised scope"
        return None

    # --------------------------------------------------------------- execution
    async def run(self, identifier: Identifier, ctx: CollectionContext) -> AdapterResult:
        started = time.monotonic()
        started_at = utcnow()

        def done(
            status: AdapterStatus,
            findings: list[Finding] | None = None,
            message: str | None = None,
            http_status: int | None = None,
        ) -> AdapterResult:
            return AdapterResult(
                source_name=self.meta.name,
                status=status,
                findings=findings or [],
                message=message,
                http_status=http_status,
                duration_ms=int((time.monotonic() - started) * 1000),
                started_at=started_at,
            )

        if not self.supports(identifier):
            return done(AdapterStatus.SKIPPED, message=f"does not accept {identifier.type.value} input")
        configured, reason = self.configuration_status(ctx.settings)
        if not configured:
            return done(AdapterStatus.NOT_CONFIGURED, message=reason)
        denial = self.authorization_check(identifier, ctx.scope)
        if denial:
            return done(AdapterStatus.SKIPPED, message=denial)
        try:
            findings = await asyncio.wait_for(self.collect(identifier, ctx), timeout=self.meta.timeout_seconds)
        except SourceError as exc:
            return done(exc.status, message=str(exc), http_status=exc.http_status)
        except TimeoutError:
            return done(AdapterStatus.UNAVAILABLE, message=f"timed out after {self.meta.timeout_seconds}s")
        except SSRFError as exc:
            return done(AdapterStatus.SKIPPED, message=f"blocked by SSRF protection: {exc}")
        except ResponseTooLarge as exc:
            return done(AdapterStatus.UNAVAILABLE, message=str(exc))
        except (httpx.HTTPError, OSError) as exc:
            return done(AdapterStatus.UNAVAILABLE, message=f"network error: {type(exc).__name__}")
        except Exception as exc:
            log.exception("adapter %s failed", self.meta.name)
            return done(AdapterStatus.ERROR, message=f"adapter error: {type(exc).__name__}")
        for f in findings:
            self._enforce_fields(f)
        return done(AdapterStatus.OK if findings else AdapterStatus.NO_RESULTS, findings)

    @abstractmethod
    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        """Query the source. Raise :class:`SourceError` for expected failure modes."""

    # ------------------------------------------------------------------ helpers
    async def fetch(self, ctx: CollectionContext, url: str, **kwargs: Any) -> SafeResponse:
        rl = self.meta.rate_limit
        resp = await ctx.http.get(url, rate_key=self.meta.name, rate=(rl.requests, rl.per_seconds), **kwargs)
        if resp.status_code == 429:
            raise SourceError(AdapterStatus.RATE_LIMITED, "source rate limit reached", 429)
        if resp.status_code in (401, 403):
            raise SourceError(
                AdapterStatus.UNAVAILABLE, f"access denied by source (HTTP {resp.status_code})", resp.status_code
            )
        if resp.status_code >= 500:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"source error (HTTP {resp.status_code})", resp.status_code)
        return resp

    def _enforce_fields(self, finding: Finding) -> None:
        allowed = set(self.meta.fields)
        dropped = [k for k in finding.attributes if k not in allowed]
        for k in dropped:
            finding.attributes.pop(k, None)
        if dropped:
            finding.flags.append("undeclared_fields_dropped")

    def finding(
        self,
        *,
        module: str,
        subject: Identifier,
        finding_type: str,
        title: str,
        description: str,
        url: str,
        attributes: dict[str, Any] | None = None,
        linked: list[LinkedIdentifier] | None = None,
        match_type: MatchType = MatchType.EXACT,
        evidence_kind: EvidenceKind = EvidenceKind.DIRECT,
        excerpt: str | None = None,
        raw: bytes | None = None,
        evidence_metadata: dict[str, Any] | None = None,
        published_at: datetime | None = None,
        entity_hint: str | None = None,
        entity_kind: str | None = None,
        claim_key: str | None = None,
        flags: list[str] | None = None,
    ) -> Finding:
        collected_at = utcnow()
        citation = self.meta.citation_format.format(
            display_name=self.meta.display_name,
            title=title,
            url=url,
            collected_at=collected_at.strftime("%Y-%m-%d %H:%M UTC"),
        )
        return Finding(
            module=module,
            source_name=self.meta.name,
            source_display_name=self.meta.display_name,
            source_url=url,
            source_category=self.meta.category,
            reliability=self.meta.reliability,
            finding_type=finding_type,
            title=title[:300],
            description=description[:2000],
            subject=subject,
            match_type=match_type,
            evidence_kind=evidence_kind,
            attributes={k: v for k, v in (attributes or {}).items() if v not in (None, "", [], {})},
            linked=linked or [],
            evidence=Evidence(
                excerpt=(excerpt[:1000] if excerpt else None),
                metadata=evidence_metadata or {},
                content_hash=Evidence.hash_bytes(raw) if raw is not None else None,
            ),
            collected_at=collected_at,
            published_at=published_at,
            entity_hint=entity_hint,
            entity_kind=entity_kind,
            claim_key=claim_key,
            citation=citation,
            flags=flags or [],
        )


def _identifier_domain(identifier: Identifier) -> str | None:
    if identifier.type == IdentifierType.DOMAIN:
        return identifier.value
    if identifier.type in (IdentifierType.URL, IdentifierType.DOCUMENT):
        from urllib.parse import urlsplit

        host = urlsplit(identifier.value).hostname
        return host.removeprefix("www.") if host else None
    if identifier.type == IdentifierType.EMAIL:
        return identifier.value.rsplit("@", 1)[1]
    return None


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    from datetime import UTC

    text = str(value).strip()
    for candidate in (text.replace("Z", "+00:00"), text[:10]):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
