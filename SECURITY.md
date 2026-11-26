# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ |

## Reporting a vulnerability

Please **do not open public issues** for security problems. Use GitHub's private vulnerability reporting
("Security" tab → "Report a vulnerability") on this repository. Include affected version/commit, a description,
reproduction steps and impact. We aim to acknowledge within 3 working days and to ship a fix or mitigation for
critical issues within 30 days, and we will credit reporters who wish to be credited.

Reports of ways to **misuse ATLAS against people** (e.g. bypassing consent or privacy controls) are treated as
security vulnerabilities.

## Security architecture (summary)

Details, threat model and audit findings: [`docs/security-audit.md`](docs/security-audit.md).

- **Authentication**: Argon2id password hashing, login lockout, constant-time failure path, HS256 JWT (60 min) in an
  `HttpOnly; SameSite=Strict; Secure` cookie, CSRF header required for cookie-authenticated writes, hashed and
  expiring API keys (`atl_…`, shown once).
- **Authorisation**: RBAC (admin, analyst, viewer, auditor) evaluated from the database on every request (token role
  claims are not trusted), investigation ownership checks, per-source minimum role.
- **Lawful-use controls**: authorisation record + attestation per investigation, consent enforcement for individuals,
  scope enforcement for active requests, opt-out suppression.
- **Data protection**: Fernet (AES-128-CBC + HMAC-SHA256) encryption of identifiers, findings, results, notes and
  privacy-request contact data at rest; keyed HMAC-SHA256 for lookups and audit logs; retention purge; secrets
  redacted from logs.
- **Outbound requests**: SSRF validation of every hop (scheme, port, credentials, private/reserved/metadata
  addresses, IPv6 transition forms), manual redirect handling, DNS pinning, response size limits, timeouts,
  per-source rate limits, robots.txt for document fetches.
- **AI layer**: untrusted content is sanitised, injection patterns are neutralised and flagged, data is wrapped in a
  nonce envelope, output is schema-constrained and every statement is validated against cited findings.
- **Web**: strict security headers and CSP, no third-party origins, HTML reports served with `default-src 'none'`.
- **Deployment**: TLS via Caddy, non-root read-only containers with all capabilities dropped, internal-only network
  for data services, production start refused with insecure configuration.

## Operator responsibilities

- Generate unique `ATLAS_SECRET_KEY`, `ATLAS_ENCRYPTION_KEY` and `ATLAS_HASH_KEY`; store them in a secret manager and
  back up the encryption key (data is unrecoverable without it).
- Enable full-disk / volume encryption for the PostgreSQL volume and backups.
- When ATLAS runs behind an **egress HTTP proxy**, the proxy resolves DNS, so DNS pinning is disabled automatically;
  configure the proxy to block private and link-local destinations.
- Keep images and dependencies updated (CI runs `pip-audit`, `npm audit` and Bandit).
