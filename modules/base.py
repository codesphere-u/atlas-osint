"""Intelligence modules.

A module owns one investigation input type. It decides *which* adapters run on
*which* identifiers (including passive pivots, e.g. from an email address to
its organisational domain), and applies module-specific post-processing and
guardrails to the findings. Modules never perform I/O themselves – adapters do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from integrations.sources.base import SourceAdapter
from integrations.sources.registry import SourceRegistry
from shared.types import Finding, Identifier, IdentifierType, MatchType


@dataclass
class CollectionTask:
    identifier: Identifier
    adapters: list[SourceAdapter]
    reason: str = "primary"
    match_override: MatchType | None = None  # e.g. variants are only ever SIMILAR
    flags: list[str] = field(default_factory=list)


class IntelligenceModule:
    name: str = "base"
    title: str = "Base"
    input_types: tuple[IdentifierType, ...] = ()
    guardrails: tuple[str, ...] = ()

    def plan(
        self, identifier: Identifier, registry: SourceRegistry, enabled: set[str], options: dict[str, Any]
    ) -> list[CollectionTask]:
        return [CollectionTask(identifier, registry.for_input(identifier.type, enabled))]

    def postprocess(self, findings: list[Finding], subject: Identifier) -> list[Finding]:
        return findings

    def summarize(self, findings: list[Finding], subject: Identifier) -> dict[str, Any]:
        return {"finding_count": len(findings)}
