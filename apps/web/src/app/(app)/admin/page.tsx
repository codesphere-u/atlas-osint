"use client";

import { useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { fmtDate, humanize } from "@/lib/format";
import type { User } from "@/lib/types";
import { useUser } from "@/components/AppShell";
import { Badge, Button, Card, EmptyState, ErrorBox, inputClass, KeyValue, PageHeader } from "@/components/ui";

interface AuditEntry { id: number; ts: string; actor_id: string | null; action: string; target_type: string | null; target_id: string | null; ip: string | null; outcome: string; details: Record<string, unknown> }
interface PrivacyReq { id: string; kind: string; identifier_type: string; identifier: string; contact_email: string | null; details: string | null; status: string; created_at: string }
interface ApiKey { id: string; name: string; prefix: string; created_at: string; last_used_at: string | null; expires_at: string | null; revoked_at: string | null; key?: string | null }

export default function AdminPage() {
  const me = useUser();
  const isAdmin = me?.role === "admin";
  const [tab, setTab] = useState(isAdmin ? "users" : "audit");
  const tabs = isAdmin ? ["users", "privacy", "audit", "api-keys", "system"] : ["audit", "api-keys"];
  return (
    <>
      <PageHeader title="System administration" subtitle="Users and roles, data-subject requests, audit trail, API keys and system configuration." />
      <div className="mb-4 flex flex-wrap gap-1" role="tablist">
        {tabs.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`rounded-md border px-3 py-1.5 text-sm ${tab === t ? "border-accent bg-accent-soft text-white" : "border-line text-muted hover:text-white"}`}>
            {humanize(t)}
          </button>
        ))}
      </div>
      {tab === "users" && <Users />}
      {tab === "privacy" && <Privacy />}
      {tab === "audit" && <Audit />}
      {tab === "api-keys" && <ApiKeys />}
      {tab === "system" && <SystemInfo />}
    </>
  );
}

function Users() {
  const { data, reload } = useApi<User[]>("/api/v1/admin/users");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("analyst");
  const [errors, setErrors] = useState<string[]>([]);
  async function create(e: FormEvent) {
    e.preventDefault();
    setErrors([]);
    try {
      await api("/api/v1/admin/users", { method: "POST", json: { email, password, role } });
      setEmail(""); setPassword("");
      await reload();
    } catch (err) { setErrors(err instanceof ApiError ? err.messages : [String(err)]); }
  }
  async function patch(id: string, body: Record<string, unknown>) {
    try { await api(`/api/v1/admin/users/${id}`, { method: "PATCH", json: body }); await reload(); }
    catch (err) { setErrors(err instanceof ApiError ? err.messages : [String(err)]); }
  }
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card title="Users" className="lg:col-span-2">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="text-xs text-muted"><tr><th className="py-2">Email</th><th>Role</th><th>Status</th><th>Last login</th></tr></thead>
            <tbody className="divide-y divide-line">
              {data?.map((u) => (
                <tr key={u.id}>
                  <td className="py-2">{u.email}</td>
                  <td><select aria-label={`Role for ${u.email}`} className="rounded border border-line bg-ink-900 px-2 py-1" value={u.role} onChange={(e) => patch(u.id, { role: e.target.value })}>
                    {["admin", "analyst", "viewer", "auditor"].map((r) => <option key={r}>{r}</option>)}</select></td>
                  <td><button className="text-xs text-accent hover:underline" onClick={() => patch(u.id, { is_active: !u.is_active })}>{u.is_active ? "Active – disable" : "Disabled – enable"}</button></td>
                  <td className="text-muted">{fmtDate(u.last_login_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="Create user">
        <form onSubmit={create} className="space-y-3">
          <input aria-label="Email" type="email" required placeholder="email" className={inputClass} value={email} onChange={(e) => setEmail(e.target.value)} />
          <input aria-label="Password" type="password" required minLength={12} placeholder="password (min 12 chars)" className={inputClass} value={password} onChange={(e) => setPassword(e.target.value)} />
          <select aria-label="Role" className={inputClass} value={role} onChange={(e) => setRole(e.target.value)}>
            {["analyst", "viewer", "auditor", "admin"].map((r) => <option key={r}>{r}</option>)}
          </select>
          <ErrorBox messages={errors} />
          <Button type="submit">Create</Button>
        </form>
      </Card>
    </div>
  );
}

function Privacy() {
  const { data, reload } = useApi<PrivacyReq[]>("/api/v1/privacy/requests");
  async function resolve(id: string, status: string) {
    await api(`/api/v1/privacy/requests/${id}/resolve`, { method: "POST", json: { status } });
    await reload();
  }
  if (!data?.length) return <EmptyState title="No data-subject requests" />;
  return (
    <div className="space-y-3">
      {data.map((r) => (
        <Card key={r.id}>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="text-sm">
              <div className="flex flex-wrap gap-2"><Badge>{humanize(r.kind)}</Badge><Badge>{r.status}</Badge><span className="text-xs text-muted">{fmtDate(r.created_at)}</span></div>
              <div className="mt-2 font-mono text-slate-200">{r.identifier_type}: {r.identifier}</div>
              {r.contact_email && <div className="text-xs text-muted">Contact: {r.contact_email}</div>}
              {r.details && <p className="mt-1 text-slate-300">{r.details}</p>}
            </div>
            {r.status === "pending" && (
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => resolve(r.id, "approved")}>{r.kind === "deletion" ? "Approve & purge" : "Approve"}</Button>
                <Button variant="danger" onClick={() => resolve(r.id, "rejected")}>Reject</Button>
              </div>
            )}
          </div>
        </Card>
      ))}
    </div>
  );
}

function Audit() {
  const [action, setAction] = useState("");
  const { data } = useApi<AuditEntry[]>(`/api/v1/admin/audit?limit=200${action ? `&action=${encodeURIComponent(action)}` : ""}`);
  return (
    <Card title="Audit trail" actions={<input aria-label="Filter by action" placeholder="action prefix, e.g. investigation" className="rounded border border-line bg-ink-900 px-2 py-1 text-xs" value={action} onChange={(e) => setAction(e.target.value)} />}>
      <p className="mb-3 text-xs text-muted">Identifiers are never written to the audit log – only keyed hashes and record IDs.</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-xs">
          <thead className="text-muted"><tr><th className="py-1">Time</th><th>Action</th><th>Outcome</th><th>Actor</th><th>Target</th><th>Details</th></tr></thead>
          <tbody className="divide-y divide-line">
            {data?.map((a) => (
              <tr key={a.id}>
                <td className="whitespace-nowrap py-1 text-muted">{fmtDate(a.ts)}</td>
                <td className="font-mono">{a.action}</td>
                <td className={a.outcome === "success" ? "text-ok" : "text-warn"}>{a.outcome}</td>
                <td className="font-mono text-muted">{a.actor_id?.slice(0, 8) ?? "system"}</td>
                <td className="font-mono text-muted">{a.target_type ? `${a.target_type}:${a.target_id?.slice(0, 8)}` : "—"}</td>
                <td className="max-w-xs truncate font-mono text-muted" title={JSON.stringify(a.details)}>{JSON.stringify(a.details)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ApiKeys() {
  const { data, reload } = useApi<ApiKey[]>("/api/v1/auth/api-keys");
  const [name, setName] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card title="Your API keys" className="lg:col-span-2">
        <ul className="divide-y divide-line text-sm">
          {data?.map((k) => (
            <li key={k.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>{k.name} <span className="font-mono text-xs text-muted">{k.prefix}…</span></span>
              <span className="flex items-center gap-3 text-xs text-muted">
                last used {fmtDate(k.last_used_at)} · expires {fmtDate(k.expires_at, false)}
                {k.revoked_at ? <Badge className="border-bad/40 text-bad">revoked</Badge> : (
                  <button className="text-bad hover:underline" onClick={async () => { await api(`/api/v1/auth/api-keys/${k.id}`, { method: "DELETE" }); await reload(); }}>Revoke</button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Create API key">
        <div className="space-y-3">
          <input aria-label="Key name" placeholder="name (e.g. ci-pipeline)" className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
          <Button disabled={!name} onClick={async () => {
            const k = await api<ApiKey>("/api/v1/auth/api-keys", { method: "POST", json: { name, expires_in_days: 90 } });
            setCreated(k.key ?? null); setName(""); await reload();
          }}>Create (90 days)</Button>
          {created && (
            <div className="rounded border border-warn/40 bg-warn/10 p-2 text-xs text-warn">
              Copy this key now; it will not be shown again:<code className="mt-1 block break-all text-slate-100">{created}</code>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

function SystemInfo() {
  const { data, reload } = useApi<Record<string, unknown>>("/api/v1/admin/system");
  const [msg, setMsg] = useState<string | null>(null);
  const problems = (data?.production_config_problems as string[] | undefined) ?? [];
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Configuration">{data ? <KeyValue data={{ ...data, production_config_problems: problems.length ? problems.join("; ") : "none" }} /> : null}</Card>
      <Card title="Data retention">
        <p className="text-sm text-muted">Investigations are deleted automatically after their retention date. Run the purge now:</p>
        <Button className="mt-3" variant="secondary" onClick={async () => {
          const r = await api<{ removed: number }>("/api/v1/admin/retention/run", { method: "POST" });
          setMsg(`${r.removed} expired investigations removed.`); await reload();
        }}>Run retention purge</Button>
        {msg && <p role="status" className="mt-2 text-sm text-ok">{msg}</p>}
      </Card>
    </div>
  );
}
