# Deployment guide

## Requirements

- Docker Engine 24+ with Compose v2, 2 vCPU / 4 GB RAM minimum.
- A hostname pointing at the server (for automatic TLS), or `localhost` for local testing.
- Outbound HTTPS to the sources you enable (see `docs/source-coverage.md`) and DNS (UDP/TCP 53).

## Services

| Service | Image | Role |
|---|---|---|
| `caddy` | caddy:2-alpine | TLS termination (ACME or local CA), HSTS, routing; the only published ports |
| `web` | built from `docker/web.Dockerfile` | Next.js standalone server (non-root, read-only) |
| `api` | built from `docker/api.Dockerfile` | FastAPI; applies migrations on start; refuses insecure production config |
| `worker` | same image as `api` | Celery worker + beat (investigations, 6-hourly retention purge) |
| `postgres` | postgres:16-alpine | Primary database (internal network only) |
| `redis` | redis:7-alpine | Broker and distributed rate-limit store (password, no persistence) |

`postgres`, `redis` and `web` live on an `internal` network with no internet access; only `api`, `worker` and
`caddy` can reach the outside.

## Install

```bash
git clone https://github.com/codesphere-u/atlas-osint.git && cd atlas-osint && cp .env.example .env
```

```bash
docker compose build api && docker compose run --rm --no-deps api atlas generate-keys
```

Edit `.env`: paste the three generated keys; set strong `POSTGRES_PASSWORD` and `REDIS_PASSWORD`; set
`ATLAS_DOMAIN`; set `ATLAS_BOOTSTRAP_ADMIN_EMAIL` and `ATLAS_BOOTSTRAP_ADMIN_PASSWORD` (≥ 12 characters, mixed
classes). Then start everything:

```bash
docker compose up -d --build
```

```bash
docker compose ps
```

Sign in at `https://<ATLAS_DOMAIN>` and remove `ATLAS_BOOTSTRAP_ADMIN_PASSWORD` from `.env` afterwards.

## Configuration reference

All settings are environment variables prefixed `ATLAS_` (see `shared/config.py` and `.env.example`). Important ones:

| Variable | Default | Notes |
|---|---|---|
| `ATLAS_ENV` | development | `production` enforces key, TLS-cookie and PostgreSQL checks |
| `ATLAS_SECRET_KEY` / `ATLAS_ENCRYPTION_KEY` / `ATLAS_HASH_KEY` | – | Required in production; **back up the encryption key** |
| `ATLAS_TASK_BACKEND` | inline | `celery` in Compose |
| `ATLAS_REQUIRE_CONSENT_FOR_INDIVIDUALS` | true | Disabling this is a policy decision of the operator and should be documented |
| `ATLAS_DEFAULT_RETENTION_DAYS` / `ATLAS_MAX_RETENTION_DAYS` | 90 / 365 | |
| `ATLAS_AI_PROVIDER` | none | `anthropic` (with `ATLAS_ANTHROPIC_API_KEY`, model `ATLAS_AI_MODEL`, default `claude-opus-5-5`) or `openai_compatible` |
| `ATLAS_API_RATE_LIMIT_PER_MINUTE` / `ATLAS_PUBLIC_RATE_LIMIT_PER_MINUTE` | 120 / 10 | Redis-backed when `ATLAS_REDIS_URL` is set |
| `ATLAS_HTTP_PIN_DNS` | true | Automatically disabled behind an egress proxy (proxy must block private ranges) |
| Source credentials | – | `ATLAS_GITHUB_TOKEN`, `ATLAS_HIBP_API_KEY`, `ATLAS_COMPANIES_HOUSE_API_KEY`, `ATLAS_OPENCORPORATES_API_TOKEN`, `ATLAS_NUMVERIFY_API_KEY`, `ATLAS_SEC_EDGAR_USER_AGENT` |

## Operations

```bash
docker compose exec api atlas create-user analyst@example.org --role analyst
```

```bash
docker compose exec api atlas retention
```

```bash
docker compose exec postgres pg_dump -U atlas -Fc atlas > atlas-$(date +%F).dump
```

- **Backups**: database dumps contain only ciphertext for sensitive columns, but still store them encrypted. Keep
  the encryption key separately; without it backups cannot be read.
- **Encryption at rest**: application-level Fernet encryption covers sensitive columns; also enable volume/disk
  encryption for `pgdata`.
- **Upgrades**: `git pull && docker compose up -d --build` – migrations run automatically on API start.
- **Logs**: JSON on stdout (`docker compose logs -f api worker`); secrets are redacted.
- **Health**: `/healthz` (liveness), `/readyz` (database); every container has a health check.

## Single-node without Docker (development)

```bash
pip install -e ".[dev]" && uvicorn atlas_api.main:app --port 8000
```

```bash
cd apps/web && npm ci && npm run build && ATLAS_API_URL=http://localhost:8000 npm start
```

SQLite and the inline task backend are used by default; do not use this mode in production.

## Verified

The Compose stack in this repository was built and started end to end (PostgreSQL migration, Celery worker
executing an investigation, PDF export, HTTPS via Caddy with HSTS and `Secure` cookies) on 2026-11-26.
