"""ORM models. Sensitive content is stored encrypted (``*_enc`` columns, Fernet)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from atlas_api.db import Base
from shared.crypto import decrypt_str, encrypt_str
from shared.types import new_id, utcnow


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="analyst")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(128))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped[User] = relationship()


class Investigation(TimestampMixin, Base):
    __tablename__ = "investigations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200))
    subject_type: Mapped[str] = mapped_column(String(20), index=True)
    subject_enc: Mapped[str] = mapped_column(Text)
    subject_hash: Mapped[str] = mapped_column(String(64), index=True)
    subject_kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # authorisation record
    purpose: Mapped[str] = mapped_column(Text)
    legal_basis: Mapped[str] = mapped_column(String(40))
    authorization_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    consent_obtained: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    authorized_domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    attestation: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    results_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    confirmed_count: Mapped[int] = mapped_column(Integer, default=0)

    findings: Mapped[list[FindingRow]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", passive_deletes=True
    )
    notes: Mapped[list[AnalystNote]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def subject_value(self) -> str:
        return decrypt_str(self.subject_enc) or ""

    def set_subject(self, value: str) -> None:
        self.subject_enc = encrypt_str(value) or ""

    @property
    def results(self) -> dict[str, Any]:
        raw = decrypt_str(self.results_enc)
        return json.loads(raw) if raw else {}

    def set_results(self, data: dict[str, Any]) -> None:
        self.results_enc = encrypt_str(json.dumps(data, default=str))


class FindingRow(TimestampMixin, Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    module: Mapped[str] = mapped_column(String(30))
    source_name: Mapped[str] = mapped_column(String(60), index=True)
    finding_type: Mapped[str] = mapped_column(String(60))
    classification: Mapped[str] = mapped_column(String(20), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    level: Mapped[str] = mapped_column(String(20))
    verification_status: Mapped[str] = mapped_column(String(20))
    claim_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_enc: Mapped[str] = mapped_column(Text)
    investigation: Mapped[Investigation] = relationship(back_populates="findings")

    @property
    def data(self) -> dict[str, Any]:
        return json.loads(decrypt_str(self.data_enc) or "{}")

    def set_data(self, data: dict[str, Any]) -> None:
        self.data_enc = encrypt_str(json.dumps(data, default=str)) or ""


class AnalystNote(TimestampMixin, Base):
    __tablename__ = "analyst_notes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body_enc: Mapped[str] = mapped_column(Text)
    investigation: Mapped[Investigation] = relationship(back_populates="notes")
    author: Mapped[User] = relationship()

    @property
    def body(self) -> str:
        return decrypt_str(self.body_enc) or ""


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), default="success")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SourceConfig(Base):
    __tablename__ = "source_configs"
    source_name: Mapped[str] = mapped_column(String(60), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    min_role: Mapped[str] = mapped_column(String(20), default="analyst")
    updated_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Suppression(TimestampMixin, Base):
    __tablename__ = "suppressions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    identifier_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    identifier_type: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(200))
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PrivacyRequest(TimestampMixin, Base):
    __tablename__ = "privacy_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(20))  # opt_out | correction | deletion
    identifier_type: Mapped[str] = mapped_column(String(20))
    identifier_hash: Mapped[str] = mapped_column(String(64), index=True)
    identifier_enc: Mapped[str] = mapped_column(Text)
    contact_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
