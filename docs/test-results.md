# Test results

Recorded on 2026-11-27 for version 0.2.0 (Python 3.13, Node 22). Re-run with the commands in `README.md`; CI runs
the same checks on every push. v0.1.0 results (2026-11-26) are summarised at the end.

## Summary

| Check | Result |
|---|---|
| Backend tests (`pytest`) | **205 passed**, 1 deselected (live network test) |
| – unit | 114 passed (normalisation, policy, adapters incl. 9 new sources, scoring, resolver, assessment, analysis, reporting incl. STIX and PDF layout, modules, registry, ER accuracy) |
| – integration | 23 passed (end-to-end API workflows with mocked sources, incl. cases, pivots, monitoring, change detection, bulk verification, TLP/STIX exports) |
| – security | 68 passed (SSRF, authentication, authorisation, lawful-use controls, prompt injection, data protection) |
| Ruff lint + format | clean (136 files) |
| mypy (62 source files) | no issues |
| Bandit SAST | no issues |
| pip-audit | no known vulnerabilities |
| Alembic `check` | no drift on SQLite and PostgreSQL 16 |
| Migration 0001 → 0002 on a populated PostgreSQL 16 database | upgrade, downgrade, re-upgrade succeed; existing rows get TLP:AMBER, `run_count` 0 |
| STIX bundles | parse with `stix2.parse(..., allow_custom=False)` |
| Source coverage document | regenerated, 40 adapters |
| Web: `tsc --noEmit`, ESLint, Vitest (19 tests), `next build` (17 routes) | all pass |
| npm audit (production deps) | 0 vulnerabilities |
| Docker Compose stack | not re-run for v0.2 (no Docker daemon in this environment); Dockerfiles unchanged since the verified v0.1 run, Compose only gained pass-through variables |
| Browser walkthrough (Playwright, live sources, DoH resolver) | ⌘K palette → domain investigation → findings (keyboard navigation, bulk verify) → exposure scorecard → graph (force/radial, focus, export) → timeline → pivot from a linked identifier → re-run with change detection → monitoring → STIX/PDF/HTML/JSON/CSV exports → organisation with GLEIF hierarchy → cases (merged graph) → overview → history, sources, admin, mobile; 0 console errors |

## What the tests cover

| Area | Representative tests |
|---|---|
| Source adapters | success, not found, 429 rate limit, network failure, malformed response, case-sensitive platforms, consent gating (HIBP), scope gating (crt.sh subdomains, HTTP headers), robots.txt, data minimisation, registrant redaction |
| Normalisation | E.164, IDNA email/domain, URL canonicalisation, handle rules, control characters, type detection |
| Privacy policy | prohibited attributes by subject kind, free-text redaction (phones, cards with Luhn, addresses, coordinates), linked phone removal, forbidden finding types |
| Scoring | every rule, caps, analyst overrides, contradiction penalties, invariant: sum of rule deltas = score |
| Entity resolution | names never merge, ORCID merges, handles never merge accounts, URL-equivalence merges, mutual links, shared-website inference, dedupe |
| Accuracy benchmark | precision / recall / FP / FN on the synthetic labelled dataset (below) |
| AI analyst | injection sanitisation, envelope escaping, unsupported/hallucinated citations dropped, confirmed claims downgraded, provider failure fallback, rejected findings withheld |
| Reports | all formats, required sections, HTML escaping, CSV formula neutralisation, TLP banners, executive summary, PDF text-position regression (body text starts at the left margin) |
| STIX | strict validation, deterministic SCO IDs, TLP marking objects equal to the OASIS definitions, every object marked |
| Assessment | each scorecard check, weights and grade boundaries, "insufficient data" below five checks, risk highlight rules, confirmed vs unconfirmed |
| Change detection | baseline, added/removed, sources unavailable in one run excluded and listed as not compared |
| New adapters | InternetDB (404, IPv4 only, risky ports), Cert Spotter (scope), security.txt (scope, parsing), email security (SPF/DMARC/MTA-STS/TLS-RPT/BIMI/DKIM, scope), lookalikes (scope, null MX), Mastodon (verified links), Bluesky (400 = not found, domain handles), Crossref (exact author only, ORCID), GLEIF hierarchy, OpenSanctions (hit, clear, not configured), DoH parsing |
| API | full investigation lifecycle, verification & re-scoring, bulk verification, notes, graph, timeline, exports, search, stats, deletion, audit trail, source configuration, cases, pivots, monitoring, scheduler |
| Security | token forgery/expiry/`alg=none`, role-claim escalation, API keys, CSRF, lockout, RBAC matrix, ownership isolation, consent/attestation/scope, opt-out & deletion, retention, encryption at rest, input validation, body limits, rate limits, headers, secret redaction, production config validation |

## Entity-resolution metrics (synthetic data)

From `scripts/evaluate_entity_resolution.py` on `tests/fixtures/er_synthetic.json` (seed 20261126, 184 records;
full output in `docs/test-results/entity-resolution-metrics.json`). Pairwise evaluation.

| Kind | TP | FP | FN | Precision | Recall | FP rate | FN rate |
|---|---|---|---|---|---|---|---|
| People / organisations | 52 | 0 | 12 | 1.000 | 0.813 | 0.0 | 0.188 |
| Accounts (same owner via direct links) | 15 | 0 | 6 | 1.000 | 0.714 | 0.0 | 0.286 |
| **Overall** | 67 | 0 | 18 | **1.000** | **0.788** | 0.0 | 0.212 |

False negatives are records of the same person that share no persistent identifier (by design they are not merged
and surface as *possible* matches). **These figures describe synthetic data only and are not a real-world accuracy
claim.**

## Live-source observations

**2026-11-27 (v0.2).** InternetDB, Cert Spotter, Mastodon, Bluesky, Crossref, GLEIF Level 2 and the DoH resolver
were checked against the live services before and after writing the adapters. The sandbox's system resolver only
answers A records, so email-security checks returned nothing until the DoH resolver was enabled (google.com: SPF
`~all`, DMARC `p=reject`). During one run crt.sh timed out; the change-detection comparison correctly listed it as
*not compared* instead of reporting removed subdomains. OpenSanctions was not called live (no key); it is covered
by fixture tests built from the documented response format.

**2026-11-26 (v0.1).**

Real data was collected from DNS, RDAP, crt.sh, GLEIF, Wikidata, OpenAlex, GDELT, Keybase, npm, Docker Hub and the
website-headers adapter. From the test environment some sources were blocked or rate-limited (GitHub API 403,
Reddit 403, Wikidata 429, Wayback connection refused); ATLAS reported these as *unavailable* / *rate-limited* in the
coverage section rather than as "no results", which is the intended behaviour.

## v0.1.0 (2026-11-26)

172 backend tests passed (90 unit, 14 integration, 68 security); Ruff, mypy (55 files), Bandit, pip-audit, Alembic
check, web typecheck/lint/Vitest (5 tests)/build and npm audit were clean. The Docker Compose stack ran end to end
(all 6 services healthy, Celery worker on PostgreSQL, PDF export over HTTPS).
