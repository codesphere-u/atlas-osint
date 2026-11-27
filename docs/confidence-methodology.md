# Confidence & assessment methodology

Confidence in ATLAS is **explainable by construction**: a score is the sum of a small number of fixed rules, every
applied rule is stored on the finding (`confidence.reasons`), and the sum of the rule deltas always equals the
score (this invariant is tested). Implementation: `engine/verification/scoring.py`.

## What a score means

A score expresses how well-supported the finding's **claim** is – e.g. "a GitHub account with the handle `x`
exists" or "`example.com` was registered on 1995-08-14". It does **not** express the probability that a record
belongs to a particular person. Identity questions are handled by entity resolution (below) and by caps that keep
name-only matches out of the "confirmed" bucket.

## Rules

| Rule | Effect | Rationale |
|---|---|---|
| `source_reliability` | Base: A 0.90 · B 0.80 · C 0.65 · D 0.50 · E 0.30 | Grade declared per source with justification (see coverage report). |
| `match_similar` | −0.30 | The returned record does not match the query exactly (case-sensitive platforms, near names, variants). |
| `match_inferred` | −0.20 | The connection was derived by ATLAS, not stated by the source. |
| `match_related` | −0.05 | An object explicitly connected to the subject (e.g. the domain of an email). |
| `inference` | −0.15 | The evidence itself is an inference. |
| `corroboration` | +0.07 per independent source asserting the same claim key, max +0.15 | Only *different* sources count. |
| `contradiction` | −0.25 | Another source reports a conflicting value for the same entity attribute. |
| `name_only_cap` | cap 0.50 | Person candidate or publication found by searching a name (Crossref works matched on the exact author name included). |
| `name_collision_cap` | cap 0.40 | Several distinct candidates share the name. |
| `variant_cap` | cap 0.40 | Found via a handle variant, not the queried handle. |
| `news_mention_cap` | cap 0.35 | An exact phrase in news text does not establish the article concerns the subject. |
| `analyst_verified` | floor 0.95 | Analyst confirmed (audited). |
| `analyst_rejected` | score 0 | Analyst rejected (audited); excluded from conclusions. |
| `upper_bound` | cap 1.00 | Bound. |

Levels: **high** ≥ 0.80 · **medium** ≥ 0.60 · **low** ≥ 0.40 · **very low** < 0.40.

## Classification (report buckets)

| Bucket | Condition |
|---|---|
| **Confirmed** | Analyst-verified, **or** score ≥ 0.80 with direct evidence, exact/related match and no dispute |
| **Possible** | Score ≥ 0.40 and not confirmed |
| **Unverified** | Score < 0.40 (insufficient evidence) |
| **Rejected** | Analyst-rejected |

Automatic verification status: `corroborated` when at least one independent source asserts the same claim,
`disputed` when the finding is part of a contradiction, otherwise `unverified`.

## Entity resolution rules

Implementation: `engine/correlation/resolver.py`.

1. Each finding names the entity it describes through a **strong key** (`entity_hint`), e.g.
   `account:github:octocat`, `person:orcid:0000-0002-1825-0097`, `organization:lei:5493…`, `domain:example.com`.
2. Entities merge only when they share a strong key, or when a URL stated by one source equals another entity's
   canonical profile URL. Adapters derive keys from persistent identifiers (an OpenAlex author with an ORCID uses the
   ORCID key, so OpenAlex, ORCID and Wikidata records with the same ORCID merge).
3. **Names never merge entities.** Equal names produce a *name collision* and a `possible_same_as` inference edge.
4. **Accounts are never merged with each other**; cross-references are relationships: `claims_account`,
   `lists_website`, `cryptographic_proof` (direct, stated by the source), `mutual_link` (both reference each other),
   `shares_website_with` (inference).
5. Relationship confidence is the best score of supporting findings; inference relationships are capped at 0.50.
6. **Multi-subject resolution** (cases): every investigation's subject is registered as an entity, so findings from
   several investigations resolve into one graph. Subsidiaries and parents from GLEIF Level 2 attach to the subject
   organisation with `parent_of` / `subsidiary_of` edges (keyed by LEI); sanctions-screening candidates attach as
   `screening_candidate` (inference), Crossref works as `name_in_author_list` (inference) unless linked by ORCID.
7. Contradictions are detected for selected attributes (validity, region, line type, registrar, dates, jurisdiction,
   legal name) when two different sources report different normalised values for the same entity.

## Measured behaviour

`scripts/evaluate_entity_resolution.py` runs the resolver on a seeded synthetic dataset with ground truth
(namesakes, ORCID-linked records, records without shared IDs, same handles owned by different people, explicit
cross-links). Current pairwise results (`docs/test-results/entity-resolution-metrics.json`):

| Kind | Precision | Recall | False-positive rate |
|---|---|---|---|
| People / organisations (merge) | 1.00 | 0.81 | 0.0 |
| Accounts (same owner via direct links) | 1.00 | 0.71 | 0.0 |

These numbers describe **synthetic data only** and are not a claim about real-world accuracy. The design trades
recall for precision: missed links appear as *possible* matches for analyst review rather than as false facts.

## Exposure scorecard

Implementation: `engine/assessment/posture.py`. The scorecard grades the **external security posture of a domain**
from evidence that was already collected – it performs no extra requests. Each check has a severity weight
(**high 10 · medium 5 · low 2**) and a status:

| Status | Credit | Meaning |
|---|---|---|
| pass | 100 % | Control present and configured as recommended |
| warn | 50 % | Present but weak (e.g. DMARC `p=none`, SPF `~all`, MTA-STS in `testing`) |
| fail | 0 % | Absent or misconfigured |
| info / unknown | not scored | Not applicable, or no evidence (source unavailable, outside scope) |

`score = round(100 × Σ credit × weight / Σ weight)` over scored checks; **grade** A ≥ 90 · B ≥ 80 · C ≥ 70 · D ≥ 60 ·
F otherwise. No grade is given when fewer than five checks could be evaluated, because a grade over two or three
checks would overstate what is known.

| Category | Checks (severity) |
|---|---|
| Email | SPF restricts senders (high) · DMARC enforced (high) · DMARC aggregate reporting (low) · MTA-STS (medium) · TLS-RPT (low) · DKIM key published (medium) |
| DNS | DNSSEC signed (medium) · CAA restricts issuers (low) |
| Web *(authorised scope)* | HTTP → HTTPS (high) · HSTS (medium) · CSP (medium) · X-Content-Type-Options (low) · Referrer-Policy (low) · clickjacking protection (low) · security.txt (low) |
| Exposure | No sensitive services exposed (high) · no known-vulnerable software versions (high) |
| Registration | Not expiring within 30 days (high) · registrar transfer lock (low) |
| Brand *(authorised scope)* | Lookalike domains (medium) |

Each check records its detail, the findings it was derived from, a recommendation when it does not pass, and a
reference (RFC, OWASP, NCSC). Known limits: DKIM is checked only against common selectors, so a missing key is a
*warning*, not a failure; InternetDB CVEs are inferred from software versions and are not confirmed
vulnerabilities; MTA-STS absence is a warning because adoption is still low. Vendor ratings (UpGuard,
SecurityScorecard, Bitsight) use other checks and weights, so ATLAS grades are **not comparable** with them.

## Risk highlights

Implementation: `engine/assessment/risk.py`. Highlights are derived deterministically from finding flags, finding
types and failed high-severity checks:

| Trigger | Severity |
|---|---|
| Possible sanctions-list match | critical |
| Possible debarment / crime-list match · sensitive service exposed · failed high-severity posture check | high |
| Possible PEP, regulatory, person-of-interest match · known-vulnerable versions · mail-capable lookalikes · breach notification · dissolved/inactive entity | medium |

Each highlight lists its supporting findings and is marked **confirmed** only when all of them are classified as
confirmed; screening hits are therefore shown as *requires confirmation* until an analyst verifies them. An
investigation's risk level is its most severe highlight.

## Change detection

Implementation: `engine/changes.py`. After each run ATLAS stores a snapshot of finding signatures
(`source | claim_key`). The next run is compared with it:

- **added** / **removed** – signatures present in only one run;
- only sources that **answered in both runs** are compared. A source that was unavailable, rate-limited or not
  configured in one of the runs is listed under *not compared* instead of producing phantom additions or removals;
- the first run is a **baseline**.

Monitoring (scheduled re-runs at 6 h – 30 d intervals) uses the same comparison. It is available for organisations,
domains, URLs and IP addresses only.
