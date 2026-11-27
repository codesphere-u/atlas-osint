# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Production deployment tooling in `deploy/`: `setup.sh` (generates `.env` with all secrets and a one-time admin
  password, refuses to overwrite keys), `check.sh` (post-deployment verification, `--clear-bootstrap-password`),
  `backup.sh`, `restore.sh` (safety dump first) and `upgrade.sh` (backup, update, verify).
- Scheduled PostgreSQL backups (`backup` service) with retention.
- Optional IP allow-list at Caddy (`ATLAS_ALLOWED_IPS`) that keeps the privacy-request page public.
- `atlas reset-password` command (clears lockout, audited).
- Deploying from published GHCR release images (`ATLAS_IMAGE_REPO`, `ATLAS_VERSION`).
- Log rotation and memory limits for every container.
- CI starts the production stack with `setup.sh` and runs `check.sh` and a sign-in on every push; shellcheck for
  the deploy scripts.

### Changed
- Web dashboard upgraded to **Next.js 16.4** (Turbopack builds) and **ESLint 10** with the native flat configs of
  `eslint-config-next` (no `FlatCompat`). `middleware.ts` is now `proxy.ts`. The PostCSS override is no longer
  needed and was removed.
- Components refactored for the React Compiler-era `react-hooks` rules: no state updates inside effects and no ref
  writes during render. The command palette and pivot dialog remount per opening; graph drag positions are
  overrides tied to the current layout; the sidebar preference is read with `useSyncExternalStore`; `useApi`
  derives its loading state and uses `useEffectEvent` for its stop condition.

### Fixed
- Pivot dialog kept the consent reference typed for a previous pivot.
- Entity graph rendered one empty frame before positions were set.
- `useApi` could report "loaded" for a new path when a slower response for the previous path arrived first.

## [0.2.0] - 2026-11-27

### Added
- **9 new sources (40 total):** Shodan InternetDB (open ports, CPEs, version-based CVEs), SSLMate Cert Spotter
  (second certificate-transparency source), `security.txt`, email security (SPF, DMARC, MTA-STS, TLS-RPT, BIMI,
  DNSSEC, DKIM selectors), lookalike domains (scope-gated), Mastodon (rel=me verified links), Bluesky (verified
  domain handles), Crossref publications (ORCID-linked), OpenSanctions sanctions/PEP/debarment screening.
- GLEIF Level 2 corporate hierarchy: direct and ultimate parents and direct subsidiaries.
- **Exposure scorecard:** A–F grade from 20 checks across email, DNS, web, exposure, registration and brand, each
  with detail, recommendation and reference; no grade with fewer than five evaluable checks.
- **Risk highlights** derived from screening hits, exposure, lookalikes, breaches, dissolved entities and failed
  high-severity checks, marked confirmed or requiring confirmation.
- **Cases** with merged entity graph, timeline and STIX/JSON export across investigations.
- **Pivots:** one-click child investigations from linked identifiers that inherit the authorisation and re-check
  consent rules.
- **Change detection** between runs (only across sources that answered in both) and **scheduled monitoring** for
  organisations and infrastructure (6 h – 30 d), via Celery beat or an inline scheduler.
- **TLP 2.0** markings on investigations and cases; printed on every PDF page and embedded as official OASIS
  marking definitions in exports.
- **STIX 2.1 export** with deterministic observable IDs, validated with the `stix2` library.
- Reports: executive summary and exposure scorecard sections.
- Bulk verification of findings; investigation update endpoint; assessment endpoint; richer statistics.
- Optional DNS-over-HTTPS resolver (`ATLAS_DNS_RESOLVER=doh`).
- Rebuilt analyst UI: command palette (⌘K) with identifier detection, overview with activity and risk charts,
  split-pane findings with keyboard navigation and bulk actions, exposure and changes pages, graph workspace
  (force/radial layouts, focus mode, search, PNG/SVG export), timeline with histogram, cases pages, pivot dialog,
  TLP/risk/grade badges, skeleton loading states and toasts.
- Migration `0002` (cases, pivots, TLP, monitoring, assessment columns).

### Fixed
- PDF reports drew body text from the right edge of the previous cell (clipped paragraphs); layout regression test.
- Domain summaries counted subdomains reported by two CT sources twice.
- STIX external references without HTTP URLs failed strict validation.

### Changed
- Entity resolution resolves several subjects together (cases) and attaches related organisations, screening
  candidates and publications to the right subject.
- The name-only confidence cap also applies to publications found by author name.
- User agent `ATLAS-OSINT/0.2`.

## [0.1.0] - 2026-11-26

### Added
- Core engine: collection orchestrator, identifier normalisation (E.164, IDNA, URL, handles, names), privacy
  policy filter, deduplication, entity resolution on persistent identifiers, contradiction and name-collision
  detection, explainable confidence scoring, coverage reporting.
- 31 source adapters across phone, username, name, email, domain/infrastructure and public-records categories,
  with a plugin registry (`atlas_osint.sources` entry points).
- Intelligence modules with guardrails and passive pivots (email → organisational domain, handle variants).
- AI analyst: deterministic analysis (classification, timeline, gaps, confidence explanations) plus optional
  Claude / OpenAI-compatible narrative with prompt-injection defences and citation validation.
- Reports in PDF, HTML, JSON and CSV.
- FastAPI backend: JWT + httpOnly cookie sessions with CSRF header, API keys, RBAC (admin, analyst, viewer,
  auditor), investigation authorisation records, consent enforcement, source access control, analyst
  verification and notes, audit log, opt-out/correction/deletion workflow, retention purge, encryption at rest,
  rate limiting, security headers, SSRF protection with DNS pinning.
- Next.js dashboard with 15 pages including entity graph, evidence timeline, source management and administration.
- Docker Compose deployment (PostgreSQL, Redis, Celery worker/beat, Caddy TLS), GitHub Actions CI.
- 172 automated tests and a synthetic entity-resolution benchmark.
