# Architecture

## Overview

```
                 ┌────────────────────── Caddy (TLS, HSTS) ──────────────────────┐
 Browser ───────►│  /api/*, /healthz ──► FastAPI (apps/api)   /* ──► Next.js (apps/web) │
                 └───────────────────────────────┬────────────────────────────────┘
                                                 │ dispatch (inline | Celery via Redis)
                                                 ▼
  ┌──────────────────────────── Investigation pipeline (engine/) ────────────────────────────┐
  │ normalize → module plan → collect (adapters, concurrent) → privacy policy → opt-out      │
  │ suppression → module post-process → dedupe → correlate → score → analyse → persist       │
  └──────────────────────────────────────────────────────────────────────────────────────────┘
        │ SafeHttpClient (SSRF checks, DNS pinning, size limits, rate limits)
        ▼
   Public APIs, registries, DNS, CT logs, archives …            PostgreSQL (encrypted columns)
```

All major components are pure Python packages that can be imported and tested independently of the API:

| Package | Responsibility |
|---|---|
| `shared/` | Settings, domain types (`Finding`, `Entity`, …), SSRF-safe HTTP client, DNS (system or DNS-over-HTTPS), privacy policy, crypto, rate limiting, logging |
| `integrations/sources/` | `SourceAdapter` contract, registry/plugin discovery, 40 adapters |
| `integrations/providers/` | LLM providers (Anthropic Claude, OpenAI-compatible self-hosted) |
| `modules/` | One module per input family: collection plan, passive pivots, guardrails, post-processing, summary |
| `engine/normalization` | Identifier detection and canonical forms (E.164, IDNA, URL, handles, names) |
| `engine/collectors` | Concurrent orchestration, per-source run records, progress callbacks |
| `engine/correlation` | Deduplication, entity resolution, relationships, contradictions, name collisions |
| `engine/verification` | Confidence scoring rules, classification (confirmed / possible / unverified / rejected) |
| `engine/assessment` | Exposure scorecard (posture checks, grade) and risk highlights |
| `engine/changes.py` | Change detection between runs (only across sources that answered both times) |
| `engine/analysis` | Untrusted-content sanitisation, deterministic analyst, LLM narrative with validation, timeline |
| `engine/reporting` | Report model, JSON/CSV/HTML/PDF renderers and the STIX 2.1 exporter (TLP 2.0 markings) |
| `engine/pipeline.py` | Composes the above into one I/O-free processing function |
| `apps/api` | HTTP API, auth, RBAC, persistence, audit, privacy workflow, retention, migrations |
| `workers/` | Celery app, investigation task, monitoring scheduler (every 10 min) and retention purge |
| `apps/web` | Analyst dashboard |

## Investigation lifecycle

1. **Create** (`POST /api/v1/investigations`): the identifier is normalised; the authorisation record is validated
   (attestation, consent rules for individuals, references); opt-out suppression is checked against a keyed hash of
   the identifier; retention date is set; an audit entry is written.
2. **Dispatch**: inline (FastAPI background task) or Celery. Status `queued → running`.
3. **Plan**: the module for the identifier type selects enabled adapters (global config ∩ creator's role ∩
   optional per-investigation restriction) and optional passive pivots.
4. **Collect**: adapters run concurrently (bounded semaphore). Each adapter checks configuration, authorisation
   (consent / scope) and returns an `AdapterResult` with a status, even on failure. Progress is persisted per source.
5. **Process** (`engine.pipeline.process`): privacy policy → suppression → module post-processing → dedupe →
   correlation → scoring → coverage report. Prior analyst decisions are re-applied on re-runs.
6. **Analyse**: deterministic analysis always; LLM narrative if requested and configured.
7. **Assess**: exposure scorecard (infrastructure subjects), risk highlights, change set against the previous run
   (restricted to sources that answered in both runs) and run history.
8. **Persist**: findings (encrypted JSON + plaintext filter columns), results blob (encrypted), risk level and grade
   columns for listing, audit entry. Monitored investigations get their next run time.
9. **Review**: analysts verify/reject findings (individually or in bulk) and add notes → re-scoring, re-correlation
   and re-assessment.
10. **Pivot / group**: pivots create child investigations that inherit the authorisation record and join a case;
    cases resolve all their findings together (multi-subject entity resolution) for a merged graph, timeline and export.
11. **Report / share / delete / expire**: PDF/HTML/JSON/CSV/STIX with the TLP marking; retention purge.

### Scheduling

With `ATLAS_TASK_BACKEND=celery`, Celery beat queues due monitoring runs every 10 minutes and purges expired data every
6 hours. With the inline backend a daemon thread in the API process does the same (`ATLAS_INLINE_SCHEDULER`).
Monitoring is refused for individuals.

## Data model (PostgreSQL)

| Table | Key columns | Encrypted |
|---|---|---|
| `users` | email, Argon2 hash, role, lockout | – |
| `api_keys` | prefix, HMAC hash, expiry, revocation | (hash only) |
| `investigations` | type, kind, status, authorisation record, retention, progress, counts, `subject_hash`, case, parent, TLP, monitoring interval/next run, risk level, grade | `subject_enc`, `results_enc` |
| `findings` | source, type, classification, score, status, claim key, dates | `data_enc` (full finding) |
| `analyst_notes` | investigation, finding, author | `body_enc` |
| `audit_logs` | actor, action, target, outcome, details (hashes only) | – |
| `cases` | title, status, TLP, owner | `description_enc` |
| `source_configs` | enabled, min role | – |
| `suppressions` | identifier HMAC | (hash only) |
| `privacy_requests` | kind, status, identifier HMAC | identifier, contact, details |

Migrations are managed by Alembic and applied automatically at API start (`ATLAS_AUTO_MIGRATE`).

## Key design decisions

| Decision | Rationale |
|---|---|
| Rule-based confidence instead of ML | Explainability and reproducibility; no labelled real-world data to train on responsibly. |
| Merge only on persistent identifiers | False merges of people are the most harmful OSINT error; we accept lower recall (measured). |
| Accounts are never merged, only linked | An account is an object on a platform; ownership is a relationship backed by evidence. |
| Encrypt whole finding documents | Findings can contain personal data; filterable metadata is kept in plain columns. |
| Deterministic analyst always runs | The platform is useful and auditable without any AI provider. |
| Official APIs over scraping | Legal clarity, stable parsing, accurate metadata; coverage is reported honestly. |
| Inline task backend for single-node | Easy development and small deployments; Celery for scale. |
| Source metadata as code | One source of truth for UI, coverage report, citations and data-minimisation enforcement. |
| Same-origin web/API via proxy | httpOnly SameSite=Strict cookies with CSRF header; no tokens in browser storage. |
| Scorecard from collected evidence only | No extra probing; weights published; vendor scores are not comparable anyway. |
| No monitoring of individuals | Scheduled re-collection about a person would be surveillance; refused in the service layer. |
| Changes compared per answering source | Source outages must not masquerade as real-world change. |
| Official OASIS TLP objects in STIX | Interoperates with OpenCTI/MISP without custom marking definitions. |
| Optional DNS-over-HTTPS | Filtered networks would otherwise yield false "no SPF/DMARC" conclusions. |

## Extensibility points

- **Sources**: `SourceAdapter` subclasses registered via the `atlas_osint.sources` entry point.
- **LLM providers**: implement `LLMProvider.generate_json`.
- **Modules**: implement `IntelligenceModule` (plan / postprocess / summarize) and register in `modules/registry.py`.
- **Report formats**: add a renderer to `engine/reporting/renderers.RENDERERS`.

## Observability

Structured JSON logs with request IDs and secret redaction; `/healthz` and `/readyz` endpoints; per-source health
derived from recent investigation progress (visible in Source management and the Overview page); container health
checks for every service.
