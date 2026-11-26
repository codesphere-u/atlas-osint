"use client";

import Link from "next/link";
import { useState } from "react";
import { useApi } from "@/lib/hooks";
import { fmtDate, TYPE_LABEL } from "@/lib/format";
import type { Investigation } from "@/lib/types";
import { Card, EmptyState, inputClass, PageHeader, Spinner, StatusPill } from "@/components/ui";

export default function HistoryPage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [mine, setMine] = useState(false);
  const params = new URLSearchParams({ limit: "200" });
  if (q) params.set("q", q);
  if (status) params.set("status", status);
  if (type) params.set("subject_type", type);
  if (mine) params.set("mine", "true");
  const { data, loading } = useApi<Investigation[]>(`/api/v1/investigations?${params}`);

  return (
    <>
      <PageHeader title="Investigation history" subtitle="Search by title or by the exact identifier (identifiers are matched by keyed hash)." />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-4">
          <input aria-label="Search" placeholder="Title or exact identifier" className={inputClass} value={q} onChange={(e) => setQ(e.target.value)} />
          <select aria-label="Status" className={inputClass} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {["completed", "running", "queued", "failed", "draft"].map((s) => <option key={s}>{s}</option>)}
          </select>
          <select aria-label="Identifier type" className={inputClass} value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All types</option>
            {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Only mine
          </label>
        </div>
        {loading && !data ? <Spinner /> : !data?.length ? <EmptyState title="No matching investigations" /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-xs uppercase text-muted">
                <tr><th className="py-2">Title</th><th>Type</th><th>Legal basis</th><th>Findings</th><th>Created</th><th>Retention until</th><th>Status</th></tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.map((i) => (
                  <tr key={i.id}>
                    <td className="py-2"><Link href={`/investigations/${i.id}`} className="text-slate-100 hover:text-accent">{i.title}</Link></td>
                    <td className="text-muted">{TYPE_LABEL[i.subject_type] ?? i.subject_type}</td>
                    <td className="text-muted">{i.legal_basis}</td>
                    <td className="font-mono">{i.finding_count} <span className="text-ok">({i.confirmed_count})</span></td>
                    <td className="text-muted">{fmtDate(i.created_at)}</td>
                    <td className="text-muted">{fmtDate(i.retention_until, false)}</td>
                    <td><StatusPill status={i.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
