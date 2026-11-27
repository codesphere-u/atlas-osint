"use client";

import { BellOff, BellRing, Minus, Plus } from "lucide-react";
import { useState } from "react";
import { ColumnChart } from "@/components/charts";
import { useUser } from "@/components/AppShell";
import { useInvestigation } from "@/components/InvestigationContext";
import { Button, Card, EmptyState, inputClass, SkeletonRows } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useToast } from "@/lib/toast";
import type { Assessment } from "@/lib/types";

const INTERVALS = [
  { v: 6, label: "Every 6 hours" }, { v: 24, label: "Daily" }, { v: 72, label: "Every 3 days" },
  { v: 168, label: "Weekly" }, { v: 720, label: "Every 30 days" },
];

export default function ChangesPage() {
  const { inv, reload } = useInvestigation();
  const user = useUser();
  const toast = useToast();
  const done = inv.status === "completed";
  const { data, reload: reloadAssessment } = useApi<Assessment>(done ? `/api/v1/investigations/${inv.id}/assessment` : null);
  const [interval, setInterval_] = useState<string>("");
  const owner = !!user && (user.role === "admin" || (user.role === "analyst" && user.id === inv.created_by));
  if (!done || !data) return <SkeletonRows rows={4} />;
  const ch = data.changes;

  async function setMonitoring(hours: number | null) {
    try {
      await api(`/api/v1/investigations/${inv.id}/monitoring`, { method: "PUT", json: { interval_hours: hours } });
      toast("success", hours ? "Monitoring enabled" : "Monitoring disabled", hours ? `Re-collected every ${hours} hours; changes appear here.` : undefined);
      await Promise.all([reload(), reloadAssessment()]);
    } catch (e) {
      toast("error", "Could not update monitoring", e instanceof ApiError ? e.messages.join(" ") : String(e));
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <div className="space-y-6 xl:col-span-2">
        <Card title={ch && !ch.baseline ? `Changes since ${fmtDate(ch.compared_to)}` : "Changes"}>
          {!ch || ch.baseline ? (
            <EmptyState title="Baseline collection">This is the first run. Re-run the collection or enable monitoring to detect what changes.</EmptyState>
          ) : ch.added_count + ch.removed_count === 0 ? (
            <p className="text-sm text-muted">No changes: all {ch.unchanged_count} findings are unchanged.</p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[#34d399]"><Plus className="h-3.5 w-3.5" />New ({ch.added_count})</h3>
                <ul className="space-y-1.5 text-sm">
                  {ch.added.map((a, i) => (
                    <li key={i} className="rounded border border-line px-2 py-1.5">
                      <div className="text-slate-100">{a.title}</div>
                      <div className="text-[11px] text-muted">{a.source}{a.flags?.length ? <span className="ml-2 text-[#f18a59]">{a.flags.join(", ")}</span> : null}</div>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[#ff8a8b]"><Minus className="h-3.5 w-3.5" />No longer observed ({ch.removed_count})</h3>
                <ul className="space-y-1.5 text-sm">
                  {ch.removed.map((a, i) => (
                    <li key={i} className="rounded border border-line px-2 py-1.5"><div className="text-slate-300 line-through decoration-slate-600">{a.title}</div>
                      <div className="text-[11px] text-muted">{a.source}</div></li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </Card>
        <Card title="Run history">
          {data.run_history.length < 2 ? <p className="text-sm text-muted">One run so far.</p> : (
            <ColumnChart ariaLabel="Findings per collection run" valueLabel="findings"
              data={data.run_history.map((r, i) => ({
                key: r.at + i, label: `#${i + 1}`, value: r.findings,
                tooltip: <>{r.findings} findings · +{r.added}/−{r.removed}{r.grade ? ` · grade ${r.grade}` : ""} · {r.trigger}<br />{fmtDate(r.at)}</>,
              }))} />
          )}
        </Card>
      </div>
      <Card title={<span className="flex items-center gap-2">{inv.monitor_interval_hours ? <BellRing className="h-4 w-4 text-accent" /> : <BellOff className="h-4 w-4 text-muted" />}Monitoring</span>}>
        {!data.monitoring.allowed ? (
          <p className="text-sm text-muted">Scheduled monitoring is only available for organisations and infrastructure. Continuous monitoring of individuals is not supported, by design.</p>
        ) : (
          <div className="space-y-3 text-sm">
            <p className="text-muted">
              {inv.monitor_interval_hours
                ? <>Re-collected every <span className="text-slate-100">{inv.monitor_interval_hours} hours</span>. Next run {fmtDate(data.monitoring.next_run_at)}.</>
                : "Re-collect automatically and record what changed: new subdomains, open ports, certificates, registrations, lookalikes or sanctions entries."}
            </p>
            {owner && (
              <>
                <select aria-label="Monitoring interval" className={inputClass} value={interval || String(inv.monitor_interval_hours ?? "")}
                  onChange={(e) => setInterval_(e.target.value)}>
                  <option value="">Choose an interval…</option>
                  {INTERVALS.map((i) => <option key={i.v} value={i.v}>{i.label}</option>)}
                </select>
                <div className="flex gap-2">
                  <Button disabled={!interval && !inv.monitor_interval_hours} onClick={() => setMonitoring(Number(interval || inv.monitor_interval_hours))}>Save schedule</Button>
                  {inv.monitor_interval_hours ? <Button variant="ghost" onClick={() => setMonitoring(null)}>Stop</Button> : null}
                </div>
                <p className="text-xs text-muted">Monitoring stops automatically at the retention date ({fmtDate(inv.retention_until, false)}).</p>
              </>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
