"use client";

import { CheckCircle2, CircleHelp, ExternalLink, Info, MinusCircle, TriangleAlert, XCircle } from "lucide-react";
import { useState } from "react";
import { ScoreRing } from "@/components/charts";
import { useInvestigation } from "@/components/InvestigationContext";
import { Card, cx, EmptyState, SkeletonRows } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import type { Assessment, CheckStatus, PostureCheck } from "@/lib/types";

const STATUS: Record<CheckStatus, { icon: React.ReactNode; label: string; cls: string }> = {
  fail: { icon: <XCircle className="h-4 w-4" />, label: "Fail", cls: "text-[#ff8a8b]" },
  warn: { icon: <TriangleAlert className="h-4 w-4" />, label: "Warning", cls: "text-[#fbcf6a]" },
  pass: { icon: <CheckCircle2 className="h-4 w-4" />, label: "Pass", cls: "text-[#34d399]" },
  info: { icon: <Info className="h-4 w-4" />, label: "Info", cls: "text-accent" },
  unknown: { icon: <CircleHelp className="h-4 w-4" />, label: "Unknown", cls: "text-muted" },
};
const ORDER: CheckStatus[] = ["fail", "warn", "unknown", "info", "pass"];
const SEV_ORDER = { high: 0, medium: 1, low: 2 };

function CheckRow({ c }: { c: PostureCheck }) {
  const s = STATUS[c.status];
  return (
    <li className="rounded-md border border-line bg-ink-900/50 p-3">
      <div className="flex items-start gap-3">
        <span className={cx("mt-0.5 shrink-0", s.cls)} aria-label={s.label}>{s.icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-slate-100">{c.title}</span>
            <span className="rounded border border-line px-1.5 text-[10px] uppercase tracking-wide text-muted">{c.severity}</span>
            <span className="font-mono text-[10px] text-muted">{c.id}</span>
          </div>
          <p className="mt-1 text-sm text-slate-300">{c.detail}</p>
          {c.recommendation && <p className="mt-1 text-sm text-accent">→ {c.recommendation}</p>}
          {c.reference && (
            <a href={c.reference} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs text-muted hover:text-accent">
              Reference <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      </div>
    </li>
  );
}

export default function ExposurePage() {
  const { inv } = useInvestigation();
  const done = inv.status === "completed";
  const { data } = useApi<Assessment>(done ? `/api/v1/investigations/${inv.id}/assessment` : null);
  const [filter, setFilter] = useState<CheckStatus | "all">("all");
  if (!done || !data) return <SkeletonRows rows={5} />;
  const p = data.posture;
  if (!p || !p.checks.length) {
    return <EmptyState title="No exposure data">Email-security, DNS, website and exposure sources produced no evaluable evidence for this subject.</EmptyState>;
  }
  const checks = [...p.checks].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || SEV_ORDER[a.severity] - SEV_ORDER[b.severity]);
  const shown = checks.filter((c) => filter === "all" || c.status === filter);
  const counts = Object.fromEntries(ORDER.map((s) => [s, p.checks.filter((c) => c.status === s).length]));
  const outOfScope = p.checks.length < 8 && !inv.authorized_domains.length;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      <div className="space-y-6">
        <Card>
          <div className="flex items-center gap-5">
            <ScoreRing score={p.score} grade={p.grade} />
            <div className="text-sm">
              <div className="font-semibold text-white">External exposure scorecard</div>
              <div className="mt-1 text-muted">{p.evaluated} checks evaluated</div>
              {p.score == null && <div className="mt-1 text-xs text-warn">Fewer than 5 checks could be evaluated – no grade.</div>}
            </div>
          </div>
          <ul className="mt-5 space-y-2">
            {Object.entries(p.categories).map(([cat, c]) => {
              const total = c.pass + c.warn + c.fail;
              return (
                <li key={cat} className="text-xs">
                  <div className="mb-1 flex justify-between text-slate-300"><span>{cat}</span><span className="font-mono text-muted">{c.pass}/{total || 0} pass</span></div>
                  <div className="flex h-1.5 gap-[2px] overflow-hidden rounded bg-ink-700" title={`${c.pass} pass, ${c.warn} warning, ${c.fail} fail`}>
                    {total > 0 && <>
                      <div style={{ width: `${(c.pass / total) * 100}%`, background: "#0aac23" }} />
                      <div style={{ width: `${(c.warn / total) * 100}%`, background: "#fbb315" }} />
                      <div style={{ width: `${(c.fail / total) * 100}%`, background: "#dc3c3d" }} />
                    </>}
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
        <Card title="Methodology">
          <p className="text-xs leading-5 text-muted">{p.methodology}</p>
          {outOfScope && (
            <p className="mt-3 flex gap-2 text-xs text-warn"><MinusCircle className="h-4 w-4 shrink-0" />
              Website, security.txt and lookalike checks only run when the domain is in the authorised scope.</p>
          )}
        </Card>
      </div>
      <div>
        <div className="mb-3 flex flex-wrap gap-1">
          {(["all", ...ORDER] as const).map((s) => (
            <button key={s} onClick={() => setFilter(s)} aria-pressed={filter === s}
              className={cx("flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs", filter === s ? "border-accent bg-accent-soft text-white" : "border-line text-muted hover:text-white")}>
              {s !== "all" && <span className={STATUS[s].cls}>{STATUS[s].icon}</span>}
              {s === "all" ? "All" : STATUS[s].label} <span className="font-mono">({s === "all" ? p.checks.length : counts[s]})</span>
            </button>
          ))}
        </div>
        <ul className="space-y-2">{shown.map((c) => <CheckRow key={c.id} c={c} />)}</ul>
      </div>
    </div>
  );
}
