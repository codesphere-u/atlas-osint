from __future__ import annotations

from collections import defaultdict
from typing import Any

from engine.normalization.identifiers import name_key
from modules.base import IntelligenceModule
from shared.types import Finding, Identifier, IdentifierType, MatchType


class NameModule(IntelligenceModule):
    name = "name"
    title = "Name intelligence"
    input_types = (IdentifierType.NAME,)
    guardrails = (
        "Individuals are never merged on a matching name alone.",
        "Each candidate is keyed by a persistent identifier (ORCID, OpenAlex, Wikidata).",
        "Name collisions are flagged explicitly.",
    )

    def postprocess(self, findings: list[Finding], subject: Identifier) -> list[Finding]:
        by_name: dict[str, set[str]] = defaultdict(set)
        for f in findings:
            if f.entity_kind == "person" and f.entity_hint:
                by_name[name_key(str(f.attributes.get("candidate_name", "")))].add(f.entity_hint)
        for f in findings:
            key = name_key(str(f.attributes.get("candidate_name", "")))
            if f.entity_kind == "person" and len(by_name.get(key, ())) > 1:
                f.flags.append("name_collision")
        return findings

    def summarize(self, findings: list[Finding], subject: Identifier) -> dict[str, Any]:
        people = {f.entity_hint for f in findings if f.entity_kind == "person" and f.entity_hint}
        exact = {f.entity_hint for f in findings if f.entity_kind == "person" and f.match_type == MatchType.EXACT}
        return {
            "candidate_profiles": len(people),
            "exact_name_candidates": len(exact),
            "name_collision": len(exact) > 1,
            "news_mentions": sum(1 for f in findings if f.finding_type == "news_mention"),
        }
