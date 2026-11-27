"use client";

import { GitBranch } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { TYPE_LABEL } from "@/lib/format";
import { useToast } from "@/lib/toast";
import type { Investigation } from "@/lib/types";
import { Button, ErrorBox, Field, inputClass, Modal } from "./ui";

const PIVOTABLE = ["domain", "url", "ip", "email", "username", "phone", "organization", "name", "document"];
const INDIVIDUAL = new Set(["username", "email", "phone", "name"]);

export interface PivotTarget {
  type: string;
  value: string;
}

/** Normalise linked identifiers for pivoting (e.g. "github:octocat" -> username "octocat"). */
export function pivotTarget(type: string, value: string): PivotTarget | null {
  if (type === "username" && value.includes(":")) return { type, value: value.split(":").slice(1).join(":").split("@")[0] ?? value };
  return PIVOTABLE.includes(type) ? { type, value } : null;
}

export function PivotDialog({ investigationId, target, onClose }: { investigationId: string; target: PivotTarget | null; onClose: () => void }) {
  if (!target) return null;
  // Keyed by target: each pivot starts from a clean form (confirmation unticked, no stale consent reference).
  return <PivotForm key={`${target.type}:${target.value}`} investigationId={investigationId} target={target} onClose={onClose} />;
}

function PivotForm({ investigationId, target, onClose }: { investigationId: string; target: PivotTarget; onClose: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const [type, setType] = useState(target.type);
  const [value, setValue] = useState(target.value);
  const [covered, setCovered] = useState(false);
  const [consentRef, setConsentRef] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setErrors([]);
    try {
      const child = await api<Investigation>(`/api/v1/investigations/${investigationId}/pivot`, {
        method: "POST",
        json: { subject_type: type, subject: value, covered_by_authorization: covered, consent_reference: consentRef || undefined },
      });
      toast("success", "Pivot started", `${TYPE_LABEL[type] ?? type}: ${value} – added to the case`);
      onClose();
      router.push(`/investigations/${child.id}`);
    } catch (e) {
      setErrors(e instanceof ApiError ? e.messages : [String(e)]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} title="Pivot to a new investigation">
      <div className="space-y-4">
        <p className="flex items-start gap-2 text-sm text-muted">
          <GitBranch className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
          The new investigation inherits this investigation&apos;s legal basis, references, scope, TLP and retention, and joins the same case.
          Consent rules for individuals are re-checked.
        </p>
        <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
          <Field label="Type" htmlFor="pv-type">
            <select id="pv-type" className={inputClass} value={type} onChange={(e) => setType(e.target.value)}>
              {PIVOTABLE.map((t) => <option key={t} value={t}>{TYPE_LABEL[t] ?? t}</option>)}
            </select>
          </Field>
          <Field label="Identifier" htmlFor="pv-value">
            <input id="pv-value" className={inputClass} value={value} onChange={(e) => setValue(e.target.value)} />
          </Field>
        </div>
        {INDIVIDUAL.has(type) && (
          <Field label="Consent reference (if different)" htmlFor="pv-consent" help="Needed when the pivot target is a different individual.">
            <input id="pv-consent" className={inputClass} value={consentRef} onChange={(e) => setConsentRef(e.target.value)} />
          </Field>
        )}
        <label className="flex items-start gap-2 text-sm text-slate-200">
          <input type="checkbox" className="mt-1 h-4 w-4" checked={covered} onChange={(e) => setCovered(e.target.checked)} />
          <span>I confirm this identifier is the same subject, or is otherwise covered by the existing authorisation.</span>
        </label>
        <ErrorBox messages={errors} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={!covered || !value || busy} onClick={submit}>{busy ? "Starting…" : "Start pivot"}</Button>
        </div>
      </div>
    </Modal>
  );
}
