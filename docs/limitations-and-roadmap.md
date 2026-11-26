# Known limitations and roadmap

## Known limitations

**Coverage**
- 31 sources. Several important platforms (X/Twitter, LinkedIn, Facebook, Instagram, TikTok) are not covered: their
  terms prohibit automated collection or require paid/partner API access. ATLAS does not scrape them.
- Reddit's unauthenticated endpoint is frequently blocked (reported as *unavailable*); OAuth support is planned.
- Mastodon/fediverse handles (`user@instance`) are not yet accepted as input.
- No public-records connectors yet for most national company registries beyond the UK (Companies House), the US
  (SEC EDGAR) and global aggregators (GLEIF, OpenCorporates, Wikidata).
- Phone intelligence is limited to numbering-plan data (and optional numverify). Public business-listing
  associations for phone numbers are not implemented because no suitably licensed open source was identified.
- Email "publicly disclosed professional associations" are limited to the organisational-domain pivot; there is no
  open, licensed corpus linking emails to people that ATLAS can lawfully query.
- Historical infrastructure is limited to RDAP, CT logs and the Wayback Machine (no passive-DNS provider).
- GDELT covers only a rolling ~3-month window; GLEIF's full-text search returns loosely related entities (they are
  correctly classified as *similar* matches).
- RDAP lookups use a "last two labels" heuristic for the registrable domain, so some multi-label public suffixes
  (e.g. `example.co.uk` subdomains) may not resolve.

**Analysis**
- Confidence weights are expert-set, not learned; entity-resolution metrics come from synthetic data only.
- Contradiction detection covers a fixed set of attributes.
- The AI narrative quality depends on the configured model; validation guarantees citations and certainty levels,
  not prose quality.

**Platform**
- Access tokens are not revocable before expiry; no SSO/OIDC or MFA yet.
- Single-tenant: all users of an installation share one organisation.
- PDF reports use core fonts (Latin-1); non-Latin characters are replaced in PDF output (HTML/JSON/CSV are full
  Unicode).
- The web UI has no end-to-end test suite in CI yet (a Playwright walkthrough was run manually for this release).

## Roadmap

| Priority | Item |
|---|---|
| High | OIDC SSO + TOTP/WebAuthn MFA; token versioning for immediate revocation |
| High | Playwright end-to-end tests in CI; accessibility audit (axe) |
| High | Reddit OAuth, Mastodon/fediverse WebFinger adapter, Bluesky (AT Protocol) public profiles |
| Medium | More registries (EU BRIS/national registers, ASIC, Corporations Canada), Crossref/arXiv publications |
| Medium | Passive DNS via licensed providers; Public Suffix List for registrable-domain detection |
| Medium | Investigation sharing/teams and multi-tenancy; case export/import in STIX 2.1 |
| Medium | Nonce-based CSP; Unicode TTF fonts for PDF |
| Low | Labelled real-world evaluation set (with consent) to calibrate confidence weights |
| Low | Scheduled re-collection and change alerts for authorised infrastructure monitoring |
