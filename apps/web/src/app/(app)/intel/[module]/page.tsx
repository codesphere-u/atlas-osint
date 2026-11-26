"use client";

import Link from "next/link";
import { notFound, useParams } from "next/navigation";
import { useApi } from "@/lib/hooks";
import { fmtDate } from "@/lib/format";
import type { Investigation, Meta, Source } from "@/lib/types";
import { InvestigationForm } from "@/components/InvestigationForm";
import { Badge, Card, PageHeader, StatusPill } from "@/components/ui";
import { useUser } from "@/components/AppShell";

const MODULES: Record<string, { module: string; title: string; blurb: string }> = {
  phone: { module: "phone", title: "Phone intelligence", blurb: "E.164 normalisation, numbering-plan region, validity, line type and range-allocated carrier. Never identifies a private subscriber." },
  username: { module: "username", title: "Username intelligence", blurb: "Public profiles on official platform APIs; exact vs similar handles; publicly documented cross-platform references." },
  name: { module: "name", title: "Name intelligence", blurb: "Professional, academic and encyclopaedic records keyed by persistent identifiers. Name collisions are flagged; names never merge people." },
  email: { module: "email", title: "Email intelligence", blurb: "Syntax and provider analysis, public DNS mail policy, organisational domain pivot and consent-gated breach notification. No mailbox probing." },
  domain: { module: "domain", title: "Domain & infrastructure intelligence", blurb: "DNS, RDAP, certificate transparency, archives, ASN mapping and (in scope) security headers. Passive by default." },
  records: { module: "public_records", title: "Public records intelligence", blurb: "Legal-entity and company registries, securities filings, news archives and public documents with licence-aware citations." },
};

export default function ModulePage() {
  const { module: slug } = useParams<{ module: string }>();
  const cfg = MODULES[slug];
  const user = useUser();
  const { data: meta } = useApi<Meta>("/api/v1/meta");
  const { data: sources } = useApi<Source[]>("/api/v1/sources");
  const mod = meta?.modules.find((m) => m.name === cfg?.module);
  const types = mod?.input_types;
  const { data: recent } = useApi<Investigation[]>(types ? `/api/v1/investigations?limit=50` : null);
  if (!cfg) notFound();
  const relevant = sources?.filter((s) => s.input_types.some((t) => types?.includes(t))) ?? [];
  const canCreate = user?.role === "admin" || user?.role === "analyst";

  return (
    <>
      <PageHeader title={cfg.title} subtitle={cfg.blurb} />
      <div className="space-y-6">
        {canCreate && types && <InvestigationForm key={slug} types={types} defaultType={types[0]} />}
        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Guardrails">
            <ul className="list-inside list-disc space-y-1 text-sm text-slate-300">
              {mod?.guardrails.map((g) => <li key={g}>{g}</li>)}
            </ul>
          </Card>
          <Card title={`Sources (${relevant.length})`}>
            <ul className="space-y-2 text-sm">
              {relevant.map((s) => (
                <li key={s.name} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-slate-200">{s.display_name}</span>
                  <span className="flex gap-1">
                    <Badge>Reliability {s.reliability}</Badge>
                    {!s.enabled && <Badge className="border-line text-muted">disabled</Badge>}
                    {!s.configured && <Badge className="border-warn/40 text-warn">needs credentials</Badge>}
                    {s.legal.active_probe && <Badge className="border-warn/40 text-warn">scope required</Badge>}
                    {s.legal.requires_subject_consent && <Badge className="border-warn/40 text-warn">consent required</Badge>}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
        <Card title="Recent investigations in this module">
          <ul className="divide-y divide-line text-sm">
            {recent?.filter((i) => types?.includes(i.subject_type)).slice(0, 10).map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-2 py-2">
                <Link href={`/investigations/${i.id}`} className="truncate text-slate-100 hover:text-accent">{i.title}</Link>
                <span className="flex items-center gap-2 text-xs text-muted">{fmtDate(i.created_at)} <StatusPill status={i.status} /></span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
