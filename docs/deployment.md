# Deployment guide

ATLAS runs as a Docker Compose stack on one Linux server. This guide takes a fresh server to a verified,
backed-up production installation in about 15 minutes. Every step was run end to end (see [Verified](#verified)).

## 1. What you need

| | Minimum | Notes |
|---|---|---|
| Server | 2 vCPU, 4 GB RAM, 40 GB SSD, Ubuntu 24.04 / Debian 12 (any Linux with Docker works) | The stack idles at ~400 MB RAM; investigations use the worker's 1.5 GB limit |
| Docker | Engine 24+ with Compose v2 | `curl -fsSL https://get.docker.com \| sh` installs both |
| Hostname | A DNS `A` (and optionally `AAAA`) record pointing at the server, e.g. `atlas.example.org` | Needed for the automatic Let's Encrypt certificate |
| Network | Inbound TCP 80 and 443; outbound HTTPS (sources) and DNS | Use `ATLAS_DNS_RESOLVER=doh` if outbound port 53 is filtered |
| Tools on the server | `git`, `openssl`, `curl` | Present on standard images |

## 2. Prepare the server

```bash
sudo apt-get update && sudo apt-get install -y git curl openssl ufw && curl -fsSL https://get.docker.com | sudo sh
```

```bash
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw --force enable
```

Docker publishes ports past `ufw`, so the stack is built to publish only Caddy's 80/443; PostgreSQL, Redis, the
API and the web app are on an internal network with no published ports.

## 3. Install

```bash
git clone https://github.com/codesphere-u/atlas-osint.git && cd atlas-osint
```

```bash
./deploy/setup.sh --domain atlas.example.org --admin-email you@example.org
```

`setup.sh` writes `.env` (mode 600) with freshly generated secrets – application key, Fernet encryption key, hash
key, PostgreSQL and Redis passwords – and a random first-administrator password that it prints **once**. It refuses
to overwrite an existing `.env`, because a new encryption key would make existing data unreadable. Options:
`--allowed-ips "203.0.113.0/24"` restricts access (see [Access control](#access-control)); `--registry v0.2.0`
uses published images instead of building (see [Published images](#published-images)).

**Store `.env` in your password manager now.** `ATLAS_ENCRYPTION_KEY` and `ATLAS_HASH_KEY` are needed to read the
database and every backup.

```bash
sudo docker compose up -d --build
```

```bash
sudo ./deploy/check.sh
```

`check.sh` waits for all seven containers to be healthy, then verifies the TLS certificate, readiness, the security
headers, the HTTP → HTTPS redirect, configuration hygiene and that a backup exists. It exits non-zero on any
failure and prints the command to investigate it.

## 4. First sign-in

1. Open `https://atlas.example.org` and sign in with the email and password `setup.sh` printed.
2. Remove the bootstrap password from `.env` (the account stays):

   ```bash
   sudo ./deploy/check.sh --clear-bootstrap-password
   ```

3. Create analyst accounts under **Administration → Users** (or `sudo docker compose exec api atlas create-user
   analyst@example.org --role analyst`).
4. Add the source API keys you have to `.env` (see the configuration reference) and apply them with
   `sudo docker compose up -d`.
5. Publish a privacy notice that points data subjects to `https://atlas.example.org/privacy`.

## Access control

ATLAS has no MFA or SSO yet. Because it holds investigation data about third parties, restrict who can reach it
when you can:

- **IP allow-list** – set `ATLAS_ALLOWED_IPS="203.0.113.0/24 198.51.100.7/32"` in `.env` and run
  `sudo docker compose up -d caddy`. Other addresses get `403`; the privacy-request page and its API stay public so
  data subjects can always exercise their rights.
- **VPN / zero-trust access** – alternatively put the hostname behind your VPN, Tailscale or an identity-aware proxy.
- Accounts lock for 15 minutes after five failed sign-ins; locked-out or forgotten passwords are reset with
  `sudo docker compose exec api atlas reset-password user@example.org` (audited).

If ATLAS sits behind another proxy or CDN, Caddy sees that proxy's address: configure the allow-list there instead.

## Backups and restore

The `backup` service writes a compressed `pg_dump` to `./backups` every `ATLAS_BACKUP_INTERVAL_HOURS` (24) and
deletes dumps older than `ATLAS_BACKUP_KEEP_DAYS` (14). Take one on demand with `sudo ./deploy/backup.sh`.

**Copy `./backups` off the server** (restic, rsync, object storage, your provider's volume snapshots). Dumps contain
mostly ciphertext but are still personal data: store them encrypted and with access control. Keep the keys from
`.env` separately – a backup is only usable with the `ATLAS_ENCRYPTION_KEY` and `ATLAS_HASH_KEY` it was made with.

Restore (a safety dump of the current database is taken first):

```bash
sudo ./deploy/restore.sh backups/atlas-20261127T020000Z.dump
```

Test a restore on a spare server before you need it: copy the repository, `.env` and a dump, run `docker compose up
-d --build`, then `restore.sh`.

## Upgrades

```bash
sudo ./deploy/upgrade.sh
```

The script takes a `pre-upgrade` backup, fast-forwards the checkout, rebuilds the images, restarts the stack
(database migrations run automatically on API start) and runs `check.sh`. Read `CHANGELOG.md` before upgrading.
With published images use `sudo ./deploy/upgrade.sh v0.3.0`.

**Rollback:** migrations are forward-only. Restore the `pre-upgrade` backup with `restore.sh`, then run the previous
version (`git checkout <previous tag>` and `docker compose up -d --build`, or set `ATLAS_VERSION` back).

## Published images

Pushing a tag `vX.Y.Z` runs `.github/workflows/release.yml`, which publishes
`ghcr.io/codesphere-u/atlas-osint/api:vX.Y.Z` and `…/web:vX.Y.Z` and creates a GitHub release. New GHCR packages
are private: make them public under the repository's **Packages** settings, or run `docker login ghcr.io` on the
server with a token that has `read:packages`. Then:

```bash
./deploy/setup.sh --domain atlas.example.org --admin-email you@example.org --registry v0.2.0
```

```bash
sudo docker compose pull && sudo docker compose up -d --no-build
```

## Monitoring

- **Uptime:** point an external monitor at `https://atlas.example.org/healthz` (liveness) and `/readyz` (database).
- **Container health:** every container has a health check; `sudo docker compose ps` shows the state and
  `sudo ./deploy/check.sh` can run from cron for a daily report.
- **Logs:** JSON on stdout, rotated by Docker (10 MB × 5 files per container): `sudo docker compose logs -f api
  worker caddy`. Secrets are redacted.
- **Backups:** `sudo docker compose logs backup` shows `backup_completed` / `backup_failed` events.
- **Source health:** the Sources page shows per-source success rates from recent investigations.

## Production checklist

- [ ] DNS record points at the server; ports 80/443 open, nothing else published
- [ ] `.env` created by `setup.sh`, mode 600, copy in a password manager
- [ ] `check.sh` passes
- [ ] Bootstrap password cleared after first sign-in
- [ ] Access restricted (`ATLAS_ALLOWED_IPS`, VPN or identity-aware proxy) – recommended while ATLAS has no MFA
- [ ] Backups copied off the server automatically; a restore tested
- [ ] External uptime monitor on `/healthz`
- [ ] Retention period (`ATLAS_DEFAULT_RETENTION_DAYS`) set to the shortest that meets your purpose
- [ ] Privacy notice published; DPIA done where your law requires it (see `PRIVACY.md`)
- [ ] Source API keys added and their terms reviewed (OpenSanctions licence for commercial use)
- [ ] Unattended OS security updates enabled (`sudo apt-get install -y unattended-upgrades`)

## Services

| Service | Image | Role |
|---|---|---|
| `caddy` | caddy:2-alpine | TLS (ACME or local CA), HSTS, optional IP allow-list, routing; the only published ports |
| `web` | `docker/web.Dockerfile` (Node 26) | Next.js 16 standalone server (non-root, read-only filesystem) |
| `api` | `docker/api.Dockerfile` (Python 3.12) | FastAPI; applies migrations on start; refuses insecure production config |
| `worker` | same image as `api` | Celery worker + beat (investigations, monitoring every 10 min, 6-hourly retention purge) |
| `postgres` | postgres:16-alpine | Primary database (internal network only) |
| `redis` | redis:7-alpine | Broker and distributed rate-limit store (password, no persistence) |
| `backup` | postgres:16-alpine | Scheduled `pg_dump` into `./backups` |

All application containers run as non-root users with read-only root filesystems, all capabilities dropped,
`no-new-privileges`, memory limits and rotated logs.

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
| `ATLAS_DNS_RESOLVER` / `ATLAS_DOH_URL` | system / `https://dns.google/resolve` | `doh` queries a DNS-over-HTTPS JSON endpoint (Google or Cloudflare format) for networks that filter or rewrite DNS; without it, email-security checks can wrongly report missing SPF/DMARC |
| `ATLAS_INLINE_SCHEDULER` / `ATLAS_SCHEDULER_INTERVAL_SECONDS` | true / 60 | With the inline backend, a thread in the API runs due monitors and the hourly purge. Run only **one** API replica with it enabled; use Celery beat for multi-node |
| `ATLAS_FEDIVERSE_INSTANCES` | mastodon.social, … | Comma-separated Mastodon instances queried for exact handles |
| `ATLAS_LOOKALIKE_MAX_CANDIDATES` | 150 | Upper bound on generated lookalike domains resolved per investigation |
| `ATLAS_ALLOWED_IPS` | everyone | Space-separated CIDRs (quoted) allowed to reach the application at Caddy; the privacy-request page stays public |
| `ATLAS_IMAGE_REPO` / `ATLAS_VERSION` | local build / latest | `ghcr.io/codesphere-u/atlas-osint` + a release tag to run published images |
| `ATLAS_BACKUP_DIR` / `ATLAS_BACKUP_INTERVAL_HOURS` / `ATLAS_BACKUP_KEEP_DAYS` | ./backups / 24 / 14 | Scheduled `pg_dump` backups |
| `ATLAS_HTTP_PORT` / `ATLAS_HTTPS_PORT` | 80 / 443 | Published ports; ACME needs both reachable from the internet |
| `ATLAS_MEM_API`, `ATLAS_MEM_WORKER`, `ATLAS_MEM_POSTGRES`, `ATLAS_MEM_WEB`, `ATLAS_MEM_REDIS`, `ATLAS_MEM_CADDY` | 1g, 1536m, 1g, 512m, 256m, 256m | Container memory limits |
| Source credentials | – | `ATLAS_GITHUB_TOKEN`, `ATLAS_HIBP_API_KEY`, `ATLAS_COMPANIES_HOUSE_API_KEY`, `ATLAS_OPENCORPORATES_API_TOKEN`, `ATLAS_NUMVERIFY_API_KEY`, `ATLAS_SEC_EDGAR_USER_AGENT`, `ATLAS_OPENSANCTIONS_API_KEY` (sanctions/PEP screening; check the licence for your use), `ATLAS_CERTSPOTTER_API_KEY` (optional, higher quota) |

## Without Docker (development only)

```bash
pip install -e ".[dev]" && uvicorn atlas_api.main:app --port 8000
```

```bash
cd apps/web && npm ci && npm run build && ATLAS_API_URL=http://localhost:8000 npm start
```

SQLite and the inline task backend are used by default; do not use this mode in production.

## Verified

- v0.1: the Compose stack was built and started end to end (PostgreSQL migration, Celery worker executing an
  investigation, PDF export, HTTPS via Caddy with HSTS and `Secure` cookies) on 2026-11-26.
- v0.2: migration `0002` was applied to a populated database (upgrade, downgrade, `alembic check`), and the full
  UI flow ran against live sources with the inline backend and scheduler on 2026-11-27.
- Production tooling (2026-11-27, Docker 29, images built from this repository): `setup.sh` → `docker compose up`
  → `check.sh` passed from an empty host; sign-in over HTTPS through Caddy with `Secure; HttpOnly; SameSite=Strict`
  cookies; an investigation executed by the Celery worker; PDF export; all pages rendered with 0 console/CSP errors;
  `--clear-bootstrap-password`; `atlas reset-password` inside the container; backup → delete → `restore.sh`
  brought the data back; the IP allow-list returned 403 for other addresses while the privacy page, its assets and
  API stayed reachable. The CI `docker` job repeats setup → up → check → sign-in on every push. Not verifiable in
  that environment: a public Let's Encrypt certificate (needs a real hostname) and source collection from inside
  containers (the sandbox has no container egress; sources reported *unavailable*, which ATLAS records correctly).
