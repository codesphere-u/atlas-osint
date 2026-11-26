from __future__ import annotations

from typing import Any

from modules.base import IntelligenceModule
from shared.types import Finding, Identifier, IdentifierType, MatchType


class PublicRecordsModule(IntelligenceModule):
    name = "public_records"
    title = "Public records intelligence"
    input_types = (IdentifierType.ORGANIZATION, IdentifierType.DOCUMENT)
    guardrails = (
        "Official registries and licensed datasets first; licence terms are recorded per finding.",
        "Officer / beneficial-owner personal data is not collected.",
        "Documents: robots.txt honoured, content hashed not republished.",
    )

    def summarize(self, findings: list[Finding], subject: Identifier) -> dict[str, Any]:
        regs = [f for f in findings if f.entity_kind == "organization"]
        return {
            "registry_records": len(regs),
            "exact_name_records": sum(1 for f in regs if f.match_type == MatchType.EXACT),
            "jurisdictions": sorted(
                {str(f.attributes.get("jurisdiction")) for f in regs if f.attributes.get("jurisdiction")}
            ),
            "news_mentions": sum(1 for f in findings if f.finding_type == "news_mention"),
            "documents": sum(1 for f in findings if f.finding_type == "public_document"),
        }
