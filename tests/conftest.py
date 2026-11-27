"""Shared pytest fixtures.

All tests run offline: HTTP is mocked with ``respx`` and DNS with a fake
resolver. Live tests against real sources are marked ``@pytest.mark.live`` and
deselected by default (run with ``pytest -m live``).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
PUBLIC_IP = "93.184.216.34"


def load_fixture(name: str):  # type: ignore[no-untyped-def]
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True, scope="session")
def _test_env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    db = tmp_path_factory.mktemp("db") / "atlas-test.db"
    os.environ.update(
        {
            "ATLAS_ENV": "test",
            "ATLAS_DATABASE_URL": f"sqlite:///{db}",
            "ATLAS_SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",
            "ATLAS_ENCRYPTION_KEY": "x5Hk3ZbUq0Gv1H1Qd8qUe1c2bH9H8mJm3oT3n0W7k2Q=",
            "ATLAS_HASH_KEY": "test-hash-key",
            "ATLAS_TASK_BACKEND": "inline",
            "ATLAS_LOG_JSON": "false",
            "ATLAS_LOG_LEVEL": "WARNING",
            "ATLAS_HTTP_PIN_DNS": "false",
            "ATLAS_API_RATE_LIMIT_PER_MINUTE": "10000",
            "ATLAS_PUBLIC_RATE_LIMIT_PER_MINUTE": "1000",
            "ATLAS_BOOTSTRAP_ADMIN_EMAIL": "admin@atlas-osint-test.com",
            "ATLAS_BOOTSTRAP_ADMIN_PASSWORD": "Admin-Password-123",
            "ATLAS_AI_PROVIDER": "none",
            "ATLAS_INLINE_SCHEDULER": "false",
        }
    )
    from shared.config import reset_settings_cache
    from shared.crypto import reset_crypto_cache

    reset_settings_cache()
    reset_crypto_cache()
    yield


def fake_resolver(host: str) -> list[str]:
    return [PUBLIC_IP]


@pytest.fixture
def http_client():  # type: ignore[no-untyped-def]
    from shared.http import SafeHttpClient

    return SafeHttpClient(user_agent="atlas-test", resolver=fake_resolver, pin_dns=False)


class FakeDNS:
    """Async fake DNS: records[(name, type)] -> list of values."""

    def __init__(self, records: dict[tuple[str, str], list[str]] | None = None) -> None:
        self.records = records or {}
        self.queries: list[tuple[str, str]] = []

    async def __call__(self, name: str, rdtype: str) -> list[str]:
        self.queries.append((name, rdtype))
        return list(self.records.get((name, rdtype), []))


@pytest.fixture
def fake_dns() -> FakeDNS:
    return FakeDNS(load_dns_fixture())


def load_dns_fixture() -> dict[tuple[str, str], list[str]]:
    raw = load_fixture("dns_records.json")
    return {(k.split("|")[0], k.split("|")[1]): v for k, v in raw.items()}


@pytest.fixture
def scope_factory():  # type: ignore[no-untyped-def]
    from integrations.sources.base import AuthorizationScope
    from shared.types import SubjectKind

    def make(
        kind: str = "infrastructure",
        consent: bool = False,
        basis: str = "legitimate_interest",
        domains: list[str] | None = None,
    ) -> AuthorizationScope:
        return AuthorizationScope(
            subject_kind=SubjectKind(kind),
            consent_obtained=consent,
            legal_basis=basis,
            authorized_domains=domains or [],
        )

    return make


@pytest.fixture
def ctx_factory(http_client, fake_dns, scope_factory):  # type: ignore[no-untyped-def]
    from integrations.sources.base import CollectionContext
    from shared.config import get_settings

    def make(**scope_kwargs):  # type: ignore[no-untyped-def]
        return CollectionContext(
            http=http_client,
            settings=get_settings(),
            scope=scope_factory(**scope_kwargs),
            extra={"dns_resolver": fake_dns},
        )

    return make


# ---------------------------------------------------------------- API fixtures
@pytest.fixture(scope="session")
def app():  # type: ignore[no-untyped-def]
    from atlas_api.main import create_app

    return create_app()


@pytest.fixture(scope="session")
def client(app):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def _login(client, email: str, password: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_headers(client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return _login(client, "admin@atlas-osint-test.com", "Admin-Password-123")


@pytest.fixture(scope="session")
def make_user(client, admin_headers):  # type: ignore[no-untyped-def]
    created: dict[str, dict[str, str]] = {}

    def make(email: str, role: str) -> dict[str, str]:
        if email not in created:
            r = client.post(
                "/api/v1/admin/users",
                headers=admin_headers,
                json={"email": email, "password": "User-Password-123", "role": role},
            )
            assert r.status_code in (201, 409), r.text
            created[email] = _login(client, email, "User-Password-123")
        return created[email]

    return make


@pytest.fixture(scope="session")
def analyst_headers(make_user) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return make_user("analyst@atlas-osint-test.com", "analyst")


@pytest.fixture(scope="session")
def analyst2_headers(make_user) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return make_user("analyst2@atlas-osint-test.com", "analyst")


@pytest.fixture(scope="session")
def viewer_headers(make_user) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return make_user("viewer@atlas-osint-test.com", "viewer")


@pytest.fixture(scope="session")
def auditor_headers(make_user) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return make_user("auditor@atlas-osint-test.com", "auditor")


@pytest.fixture
def mocked_collection(fake_dns):  # type: ignore[no-untyped-def]
    """Route investigation collection through respx mocks and the fake DNS resolver."""
    import respx
    from atlas_api.services import investigations as svc

    from shared.http import SafeHttpClient

    svc.collection_hooks["http_factory"] = lambda: SafeHttpClient(
        user_agent="atlas-test", resolver=fake_resolver, pin_dns=False
    )
    svc.collection_hooks["extra"] = {"dns_resolver": fake_dns}
    with respx.mock(assert_all_called=False) as mock:
        install_source_mocks(mock)
        yield mock
    svc.collection_hooks["http_factory"] = None
    svc.collection_hooks["extra"] = {}


def install_source_mocks(mock) -> None:  # type: ignore[no-untyped-def]
    import httpx

    j = lambda name, status=200: httpx.Response(status, json=load_fixture(name))  # noqa: E731
    mock.get("https://data.iana.org/rdap/dns.json").mock(return_value=j("iana_rdap_bootstrap.json"))
    mock.get(url__regex=r"https://internetdb\.shodan\.io/93\.184\.216\.34").mock(return_value=j("internetdb.json"))
    mock.get(url__regex=r"https://internetdb\.shodan\.io/.*").mock(return_value=httpx.Response(404, json={}))
    mock.get(url__regex=r"https://api\.certspotter\.com/.*").mock(return_value=j("certspotter.json"))
    mock.get("https://example.com/.well-known/security.txt").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "security.txt").read_text(), headers={"content-type": "text/plain"}
        )
    )
    mock.get("https://mta-sts.example.com/.well-known/mta-sts.txt").mock(
        return_value=httpx.Response(200, text="version: STSv1\nmode: testing\nmx: *.example-mail.test\n")
    )
    mock.get(url__regex=r"https://rdap\.org/ip/.*").mock(return_value=httpx.Response(404, json={}))
    mock.get(url__regex=r"https://mastodon\.social/.*").mock(return_value=httpx.Response(404, json={}))
    mock.get(url__regex=r"https://public\.api\.bsky\.app/.*").mock(return_value=httpx.Response(400, json={}))
    mock.get(url__regex=r"https://api\.crossref\.org/.*").mock(return_value=j("crossref_works.json"))
    mock.get(url__regex=r"https://rdap\.example-registry\.test/domain/.*").mock(return_value=j("rdap_domain.json"))
    mock.get(url__regex=r"https://crt\.sh/.*").mock(return_value=j("crtsh.json"))
    mock.get(url__regex=r"https://web\.archive\.org/cdx/.*").mock(return_value=j("wayback_cdx.json"))
    mock.get(url__regex=r"http://example\.com/.*").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html", "strict-transport-security": "max-age=1", "server": "nginx"},
            text=(FIXTURES / "homepage.html").read_text(),
        )
    )
    mock.get(url__regex=r"https://api\.github\.com/users/octo-sample").mock(return_value=j("github_user.json"))
    mock.get(url__regex=r"https://api\.github\.com/users/.*").mock(return_value=httpx.Response(404, json={}))
    mock.get(url__regex=r"https://gitlab\.com/api/v4/users\?.*").mock(return_value=httpx.Response(200, json=[]))
    mock.get(url__regex=r"https://hacker-news\.firebaseio\.com/.*").mock(
        return_value=httpx.Response(200, content=b"null")
    )
    mock.get(url__regex=r"https://www\.reddit\.com/.*").mock(return_value=httpx.Response(403, json={}))
    mock.get(url__regex=r"https://dev\.to/api/users/by_username.*").mock(return_value=j("devto_user.json"))
    mock.get(url__regex=r"https://codeberg\.org/.*").mock(return_value=httpx.Response(404, json={}))
    mock.get(url__regex=r"https://hub\.docker\.com/.*").mock(return_value=httpx.Response(404, json={}))
    mock.get(url__regex=r"https://registry\.npmjs\.org/.*").mock(return_value=httpx.Response(200, json={"objects": []}))
    mock.get(url__regex=r"https://meta\.wikimedia\.org/.*").mock(
        return_value=httpx.Response(200, json={"query": {"globaluserinfo": {"missing": ""}}})
    )
    mock.get(url__regex=r"https://keybase\.io/.*").mock(return_value=j("keybase_user.json"))
    mock.get(url__regex=r"https://api\.openalex\.org/authors.*").mock(return_value=j("openalex_authors.json"))
    mock.get(url__regex=r"https://pub\.orcid\.org/.*").mock(return_value=j("orcid_search.json"))
    mock.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?.*action=wbsearchentities.*").mock(
        return_value=j("wikidata_search.json")
    )
    mock.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?.*action=wbgetentities.*").mock(
        return_value=j("wikidata_entities.json")
    )
    mock.get(url__regex=r"https://api\.gdeltproject\.org/.*").mock(return_value=j("gdelt.json"))
    mock.get(url__regex=r"https://api\.gleif\.org/.*").mock(return_value=j("gleif.json"))
