/** Client-side identifier type detection for quick launch (the API re-validates and normalises). */
export type DetectedType = "email" | "url" | "ip" | "phone" | "domain" | "username" | "name" | "organization";

const ORG_SUFFIX = /\b(inc|ltd|llc|plc|gmbh|ag|sa|corp|corporation|limited|company|co|bv|nv|ab|oy|srl|sas)\.?$/i;

export function detectIdentifier(raw: string): { type: DetectedType; value: string } | null {
  const value = raw.trim();
  if (!value || value.length > 512) return null;
  if (/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value)) return { type: "email", value };
  if (/^https?:\/\//i.test(value)) return { type: "url", value };
  if (/^(\d{1,3}\.){3}\d{1,3}$/.test(value) && value.split(".").every((o) => Number(o) <= 255))
    return { type: "ip", value };
  if (/^[0-9a-f:]+$/i.test(value) && value.includes("::")) return { type: "ip", value };
  if (/^\+[\d\s().-]{7,20}$/.test(value)) return { type: "phone", value };
  if (!/\s/.test(value) && /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i.test(value))
    return { type: "domain", value };
  if (/\s/.test(value)) return { type: ORG_SUFFIX.test(value) ? "organization" : "name", value };
  if (/^@?[a-z0-9][a-z0-9._-]{0,62}$/i.test(value)) return { type: "username", value: value.replace(/^@/, "") };
  return null;
}
