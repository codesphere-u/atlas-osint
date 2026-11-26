"use client";

import { useState } from "react";
import { useApi } from "@/lib/hooks";
import { CLASSIFICATION_STYLE, humanize } from "@/lib/format";
import type { Classification, TimelineEvent } from "@/lib/types";
import { useInvestigation } from "@/components/InvestigationContext";
import { Badge, EmptyState, Spinner } from "@/components/ui";

export default function TimelinePage() {
  const { inv } = useInvestigation();
  const [filter, setFilter] = useState<string>("all");
  const { data } = useApi<TimelineEvent[]>(inv.status === "completed" ? `/api/v1/investigations/${inv.id}/timeline` : null);
  if (inv.status !== "completed") return <Spinner label="Waiting for collection to finish" />;
  if (!data) return <Spinner />;
  const events = data.filter((e) => filter === "all" || e.category === filter);
  if (!data.length) return <EmptyState title="No dated evidence">None of the findings carry a publication or event date.</EmptyState>;
  const years = [...new Set(events.map((e) => e.date.slice(0, 4)))];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1">
        {["all", "confirmed", "possible", "unverified"].map((f) => (
          <button key={f} onClick={() => setFilter(f)} aria-pressed={filter === f}
            className={`rounded-md border px-3 py-1.5 text-xs ${filter === f ? "border-accent bg-accent-soft text-white" : "border-line text-muted"}`}>
            {humanize(f)}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted">Dates come from source records (registration, account creation, publication, archive capture). The timeline is computed deterministically – never by AI.</p>
      {years.map((year) => (
        <section key={year}>
          <h2 className="mb-2 font-mono text-sm text-accent">{year}</h2>
          <ol className="relative space-y-3 border-l border-line pl-5">
            {events.filter((e) => e.date.startsWith(year)).map((e, i) => (
              <li key={`${e.finding_id}-${i}`} className="relative">
                <span className="absolute -left-[25px] top-1.5 h-2.5 w-2.5 rounded-full border border-ink-950 bg-accent" aria-hidden />
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <time dateTime={e.date} className="font-mono text-xs text-muted">{e.date}</time>
                  <span className="text-slate-100">{e.label}</span>
                  <Badge className={CLASSIFICATION_STYLE[e.category as Classification]}>{e.category}</Badge>
                </div>
                <div className="text-xs text-muted">{e.source} · {humanize(e.date_kind.replace("attribute:", ""))}</div>
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
