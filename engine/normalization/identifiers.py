"""Identifier detection, validation and canonical normalisation.

Normalisation is what makes correlation explainable: two findings are only
linked by a shared identifier when their *normalised* values are equal.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

import phonenumbers
from email_validator import EmailNotValidError, validate_email

from shared.types import Identifier, IdentifierType


class InvalidIdentifier(ValueError):
    pass


USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9_])?$")
DOMAIN_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
MAX_INPUT_LEN = 512


def _clean(raw: str) -> str:
    if not isinstance(raw, str):
        raise InvalidIdentifier("identifier must be a string")
    value = unicodedata.normalize("NFKC", raw).strip()
    value = "".join(ch for ch in value if unicodedata.category(ch)[0] != "C")
    if not value:
        raise InvalidIdentifier("identifier is empty")
    if len(value) > MAX_INPUT_LEN:
        raise InvalidIdentifier("identifier is too long")
    return value


def normalize_phone(raw: str, default_region: str | None = None) -> str:
    value = _clean(raw)
    try:
        number = phonenumbers.parse(value, default_region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidIdentifier(f"not a parseable phone number: {exc}") from exc
    if not phonenumbers.is_possible_number(number):
        raise InvalidIdentifier("not a possible phone number for its region")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalize_email(raw: str) -> str:
    value = _clean(raw)
    try:
        info = validate_email(value, check_deliverability=False)
    except EmailNotValidError as exc:
        raise InvalidIdentifier(str(exc)) from exc
    local, _, domain = info.normalized.rpartition("@")
    return f"{local.lower()}@{normalize_domain(domain)}"


def normalize_domain(raw: str) -> str:
    value = _clean(raw).lower().rstrip(".")
    if "://" in value:
        value = urlsplit(value).hostname or ""
    value = value.split("/", 1)[0].split(":", 1)[0]
    if value.startswith("www."):
        value = value[4:]
    try:
        ascii_value = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidIdentifier("invalid internationalised domain name") from exc
    labels = ascii_value.split(".")
    if len(labels) < 2 or len(ascii_value) > 253:
        raise InvalidIdentifier("domain must have at least two labels")
    if not all(DOMAIN_LABEL_RE.match(label) for label in labels):
        raise InvalidIdentifier("domain contains invalid labels")
    if labels[-1].isdigit():
        raise InvalidIdentifier("top-level domain cannot be numeric")
    return ascii_value


def normalize_url(raw: str) -> str:
    value = _clean(raw)
    if "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https"):
        raise InvalidIdentifier("only http(s) URLs are supported")
    if parts.username or parts.password:
        raise InvalidIdentifier("URLs with embedded credentials are not accepted")
    host = parts.hostname or ""
    try:
        ipaddress.ip_address(host)
        norm_host = host
    except ValueError:
        norm_host = normalize_domain(host) if host else ""
        if host.lower().startswith("www."):
            norm_host = "www." + norm_host
    if not norm_host:
        raise InvalidIdentifier("URL has no host")
    netloc = norm_host if parts.port in (None, 80, 443) else f"{norm_host}:{parts.port}"
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


def normalize_username(raw: str) -> str:
    value = _clean(raw).lstrip("@")
    if not USERNAME_RE.match(value):
        raise InvalidIdentifier("username may contain letters, digits, '.', '_' and '-' (max 64)")
    return value.lower()


def normalize_name(raw: str) -> str:
    value = _clean(raw)
    value = re.sub(r"\s+", " ", value)
    if not re.search(r"[^\W\d_]", value):
        raise InvalidIdentifier("name must contain letters")
    if len(value) > 200:
        raise InvalidIdentifier("name too long")
    return value


def name_key(name: str) -> str:
    """Accent- and case-insensitive comparison key for names (used to flag collisions only)."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", stripped.casefold())).strip()


_LEGAL_FORMS = re.compile(
    r"\b(inc|incorporated|ltd|limited|llc|llp|plc|gmbh|ag|sa|sas|srl|bv|nv|oy|ab|as|kk|corp|corporation|co|company)\b"
)


def org_name_key(name: str) -> str:
    """Comparison key for organisation names that ignores common legal-form suffixes."""
    return re.sub(r"\s+", " ", _LEGAL_FORMS.sub("", name_key(name))).strip()


def normalize_ip(raw: str) -> str:
    try:
        return str(ipaddress.ip_address(_clean(raw)))
    except ValueError as exc:
        raise InvalidIdentifier("invalid IP address") from exc


def normalize_organization(raw: str) -> str:
    return normalize_name(raw)


_NORMALIZERS = {
    IdentifierType.PHONE: normalize_phone,
    IdentifierType.EMAIL: normalize_email,
    IdentifierType.DOMAIN: normalize_domain,
    IdentifierType.URL: normalize_url,
    IdentifierType.DOCUMENT: normalize_url,
    IdentifierType.USERNAME: normalize_username,
    IdentifierType.NAME: normalize_name,
    IdentifierType.ORGANIZATION: normalize_organization,
    IdentifierType.IP: normalize_ip,
}


def normalize(type_: IdentifierType | str, raw: str, *, default_region: str | None = None) -> Identifier:
    t = IdentifierType(type_)
    if t == IdentifierType.PHONE:
        value = normalize_phone(raw, default_region)
    else:
        value = _NORMALIZERS[t](raw)
    return Identifier(type=t, value=value, raw=raw)


def try_normalize(type_: IdentifierType | str, raw: str) -> Identifier | None:
    try:
        return normalize(type_, raw)
    except (InvalidIdentifier, ValueError):
        return None


def detect_type(raw: str) -> IdentifierType:
    """Best-effort detection of the identifier type for free-text input."""
    value = _clean(raw)
    if "@" in value and not value.startswith("@") and try_normalize(IdentifierType.EMAIL, value):
        return IdentifierType.EMAIL
    if value.lower().startswith(("http://", "https://")):
        return IdentifierType.URL
    if try_normalize(IdentifierType.IP, value):
        return IdentifierType.IP
    if re.fullmatch(r"\+?[\d\s().-]{7,20}", value) and value.startswith("+"):
        if try_normalize(IdentifierType.PHONE, value):
            return IdentifierType.PHONE
    if " " not in value and "." in value and try_normalize(IdentifierType.DOMAIN, value):
        return IdentifierType.DOMAIN
    if " " in value:
        return IdentifierType.NAME
    if try_normalize(IdentifierType.USERNAME, value):
        return IdentifierType.USERNAME
    return IdentifierType.NAME
