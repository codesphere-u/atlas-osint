"""Tests for the v0.2 source adapters (HTTP mocked with respx, DNS with the fake resolver)."""

import json

import httpx
import respx

from integrations.sources.infrastructure import (
    CertSpotterAdapter,
    EmailSecurityAdapter,
    LookalikeDomainsAdapter,
    SecurityTxtAdapter,
    ShodanInternetDbAdapter,
    lookalike_candidates,
    parse_security_txt,
)
from integrations.sources.name import CrossrefWorksAdapter
from integrations.sources.public_records import GleifAdapter, OpenSanctionsAdapter
from integrations.sources.social import BlueskyAdapter, MastodonAdapter
from shared.dns import _unquote_txt, parse_doh_answer
from shared.types import AdapterStatus, EvidenceKind, Identifier, IdentifierType, MatchType
from tests.conftest import FIXTURES, install_source_mocks, load_fixture


def ident(t, v, raw=None):
    return Identifier(type=IdentifierType(t), value=v, raw=raw or v)


def j(name, status=200):
    return httpx.Response(status, json=load_fixture(name))


async def test_internetdb_flags_risky_ports_and_vulns(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://internetdb.shodan.io/93.184.216.34").mock(return_value=j("internetdb.json"))
        res = await ShodanInternetDbAdapter().run(ident("domain", "example.com"), ctx_factory())
    [f] = res.findings
    assert f.attributes["open_ports"] == [22, 80, 443, 3306]
    assert f.attributes["risky_ports"] == ["3306/MySQL"]
    assert f.attributes["vuln_count"] == 2
    assert {"risk:exposed_service", "risk:potential_vulnerabilities"} <= set(f.flags)
    assert "not confirmed exploitable" in f.description
    assert f.match_type == MatchType.RELATED  # queried a domain, data is about its IP


async def test_internetdb_unknown_ip_is_no_results(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://internetdb\.shodan\.io/.*").mock(
            return_value=httpx.Response(404, json={"detail": "No information available"})
        )
        res = await ShodanInternetDbAdapter().run(ident("ip", "93.184.216.34"), ctx_factory())
    assert res.status == AdapterStatus.NO_RESULTS


async def test_certspotter_subdomains_scope_and_corroboration_key(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://api\.certspotter\.com/.*").mock(return_value=j("certspotter.json"))
        out = await CertSpotterAdapter().run(ident("domain", "example.com"), ctx_factory())
        inside = await CertSpotterAdapter().run(ident("domain", "example.com"), ctx_factory(domains=["example.com"]))
    assert [f.finding_type for f in out.findings] == ["certificate_transparency_active"]
    subs = sorted(f.attributes["subdomain"] for f in inside.findings if f.finding_type == "subdomain")
    assert subs == ["api.example.com", "dev.example.com", "www.example.com"]
    # same claim key as crt.sh subdomains -> independent corroboration
    assert all(f.claim_key == f"domain.subdomain:{f.attributes['subdomain']}" for f in inside.findings[1:])


async def test_security_txt_requires_scope_and_parses_fields(ctx_factory):
    res = await SecurityTxtAdapter().run(ident("domain", "example.com"), ctx_factory())
    assert res.status == AdapterStatus.SKIPPED
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://example.com/.well-known/security.txt").mock(
            return_value=httpx.Response(
                200, text=(FIXTURES / "security.txt").read_text(), headers={"content-type": "text/plain; charset=utf-8"}
            )
        )
        res = await SecurityTxtAdapter().run(ident("domain", "example.com"), ctx_factory(domains=["example.com"]))
    a = res.findings[0].attributes
    assert a["present"] is True and a["expired"] is False
    assert a["contact"] == ["mailto:security@example.com", "https://example.com/security"]
    assert parse_security_txt("# comment\nContact: x\nbogus line\nUnknown: y")["contact"] == ["x"]


async def test_security_txt_absent_is_reported(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://example\.com/.*").mock(return_value=httpx.Response(404, text="nope"))
        res = await SecurityTxtAdapter().run(ident("domain", "example.com"), ctx_factory(domains=["example.com"]))
    assert res.findings[0].attributes == {"present": False}


async def test_email_security_records(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://mta-sts.example.com/.well-known/mta-sts.txt").mock(
            return_value=httpx.Response(
                200, text="version: STSv1\nmode: enforce\nmx: *.example-mail.test\nmax_age: 86400\n"
            )
        )
        res = await EmailSecurityAdapter().run(ident("domain", "example.com"), ctx_factory(domains=["example.com"]))
        out_scope = await EmailSecurityAdapter().run(ident("domain", "example.com"), ctx_factory())
    a = res.findings[0].attributes
    assert a["spf_all"] == "-all" and a["dmarc_policy"] == "reject" and a["dmarc_rua"] is True
    assert a["mta_sts"] is True and a["mta_sts_mode"] == "enforce" and a["tls_rpt"] is True
    assert a["dnssec"] is True and a["dkim_selectors_found"] == ["selector1"] and a["bimi"] is False
    assert out_scope.findings[0].attributes.get("mta_sts_mode") is None  # policy file only fetched in scope


def test_lookalike_candidates_are_deterministic_and_bounded():
    c = lookalike_candidates("example.com", 500)
    domains = [d for d, _ in c]
    assert domains == [d for d, _ in lookalike_candidates("example.com", 500)]
    assert "example.com" not in domains and len(domains) == len(set(domains))
    assert ("examp1e.com", "homoglyph") in c and ("exampel.com", "transposition") in c
    assert ("example.net", "tld-swap") in c
    assert len(lookalike_candidates("example.com", 10)) == 10


async def test_lookalikes_require_scope_and_detect_mail(ctx_factory):
    res = await LookalikeDomainsAdapter().run(ident("domain", "example.com"), ctx_factory())
    assert res.status == AdapterStatus.SKIPPED and "authorised scope" in res.message
    res = await LookalikeDomainsAdapter().run(ident("domain", "example.com"), ctx_factory(domains=["example.com"]))
    summary, *hits = res.findings
    by_domain = {f.attributes["lookalike_domain"]: f for f in hits}
    assert set(by_domain) == {"examp1e.com", "example.net", "exampel.com"}
    assert by_domain["examp1e.com"].attributes["mail_capable"] is True
    assert "risk:lookalike_mail" in by_domain["examp1e.com"].flags
    assert by_domain["exampel.com"].attributes["mail_capable"] is False  # null MX
    assert summary.attributes["registered_count"] == 3 and summary.attributes["mail_capable_count"] == 1
    assert by_domain["example.net"].linked[0].evidence_kind == EvidenceKind.INFERENCE


async def test_mastodon_verified_links(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://mastodon\.social/api/v1/accounts/lookup.*").mock(
            return_value=j("mastodon_account.json")
        )
        res = await MastodonAdapter().run(ident("username", "octo-sample"), ctx_factory(kind="individual"))
    f = res.findings[0]
    assert f.entity_hint == "account:mastodon:octo-sample@mastodon.social"
    rels = {(li.relation, li.identifier.value) for li in f.linked}
    assert ("verified_link", "https://octo.example.org/") in rels or (
        "verified_link",
        "https://octo.example.org",
    ) in rels
    assert any(r == "lists_website" for r, _ in rels)  # unverified field -> plain listed website


async def test_bluesky_custom_domain_handle_is_verified_domain(ctx_factory):
    assert BlueskyAdapter.candidates("octo") == ["octo.bsky.social"]
    assert BlueskyAdapter.candidates("octo.example.org") == ["octo.example.org"]
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://public\.api\.bsky\.app/.*").mock(return_value=j("bluesky_profile.json"))
        res = await BlueskyAdapter().run(ident("username", "octo.example.org"), ctx_factory(kind="individual"))
    f = res.findings[0]
    assert ("verified_domain_handle", "octo.example.org") in {(li.relation, li.identifier.value) for li in f.linked}


async def test_bluesky_not_found(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://public\.api\.bsky\.app/.*").mock(
            return_value=httpx.Response(400, json={"error": "InvalidRequest", "message": "Profile not found"})
        )
        res = await BlueskyAdapter().run(ident("username", "nobody"), ctx_factory(kind="individual"))
    assert res.status == AdapterStatus.NO_RESULTS


async def test_crossref_exact_author_and_orcid_link(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://api\.crossref\.org/works.*").mock(return_value=j("crossref_works.json"))
        res = await CrossrefWorksAdapter().run(ident("name", "Maria Example"), ctx_factory(kind="individual"))
    dois = [f.attributes["doi"] for f in res.findings]
    assert dois == ["10.5555/synth.001", "10.5555/synth.002"]  # fuzzy hit without that author excluded
    first = res.findings[0]
    assert first.linked[0].identifier.value == "https://orcid.org/0000-0002-1825-0097"
    assert first.attributes["author_position"] == 1 and first.attributes["coauthor_count"] == 1


async def test_gleif_corporate_hierarchy(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r".*/lei-records/5493001KJTIIGC8Y1R12/direct-parent").mock(
            return_value=j("gleif_parent.json")
        )
        mock.get(url__regex=r".*/lei-records/5493001KJTIIGC8Y1R12/ultimate-parent").mock(
            return_value=j("gleif_parent.json")
        )
        mock.get(url__regex=r".*/lei-records/5493001KJTIIGC8Y1R12/direct-children.*").mock(
            return_value=j("gleif_children.json")
        )
        install_source_mocks(mock)  # generic routes last: respx matches in registration order
        res = await GleifAdapter().run(ident("organization", "Example Corp"), ctx_factory(kind="organization"))
    rels = [
        (f.attributes.get("relationship"), f.attributes["registry_id"])
        for f in res.findings
        if f.finding_type == "corporate_relationship"
    ]
    assert ("direct_parent", "5493000PARENT0000001") in rels
    assert ("direct_subsidiary", "5493000CHILD00000001") in rels and len(rels) == 3  # ultimate == direct: deduped
    parent = next(f for f in res.findings if f.attributes.get("relationship") == "direct_parent")
    assert parent.linked[0].entity_key == "organization:lei:5493001KJTIIGC8Y1R12"
    child = next(f for f in res.findings if f.attributes.get("relationship") == "direct_subsidiary")
    assert child.attributes["subsidiary_count"] == 2


async def test_opensanctions_requires_key(ctx_factory):
    res = await OpenSanctionsAdapter().run(ident("organization", "Example Corp"), ctx_factory(kind="organization"))
    assert res.status == AdapterStatus.NOT_CONFIGURED


async def test_opensanctions_hits_and_clear(ctx_factory, monkeypatch):
    from pydantic import SecretStr

    from shared.config import get_settings

    monkeypatch.setattr(get_settings(), "opensanctions_api_key", SecretStr("k"))
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(url__regex=r"https://api\.opensanctions\.org/match/default.*").mock(
            return_value=j("opensanctions_hit.json")
        )
        res = await OpenSanctionsAdapter().run(ident("organization", "Example Corp"), ctx_factory(kind="organization"))
        req = route.calls[0].request
    assert req.headers["authorization"] == "ApiKey k"
    body = json.loads(req.content)
    assert body["queries"]["q"]["schema"] == "Company" and body["queries"]["q"]["properties"]["name"] == [
        "Example Corp"
    ]
    assert len(res.findings) == 2  # match=False result excluded
    top = res.findings[0]
    assert top.match_type == MatchType.EXACT and "risk:sanction" in top.flags
    assert "risk:debarment" in res.findings[1].flags and res.findings[1].match_type == MatchType.SIMILAR
    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r"https://api\.opensanctions\.org/.*").mock(return_value=j("opensanctions_clear.json"))
        clear = await OpenSanctionsAdapter().run(
            ident("organization", "Example Corp"), ctx_factory(kind="organization")
        )
    assert clear.findings[0].finding_type == "sanctions_screening_clear"


def test_doh_parsing():
    payload = {
        "Status": 0,
        "Answer": [
            {"type": 5, "data": "alias.example."},
            {"type": 16, "data": '"v=spf1 " "include:x -all"'},
            {"type": 16, "data": "v=DMARC1; p=reject"},
        ],
    }
    assert parse_doh_answer(payload, "example.com", "TXT") == ["v=spf1 include:x -all", "v=DMARC1; p=reject"]
    assert parse_doh_answer({"Status": 3}, "nx.example", "A") == []
    assert _unquote_txt('"a\\"b"') == 'a"b'
    import pytest

    from shared.dns import DnsLookupError

    with pytest.raises(DnsLookupError):
        parse_doh_answer({"Status": 2}, "example.com", "A")
