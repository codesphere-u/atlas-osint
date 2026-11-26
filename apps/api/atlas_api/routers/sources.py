from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas_api.audit import audit
from atlas_api.db import get_db
from atlas_api.deps import Principal, client_ip, require
from atlas_api.models import Investigation, SourceConfig
from atlas_api.schemas import SourceUpdate
from atlas_api.security import Permission
from integrations.sources.base import SourceAdapter
from integrations.sources.registry import get_registry
from shared.config import get_settings
from shared.types import IdentifierType

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


def source_out(a: SourceAdapter, cfg: SourceConfig | None, health: dict[str, int]) -> dict[str, Any]:
    configured, reason = a.configuration_status(get_settings())
    m = a.meta
    return {
        **m.model_dump(mode="json"),
        "enabled": cfg.enabled if cfg else m.default_enabled,
        "min_role": cfg.min_role if cfg else "analyst",
        "configured": configured,
        "configuration_message": reason,
        "health": health,
    }


def _health(db: Session) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    recent = db.scalars(select(Investigation).order_by(Investigation.created_at.desc()).limit(100)).all()
    for inv in recent:
        for src, st in ((inv.progress or {}).get("sources") or {}).items():
            out.setdefault(src, {})
            out[src][st] = out[src].get(st, 0) + 1
    return out


@router.get("")
def list_sources(
    principal: Principal = Depends(require(Permission.SOURCE_READ)), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    configs = {c.source_name: c for c in db.scalars(select(SourceConfig)).all()}
    health = _health(db)
    return [source_out(a, configs.get(a.meta.name), health.get(a.meta.name, {})) for a in get_registry().all()]


@router.get("/coverage")
def coverage_matrix(
    principal: Principal = Depends(require(Permission.SOURCE_READ)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    configs = {c.source_name: c for c in db.scalars(select(SourceConfig)).all()}
    matrix: dict[str, list[dict[str, Any]]] = {}
    for t in IdentifierType:
        rows = []
        for a in get_registry().for_input(t):
            cfg = configs.get(a.meta.name)
            configured, _ = a.configuration_status(get_settings())
            rows.append(
                {
                    "source": a.meta.name,
                    "display_name": a.meta.display_name,
                    "enabled": cfg.enabled if cfg else a.meta.default_enabled,
                    "configured": configured,
                    "reliability": a.meta.reliability.value,
                    "access_method": a.meta.access_method.value,
                }
            )
        matrix[t.value] = rows
    return {"matrix": matrix}


@router.patch("/{name}")
def update_source(
    name: str,
    body: SourceUpdate,
    request: Request,
    principal: Principal = Depends(require(Permission.SOURCE_MANAGE)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    adapter = get_registry().get(name)
    if adapter is None:
        raise HTTPException(status_code=404, detail="unknown source")
    cfg = db.get(SourceConfig, name) or SourceConfig(source_name=name, enabled=adapter.meta.default_enabled)
    if body.enabled is not None:
        cfg.enabled = body.enabled
    if body.min_role is not None:
        cfg.min_role = body.min_role
    cfg.updated_by = principal.id
    db.add(cfg)
    db.commit()
    audit(
        db,
        actor_id=principal.id,
        action="source.update",
        target_type="source",
        target_id=name,
        ip=client_ip(request),
        details=body.model_dump(exclude_none=True),
    )
    return source_out(adapter, cfg, _health(db).get(name, {}))
