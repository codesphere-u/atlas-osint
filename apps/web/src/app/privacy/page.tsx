"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { TYPE_LABEL } from "@/lib/format";
import { Button, ErrorBox, Field, inputClass } from "@/components/ui";

export default function PrivacyRequestPage() {
  const [kind, setKind] = useState("opt_out");
  const [identifierType, setIdentifierType] = useState("email");
  const [identifier, setIdentifier] = useState("");
  const [contact, setContact] = useState("");
  const [details, setDetails] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErrors([]);
    try {
      const r = await api<{ id: string; message: string }>("/api/v1/privacy/requests", {
        method: "POST",
        json: { kind, identifier_type: identifierType, identifier, contact_email: contact || undefined, details: details || undefined },
      });
      setResult(`${r.message} Reference: ${r.id}`);
    } catch (err) {
      setErrors(err instanceof ApiError ? err.messages : [String(err)]);
    }
  }

  return (
    <main className="mx-auto max-w-xl px-4 py-12">
      <h1 className="text-xl font-semibold text-white">Data-subject request</h1>
      <p className="mt-2 text-sm text-muted">
        Ask this ATLAS OSINT installation to stop processing (opt-out), correct, or delete information about an identifier
        that belongs to you. Approved opt-outs prevent new investigations of the identifier and suppress it in results.
      </p>
      {result ? (
        <div role="status" className="mt-6 rounded-md border border-ok/40 bg-ok/10 p-4 text-sm text-ok">{result}</div>
      ) : (
        <form onSubmit={submit} className="mt-6 space-y-4">
          <Field label="Request type" htmlFor="kind">
            <select id="kind" className={inputClass} value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="opt_out">Opt-out (stop processing)</option>
              <option value="correction">Correction</option>
              <option value="deletion">Deletion</option>
            </select>
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Identifier type" htmlFor="itype">
              <select id="itype" className={inputClass} value={identifierType} onChange={(e) => setIdentifierType(e.target.value)}>
                {["email", "phone", "username", "name", "domain"].map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
              </select>
            </Field>
            <Field label="Identifier" htmlFor="ident">
              <input id="ident" required className={inputClass} value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
            </Field>
          </div>
          <Field label="Contact email (optional)" htmlFor="contact" help="Used only to respond to this request; stored encrypted.">
            <input id="contact" type="email" className={inputClass} value={contact} onChange={(e) => setContact(e.target.value)} />
          </Field>
          <Field label="Details" htmlFor="details">
            <textarea id="details" rows={4} maxLength={4000} className={inputClass} value={details} onChange={(e) => setDetails(e.target.value)} />
          </Field>
          <ErrorBox messages={errors} />
          <Button type="submit" disabled={!identifier}>Submit request</Button>
        </form>
      )}
      <p className="mt-8 text-xs text-muted"><Link href="/login" className="text-accent hover:underline">Back to sign-in</Link></p>
    </main>
  );
}
