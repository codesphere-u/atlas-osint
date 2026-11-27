"""Core domain types shared by every layer of ATLAS OSINT.

These Pydantic models are the contract between source adapters, the
correlation engine, the API and the report generators. They deliberately carry
provenance on every finding: who said it, where, when, and how sure we are.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class IdentifierType(StrEnum):
    PHONE = "phone"
    USERNAME = "username"
    NAME = "name"
    EMAIL = "email"
    DOMAIN = "domain"
    URL = "url"
    IP = "ip"
    ORGANIZATION = "organization"
    DOCUMENT = "document"  # URL of a publicly accessible document or record


class SubjectKind(StrEnum):
    """What kind of subject an investigation concerns. Drives privacy rules."""

    INDIVIDUAL = "individual"
    ORGANIZATION = "organization"
    INFRASTRUCTURE = "infrastructure"


# Identifier types that, when used as investigation input, describe a natural person
# unless the analyst explicitly declares otherwise.
INDIVIDUAL_IDENTIFIER_TYPES = frozenset(
    {IdentifierType.PHONE, IdentifierType.USERNAME, IdentifierType.NAME, IdentifierType.EMAIL}
)


class Identifier(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: IdentifierType
    value: str  # normalized value
    raw: str | None = None  # value as provided

    @property
    def key(self) -> str:
        return f"{self.type.value}:{self.value}"


class SourceCategory(StrEnum):
    PHONE = "phone"
    USERNAME = "username"
    NAME = "name"
    EMAIL = "email"
    DOMAIN = "domain"
    INFRASTRUCTURE = "infrastructure"
    PUBLIC_RECORDS = "public_records"
    ACADEMIC = "academic"
    NEWS = "news"
    ARCHIVE = "archive"
    DOCUMENTS = "documents"
    BREACH_NOTIFICATION = "breach_notification"


class AccessMethod(StrEnum):
    OFFICIAL_API = "official_api"
    PUBLIC_API = "public_api"
    DNS = "dns"
    RDAP = "rdap"
    OFFLINE_DATASET = "offline_dataset"
    PUBLIC_WEB = "public_web"
    LICENSED_API = "licensed_api"


class Reliability(StrEnum):
    """Source reliability grade (adapted from the Admiralty / NATO system)."""

    A = "A"  # authoritative primary source (registry, protocol, official API of the record holder)
    B = "B"  # usually reliable (official platform API about its own users)
    C = "C"  # fairly reliable (curated third-party aggregator)
    D = "D"  # not usually reliable (crowd-sourced / scraped index)
    E = "E"  # unreliable / unknown provenance


class MatchType(StrEnum):
    EXACT = "exact"  # the queried identifier matches exactly
    SIMILAR = "similar"  # near match (case/diacritics/variant) – never merged automatically
    RELATED = "related"  # an object explicitly connected to the subject by the source
    INFERRED = "inferred"  # connection derived by ATLAS, not stated by the source


class EvidenceKind(StrEnum):
    DIRECT = "direct"  # the source states it
    INFERENCE = "inference"  # derived by reasoning over other evidence


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    CORROBORATED = "corroborated"  # independent sources agree (automatic)
    VERIFIED = "verified"  # an analyst verified it
    REJECTED = "rejected"  # an analyst rejected it
    DISPUTED = "disputed"  # contradicting evidence exists


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    VERY_LOW = "very_low"


class ConfidenceReason(BaseModel):
    rule: str
    delta: float
    explanation: str


class Confidence(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    level: ConfidenceLevel
    reasons: list[ConfidenceReason] = Field(default_factory=list)


class Evidence(BaseModel):
    excerpt: str | None = None  # short quotation or permitted metadata summary
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str | None = None  # sha256 of the raw response used, for reproducibility

    @staticmethod
    def hash_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()


class LinkedIdentifier(BaseModel):
    identifier: Identifier
    relation: str  # e.g. "lists_website", "registrant_org", "resolves_to"
    evidence_kind: EvidenceKind = EvidenceKind.DIRECT
    # Explicit entity key when the identifier alone is not a strong key (e.g. a parent company's LEI).
    entity_key: str | None = None


class Finding(BaseModel):
    id: str = Field(default_factory=new_id)
    module: str
    source_name: str
    source_display_name: str
    source_url: str
    source_category: SourceCategory
    reliability: Reliability
    finding_type: str
    title: str
    description: str
    subject: Identifier  # the identifier that was queried
    match_type: MatchType = MatchType.EXACT
    evidence_kind: EvidenceKind = EvidenceKind.DIRECT
    attributes: dict[str, Any] = Field(default_factory=dict)
    linked: list[LinkedIdentifier] = Field(default_factory=list)
    entity_hint: str | None = None  # e.g. "account:github:octocat", used by the resolver
    entity_kind: str | None = None  # account | organization | domain | publication | ...
    claim_key: str | None = None  # findings sharing a claim_key assert the same thing
    evidence: Evidence = Field(default_factory=Evidence)
    collected_at: datetime = Field(default_factory=utcnow)
    published_at: datetime | None = None
    confidence: Confidence | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    citation: str | None = None
    flags: list[str] = Field(default_factory=list)


class AdapterStatus(StrEnum):
    OK = "ok"  # query succeeded and returned findings
    NO_RESULTS = "no_results"  # query succeeded, nothing found
    SKIPPED = "skipped"  # not applicable / not authorized / disabled
    NOT_CONFIGURED = "not_configured"  # credentials missing
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"  # remote error / blocked / network failure
    ERROR = "error"  # adapter bug or unexpected response


class AdapterResult(BaseModel):
    source_name: str
    status: AdapterStatus
    findings: list[Finding] = Field(default_factory=list)
    message: str | None = None
    http_status: int | None = None
    duration_ms: int = 0
    started_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Correlation output
# ---------------------------------------------------------------------------


class Entity(BaseModel):
    id: str = Field(default_factory=new_id)
    kind: str
    label: str
    identifiers: list[Identifier] = Field(default_factory=list)
    strong_keys: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    is_subject: bool = False
    confidence: float = 0.0


class Relationship(BaseModel):
    id: str = Field(default_factory=new_id)
    source_entity_id: str
    target_entity_id: str
    type: str
    evidence_kind: EvidenceKind
    finding_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    rationale: str


class Contradiction(BaseModel):
    id: str = Field(default_factory=new_id)
    entity_id: str | None = None
    attribute: str
    values: dict[str, list[str]]  # value -> finding ids
    explanation: str


class NameCollision(BaseModel):
    name: str
    entity_ids: list[str]
    explanation: str


class CorrelationResult(BaseModel):
    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    name_collisions: list[NameCollision] = Field(default_factory=list)
    duplicates_collapsed: int = 0
