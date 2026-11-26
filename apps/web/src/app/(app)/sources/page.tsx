"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { humanize } from "@/lib/format";
import type { Source } from "@/lib/types";
import { useUser } from "@/components/AppShell";
import { Badge, Card, inputClass, PageHeader, Spinner } from "@/components/ui";

export default function SourcesPage() {
  const user = useUser();
  const { data, setData } = useApi<Source[]>("/api/v1/sources");
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const isAdmin = user?.role === "admin";
  const categories = useMemo(() => [...new Set((data ?? []).map((s) => s.category))].sort(), [data]);
  const list = (data ?? []).filter((s) => (!cat || s.category === cat) && (!q || `${s.display_name} ${s.name} ${s.description}`.toLowerCase().includes(q.toLowerCase())));
  const summary = {
    total: data?.length ?? 0,
    enabled: data?.filter((s) => s.enabled).length ?? 0,
    configured: data?.filter((s) => s.configured).length ?? 0,
  };

  async function update(name: string, body: Partial<Pick<Source, "enabled" | "min_role">>) {
    const updated = await api<Source>(`/api/v1/sources/${name}`, { method: "PATCH", json: body });
    setData((prev) => prev?.map((s) => (s.name === name ? updated : s)));
  }

  return (
    <>
      <PageHeader
        title="Source management"
        subtitle={`${summary.total} registered adapters · ${summary.enabled} enabled · ${summary.configured} configured. Coverage is limited to these sources.`}
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <input aria-label="Search sources" placeholder="Search sources" className={inputClass} value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Category" className={inputClass} value={cat} onChange={(e) => setCat(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
        </select>
      </div>
      {!data ? <Spinner /> : (
        <div className="space-y-3">
          {list.map((s) => {
            const runs = Object.values(s.health).reduce((a, b) => a + b, 0);
            const failures = (s.health.unavailable ?? 0) + (s.health.error ?? 0) + (s.health.rate_limited ?? 0);
            return (
              <Card key={s.name}>
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <h2 className="font-medium text-slate-100">{s.display_name} <span className="font-mono text-xs text-muted">{s.name}</span></h2>
                    <p className="mt-1 text-sm text-muted">{s.description}</p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      <Badge>{humanize(s.category)}</Badge>
                      <Badge>{humanize(s.access_method)}</Badge>
                      <Badge title="Reliability grade">Reliability {s.reliability}</Badge>
                      <Badge>Inputs: {s.input_types.join(", ")}</Badge>
                      {s.legal.active_probe && <Badge className="border-warn/40 text-warn">Active · scope required</Badge>}
                      {s.legal.requires_subject_consent && <Badge className="border-warn/40 text-warn">Consent required</Badge>}
                      {s.configured ? <Badge className="border-ok/40 text-ok">Configured</Badge> : <Badge className="border-warn/40 text-warn">{s.configuration_message}</Badge>}
                      {runs > 0 && <Badge className={failures ? "border-bad/40 text-bad" : "border-ok/40 text-ok"}>{runs - failures}/{runs} recent runs OK</Badge>}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-3 text-sm">
                    <label className="flex items-center gap-2">
                      <input type="checkbox" checked={s.enabled} disabled={!isAdmin} onChange={(e) => update(s.name, { enabled: e.target.checked })} />
                      Enabled
                    </label>
                    <label className="flex items-center gap-2 text-xs text-muted">
                      Min role
                      <select className="rounded border border-line bg-ink-900 px-2 py-1 text-slate-200" value={s.min_role} disabled={!isAdmin}
                        onChange={(e) => update(s.name, { min_role: e.target.value })}>
                        {["viewer", "analyst", "admin"].map((r) => <option key={r}>{r}</option>)}
                      </select>
                    </label>
                    <button className="text-xs text-accent hover:underline" aria-expanded={open === s.name} onClick={() => setOpen(open === s.name ? null : s.name)}>
                      {open === s.name ? "Hide" : "Details"}
                    </button>
                  </div>
                </div>
                {open === s.name && (
                  <dl className="mt-4 grid gap-x-6 gap-y-2 border-t border-line pt-3 text-sm sm:grid-cols-2">
                    <div><dt className="text-xs text-muted">Rate limit</dt><dd>{s.rate_limit.requests} / {s.rate_limit.per_seconds}s {s.rate_limit.notes && `(${s.rate_limit.notes})`}</dd></div>
                    <div><dt className="text-xs text-muted">Freshness</dt><dd>{s.freshness}</dd></div>
                    <div><dt className="text-xs text-muted">Authentication</dt><dd>{s.auth.required ? `Required (${s.auth.kind})` : s.auth.optional ? "Optional" : "None"} {s.auth.how_to_obtain && <span className="text-muted">– {s.auth.how_to_obtain}</span>}</dd></div>
                    <div><dt className="text-xs text-muted">Licence</dt><dd>{s.legal.license ?? "See terms"}</dd></div>
                    <div className="sm:col-span-2"><dt className="text-xs text-muted">Restrictions</dt><dd>{s.legal.restrictions}</dd></div>
                    <div className="sm:col-span-2"><dt className="text-xs text-muted">Collected fields (data minimisation contract)</dt><dd className="font-mono text-xs">{s.fields.join(", ")}</dd></div>
                    <div className="sm:col-span-2"><dt className="text-xs text-muted">Links</dt>
                      <dd className="text-xs"><a className="text-accent hover:underline" href={s.homepage} target="_blank" rel="noopener noreferrer">Documentation</a>
                        {s.legal.terms_url && <> · <a className="text-accent hover:underline" href={s.legal.terms_url} target="_blank" rel="noopener noreferrer">Terms</a></>}</dd></div>
                  </dl>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </>
  );
}
