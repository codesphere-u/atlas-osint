"""Collection orchestrator: runs a module's collection plan across adapters concurrently.

It records a :class:`SourceRun` for every (adapter, identifier) pair – including
skipped, unconfigured and failed sources – so every report can state exactly
which sources were consulted and what coverage was achieved.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from integrations.sources.base import AuthorizationScope, CollectionContext
from integrations.sources.registry import SourceRegistry
from modules.base import CollectionTask, IntelligenceModule
from shared.config import Settings
from shared.http import SafeHttpClient
from shared.types import AdapterStatus, Finding, Identifier


@dataclass
class SourceRun:
    source_name: str
    identifier: str
    reason: str
    status: AdapterStatus
    message: str | None
    finding_count: int
    duration_ms: int
    started_at: datetime
    http_status: int | None = None


@dataclass
class CollectionOutcome:
    findings: list[Finding] = field(default_factory=list)
    runs: list[SourceRun] = field(default_factory=list)


ProgressCallback = Callable[[SourceRun, int, int], None]


def build_http_client(settings: Settings, **overrides: Any) -> SafeHttpClient:
    return SafeHttpClient(
        user_agent=settings.user_agent,
        timeout=settings.http_timeout_seconds,
        max_bytes=settings.http_max_response_bytes,
        allowed_ports=settings.http_allowed_ports,
        pin_dns=settings.http_pin_dns,
        **overrides,
    )


async def collect(
    *,
    subject: Identifier,
    module: IntelligenceModule,
    registry: SourceRegistry,
    enabled_sources: set[str],
    scope: AuthorizationScope,
    settings: Settings,
    options: dict[str, Any] | None = None,
    http: SafeHttpClient | None = None,
    progress: ProgressCallback | None = None,
    extra: dict[str, Any] | None = None,
    investigation_id: str | None = None,
) -> CollectionOutcome:
    options = options or {}
    tasks: list[CollectionTask] = module.plan(subject, registry, enabled_sources, options)
    jobs = [(task, adapter) for task in tasks for adapter in task.adapters]
    total = len(jobs)
    own_client = http is None
    client = http or build_http_client(settings)
    ctx = CollectionContext(
        http=client, settings=settings, scope=scope, investigation_id=investigation_id, extra=extra or {}
    )
    sem = asyncio.Semaphore(max(1, settings.max_concurrent_adapters))
    outcome = CollectionOutcome()
    done_count = 0
    lock = asyncio.Lock()

    async def run_one(task: CollectionTask, adapter: Any) -> None:
        nonlocal done_count
        async with sem:
            result = await adapter.run(task.identifier, ctx)
        for f in result.findings:
            # Findings are always attributed to the investigation subject; pivots keep the queried value.
            if task.identifier != subject:
                f.flags.append(f"queried:{task.identifier.key}")
                f.subject = subject
            if task.match_override is not None:
                f.match_type = task.match_override
            f.flags.extend(task.flags)
        run = SourceRun(
            source_name=adapter.meta.name,
            identifier=task.identifier.key,
            reason=task.reason,
            status=result.status,
            message=result.message,
            finding_count=len(result.findings),
            duration_ms=result.duration_ms,
            started_at=result.started_at,
            http_status=result.http_status,
        )
        async with lock:
            outcome.findings.extend(result.findings)
            outcome.runs.append(run)
            done_count += 1
            if progress:
                progress(run, done_count, total)

    try:
        await asyncio.gather(*(run_one(t, a) for t, a in jobs))
    finally:
        if own_client:
            await client.aclose()
    outcome.runs.sort(key=lambda r: (r.identifier, r.source_name))
    return outcome
