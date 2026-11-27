"use client";

import { CheckCircle2, Info, TriangleAlert, X } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Tone = "success" | "error" | "info";
interface Toast { id: number; tone: Tone; title: string; body?: string }

const ToastCtx = createContext<(tone: Tone, title: string, body?: string) => void>(() => undefined);
export const useToast = () => useContext(ToastCtx);

const ICON = { success: CheckCircle2, error: TriangleAlert, info: Info };
const TONE = { success: "border-ok/40", error: "border-bad/50", info: "border-accent/40" };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: Tone, title: string, body?: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, tone, title, body }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 8000 : 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
        {toasts.map((t) => {
          const Icon = ICON[t.tone];
          return (
            <div key={t.id} role={t.tone === "error" ? "alert" : "status"}
              className={`pointer-events-auto flex items-start gap-3 rounded-lg border bg-ink-800/95 p-3 shadow-xl backdrop-blur ${TONE[t.tone]}`}>
              <Icon className={t.tone === "error" ? "mt-0.5 h-4 w-4 text-bad" : t.tone === "success" ? "mt-0.5 h-4 w-4 text-ok" : "mt-0.5 h-4 w-4 text-accent"} aria-hidden />
              <div className="min-w-0 flex-1 text-sm">
                <div className="font-medium text-slate-100">{t.title}</div>
                {t.body && <div className="mt-0.5 text-xs text-muted">{t.body}</div>}
              </div>
              <button aria-label="Dismiss" className="text-muted hover:text-white" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastCtx.Provider>
  );
}
