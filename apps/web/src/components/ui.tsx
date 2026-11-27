import Link from "next/link";
import type { ReactNode } from "react";
import { CLASSIFICATION_LABEL, CLASSIFICATION_STYLE, LEVEL_COLOR, pct, STATUS_STYLE, humanize } from "@/lib/format";
import type { Classification, Level } from "@/lib/types";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-lg border border-line bg-ink-850/80", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          {title && <h2 className="text-sm font-semibold text-slate-100">{title}</h2>}
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="truncate text-xl font-semibold text-white">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Button({
  children, variant = "primary", className, ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" }) {
  const styles = {
    primary: "bg-accent text-ink-950 hover:bg-blue-400 disabled:bg-accent/40",
    secondary: "border border-line bg-ink-800 text-slate-200 hover:bg-ink-700",
    danger: "border border-bad/50 text-bad hover:bg-bad/10",
    ghost: "text-muted hover:text-white",
  }[variant];
  return (
    <button
      {...props}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed",
        styles, className,
      )}
    >
      {children}
    </button>
  );
}

export function ButtonLink({ href, children, variant = "secondary" }: { href: string; children: ReactNode; variant?: "primary" | "secondary" }) {
  return (
    <Link
      href={href}
      className={cx(
        "inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        variant === "primary" ? "bg-accent text-ink-950 hover:bg-blue-400" : "border border-line bg-ink-800 text-slate-200 hover:bg-ink-700",
      )}
    >
      {children}
    </Link>
  );
}

export function Badge({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium", className ?? "border-line text-muted")}>
      {children}
    </span>
  );
}

export function ClassificationBadge({ value }: { value: Classification }) {
  return <Badge className={CLASSIFICATION_STYLE[value]}>{CLASSIFICATION_LABEL[value]}</Badge>;
}

export function StatusPill({ status }: { status: string }) {
  return <Badge className={STATUS_STYLE[status] ?? "border-line text-muted"}>{humanize(status)}</Badge>;
}

export function ConfidenceMeter({ score, level }: { score: number; level: Level }) {
  return (
    <div className="flex items-center gap-2" aria-label={`Confidence ${pct(score)} (${humanize(level)})`}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-ink-700" aria-hidden>
        <div className={cx("h-full", LEVEL_COLOR[level])} style={{ width: `${Math.round(score * 100)}%` }} />
      </div>
      <span className="font-mono text-xs text-slate-300">{pct(score)}</span>
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-ink-850/80 p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-white">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line p-8 text-center">
      <p className="font-medium text-slate-200">{title}</p>
      {children && <div className="mt-2 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-accent" aria-hidden />
      {label}…
    </div>
  );
}

export function ErrorBox({ messages }: { messages: string[] }) {
  if (!messages.length) return null;
  return (
    <div role="alert" className="rounded-md border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
      <ul className="list-inside list-disc space-y-1">{messages.map((m) => <li key={m}>{m}</li>)}</ul>
    </div>
  );
}

export function Field({ label, htmlFor, help, children }: { label: string; htmlFor: string; help?: ReactNode; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-200">{label}</label>
      {children}
      {help && <p className="text-xs text-muted">{help}</p>}
    </div>
  );
}

export const inputClass =
  "w-full rounded-md border border-line bg-ink-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";

function formatValue(v: unknown): string {
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ") : "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (v && typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function KeyValue({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!entries.length) return <p className="text-sm text-muted">No attributes.</p>;
  return (
    <dl className="space-y-2 text-sm">
      {entries.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs text-muted">{humanize(k)}</dt>
          <dd className="break-words font-mono text-xs leading-5 text-slate-200">{formatValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ---------------------------------------------------------------- v0.2 primitives */

const TLP_STYLE: Record<string, string> = {
  clear: "text-white",
  green: "text-[#33ff00]",
  amber: "text-[#ffc000]",
  "amber+strict": "text-[#ffc000]",
  red: "text-[#ff2b2b]",
};

/** FIRST TLP 2.0 label: coloured text on black, as the standard prescribes. */
export function TlpBadge({ tlp }: { tlp: string }) {
  return (
    <span title="Traffic Light Protocol 2.0 sharing restriction"
      className={cx("inline-flex items-center rounded bg-black px-2 py-0.5 font-mono text-[11px] font-bold tracking-wide ring-1 ring-white/10", TLP_STYLE[tlp] ?? "text-white")}>
      TLP:{tlp.toUpperCase()}
    </span>
  );
}

const RISK_STYLE: Record<string, string> = {
  critical: "border-[#dc3c3d] bg-[#dc3c3d]/15 text-[#ff8a8b]",
  high: "border-[#f18a59]/70 bg-[#f18a59]/10 text-[#f8b08c]",
  medium: "border-[#fbb315]/60 bg-[#fbb315]/10 text-[#fbcf6a]",
  low: "border-line text-slate-300",
  none: "border-line text-muted",
};

export function RiskBadge({ level }: { level: string | null | undefined }) {
  if (!level) return null;
  return <Badge className={RISK_STYLE[level] ?? RISK_STYLE.none} title="Highest risk highlight">{level === "none" ? "No risk flags" : `${level} risk`}</Badge>;
}

const GRADE_STYLE: Record<string, string> = {
  A: "text-[#34d399] border-[#34d399]/50",
  B: "text-[#86efac] border-[#86efac]/40",
  C: "text-[#fbcf6a] border-[#fbb315]/50",
  D: "text-[#f8b08c] border-[#f18a59]/60",
  F: "text-[#ff8a8b] border-[#dc3c3d]/70",
};

export function GradeBadge({ grade, size = "sm" }: { grade: string | null | undefined; size?: "sm" | "lg" }) {
  if (!grade) return null;
  return (
    <span title="Exposure scorecard grade"
      className={cx("inline-grid place-items-center rounded-md border font-bold", GRADE_STYLE[grade] ?? "border-line text-slate-200",
        size === "lg" ? "h-16 w-16 text-4xl" : "h-6 min-w-6 px-1 text-xs")}>
      {grade}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cx("animate-pulse rounded-md bg-ink-700/60", className)} />;
}

export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-14 w-full" />)}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-line bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">{children}</kbd>;
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[10vh] backdrop-blur-sm"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label={title}
        className={cx("w-full rounded-xl border border-line bg-ink-900 shadow-2xl", wide ? "max-w-2xl" : "max-w-lg")}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="text-sm font-semibold text-white">{title}</h2>
          <button onClick={onClose} className="rounded p-1 text-muted hover:bg-ink-700 hover:text-white" aria-label="Close">✕</button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function SectionTitle({ icon, children, aside }: { icon?: ReactNode; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-2">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-100">{icon}{children}</h2>
      {aside}
    </div>
  );
}
