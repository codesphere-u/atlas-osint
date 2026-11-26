"""Email sources.

ATLAS never connects to mail servers to probe mailboxes (no SMTP RCPT probing),
never triggers password-reset flows and never attempts mailbox access. Email
intelligence is limited to syntax/domain analysis, public DNS policy records
and – with documented consent – an authorised breach-notification service.
"""

from __future__ import annotations

from urllib.parse import quote

from email_validator import EmailNotValidError, validate_email

from integrations.sources.base import (
    AuthRequirement,
    CollectionContext,
    LegalInfo,
    RateLimit,
    SourceAdapter,
    SourceError,
    SourceMetadata,
    parse_datetime,
)
from shared.dns import DnsLookupError, resolve
from shared.types import (
    AccessMethod,
    AdapterStatus,
    Finding,
    Identifier,
    IdentifierType,
    LinkedIdentifier,
    Reliability,
    SourceCategory,
)

FREEMAIL_DOMAINS = frozenset(
    """gmail.com googlemail.com outlook.com hotmail.com live.com msn.com yahoo.com ymail.com icloud.com me.com
    mac.com aol.com proton.me protonmail.com pm.me gmx.com gmx.de gmx.net web.de mail.com yandex.com yandex.ru
    zoho.com tutanota.com tuta.io fastmail.com hey.com qq.com 163.com 126.com mail.ru inbox.ru""".split()
)
DISPOSABLE_DOMAINS = frozenset(
    """mailinator.com guerrillamail.com 10minutemail.com tempmail.com temp-mail.org yopmail.com trashmail.com
    sharklasers.com getnada.com dispostable.com maildrop.cc throwawaymail.com""".split()
)
ROLE_LOCALPARTS = frozenset(
    """admin administrator info contact support help sales marketing billing abuse postmaster hostmaster
    webmaster security noc office hello press media jobs careers hr legal privacy team""".split()
)


def _dns(ctx: CollectionContext):
    return ctx.extra.get("dns_resolver", resolve)


class EmailSyntaxAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="email_syntax",
        display_name="ATLAS email syntax & provider analysis",
        description="Offline RFC 5322/6531 syntax validation and provider classification "
        "(free-mail, disposable, role account).",
        category=SourceCategory.EMAIL,
        input_types=[IdentifierType.EMAIL],
        access_method=AccessMethod.OFFLINE_DATASET,
        homepage="https://github.com/JoshData/python-email-validator",
        rate_limit=RateLimit(requests=0, per_seconds=1, notes="offline"),
        legal=LegalInfo(license="Unlicense / Apache-2.0", restrictions="Offline analysis only."),
        fields=["syntax_valid", "normalized", "email_address_domain", "provider_type", "role_account", "smtputf8"],
        freshness="static",
        reliability=Reliability.A,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        try:
            info = validate_email(identifier.value, check_deliverability=False)
        except EmailNotValidError as exc:
            return [
                self.finding(
                    module="email",
                    subject=identifier,
                    finding_type="email_syntax",
                    title="Email address is syntactically invalid",
                    description=str(exc),
                    url="https://www.rfc-editor.org/rfc/rfc5322",
                    attributes={"syntax_valid": False},
                )
            ]
        local, domain = info.local_part.lower(), info.domain.lower()
        provider = (
            "disposable"
            if domain in DISPOSABLE_DOMAINS
            else "free_mail"
            if domain in FREEMAIL_DOMAINS
            else "organizational_or_custom"
        )
        role = local.split("+", 1)[0] in ROLE_LOCALPARTS
        linked = []
        if provider == "organizational_or_custom":
            linked.append(
                LinkedIdentifier(
                    identifier=Identifier(type=IdentifierType.DOMAIN, value=domain), relation="email_domain"
                )
            )
        return [
            self.finding(
                module="email",
                subject=identifier,
                finding_type="email_syntax",
                title=f"Email syntax valid; provider type: {provider.replace('_', ' ')}",
                description=f"The address is syntactically valid. Domain '{domain}' is classified as "
                f"{provider.replace('_', ' ')}" + ("; the local part is a role account." if role else "."),
                url="https://www.rfc-editor.org/rfc/rfc5322",
                attributes={
                    "syntax_valid": True,
                    "normalized": info.normalized,
                    "email_address_domain": domain,
                    "provider_type": provider,
                    "role_account": role,
                    "smtputf8": info.smtputf8,
                },
                linked=linked,
                entity_hint=f"email:{identifier.value}",
                entity_kind="email",
                claim_key=f"email.syntax:{identifier.value}=valid",
            )
        ]


class EmailDomainDnsAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="email_domain_dns",
        display_name="Public DNS (MX / SPF / DMARC)",
        description="Mail exchanger and published sender-policy records of the email domain.",
        category=SourceCategory.EMAIL,
        input_types=[IdentifierType.EMAIL],
        access_method=AccessMethod.DNS,
        homepage="https://www.rfc-editor.org/rfc/rfc7489",
        rate_limit=RateLimit(requests=20, per_seconds=1),
        legal=LegalInfo(restrictions="Public DNS data."),
        fields=["mx_records", "accepts_mail", "spf", "dmarc", "dmarc_policy", "mail_provider"],
        freshness="real-time (subject to DNS TTLs)",
        reliability=Reliability.A,
    )

    PROVIDERS = {
        "google.com": "Google Workspace / Gmail",
        "googlemail.com": "Google Workspace / Gmail",
        "outlook.com": "Microsoft 365 / Outlook",
        "protection.outlook.com": "Microsoft 365",
        "pphosted.com": "Proofpoint",
        "mimecast.com": "Mimecast",
        "zoho.com": "Zoho Mail",
        "protonmail.ch": "Proton Mail",
        "messagingengine.com": "Fastmail",
        "icloud.com": "iCloud Mail",
        "yahoodns.net": "Yahoo Mail",
    }

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        domain = identifier.value.rsplit("@", 1)[1]
        resolver = _dns(ctx)
        try:
            mx = await resolver(domain, "MX")
            txt = await resolver(domain, "TXT")
            dmarc_txt = await resolver(f"_dmarc.{domain}", "TXT")
        except DnsLookupError as exc:
            raise SourceError(AdapterStatus.UNAVAILABLE, str(exc)) from exc
        mx_hosts = sorted((r.split()[-1].rstrip(".").lower() for r in mx if r.split()), key=str)
        spf = next((t for t in txt if t.lower().startswith("v=spf1")), None)
        dmarc = next((t for t in dmarc_txt if t.lower().startswith("v=dmarc1")), None)
        policy = None
        if dmarc:
            for part in dmarc.split(";"):
                k, _, v = part.strip().partition("=")
                if k.lower() == "p":
                    policy = v.strip()
        provider = next(
            (name for suffix, name in self.PROVIDERS.items() if any(h.endswith(suffix) for h in mx_hosts)), None
        )
        accepts = bool(mx_hosts) and mx_hosts != [""]
        desc = (
            f"Domain {domain} publishes {len(mx_hosts)} MX record(s)"
            + (f" ({provider})" if provider else "")
            + f"; SPF {'present' if spf else 'absent'}; DMARC {'policy ' + policy if policy else 'absent'}. "
            "MX records show the domain can receive mail; they do not prove that this specific mailbox exists."
        )
        return [
            self.finding(
                module="email",
                subject=identifier,
                finding_type="email_domain_mail_config",
                title=f"Mail configuration of {domain}",
                description=desc,
                url=f"dns:{domain}",
                attributes={
                    "mx_records": mx_hosts,
                    "accepts_mail": accepts,
                    "spf": spf,
                    "dmarc": dmarc,
                    "dmarc_policy": policy,
                    "mail_provider": provider,
                },
                excerpt="; ".join(mx_hosts[:5]),
                entity_hint=f"domain:{domain}",
                entity_kind="domain",
                claim_key=f"domain.mx:{domain}={','.join(mx_hosts)}",
            )
        ]


class HibpAdapter(SourceAdapter):
    """Have I Been Pwned – authorised breach *notification* service (breach names only)."""

    meta = SourceMetadata(
        name="hibp",
        display_name="Have I Been Pwned (breach notification)",
        description="Lists names of publicly disclosed data breaches that included the address. Never returns "
        "breached data itself. Requires an API key and documented consent of the address owner.",
        category=SourceCategory.BREACH_NOTIFICATION,
        input_types=[IdentifierType.EMAIL],
        access_method=AccessMethod.LICENSED_API,
        homepage="https://haveibeenpwned.com/API/v3",
        auth=AuthRequirement(
            required=True,
            kind="api_key",
            settings_fields=["hibp_api_key"],
            how_to_obtain="Purchase an API key at https://haveibeenpwned.com/API/Key",
        ),
        rate_limit=RateLimit(requests=10, per_seconds=60, notes="depends on subscription"),
        legal=LegalInfo(
            terms_url="https://haveibeenpwned.com/API/v3#AcceptableUse",
            license="CC-BY-4.0 (breach metadata)",
            restrictions="Acceptable use: only for the protection of the address owner. ATLAS requires "
            "documented consent (or self-lookup) before calling this API.",
            contains_personal_data=True,
            requires_subject_consent=True,
        ),
        fields=["breach_name", "breach_domain", "breach_date", "data_classes", "is_verified"],
        freshness="real-time",
        reliability=Reliability.B,
        default_enabled=False,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resp = await self.fetch(
            ctx,
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{quote(identifier.value)}",
            params={"truncateResponse": "false"},
            headers={"hibp-api-key": ctx.secret("hibp_api_key") or ""},
        )
        if resp.status_code == 404:
            return []
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        out = []
        for b in resp.json():
            out.append(
                self.finding(
                    module="email",
                    subject=identifier,
                    finding_type="breach_notification",
                    title=f"Address appears in disclosed breach: {b.get('Title') or b.get('Name')}",
                    description=f"HIBP reports the address in the '{b.get('Name')}' breach "
                    f"({b.get('BreachDate')}). Exposed data classes: {', '.join(b.get('DataClasses') or [])}. "
                    "No breached data is retrieved by ATLAS.",
                    url=f"https://haveibeenpwned.com/PwnedWebsites#{b.get('Name')}",
                    attributes={
                        "breach_name": b.get("Name"),
                        "breach_domain": b.get("Domain"),
                        "breach_date": b.get("BreachDate"),
                        "data_classes": b.get("DataClasses"),
                        "is_verified": b.get("IsVerified"),
                    },
                    published_at=parse_datetime(b.get("AddedDate")),
                    entity_hint=f"email:{identifier.value}",
                    entity_kind="email",
                    claim_key=f"email.breach:{identifier.value}:{b.get('Name')}",
                )
            )
        return out
