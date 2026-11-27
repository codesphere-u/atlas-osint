from __future__ import annotations

from workers.celery_app import app


@app.task(name="atlas.run_investigation", bind=True, max_retries=0)
def run_investigation(self, investigation_id: str) -> str:  # type: ignore[no-untyped-def]
    from atlas_api.services.investigations import execute_investigation

    execute_investigation(investigation_id)
    return investigation_id


@app.task(name="atlas.retention_purge")
def retention_purge() -> int:
    from atlas_api.db import get_sessionmaker
    from atlas_api.services.investigations import purge_expired

    with get_sessionmaker()() as db:
        return purge_expired(db)


@app.task(name="atlas.run_due_monitors")
def run_due_monitors() -> list[str]:
    from atlas_api.db import get_sessionmaker
    from atlas_api.services.investigations import run_due_monitors as due

    with get_sessionmaker()() as db:
        return due(db, dispatch=lambda inv_id: run_investigation.delay(inv_id))
