"""Change detection between collection runs of the same investigation.

Findings are compared by a stable signature (source + claim key), so a re-run or a scheduled monitoring run
can report exactly what appeared and what disappeared – e.g. a new subdomain, a new open port, a changed
registrar, a newly registered lookalike domain or a new sanctions-list entry.
"""

from __future__ import annotations

from typing import Any

from shared.types import Finding

MAX_ITEMS = 200


def signature(f: Finding) -> str:
    return f"{f.source_name}|{f.claim_key or f.finding_type + ':' + f.title}"


def snapshot(findings: list[Finding]) -> list[dict[str, str]]:
    return [
        {"sig": signature(f), "title": f.title, "source": f.source_display_name, "finding_type": f.finding_type}
        for f in findings
    ]


def diff(
    previous: list[dict[str, str]] | None,
    current: list[Finding],
    compared_to: str | None,
    *,
    previous_answered: set[str] | None = None,
    current_answered: set[str] | None = None,
) -> dict[str, Any]:
    """Compare two runs.

    Only sources that answered in *both* runs are compared: a source that was unavailable or rate-limited in
    one run would otherwise make all of its findings look added or removed. Those sources are listed in
    ``not_compared`` so the analyst knows the comparison is partial.
    """
    if previous is None:
        return {
            "baseline": True,
            "compared_to": None,
            "added": [],
            "removed": [],
            "added_count": 0,
            "removed_count": 0,
            "unchanged_count": len(current),
        }
    comparable: set[str] | None = None
    if previous_answered is not None and current_answered is not None:
        comparable = previous_answered & current_answered

    def keep(sig: str) -> bool:
        return comparable is None or sig.split("|", 1)[0] in comparable

    prev = {p["sig"]: p for p in previous if keep(p["sig"])}
    cur = {signature(f): f for f in current if keep(signature(f))}
    added = [
        {
            "title": f.title,
            "source": f.source_display_name,
            "finding_type": f.finding_type,
            "finding_id": f.id,
            "flags": [x for x in f.flags if x.startswith("risk:")],
        }
        for sig, f in cur.items()
        if sig not in prev
    ]
    removed = [
        {"title": p["title"], "source": p["source"], "finding_type": p["finding_type"]}
        for sig, p in prev.items()
        if sig not in cur
    ]
    return {
        "baseline": False,
        "compared_to": compared_to,
        "added": added[:MAX_ITEMS],
        "removed": removed[:MAX_ITEMS],
        "added_count": len(added),
        "removed_count": len(removed),
        "unchanged_count": len(set(cur) & set(prev)),
        "not_compared": sorted((previous_answered or set()) ^ (current_answered or set()))
        if comparable is not None
        else [],
    }
