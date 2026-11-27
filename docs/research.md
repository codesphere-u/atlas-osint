# Phase 1 – Survey of existing open-source OSINT tools

Purpose: learn from existing tools (capabilities, architecture, licensing, limitations) and decide what ATLAS
should do differently. Facts were checked in November 2026; licences and maintenance status change, so verify
against each repository's `LICENSE` file before reusing code. **ATLAS does not include code from any of these
projects**; where an idea is borrowed it is noted below.

## Tools reviewed

| Tool | Focus | Licence | Architecture strengths | Limitations / concerns for ATLAS's goals |
|---|---|---|---|---|
| [SpiderFoot](https://github.com/smicallef/spiderfoot) | Automated recon across 200+ modules (domains, IPs, emails, names) | MIT (upstream; some older forks show GPL-2.0) | Event-driven module bus: modules subscribe to data types and emit new ones; web UI; correlation rules (YAML) | Last tagged release 2022 (community fork *spiderfoot-ng* exists). Breadth over provenance: findings carry little confidence semantics; several modules scrape or use leaked data; aggressive pivoting can drift far beyond authorised scope. |
| [theHarvester](https://github.com/laramies/theHarvester) | Emails, subdomains, hosts from search engines & APIs | GPL-2.0 | Simple per-source modules, async collection | Flat output (lists of strings) without provenance or confidence; search-engine scraping conflicts with many ToS. |
| [OWASP Amass](https://github.com/owasp-amass/amass) | Attack-surface mapping, subdomain enumeration | Apache-2.0 | Graph database of assets, many passive data sources, careful rate handling | Infrastructure only; active techniques (brute force, zone walking) need explicit authorisation. |
| [Recon-ng](https://github.com/lanmaster53/recon-ng) | Modular recon framework (Metasploit-style) | GPL-3.0 | Marketplace of modules, workspace DB, API-key management | CLI only; modules of varying quality and legality; no evidence scoring. |
| [Sherlock](https://github.com/sherlock-project/sherlock) | Username presence on 400+ sites | MIT | Data-driven site list (JSON) with per-site detection rules | Detection by HTTP status/body heuristics produces false positives; no metadata; scraping many sites conflicts with ToS. |
| [Maigret](https://github.com/soxoj/maigret) | Sherlock successor: 3000+ sites, profile parsing, reports | MIT | Extracts profile identifiers and recursively searches them; PDF/HTML reports | Recursive pivoting on extracted personal identifiers is effectively automated dossier building on individuals; heuristic detection. |
| [WhatsMyName](https://github.com/WebBreacher/WhatsMyName) | Curated username-detection dataset | CC BY-SA 4.0 (data) | Community-maintained detection signatures, positive/negative test accounts | Dataset, not a platform; share-alike licence affects derived data. |
| [PhoneInfoga](https://github.com/sundowndev/phoneinfoga) | Phone number information | GPL-3.0 | Uses libphonenumber for normalisation; scanner plugins | README states the project is unmaintained. Relies on search-engine dorking for "footprints". |
| [holehe](https://github.com/megadose/holehe) | Whether an email is registered on sites | GPL-3.0 | Many site checks | Works by abusing **password-reset / signup flows** – explicitly excluded from ATLAS. |
| [GHunt](https://github.com/mxrch/GHunt) | Google-account OSINT | AGPL-3.0 | Deep Google API knowledge | Requires authenticated cookies; targets individuals' accounts – out of scope. |
| [IntelOwl](https://github.com/intelowlproject/IntelOwl) | Threat-intel enrichment of observables | AGPL-3.0 | Analyzer/connector plugin model, Celery workers, REST API, RBAC | Threat-intel oriented (IOCs) rather than evidence reporting about entities. |
| [OpenCTI](https://github.com/OpenCTI-Platform/opencti) | Cyber-threat-intelligence knowledge graph | Apache-2.0 | STIX 2.1 data model, connectors, provenance via reports/marking definitions | Heavy platform (Elastic, RabbitMQ, MinIO); CTI focus. |
| [Maltego](https://www.maltego.com/) (reference, proprietary) | Link analysis with "transforms" | Commercial (free CE tier) | The graph-centric UX that OSINT analysts expect | Closed source; transform hub mixes data of very different reliability. |

## What works well (adopted)

- **Plugin modules with typed inputs/outputs** (SpiderFoot, IntelOwl, Recon-ng) → ATLAS `SourceAdapter` with a
  declared metadata contract, discovered through Python entry points.
- **Data-driven source descriptions** (WhatsMyName, Sherlock) → declarative `SourceMetadata` (access method,
  auth, rate limits, licence, fields, reliability, citation format) that also generates the coverage report.
- **Graph-centric analysis** (Maltego, Amass, OpenCTI) → entity/relationship model and interactive graph.
- **Workers for long-running collection** (IntelOwl) → Celery with an inline fallback for single-node use.
- **Provenance objects** (OpenCTI/STIX) → every finding is a self-contained evidence record with citation.

## Recurring gaps (ATLAS's design response)

| Gap in existing tools | ATLAS response |
|---|---|
| Findings are bare strings; no notion of how sure we are | Rule-based, explainable confidence on every finding, with the list of applied rules |
| Same username/name treated as same person | Merge only on persistent identifiers; collisions flagged; same-handle links marked as inference |
| Heuristic HTTP-status scraping of hundreds of sites | Official/public APIs only; smaller but honest coverage, reported per investigation |
| Password-reset abuse, leaked databases, authenticated scraping | Excluded by policy; breach *notification* only via HIBP with consent |
| Unlimited recursive pivoting on personal data | Pivots are module-defined, passive and bounded (email → organisational domain; handle variants marked similar) |
| No legal/ethical guardrails | Authorisation record, consent enforcement for individuals, scope enforcement, opt-out, retention, audit |
| Collected web text fed to LLMs unfiltered (newer tools) | Sanitisation, injection detection, data envelope, schema-constrained output, citation validation |
| Licences of data sources not tracked | Licence and restrictions recorded per source and per finding citation |

## Sources

- SpiderFoot: <https://github.com/smicallef/spiderfoot>, community fork <https://pypi.org/project/spiderfoot-ng/>
- PhoneInfoga maintenance notice: <https://github.com/sundowndev/phoneinfoga>
- Maigret: <https://github.com/soxoj/maigret>
- Other repositories as linked in the table.

---

# v0.2 research – intelligence-platform features and UI patterns (November 2026)

Goal: identify what makes commercial and open intelligence platforms effective for analysts, and adopt what fits
ATLAS's lawful-use model. Findings were checked against vendor documentation and, for every new data source, the live
API response was inspected before an adapter was written.

## Platform patterns

| Observation | Where seen | ATLAS v0.2 response |
|---|---|---|
| Investigations are organised in **cases**; analysts **pivot** from a discovered entity into the next query in one click, and graph, table and histogram views coexist | Maltego (Graph browser: case management, one-click pivot from Search into Graph, graph/table/histogram views, split screen) | Cases with merged graph and timeline; one-click pivot dialogs on any linked identifier; graph + split-pane table + timeline histogram |
| Running only relevant transforms avoids cluttering the graph with noise | Maltego best-practice guidance | Module-defined, bounded pivots; kind filters, inference toggle and focus mode in the graph |
| External attack-surface tools grade a domain from email authentication (SPF, DMARC, MTA-STS, TLS-RPT), DNSSEC, TLS, headers, exposed ports and known CVEs; **each vendor weights checks differently, so scores are not comparable** | SecLens, UpGuard, Infoblox EASM, domain-posture checkers | Exposure scorecard built only from collected evidence, published weights, per-check recommendation and reference; explicitly not comparable with vendor scores |
| MTA-STS is rarely enforced (≈0.6 % of mail-enabled domains) and DMARC moves none → quarantine → reject | SecLens study, DMARC guidance | MTA-STS absence is a *warning* not a failure; DMARC p=none is a warning |
| Passive discovery via certificate transparency and DNS, no active scanning | Infoblox EASM | Two independent CT sources (crt.sh + Cert Spotter) corroborate subdomains; Shodan InternetDB provides exposure data without ATLAS scanning anything |
| Sanctions/PEP screening returns **possible matches with a similarity score; the score is match confidence, not risk**; topics distinguish sanctions, PEP, debarment, regulatory action | OpenSanctions API documentation | OpenSanctions adapter records hits as *possible* matches with topics and datasets, and also records clear results as evidence |
| Intelligence sharing uses **TLP 2.0** (CLEAR, GREEN, AMBER, AMBER+STRICT, RED) and **STIX 2.1** bundles with the marking-definition objects included | FIRST/CISA TLP 2.0; OASIS STIX 2.1; EclecticIQ ingestion notes | TLP on investigations and cases, printed on every PDF page; STIX export embeds the official OASIS TLP 2.0 marking objects (verified byte-for-byte) and uses spec-defined deterministic observable IDs |
| Keyboard-first command palettes, split-pane master/detail lists and dense tables with filters are standard in professional tools | Linear, Vercel, Raycast, Kibana-style analyst consoles | ⌘K palette with identifier auto-detection, j/k navigation, bulk actions, grouping and sorting |

## New sources – verification notes

| Source | Verified behaviour | Terms |
|---|---|---|
| Shodan InternetDB | `GET /{ip}` returns `ports`, `cpes`, `hostnames`, `tags`, `vulns`; 404 `{"detail":"No information available"}` for unknown IPs; IPv4 only | Free for non-commercial use; commercial products need a Shodan licence |
| SSLMate Cert Spotter | `GET /v1/issuances?domain=…&include_subdomains=true&expand=dns_names&expand=issuer` works anonymously with a small allowance; lists unexpired certificates | SSLMate terms; optional API key |
| Mastodon | `GET /api/v1/accounts/lookup?acct=` returns profile `fields[]` with `verified_at` for rel="me"-verified links | Instance terms |
| Bluesky | `app.bsky.actor.getProfile` on `public.api.bsky.app`; 400 for unknown handles; custom-domain handles are verified by Bluesky | Bluesky terms |
| Crossref | `/works?query.author=` is fuzzy, so ATLAS keeps only works with an exact author-name match; author entries may carry ORCID iDs | Metadata free to reuse |
| GLEIF Level 2 | `/lei-records/{lei}/direct-parent`, `/ultimate-parent` (404 when none reported), `/direct-children` with pagination totals | CC0 |
| OpenSanctions | `POST /match/default` with `Authorization: ApiKey …`, body `{"queries":{"q":{"schema":"Company","properties":{"name":[…]}}}}`; results carry `score`, `match`, `datasets`, `properties.topics` | CC BY-NC 4.0 for non-commercial use; free keys for journalism/NGO/academia; business use needs a licence |
| DNS-over-HTTPS | Google/Cloudflare JSON API: `Status` 0/3, typed `Answer` records; Cloudflare quotes TXT segments | Public resolvers |

## Sources

- Maltego platform guide and pricing: <https://academy.maltego.com/gtm-enablement-guide>, <https://www.maltego.com/pricing>
- Domain security posture tooling: <https://mcpservers.org/de/servers/seclens-one>, <https://www.upguard.com/security-report/powerdmarc>, <https://www.infoblox.com/products/brand-protection>
- OpenSanctions API and licensing: <https://www.opensanctions.org/docs/api/>, <https://www.opensanctions.org/docs/commercial/exemption/>, <https://www.opensanctions.org/faq/api/metering/>
- TLP 2.0: <https://www.cisa.gov/tlp>; STIX TLP 2.0 marking objects: OASIS `cti-stix-common-objects` (extension-definition-specifications/tlp-2.0); EclecticIQ STIX 2.1 marking notes: <https://docs.eclecticiq.com/ic/2.13.0/STIX_2.1_Data_Markings.html>
- Shodan InternetDB: <https://blog.shodan.io/introducing-the-internetdb-api/>, <https://book.shodan.io/developer-apis/internetdb/>
- Cert Spotter API: <https://sslmate.com/certspotter/api/docs-v1>
