from __future__ import annotations

from typing import Any

from modules.base import IntelligenceModule
from shared.types import Finding, Identifier, IdentifierType

# Attribute keys that would amount to identifying a subscriber. No built-in adapter emits these;
# the guard protects against third-party plugins doing so.
_SUBSCRIBER_KEYS = ("subscriber", "owner", "holder_name", "caller_name", "cnam", "registered_to")


class PhoneModule(IntelligenceModule):
    name = "phone"
    title = "Phone intelligence"
    input_types = (IdentifierType.PHONE,)
    guardrails = (
        "Never asserts the identity of a private subscriber.",
        "Carrier = original range allocation; number portability is disclosed.",
        "Region is numbering-plan level, never a precise location.",
    )

    def postprocess(self, findings: list[Finding], subject: Identifier) -> list[Finding]:
        for f in findings:
            for key in list(f.attributes):
                if any(s in key.lower() for s in _SUBSCRIBER_KEYS):
                    f.attributes.pop(key)
                    f.flags.append("subscriber_identity_removed")
        return findings

    def summarize(self, findings: list[Finding], subject: Identifier) -> dict[str, Any]:
        plan = next((f for f in findings if f.finding_type == "phone_numbering_plan"), None)
        a = plan.attributes if plan else {}
        return {
            "e164": a.get("phone_e164", subject.value),
            "valid": a.get("phone_valid"),
            "region": a.get("phone_region"),
            "line_type": a.get("phone_line_type"),
            "original_carrier": a.get("phone_carrier"),
            "subscriber_identified": False,
            "public_references": sum(
                1
                for f in findings
                if f.finding_type not in ("phone_numbering_plan", "phone_region", "phone_carrier_lookup")
            ),
        }
