"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { cx, Spinner } from "./ui";

const UserContext = createContext<User | null>(null);
export const useUser = () => useContext(UserContext);

const NAV: { section: string; items: { href: string; label: string; roles?: string[] }[] }[] = [
  {
    section: "Workspace",
    items: [
      { href: "/", label: "Overview" },
      { href: "/investigations/new", label: "New investigation", roles: ["admin", "analyst"] },
      { href: "/history", label: "Investigation history" },
    ],
  },
  {
    section: "Intelligence",
    items: [
      { href: "/intel/phone", label: "Phone" },
      { href: "/intel/username", label: "Username" },
      { href: "/intel/name", label: "Name" },
      { href: "/intel/email", label: "Email" },
      { href: "/intel/domain", label: "Domain & infrastructure" },
      { href: "/intel/records", label: "Public records" },
    ],
  },
  {
    section: "Platform",
    items: [
      { href: "/sources", label: "Source management" },
      { href: "/admin", label: "Administration", roles: ["admin", "auditor"] },
    ],
  },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api<User>("/api/v1/auth/me").then(setUser).catch(() => undefined);
  }, []);
  useEffect(() => setOpen(false), [pathname]);

  async function logout() {
    await api("/api/v1/auth/logout", { method: "POST" }).catch(() => undefined);
    router.push("/login");
  }

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Checking session" />
      </div>
    );
  }

  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  return (
    <UserContext.Provider value={user}>
      <div className="flex min-h-screen">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-accent focus:px-3 focus:py-2 focus:text-ink-950">
          Skip to content
        </a>
        <aside
          className={cx(
            "fixed inset-y-0 left-0 z-40 w-64 shrink-0 border-r border-line bg-ink-900 transition-transform lg:static lg:translate-x-0",
            open ? "translate-x-0" : "-translate-x-full",
          )}
          aria-label="Primary"
        >
          <div className="flex h-14 items-center gap-2 border-b border-line px-4">
            <span aria-hidden className="grid h-7 w-7 place-items-center rounded bg-accent/20 font-mono text-xs font-bold text-accent">A</span>
            <div>
              <div className="text-sm font-semibold tracking-wide text-white">ATLAS OSINT</div>
              <div className="text-[10px] text-muted">Connected evidence</div>
            </div>
          </div>
          <nav className="space-y-5 overflow-y-auto p-3">
            {NAV.map((group) => (
              <div key={group.section}>
                <div className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">{group.section}</div>
                <ul className="space-y-0.5">
                  {group.items
                    .filter((i) => !i.roles || i.roles.includes(user.role))
                    .map((item) => (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          aria-current={isActive(item.href) ? "page" : undefined}
                          className={cx(
                            "block rounded-md px-2 py-1.5 text-sm",
                            isActive(item.href) ? "bg-accent-soft text-white" : "text-slate-300 hover:bg-ink-800 hover:text-white",
                          )}
                        >
                          {item.label}
                        </Link>
                      </li>
                    ))}
                </ul>
              </div>
            ))}
          </nav>
        </aside>
        {open && <button aria-label="Close menu" className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setOpen(false)} />}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b border-line bg-ink-950/90 px-4 backdrop-blur">
            <button className="rounded p-2 text-slate-300 hover:bg-ink-800 lg:hidden" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)}>
              <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden><path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.6" /></svg>
            </button>
            <div className="hidden text-xs text-muted sm:block">Lawful, authorised use only · all actions are audited</div>
            <div className="flex items-center gap-3 text-sm">
              <span className="hidden text-slate-300 sm:inline">{user.email}</span>
              <span className="rounded border border-line px-2 py-0.5 text-xs text-muted">{user.role}</span>
              <button onClick={logout} className="text-muted hover:text-white">Sign out</button>
            </div>
          </header>
          <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">{children}</main>
        </div>
      </div>
    </UserContext.Provider>
  );
}
