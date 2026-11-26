# Test results

Recorded on 2026-11-26 for version 0.1.0 (Python 3.13, Node 22). Re-run with the commands in `README.md`; CI runs
the same checks on every push.

## Summary

| Check | Result |
|---|---|
| Backend tests (`pytest`) | **172 passed**, 1 deselected (live network test) |
| – unit | 90 passed (normalisation, policy, adapters, scoring, resolver, analysis, reporting, modules, registry, ER accuracy) |
| – integration | 14 passed (end-to-end API workflows with mocked sources) |
| – security | 68 passed (SSRF, authentication, authorisation, lawful-use controls, prompt injection, data protection) |
| Ruff lint + format | clean |
| mypy (55 source files) | no issues |
| Bandit SAST | no issues |
| pip-audit | no known vulnerabilities |
| Alembic `check` (models vs migrations) | no drift |
| Web: `tsc --noEmit`, ESLint, Vitest (5 tests), `next build` | all pass |
| npm audit (production deps) | 0 vulnerabilities |
| Docker images (api, web) | build |
| Docker Compose stack | all 6 services healthy; Celery worker completed an investigation on PostgreSQL; PDF export over HTTPS |
| Browser walkthrough (Playwright, live sources) | login → module page → domain & organisation investigations → results, graph, timeline, reports (PDF/HTML/JSON/CSV) → sources, history, admin, mobile view; 0 console errors |

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
| Reports | all formats, required sections, HTML escaping, CSV formula neutralisation |
| API | full investigation lifecycle, verification & re-scoring, notes, graph, timeline, exports, search, stats, deletion, audit trail, source configuration |
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

## Live-source observations (sandboxed run, 2026-11-26)

Real data was collected from DNS, RDAP, crt.sh, GLEIF, Wikidata, OpenAlex, GDELT, Keybase, npm, Docker Hub and the
website-headers adapter. From the test environment some sources were blocked or rate-limited (GitHub API 403,
Reddit 403, Wikidata 429, Wayback connection refused); ATLAS reported these as *unavailable* / *rate-limited* in the
coverage section rather than as "no results", which is the intended behaviour.
