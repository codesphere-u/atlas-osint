from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from atlas_api import __version__
from atlas_api.db import get_db
from atlas_api.schemas import LegalBasis
from engine.reporting.model import METHODOLOGY
from modules.registry import MODULES
from shared.config import get_settings
from shared.types import IdentifierType, SubjectKind

router = APIRouter(tags=["meta"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.get("/api/v1/meta")
def meta() -> dict[str, Any]:
    s = get_settings()
    return {
        "version": __version__,
        "identifier_types": [t.value for t in IdentifierType],
        "subject_kinds": [k.value for k in SubjectKind],
        "legal_bases": [b.value for b in LegalBasis],
        "require_consent_for_individuals": s.require_consent_for_individuals,
        "default_retention_days": s.default_retention_days,
        "max_retention_days": s.max_retention_days,
        "ai_provider": s.ai_provider,
        "modules": [
            {
                "name": m.name,
                "title": m.title,
                "input_types": [t.value for t in m.input_types],
                "guardrails": list(m.guardrails),
            }
            for m in MODULES
        ],
        "methodology": METHODOLOGY,
    }
