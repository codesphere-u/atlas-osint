# API reference

Interactive OpenAPI documentation is served at `/api/docs` (schema: `/api/openapi.json`).

## Authentication

| Method | How |
|---|---|
| Browser session | `POST /api/v1/auth/login` sets an `HttpOnly; SameSite=Strict` cookie. Writes must send `X-Atlas-CSRF: 1`. |
| Bearer token | `Authorization: Bearer <access_token>` from the login response (60 min). |
| API key | `Authorization: Bearer atl_…` (create under Administration → API keys; shown once; expires). |

Roles: **admin** (everything), **analyst** (create/verify/delete own investigations, export), **viewer** (read all,
export), **auditor** (read all, audit log). Rate limits: 120 requests/min per credential, 10/min for public
endpoints (login, privacy requests) – configurable.

## Endpoints

| Method & path | Permission | Purpose |
|---|---|---|
| `POST /api/v1/auth/login` · `POST /api/v1/auth/logout` · `GET /api/v1/auth/me` | – / any | Session |
| `GET/POST /api/v1/auth/api-keys` · `DELETE /api/v1/auth/api-keys/{id}` | any | Personal API keys |
| `POST /api/v1/investigations` | investigation:create | Create (and run) an investigation (`tlp`, `case_id` optional) |
| `GET /api/v1/investigations?q=&status=&subject_type=&mine=&limit=&offset=` | read | List/search (`X-Total-Count`); rows include TLP, risk level, grade, monitoring |
| `GET /api/v1/investigations/stats` | read | Dashboard statistics (activity by day, risk levels, grades, recent changes, attention list) |
| `PATCH /api/v1/investigations/{id}` | owner | Title, TLP, case |
| `POST /api/v1/investigations/{id}/pivot` | owner | Start a child investigation from a linked identifier (inherits authorisation; joins/creates a case) |
| `PUT /api/v1/investigations/{id}/monitoring` | owner | `{"interval_hours": 6\|24\|72\|168\|720\|null}` – organisations and infrastructure only |
| `GET /api/v1/investigations/{id}/assessment` | read | Exposure scorecard, risk highlights, latest change set, run history |
| `POST /api/v1/investigations/{id}/findings/bulk` | owner | Verify / reject / reset up to 500 findings at once |
| `GET /api/v1/investigations/{id}` | read | Detail with coverage & module summary |
| `GET /api/v1/investigations/{id}/progress` | read | Live collection progress |
| `POST /api/v1/investigations/{id}/run` | owner | Re-run collection (analyst decisions preserved) |
| `GET /api/v1/investigations/{id}/findings?classification=&source=&module=&finding_type=&min_score=&q=` | read | Findings with provenance |
| `PATCH /api/v1/investigations/{id}/findings/{fid}` | owner | Verify / reject / reset (+ note) → re-scoring |
| `GET /api/v1/investigations/{id}/graph?min_confidence=` | read | Entities, relationships, collisions, contradictions |
| `GET /api/v1/investigations/{id}/timeline` | read | Chronological evidence |
| `GET/POST /api/v1/investigations/{id}/analysis?use_ai=` | read / owner | Analysis; regenerate (optionally with AI) |
| `GET/POST /api/v1/investigations/{id}/notes` | read / owner | Analyst notes |
| `GET /api/v1/investigations/{id}/report?format=pdf\|html\|json\|csv\|stix` | report:export | Export with TLP marking (audited) |
| `DELETE /api/v1/investigations/{id}` | owner | Permanent deletion (audited) |
| `GET/POST /api/v1/cases` · `GET/PATCH/DELETE /api/v1/cases/{id}` | read / investigation:create | Cases (deleting a case unlinks, never deletes, its investigations) |
| `GET /api/v1/cases/{id}/graph` · `GET …/timeline` | read | Merged entity graph and timeline across the case |
| `GET /api/v1/cases/{id}/export?format=stix\|json` | report:export | Case-level STIX 2.1 bundle or JSON (audited) |
| `GET /api/v1/sources` · `GET /api/v1/sources/coverage` | source:read | Adapter metadata, health, coverage matrix |
| `PATCH /api/v1/sources/{name}` | admin | Enable/disable, minimum role |
| `POST /api/v1/privacy/requests` | public | Data-subject opt-out / correction / deletion request |
| `GET /api/v1/privacy/requests` · `POST …/{id}/resolve` | admin | Review requests (approve → suppression / purge) |
| `GET/POST /api/v1/admin/users` · `PATCH …/{id}` | admin | User management |
| `GET /api/v1/admin/audit?action=&actor_id=` | admin, auditor | Audit trail |
| `POST /api/v1/admin/retention/run` · `GET /api/v1/admin/system` | admin | Retention purge, configuration status |
| `GET /api/v1/meta` · `GET /healthz` · `GET /readyz` | public | Metadata, liveness, readiness |

## Creating an investigation

```bash
curl -sX POST https://atlas.example.org/api/v1/investigations -H "Authorization: Bearer $ATLAS_KEY" -H "Content-Type: application/json" -d '{"title":"Supplier check","subject_type":"organization","subject":"Example Corp","purpose":"Supplier due diligence before contract signature.","legal_basis":"legitimate_interest","attestation":true}'
```

Validation errors return `422` with `detail.authorization` listing unmet authorisation requirements; identifiers
under an approved opt-out return `451`.

## Pivoting

```bash
curl -sX POST https://atlas.example.org/api/v1/investigations/$ID/pivot -H "Authorization: Bearer $ATLAS_KEY" -H "Content-Type: application/json" -d '{"subject_type":"domain","subject":"example.net","covered_by_authorization":true}'
```

`covered_by_authorization` must be `true`: the analyst confirms the new identifier falls under the original
authorisation. Pivots to individuals are evaluated against the consent rules again and are refused without a
consent-based legal basis.

## STIX 2.1 export

`format=stix` returns a bundle containing an ATLAS `identity` (system); SCOs with spec-defined deterministic IDs
(`domain-name`, `ipv4-addr`, `ipv6-addr`, `email-addr`, `url`, `user-account`); `identity` objects
(`organization` / `individual`) for resolved organisations and people; `relationship` objects (`related-to`, with
the ATLAS relationship type, evidence kind, rationale and confidence in the description); one `note` per finding
with its classification, external reference (source URL and SHA-256 of the raw response) and links to the objects
it supports; and a `report` that references everything. The official OASIS TLP 2.0 `marking-definition` is
embedded and applied to every object. Bundles validate with `stix2.parse(..., allow_custom=False)`, which is
part of the test suite.
