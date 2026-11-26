"""Celery application (Redis broker). Start with: ``celery -A workers.celery_app worker -B``."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from shared.config import get_settings

settings = get_settings()
broker = settings.redis_url or "redis://localhost:6379/0"

app = Celery("atlas", broker=broker, backend=broker, include=["workers.tasks"])
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=900,
    task_soft_time_limit=840,
    result_expires=3600,
    beat_schedule={
        "retention-purge": {"task": "atlas.retention_purge", "schedule": crontab(minute=17, hour="*/6")},
    },
)
