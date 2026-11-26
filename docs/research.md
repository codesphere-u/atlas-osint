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
