"""Append-only audit trail. Never stores raw identifiers – only keyed hashes."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from atlas_api.models import AuditLog


def audit(
    db: Session,
    *,
    actor_id: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
    commit: bool = True,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            outcome=outcome,
            details=details or {},
        )
    )
    if commit:
        db.commit()
