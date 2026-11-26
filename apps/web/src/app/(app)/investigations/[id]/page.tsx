"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { humanize } from "@/lib/format";
import type { Analysis, Classification, Finding } from "@/lib/types";
import { EvidenceCard } from "@/components/EvidenceCard";
import { useInvestigation } from "@/components/InvestigationContext";
import { useUser } from "@/components/AppShell";
import { Card, EmptyState, inputClass, KeyValue, Spinner, Stat, StatusPill } from "@/components/ui";

const BUCKETS: (Classification | "all")[] = ["all", "confirmed", "possible", "unverified", "rejected"];

export default function ResultsPage() {
  const { inv, reload } = useInvestigation();
  const user = useUser();
  const done = inv.status === "completed";
  const { data: findings, setData } = useApi<Finding[]>(done ? `/api/v1/investigations/${inv.id}/findings` : null);
  const { data: analysis } = useApi<Analysis>(done ? `/api/v1/investigations/${inv.id}/analysis` : null);
  const [bucket, setBucket] = useState<(typeof BUCKETS)[number]>("all");
  const [source, setSource] = useState("");
  const [q, setQ] = useState("");
  const [minScore, setMinScore] = useState(0);
  const canVerify = !!user && (user.role === "admin" || (user.role === "analyst" && user.id === inv.created_by));

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: findings?.length ?? 0 };
    for (const f of findings ?? []) c[f.classification] = (c[f.classification] ?? 0) + 1;
    return c;
  }, [findings]);
  const sources = useMemo(() => [...new Set((findings ?? []).map((f) => f.source_name))].sort(), [findings]);
  const visible = (findings ?? []).filter(
    (f) =>
      (bucket === "all" || f.classification === bucket) &&
      (!source || f.source_name === source) &&
      (f.confidence?.score ?? 0) >= minScore &&
      (!q || `${f.title} ${f.description}`.toLowerCase().includes(q.toLowerCase())),
  );

  async function verify(id: string, status: "verified" | "rejected" | "unverified", note?: string) {
    await api(`/api/v1/investigations/${inv.id}/findings/${id}`, { method: "PATCH", json: { status, note } });
    const fresh = await api<Finding[]>(`/api/v1/investigations/${inv.id}/findings`);
    setData(fresh);
    await reload();
  }

  if (!done) return inv.status === "failed" ? null : <Spinner label="Waiting for collection to finish" />;
  const cov = inv.coverage;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Findings" value={inv.finding_count} hint={`${counts.confirmed ?? 0} confirmed · ${counts.possible ?? 0} possible`} />
        <Stat label="Sources answered" value={`${cov.sources_answered ?? 0}/${cov.sources_consulted ?? 0}`} hint={`Coverage ${Math.round((cov.coverage_ratio ?? 0) * 100)}%`} />
        <Stat label="Entities / links" value={`${inv.entity_count} / ${inv.relationship_count}`} />
        <Stat label="Contradictions" value={inv.contradiction_count} hint={cov.suppressed_items ? `${cov.suppressed_items} items withheld (opt-out)` : undefined} />
      </div>

      {analysis && (
        <Card title="Summary">
          <p className="whitespace-pre-line text-sm text-slate-300">{analysis.summary}</p>
          {analysis.insufficient_evidence.length > 0 && (
            <ul className="mt-3 list-inside list-disc space-y-1 text-sm text-warn">
              {analysis.insufficient_evidence.map((i) => <li key={i}>{i}</li>)}
            </ul>
          )}
        </Card>
      )}

      <div className="grid gap-6 xl:grid-cols-4">
        <div className="space-y-4 xl:col-span-3">
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="Classification filter">
            {BUCKETS.map((b) => (
              <button key={b} role="tab" aria-selected={bucket === b} onClick={() => setBucket(b)}
                className={`rounded-md border px-3 py-1.5 text-xs ${bucket === b ? "border-accent bg-accent-soft text-white" : "border-line text-muted hover:text-white"}`}>
                {humanize(b)} <span className="font-mono">({counts[b] ?? 0})</span>
              </button>
            ))}
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <input aria-label="Search findings" placeholder="Search findings" className={inputClass} value={q} onChange={(e) => setQ(e.target.value)} />
            <select aria-label="Source" className={inputClass} value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">All sources</option>
              {sources.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <label className="flex items-center gap-2 text-xs text-muted">
              Min confidence
              <input type="range" min={0} max={1} step={0.05} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} className="flex-1" />
              <span className="w-10 font-mono">{Math.round(minScore * 100)}%</span>
            </label>
          </div>
          {!findings ? <Spinner /> : visible.length === 0 ? <EmptyState title="No findings match the filters" /> : (
            <div className="space-y-3">
              {visible.map((f) => (
                <EvidenceCard key={f.id} finding={f} canVerify={canVerify} onVerify={verify} injectionFlags={analysis?.injection_flags[f.id]} />
              ))}
            </div>
          )}
        </div>
        <div className="space-y-4">
          <Card title="Module summary"><KeyValue data={inv.module_summary} /></Card>
          <Card title="Sources consulted">
            <ul className="space-y-2 text-xs">
              {(cov.runs ?? []).map((r, i) => (
                <li key={i} className="space-y-0.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-slate-200" title={r.display_name}>{r.display_name}</span>
                    <StatusPill status={r.status} />
                  </div>
                  {r.message && <div className="text-muted">{r.message}</div>}
                  {r.reason !== "primary" && <div className="text-muted">({r.reason})</div>}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
