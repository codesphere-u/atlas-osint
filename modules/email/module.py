from __future__ import annotations

from typing import Any

from integrations.sources.email import DISPOSABLE_DOMAINS, FREEMAIL_DOMAINS
from modules.base import CollectionTask, IntelligenceModule
from shared.types import Finding, Identifier, IdentifierType, MatchType

# Passive domain sources used when pivoting from an organisational email address to its domain.
PIVOT_SOURCES = ("rdap_domain", "dns_records", "wayback")


class EmailModule(IntelligenceModule):
    name = "email"
    title = "Email intelligence"
    input_types = (IdentifierType.EMAIL,)
    guardrails = (
        "No mailbox probing (SMTP), no password-reset enumeration, no mailbox access.",
        "Breach-notification lookups require documented consent and return breach names only.",
        "Domain pivots are passive (DNS, RDAP, archive).",
    )

    def plan(self, identifier, registry, enabled, options) -> list[CollectionTask]:
        tasks = [CollectionTask(identifier, registry.for_input(IdentifierType.EMAIL, enabled))]
        domain = identifier.value.rsplit("@", 1)[1]
        if domain not in FREEMAIL_DOMAINS and domain not in DISPOSABLE_DOMAINS and options.get("pivot_domain", True):
            adapters = [a for a in registry.for_input(IdentifierType.DOMAIN, enabled) if a.meta.name in PIVOT_SOURCES]
            tasks.append(
                CollectionTask(
                    Identifier(type=IdentifierType.DOMAIN, value=domain),
                    adapters,
                    reason="email domain pivot",
                    match_override=MatchType.RELATED,
                    flags=["pivot:email_domain"],
                )
            )
        return tasks

    def summarize(self, findings: list[Finding], subject: Identifier) -> dict[str, Any]:
        syntax = next((f for f in findings if f.finding_type == "email_syntax"), None)
        mail = next((f for f in findings if f.finding_type == "email_domain_mail_config"), None)
        return {
            "syntax_valid": syntax.attributes.get("syntax_valid") if syntax else None,
            "provider_type": syntax.attributes.get("provider_type") if syntax else None,
            "domain_accepts_mail": mail.attributes.get("accepts_mail") if mail else None,
            "breach_notifications": sum(1 for f in findings if f.finding_type == "breach_notification"),
            "mailbox_probed": False,
        }
