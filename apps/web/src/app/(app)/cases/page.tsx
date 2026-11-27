"use client";

import { Briefcase, FolderSearch, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useUser } from "@/components/AppShell";
import { Button, cx, EmptyState, ErrorBox, Field, inputClass, Modal, PageHeader, RiskBadge, SkeletonRows, TlpBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate, TYPE_LABEL } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { CaseSummary } from "@/lib/types";

export default function CasesPage() {
  const user = useUser();
  const router = useRouter();
  const [status, setStatus] = useState<"open" | "closed" | "">("open");
  const { data } = useApi<CaseSummary[]>(`/api/v1/cases${status ? `?status=${status}` : ""}`);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tlp, setTlp] = useState("amber");
  const [errors, setErrors] = useState<string[]>([]);
  const canCreate = user?.role === "admin" || user?.role === "analyst";

  async function create() {
    try {
      const c = await api<CaseSummary>("/api/v1/cases", { method: "POST", json: { title, description: description || undefined, tlp } });
      router.push(`/cases/${c.id}`);
    } catch (e) {
      setErrors(e instanceof ApiError ? e.messages : [String(e)]);
    }
  }

  return (
    <>
      <PageHeader title="Cases" subtitle="Group related investigations – an organisation, its domains, people who consented and every pivot – and analyse them together."
        actions={canCreate && <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" />New case</Button>} />
      <div className="mb-4 flex gap-1">
        {(["open", "closed", ""] as const).map((s) => (
          <button key={s || "all"} onClick={() => setStatus(s)} aria-pressed={status === s}
            className={cx("rounded-md border px-3 py-1.5 text-xs", status === s ? "border-accent bg-accent-soft text-white" : "border-line text-muted")}>
            {s ? s[0]!.toUpperCase() + s.slice(1) : "All"}
          </button>
        ))}
      </div>
      {!data ? <SkeletonRows rows={4} /> : data.length === 0 ? (
        <EmptyState title="No cases yet">Create a case, or pivot from any investigation – a case is created automatically.</EmptyState>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((c) => (
            <Link key={c.id} href={`/cases/${c.id}`} className="group rounded-lg border border-line bg-ink-850/80 p-4 hover:border-accent/50">
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <Briefcase className="h-4 w-4 shrink-0 text-accent" />
                  <h2 className="truncate font-medium text-slate-100 group-hover:text-white">{c.title}</h2>
                </div>
                <TlpBadge tlp={c.tlp} />
              </div>
              {c.description && <p className="mt-2 line-clamp-2 text-sm text-muted">{c.description}</p>}
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
                <span className="flex items-center gap-1"><FolderSearch className="h-3.5 w-3.5" />{c.investigation_count} investigations</span>
                <span>{c.finding_count} findings</span>
                {c.risk_level !== "none" && <RiskBadge level={c.risk_level} />}
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {c.subject_types.map((t) => <span key={t} className="rounded border border-line px-1.5 text-[10px] text-muted">{TYPE_LABEL[t] ?? t}</span>)}
              </div>
              <div className="mt-3 text-[11px] text-muted">Updated {fmtDate(c.updated_at)} · {c.status}</div>
            </Link>
          ))}
        </div>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="New case">
        <div className="space-y-3">
          <Field label="Title" htmlFor="c-title"><input id="c-title" className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} /></Field>
          <Field label="Description" htmlFor="c-desc" help="Stored encrypted.">
            <textarea id="c-desc" rows={3} className={inputClass} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={8000} />
          </Field>
          <Field label="Sharing (TLP 2.0)" htmlFor="c-tlp">
            <select id="c-tlp" className={inputClass} value={tlp} onChange={(e) => setTlp(e.target.value)}>
              {["clear", "green", "amber", "amber+strict", "red"].map((t) => <option key={t} value={t}>TLP:{t.toUpperCase()}</option>)}
            </select>
          </Field>
          <ErrorBox messages={errors} />
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button disabled={!title} onClick={create}>Create case</Button></div>
        </div>
      </Modal>
    </>
  );
}
