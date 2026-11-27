"use client";

import {
  ArrowRight, Briefcase, CornerDownLeft, FolderSearch, LayoutDashboard, Plus, Search, Settings, Database, History,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { detectIdentifier } from "@/lib/detect";
import { TYPE_LABEL } from "@/lib/format";
import type { CaseSummary, Investigation } from "@/lib/types";
import { cx, Kbd } from "./ui";

interface Item {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon: ReactNode;
  run: () => void;
}

const NAV = [
  { href: "/", label: "Overview", icon: <LayoutDashboard className="h-4 w-4" /> },
  { href: "/investigations/new", label: "New investigation", icon: <Plus className="h-4 w-4" /> },
  { href: "/cases", label: "Cases", icon: <Briefcase className="h-4 w-4" /> },
  { href: "/history", label: "Investigation history", icon: <History className="h-4 w-4" /> },
  { href: "/sources", label: "Source management", icon: <Database className="h-4 w-4" /> },
  { href: "/admin", label: "Administration", icon: <Settings className="h-4 w-4" /> },
];

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const [invs, setInvs] = useState<Investigation[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setActive(0);
    setTimeout(() => input.current?.focus(), 0);
    api<Investigation[]>("/api/v1/investigations?limit=50").then(setInvs).catch(() => undefined);
    api<CaseSummary[]>("/api/v1/cases").then(setCases).catch(() => undefined);
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const go = (href: string) => () => { onClose(); router.push(href); };
    const needle = q.trim().toLowerCase();
    const out: Item[] = [];
    const detected = detectIdentifier(q);
    if (detected) {
      out.push({
        id: "launch", group: "Investigate", icon: <Search className="h-4 w-4 text-accent" />,
        label: `Investigate ${TYPE_LABEL[detected.type]?.toLowerCase() ?? detected.type}: ${detected.value}`,
        hint: "Opens the authorisation form pre-filled",
        run: go(`/investigations/new?type=${detected.type}&subject=${encodeURIComponent(detected.value)}`),
      });
    }
    for (const n of NAV) {
      if (!needle || n.label.toLowerCase().includes(needle)) {
        out.push({ id: `nav-${n.href}`, group: "Go to", label: n.label, icon: n.icon, run: go(n.href) });
      }
    }
    for (const i of invs.filter((x) => !needle || `${x.title} ${x.subject}`.toLowerCase().includes(needle)).slice(0, 6)) {
      out.push({ id: `inv-${i.id}`, group: "Investigations", label: i.title, hint: `${TYPE_LABEL[i.subject_type] ?? i.subject_type} · ${i.status}`,
        icon: <FolderSearch className="h-4 w-4" />, run: go(`/investigations/${i.id}`) });
    }
    for (const c of cases.filter((x) => !needle || x.title.toLowerCase().includes(needle)).slice(0, 4)) {
      out.push({ id: `case-${c.id}`, group: "Cases", label: c.title, hint: `${c.investigation_count} investigations`,
        icon: <Briefcase className="h-4 w-4" />, run: go(`/cases/${c.id}`) });
    }
    return out;
  }, [q, invs, cases, onClose, router]);

  useEffect(() => setActive(0), [q]);
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[55] flex items-start justify-center bg-black/60 p-4 pt-[12vh] backdrop-blur-sm"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label="Command palette"
        className="w-full max-w-xl overflow-hidden rounded-xl border border-line bg-ink-900 shadow-2xl">
        <div className="flex items-center gap-2 border-b border-line px-4">
          <Search className="h-4 w-4 text-muted" aria-hidden />
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} role="combobox" aria-expanded="true"
            aria-controls="cmdk-list" aria-activedescendant={items[active]?.id}
            placeholder="Type an identifier to investigate, or search…"
            className="h-12 flex-1 bg-transparent text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none"
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              else if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(items.length - 1, a + 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
              else if (e.key === "Enter") { e.preventDefault(); items[active]?.run(); }
            }} />
          <Kbd>esc</Kbd>
        </div>
        <ul id="cmdk-list" role="listbox" className="max-h-[50vh] overflow-y-auto p-2">
          {items.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted">No matches.</li>}
          {items.map((it, idx) => (
            <li key={it.id}>
              {(idx === 0 || items[idx - 1]?.group !== it.group) && (
                <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted">{it.group}</div>
              )}
              <button id={it.id} role="option" aria-selected={idx === active} onMouseEnter={() => setActive(idx)} onClick={it.run}
                className={cx("flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm",
                  idx === active ? "bg-accent-soft text-white" : "text-slate-300")}>
                <span className="text-muted">{it.icon}</span>
                <span className="min-w-0 flex-1 truncate">{it.label}</span>
                {it.hint && <span className="hidden truncate text-xs text-muted sm:inline">{it.hint}</span>}
                {idx === active ? <CornerDownLeft className="h-3.5 w-3.5 text-muted" /> : <ArrowRight className="h-3.5 w-3.5 opacity-0" />}
              </button>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-3 border-t border-line px-4 py-2 text-[11px] text-muted">
          <span><Kbd>↑</Kbd> <Kbd>↓</Kbd> navigate</span><span><Kbd>↵</Kbd> select</span><span><Kbd>⌘K</Kbd> toggle</span>
        </div>
      </div>
    </div>
  );
}
