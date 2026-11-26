"""Source adapter tests (HTTP mocked with respx, DNS with a fake resolver)."""

import httpx
import pytest
import respx

from integrations.sources.domain import (
    CrtShAdapter,
    DnsRecordsAdapter,
    HttpSecurityAdapter,
    RdapDomainAdapter,
    TeamCymruAsnAdapter,
    WaybackAdapter,
)
from integrations.sources.email import EmailDomainDnsAdapter, EmailSyntaxAdapter, HibpAdapter
from integrations.sources.name import OpenAlexAuthorsAdapter, OrcidAdapter, WikidataAdapter
from integrations.sources.phone import LibPhoneNumberAdapter, NumverifyAdapter
from integrations.sources.public_records import CompaniesHouseAdapter, GleifAdapter, PublicDocumentAdapter
from integrations.sources.username import (
    DevToAdapter,
    GitHubAdapter,
    HackerNewsAdapter,
    KeybaseAdapter,
    WikimediaAdapter,
)
from shared.types import AdapterStatus, Identifier, IdentifierType, MatchType
from tests.conftest import install_source_mocks, load_fixture


def ident(t, v, raw=None):
    return Identifier(type=IdentifierType(t), value=v, raw=raw or v)


async def test_libphonenumber_valid_number(ctx_factory):
    res = await LibPhoneNumberAdapter().run(ident("phone", "+442079460958"), ctx_factory())
    assert res.status == AdapterStatus.OK
    plan = res.findings[0]
    assert plan.attributes["phone_region"] == "GB"
    assert plan.attributes["phone_valid"] is True
    assert "does not identify the subscriber" in plan.description
    assert not any("subscriber" in k for k in plan.attributes)


async def test_libphonenumber_invalid_number_is_reported(ctx_factory):
    res = await LibPhoneNumberAdapter().run(ident("phone", "+15555550100"), ctx_factory())
    assert res.findings[0].attributes["phone_valid"] is False


async def test_numverify_not_configured(ctx_factory):
    res = await NumverifyAdapter().run(ident("phone", "+442079460958"), ctx_factory())
    assert res.status == AdapterStatus.NOT_CONFIGURED
    assert "ATLAS_NUMVERIFY_API_KEY" in res.message


async def test_github_exact_match_and_minimisation(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        install_source_mocks(mock)
        res = await GitHubAdapter().run(ident("username", "octo-sample"), ctx_factory())
    assert res.status == AdapterStatus.OK
    f = res.findings[0]
    assert f.match_type == MatchType.EXACT
    assert f.entity_hint == "account:github:octo-sample"
    # data minimisation: undeclared fields (email, location) are never collected
    assert "email" not in f.attributes and "location" not in f.attributes
    rels = {li.relation for li in f.linked}
    assert {"lists_website", "lists_website_domain", "claims_account"} <= rels
    assert f.evidence.content_hash and len(f.evidence.content_hash) == 64


async def test_github_not_found(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.github.com/users/nobody").mock(return_value=httpx.Response(404, json={}))
        res = await GitHubAdapter().run(ident("username", "nobody"), ctx_factory())
    assert res.status == AdapterStatus.NO_RESULTS


async def test_github_rate_limited(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.github.com/users/x").mock(return_value=httpx.Response(429))
        res = await GitHubAdapter().run(ident("username", "x"), ctx_factory())
    assert res.status == AdapterStatus.RATE_LIMITED


async def test_network_error_is_unavailable_not_crash(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.github.com/users/x").mock(side_effect=httpx.ConnectError("boom"))
        res = await GitHubAdapter().run(ident("username", "x"), ctx_factory())
    assert res.status == AdapterStatus.UNAVAILABLE


async def test_malformed_response_is_error(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.github.com/users/x").mock(return_value=httpx.Response(200, text="<html>"))
        res = await GitHubAdapter().run(ident("username", "x"), ctx_factory())
    assert res.status == AdapterStatus.ERROR


async def test_hackernews_is_case_sensitive(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://hacker-news.firebaseio.com/v0/user/PG.json").mock(
            return_value=httpx.Response(200, json={"id": "PG", "created": 1160418092, "karma": 5})
        )
        res = await HackerNewsAdapter().run(ident("username", "pg", raw="PG"), ctx_factory())
    assert route.called
    assert res.findings[0].match_type == MatchType.EXACT


async def test_devto_links_github(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        install_source_mocks(mock)
        res = await DevToAdapter().run(ident("username", "octo-sample"), ctx_factory())
    keys = {li.identifier.value for li in res.findings[0].linked}
    assert "github:octo-sample" in keys


async def test_keybase_proofs_are_cryptographic_links(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        install_source_mocks(mock)
        res = await KeybaseAdapter().run(ident("username", "octo-sample"), ctx_factory())
    f = res.findings[0]
    assert {li.relation for li in f.linked} == {"cryptographic_proof"}
    assert any(li.identifier.type == IdentifierType.DOMAIN for li in f.linked)


async def test_wikimedia_missing_user(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        install_source_mocks(mock)
        res = await WikimediaAdapter().run(ident("username", "nobody"), ctx_factory())
    assert res.status == AdapterStatus.NO_RESULTS


async def test_openalex_candidates_keyed_by_persistent_ids(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        install_source_mocks(mock)
        res = await OpenAlexAuthorsAdapter().run(ident("name", "Maria Example"), ctx_factory(kind="individual"))
    hints = [f.entity_hint for f in res.findings]
    assert hints == ["person:orcid:0000-0002-1825-0097", "person:openalex:A0000000002", "person:openalex:A0000000003"]
    assert res.findings[2].match_type == MatchType.SIMILAR


async def test_orcid_and_wikidata(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        install_source_mocks(mock)
        orcid = await OrcidAdapter().run(ident("name", "Maria Example"), ctx_factory(kind="individual"))
        wd = await WikidataAdapter().run(ident("name", "Maria Example"), ctx_factory(kind="individual"))
        wd_org = await WikidataAdapter().run(ident("organization", "Example Corp"), ctx_factory(kind="organization"))
    assert orcid.findings[0].entity_hint == "person:orcid:0000-0002-1825-0097"
    assert [f.entity_hint for f in wd.findings] == ["person:orcid:0000-0002-1825-0097", "person:wikidata:Q900002"]
    assert [f.entity_hint for f in wd_org.findings] == ["organization:lei:5493001KJTIIGC8Y1R12"]


async def test_email_syntax_classification(ctx_factory):
    res = await EmailSyntaxAdapter().run(ident("email", "info@acme-research.org"), ctx_factory(kind="individual"))
    a = res.findings[0].attributes
    assert a["provider_type"] == "organizational_or_custom" and a["role_account"] is True
    res = await EmailSyntaxAdapter().run(ident("email", "someone@gmail.com"), ctx_factory(kind="individual"))
    assert res.findings[0].attributes["provider_type"] == "free_mail"
    assert res.findings[0].linked == []


async def test_email_domain_dns(ctx_factory):
    res = await EmailDomainDnsAdapter().run(ident("email", "a@example.com"), ctx_factory(kind="individual"))
    a = res.findings[0].attributes
    assert a["mx_records"] == ["mx1.example-mail.test", "mx2.example-mail.test"]
    assert a["dmarc_policy"] == "reject"
    assert "do not prove that this specific mailbox exists" in res.findings[0].description


async def test_hibp_requires_consent_for_individuals(ctx_factory, monkeypatch):
    from pydantic import SecretStr

    from shared.config import get_settings

    monkeypatch.setattr(get_settings(), "hibp_api_key", SecretStr("k"))
    res = await HibpAdapter().run(
        ident("email", "a@example.com"), ctx_factory(kind="individual", consent=False, basis="research")
    )
    assert res.status == AdapterStatus.SKIPPED and "consent" in res.message
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://haveibeenpwned\.com/.*").mock(
            return_value=httpx.Response(200, json=load_fixture("hibp.json"))
        )
        res = await HibpAdapter().run(
            ident("email", "a@example.com"), ctx_factory(kind="individual", consent=True, basis="consent")
        )
    assert res.status == AdapterStatus.OK
    assert res.findings[0].attributes["breach_name"] == "SyntheticBreach"


async def test_dns_records(ctx_factory):
    res = await DnsRecordsAdapter().run(ident("domain", "example.com"), ctx_factory())
    by_type = {f.attributes["record_type"]: f for f in res.findings}
    assert set(by_type) == {"A", "AAAA", "MX", "NS", "TXT"}
    txt = by_type["TXT"].attributes
    assert txt["verification_tokens_count"] == 1
    assert all("verification" not in v for v in txt["values"])  # tokens are counted, not stored


async def test_rdap_redacts_individual_registrant(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        install_source_mocks(mock)
        res = await RdapDomainAdapter().run(ident("domain", "example.com"), ctx_factory())
    reg = res.findings[0]
    assert reg.attributes["registrar"].startswith("RESERVED-Internet")
    assert "registrant_org" not in reg.attributes  # individual registrant never recorded
    assert "Jane Private Person" not in reg.model_dump_json()


async def test_crtsh_subdomains_only_in_scope(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        install_source_mocks(mock)
        out_scope = await CrtShAdapter().run(ident("domain", "example.com"), ctx_factory())
        in_scope = await CrtShAdapter().run(ident("domain", "example.com"), ctx_factory(domains=["example.com"]))
    assert [f.finding_type for f in out_scope.findings] == ["certificate_transparency_summary"]
    assert out_scope.findings[0].attributes["listing_withheld"] is True
    subs = sorted(f.attributes["subdomain"] for f in in_scope.findings if f.finding_type == "subdomain")
    assert subs == ["api.example.com", "dev.example.com", "www.example.com"]


async def test_http_security_requires_scope(ctx_factory):
    res = await HttpSecurityAdapter().run(ident("domain", "example.com"), ctx_factory())
    assert res.status == AdapterStatus.SKIPPED and "authorised scope" in res.message
    with respx.mock(assert_all_called=False) as mock:
        install_source_mocks(mock)
        res = await HttpSecurityAdapter().run(ident("domain", "example.com"), ctx_factory(domains=["example.com"]))
    a = res.findings[0].attributes
    assert "HSTS" in a["security_headers_present"] and "CSP" in a["security_headers_missing"]
    assert {"Next.js", "jQuery"} <= set(a["technologies"])
    assert a["generator"] == "SyntheticCMS 1.0"


async def test_team_cymru(ctx_factory):
    res = await TeamCymruAsnAdapter().run(ident("ip", "93.184.216.34"), ctx_factory())
    a = res.findings[0].attributes
    assert a["asn"] == "AS15133" and a["prefix"] == "93.184.216.0/24"


async def test_wayback(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        install_source_mocks(mock)
        res = await WaybackAdapter().run(ident("domain", "example.com"), ctx_factory())
    assert res.findings[0].attributes["first_capture"].startswith("2002-01-20")


async def test_gleif_and_companies_house(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        install_source_mocks(mock)
        res = await GleifAdapter().run(ident("organization", "Example Corp"), ctx_factory(kind="organization"))
    assert res.findings[0].match_type == MatchType.EXACT
    assert res.findings[1].match_type == MatchType.SIMILAR
    ch = await CompaniesHouseAdapter().run(ident("organization", "Example Corp"), ctx_factory(kind="organization"))
    assert ch.status == AdapterStatus.NOT_CONFIGURED


async def test_public_document_respects_robots(ctx_factory):
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://docs.example/robots.txt").mock(
            return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        )
        mock.get("https://docs.example/private/a.pdf").mock(return_value=httpx.Response(200, content=b"%PDF-1.4"))
        pdf = b"%PDF-1.4\n1 0 obj << /Title (Annual Report) /Author (Example Corp) /CreationDate (D:20240102) >>"
        mock.get("https://docs.example/public/r.pdf").mock(
            return_value=httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"})
        )
        blocked = await PublicDocumentAdapter().run(
            ident("document", "https://docs.example/private/a.pdf"), ctx_factory(kind="organization")
        )
        ok = await PublicDocumentAdapter().run(
            ident("document", "https://docs.example/public/r.pdf"), ctx_factory(kind="organization")
        )
    assert blocked.status == AdapterStatus.SKIPPED and "robots.txt" in blocked.message
    a = ok.findings[0].attributes
    assert a["doc_title"] == "Annual Report" and a["doc_created"] == "2024-01-02" and len(a["sha256"]) == 64


async def test_adapter_blocked_by_ssrf_reports_skipped(ctx_factory, http_client):
    http_client.resolver = lambda h: ["10.0.0.1"]
    res = await GitHubAdapter().run(ident("username", "x"), ctx_factory())
    assert res.status == AdapterStatus.SKIPPED and "SSRF" in res.message


@pytest.mark.live
async def test_live_libphonenumber_and_dns():  # pragma: no cover - network
    from integrations.sources.base import AuthorizationScope, CollectionContext
    from shared.config import get_settings
    from shared.http import SafeHttpClient
    from shared.types import SubjectKind

    async with SafeHttpClient(user_agent=get_settings().user_agent) as http:
        ctx = CollectionContext(
            http=http,
            settings=get_settings(),
            scope=AuthorizationScope(subject_kind=SubjectKind.INFRASTRUCTURE, legal_basis="research"),
        )
        res = await DnsRecordsAdapter().run(ident("domain", "example.com"), ctx)
        assert res.status == AdapterStatus.OK
