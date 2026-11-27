"""ATLAS OSINT API application factory."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from atlas_api import __version__
from atlas_api.db import get_sessionmaker
from atlas_api.models import User
from atlas_api.routers import admin, auth, cases, investigations, meta, privacy, sources
from atlas_api.security import hash_password, validate_password_strength
from shared.config import get_settings
from shared.logging import configure_logging
from shared.ratelimit import WindowRateLimiter

log = logging.getLogger("atlas.api")


def run_migrations() -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    here = Path(__file__).parent / "migrations"
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")


def bootstrap_admin() -> None:
    s = get_settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        return
    with get_sessionmaker()() as db:
        email = s.bootstrap_admin_email.lower()
        if db.scalar(select(User).where(User.email == email)):
            return
        password = s.bootstrap_admin_password.get_secret_value()
        validate_password_strength(password)
        db.add(User(email=email, password_hash=hash_password(password), role="admin"))
        db.commit()
        log.info("bootstrap administrator created")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    problems = s.validate_production()
    if problems:
        raise RuntimeError("refusing to start with insecure production configuration: " + "; ".join(problems))
    if s.auto_migrate:
        run_migrations()
    bootstrap_admin()
    stop = threading.Event()
    scheduler: threading.Thread | None = None
    if s.task_backend == "inline":
        from atlas_api.services.investigations import purge_expired

        with get_sessionmaker()() as db:
            purge_expired(db)
        if s.inline_scheduler:
            scheduler = threading.Thread(
                target=_inline_scheduler, args=(stop, s.scheduler_interval_seconds), name="atlas-scheduler", daemon=True
            )
            scheduler.start()
    yield
    stop.set()
    if scheduler is not None:
        scheduler.join(timeout=5)


def _inline_scheduler(stop: threading.Event, interval: int) -> None:
    """Single-node scheduler: runs due monitoring jobs and the hourly retention purge (Celery beat does this
    when ATLAS_TASK_BACKEND=celery)."""
    from atlas_api.services.investigations import purge_expired, run_due_monitors

    last_purge = time.monotonic()
    while not stop.wait(interval):
        try:
            with get_sessionmaker()() as db:
                run_due_monitors(db)
                if time.monotonic() - last_purge > 3600:
                    purge_expired(db)
                    last_purge = time.monotonic()
        except Exception:
            log.exception("inline scheduler iteration failed")


def _redis_client() -> Any | None:
    url = get_settings().redis_url
    if not url:
        return None
    try:
        import redis

        return redis.Redis.from_url(url, socket_timeout=0.5)
    except Exception:
        return None


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="ATLAS OSINT API",
        version=__version__,
        description="Open-source intelligence. Connected evidence. Verifiable insights.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    limiter = WindowRateLimiter(_redis_client())

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.monotonic()
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > s.max_request_bytes:
            return JSONResponse({"detail": "request body too large"}, status_code=413)
        path = request.url.path
        if path.startswith("/api/"):
            ip = request.client.host if request.client else "unknown"
            public = (
                path.startswith("/api/v1/privacy/requests") and request.method == "POST"
            ) or path == "/api/v1/auth/login"
            auth = request.headers.get("authorization", "")[-16:] or request.cookies.get("atlas_session", "")[-16:]
            key = f"public:{ip}:{path}" if public else f"api:{auth or ip}"
            limit = s.public_rate_limit_per_minute if public else s.api_rate_limit_per_minute
            allowed, _remaining, reset = limiter.hit(key, limit)
            # Per-IP ceiling as well, so rotating (invalid) credentials cannot bypass the per-credential limit.
            if allowed and not public:
                allowed, _remaining, reset = limiter.hit(f"ip:{ip}", limit * 4)
            if not allowed:
                return JSONResponse(
                    {"detail": "rate limit exceeded"}, status_code=429, headers={"Retry-After": str(reset)}
                )
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if s.cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        if path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = rid
        log.info(
            "%s %s %s",
            request.method,
            path,
            response.status_code,
            extra={
                "request_id": rid,
                "duration_ms": int((time.monotonic() - start) * 1000),
                "status": response.status_code,
            },
        )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Atlas-CSRF", "X-Request-ID"],
        expose_headers=["X-Total-Count", "X-Request-ID"],
    )
    for r in (
        meta.router,
        auth.router,
        investigations.router,
        cases.router,
        sources.router,
        privacy.router,
        admin.router,
    ):
        app.include_router(r)
    return app


app = create_app()
