"use client";

import { Download, FileJson, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useUser } from "@/components/AppShell";
import { GraphWorkspace } from "@/components/GraphWorkspace";
import { TimelineView } from "@/components/TimelineView";
import {
  Button, ButtonLink, Card, cx, ErrorBox, GradeBadge, inputClass, PageHeader, RiskBadge, SkeletonRows, Stat, StatusPill, TlpBadge,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate, TYPE_LABEL } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useToast } from "@/lib/toast";
import type { CaseDetail, TimelineEvent } from "@/lib/types";

type Tab = "investigations" | "graph" | "timeline" | "settings";

function CaseTimeline({ id }: { id: string }) {
  const { data } = useApi<TimelineEvent[]>(`/api/v1/cases/${id}/timeline`);
  return data ? <TimelineView events={data} /> : <SkeletonRows rows={4} />;
}

export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const user = useUser();
  const router = useRouter();
  const toast = useToast();
  const { data, error, reload } = useApi<CaseDetail>(`/api/v1/cases/${id}`);
  const [tab, setTab] = useState<Tab>("investigations");
  const [title, setTitle] = useState<string | null>(null);
  const [description, setDescription] = useState<string | null>(null);
  if (error) return <ErrorBox messages={error.messages} />;
  if (!data) return <SkeletonRows rows={5} />;
  const owner = !!user && (user.role === "admin" || user.id === data.created_by);
  const completed = data.investigations.filter((i) => i.status === "completed").length;

  async function patch(body: Record<string, unknown>) {
    try {
      await api(`/api/v1/cases/${id}`, { method: "PATCH", json: body });
      toast("success", "Case updated");
      await reload();
    } catch (e) {
      toast("error", "Update failed", e instanceof ApiError ? e.messages.join(" ") : String(e));
    }
  }

  return (
    <>
      <PageHeader
        title={<span className="flex items-center gap-2"><TlpBadge tlp={data.tlp} />{data.title}</span>}
        subtitle={data.description || `Created ${fmtDate(data.created_at)}`}
        actions={<>
          <a href={`/api/v1/cases/${id}/export?format=stix`} className="inline-flex items-center gap-2 rounded-md border border-line bg-ink-800 px-3 py-2 text-sm text-slate-200 hover:bg-ink-700"><Download className="h-4 w-4" />STIX 2.1</a>
          <a href={`/api/v1/cases/${id}/export?format=json`} className="inline-flex items-center gap-2 rounded-md border border-line bg-ink-800 px-3 py-2 text-sm text-slate-200 hover:bg-ink-700"><FileJson className="h-4 w-4" />JSON</a>
          {owner && <ButtonLink href={`/investigations/new?case=${id}`} variant="primary"><Plus className="h-4 w-4" />Add investigation</ButtonLink>}
        </>}
      />
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Investigations" value={data.investigation_count} hint={`${completed} completed`} />
        <Stat label="Findings" value={data.finding_count} hint={`${data.confirmed_count} confirmed`} />
        <Stat label="Highest risk" value={<RiskBadge level={data.risk_level} />} />
        <Stat label="Status" value={<span className="capitalize">{data.status}</span>} />
      </div>
      <nav className="mb-5 flex gap-1 overflow-x-auto border-b border-line" aria-label="Case sections">
        {(["investigations", "graph", "timeline", ...(owner ? ["settings"] : [])] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)} aria-current={tab === t ? "page" : undefined}
            className={cx("whitespace-nowrap border-b-2 px-3 py-2 text-sm capitalize", tab === t ? "border-accent text-white" : "border-transparent text-muted hover:text-white")}>
            {t === "graph" ? "Merged graph" : t === "timeline" ? "Merged timeline" : t}
          </button>
        ))}
      </nav>
      {tab === "investigations" && (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-xs uppercase text-muted"><tr><th className="py-2">Investigation</th><th>Type</th><th>Grade</th><th>Risk</th><th>Findings</th><th>Collected</th><th>Status</th></tr></thead>
              <tbody className="divide-y divide-line">
                {data.investigations.map((i) => (
                  <tr key={i.id}>
                    <td className="py-2">
                      <Link href={`/investigations/${i.id}`} className="text-slate-100 hover:text-accent">{i.title}</Link>
                      {i.parent_id && <div className="text-[11px] text-muted">pivot</div>}
                    </td>
                    <td className="text-muted">{TYPE_LABEL[i.subject_type] ?? i.subject_type}</td>
                    <td><GradeBadge grade={i.posture_grade} /></td>
                    <td>{i.risk_level && i.risk_level !== "none" ? <RiskBadge level={i.risk_level} /> : <span className="text-muted">–</span>}</td>
                    <td className="font-mono">{i.finding_count}</td>
                    <td className="text-muted">{fmtDate(i.finished_at)}</td>
                    <td><StatusPill status={i.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {tab === "graph" && (completed ? <GraphWorkspace url={`/api/v1/cases/${id}/graph`} /> : <p className="text-sm text-muted">No completed investigations yet.</p>)}
      {tab === "timeline" && <CaseTimeline id={id} />}
      {tab === "settings" && owner && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Details">
            <div className="space-y-3">
              <input aria-label="Title" className={inputClass} value={title ?? data.title} onChange={(e) => setTitle(e.target.value)} />
              <textarea aria-label="Description" rows={4} className={inputClass} value={description ?? data.description} onChange={(e) => setDescription(e.target.value)} />
              <Button onClick={() => patch({ title: title ?? data.title, description: description ?? data.description })}>Save</Button>
            </div>
          </Card>
          <Card title="Handling">
            <div className="space-y-3 text-sm">
              <label className="block text-xs text-muted">Sharing (TLP 2.0)
                <select className={`${inputClass} mt-1`} value={data.tlp} onChange={(e) => patch({ tlp: e.target.value })}>
                  {["clear", "green", "amber", "amber+strict", "red"].map((t) => <option key={t} value={t}>TLP:{t.toUpperCase()}</option>)}
                </select>
              </label>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => patch({ status: data.status === "open" ? "closed" : "open" })}>
                  {data.status === "open" ? "Close case" : "Reopen case"}
                </Button>
                <Button variant="danger" onClick={async () => {
                  if (!window.confirm("Delete this case? Its investigations are kept and simply unlinked.")) return;
                  await api(`/api/v1/cases/${id}`, { method: "DELETE" });
                  router.push("/cases");
                }}><Trash2 className="h-4 w-4" />Delete case</Button>
              </div>
            </div>
          </Card>
        </div>
      )}
    </>
  );
}
