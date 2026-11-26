import pytest

from engine.normalization.identifiers import (
    InvalidIdentifier,
    detect_type,
    name_key,
    normalize,
    normalize_domain,
    normalize_email,
    normalize_phone,
    normalize_url,
    normalize_username,
    org_name_key,
)
from shared.types import IdentifierType


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+44 20 7946 0958", "+442079460958"),
        ("+1 (415) 555-0199", "+14155550199"),
        ("004420 7946 0958".replace("00", "+", 1), "+442079460958"),
    ],
)
def test_phone_e164(raw, expected):
    assert normalize_phone(raw) == expected


def test_phone_with_default_region():
    assert normalize_phone("020 7946 0958", "GB") == "+442079460958"


@pytest.mark.parametrize("raw", ["12", "not a number", "+999 1"])
def test_phone_invalid(raw):
    with pytest.raises(InvalidIdentifier):
        normalize_phone(raw)


def test_email_normalisation_lowercases_and_idna():
    assert normalize_email("John.Doe@Example.COM") == "john.doe@example.com"
    assert normalize_email("user@bücher.example") == "user@xn--bcher-kva.example"


@pytest.mark.parametrize("raw", ["no-at-sign", "a@b", "a@@b.com", "a b@c.com"])
def test_email_invalid(raw):
    with pytest.raises(InvalidIdentifier):
        normalize_email(raw)


def test_domain_normalisation():
    assert normalize_domain("https://WWW.Example.com/path?q=1") == "example.com"
    assert normalize_domain("example.com.") == "example.com"
    for bad in ["localhost", "-bad.com", "a..b", "1.2.3.4", "x" * 300 + ".com"]:
        with pytest.raises(InvalidIdentifier):
            normalize_domain(bad)


def test_url_normalisation():
    assert normalize_url("Example.com/a/") == "https://example.com/a"
    assert normalize_url("http://www.example.com:80/") == "http://www.example.com/"
    with pytest.raises(InvalidIdentifier):
        normalize_url("ftp://example.com/")
    with pytest.raises(InvalidIdentifier):
        normalize_url("https://user:pass@example.com/")


def test_username_rules():
    assert normalize_username("@Octo_Cat") == "octo_cat"
    for bad in ["", "a b", "x" * 80, "../etc", "<script>"]:
        with pytest.raises(InvalidIdentifier):
            normalize_username(bad)


def test_control_characters_stripped():
    ident = normalize(IdentifierType.NAME, "Ada\u0000 Lovelace​")
    assert "\u0000" not in ident.value


def test_name_key_is_accent_and_case_insensitive():
    assert name_key("Mária  Exámple") == name_key("maria example")
    assert org_name_key("Siemens AG") == org_name_key("siemens")


@pytest.mark.parametrize(
    "raw,t",
    [
        ("someone@example.com", IdentifierType.EMAIL),
        ("https://example.com/x", IdentifierType.URL),
        ("8.8.8.8", IdentifierType.IP),
        ("+14155550199", IdentifierType.PHONE),
        ("example.org", IdentifierType.DOMAIN),
        ("Ada Lovelace", IdentifierType.NAME),
        ("octocat", IdentifierType.USERNAME),
    ],
)
def test_detect_type(raw, t):
    assert detect_type(raw) == t
