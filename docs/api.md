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
| `POST /api/v1/investigations` | investigation:create | Create (and run) an investigation |
| `GET /api/v1/investigations?q=&status=&subject_type=&mine=&limit=&offset=` | read | List/search (`X-Total-Count`) |
| `GET /api/v1/investigations/stats` | read | Dashboard statistics |
| `GET /api/v1/investigations/{id}` | read | Detail with coverage & module summary |
| `GET /api/v1/investigations/{id}/progress` | read | Live collection progress |
| `POST /api/v1/investigations/{id}/run` | owner | Re-run collection (analyst decisions preserved) |
| `GET /api/v1/investigations/{id}/findings?classification=&source=&module=&finding_type=&min_score=&q=` | read | Findings with provenance |
| `PATCH /api/v1/investigations/{id}/findings/{fid}` | owner | Verify / reject / reset (+ note) → re-scoring |
| `GET /api/v1/investigations/{id}/graph?min_confidence=` | read | Entities, relationships, collisions, contradictions |
| `GET /api/v1/investigations/{id}/timeline` | read | Chronological evidence |
| `GET/POST /api/v1/investigations/{id}/analysis?use_ai=` | read / owner | Analysis; regenerate (optionally with AI) |
| `GET/POST /api/v1/investigations/{id}/notes` | read / owner | Analyst notes |
| `GET /api/v1/investigations/{id}/report?format=pdf\|html\|json\|csv` | report:export | Export (audited) |
| `DELETE /api/v1/investigations/{id}` | owner | Permanent deletion (audited) |
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
