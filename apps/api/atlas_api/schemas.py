"""Request and response schemas (strict input validation)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from shared.types import IdentifierType, SubjectKind


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LegalBasis(StrEnum):
    CONSENT = "consent"  # documented consent of the individual
    SELF = "self"  # the requester investigates their own identifiers
    LEGITIMATE_INTEREST = "legitimate_interest"  # e.g. due diligence on an organisation
    AUTHORIZED_SECURITY_ASSESSMENT = "authorized_security_assessment"  # written authorisation from asset owner
    JOURNALISM = "journalism"
    RESEARCH = "research"
    LEGAL_OBLIGATION = "legal_obligation"


class LoginRequest(Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    user: UserOut


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class UserCreate(Strict):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    role: str = Field(pattern="^(admin|analyst|viewer|auditor)$")


class UserUpdate(Strict):
    role: str | None = Field(default=None, pattern="^(admin|analyst|viewer|auditor)$")
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)


class ApiKeyCreate(Strict):
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int | None = Field(default=90, ge=1, le=365)


class ApiKeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    key: str | None = None  # only returned once at creation


TLP = Literal["clear", "green", "amber", "amber+strict", "red"]


class InvestigationOptions(Strict):
    include_variants: bool = False
    pivot_domain: bool = True
    ai_analysis: bool = False
    sources: list[str] | None = Field(default=None, max_length=100)


class InvestigationCreate(Strict):
    title: str = Field(min_length=1, max_length=200)
    subject_type: IdentifierType
    subject: str = Field(min_length=1, max_length=512)
    subject_kind: SubjectKind | None = None
    purpose: str = Field(min_length=10, max_length=2000)
    legal_basis: LegalBasis
    authorization_reference: str | None = Field(default=None, max_length=200)
    consent_obtained: bool = False
    consent_reference: str | None = Field(default=None, max_length=200)
    authorized_domains: list[str] = Field(default_factory=list, max_length=50)
    attestation: bool = False
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    default_region: str | None = Field(default=None, pattern="^[A-Z]{2}$")
    options: InvestigationOptions = Field(default_factory=InvestigationOptions)
    tlp: TLP = "amber"
    case_id: str | None = Field(default=None, max_length=32)
    run: bool = True

    @field_validator("title", "purpose")
    @classmethod
    def _no_control(cls, v: str) -> str:
        if any(ord(c) < 32 and c not in "\n\t" for c in v):
            raise ValueError("control characters are not allowed")
        return v


class InvestigationOut(BaseModel):
    id: str
    title: str
    subject_type: str
    subject: str
    subject_kind: str
    status: str
    purpose: str
    legal_basis: str
    authorization_reference: str | None
    consent_obtained: bool
    consent_reference: str | None
    authorized_domains: list[str]
    options: dict[str, Any]
    created_by: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    retention_until: datetime
    error: str | None
    progress: dict[str, Any]
    finding_count: int
    confirmed_count: int
    tlp: str = "amber"
    case_id: str | None = None
    parent_id: str | None = None
    monitor_interval_hours: int | None = None
    next_run_at: datetime | None = None
    run_count: int = 0
    risk_level: str | None = None
    posture_grade: str | None = None


class InvestigationDetail(InvestigationOut):
    coverage: dict[str, Any] = Field(default_factory=dict)
    module_summary: dict[str, Any] = Field(default_factory=dict)
    entity_count: int = 0
    relationship_count: int = 0
    contradiction_count: int = 0


class FindingVerify(Strict):
    status: str = Field(pattern="^(verified|rejected|unverified)$")
    note: str | None = Field(default=None, max_length=4000)


class NoteCreate(Strict):
    body: str = Field(min_length=1, max_length=8000)
    finding_id: str | None = Field(default=None, max_length=32)


class SourceUpdate(Strict):
    enabled: bool | None = None
    min_role: str | None = Field(default=None, pattern="^(viewer|analyst|admin)$")


class PrivacyRequestCreate(Strict):
    kind: str = Field(pattern="^(opt_out|correction|deletion)$")
    identifier_type: IdentifierType
    identifier: str = Field(min_length=1, max_length=512)
    contact_email: EmailStr | None = None
    details: str | None = Field(default=None, max_length=4000)


class PrivacyRequestResolve(Strict):
    status: str = Field(pattern="^(approved|rejected|completed)$")
    note: str | None = Field(default=None, max_length=4000)


class InvestigationUpdate(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    tlp: TLP | None = None
    case_id: str | None = Field(default=None, max_length=32)
    remove_from_case: bool = False


class PivotRequest(Strict):
    subject_type: IdentifierType
    subject: str = Field(min_length=1, max_length=512)
    subject_kind: SubjectKind | None = None
    title: str | None = Field(default=None, max_length=200)
    consent_reference: str | None = Field(default=None, max_length=200)
    # The analyst confirms the pivot target is the same subject, or is otherwise covered by the authorisation.
    covered_by_authorization: bool = False
    run: bool = True


class MonitoringUpdate(Strict):
    interval_hours: int | None = Field(default=None, description="null disables monitoring")

    @field_validator("interval_hours")
    @classmethod
    def _allowed(cls, v: int | None) -> int | None:
        if v is not None and v not in (6, 24, 72, 168, 720):
            raise ValueError("interval must be one of 6, 24, 72, 168 or 720 hours")
        return v


class BulkVerify(Strict):
    finding_ids: list[str] = Field(min_length=1, max_length=500)
    status: str = Field(pattern="^(verified|rejected|unverified)$")
    note: str | None = Field(default=None, max_length=4000)


class CaseCreate(Strict):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=8000)
    tlp: TLP = "amber"


class CaseUpdate(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=8000)
    status: str | None = Field(default=None, pattern="^(open|closed)$")
    tlp: TLP | None = None


TokenResponse.model_rebuild()
