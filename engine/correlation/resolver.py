"""Entity resolution and correlation.

Design rules (enforced here and covered by tests):

1. Entities are created from *strong keys*: source-persistent identifiers
   (platform account, ORCID iD, LEI, CIK, Wikidata QID), normalised
   identifiers (E.164 phone, email, domain, IP, URL) or document hashes.
2. Two entities are merged **only** when they share a strong key, or when a
   profile URL stated by one source equals another entity's canonical URL.
3. Names never merge entities. Equal names produce *name-collision* records
   and, at most, a ``possible_same_as`` relationship marked as inference.
4. Same handle on different platforms is reported as an inference, not merged.
5. Relationships keep the finding IDs that support them and whether the
   support is direct evidence or inference.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from engine.normalization.identifiers import name_key
from shared.types import (
    Contradiction,
    CorrelationResult,
    Entity,
    EvidenceKind,
    Finding,
    Identifier,
    IdentifierType,
    MatchType,
    NameCollision,
    Relationship,
)

CONTRADICTION_KEYS = {
    "phone_valid": "validity",
    "phone_region": "numbering-plan region",
    "phone_line_type": "line type",
    "registrar": "registrar",
    "created": "creation date",
    "jurisdiction": "jurisdiction",
    "registered_country": "registered country",
    "incorporation_date": "incorporation date",
    "legal_name": "legal name",
}

_SUBJECT_KIND = {
    IdentifierType.PHONE: "phone",
    IdentifierType.EMAIL: "email",
    IdentifierType.DOMAIN: "domain",
    IdentifierType.URL: "url",
    IdentifierType.IP: "ip",
    IdentifierType.USERNAME: "handle",
    IdentifierType.NAME: "name_query",
    IdentifierType.ORGANIZATION: "organization_query",
    IdentifierType.DOCUMENT: "document",
}


def identifier_key(identifier: Identifier) -> str:
    """Strong key for a (normalised) identifier."""
    t, v = identifier.type, identifier.value
    if t == IdentifierType.USERNAME and ":" in v:
        platform, handle = v.split(":", 1)
        return f"account:{platform}:{handle.lower()}"
    if t == IdentifierType.USERNAME:
        return f"handle:{v.lower()}"
    if t == IdentifierType.NAME:
        return f"name_query:{name_key(v)}"
    if t == IdentifierType.ORGANIZATION:
        return f"organization_query:{name_key(v)}"
    if t == IdentifierType.URL:
        orcid = re.match(r"https?://orcid\.org/(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", v)
        if orcid:
            return f"person:orcid:{orcid.group(1)}"
        return f"url:{v.rstrip('/')}"
    return f"{t.value}:{v}"


def _kind_for_key(key: str) -> str:
    return key.split(":", 1)[0]


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # deterministic representative: lexicographically smallest
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def dedupe(findings: list[Finding]) -> tuple[list[Finding], int]:
    seen: dict[tuple[str, str], Finding] = {}
    out: list[Finding] = []
    collapsed = 0
    for f in findings:
        key = (f.source_name, f.claim_key or f.id)
        if key in seen:
            collapsed += 1
            continue
        seen[key] = f
        out.append(f)
    return out, collapsed


def _norm_value(attr: str, value: Any) -> str:
    text = str(value).strip().lower()
    if attr in ("created", "incorporation_date"):
        return text[:10]
    if attr in ("registrar", "legal_name"):
        text = re.sub(r"[.,]|\b(inc|llc|ltd|limited|corp|corporation|gmbh)\b", "", text)
        return re.sub(r"\s+", " ", text).strip()
    return text


def resolve(findings: list[Finding], subject: Identifier) -> CorrelationResult:
    uf = _UnionFind()
    subject_key = identifier_key(subject)
    uf.find(subject_key)
    labels: dict[str, str] = {subject_key: subject.value}
    identifiers: dict[str, list[Identifier]] = defaultdict(list)
    identifiers[subject_key].append(subject)
    finding_keys: dict[str, list[str]] = defaultdict(list)  # key -> finding ids
    attrs_by_key: dict[str, dict[str, Any]] = defaultdict(dict)
    profile_urls: dict[str, str] = {}  # canonical profile url -> key

    # 1) Collect strong keys from findings.
    for f in findings:
        key = f.entity_hint or subject_key
        uf.find(key)
        finding_keys[key].append(f.id)
        a = f.attributes
        label = (
            a.get("candidate_name")
            or a.get("legal_name")
            or a.get("display_name")
            or (f"{a.get('platform')}/{a.get('username')}" if a.get("platform") else None)
        )
        if label and key not in labels:
            labels[key] = str(label)
        if f.entity_kind == "account" and a.get("profile_url"):
            profile_urls[str(a["profile_url"]).rstrip("/").lower()] = key
        if f.entity_kind == "person" and a.get("orcid") and not key.startswith("person:orcid:"):
            uf.union(key, f"person:orcid:{a['orcid']}")
        for k in ("platform", "username", "account_id", "persistent_id", "registry_id", "id_scheme"):
            if k in a:
                attrs_by_key[key].setdefault(k, a[k])
        for li in f.linked:
            lk = identifier_key(li.identifier)
            uf.find(lk)
            identifiers[lk].append(li.identifier)
            labels.setdefault(lk, li.identifier.value)

    # 2) Merge entities that share an explicit identifier: a URL that is another entity's profile URL.
    for key in list(uf.parent):
        if key.startswith("url:"):
            target = profile_urls.get(key[4:].lower())
            if target:
                uf.union(key, target)
    # Subject equivalences (e.g. subject domain == hint domain) are already identical keys.

    # 3) Build entities per union root.
    groups: dict[str, list[str]] = defaultdict(list)
    for key in list(uf.parent):
        groups[uf.find(key)].append(key)
    entities: dict[str, Entity] = {}
    key_to_entity: dict[str, str] = {}
    for _root, keys in sorted(groups.items()):
        primary = sorted(keys, key=lambda k: (k.startswith("url:"), k))[0]
        is_subject = subject_key in keys
        kind = _SUBJECT_KIND[subject.type] if is_subject else _kind_for_key(primary)
        ids = sorted({i.key: i for k in keys for i in identifiers.get(k, [])}.values(), key=lambda i: i.key)
        fids = sorted({fid for k in keys for fid in finding_keys.get(k, [])})
        label = next((labels[k] for k in sorted(keys) if k in labels and not k.startswith("url:")), None) or labels.get(
            primary, primary.split(":", 1)[-1]
        )
        attrs: dict[str, Any] = {}
        for k in keys:
            attrs.update(attrs_by_key.get(k, {}))
        ent = Entity(
            kind=kind,
            label=label,
            identifiers=ids,
            strong_keys=sorted(keys),
            finding_ids=fids,
            attributes=attrs,
            is_subject=is_subject,
        )
        entities[ent.id] = ent
        for k in keys:
            key_to_entity[k] = ent.id

    subject_entity = key_to_entity[subject_key]
    by_id = {f.id: f for f in findings}
    rels: dict[tuple[str, str, str], Relationship] = {}

    def add_rel(src: str, dst: str, rtype: str, kind: EvidenceKind, fid: str, why: str) -> None:
        if src == dst:
            return
        k = (src, dst, rtype)
        if k in rels:
            if fid not in rels[k].finding_ids:
                rels[k].finding_ids.append(fid)
            return
        rels[k] = Relationship(
            source_entity_id=src, target_entity_id=dst, type=rtype, evidence_kind=kind, finding_ids=[fid], rationale=why
        )

    # 4) Relationships: subject -> entity, entity -> linked identifiers.
    for f in findings:
        eid = key_to_entity[f.entity_hint or subject_key]
        if eid != subject_entity:
            rtype, kind, why = _subject_relation(f, subject)
            add_rel(subject_entity, eid, rtype, kind, f.id, why)
        for li in f.linked:
            target = key_to_entity[identifier_key(li.identifier)]
            add_rel(
                eid,
                target,
                li.relation,
                li.evidence_kind,
                f.id,
                f"{f.source_display_name} states relation '{li.relation}'",
            )

    # 5) Mutual cross-platform links (A links to B and B links to A) are strong direct evidence.
    for (src, dst, _rtype), rel in list(rels.items()):
        if entities[src].kind == "account" and entities[dst].kind == "account":
            back = [r for (s, d, _), r in rels.items() if s == dst and d == src]
            if back:
                lo, hi = sorted((src, dst))
                add_rel(
                    lo,
                    hi,
                    "mutual_link",
                    EvidenceKind.DIRECT,
                    rel.finding_ids[0],
                    "Both accounts publicly reference each other",
                )
                for b in back:
                    for fid in b.finding_ids:
                        add_rel(
                            lo,
                            hi,
                            "mutual_link",
                            EvidenceKind.DIRECT,
                            fid,
                            "Both accounts publicly reference each other",
                        )

    # 6) Shared website between two accounts -> inference only.
    site_owners: dict[str, set[str]] = defaultdict(set)
    for src, dst, rtype in list(rels):
        if rtype in ("lists_website_domain",) and entities[src].kind == "account":
            site_owners[dst].add(src)
    for site, owners in site_owners.items():
        owners_sorted = sorted(owners)
        for i, owner_a in enumerate(owners_sorted):
            for owner_b in owners_sorted[i + 1 :]:
                fid = next(iter(rels[(owner_a, site, "lists_website_domain")].finding_ids))
                add_rel(
                    owner_a,
                    owner_b,
                    "shares_website_with",
                    EvidenceKind.INFERENCE,
                    fid,
                    f"Both accounts list the website {entities[site].label}; this suggests but does not "
                    "prove common control",
                )

    # 7) Name collisions among person / organisation candidates.
    collisions: list[NameCollision] = []
    by_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    for e in entities.values():
        if e.kind in ("person", "organization") and not e.is_subject:
            by_name[(e.kind, name_key(e.label))].append(e.id)
    for (kind, nk), member_ids in by_name.items():
        ids_sorted = sorted(member_ids)
        if len(ids_sorted) > 1 and nk:
            collisions.append(
                NameCollision(
                    name=entities[ids_sorted[0]].label,
                    entity_ids=ids_sorted,
                    explanation=f"{len(ids_sorted)} distinct {kind} records share the name "
                    f"'{entities[ids_sorted[0]].label}'. "
                    "They are kept separate because no shared persistent identifier links them.",
                )
            )
            for i, ent_a in enumerate(ids_sorted):
                for ent_b in ids_sorted[i + 1 :]:
                    fid = entities[ent_a].finding_ids[0] if entities[ent_a].finding_ids else ""
                    add_rel(
                        ent_a,
                        ent_b,
                        "possible_same_as",
                        EvidenceKind.INFERENCE,
                        fid,
                        "Same name only – insufficient evidence of identity; not merged",
                    )

    # 8) Contradictions per entity.
    contradictions: list[Contradiction] = []
    for e in entities.values():
        per_attr: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        sources: dict[str, set[str]] = defaultdict(set)
        for fid in e.finding_ids:
            f = by_id[fid]
            for attr in CONTRADICTION_KEYS:
                if attr in f.attributes and f.attributes[attr] not in (None, ""):
                    per_attr[attr][_norm_value(attr, f.attributes[attr])].add(fid)
                    sources[attr].add(f.source_name)
        for attr, values in per_attr.items():
            if len(values) > 1 and len(sources[attr]) > 1:
                contradictions.append(
                    Contradiction(
                        entity_id=e.id,
                        attribute=attr,
                        values={v: sorted(ids) for v, ids in values.items()},
                        explanation=f"Sources disagree on the {CONTRADICTION_KEYS[attr]} of '{e.label}': "
                        + "; ".join(f"'{v}'" for v in sorted(values))
                        + ".",
                    )
                )

    return CorrelationResult(
        entities=sorted(entities.values(), key=lambda e: (not e.is_subject, e.kind, e.label)),
        relationships=sorted(rels.values(), key=lambda r: (r.type, r.source_entity_id, r.target_entity_id)),
        contradictions=contradictions,
        name_collisions=collisions,
    )


def _subject_relation(f: Finding, subject: Identifier) -> tuple[str, EvidenceKind, str]:
    if f.entity_kind == "account":
        if f.match_type == MatchType.EXACT:
            return (
                "handle_exact_match",
                EvidenceKind.DIRECT,
                f"{f.source_display_name} has an account with exactly this handle; same handle does not "
                "prove the same owner",
            )
        return ("handle_similar", EvidenceKind.INFERENCE, "Account handle is similar, not identical")
    if f.entity_kind in ("person", "organization"):
        if f.match_type == MatchType.EXACT:
            return (
                "name_match",
                EvidenceKind.INFERENCE,
                "Record name matches the searched name; a name match is not an identity match",
            )
        return ("similar_name", EvidenceKind.INFERENCE, "Record name is similar to the searched name")
    if f.entity_kind == "publication":
        return ("mentioned_in", EvidenceKind.INFERENCE, "Exact phrase appears in the publication")
    if "pivot:email_domain" in f.flags:
        return ("email_domain", EvidenceKind.DIRECT, "Domain part of the email address")
    return (
        "related_to",
        EvidenceKind.DIRECT if f.match_type != MatchType.INFERRED else EvidenceKind.INFERENCE,
        f"Reported by {f.source_display_name}",
    )


def _score(f: Finding) -> float:
    return f.confidence.score if f.confidence else 0.0


def finalize_entity_confidence(result: CorrelationResult, findings: list[Finding]) -> None:
    by_id = {f.id: f for f in findings}
    for e in result.entities:
        scores = [_score(by_id[i]) for i in e.finding_ids if i in by_id and by_id[i].confidence]
        e.confidence = max(scores) if scores else (1.0 if e.is_subject else 0.0)
    for r in result.relationships:
        scores = [_score(by_id[i]) for i in r.finding_ids if i in by_id and by_id[i].confidence]
        base = max(scores) if scores else 0.0
        if r.evidence_kind == EvidenceKind.INFERENCE:
            base = min(base, 0.5)
        if r.type == "mutual_link":
            base = min(1.0, base + 0.1)
        r.confidence = round(base, 4)
