"use client";

import { BellRing, Briefcase, CornerLeftUp, Radio } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";
import { useApi } from "@/lib/hooks";
import { fmtDate, LEGAL_BASIS_LABEL, TYPE_LABEL } from "@/lib/format";
import type { InvestigationDetail } from "@/lib/types";
import { cx, ErrorBox, GradeBadge, RiskBadge, Skeleton, StatusPill, TlpBadge } from "./ui";

interface Ctx {
  inv: InvestigationDetail;
  reload: () => Promise<unknown>;
}

const InvestigationCtx = createContext<Ctx | null>(null);

export function useInvestigation(): Ctx {
  const v = useContext(InvestigationCtx);
  if (!v) throw new Error("useInvestigation outside provider");
  return v;
}

const INFRA = new Set(["domain", "url", "ip"]);

export function InvestigationProvider({ children }: { children: ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const { data, error, reload } = useApi<InvestigationDetail>(`/api/v1/investigations/${id}`, {
    pollMs: 2000,
    until: (d) => d.status === "completed" || d.status === "failed" || d.status === "draft",
  });
  if (error) return <ErrorBox messages={error.messages} />;
  if (!data) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-1/2" /><Skeleton className="h-4 w-2/3" /><Skeleton className="h-10 w-full" />
      </div>
    );
  }
  const base = `/investigations/${id}`;
  const prog = data.progress ?? {};
  const running = data.status === "queued" || data.status === "running";
  const tabs = [
    { suffix: "", label: "Findings" },
    ...(INFRA.has(data.subject_type) ? [{ suffix: "/exposure", label: "Exposure" }] : []),
    { suffix: "/graph", label: "Entity graph" },
    { suffix: "/timeline", label: "Timeline" },
    { suffix: "/changes", label: "Changes & monitoring" },
    { suffix: "/report", label: "Analysis & reports" },
  ];

  return (
    <InvestigationCtx.Provider value={{ inv: data, reload }}>
      <div className="mb-5 space-y-3">
        {(data.case_id || data.parent_id) && (
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
            {data.case_id && (
              <Link href={`/cases/${data.case_id}`} className="flex items-center gap-1 hover:text-accent"><Briefcase className="h-3.5 w-3.5" />Case</Link>
            )}
            {data.parent_id && (
              <Link href={`/investigations/${data.parent_id}`} className="flex items-center gap-1 hover:text-accent"><CornerLeftUp className="h-3.5 w-3.5" />Pivoted from parent investigation</Link>
            )}
          </div>
        )}
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <TlpBadge tlp={data.tlp} />
              <h1 className="min-w-0 truncate text-xl font-semibold text-white">{data.title}</h1>
            </div>
            <p className="mt-1 text-sm text-muted">
              {TYPE_LABEL[data.subject_type] ?? data.subject_type}: <span className="font-mono text-slate-200">{data.subject}</span> ·{" "}
              {data.subject_kind} · {LEGAL_BASIS_LABEL[data.legal_basis] ?? data.legal_basis}
              {data.authorization_reference && <> · ref {data.authorization_reference}</>}
            </p>
            <p className="text-xs text-muted">
              Collected {fmtDate(data.finished_at ?? data.started_at)} · run {data.run_count || 1} · retained until {fmtDate(data.retention_until, false)}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2 self-start">
            {data.monitor_interval_hours ? (
              <span className="flex items-center gap-1 rounded-full border border-accent/40 px-2 py-0.5 text-[11px] text-accent" title={`Next run ${fmtDate(data.next_run_at)}`}>
                <BellRing className="h-3 w-3" /> Monitored every {data.monitor_interval_hours}h
              </span>
            ) : null}
            <GradeBadge grade={data.posture_grade} />
            <RiskBadge level={data.risk_level} />
            <StatusPill status={data.status} />
          </div>
        </div>
        {running && (
          <div className="rounded-lg border border-line bg-ink-850 p-3" role="status" aria-live="polite">
            <div className="mb-2 flex justify-between text-xs text-muted">
              <span className="flex items-center gap-1.5"><Radio className="h-3.5 w-3.5 animate-pulse text-accent" />Collecting from public sources…</span>
              <span className="font-mono">{prog.done ?? 0}/{prog.total || "?"}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-ink-700">
              <div className="h-full bg-accent transition-all" style={{ width: `${prog.total ? ((prog.done ?? 0) / prog.total) * 100 : 5}%` }} />
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {Object.entries(prog.sources ?? {}).map(([s, st]) => (
                <span key={s} className="text-[11px]"><StatusPill status={st} /> <span className="text-muted">{s}</span></span>
              ))}
            </div>
          </div>
        )}
        {data.status === "failed" && <ErrorBox messages={[`Investigation failed: ${data.error ?? "unknown error"}`]} />}
        <nav aria-label="Investigation sections" className="flex gap-1 overflow-x-auto border-b border-line">
          {tabs.map((t) => {
            const href = base + t.suffix;
            const active = t.suffix ? pathname.startsWith(href) : pathname === base;
            return (
              <Link key={t.suffix} href={href} aria-current={active ? "page" : undefined}
                className={cx("whitespace-nowrap border-b-2 px-3 py-2 text-sm", active ? "border-accent text-white" : "border-transparent text-muted hover:text-white")}>
                {t.label}
              </Link>
            );
          })}
        </nav>
      </div>
      {children}
    </InvestigationCtx.Provider>
  );
}
