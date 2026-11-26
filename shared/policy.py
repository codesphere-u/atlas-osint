"""Privacy policy enforcement (data minimisation by design).

This filter runs on every finding *after* collection and *before* anything is
persisted, scored or shown to an analyst. It is deliberately conservative:

* Attributes whose keys indicate a prohibited category are removed.
* For investigations about individuals, free-text excerpts are scrubbed of
  patterns that look like residential addresses, phone numbers (other than the
  investigated one), payment cards, national identifiers, coordinates and
  credentials.
* Findings of prohibited types are dropped entirely.

Every action is counted and surfaced in the coverage report so that analysts
can see that data was withheld and why.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from shared.types import Finding, IdentifierType, SubjectKind

# Attribute keys that are never stored, for any subject.
ALWAYS_FORBIDDEN_KEY_PARTS = (
    "password",
    "passwd",
    "credential",
    "secret",
    "token",
    "session",
    "cookie",
    "private_key",
    "api_key",
    "apikey",
    "access_key",
    "secret_key",
    "auth",
    "authorization",
    "card_number",
    "cvv",
    "iban",
    "bank_account",
    "account_number",
    "routing_number",
    "ssn",
    "national_id",
    "passport",
    "tax_id_personal",
)

# Additional keys forbidden in dossiers about individuals.
INDIVIDUAL_FORBIDDEN_KEY_PARTS = (
    "address",
    "street",
    "postcode",
    "postal_code",
    "zip",
    "residence",
    "home",
    "location",
    "latitude",
    "longitude",
    "geo",
    "coordinates",
    "date_of_birth",
    "birth",
    "dob",
    "age",
    "gender",
    "sex",
    "religion",
    "ethnic",
    "race",
    "health",
    "medical",
    "disability",
    "sexual",
    "political",
    "union_membership",
    "biometric",
    "criminal",
    "phone",  # phone numbers other than the queried identifier are not collected for individuals
    "mobile",
    "whatsapp",
    "telegram",
    "salary",
    "income",
    "net_worth",
)

# Keys that look forbidden but are explicitly safe (exact match).
SAFE_KEYS = frozenset(
    {
        "phone_e164",
        "phone_region",
        "phone_country_code",
        "phone_line_type",
        "phone_valid",
        "phone_possible",
        "phone_national_format",
        "phone_international_format",
        "phone_carrier",
        "phone_timezones",
        "phone_description",
        "ip_address",
        "email_address_domain",
        "email_address",
        "token_count",
        "home_page",  # website URL
        "homepage",
        "location_type",
    }
)

FORBIDDEN_FINDING_TYPES_INDIVIDUAL = frozenset(
    {"residential_address", "precise_location", "financial_account", "credential", "sensitive_attribute"}
)
FORBIDDEN_FINDING_TYPES_ALL = frozenset({"credential", "financial_account"})

_REDACTIONS: list[tuple[str, re.Pattern[str]]] = [
    ("payment_card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("us_ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    (
        "coordinates",
        re.compile(r"[-+]?\b\d{1,2}\.\d{4,}\s*,\s*[-+]?\d{1,3}\.\d{4,}\b"),
    ),
    (
        "street_address",
        re.compile(
            r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,4}(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|"
            r"Court|Ct|Boulevard|Blvd|Way|Place|Pl|Terrace|Close)\b\.?",
        ),
    ),
    ("phone_number", re.compile(r"(?<![\w.])\+?\(?\d{1,4}\)?[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b")),
    ("secret", re.compile(r"(?i)\b(?:password|passwd|api[_-]?key|secret)\s*[:=]\s*\S+")),
]


@dataclass
class PolicyReport:
    attributes_removed: Counter[str] = field(default_factory=Counter)
    redactions: Counter[str] = field(default_factory=Counter)
    findings_dropped: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, dict[str, int]]:
        return {
            "attributes_removed": dict(self.attributes_removed),
            "redactions": dict(self.redactions),
            "findings_dropped": dict(self.findings_dropped),
        }

    def merge(self, other: PolicyReport) -> None:
        self.attributes_removed.update(other.attributes_removed)
        self.redactions.update(other.redactions)
        self.findings_dropped.update(other.findings_dropped)


_TOKEN_SPLIT = re.compile(r"[_\-\s.]+|(?<=[a-z0-9])(?=[A-Z])")


def _key_tokens(key: str) -> list[str]:
    return [t.lower() for t in _TOKEN_SPLIT.split(key) if t]


def _part_matches(part: str, tokens: list[str]) -> bool:
    if "_" in part:
        return f"_{part}_" in f"_{'_'.join(tokens)}_"
    return part in tokens


def _key_forbidden(key: str, subject_kind: SubjectKind) -> bool:
    """Token-based matching so that e.g. ``language`` is not mistaken for ``age``."""
    if key.lower() in SAFE_KEYS:
        return False
    tokens = _key_tokens(key)
    if any(_part_matches(part, tokens) for part in ALWAYS_FORBIDDEN_KEY_PARTS):
        return True
    if subject_kind == SubjectKind.INDIVIDUAL:
        return any(_part_matches(part, tokens) for part in INDIVIDUAL_FORBIDDEN_KEY_PARTS)
    return False


def scrub_text(text: str, *, keep: set[str], report: PolicyReport) -> str:
    """Redact sensitive patterns from free text, preserving the investigated identifiers."""

    def _sub(label: str) -> callable:  # type: ignore[valid-type]
        def repl(match: re.Match[str]) -> str:
            value = match.group(0)
            digits = re.sub(r"\D", "", value)
            if value in keep or (digits and digits in keep):
                return value
            if label == "phone_number" and len(digits) < 9:
                return value  # too short to be a phone number (years, counts, ...)
            if label == "payment_card" and not _luhn_ok(digits):
                return value
            report.redactions[label] += 1
            return f"[redacted:{label}]"

        return repl

    for label, pattern in _REDACTIONS:
        text = pattern.sub(_sub(label), text)
    return text


def _luhn_ok(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _clean_value(value: object, subject_kind: SubjectKind, keep: set[str], report: PolicyReport) -> object:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _key_forbidden(str(k), subject_kind):
                report.attributes_removed[str(k)] += 1
                continue
            out[k] = _clean_value(v, subject_kind, keep, report)
        return out
    if isinstance(value, list):
        return [_clean_value(v, subject_kind, keep, report) for v in value]
    if isinstance(value, str) and subject_kind == SubjectKind.INDIVIDUAL:
        return scrub_text(value, keep=keep, report=report)
    return value


def apply_privacy_policy(
    findings: list[Finding], subject_kind: SubjectKind, *, keep_values: set[str] | None = None
) -> tuple[list[Finding], PolicyReport]:
    report = PolicyReport()
    keep = set(keep_values or set())
    out: list[Finding] = []
    forbidden_types = (
        FORBIDDEN_FINDING_TYPES_INDIVIDUAL if subject_kind == SubjectKind.INDIVIDUAL else FORBIDDEN_FINDING_TYPES_ALL
    )
    for finding in findings:
        if finding.finding_type in forbidden_types:
            report.findings_dropped[finding.finding_type] += 1
            continue
        local_keep = keep | {finding.subject.value}
        if finding.subject.type == IdentifierType.PHONE:
            local_keep.add(re.sub(r"\D", "", finding.subject.value))
        f = finding.model_copy(deep=True)
        f.attributes = _clean_value(f.attributes, subject_kind, local_keep, report)  # type: ignore[assignment]
        f.evidence.metadata = _clean_value(f.evidence.metadata, subject_kind, local_keep, report)  # type: ignore[assignment]
        if f.evidence.excerpt and subject_kind == SubjectKind.INDIVIDUAL:
            f.evidence.excerpt = scrub_text(f.evidence.excerpt, keep=local_keep, report=report)
        if subject_kind == SubjectKind.INDIVIDUAL:
            f.description = scrub_text(f.description, keep=local_keep, report=report)
            # Phone numbers linked from profiles of individuals are private contact details.
            before = len(f.linked)
            f.linked = [
                li for li in f.linked if li.identifier.type != IdentifierType.PHONE or li.identifier.value in local_keep
            ]
            if len(f.linked) != before:
                report.attributes_removed["linked_phone"] += before - len(f.linked)
        out.append(f)
    return out, report
