"use client";

import { useState } from "react";
import { fmtDate, humanize, safeHref } from "@/lib/format";
import type { Finding } from "@/lib/types";
import { Badge, Button, ClassificationBadge, ConfidenceMeter, KeyValue } from "./ui";

export function EvidenceCard({
  finding, canVerify, onVerify, injectionFlags, defaultOpen = false, onPivot,
}: {
  finding: Finding;
  canVerify: boolean;
  onVerify?: (id: string, status: "verified" | "rejected" | "unverified", note?: string) => Promise<void>;
  injectionFlags?: string[];
  defaultOpen?: boolean;
  onPivot?: (type: string, value: string) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const f = finding;
  const href = safeHref(f.source_url);

  async function decide(status: "verified" | "rejected" | "unverified") {
    if (!onVerify) return;
    setBusy(true);
    try {
      await onVerify(f.id, status, note || undefined);
      setNote("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="rounded-lg border border-line bg-ink-850/80 p-4" aria-labelledby={`f-${f.id}`}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 id={`f-${f.id}`} className="break-words text-sm font-semibold text-slate-100">{f.title}</h3>
          <p className="mt-1 text-sm text-slate-300">{f.description}</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <ClassificationBadge value={f.classification} />
          {f.confidence && <ConfidenceMeter score={f.confidence.score} level={f.confidence.level} />}
        </div>
      </div>
      {f.evidence.excerpt && (
        <blockquote className="mt-3 border-l-2 border-line pl-3 text-sm italic text-slate-400">{f.evidence.excerpt}</blockquote>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
        <Badge title="Source reliability grade (A highest)">Reliability {f.reliability}</Badge>
        <Badge>{humanize(f.match_type)} match</Badge>
        <Badge className={f.evidence_kind === "inference" ? "border-warn/40 text-warn" : undefined}>{humanize(f.evidence_kind)} evidence</Badge>
        <Badge>{humanize(f.verification_status)}</Badge>
        {injectionFlags?.length ? (
          <Badge className="border-bad/50 text-bad" title={injectionFlags.join(", ")}>Untrusted instructions detected</Badge>
        ) : null}
        <span>
          {f.source_display_name} ·{" "}
          {href ? (
            <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-accent hover:underline">source</a>
          ) : (
            <span className="font-mono">{f.source_url}</span>
          )}{" "}
          · collected {fmtDate(f.collected_at)}
          {f.published_at && <> · published {fmtDate(f.published_at, false)}</>}
        </span>
      </div>
      <button className="mt-3 text-xs text-accent hover:underline" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? "Hide evidence details" : "Show evidence details"}
      </button>
      {open && (
        <div className="mt-3 grid gap-4 border-t border-line pt-3 lg:grid-cols-2">
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Why this confidence</h4>
            <ul className="space-y-1 text-sm">
              {f.confidence?.reasons.map((r, i) => (
                <li key={i} className="flex gap-2">
                  <span className={r.delta >= 0 ? "font-mono text-ok" : "font-mono text-bad"}>{r.delta >= 0 ? "+" : ""}{r.delta.toFixed(2)}</span>
                  <span className="text-slate-300">{r.explanation}</span>
                </li>
              ))}
            </ul>
            <h4 className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Provenance</h4>
            <dl className="space-y-1 text-xs text-slate-300">
              <div><dt className="inline text-muted">Finding ID: </dt><dd className="inline font-mono">{f.id}</dd></div>
              {f.evidence.content_hash && <div><dt className="inline text-muted">Response SHA-256: </dt><dd className="inline break-all font-mono">{f.evidence.content_hash}</dd></div>}
              {f.citation && <div><dt className="inline text-muted">Citation: </dt><dd className="inline">{f.citation}</dd></div>}
              {f.flags.length > 0 && <div><dt className="inline text-muted">Flags: </dt><dd className="inline font-mono">{f.flags.join(", ")}</dd></div>}
            </dl>
          </div>
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Attributes (permitted metadata)</h4>
            <KeyValue data={f.attributes} />
            {f.linked.length > 0 && (
              <>
                <h4 className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Linked identifiers</h4>
                <ul className="space-y-1 text-xs">
                  {f.linked.map((l, i) => (
                    <li key={i} className="flex items-center justify-between gap-2 font-mono text-slate-300">
                      <span className="min-w-0 break-all">
                        {l.relation} → {l.identifier.type}:{l.identifier.value} <span className="text-muted">({l.evidence_kind})</span>
                      </span>
                      {onPivot && (
                        <button onClick={() => onPivot(l.identifier.type, l.identifier.value)}
                          className="shrink-0 rounded border border-line px-1.5 py-0.5 font-sans text-[11px] text-accent hover:bg-accent-soft">
                          Pivot
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
          {canVerify && (
            <div className="lg:col-span-2">
              <label htmlFor={`note-${f.id}`} className="text-xs text-muted">Analyst note (optional, stored encrypted)</label>
              <textarea id={`note-${f.id}`} value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={4000}
                className="mt-1 w-full rounded-md border border-line bg-ink-900 p-2 text-sm text-slate-100" />
              <div className="mt-2 flex flex-wrap gap-2">
                <Button variant="secondary" disabled={busy} onClick={() => decide("verified")}>Mark verified</Button>
                <Button variant="danger" disabled={busy} onClick={() => decide("rejected")}>Reject</Button>
                {f.verification_status !== "unverified" && (
                  <Button variant="ghost" disabled={busy} onClick={() => decide("unverified")}>Reset</Button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
