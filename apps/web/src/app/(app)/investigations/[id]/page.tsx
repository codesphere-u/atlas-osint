"use client";

import { CheckCircle2, CircleDashed, CircleHelp, Download, ShieldAlert, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useUser } from "@/components/AppShell";
import { EvidenceCard } from "@/components/EvidenceCard";
import { useInvestigation } from "@/components/InvestigationContext";
import { pivotTarget, PivotDialog, type PivotTarget } from "@/components/PivotDialog";
import {
  Button, Card, cx, EmptyState, inputClass, Kbd, KeyValue, RiskBadge, SkeletonRows, Stat, StatusPill,
} from "@/components/ui";
import { api } from "@/lib/api";
import { humanize, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useToast } from "@/lib/toast";
import type { Analysis, Assessment, Classification, Finding } from "@/lib/types";

const BUCKETS: (Classification | "all")[] = ["all", "confirmed", "possible", "unverified", "rejected"];
const CLASS_ICON: Record<Classification, React.ReactNode> = {
  confirmed: <CheckCircle2 className="h-3.5 w-3.5 text-[#34d399]" aria-label="Confirmed" />,
  possible: <CircleHelp className="h-3.5 w-3.5 text-accent" aria-label="Possible" />,
  unverified: <CircleDashed className="h-3.5 w-3.5 text-warn" aria-label="Unverified" />,
  rejected: <XCircle className="h-3.5 w-3.5 text-bad" aria-label="Rejected" />,
};
type GroupBy = "none" | "source_display_name" | "finding_type" | "classification";
type SortBy = "confidence" | "newest" | "source";

function toCsv(rows: Finding[]): string {
  const esc = (v: unknown) => {
    let s = v == null ? "" : String(v);
    if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return `"${s.replace(/"/g, '""')}"`;
  };
  const head = ["id", "classification", "confidence", "title", "source", "source_url", "collected_at"];
  return [head.join(","), ...rows.map((f) => [f.id, f.classification, f.confidence?.score, f.title, f.source_display_name, f.source_url, f.collected_at].map(esc).join(","))].join("\n");
}

export default function FindingsPage() {
  const { inv, reload } = useInvestigation();
  const user = useUser();
  const toast = useToast();
  const done = inv.status === "completed";
  const { data: findings, setData } = useApi<Finding[]>(done ? `/api/v1/investigations/${inv.id}/findings` : null);
  const { data: analysis } = useApi<Analysis>(done ? `/api/v1/investigations/${inv.id}/analysis` : null);
  const { data: assessment, reload: reloadAssessment } = useApi<Assessment>(done ? `/api/v1/investigations/${inv.id}/assessment` : null);
  const [bucket, setBucket] = useState<(typeof BUCKETS)[number]>("all");
  const [source, setSource] = useState("");
  const [q, setQ] = useState("");
  const [minScore, setMinScore] = useState(0);
  const [groupBy, setGroupBy] = useState<GroupBy>("none");
  const [sortBy, setSortBy] = useState<SortBy>("confidence");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pivot, setPivot] = useState<PivotTarget | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const canVerify = !!user && (user.role === "admin" || (user.role === "analyst" && user.id === inv.created_by));

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: findings?.length ?? 0 };
    for (const f of findings ?? []) c[f.classification] = (c[f.classification] ?? 0) + 1;
    return c;
  }, [findings]);
  const sources = useMemo(() => [...new Set((findings ?? []).map((f) => f.source_name))].sort(), [findings]);
  const visible = useMemo(() => {
    const out = (findings ?? []).filter(
      (f) => (bucket === "all" || f.classification === bucket) && (!source || f.source_name === source) &&
        (f.confidence?.score ?? 0) >= minScore && (!q || `${f.title} ${f.description}`.toLowerCase().includes(q.toLowerCase())),
    );
    const cmp: Record<SortBy, (a: Finding, b: Finding) => number> = {
      confidence: (a, b) => (b.confidence?.score ?? 0) - (a.confidence?.score ?? 0),
      newest: (a, b) => (b.published_at ?? b.collected_at).localeCompare(a.published_at ?? a.collected_at),
      source: (a, b) => a.source_display_name.localeCompare(b.source_display_name),
    };
    return out.sort(cmp[sortBy]);
  }, [findings, bucket, source, minScore, q, sortBy]);
  const groups = useMemo(() => {
    if (groupBy === "none") return [{ key: "", items: visible }];
    const map = new Map<string, Finding[]>();
    for (const f of visible) {
      const k = String(f[groupBy] ?? "other");
      map.set(k, [...(map.get(k) ?? []), f]);
    }
    return [...map.entries()].map(([key, items]) => ({ key, items }));
  }, [visible, groupBy]);
  const order = useMemo(() => groups.flatMap((g) => g.items), [groups]);
  const active = order.find((f) => f.id === activeId) ?? order[0];

  const refresh = useCallback(async () => {
    setData(await api<Finding[]>(`/api/v1/investigations/${inv.id}/findings`));
    await Promise.all([reload(), reloadAssessment()]);
  }, [inv.id, reload, reloadAssessment, setData]);

  async function verify(id: string, status: "verified" | "rejected" | "unverified", note?: string) {
    await api(`/api/v1/investigations/${inv.id}/findings/${id}`, { method: "PATCH", json: { status, note } });
    toast("success", `Finding ${status}`, "Scores, correlation and assessment were recomputed.");
    await refresh();
  }

  async function bulk(status: "verified" | "rejected") {
    const ids = [...selected];
    await api(`/api/v1/investigations/${inv.id}/findings/bulk`, { method: "POST", json: { finding_ids: ids, status } });
    toast("success", `${ids.length} findings ${status}`);
    setSelected(new Set());
    await refresh();
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
      if (!order.length) return;
      const idx = Math.max(0, order.findIndex((f) => f.id === active?.id));
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        setActiveId(order[Math.min(order.length - 1, idx + 1)]?.id ?? null);
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        setActiveId(order[Math.max(0, idx - 1)]?.id ?? null);
      } else if (e.key === "x" && active && canVerify) {
        setSelected((s) => { const n = new Set(s); if (n.has(active.id)) n.delete(active.id); else n.add(active.id); return n; });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [order, active, canVerify]);

  useEffect(() => {
    // Only follow the selection once the user has moved it; never scroll the page on first render.
    if (!activeId) return;
    listRef.current?.querySelector(`[data-fid="${activeId}"]`)?.scrollIntoView({ block: "nearest" });
  }, [activeId]);

  if (!done) return inv.status === "failed" ? null : <SkeletonRows rows={6} />;
  const cov = inv.coverage;
  const risk = assessment?.risk ?? [];

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Findings" value={inv.finding_count} hint={`${counts.confirmed ?? 0} confirmed · ${counts.possible ?? 0} possible`} />
        <Stat label="Sources answered" value={`${cov.sources_answered ?? 0}/${cov.sources_consulted ?? 0}`} hint={`Coverage ${Math.round((cov.coverage_ratio ?? 0) * 100)}%`} />
        <Stat label="Entities / links" value={`${inv.entity_count} / ${inv.relationship_count}`} />
        <Stat label="Contradictions" value={inv.contradiction_count} hint={cov.suppressed_items ? `${cov.suppressed_items} items withheld (opt-out)` : undefined} />
      </div>

      {risk.length > 0 && (
        <Card title={<span className="flex items-center gap-2"><ShieldAlert className="h-4 w-4 text-[#f18a59]" />Risk highlights</span>}>
          <ul className="grid gap-2 md:grid-cols-2">
            {risk.slice(0, 6).map((h, i) => (
              <li key={i} className="rounded-md border border-line bg-ink-900/60 p-3">
                <div className="flex flex-wrap items-center gap-2 text-sm text-slate-100"><RiskBadge level={h.severity} />{h.title}</div>
                <div className="mt-1 line-clamp-2 text-xs text-muted">{h.detail}</div>
                <div className="mt-1 text-[11px] text-muted">{h.confirmed ? "Supported by confirmed findings" : "Requires analyst confirmation"} ·{" "}
                  <button className="text-accent hover:underline" onClick={() => setActiveId(h.finding_ids[0] ?? null)}>show evidence</button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {analysis && (
        <details className="rounded-lg border border-line bg-ink-850/80 p-4" open={risk.length === 0}>
          <summary className="cursor-pointer text-sm font-semibold text-slate-100">Summary</summary>
          <p className="mt-2 whitespace-pre-line text-sm text-slate-300">{analysis.summary}</p>
          {analysis.insufficient_evidence.length > 0 && (
            <ul className="mt-3 list-inside list-disc space-y-1 text-sm text-warn">{analysis.insufficient_evidence.map((i) => <li key={i}>{i}</li>)}</ul>
          )}
        </details>
      )}

      <div className="space-y-3">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Classification filter">
          {BUCKETS.map((b) => (
            <button key={b} role="tab" aria-selected={bucket === b} onClick={() => setBucket(b)}
              className={cx("flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs", bucket === b ? "border-accent bg-accent-soft text-white" : "border-line text-muted hover:text-white")}>
              {b !== "all" && CLASS_ICON[b]}{humanize(b)} <span className="font-mono">({counts[b] ?? 0})</span>
            </button>
          ))}
        </div>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          <input aria-label="Search findings" placeholder="Search findings" className={inputClass} value={q} onChange={(e) => setQ(e.target.value)} />
          <select aria-label="Source" className={inputClass} value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">All sources</option>{sources.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select aria-label="Group by" className={inputClass} value={groupBy} onChange={(e) => setGroupBy(e.target.value as GroupBy)}>
            <option value="none">No grouping</option><option value="source_display_name">Group by source</option>
            <option value="finding_type">Group by type</option><option value="classification">Group by classification</option>
          </select>
          <select aria-label="Sort" className={inputClass} value={sortBy} onChange={(e) => setSortBy(e.target.value as SortBy)}>
            <option value="confidence">Highest confidence</option><option value="newest">Newest evidence</option><option value="source">Source A–Z</option>
          </select>
          <label className="flex items-center gap-2 text-xs text-muted">Min
            <input type="range" min={0} max={1} step={0.05} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} className="flex-1" />
            <span className="w-9 font-mono">{pct(minScore)}</span>
          </label>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          <span>{visible.length} shown · <Kbd>j</Kbd>/<Kbd>k</Kbd> move{canVerify && <> · <Kbd>x</Kbd> select</>}</span>
          <div className="flex items-center gap-2">
            {selected.size > 0 && canVerify && (
              <>
                <span className="text-slate-200">{selected.size} selected</span>
                <Button variant="secondary" className="py-1" onClick={() => bulk("verified")}>Verify</Button>
                <Button variant="danger" className="py-1" onClick={() => bulk("rejected")}>Reject</Button>
                <Button variant="ghost" className="py-1" onClick={() => setSelected(new Set())}>Clear</Button>
              </>
            )}
            <a className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-slate-300 hover:bg-ink-700" download={`atlas-findings-${inv.id.slice(0, 8)}.csv`}
              href={`data:text/csv;charset=utf-8,${encodeURIComponent(toCsv(visible))}`}>
              <Download className="h-3.5 w-3.5" />Export view
            </a>
          </div>
        </div>
      </div>

      {!findings ? <SkeletonRows rows={6} /> : visible.length === 0 ? <EmptyState title="No findings match the filters" /> : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <div ref={listRef} className="max-h-[70vh] space-y-3 overflow-y-auto pr-1" role="listbox" aria-label="Findings">
            {groups.map((g) => (
              <div key={g.key}>
                {g.key && <div className="sticky top-0 z-[1] bg-ink-950/95 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted">{humanize(g.key)} · {g.items.length}</div>}
                <ul className="space-y-1">
                  {g.items.map((f) => (
                    <li key={f.id} data-fid={f.id} role="option" aria-selected={active?.id === f.id}
                      className={cx("flex cursor-pointer items-start gap-2 rounded-md border px-3 py-2",
                        active?.id === f.id ? "border-accent/60 bg-accent-soft/40" : "border-transparent hover:border-line hover:bg-ink-850")}
                      onClick={() => setActiveId(f.id)}>
                      {canVerify && (
                        <input type="checkbox" aria-label={`Select ${f.title}`} className="mt-1 h-3.5 w-3.5" checked={selected.has(f.id)}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => setSelected((s) => { const n = new Set(s); if (e.target.checked) n.add(f.id); else n.delete(f.id); return n; })} />
                      )}
                      <span className="mt-0.5">{CLASS_ICON[f.classification]}</span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm text-slate-100">{f.title}</div>
                        <div className="flex items-center gap-2 text-[11px] text-muted">
                          <span className="truncate">{f.source_display_name}</span>
                          {f.flags.some((x) => x.startsWith("risk:")) && <span className="text-[#f18a59]">risk</span>}
                          {analysis?.injection_flags[f.id] && <span className="text-bad">untrusted text</span>}
                        </div>
                      </div>
                      <span className="font-mono text-xs text-slate-300">{pct(f.confidence?.score)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className="space-y-4 xl:sticky xl:top-20 xl:self-start">
            {active && (
              <EvidenceCard key={active.id} finding={active} canVerify={canVerify} onVerify={verify} defaultOpen
                injectionFlags={analysis?.injection_flags[active.id]}
                onPivot={canVerify ? (t, v) => setPivot(pivotTarget(t, v)) : undefined} />
            )}
            <details className="rounded-lg border border-line bg-ink-850/80 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-100">Module summary & sources consulted</summary>
              <div className="mt-3 grid gap-4 md:grid-cols-2">
                <KeyValue data={inv.module_summary} />
                <ul className="space-y-2 text-xs">
                  {(cov.runs ?? []).map((r, i) => (
                    <li key={i}>
                      <div className="flex items-center justify-between gap-2"><span className="truncate text-slate-200">{r.display_name}</span><StatusPill status={r.status} /></div>
                      {r.message && <div className="text-muted">{r.message}</div>}
                    </li>
                  ))}
                </ul>
              </div>
            </details>
          </div>
        </div>
      )}
      <PivotDialog investigationId={inv.id} target={pivot} onClose={() => setPivot(null)} />
    </div>
  );
}
