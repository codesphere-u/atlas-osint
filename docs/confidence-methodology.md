# Confidence methodology

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
| `name_only_cap` | cap 0.50 | Person candidate found by searching a name. |
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
6. Contradictions are detected for selected attributes (validity, region, line type, registrar, dates, jurisdiction,
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
