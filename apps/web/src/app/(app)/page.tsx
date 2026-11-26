"use client";

import Link from "next/link";
import { useApi } from "@/lib/hooks";
import { fmtDate, humanize, TYPE_LABEL } from "@/lib/format";
import type { Investigation } from "@/lib/types";
import { ButtonLink, Card, EmptyState, PageHeader, Spinner, Stat, StatusPill } from "@/components/ui";
import { useUser } from "@/components/AppShell";

interface Stats {
  investigations: number;
  by_status: Record<string, number>;
  by_subject_type: Record<string, number>;
  findings_by_classification: Record<string, number>;
  findings_total: number;
  source_status: Record<string, Record<string, number>>;
  recent: Investigation[];
}

export default function OverviewPage() {
  const user = useUser();
  const { data, loading } = useApi<Stats>("/api/v1/investigations/stats", { pollMs: 15000 });
  const canCreate = user?.role === "admin" || user?.role === "analyst";
  const cls = data?.findings_by_classification ?? {};
  const unhealthy = Object.entries(data?.source_status ?? {})
    .map(([name, s]) => ({ name, bad: (s.unavailable ?? 0) + (s.error ?? 0) + (s.rate_limited ?? 0), total: Object.values(s).reduce((a, b) => a + b, 0) }))
    .filter((s) => s.bad > 0)
    .sort((a, b) => b.bad - a.bad)
    .slice(0, 6);

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Investigations, evidence quality and source health at a glance."
        actions={canCreate && <ButtonLink href="/investigations/new" variant="primary">New investigation</ButtonLink>}
      />
      {loading && !data ? (
        <Spinner />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Investigations" value={data?.investigations ?? 0} hint={`${data?.by_status.running ?? 0} running · ${data?.by_status.failed ?? 0} failed`} />
            <Stat label="Findings" value={data?.findings_total ?? 0} hint="All collected, evidence-backed items" />
            <Stat label="Confirmed" value={cls.confirmed ?? 0} hint={`${cls.possible ?? 0} possible · ${cls.unverified ?? 0} unverified`} />
            <Stat label="Rejected by analysts" value={cls.rejected ?? 0} hint="Excluded from conclusions" />
          </div>
          <div className="grid gap-6 lg:grid-cols-3">
            <Card title="Recent investigations" className="lg:col-span-2" actions={<Link href="/history" className="text-xs text-accent hover:underline">View all</Link>}>
              {data?.recent.length ? (
                <ul className="divide-y divide-line">
                  {data.recent.map((i) => (
                    <li key={i.id} className="flex flex-col gap-1 py-2 sm:flex-row sm:items-center sm:justify-between">
                      <Link href={`/investigations/${i.id}`} className="min-w-0 truncate text-sm text-slate-100 hover:text-accent">
                        {i.title}
                        <span className="ml-2 text-xs text-muted">{TYPE_LABEL[i.subject_type] ?? i.subject_type}</span>
                      </Link>
                      <div className="flex shrink-0 items-center gap-3 text-xs text-muted">
                        <span>{i.finding_count} findings</span>
                        <span>{fmtDate(i.created_at)}</span>
                        <StatusPill status={i.status} />
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title="No investigations yet">Start one from a module page or “New investigation”.</EmptyState>
              )}
            </Card>
            <div className="space-y-6">
              <Card title="By identifier type">
                <ul className="space-y-1 text-sm">
                  {Object.entries(data?.by_subject_type ?? {}).map(([t, n]) => (
                    <li key={t} className="flex justify-between"><span className="text-slate-300">{TYPE_LABEL[t] ?? t}</span><span className="font-mono">{n}</span></li>
                  ))}
                  {!Object.keys(data?.by_subject_type ?? {}).length && <li className="text-muted">No data yet.</li>}
                </ul>
              </Card>
              <Card title="Source health (recent runs)" actions={<Link href="/sources" className="text-xs text-accent hover:underline">Sources</Link>}>
                {unhealthy.length ? (
                  <ul className="space-y-1 text-sm">
                    {unhealthy.map((s) => (
                      <li key={s.name} className="flex justify-between"><span className="text-slate-300">{humanize(s.name)}</span><span className="font-mono text-warn">{s.bad}/{s.total} failed</span></li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted">No failing sources in recent investigations.</p>
                )}
              </Card>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
