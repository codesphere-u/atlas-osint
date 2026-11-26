# Privacy

ATLAS OSINT processes personal data when it is used to investigate individuals. This document describes the
privacy controls built into the software and the responsibilities of whoever operates an installation (the
"controller" under GDPR/UK GDPR).

## Principles implemented in code

| Principle | Implementation |
|---|---|
| Lawfulness & accountability | Every investigation stores purpose, legal basis, authorisation reference, consent reference and an attestation; all are audited. |
| Consent-based profiling | With `ATLAS_REQUIRE_CONSENT_FOR_INDIVIDUALS=true` (default) an individual can only be investigated with legal basis `consent` (with a consent reference) or `self`. |
| Data minimisation | Each source declares the fields it may emit; anything else is dropped. A policy filter removes prohibited categories (see below) and redacts free text. |
| Purpose limitation | Results are visible only to the owner, administrators and read-only roles; no cross-investigation people database is built. |
| Storage limitation | Each investigation has a retention date (default 90 days, maximum 365) after which it is deleted automatically. |
| Integrity & confidentiality | Encryption at rest, TLS in transit, RBAC, audit trail without raw identifiers. |
| Data-subject rights | Public request form (`/privacy`): opt-out, correction, deletion. Approved opt-outs block future investigations and suppress the identifier in results; deletion purges matching data. |

## Data ATLAS never collects about individuals

Residential or postal addresses, precise or self-reported locations, private phone numbers or other private
contact details (other than the identifier being investigated), dates of birth or ages, financial or payment data,
government identifiers, credentials, passwords or tokens, health, religion, ethnicity, sexual orientation, political
opinion, union membership, biometric or criminal-record data. Breach lookups return breach *names* only, and only
with documented consent.

ATLAS never identifies the subscriber of a phone number, never probes mailboxes or triggers password-reset flows,
never logs into accounts and never accesses non-public systems.

## Sources and licences

Every finding records the source, URL, collection time and citation; each source's licence and restrictions are
listed in [`docs/source-coverage.md`](docs/source-coverage.md). Operators must comply with those terms.

## Operator checklist

- Identify your lawful basis and document it (e.g. a DPIA for any systematic monitoring or profiling).
- Publish a privacy notice that explains how data subjects can use the `/privacy` request form, and review
  requests promptly (Administration → Privacy).
- Configure retention to the shortest period that meets your purpose.
- Restrict accounts to trained analysts; review the audit log regularly.
- Do not export reports to unsecured locations; reports contain personal data.

## Correction process

Correction requests are recorded and shown to administrators. Because ATLAS reports what public sources state,
corrections are handled by (a) rejecting the incorrect finding with an analyst note, which removes it from
conclusions and reports, and (b) where appropriate approving an opt-out. ATLAS cannot change the original source;
the data subject should also contact that source.
