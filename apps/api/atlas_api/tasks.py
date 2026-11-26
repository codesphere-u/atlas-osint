"""Task dispatch: inline (FastAPI background task, single-node) or Celery (distributed workers)."""

from __future__ import annotations

from fastapi import BackgroundTasks

from atlas_api.services.investigations import execute_investigation
from shared.config import get_settings


def dispatch_investigation(investigation_id: str, background: BackgroundTasks | None) -> str:
    settings = get_settings()
    if settings.task_backend == "celery":
        from workers.tasks import run_investigation

        run_investigation.delay(investigation_id)
        return "celery"
    if background is not None:
        background.add_task(execute_investigation, investigation_id)
    else:
        execute_investigation(investigation_id)
    return "inline"
