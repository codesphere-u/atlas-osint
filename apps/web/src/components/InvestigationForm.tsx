"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { LEGAL_BASIS_LABEL, TYPE_LABEL } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { CaseSummary, Investigation, Meta } from "@/lib/types";
import { Button, Card, ErrorBox, Field, inputClass } from "./ui";

const INDIVIDUAL_TYPES = new Set(["phone", "username", "name", "email"]);
const PLACEHOLDER: Record<string, string> = {
  phone: "+44 20 7946 0958",
  username: "octocat",
  name: "Ada Lovelace",
  email: "someone@example.org",
  domain: "example.com",
  url: "https://example.com/page",
  ip: "93.184.216.34",
  organization: "Example Corporation",
  document: "https://example.com/annual-report.pdf",
};

export function InvestigationForm({ types, defaultType }: { types?: string[]; defaultType?: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const { data: meta } = useApi<Meta>("/api/v1/meta");
  const { data: cases } = useApi<CaseSummary[]>("/api/v1/cases?status=open");
  const allowedTypes = types ?? meta?.identifier_types ?? Object.keys(TYPE_LABEL);
  const presetType = params.get("type");
  const [subjectType, setSubjectType] = useState(
    presetType && (!types || types.includes(presetType)) ? presetType : defaultType ?? allowedTypes[0] ?? "domain",
  );
  const [subject, setSubject] = useState(params.get("subject") ?? "");
  const [tlp, setTlp] = useState("amber");
  const [caseId, setCaseId] = useState(params.get("case") ?? "");
  const [title, setTitle] = useState("");
  const [purpose, setPurpose] = useState("");
  const [subjectKind, setSubjectKind] = useState("");
  const [legalBasis, setLegalBasis] = useState("");
  const [consentObtained, setConsentObtained] = useState(false);
  const [consentRef, setConsentRef] = useState("");
  const [authRef, setAuthRef] = useState("");
  const [domains, setDomains] = useState("");
  const [retention, setRetention] = useState("");
  const [region, setRegion] = useState("");
  const [variants, setVariants] = useState(false);
  const [ai, setAi] = useState(false);
  const [attest, setAttest] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const effectiveKind = subjectKind || (INDIVIDUAL_TYPES.has(subjectType) || subjectType === "document"
    ? "individual" : subjectType === "organization" ? "organization" : "infrastructure");
  const individual = effectiveKind === "individual";
  const consentRequired = individual && (meta?.require_consent_for_individuals ?? true);
  const bases = useMemo(() => {
    const all = meta?.legal_bases ?? Object.keys(LEGAL_BASIS_LABEL);
    return consentRequired ? all.filter((b) => b === "consent" || b === "self") : all;
  }, [meta, consentRequired]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErrors([]);
    setBusy(true);
    try {
      const inv = await api<Investigation>("/api/v1/investigations", {
        method: "POST",
        json: {
          title: title || `${TYPE_LABEL[subjectType] ?? subjectType}: ${subject}`.slice(0, 200),
          subject_type: subjectType,
          subject,
          subject_kind: subjectKind || undefined,
          purpose,
          legal_basis: legalBasis,
          authorization_reference: authRef || undefined,
          consent_obtained: consentObtained,
          consent_reference: consentRef || undefined,
          authorized_domains: domains.split(/[\s,]+/).filter(Boolean),
          attestation: attest,
          retention_days: retention ? Number(retention) : undefined,
          default_region: region || undefined,
          options: { include_variants: variants, ai_analysis: ai, pivot_domain: true },
          tlp,
          case_id: caseId || undefined,
        },
      });
      router.push(`/investigations/${inv.id}`);
    } catch (err) {
      setErrors(err instanceof ApiError ? err.messages : [String(err)]);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-6 lg:grid-cols-3" noValidate>
      <div className="space-y-6 lg:col-span-2">
        <Card title="Subject">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Identifier type" htmlFor="stype">
              <select id="stype" className={inputClass} value={subjectType} onChange={(e) => setSubjectType(e.target.value)}>
                {allowedTypes.map((t) => <option key={t} value={t}>{TYPE_LABEL[t] ?? t}</option>)}
              </select>
            </Field>
            <Field label="Identifier" htmlFor="subject" help="Normalised server-side (E.164, IDNA, lower-case handles).">
              <input id="subject" required maxLength={512} className={inputClass} value={subject}
                placeholder={PLACEHOLDER[subjectType]} onChange={(e) => setSubject(e.target.value)} />
            </Field>
            {subjectType === "phone" && (
              <Field label="Default region (optional)" htmlFor="region" help="ISO country code for numbers without a + prefix.">
                <input id="region" maxLength={2} className={inputClass} value={region} placeholder="GB"
                  onChange={(e) => setRegion(e.target.value.toUpperCase())} />
              </Field>
            )}
            <Field label="Title" htmlFor="title" help="Optional; defaults to the identifier.">
              <input id="title" maxLength={200} className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} />
            </Field>
            <Field label="Subject kind" htmlFor="skind" help="Determines privacy rules. Individuals receive the strictest protection.">
              <select id="skind" className={inputClass} value={subjectKind} onChange={(e) => setSubjectKind(e.target.value)}>
                <option value="">Automatic ({effectiveKind})</option>
                <option value="individual">Individual</option>
                <option value="organization">Organization</option>
                <option value="infrastructure">Infrastructure</option>
              </select>
            </Field>
          </div>
        </Card>

        <Card title="Authorisation record">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Legal basis" htmlFor="basis" help={consentRequired ? "Profiling an individual requires documented consent or a self-investigation." : undefined}>
              <select id="basis" required className={inputClass} value={legalBasis} onChange={(e) => setLegalBasis(e.target.value)}>
                <option value="">Select…</option>
                {bases.map((b) => <option key={b} value={b}>{LEGAL_BASIS_LABEL[b] ?? b}</option>)}
              </select>
            </Field>
            <Field label="Authorisation reference" htmlFor="authref" help="Engagement ID, ticket or written-authorisation reference.">
              <input id="authref" maxLength={200} className={inputClass} value={authRef} onChange={(e) => setAuthRef(e.target.value)} />
            </Field>
            {legalBasis === "consent" && (
              <>
                <div className="flex items-center gap-2 sm:col-span-2">
                  <input id="consent" type="checkbox" checked={consentObtained} onChange={(e) => setConsentObtained(e.target.checked)}
                    className="h-4 w-4 rounded border-line bg-ink-900" />
                  <label htmlFor="consent" className="text-sm text-slate-200">Documented consent has been obtained from the individual</label>
                </div>
                <Field label="Consent reference" htmlFor="cref">
                  <input id="cref" maxLength={200} className={inputClass} value={consentRef} onChange={(e) => setConsentRef(e.target.value)} />
                </Field>
              </>
            )}
            <Field label="Authorised domains (scope)" htmlFor="domains" help="Active checks (website headers) and subdomain listings only run for these domains.">
              <input id="domains" className={inputClass} value={domains} placeholder="example.com, example.org" onChange={(e) => setDomains(e.target.value)} />
            </Field>
            <div className="sm:col-span-2">
              <Field label="Purpose" htmlFor="purpose" help="Why this investigation is necessary and proportionate (min. 10 characters; recorded in the audit trail).">
                <textarea id="purpose" required minLength={10} maxLength={2000} rows={3} className={inputClass} value={purpose} onChange={(e) => setPurpose(e.target.value)} />
              </Field>
            </div>
          </div>
        </Card>
      </div>

      <div className="space-y-6">
        <Card title="Handling">
          <div className="space-y-3">
            <Field label="Sharing (TLP 2.0)" htmlFor="tlp" help="Applied to reports and STIX exports.">
              <select id="tlp" className={inputClass} value={tlp} onChange={(e) => setTlp(e.target.value)}>
                <option value="clear">TLP:CLEAR – no limit on disclosure</option>
                <option value="green">TLP:GREEN – community</option>
                <option value="amber">TLP:AMBER – organisation and clients</option>
                <option value="amber+strict">TLP:AMBER+STRICT – organisation only</option>
                <option value="red">TLP:RED – named recipients only</option>
              </select>
            </Field>
            <Field label="Case (optional)" htmlFor="case" help="Group related investigations for a merged graph.">
              <select id="case" className={inputClass} value={caseId} onChange={(e) => setCaseId(e.target.value)}>
                <option value="">No case</option>
                {cases?.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
              </select>
            </Field>
          </div>
        </Card>
        <Card title="Options">
          <div className="space-y-3 text-sm">
            {subjectType === "username" && (
              <label className="flex items-start gap-2">
                <input type="checkbox" checked={variants} onChange={(e) => setVariants(e.target.checked)} className="mt-1 h-4 w-4" />
                <span><span className="text-slate-200">Check handle variants</span><br /><span className="text-xs text-muted">Results are always marked “similar”, never exact.</span></span>
              </label>
            )}
            <label className="flex items-start gap-2">
              <input type="checkbox" checked={ai} onChange={(e) => setAi(e.target.checked)} className="mt-1 h-4 w-4" />
              <span><span className="text-slate-200">AI analyst narrative</span><br /><span className="text-xs text-muted">Provider: {meta?.ai_provider ?? "…"}. Deterministic analysis always runs.</span></span>
            </label>
            <Field label="Retention (days)" htmlFor="ret" help={`Default ${meta?.default_retention_days ?? 90}, maximum ${meta?.max_retention_days ?? 365}. Data is deleted automatically afterwards.`}>
              <input id="ret" type="number" min={1} max={meta?.max_retention_days ?? 365} className={inputClass} value={retention} onChange={(e) => setRetention(e.target.value)} />
            </Field>
          </div>
        </Card>
        <Card title="Attestation">
          <label className="flex items-start gap-2 text-sm text-slate-200">
            <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} className="mt-1 h-4 w-4" required />
            <span>I confirm this investigation is lawful, proportionate and authorised, concerns publicly available information only, and will not be used for stalking, harassment, doxxing or discrimination.</span>
          </label>
        </Card>
        <ErrorBox messages={errors} />
        <Button type="submit" disabled={busy || !subject || !legalBasis || !attest || purpose.length < 10} className="w-full">
          {busy ? "Starting…" : "Start investigation"}
        </Button>
      </div>
    </form>
  );
}
