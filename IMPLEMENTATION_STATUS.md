# Implementation status

Status legend: **Implemented & tested** · **Partial** (works, with stated gaps) · **Blocked** (cannot be done
lawfully / without third-party access) · **Not started**. Last updated 2026-11-26 (v0.1.0).

## 2. Core intelligence engine

| Requirement | Status | Notes |
|---|---|---|
| Phone: E.164 normalisation, country/numbering plan, validity, formatting | Implemented & tested | libphonenumber (offline) |
| Phone: carrier & line type | Implemented & tested | Range-allocated carrier (portability disclosed); numverify adapter optional (key) |
| Phone: published business-contact associations, indexed references | Blocked | No openly licensed, ToS-compatible source identified; search-engine scraping deliberately excluded |
| Phone: never identifies private subscriber | Implemented & tested | Module guard strips subscriber-like attributes |
| Username: profiles across platforms, exact vs similar, metadata | Implemented & tested | 10 platforms via official/public APIs; variants marked similar |
| Username: cross-platform references | Implemented & tested | Claimed accounts, listed URLs, Keybase cryptographic proofs, mutual links |
| Username: unavailable/restricted sources recorded | Implemented & tested | Per-source status in coverage |
| Name: professional/academic profiles, affiliations, publications | Partial | OpenAlex, ORCID, Wikidata; interviews/biographies only via GDELT news mentions |
| Name: collisions, confirmed vs possible, never merge on name | Implemented & tested | |
| Email: syntax, domain, DNS policy | Implemented & tested | |
| Email: professional associations | Partial | Organisational-domain pivot only (see limitations) |
| Email: authorised breach notification | Implemented & tested | HIBP, key + consent required |
| Email: no mailbox access / password recovery | Implemented | No such code paths exist |
| Domain: DNS, RDAP, CT, technologies, security headers, IP/ASN, history | Implemented & tested | Wayback + RDAP + CT for history; no passive-DNS provider |
| Domain: subdomains within authorised scope | Implemented & tested | CT-derived, listed only when in scope; no brute force |
| Public records: registries, company records, news, documents | Partial | GLEIF, SEC EDGAR, Companies House, OpenCorporates, Wikidata, GDELT, public documents; academic repositories via OpenAlex; few national registries |

## 3–4. Source framework and correlation

| Requirement | Status | Notes |
|---|---|---|
| Plugin architecture with full metadata contract | Implemented & tested | Entry points; metadata drives UI, coverage doc, citations, minimisation |
| Transparent coverage reporting | Implemented & tested | Per investigation and `docs/source-coverage.md` (generated, checked in CI) |
| Duplicates, shared identifiers, contradictions, direct vs inference, provenance | Implemented & tested | |
| Explainable confidence; manual analyst verification | Implemented & tested | |
| Every finding carries description, URL, source, timestamps, excerpt, confidence, status | Implemented & tested | Plus response hash and citation |

## 5. AI analyst

| Requirement | Status | Notes |
|---|---|---|
| Summaries, timelines, inconsistencies, relationships, structured report, confirmed/possible/unknown, confidence explanations, insufficient evidence | Implemented & tested | Deterministic layer always; LLM narrative optional |
| Never converts speculation to fact | Implemented & tested | Citation validation and downgrade rules |
| Prompt-injection protection | Implemented & tested | Sanitisation, flags, envelope, schema output |
| Live Claude call | Partial | Implemented with the official SDK; not exercised against the real API in tests (no key in CI) – covered with a fake provider |

## 6. Dashboard (15 pages)

| Page | Status |
|---|---|
| Overview, New investigation, Phone, Username, Name, Email, Domain, Public records, Results, Entity graph, Evidence timeline, Source management, Investigation history, Reports (analysis & exports), Administration | Implemented; verified by build, typecheck, lint, unit tests and a Playwright walkthrough with live data (desktop + mobile). No automated E2E suite in CI yet. |
| Extra: Login, public Privacy-request page | Implemented |

## 7. Privacy, security, compliance

| Requirement | Status |
|---|---|
| Lawful-use controls, authorisation records, consent-based profiling | Implemented & tested |
| Data minimisation, prohibited categories | Implemented & tested |
| Retention limits, deletion workflows, opt-out & correction | Implemented & tested (correction = review + reject finding; source data cannot be changed) |
| Audit logs | Implemented & tested |
| Encryption in transit (Caddy TLS) and at rest (Fernet) | Implemented & tested (TLS verified in Compose) |
| RBAC, API authentication, rate limiting, SSRF protection, input validation | Implemented & tested |
| Secret management | Implemented (env/secret store, `SecretStr`, redaction, production checks) |
| Source-specific access controls | Implemented & tested (enable/disable, minimum role, consent/scope flags) |
| MFA / SSO | Not started (roadmap) |

## 8–13. Architecture, reports, testing, delivery

| Requirement | Status |
|---|---|
| FastAPI, PostgreSQL, SQLAlchemy, Redis, Celery, Next.js, TypeScript, Tailwind | Implemented |
| Docker, Compose, CI/CD, automated migrations, env config, structured logging, health checks | Implemented & verified (Compose run end to end) |
| Monitoring | Partial – health endpoints, container health checks, per-source health, JSON logs; no metrics exporter |
| PDF, JSON, CSV, HTML reports with all required sections | Implemented & tested (PDF limited to Latin-1 glyphs) |
| Unit, integration, adapter, API, authn, authz, security, validation, ER accuracy, regression tests | Implemented (172 tests) |
| Synthetic datasets; measured FP/FN rates | Implemented (`docs/test-results.md`) |
| Repository structure and community files | Implemented |
