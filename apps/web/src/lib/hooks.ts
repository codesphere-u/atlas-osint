"use client";

import { useCallback, useEffect, useEffectEvent, useState } from "react";
import { api, ApiError } from "./api";

export function useApi<T>(path: string | null, opts: { pollMs?: number; until?: (d: T) => boolean } = {}) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | null>(null);
  // Loading means "no response yet for the current path"; derived, so a path change needs no state reset.
  const [answeredPath, setAnsweredPath] = useState<string | null>(null);
  const loading = !!path && answeredPath !== path;
  // Always sees the latest `until` callback without restarting the polling effect.
  const isDone = useEffectEvent((d: T) => opts.until?.(d) ?? false);

  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      setData(d);
      setError(null);
      return d;
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
    } finally {
      setAnsweredPath(path);
    }
  }, [path]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;
    const tick = async () => {
      const d = await load();
      if (cancelled || !opts.pollMs) return;
      if (d !== undefined && isDone(d)) return;
      timer = setTimeout(tick, opts.pollMs);
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [load, path, opts.pollMs]);

  return { data, error, loading, reload: load, setData };
}
