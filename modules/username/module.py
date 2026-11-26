from __future__ import annotations

from typing import Any

from modules.base import CollectionTask, IntelligenceModule
from shared.types import Finding, Identifier, IdentifierType, MatchType


def username_variants(handle: str, limit: int = 3) -> list[str]:
    """Common separator variants of a handle (``john_doe`` -> ``johndoe``, ``john.doe``, ``john-doe``)."""
    seps = ["_", ".", "-"]
    base = handle
    for s in seps:
        base = base.replace(s, " ")
    tokens = [t for t in base.split(" ") if t]
    if len(tokens) < 2:
        return []
    candidates = ["".join(tokens)] + [s.join(tokens) for s in seps]
    return [c for c in dict.fromkeys(candidates) if c != handle][:limit]


class UsernameModule(IntelligenceModule):
    name = "username"
    title = "Username intelligence"
    input_types = (IdentifierType.USERNAME,)
    guardrails = (
        "Exact handle matches are distinguished from similar handles.",
        "Accounts on different platforms are never merged on the handle alone.",
        "Only public profile metadata from official APIs; no login, no private data.",
    )

    def plan(self, identifier, registry, enabled, options) -> list[CollectionTask]:
        adapters = registry.for_input(IdentifierType.USERNAME, enabled)
        tasks = [CollectionTask(identifier, adapters)]
        if options.get("include_variants"):
            for v in username_variants(identifier.value):
                tasks.append(
                    CollectionTask(
                        Identifier(type=IdentifierType.USERNAME, value=v, raw=v),
                        adapters,
                        reason=f"variant of '{identifier.value}'",
                        match_override=MatchType.SIMILAR,
                        flags=["variant_query"],
                    )
                )
        return tasks

    def summarize(self, findings: list[Finding], subject: Identifier) -> dict[str, Any]:
        exact = sorted(
            x
            for x in {
                f.attributes.get("platform")
                for f in findings
                if f.finding_type == "account_profile" and f.match_type == MatchType.EXACT
            }
            if x
        )
        similar = sorted(
            {
                f"{f.attributes.get('platform')}:{f.attributes.get('username')}"
                for f in findings
                if f.finding_type == "account_profile" and f.match_type == MatchType.SIMILAR
            }
        )
        return {"exact_platforms": exact, "similar_accounts": similar, "exact_count": len(exact)}
