"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError, reportUrl } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { fmtDate } from "@/lib/format";
import { useToast } from "@/lib/toast";
import type { Analysis, CaseSummary, Note, Statement } from "@/lib/types";
import { useInvestigation } from "@/components/InvestigationContext";
import { useUser } from "@/components/AppShell";
import { Badge, Button, Card, ErrorBox, inputClass, Spinner } from "@/components/ui";

function Statements({ items, empty }: { items: Statement[]; empty: string }) {
  if (!items.length) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <ul className="space-y-2 text-sm">
      {items.map((s, i) => (
        <li key={i} className="text-slate-300">
          {s.statement}
          <span className="ml-2 font-mono text-[10px] text-muted">[{s.finding_ids.map((f) => f.slice(0, 6)).join(", ")}]</span>
        </li>
      ))}
    </ul>
  );
}

function Handling() {
  const { inv, reload } = useInvestigation();
  const toast = useToast();
  const { data: cases } = useApi<CaseSummary[]>("/api/v1/cases?status=open");
  async function patch(body: Record<string, unknown>, label: string) {
    try {
      await api(`/api/v1/investigations/${inv.id}`, { method: "PATCH", json: body });
      toast("success", label);
      await reload();
    } catch (e) {
      toast("error", "Update failed", e instanceof ApiError ? e.messages.join(" ") : String(e));
    }
  }
  return (
    <Card title="Handling">
      <div className="space-y-3 text-sm">
        <label className="block text-xs text-muted">Sharing (TLP 2.0)
          <select className={`${inputClass} mt-1`} value={inv.tlp} onChange={(e) => patch({ tlp: e.target.value }, `Marked TLP:${e.target.value.toUpperCase()}`)}>
            {["clear", "green", "amber", "amber+strict", "red"].map((t) => <option key={t} value={t}>TLP:{t.toUpperCase()}</option>)}
          </select>
        </label>
        <label className="block text-xs text-muted">Case
          <select className={`${inputClass} mt-1`} value={inv.case_id ?? ""}
            onChange={(e) => patch(e.target.value ? { case_id: e.target.value } : { remove_from_case: true }, e.target.value ? "Added to case" : "Removed from case")}>
            <option value="">No case</option>
            {cases?.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
        </label>
      </div>
    </Card>
  );
}

export default function ReportPage() {
  const { inv, reload } = useInvestigation();
  const user = useUser();
  const router = useRouter();
  const done = inv.status === "completed";
  const { data: analysis, setData: setAnalysis } = useApi<Analysis>(done ? `/api/v1/investigations/${inv.id}/analysis` : null);
  const { data: notes, reload: reloadNotes } = useApi<Note[]>(`/api/v1/investigations/${inv.id}/notes`);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const owner = !!user && (user.role === "admin" || (user.role === "analyst" && user.id === inv.created_by));

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setErrors([]);
    try {
      await fn();
    } catch (e) {
      setErrors(e instanceof ApiError ? e.messages : [String(e)]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <div className="space-y-6 xl:col-span-2">
        {!done ? <Spinner label="Waiting for collection to finish" /> : !analysis ? <Spinner /> : (
          <>
            <Card
              title="Intelligence analysis"
              actions={<div className="flex items-center gap-2">
                <Badge className={analysis.ai_generated ? "border-warn/50 text-warn" : undefined}>
                  {analysis.ai_generated ? `AI narrative · ${analysis.provider}/${analysis.model}` : "Deterministic"}
                </Badge>
                {owner && <Button variant="secondary" disabled={busy} onClick={() => run(async () => {
                  setAnalysis(await api<Analysis>(`/api/v1/investigations/${inv.id}/analysis?use_ai=true`, { method: "POST" }));
                })}>Regenerate</Button>}
              </div>}
            >
              <p className="whitespace-pre-line text-sm text-slate-300">{analysis.summary}</p>
              {analysis.ai_generated && (
                <p className="mt-3 rounded border border-warn/40 bg-warn/10 p-2 text-xs text-warn">
                  AI statements were validated against cited findings; anything unsupported was downgraded or dropped. Review before relying on it.
                </p>
              )}
              <p className="mt-3 text-xs text-muted">Generated {fmtDate(analysis.generated_at)}. {analysis.disclaimer}</p>
            </Card>
            <div className="grid gap-6 lg:grid-cols-2">
              <Card title={`Confirmed facts (${analysis.confirmed_facts.length})`}><Statements items={analysis.confirmed_facts} empty="No confirmed facts." /></Card>
              <Card title={`Possible matches (${analysis.possible_matches.length})`}><Statements items={analysis.possible_matches} empty="No possible matches." /></Card>
              <Card title="Unknowns & insufficient evidence">
                <ul className="list-inside list-disc space-y-1 text-sm text-slate-300">
                  {[...analysis.insufficient_evidence, ...analysis.unknowns].slice(0, 40).map((u, i) => <li key={i}>{u}</li>)}
                </ul>
              </Card>
              <Card title={`Inconsistencies (${analysis.inconsistencies.length})`}><Statements items={analysis.inconsistencies} empty="No contradictions or name collisions detected." /></Card>
            </div>
            <Card title="Relationships explained"><Statements items={analysis.relationships.slice(0, 50)} empty="No relationships." /></Card>
            <Card title="Why each confidence score was assigned">
              <div className="max-h-96 space-y-3 overflow-y-auto pr-2">
                {analysis.confidence_explanations.map((c) => (
                  <div key={c.finding_id} className="text-sm">
                    <div className="flex justify-between gap-2"><span className="text-slate-200">{c.title}</span><span className="font-mono text-xs">{Math.round(c.score * 100)}%</span></div>
                    <ul className="ml-4 list-disc text-xs text-muted">{c.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
                  </div>
                ))}
              </div>
            </Card>
            {(analysis.validation_notes.length > 0 || Object.keys(analysis.injection_flags).length > 0) && (
              <Card title="Safety & validation log">
                <ul className="list-inside list-disc space-y-1 text-xs text-muted">
                  {analysis.validation_notes.map((n, i) => <li key={i}>{n}</li>)}
                  {Object.entries(analysis.injection_flags).map(([fid, flags]) => (
                    <li key={fid}>Finding {fid.slice(0, 8)} contains text resembling instructions ({flags.join(", ")}); treated as data.</li>
                  ))}
                </ul>
              </Card>
            )}
          </>
        )}
      </div>
      <div className="space-y-6">
        <Card title="Export report">
          <p className="mb-3 text-xs text-muted">Reports carry the {inv.tlp.toUpperCase()} marking and include an executive summary, scope, collection period, sources consulted, findings, contradictions, methodology, limitations and analyst notes. Exports are audited.</p>
          <div className="grid grid-cols-2 gap-2">
            {(["pdf", "html", "json", "csv"] as const).map((f) => (
              <a key={f} href={done ? reportUrl(inv.id, f) : undefined} aria-disabled={!done}
                className={`rounded-md border border-line px-3 py-2 text-center text-sm uppercase ${done ? "text-slate-200 hover:bg-ink-700" : "pointer-events-none text-muted"}`}>
                {f}
              </a>
            ))}
            <a href={done ? reportUrl(inv.id, "stix") : undefined} aria-disabled={!done}
              className={`col-span-2 rounded-md border border-accent/40 px-3 py-2 text-center text-sm ${done ? "text-accent hover:bg-accent-soft" : "pointer-events-none text-muted"}`}>
              STIX 2.1 bundle <span className="text-xs text-muted">(OpenCTI, MISP, TAXII)</span>
            </a>
          </div>
        </Card>
        {owner && <Handling />}
        <Card title={`Analyst notes (${notes?.length ?? 0})`}>
          <ul className="mb-3 max-h-72 space-y-2 overflow-y-auto text-sm">
            {notes?.map((n) => (
              <li key={n.id} className="rounded border border-line p-2">
                <div className="text-[11px] text-muted">{fmtDate(n.created_at)} · {n.author}{n.finding_id && ` · finding ${n.finding_id.slice(0, 8)}`}</div>
                <div className="whitespace-pre-line text-slate-300">{n.body}</div>
              </li>
            ))}
          </ul>
          {owner && (
            <>
              <label htmlFor="note" className="sr-only">New note</label>
              <textarea id="note" rows={3} maxLength={8000} className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add an analyst note" />
              <Button className="mt-2" variant="secondary" disabled={!note || busy} onClick={() => run(async () => {
                await api(`/api/v1/investigations/${inv.id}/notes`, { method: "POST", json: { body: note } });
                setNote("");
                await reloadNotes();
              })}>Add note</Button>
            </>
          )}
        </Card>
        {owner && (
          <Card title="Lifecycle">
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" disabled={busy || inv.status === "running"} onClick={() => run(async () => {
                await api(`/api/v1/investigations/${inv.id}/run`, { method: "POST" });
                await reload();
                router.push(`/investigations/${inv.id}`);
              })}>Re-run collection</Button>
              <Button variant="danger" disabled={busy} onClick={() => {
                if (!window.confirm("Permanently delete this investigation, its findings and notes?")) return;
                void run(async () => {
                  await api(`/api/v1/investigations/${inv.id}`, { method: "DELETE" });
                  router.push("/history");
                });
              }}>Delete investigation</Button>
            </div>
            <p className="mt-2 text-xs text-muted">Analyst verification decisions are preserved across re-runs. Deletion is permanent and audited.</p>
          </Card>
        )}
        <ErrorBox messages={errors} />
      </div>
    </div>
  );
}
