# Security audit

Scope: ATLAS OSINT 0.1.0 (Phase 10), re-reviewed for 0.2.0 (see [v0.2 review](#v02-review)) – backend, engine, adapters, AI layer, web app, Docker deployment. Method: threat
modelling (STRIDE + misuse cases), manual code review of security-relevant paths, automated tests
(`tests/security/`, 68 tests), static analysis (Bandit, Ruff security rules, mypy), dependency audits
(`pip-audit`, `npm audit`) and an end-to-end run of the Docker Compose stack. Performed by the authors – **this is
not an independent third-party penetration test**; one is recommended before high-risk deployments.

## Assets and adversaries

| Asset | Why it matters |
|---|---|
| Investigation data (identifiers, findings, notes) | Personal data about third parties |
| Credentials & keys (passwords, API keys, encryption key) | Account takeover, decryption of data |
| Platform capability itself | Could be misused to profile people |
| Hosting network | SSRF could reach internal services / cloud metadata |

| Adversary | Examples |
|---|---|
| External attacker | Credential stuffing, injection, SSRF via crafted identifiers or redirects |
| Malicious source content | Prompt injection in profile bios / web pages, XSS payloads, CSV formula injection, oversized responses |
| Malicious or careless insider | Analyst profiling a person without basis, reading colleagues' investigations, exporting data |

## Controls and verification

| Threat | Control | Verified by |
|---|---|---|
| Spoofing – stolen/forged tokens | HS256 JWT with `exp`/`iat`/`typ`, algorithm pinned (no `none`), role re-read from DB; Argon2id; lockout after 5 failures; equal responses for unknown user / wrong password | `test_auth.py` (expired, forged, `alg=none`, role-claim escalation, lockout, enumeration) |
| CSRF | `SameSite=Strict` cookie + mandatory `X-Atlas-CSRF` header for cookie-authenticated writes; CORS allow-list | `test_cookie_session_requires_csrf_header_for_writes` |
| API key theft | Keys hashed (HMAC), prefix lookup, expiry, revocation, shown once, keys cannot mint keys | `test_api_key_lifecycle` |
| Elevation of privilege | RBAC permission checks on every route; ownership checks (others' investigations return 404); admin cannot self-demote; per-source min role | `test_authorization.py` |
| Tampering / injection | Pydantic strict schemas (`extra="forbid"`), identifier normalisers, control-character rejection, SQLAlchemy parameterised queries, body size limit (413) | `test_data_protection.py` |
| XSS | React escaping; Jinja2 autoescape in HTML reports; reports served with `default-src 'none'` CSP; only `http(s)` links rendered | `test_html_report_escapes_content_and_has_sections`, `format.test.ts` |
| CSV formula injection | Cells starting with `= + - @` are prefixed | `test_csv_report_neutralises_formula_injection` |
| SSRF | Scheme/port allow-list, no credentials in URLs, blocks loopback/RFC1918/link-local/CGNAT/multicast/reserved/ULA/IPv4-mapped/6to4/Teredo/metadata hostnames, re-validation on every redirect, DNS pinning with SNI preserved, size limits, timeouts | `test_ssrf.py` (14 address classes, redirect to private IP, pinning, size limit) |
| Prompt injection | Sanitisation (invisible/bidi characters, control chars), pattern neutralisation & flags, nonce envelope with escaped `<>`, JSON-schema output, citation validation, confirmed-claim downgrade, rejected findings withheld, deterministic fallback | `test_prompt_injection.py` |
| Information disclosure – data at rest | Fernet encryption of identifiers, findings, results, notes, privacy-request PII; keyed hashes for lookup; audit log without raw identifiers | `test_sensitive_columns_are_encrypted_at_rest`, `test_audit_trail_records_actions_without_identifiers`; verified on PostgreSQL in Compose |
| Information disclosure – logs | Secret redaction in log formatter; `SecretStr` settings | `test_secrets_are_redacted_in_logs`, `test_settings_repr_hides_secrets` |
| Denial of service | Per-credential and per-IP rate limits (Redis-backed), stricter public limits, response size caps, adapter timeouts, bounded concurrency | `test_rate_limiter_blocks_excess`, `test_public_endpoint_rate_limited`, `test_rotating_bogus_tokens_hit_per_ip_limit` |
| Insecure deployment | Production start refused without strong keys / TLS cookies / PostgreSQL; non-root read-only containers, all capabilities dropped, `no-new-privileges`; data services on an internal network; TLS + HSTS via Caddy | `test_production_configuration_is_validated`; Compose run |
| Misuse against individuals | Attestation, consent/self legal basis for individuals, consent-gated breach lookups, scope-gated active probes and subdomain listings, data-minimisation filter, opt-out suppression (incl. URLs on opted-out domains), retention purge, deletion workflow, full audit | `test_lawful_use.py`, `test_policy.py`, adapter tests |
| Supply chain | Pinned web dependencies with lockfile; `pip-audit`, `npm audit`, Bandit in CI | CI `security` job |

## Findings during this audit

| ID | Severity | Finding | Status |
|---|---|---|---|
| A-01 | Medium | Per-credential API rate limiting could be bypassed by rotating random bearer tokens (each got a new bucket). | **Fixed** – additional per-IP ceiling; regression test. |
| A-02 | Medium | Opt-out of a domain did not suppress website URLs on that domain linked from profiles. | **Fixed** – URL identifiers also match their host domain; test. |
| A-03 | High (dependency) | PostCSS bundled with Next.js 15 affected by GHSA-qx2v-qp2m-jg93 and related advisories. | **Fixed** – `overrides` pinned postcss 8.5.33. Since the Next.js 16 upgrade the bundled PostCSS (8.5.23) is unaffected, so the override was removed; `npm audit` clean. |
| A-04 | Medium | Policy filter did not treat `api_key`/`access_key` attribute names as credentials. | **Fixed** – added to always-forbidden keys; test. |
| A-05 | Low | Injection detector missed forged `</untrusted_data>` tags and `SYSTEM:` prefixes. | **Fixed** – pattern extended; tests. |
| A-06 | High (Bandit B613) | Sanitiser regex contained literal bidi control characters in source ("Trojan Source"). | **Fixed** – ASCII escape sequences only. |
| A-07 | Medium (availability) | Comma-separated list settings (`ATLAS_CORS_ORIGINS`) crashed the API at start in Docker. | **Fixed** – `NoDecode` + CSV/JSON parsing; test. |

No unresolved critical or high findings remain in the reviewed scope.

## Residual risks and accepted trade-offs

| Risk | Rationale / mitigation |
|---|---|
| Access tokens cannot be revoked before expiry (60 min) | Disabling a user blocks it immediately (active flag checked per request); logout removes the cookie. Token versioning is on the roadmap. |
| Account lockout can be triggered by an attacker (DoS on a known account) | Standard trade-off; lockout is 15 minutes; rate limits restrict attempts. |
| `script-src 'unsafe-inline'` in the web CSP | Required by Next.js inline bootstrap without nonces; no third-party origins are allowed. Nonce-based CSP on the roadmap. |
| DNS pinning disabled behind an egress proxy | The proxy resolves names; operators must enforce private-range blocking at the proxy (documented). |
| Uvicorn trusts `X-Forwarded-For` from any peer in the container | The API is only reachable from Caddy on the internal network; do not publish port 8000. |
| Some providers place API keys in query strings (numverify, OpenCorporates) | Provider requirement; requests are HTTPS; keys never logged by ATLAS. |
| Insider with legitimate analyst role can still misuse data they are authorised to see | Mitigated by attestation, consent rules, ownership isolation, audit trail and retention; requires organisational oversight. |
| Name-based opt-outs only match the exact normalised name | Names are ambiguous by nature; data subjects are advised to also submit unique identifiers. |
| Self-performed audit | Independent penetration test recommended before handling high-risk data. |

## v0.2 review

Scope: the new sources, exposure scorecard, risk highlights, cases, pivots, monitoring/scheduler, TLP, STIX export,
DNS-over-HTTPS and the rebuilt UI. Method as above, plus misuse-case review of each new capability, strict STIX
validation and a full live end-to-end run of the UI.

### New capabilities and their controls

| Capability | Misuse / failure case | Control | Verified by |
|---|---|---|---|
| Pivots | Chaining from an authorised subject to unrelated people | Child inherits the authorisation record, analyst must confirm `covered_by_authorization`, consent rules for individuals are evaluated again, opt-out suppression is checked, pivots are audited | `test_pivot_creates_case_and_child` (unconfirmed → 422, person without consent → 422, viewer → 403) |
| Monitoring | Scheduled surveillance of a person | Refused for individuals in the service layer; organisations and infrastructure only; fixed intervals ≥ 6 h; runs carry the original authorisation and are audited | `test_monitoring_rules_and_scheduler` |
| Cases | Reading or attaching colleagues' investigations | Ownership checks on cases and on every investigation attached; other users get 404 | `test_case_crud_and_assignment` |
| Lookalike discovery, security.txt, MTA-STS policy, subdomain listings | Probing or enumerating infrastructure without permission | `requires_authorized_scope` on the adapter; skipped with a reason outside scope; lookalike candidates are bounded (`ATLAS_LOOKALIKE_MAX_CANDIDATES`) and only resolved, never connected to | `test_adapters_v2.py` |
| Shodan InternetDB | Turning ATLAS into a scanner | Read-only lookups of an existing passive dataset; ATLAS sends no traffic to the target | Adapter review |
| OpenSanctions screening | Treating a name match as a fact about someone | Hits are *possible* matches with score and topics; risk highlights say *requires confirmation*; name-only caps apply | `test_assessment.py` |
| Crossref publications | Attributing papers to a namesake | Exact author-name match only; ORCID required for a direct link; otherwise inference edge and name cap | `test_adapters_v2.py`, ER evaluation |
| STIX / TLP export | Sharing beyond the intended audience | TLP set per investigation/case, embedded as official OASIS marking objects on every STIX object and printed on every PDF page; exports audited | `test_stix_report_export_uses_investigation_tlp`, `test_reporting.py` |
| DoH resolver | Leaking queried domains to a third party | Opt-in (`ATLAS_DNS_RESOLVER=doh`), documented; system resolver remains the default | Config review |
| Inline scheduler | Duplicate runs with several replicas | Documented single-replica restriction; Celery beat for multi-node | Docs |

### Findings

| ID | Severity | Finding | Status |
|---|---|---|---|
| B-01 | Medium (integrity) | Change detection reported every finding of a source that was down in one run as *added* or *removed* (11 phantom changes seen live when crt.sh timed out). | **Fixed** – only sources that answered in both runs are compared; others listed as *not compared*; test. |
| B-02 | Medium (integrity) | PDF reports: body text was drawn from the right edge of the previous cell (fpdf2 `multi_cell` default `new_x=RIGHT`), so paragraphs were clipped or off-page. Present since v0.1. | **Fixed** – explicit `new_x="LMARGIN"`; pypdf layout regression test. |
| B-03 | Low (interoperability) | STIX external references without an HTTP URL had only `source_name`, which strict validators reject. | **Fixed** – a description is added; bundles validated with `allow_custom=False` in tests. |
| B-04 | Low (accuracy) | Lookalike detection counted domains with a null MX or an MX pointing at `localhost` as mail-capable. | **Fixed** – excluded; test. |
| B-05 | Low (accuracy) | InternetDB was queried with IPv6 addresses it does not cover, producing misleading "no data" results. | **Fixed** – IPv4 only. |
| B-06 | Low (accuracy) | On networks that filter DNS, email-security checks reported SPF/DMARC as missing. | **Mitigated** – DoH resolver option; documented. |
| B-07 | Low (availability) | Migration `0002` added non-null columns without server defaults and an unnamed FK (fails on populated DBs / SQLite batch mode). | **Fixed** – defaults and named FK; upgrade/downgrade tested on populated DB. |

No unresolved critical or high findings remain in the v0.2 scope. The residual risks above still apply; in
addition, InternetDB CVEs are version-based inferences and OpenSanctions use is subject to its licence.
