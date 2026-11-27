"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { CLASSIFICATION_STYLE, humanize } from "@/lib/format";
import type { Classification, TimelineEvent } from "@/lib/types";
import { ColumnChart } from "./charts";
import { Badge, cx, EmptyState } from "./ui";

export function TimelineView({ events }: { events: TimelineEvent[] }) {
  const [category, setCategory] = useState("all");
  const [year, setYear] = useState<string | null>(null);
  const filtered = events.filter((e) => category === "all" || e.category === category);
  const years = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of filtered) counts.set(e.date.slice(0, 4), (counts.get(e.date.slice(0, 4)) ?? 0) + 1);
    const ys = [...counts.keys()].map(Number).sort((a, b) => a - b);
    if (!ys.length) return [];
    const out = [];
    for (let y = ys[0]!; y <= ys[ys.length - 1]!; y++) out.push({ key: String(y), label: String(y), value: counts.get(String(y)) ?? 0 });
    return out;
  }, [filtered]);
  const shown = filtered.filter((e) => !year || e.date.startsWith(year));
  const groups = [...new Set(shown.map((e) => e.date.slice(0, 4)))];
  if (!events.length) return <EmptyState title="No dated evidence">None of the findings carry a publication or event date.</EmptyState>;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          {["all", "confirmed", "possible", "unverified"].map((f) => (
            <button key={f} onClick={() => setCategory(f)} aria-pressed={category === f}
              className={cx("rounded-md border px-3 py-1.5 text-xs", category === f ? "border-accent bg-accent-soft text-white" : "border-line text-muted")}>
              {humanize(f)}
            </button>
          ))}
        </div>
        {year && <button onClick={() => setYear(null)} className="text-xs text-accent hover:underline">Clear year filter ({year})</button>}
      </div>
      <div className="rounded-lg border border-line bg-ink-850/80 p-4">
        <div className="mb-2 text-xs text-muted">Dated evidence per year – click a bar to filter</div>
        <ColumnChart data={years} ariaLabel="Dated evidence per year" valueLabel="events" height={130} selected={year} onSelect={setYear} />
      </div>
      <p className="text-xs text-muted">Dates come from source records (registration, account creation, publication, archive capture, certificates). The timeline is computed deterministically – never by AI.</p>
      {groups.map((y) => (
        <section key={y}>
          <h2 className="mb-2 font-mono text-sm text-accent">{y}</h2>
          <ol className="relative space-y-3 border-l border-line pl-5">
            {shown.filter((e) => e.date.startsWith(y)).map((e, i) => (
              <li key={`${e.finding_id}-${i}`} className="relative">
                <span className="absolute -left-[25px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-ink-950 bg-accent" aria-hidden />
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <time dateTime={e.date} className="font-mono text-xs text-muted">{e.date}</time>
                  <span className="text-slate-100">{e.label}</span>
                  <Badge className={CLASSIFICATION_STYLE[e.category as Classification]}>{e.category}</Badge>
                </div>
                <div className="text-xs text-muted">
                  {e.source} · {humanize(e.date_kind.replace("attribute:", ""))}
                  {e.investigation_id && <> · <Link href={`/investigations/${e.investigation_id}`} className="text-accent hover:underline">{e.investigation}</Link></>}
                </div>
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
