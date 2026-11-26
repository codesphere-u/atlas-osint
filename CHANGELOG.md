# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
- 170+ automated tests and a synthetic entity-resolution benchmark.
