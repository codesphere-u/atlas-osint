# Contributing to ATLAS OSINT

Thank you for helping build a trustworthy, lawful OSINT platform. Please read the
[Code of Conduct](CODE_OF_CONDUCT.md) – especially the *no misuse* rule – before contributing.

## Ground rules

1. **Correctness and provenance over coverage.** A new source is welcome only if every finding it produces can be
   cited, reproduced and scored honestly.
2. **No placeholder functionality presented as complete.** If something is partial, say so in
   `IMPLEMENTATION_STATUS.md`.
3. **No accuracy claims without measurement.** Use the evaluation scripts; state the dataset.
4. **Synthetic data only** in tests, fixtures, screenshots and issues.
5. **Security-sensitive changes** (auth, RBAC, SSRF, privacy policy, AI layer) need tests in `tests/security/`.

## Development setup

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
```

```bash
cd apps/web && npm ci
```

Run the full check suite before opening a pull request:

```bash
ruff check . && ruff format --check . && mypy && pytest && bandit -q -c pyproject.toml -r shared engine modules integrations workers apps/api
```

```bash
cd apps/web && npm run typecheck && npm run lint && npm test && npm run build
```

## Adding a source adapter

Follow [`docs/writing-source-adapters.md`](docs/writing-source-adapters.md). In short:

- subclass `SourceAdapter`, fill in **all** `SourceMetadata` fields (licence, restrictions, rate limit, fields,
  reliability with a justification in the PR description);
- prefer official APIs and registries; never scrape where terms forbid it; respect robots.txt for web content;
- declare every attribute you emit in `meta.fields` (undeclared fields are dropped automatically);
- set `requires_subject_consent` / `active_probe` where applicable;
- add respx-mocked tests for success, not-found, rate-limit and malformed responses;
- regenerate `docs/source-coverage.md` with `python scripts/generate_source_coverage.py`.

Adapters can also ship as separate packages using the `atlas_osint.sources` entry-point group.

## Database changes

Change `apps/api/atlas_api/models.py`, then generate and review a migration:

```bash
alembic -c apps/api/atlas_api/migrations/alembic.ini revision --autogenerate -m "describe change"
```

## Commits and pull requests

- Small, focused PRs with tests. Describe user-visible behaviour and any privacy/security impact.
- Update `CHANGELOG.md` (Unreleased section), `IMPLEMENTATION_STATUS.md` and docs as needed.
- CI must be green (lint, types, tests, security scans, web build, Docker build).
