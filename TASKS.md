# Tasks

Tracks the engineering phases of the original brief. See `IMPLEMENTATION_STATUS.md` for per-requirement status.

## Phases

- [x] **Phase 1** – Research existing OSINT tools → `docs/research.md`
- [x] **Phase 2** – Architecture and implementation plan → `docs/architecture.md`
- [x] **Phase 3** – Repository and backend foundation (config, domain types, DB, migrations, API skeleton)
- [x] **Phase 4** – Source adapter framework + 31 adapters + 6 intelligence modules
- [x] **Phase 5** – Evidence & provenance, entity resolution, confidence scoring, coverage reporting
- [x] **Phase 6** – Next.js dashboard and investigation workflows (15 pages)
- [x] **Phase 7** – AI analyst (deterministic + LLM with validation) and PDF/HTML/JSON/CSV reports
- [x] **Phase 8** – Security, privacy, compliance controls and tests
- [x] **Phase 9** – Documentation and deployment (Docker Compose, Caddy TLS, CI)
- [x] **Phase 10** – Quality audit → `docs/security-audit.md`, `docs/test-results.md`

## Backlog (next)

- [ ] OIDC SSO and MFA; token versioning for immediate revocation
- [ ] Playwright E2E suite in CI; axe accessibility checks
- [ ] Reddit OAuth adapter; Mastodon/WebFinger and Bluesky adapters
- [ ] Additional national company registries; Crossref/arXiv publications
- [ ] Public Suffix List for registrable-domain detection in RDAP
- [ ] Prometheus metrics endpoint
- [ ] Nonce-based CSP for the web app; Unicode fonts in PDF reports
- [ ] Multi-tenancy and investigation sharing
- [ ] Independent third-party penetration test
