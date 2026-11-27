"""Measure entity-resolution precision / recall on the labelled synthetic dataset.

Pairwise evaluation: every pair of records is a *true match* when it shares a ``truth_id``.

* People/organisations: a pair is a *predicted match* when the resolver merges both records into the
  same entity.
* Platform accounts are never merged (an account on GitHub and one on DEV are different objects even
  when one person owns both). For accounts, a pair is a *predicted same owner* when the two account
  entities are connected through direct-evidence relationships between accounts/URLs (claimed
  accounts, listed profile URLs, mutual links). Same-handle and shared-website relations are
  inference and do not count.

Run: ``python scripts/evaluate_entity_resolution.py`` (writes docs/test-results/entity-resolution-metrics.json).
These numbers describe behaviour on synthetic data only; they are not a claim about real-world accuracy.
"""

from __future__ import annotations

import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.correlation.resolver import resolve  # noqa: E402
from shared.types import (  # noqa: E402
    Finding,
    Identifier,
    IdentifierType,
    LinkedIdentifier,
    Reliability,
    SourceCategory,
)


def to_findings(records: list[dict]) -> tuple[list[Finding], dict[str, str]]:
    findings, truth = [], {}
    for r in records:
        if r["kind"] == "person":
            subject = Identifier(type=IdentifierType.NAME, value=r["name"])
            attrs = {"candidate_name": r["name"], "orcid": r.get("orcid")}
            linked = []
        else:
            subject = Identifier(type=IdentifierType.USERNAME, value=r["handle"])
            attrs = {"platform": r["source"], "username": r["handle"], "profile_url": r["profile_url"]}
            linked = [
                LinkedIdentifier(identifier=Identifier(type=IdentifierType.URL, value=u), relation="lists_website")
                for u in r.get("links", [])
            ]
        f = Finding(
            module="eval",
            source_name=r["source"],
            source_display_name=r["source"],
            source_url="https://eval.example/",
            source_category=SourceCategory.NAME,
            reliability=Reliability.B,
            finding_type="candidate",
            title="t",
            description="d",
            subject=subject,
            attributes={k: v for k, v in attrs.items() if v},
            linked=linked,
            entity_hint=r["hint"],
            entity_kind=r["kind"],
        )
        findings.append(f)
        truth[f.id] = r["truth_id"]
    return findings, truth


def evaluate(records: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[r["kind"]].append(r)
    totals = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    per_kind = {}
    for kind, recs in groups.items():
        findings, truth = to_findings(recs)
        subjects = list({f.subject.key: f.subject for f in findings}.values())
        corr = resolve(findings, subjects[0], subjects[1:])
        predicted = {}
        for e in corr.entities:
            for fid in e.finding_ids:
                predicted[fid] = e.id
        if kind == "account":
            predicted = _owner_components(corr, predicted)
        c = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        for a, b in itertools.combinations([f.id for f in findings], 2):
            same_truth = truth[a] == truth[b]
            same_pred = predicted[a] == predicted[b]
            key = "tp" if same_truth and same_pred else "fp" if same_pred else "fn" if same_truth else "tn"
            c[key] += 1
        per_kind[kind] = _metrics(c) | {"records": len(recs), "name_collisions_flagged": len(corr.name_collisions)}
        for k in totals:
            totals[k] += c[k]
    return {"overall": _metrics(totals), "by_kind": per_kind}


def _owner_components(corr, predicted: dict[str, str]) -> dict[str, str]:  # type: ignore[no-untyped-def]
    subject_ids = {e.id for e in corr.entities if e.is_subject}
    parent = {e.id: e.id for e in corr.entities}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for r in corr.relationships:
        if r.evidence_kind.value != "direct" or r.source_entity_id in subject_ids or r.target_entity_id in subject_ids:
            continue
        parent[find(r.source_entity_id)] = find(r.target_entity_id)
    return {fid: find(eid) for fid, eid in predicted.items()}


def _metrics(c: dict[str, int]) -> dict:
    tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
    return {
        **c,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "false_positive_rate": round(fp / (fp + tn), 6) if fp + tn else None,
        "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else None,
    }


def main() -> None:
    data = json.loads((ROOT / "tests" / "fixtures" / "er_synthetic.json").read_text())
    result = {
        "dataset": "tests/fixtures/er_synthetic.json",
        "seed": data["seed"],
        "records": len(data["records"]),
        "note": "Synthetic data. Pairwise metrics. Not a real-world accuracy claim.",
        **evaluate(data["records"]),
    }
    out = ROOT / "docs" / "test-results" / "entity-resolution-metrics.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
