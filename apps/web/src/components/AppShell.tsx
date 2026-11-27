"use client";

import {
  AtSign, Briefcase, Building2, ChevronsLeft, ChevronsRight, Database, Globe, History, LayoutDashboard, LogOut,
  Mail, Menu, Phone, Plus, Radar, Search, Settings, UserRound,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { ToastProvider } from "@/lib/toast";
import type { User } from "@/lib/types";
import { CommandPalette } from "./CommandPalette";
import { cx, Kbd, Spinner } from "./ui";

const UserContext = createContext<User | null>(null);
export const useUser = () => useContext(UserContext);

type NavItem = { href: string; label: string; icon: ReactNode; roles?: string[] };
const I = "h-4 w-4 shrink-0";
const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: "Workspace",
    items: [
      { href: "/", label: "Overview", icon: <LayoutDashboard className={I} /> },
      { href: "/investigations/new", label: "New investigation", icon: <Plus className={I} />, roles: ["admin", "analyst"] },
      { href: "/cases", label: "Cases", icon: <Briefcase className={I} /> },
      { href: "/history", label: "History", icon: <History className={I} /> },
    ],
  },
  {
    section: "Intelligence",
    items: [
      { href: "/intel/phone", label: "Phone", icon: <Phone className={I} /> },
      { href: "/intel/username", label: "Username", icon: <AtSign className={I} /> },
      { href: "/intel/name", label: "Name", icon: <UserRound className={I} /> },
      { href: "/intel/email", label: "Email", icon: <Mail className={I} /> },
      { href: "/intel/domain", label: "Domain & infrastructure", icon: <Globe className={I} /> },
      { href: "/intel/records", label: "Public records", icon: <Building2 className={I} /> },
    ],
  },
  {
    section: "Platform",
    items: [
      { href: "/sources", label: "Sources", icon: <Database className={I} /> },
      { href: "/admin", label: "Administration", icon: <Settings className={I} />, roles: ["admin", "auditor"] },
    ],
  },
];

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem("atlas.sidebar") === "collapsed";
  } catch {
    return false;
  }
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [palette, setPalette] = useState(false);

  useEffect(() => {
    api<User>("/api/v1/auth/me").then(setUser).catch(() => undefined);
    setCollapsed(readCollapsed());
  }, []);
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      } else if (e.key === "/" && !typing) {
        e.preventDefault();
        setPalette(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function toggleCollapsed() {
    setCollapsed((c) => {
      try {
        window.localStorage.setItem("atlas.sidebar", c ? "expanded" : "collapsed");
      } catch {
        /* storage unavailable: preference is per-session only */
      }
      return !c;
    });
  }

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
  const narrow = collapsed && !open;
  return (
    <UserContext.Provider value={user}>
      <ToastProvider>
        <div className="flex min-h-screen">
          <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-accent focus:px-3 focus:py-2 focus:text-ink-950">
            Skip to content
          </a>
          <aside
            className={cx(
              "fixed inset-y-0 left-0 z-40 flex shrink-0 flex-col border-r border-line bg-ink-900 transition-[width,transform] lg:sticky lg:top-0 lg:h-screen lg:translate-x-0",
              open ? "translate-x-0" : "-translate-x-full",
              narrow ? "w-64 lg:w-16" : "w-64",
            )}
            aria-label="Primary"
          >
            <div className="flex h-14 items-center gap-2.5 border-b border-line px-4">
              <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-accent/30 to-accent/5 ring-1 ring-accent/40">
                <Radar className="h-4 w-4 text-accent" />
              </span>
              <div className={cx("min-w-0", narrow && "lg:hidden")}>
                <div className="text-sm font-semibold tracking-wide text-white">ATLAS OSINT</div>
                <div className="text-[10px] text-muted">Connected evidence</div>
              </div>
            </div>
            <nav className="flex-1 space-y-5 overflow-y-auto p-3">
              {NAV.map((group) => (
                <div key={group.section}>
                  <div className={cx("px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted", narrow && "lg:sr-only")}>
                    {group.section}
                  </div>
                  <ul className="space-y-0.5">
                    {group.items
                      .filter((i) => !i.roles || i.roles.includes(user.role))
                      .map((item) => (
                        <li key={item.href}>
                          <Link
                            href={item.href}
                            title={narrow ? item.label : undefined}
                            aria-current={isActive(item.href) ? "page" : undefined}
                            className={cx(
                              "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm",
                              isActive(item.href) ? "bg-accent-soft text-white" : "text-slate-300 hover:bg-ink-800 hover:text-white",
                              narrow && "lg:justify-center",
                            )}
                          >
                            {item.icon}
                            <span className={cx("truncate", narrow && "lg:sr-only")}>{item.label}</span>
                          </Link>
                        </li>
                      ))}
                  </ul>
                </div>
              ))}
            </nav>
            <button onClick={toggleCollapsed} className="hidden items-center gap-2 border-t border-line px-4 py-3 text-xs text-muted hover:text-white lg:flex"
              aria-label={narrow ? "Expand sidebar" : "Collapse sidebar"}>
              {narrow ? <ChevronsRight className="h-4 w-4" /> : <><ChevronsLeft className="h-4 w-4" /> Collapse</>}
            </button>
          </aside>
          {open && <button aria-label="Close menu" className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setOpen(false)} />}
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-ink-950/85 px-4 backdrop-blur">
              <button className="rounded p-2 text-slate-300 hover:bg-ink-800 lg:hidden" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)}>
                <Menu className="h-5 w-5" />
              </button>
              <button onClick={() => setPalette(true)}
                className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border border-line bg-ink-900 px-3 text-left text-sm text-muted hover:border-accent/50 sm:max-w-md">
                <Search className="h-4 w-4 shrink-0" />
                <span className="truncate">Investigate an identifier or search…</span>
                <span className="ml-auto hidden gap-1 sm:flex"><Kbd>⌘</Kbd><Kbd>K</Kbd></span>
              </button>
              <div className="ml-auto flex items-center gap-3 text-sm">
                <span className="hidden text-xs text-muted xl:inline">Lawful, authorised use only · audited</span>
                <span className="hidden text-slate-300 md:inline">{user.email}</span>
                <span className="rounded border border-line px-2 py-0.5 text-xs capitalize text-muted">{user.role}</span>
                <button onClick={logout} className="rounded p-1.5 text-muted hover:bg-ink-800 hover:text-white" aria-label="Sign out" title="Sign out">
                  <LogOut className="h-4 w-4" />
                </button>
              </div>
            </header>
            <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6">{children}</main>
          </div>
        </div>
        <CommandPalette open={palette} onClose={() => setPalette(false)} />
      </ToastProvider>
    </UserContext.Provider>
  );
}
