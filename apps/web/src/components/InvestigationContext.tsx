"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";
import { useApi } from "@/lib/hooks";
import { fmtDate, LEGAL_BASIS_LABEL, TYPE_LABEL } from "@/lib/format";
import type { InvestigationDetail } from "@/lib/types";
import { cx, ErrorBox, Spinner, StatusPill } from "./ui";

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

const TABS = [
  { suffix: "", label: "Results" },
  { suffix: "/graph", label: "Entity graph" },
  { suffix: "/timeline", label: "Evidence timeline" },
  { suffix: "/report", label: "Analysis & reports" },
];

export function InvestigationProvider({ children }: { children: ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const { data, error, reload } = useApi<InvestigationDetail>(`/api/v1/investigations/${id}`, {
    pollMs: 2000,
    until: (d) => d.status === "completed" || d.status === "failed" || d.status === "draft",
  });
  if (error) return <ErrorBox messages={error.messages} />;
  if (!data) return <Spinner label="Loading investigation" />;
  const base = `/investigations/${id}`;
  const prog = data.progress ?? {};
  const running = data.status === "queued" || data.status === "running";

  return (
    <InvestigationCtx.Provider value={{ inv: data, reload }}>
      <div className="mb-5 space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold text-white">{data.title}</h1>
            <p className="mt-1 text-sm text-muted">
              {TYPE_LABEL[data.subject_type] ?? data.subject_type}: <span className="font-mono text-slate-200">{data.subject}</span> ·{" "}
              {data.subject_kind} · {LEGAL_BASIS_LABEL[data.legal_basis] ?? data.legal_basis}
              {data.authorization_reference && <> · ref {data.authorization_reference}</>}
            </p>
            <p className="text-xs text-muted">
              Created {fmtDate(data.created_at)} · collection {fmtDate(data.started_at)} → {fmtDate(data.finished_at)} · retained until {fmtDate(data.retention_until, false)}
            </p>
          </div>
          <div className="shrink-0 self-start"><StatusPill status={data.status} /></div>
        </div>
        {running && (
          <div className="rounded-lg border border-line bg-ink-850 p-3" role="status" aria-live="polite">
            <div className="mb-2 flex justify-between text-xs text-muted">
              <span>Collecting from public sources…</span>
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
          {TABS.map((t) => {
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
