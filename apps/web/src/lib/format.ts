import type { Classification, Level } from "./types";

export function fmtDate(value: string | null | undefined, withTime = true): string {
  if (!value) return "—";
  const d = new Date(value.endsWith("Z") || value.includes("+") ? value : `${value}Z`);
  if (Number.isNaN(d.getTime())) return value;
  return withTime
    ? d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
    : d.toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function pct(score: number | null | undefined): string {
  return score == null ? "—" : `${Math.round(score * 100)}%`;
}

export const CLASSIFICATION_STYLE: Record<Classification, string> = {
  confirmed: "border-ok/50 bg-ok/10 text-ok",
  possible: "border-accent/50 bg-accent/10 text-accent",
  unverified: "border-warn/50 bg-warn/10 text-warn",
  rejected: "border-bad/50 bg-bad/10 text-bad line-through",
};

export const CLASSIFICATION_LABEL: Record<Classification, string> = {
  confirmed: "Confirmed",
  possible: "Possible match",
  unverified: "Unverified",
  rejected: "Rejected",
};

export const LEVEL_COLOR: Record<Level, string> = {
  high: "bg-ok",
  medium: "bg-accent",
  low: "bg-warn",
  very_low: "bg-bad",
};

export const STATUS_STYLE: Record<string, string> = {
  completed: "text-ok border-ok/40",
  running: "text-accent border-accent/40",
  queued: "text-muted border-line",
  draft: "text-muted border-line",
  failed: "text-bad border-bad/40",
  ok: "text-ok border-ok/40",
  no_results: "text-muted border-line",
  skipped: "text-muted border-line",
  not_configured: "text-warn border-warn/40",
  rate_limited: "text-warn border-warn/40",
  unavailable: "text-bad border-bad/40",
  error: "text-bad border-bad/40",
};

export const TYPE_LABEL: Record<string, string> = {
  phone: "Phone number",
  username: "Username",
  name: "Full name",
  email: "Email address",
  domain: "Domain",
  url: "URL",
  ip: "IP address",
  organization: "Organization",
  document: "Public document (URL)",
};

export const LEGAL_BASIS_LABEL: Record<string, string> = {
  consent: "Documented consent of the individual",
  self: "Self-investigation (my own identifiers)",
  legitimate_interest: "Legitimate interest (e.g. organisational due diligence)",
  authorized_security_assessment: "Authorised security assessment",
  journalism: "Journalism",
  research: "Research",
  legal_obligation: "Legal obligation",
};

export function humanize(s: string): string {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function safeHref(url: string): string | undefined {
  return /^https?:\/\//i.test(url) ? url : undefined;
}
