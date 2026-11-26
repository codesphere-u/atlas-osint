from engine.correlation.resolver import dedupe, identifier_key, resolve
from shared.types import EvidenceKind, Identifier, IdentifierType, MatchType
from tests.unit.helpers import finding


def ent_by_key(corr, key):
    return next(e for e in corr.entities if key in e.strong_keys)


def test_names_never_merge_people():
    subj = ("name", "Maria Example")
    fs = [
        finding(
            "openalex",
            subject=subj,
            hint="person:openalex:A1",
            kind="person",
            attrs={"candidate_name": "Maria Example"},
        ),
        finding(
            "wikidata",
            subject=subj,
            hint="person:wikidata:Q2",
            kind="person",
            attrs={"candidate_name": "Maria Example"},
        ),
    ]
    corr = resolve(fs, fs[0].subject)
    people = [e for e in corr.entities if e.kind == "person"]
    assert len(people) == 2
    assert len(corr.name_collisions) == 1
    same = [r for r in corr.relationships if r.type == "possible_same_as"]
    assert same and all(r.evidence_kind == EvidenceKind.INFERENCE for r in same)


def test_shared_orcid_merges_records():
    subj = ("name", "Maria Example")
    fs = [
        finding(
            "openalex",
            subject=subj,
            hint="person:orcid:0000-0002-1825-0097",
            kind="person",
            attrs={"candidate_name": "Maria Example", "orcid": "0000-0002-1825-0097"},
        ),
        finding(
            "orcid",
            subject=subj,
            hint="person:orcid:0000-0002-1825-0097",
            kind="person",
            attrs={"candidate_name": "Maria Example"},
        ),
        finding(
            "wikidata",
            subject=subj,
            hint="person:wikidata:Q1",
            kind="person",
            attrs={"candidate_name": "Maria Example", "orcid": "0000-0002-1825-0097"},
        ),
    ]
    corr = resolve(fs, fs[0].subject)
    people = [e for e in corr.entities if e.kind == "person"]
    assert len(people) == 1 and len(people[0].finding_ids) == 3
    assert corr.name_collisions == []


def test_same_handle_on_two_platforms_is_not_merged():
    fs = [
        finding("github", hint="account:github:octo", kind="account"),
        finding("gitlab", hint="account:gitlab:octo", kind="account"),
    ]
    corr = resolve(fs, fs[0].subject)
    accounts = [e for e in corr.entities if e.kind == "account"]
    assert len(accounts) == 2
    assert {r.type for r in corr.relationships} == {"handle_exact_match"}


def test_profile_url_link_merges_with_account_and_mutual_links_detected():
    gh = finding(
        "github",
        hint="account:github:octo",
        kind="account",
        attrs={"profile_url": "https://github.com/octo"},
        linked=[("username", "devto:octo", "claims_account")],
    )
    dv = finding(
        "devto",
        hint="account:devto:octo",
        kind="account",
        attrs={"profile_url": "https://dev.to/octo"},
        linked=[("url", "https://github.com/octo", "lists_website")],
    )
    corr = resolve([gh, dv], gh.subject)
    assert len([e for e in corr.entities if e.kind == "account"]) == 2  # URL merged into github account entity
    types = {r.type for r in corr.relationships}
    assert "mutual_link" in types


def test_shared_website_is_inference_only():
    a = finding(
        "github", hint="account:github:a", kind="account", linked=[("domain", "site.example", "lists_website_domain")]
    )
    b = finding(
        "devto", hint="account:devto:b", kind="account", linked=[("domain", "site.example", "lists_website_domain")]
    )
    corr = resolve([a, b], a.subject)
    rel = next(r for r in corr.relationships if r.type == "shares_website_with")
    assert rel.evidence_kind == EvidenceKind.INFERENCE


def test_subject_merges_with_equal_identifier_hint():
    subj = ("domain", "example.com")
    fs = [
        finding("dns", subject=subj, hint="domain:example.com", kind="domain"),
        finding("rdap", subject=subj, hint="domain:example.com", kind="domain"),
    ]
    corr = resolve(fs, fs[0].subject)
    subject = next(e for e in corr.entities if e.is_subject)
    assert len(subject.finding_ids) == 2


def test_dedupe_same_source_same_claim():
    fs, n = dedupe([finding("a", claim="x"), finding("a", claim="x"), finding("b", claim="x")])
    assert n == 1 and len(fs) == 2


def test_identifier_keys():
    assert (
        identifier_key(Identifier(type=IdentifierType.URL, value="https://orcid.org/0000-0002-1825-0097"))
        == "person:orcid:0000-0002-1825-0097"
    )
    assert identifier_key(Identifier(type=IdentifierType.USERNAME, value="github:Octo")) == "account:github:octo"


def test_similar_handles_produce_inference_relationship():
    f = finding("github", hint="account:github:octo1", kind="account", match=MatchType.SIMILAR)
    corr = resolve([f], f.subject)
    assert corr.relationships[0].type == "handle_similar"
    assert corr.relationships[0].evidence_kind == EvidenceKind.INFERENCE
