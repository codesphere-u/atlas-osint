"""Generate the synthetic, labelled entity-resolution dataset (tests/fixtures/er_synthetic.json).

The dataset deliberately contains the hard cases an OSINT resolver must get right:
* namesakes (several distinct people sharing a name),
* the same person in several sources linked by a persistent identifier (ORCID),
* the same person in several sources with *no* shared identifier (expected false negatives),
* the same handle on several platforms owned by *different* people,
* accounts that explicitly reference each other (profile URL / claimed account).

Every record carries a ground-truth ``truth_id``. Deterministic (seeded) so results are reproducible.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "er_synthetic.json"
FIRST = ["Maria", "John", "Aiko", "Wei", "Fatima", "Lars", "Priya", "Diego"]
LAST = ["Example", "Sample", "Tanaka", "Chen", "Haddad"]


def orcid(rng: random.Random) -> str:
    d = [str(rng.randint(0, 9)) for _ in range(15)]
    return f"0000-{''.join(d[:3])}{d[3]}-{''.join(d[4:8])}-{''.join(d[8:11])}{d[11]}"


def main(seed: int = 20261126, people: int = 80, account_owners: int = 40) -> None:
    rng = random.Random(seed)
    records = []
    for i in range(people):
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        truth = f"P{i}"
        has_orcid = rng.random() < 0.7
        oid = orcid(rng) if has_orcid else None
        records.append(
            {
                "truth_id": truth,
                "source": "openalex",
                "kind": "person",
                "name": name,
                "hint": f"person:orcid:{oid}" if oid else f"person:openalex:A{i}",
                "orcid": oid,
            }
        )
        if oid and rng.random() < 0.6:
            records.append(
                {
                    "truth_id": truth,
                    "source": "orcid",
                    "kind": "person",
                    "name": name,
                    "hint": f"person:orcid:{oid}",
                    "orcid": oid,
                }
            )
        if rng.random() < 0.25:
            link = oid if (oid and rng.random() < 0.5) else None
            records.append(
                {
                    "truth_id": truth,
                    "source": "wikidata",
                    "kind": "person",
                    "name": name,
                    "hint": f"person:wikidata:Q{i}",
                    "orcid": link,
                }
            )
    handles = ["octo", "pixel", "nova", "atlas", "ember", "quill"]
    used: set[tuple[str, str]] = set()  # a handle is unique per platform, but not across platforms
    for j in range(account_owners):
        truth = f"A{j}"
        handle = f"{rng.choice(handles)}{rng.randint(1, 4)}"
        platforms = [
            p
            for p in rng.sample(["github", "gitlab", "devto", "codeberg"], k=rng.randint(1, 3))
            if (p, handle) not in used
        ]
        if not platforms:
            continue
        used.update((p, handle) for p in platforms)
        first = platforms[0]
        for p in platforms:
            rec = {
                "truth_id": truth,
                "source": p,
                "kind": "account",
                "handle": handle,
                "hint": f"account:{p}:{handle}",
                "profile_url": f"https://{p}.example/{handle}",
                "links": [],
            }
            if p != first and rng.random() < 0.5:
                rec["links"].append(f"https://{first}.example/{handle}")
            records.append(rec)
    OUT.write_text(json.dumps({"seed": seed, "records": records}, indent=1) + "\n")
    print(f"wrote {len(records)} records to {OUT}")


if __name__ == "__main__":
    main()
