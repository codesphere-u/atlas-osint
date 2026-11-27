"use client";

/**
 * Small dependency-free SVG charts (dark surface #0f172a).
 * Colours validated with the dataviz palette validator against the dashboard surface:
 *   series-1 #338ced; blue #338ced + critical #dc3c3d (health); status palette always paired with icon + label.
 */
import { useId, useState, type ReactNode } from "react";

export const CHART = {
  series1: "#338ced",
  critical: "#dc3c3d",
  good: "#0aac23",
  warning: "#fbb315",
  serious: "#f18a59",
  neutral: "#475569",
  grid: "#1f2a44",
  text: "#e2e8f0",
  muted: "#8b98b5",
};

/** Path for a bar whose data end (top) has 4px rounded corners and whose base sits flat on the baseline. */
function topRoundedBar(x: number, y: number, w: number, h: number, r = 4): string {
  if (h <= 0) return "";
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`;
}

function niceMax(v: number): number {
  if (v <= 4) return Math.max(1, Math.ceil(v));
  const p = 10 ** Math.floor(Math.log10(v));
  return Math.ceil(v / p) * p;
}

export interface ColumnDatum {
  key: string;
  label: string;
  value: number;
  tooltip?: ReactNode;
}

/** Single-series column chart with per-column hover tooltip; optional click-to-select. */
export function ColumnChart({
  data, height = 140, ariaLabel, selected, onSelect, valueLabel = "value",
}: {
  data: ColumnDatum[];
  height?: number;
  ariaLabel: string;
  selected?: string | null;
  onSelect?: (key: string | null) => void;
  valueLabel?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 600;
  const pad = { top: 8, right: 4, bottom: 22, left: 28 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const max = niceMax(Math.max(0, ...data.map((d) => d.value)));
  const step = innerW / Math.max(1, data.length);
  const gap = 2;
  const barW = Math.max(2, Math.min(28, step - gap));
  const ticks = [0, max / 2, max];
  const labelEvery = Math.max(1, Math.ceil(data.length / 8));
  const hovered = hover !== null ? data[hover] : null;

  return (
    <figure className="relative" aria-label={ariaLabel}>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label={ariaLabel}
        onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => {
          const y = pad.top + innerH - (t / max) * innerH;
          return (
            <g key={t}>
              <line x1={pad.left} x2={width - pad.right} y1={y} y2={y} stroke={CHART.grid} strokeWidth={1} />
              <text x={pad.left - 6} y={y + 3} textAnchor="end" fontSize={10} fill={CHART.muted}>{Math.round(t)}</text>
            </g>
          );
        })}
        {data.map((d, i) => {
          const h = (d.value / max) * innerH;
          const x = pad.left + i * step + (step - barW) / 2;
          const y = pad.top + innerH - h;
          const dim = selected && selected !== d.key;
          return (
            <g key={d.key}>
              <path d={topRoundedBar(x, y, barW, h)} fill={CHART.series1} opacity={dim ? 0.35 : hover === i ? 1 : 0.85} />
              {/* hit target: the full column height, wider than the mark */}
              <rect x={pad.left + i * step} y={pad.top} width={step} height={innerH} fill="transparent"
                onMouseEnter={() => setHover(i)} onClick={() => onSelect?.(selected === d.key ? null : d.key)}
                style={{ cursor: onSelect ? "pointer" : "default" }} />
              {i % labelEvery === 0 && (
                <text x={pad.left + i * step + step / 2} y={height - 6} textAnchor="middle" fontSize={10} fill={CHART.muted}>
                  {d.label}
                </text>
              )}
            </g>
          );
        })}
        <line x1={pad.left} x2={width - pad.right} y1={pad.top + innerH} y2={pad.top + innerH} stroke={CHART.neutral} />
      </svg>
      {hovered && hover !== null && (
        <div className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 rounded-md border border-line bg-ink-800 px-2 py-1 text-xs shadow-lg"
          style={{ left: `${((pad.left + hover * step + step / 2) / width) * 100}%` }}>
          <div className="font-medium text-slate-100">{hovered.label}</div>
          <div className="text-muted">{hovered.tooltip ?? `${hovered.value} ${valueLabel}`}</div>
        </div>
      )}
      <table className="sr-only">
        <caption>{ariaLabel}</caption>
        <tbody>{data.map((d) => <tr key={d.key}><th>{d.label}</th><td>{d.value}</td></tr>)}</tbody>
      </table>
    </figure>
  );
}

export interface Segment {
  key: string;
  label: string;
  value: number;
  color: string;
  icon: ReactNode;
}

/** 100% segmented bar with 2px surface gaps; legend always shows icon + label + count (never colour alone). */
export function SegmentedBar({ segments, ariaLabel }: { segments: Segment[]; ariaLabel: string }) {
  const total = segments.reduce((a, s) => a + s.value, 0);
  const [hover, setHover] = useState<string | null>(null);
  const id = useId();
  if (!total) return <p className="text-sm text-muted">No data yet.</p>;
  return (
    <figure aria-labelledby={id}>
      <div className="flex h-3 w-full gap-[2px] overflow-hidden rounded" role="img" aria-label={ariaLabel}>
        {segments.filter((s) => s.value > 0).map((s) => (
          <div key={s.key} className="h-full first:rounded-l last:rounded-r" title={`${s.label}: ${s.value}`}
            onMouseEnter={() => setHover(s.key)} onMouseLeave={() => setHover(null)}
            style={{ width: `${(s.value / total) * 100}%`, background: s.color, opacity: hover && hover !== s.key ? 0.45 : 1 }} />
        ))}
      </div>
      <figcaption id={id} className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
        {segments.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5 text-slate-300"
            onMouseEnter={() => setHover(s.key)} onMouseLeave={() => setHover(null)}>
            <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: s.color }} aria-hidden />
            {s.icon}
            <span>{s.label}</span>
            <span className="ml-auto font-mono text-slate-100">{s.value}</span>
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

/** Per-row two-part bar (OK vs failed) for source health; numbers are always printed beside the bar. */
export function HealthBars({ rows }: { rows: { key: string; label: string; ok: number; failed: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.ok + r.failed));
  return (
    <div className="space-y-2">
      <div className="flex gap-4 text-[11px] text-muted" aria-hidden>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ background: CHART.series1 }} />answered</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ background: CHART.critical }} />unavailable / error</span>
      </div>
      {rows.map((r) => (
        <div key={r.key} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-2 text-xs"
          title={`${r.label}: ${r.ok} answered, ${r.failed} failed`}>
          <span className="truncate text-slate-300">{r.label}</span>
          <div className="flex h-2 gap-[2px]">
            {r.ok > 0 && <div className="h-full rounded-l" style={{ width: `${(r.ok / max) * 100}%`, background: CHART.series1 }} />}
            {r.failed > 0 && <div className="h-full rounded-r" style={{ width: `${(r.failed / max) * 100}%`, background: CHART.critical }} />}
          </div>
          <span className="font-mono text-muted">{r.ok}/{r.ok + r.failed}</span>
        </div>
      ))}
    </div>
  );
}

/** Radial score gauge for the exposure grade (single value -> a hero number with a ring, not a chart). */
export function ScoreRing({ score, grade }: { score: number | null; grade: string | null }) {
  const r = 42;
  const c = 2 * Math.PI * r;
  const pct = score == null ? 0 : score / 100;
  const color = grade === "A" || grade === "B" ? CHART.good : grade === "C" ? CHART.warning : grade ? CHART.critical : CHART.neutral;
  return (
    <div className="relative h-28 w-28" role="img" aria-label={score == null ? "Insufficient data for a grade" : `Grade ${grade}, score ${score} of 100`}>
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
        <circle cx="50" cy="50" r={r} fill="none" stroke={CHART.grid} strokeWidth="8" />
        <circle cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
          strokeDasharray={`${c * pct} ${c}`} />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <div className="text-3xl font-bold leading-none text-white">{grade ?? "–"}</div>
          <div className="mt-1 font-mono text-xs text-muted">{score == null ? "n/a" : `${score}/100`}</div>
        </div>
      </div>
    </div>
  );
}
