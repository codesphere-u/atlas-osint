"use client";

import {
  AlertTriangle, ArrowRight, BellRing, Briefcase, CheckCircle2, CircleDashed, CircleHelp, FolderSearch, Search, ShieldAlert,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { CHART, ColumnChart, HealthBars, SegmentedBar } from "@/components/charts";
import { useUser } from "@/components/AppShell";
import { ButtonLink, Card, EmptyState, GradeBadge, PageHeader, RiskBadge, SectionTitle, Skeleton, StatusPill } from "@/components/ui";
import { detectIdentifier } from "@/lib/detect";
import { fmtDate, humanize, TYPE_LABEL } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Stats } from "@/lib/types";

function Kpi({ label, value, hint, icon }: { label: string; value: React.ReactNode; hint?: React.ReactNode; icon: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-ink-850/80 p-4">
      <div className="flex items-center justify-between text-xs uppercase tracking-wide text-muted">{label}<span className="text-muted">{icon}</span></div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

function Omnibox() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const detected = detectIdentifier(q);
  function submit(e: FormEvent) {
    e.preventDefault();
    if (detected) router.push(`/investigations/new?type=${detected.type}&subject=${encodeURIComponent(detected.value)}`);
  }
  return (
    <form onSubmit={submit} className="rounded-xl border border-line bg-gradient-to-br from-ink-850 to-ink-900 p-4 sm:p-5">
      <label htmlFor="omnibox" className="text-sm font-medium text-slate-200">Start an investigation</label>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
          <input id="omnibox" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off"
            placeholder="Domain, IP, email, phone (+44…), @handle, person or organisation name"
            className="h-11 w-full rounded-lg border border-line bg-ink-950 pl-9 pr-3 text-sm text-slate-100 placeholder:text-slate-500 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent" />
        </div>
        <button type="submit" disabled={!detected}
          className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-accent px-4 text-sm font-medium text-ink-950 hover:bg-blue-400 disabled:bg-accent/30">
          Investigate <ArrowRight className="h-4 w-4" />
        </button>
      </div>
      <p className="mt-2 h-4 text-xs text-muted" aria-live="polite">
        {detected ? <>Detected <span className="text-slate-200">{TYPE_LABEL[detected.type]}</span> – you will confirm the authorisation record next.</> : q ? "Not a recognised identifier yet." : " "}
      </p>
    </form>
  );
}

export default function OverviewPage() {
  const user = useUser();
  const { data, loading } = useApi<Stats>("/api/v1/investigations/stats", { pollMs: 20000 });
  const canCreate = user?.role === "admin" || user?.role === "analyst";
  const cls = data?.findings_by_classification ?? {};
  const days = Object.entries(data?.by_day ?? {});
  const health = Object.entries(data?.source_status ?? {})
    .map(([name, s]) => ({
      key: name, label: humanize(name),
      ok: (s.ok ?? 0) + (s.no_results ?? 0),
      failed: (s.unavailable ?? 0) + (s.error ?? 0) + (s.rate_limited ?? 0),
    }))
    .filter((r) => r.ok + r.failed > 0)
    .sort((a, b) => b.failed - a.failed || b.ok - a.ok)
    .slice(0, 8);

  return (
    <>
      <PageHeader title="Overview" subtitle="Investigations, evidence quality, risk and source health at a glance."
        actions={canCreate && <ButtonLink href="/investigations/new" variant="primary">New investigation</ButtonLink>} />
      <div className="space-y-6">
        {canCreate && <Omnibox />}
        {loading && !data ? (
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <Kpi label="Investigations" value={data?.investigations ?? 0} icon={<FolderSearch className="h-4 w-4" />}
                hint={`${data?.by_status.running ?? 0} running · ${data?.monitored ?? 0} monitored`} />
              <Kpi label="Cases" value={data?.cases ?? 0} icon={<Briefcase className="h-4 w-4" />} hint="Grouped investigations" />
              <Kpi label="Confirmed findings" value={cls.confirmed ?? 0} icon={<CheckCircle2 className="h-4 w-4" />}
                hint={`of ${data?.findings_total ?? 0} evidence-backed findings`} />
              <Kpi label="High-risk subjects" value={(data?.risk_levels.critical ?? 0) + (data?.risk_levels.high ?? 0)}
                icon={<ShieldAlert className="h-4 w-4" />} hint={`${data?.risk_levels.medium ?? 0} medium · ${data?.risk_levels.none ?? 0} clear`} />
            </div>
            <div className="grid gap-6 xl:grid-cols-3">
              <Card title="Investigations started – last 30 days" className="xl:col-span-2">
                <ColumnChart ariaLabel="Investigations started per day, last 30 days" valueLabel="investigations"
                  data={days.map(([d, v]) => ({ key: d, label: d.slice(5), value: v }))} />
              </Card>
              <Card title="Evidence quality">
                <SegmentedBar ariaLabel="Findings by classification" segments={[
                  { key: "confirmed", label: "Confirmed", value: cls.confirmed ?? 0, color: CHART.good, icon: <CheckCircle2 className="h-3 w-3 text-slate-400" /> },
                  { key: "possible", label: "Possible", value: cls.possible ?? 0, color: CHART.series1, icon: <CircleHelp className="h-3 w-3 text-slate-400" /> },
                  { key: "unverified", label: "Unverified", value: cls.unverified ?? 0, color: CHART.warning, icon: <CircleDashed className="h-3 w-3 text-slate-400" /> },
                  { key: "rejected", label: "Rejected", value: cls.rejected ?? 0, color: CHART.critical, icon: <XCircle className="h-3 w-3 text-slate-400" /> },
                ]} />
                <p className="mt-4 text-xs text-muted">Confirmed = source-backed claim established; it never by itself identifies a person.</p>
                {Object.keys(data?.posture_grades ?? {}).length > 0 && (
                  <div className="mt-4 border-t border-line pt-3">
                    <div className="mb-2 text-xs text-muted">Exposure grades</div>
                    <div className="flex flex-wrap gap-3">
                      {["A", "B", "C", "D", "F"].filter((g) => data?.posture_grades[g]).map((g) => (
                        <span key={g} className="flex items-center gap-1.5 text-sm"><GradeBadge grade={g} /><span className="font-mono text-slate-300">×{data?.posture_grades[g]}</span></span>
                      ))}
                    </div>
                  </div>
                )}
              </Card>
            </div>
            <div className="grid gap-6 xl:grid-cols-3">
              <Card className="xl:col-span-2">
                <SectionTitle icon={<AlertTriangle className="h-4 w-4 text-[#f18a59]" />}>Needs attention</SectionTitle>
                {data?.attention.length ? (
                  <ul className="divide-y divide-line">
                    {data.attention.map((a, i) => (
                      <li key={i} className="flex flex-col gap-1 py-2.5 sm:flex-row sm:items-center sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 text-sm text-slate-100"><RiskBadge level={a.severity} />{a.title}</div>
                          <div className="truncate text-xs text-muted">{a.detail}</div>
                        </div>
                        <Link href={`/investigations/${a.investigation_id}`} className="shrink-0 text-xs text-accent hover:underline">{a.investigation}</Link>
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-sm text-muted">No critical or high-severity highlights in recent investigations.</p>}
              </Card>
              <Card>
                <SectionTitle icon={<BellRing className="h-4 w-4 text-accent" />}>Recent changes</SectionTitle>
                {data?.recent_changes.length ? (
                  <ul className="space-y-3">
                    {data.recent_changes.map((c) => (
                      <li key={c.investigation_id + c.at} className="text-sm">
                        <Link href={`/investigations/${c.investigation_id}/changes`} className="text-slate-100 hover:text-accent">{c.title}</Link>
                        <div className="text-xs text-muted">
                          <span className="text-ok">+{c.added}</span> / <span className="text-bad">−{c.removed}</span> · {fmtDate(c.at)}
                        </div>
                        {c.sample.length > 0 && <div className="truncate text-xs text-muted">{c.sample.join(" · ")}</div>}
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-sm text-muted">Re-run or monitor an investigation to see what changed between collections.</p>}
              </Card>
            </div>
            <div className="grid gap-6 xl:grid-cols-3">
              <Card title="Recent investigations" className="xl:col-span-2" actions={<Link href="/history" className="text-xs text-accent hover:underline">View all</Link>}>
                {data?.recent.length ? (
                  <ul className="divide-y divide-line">
                    {data.recent.map((i) => (
                      <li key={i.id} className="flex flex-col gap-1 py-2 sm:flex-row sm:items-center sm:justify-between">
                        <Link href={`/investigations/${i.id}`} className="min-w-0 truncate text-sm text-slate-100 hover:text-accent">
                          {i.title}<span className="ml-2 text-xs text-muted">{TYPE_LABEL[i.subject_type] ?? i.subject_type}</span>
                        </Link>
                        <div className="flex shrink-0 items-center gap-2 text-xs text-muted">
                          <GradeBadge grade={i.posture_grade} />
                          {i.risk_level && i.risk_level !== "none" && <RiskBadge level={i.risk_level} />}
                          <span>{i.finding_count} findings</span>
                          <span className="hidden sm:inline">{fmtDate(i.created_at)}</span>
                          <StatusPill status={i.status} />
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : <EmptyState title="No investigations yet">Paste an identifier above to start.</EmptyState>}
              </Card>
              <Card title="Source health (recent runs)" actions={<Link href="/sources" className="text-xs text-accent hover:underline">Sources</Link>}>
                {health.length ? <HealthBars rows={health} /> : <p className="text-sm text-muted">No source runs yet.</p>}
              </Card>
            </div>
          </>
        )}
      </div>
    </>
  );
}
