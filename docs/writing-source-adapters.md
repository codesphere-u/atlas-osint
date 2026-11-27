# Writing a source adapter

A source adapter queries **one** information source and turns its response into `Finding` objects. Adapters are
plugins: the core engine, the UI, reports and the coverage document all read the adapter's metadata, so adding a
source never requires changes to the engine.

## 1. Check that the source is acceptable

- Public information only, accessible without circumventing authentication, paywalls or technical measures.
- Prefer, in order: official APIs → public registries → licensed datasets → public web pages (robots.txt honoured
  and terms permitting automated access).
- No breached data, credential databases, password-reset/sign-up probing, private messaging, or anything that
  identifies private subscribers or reveals private addresses, precise locations, financial or sensitive data.

## 2. Implement the adapter

```python
from integrations.sources.base import (
    CollectionContext,
    LegalInfo,
    RateLimit,
    SourceAdapter,
    SourceError,
    SourceMetadata,
)
from shared.types import AccessMethod, AdapterStatus, Identifier, IdentifierType, Reliability, SourceCategory


class ExampleRegistryAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="example_registry",  # stable slug
        display_name="Example Business Registry",
        description="Official register of companies in Exampleland.",
        category=SourceCategory.PUBLIC_RECORDS,
        input_types=[IdentifierType.ORGANIZATION],
        access_method=AccessMethod.OFFICIAL_API,
        homepage="https://registry.example/api-docs",
        rate_limit=RateLimit(requests=5, per_seconds=1),
        legal=LegalInfo(
            license="Open Government Licence",
            terms_url="https://registry.example/terms",
            restrictions="Company data only; officers' personal data is not collected.",
        ),
        fields=["legal_name", "registry_id", "status", "incorporation_date"],  # data-minimisation contract
        freshness="daily",
        reliability=Reliability.A,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext):
        resp = await self.fetch(ctx, "https://registry.example/api/search", params={"q": identifier.value})
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        out = []
        for c in resp.json()["items"]:
            out.append(
                self.finding(
                    module="public_records",
                    subject=identifier,
                    finding_type="company_registration",
                    title=f"{c['name']} ({c['number']})",
                    description=f"Company '{c['name']}', status {c['status']}.",
                    url=f"https://registry.example/company/{c['number']}",
                    attributes={"legal_name": c["name"], "registry_id": c["number"], "status": c["status"]},
                    raw=resp.content,  # hashed for reproducibility
                    entity_hint=f"organization:exreg:{c['number']}",  # persistent identifier -> entity key
                    entity_kind="organization",
                    claim_key=f"org.exreg:{c['number']}",  # same claim from other sources corroborates
                )
            )
        return out
```

### What the base class does for you

- `run()` checks input type, credentials (`configuration_status`), consent (`requires_subject_consent`) and scope
  (`active_probe` for anything that sends traffic to the target; `requires_authorized_scope` for passive lookups
  that are only legitimate for assets the requester may assess, such as lookalike discovery), applies a timeout and converts every failure into an `AdapterResult` status – an adapter can never
  crash an investigation.
- `fetch(ctx, url, method="GET", **kwargs)` goes through the SSRF-safe client (any method; e.g. `POST` for match APIs), enforces the declared rate limit and maps 401/403/429/5xx to statuses.
- `finding()` builds the citation, truncates long text, hashes the raw response, drops empty attributes.
- Attributes not listed in `meta.fields` are removed and the finding is flagged `undeclared_fields_dropped`.
- After collection the privacy policy filter runs regardless of what the adapter emits.

### Guidelines

- **Entity hints** must be built from persistent identifiers, never from names alone.
- Use `MatchType.SIMILAR` whenever the returned record does not match the query exactly.
- Use `EvidenceKind.INFERENCE` for anything the source does not state directly.
- Keep `excerpt` short and factual; free text is treated as untrusted by the AI layer.
- Choose the reliability grade conservatively and justify it in the pull request.
- Credentials: add an optional `SecretStr` field to `shared/config.Settings` and list it in
  `AuthRequirement.settings_fields`.

## 3. Register it

Built-in: add the class to `integrations/sources/builtin.py`. External package:

```toml
[project.entry-points."atlas_osint.sources"]
example_registry = "my_package.example:ExampleRegistryAdapter"
```

## 4. Test it

Add respx-mocked tests (see `tests/unit/test_adapters.py`) for success, not found, rate limit (429), malformed
responses and any consent/scope behaviour, then regenerate the coverage document:

```bash
python scripts/generate_source_coverage.py
```
