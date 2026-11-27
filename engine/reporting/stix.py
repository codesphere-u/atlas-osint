"""STIX 2.1 export for interoperability with OpenCTI, MISP and other CTI platforms.

* Observables (domain-name, ipv4/ipv6-addr, email-addr, url, user-account) use the deterministic UUIDv5
  identifiers defined by the STIX 2.1 specification, so the same observable deduplicates across exports.
* People and organisations become ``identity`` objects; every ATLAS finding becomes a ``note`` with its source
  as an external reference and its confidence (0–100); relationships become ``relationship`` objects.
* The investigation's TLP 2.0 marking is applied to every object using the official OASIS marking-definition
  objects (extension-definition--60a3c5c5-0d10-413e-aab3-9e08dde9e88d).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from engine.verification.scoring import classify
from shared.types import CorrelationResult, Entity, Finding

STIX_SCO_NAMESPACE = uuid.UUID("00abedb4-aa42-466c-9c01-fed23315a9b7")  # STIX 2.1 §2.9
ATLAS_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/codesphere-u/atlas-osint")
TLP_EXTENSION = "extension-definition--60a3c5c5-0d10-413e-aab3-9e08dde9e88d"

# Official TLP 2.0 marking definitions (OASIS cti-stix-common-objects, extension-definition-specifications/tlp-2.0)
TLP_MARKINGS: dict[str, dict[str, Any]] = {
    level: {
        "type": "marking-definition",
        "spec_version": "2.1",
        "id": mid,
        "created": "2022-10-01T00:00:00.000Z",
        "name": f"TLP:{level.upper()}",
        "extensions": {TLP_EXTENSION: {"extension_type": "property-extension", "tlp_2_0": level}},
    }
    for level, mid in {
        "clear": "marking-definition--94868c89-83c2-464b-929b-a1a8aa3c8487",
        "green": "marking-definition--bab4a63c-aed9-4cf5-a766-dfca5abac2bb",
        "amber": "marking-definition--55d920b0-5e8b-4f79-9ee9-91f868d9b421",
        "amber+strict": "marking-definition--939a9414-2ddd-4d32-a0cd-375ea402b003",
        "red": "marking-definition--e828b379-4e03-4974-9ac4-e53a884c97c1",
    }.items()
}


def _ts(dt: datetime | None = None) -> str:
    dt = (dt or datetime.now(UTC)).astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def sco_id(obj_type: str, contributing: dict[str, Any]) -> str:
    """Deterministic SCO id: UUIDv5(STIX namespace, JCS-canonical JSON of the ID-contributing properties)."""
    canonical = json.dumps(contributing, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{obj_type}--{uuid.uuid5(STIX_SCO_NAMESPACE, canonical)}"


def _sdo_id(obj_type: str, key: str) -> str:
    return f"{obj_type}--{uuid.uuid5(ATLAS_NAMESPACE, key)}"


def _entity_object(e: Entity, created: str, common: dict[str, Any]) -> dict[str, Any] | None:
    key = e.strong_keys[0] if e.strong_keys else e.id
    kind = e.kind
    if kind == "domain":
        value = next((k.split(":", 1)[1] for k in e.strong_keys if k.startswith("domain:")), e.label)
        return {
            "type": "domain-name",
            "spec_version": "2.1",
            "id": sco_id("domain-name", {"value": value}),
            "value": value,
            "object_marking_refs": common["object_marking_refs"],
        }
    if kind == "ip":
        value = next((k.split(":", 1)[1] for k in e.strong_keys if k.startswith("ip:")), e.label)
        t = "ipv6-addr" if ":" in value else "ipv4-addr"
        return {
            "type": t,
            "spec_version": "2.1",
            "id": sco_id(t, {"value": value}),
            "value": value,
            "object_marking_refs": common["object_marking_refs"],
        }
    if kind == "email":
        value = next((k.split(":", 1)[1] for k in e.strong_keys if k.startswith("email:")), e.label)
        return {
            "type": "email-addr",
            "spec_version": "2.1",
            "id": sco_id("email-addr", {"value": value}),
            "value": value,
            "object_marking_refs": common["object_marking_refs"],
        }
    if kind == "url":
        value = next((k.split(":", 1)[1] for k in e.strong_keys if k.startswith("url:")), e.label)
        return {
            "type": "url",
            "spec_version": "2.1",
            "id": sco_id("url", {"value": value}),
            "value": value,
            "object_marking_refs": common["object_marking_refs"],
        }
    if kind == "account":
        acct = next((k for k in e.strong_keys if k.startswith("account:")), key)
        _, platform, login = ([*acct.split(":", 2), "", ""])[:3]
        contributing = {"account_type": platform, "account_login": login}
        obj = {
            "type": "user-account",
            "spec_version": "2.1",
            "id": sco_id("user-account", contributing),
            "account_type": platform,
            "account_login": login,
            "object_marking_refs": common["object_marking_refs"],
        }
        if e.attributes.get("display_name"):
            obj["display_name"] = str(e.attributes["display_name"])
        return obj
    if kind in ("person", "organization"):
        return {
            "type": "identity",
            "spec_version": "2.1",
            "id": _sdo_id("identity", key),
            "created": created,
            "modified": created,
            "name": e.label[:250],
            "identity_class": "individual" if kind == "person" else "organization",
            "confidence": round(e.confidence * 100),
            **common,
        }
    return None


def build_stix_bundle(
    *,
    investigation: dict[str, Any],
    findings: list[Finding],
    correlation: CorrelationResult,
    tlp: str = "amber",
) -> dict[str, Any]:
    marking = TLP_MARKINGS.get(tlp, TLP_MARKINGS["amber"])
    created = _ts()
    producer = {
        "type": "identity",
        "spec_version": "2.1",
        "id": _sdo_id("identity", "atlas-osint-producer"),
        "created": "2026-01-01T00:00:00.000Z",
        "modified": "2026-01-01T00:00:00.000Z",
        "name": "ATLAS OSINT",
        "identity_class": "system",
    }
    common = {"created_by_ref": producer["id"], "object_marking_refs": [marking["id"]]}
    objects: list[dict[str, Any]] = [marking, producer]
    entity_obj: dict[str, str] = {}
    seen: set[str] = set()
    for e in correlation.entities:
        obj = _entity_object(e, created, common)
        if obj is None:
            continue
        entity_obj[e.id] = obj["id"]
        if obj["id"] not in seen:
            seen.add(obj["id"])
            objects.append(obj)
    for r in correlation.relationships:
        src, dst = entity_obj.get(r.source_entity_id), entity_obj.get(r.target_entity_id)
        if not src or not dst or src == dst:
            continue
        objects.append(
            {
                "type": "relationship",
                "spec_version": "2.1",
                "id": _sdo_id("relationship", f"{investigation['id']}:{r.id}"),
                "created": created,
                "modified": created,
                "relationship_type": "related-to",
                "source_ref": src,
                "target_ref": dst,
                "description": f"{r.type} ({r.evidence_kind.value} evidence): {r.rationale}"[:1000],
                "confidence": round(r.confidence * 100),
                **common,
            }
        )
    report_id = _sdo_id("report", f"investigation:{investigation['id']}")
    finding_entity: dict[str, list[str]] = {}
    for e in correlation.entities:
        if e.id in entity_obj:
            for fid in e.finding_ids:
                finding_entity.setdefault(fid, []).append(entity_obj[e.id])
    for f in findings:
        if classify(f) == "rejected":
            continue
        refs = sorted(set(finding_entity.get(f.id, []))) or [report_id]
        note: dict[str, Any] = {
            "type": "note",
            "spec_version": "2.1",
            "id": _sdo_id("note", f"{investigation['id']}:{f.id}"),
            "created": _ts(f.collected_at),
            "modified": _ts(f.collected_at),
            "abstract": f.title[:250],
            "content": f"{f.description}\n\nClassification: {classify(f)}; "
            f"verification: {f.verification_status.value}; match: {f.match_type.value}; "
            f"evidence: {f.evidence_kind.value}; ATLAS finding {f.id}.",
            "authors": ["ATLAS OSINT"],
            "object_refs": refs,
            "confidence": round((f.confidence.score if f.confidence else 0) * 100),
            **common,
        }
        ref: dict[str, Any] = {"source_name": f.source_display_name[:250]}
        if f.source_url.startswith(("http://", "https://")):
            ref["url"] = f.source_url
        if f.evidence.content_hash:
            ref["hashes"] = {"SHA-256": f.evidence.content_hash}
        note["external_references"] = [ref]
        objects.append(note)
    published = investigation.get("collection_finished_at") or investigation.get("finished_at")
    report = {
        "type": "report",
        "spec_version": "2.1",
        "id": report_id,
        "created": created,
        "modified": created,
        "name": str(investigation.get("title") or "ATLAS OSINT investigation")[:250],
        "description": f"ATLAS OSINT investigation of {investigation.get('subject_type')} "
        f"(legal basis: {investigation.get('legal_basis')}). Purpose: {investigation.get('purpose')}",
        "report_types": ["observed-data"],
        "published": _ts(datetime.fromisoformat(published) if isinstance(published, str) else None),
        "object_refs": [
            o["id"] for o in objects if o["type"] not in ("marking-definition",) and o["id"] != producer["id"]
        ]
        or [producer["id"]],
        **common,
    }
    objects.append(report)
    return {"type": "bundle", "id": f"bundle--{uuid.uuid4()}", "objects": objects}


def render_stix(bundle: dict[str, Any]) -> bytes:
    return json.dumps(bundle, indent=2, ensure_ascii=False).encode()
