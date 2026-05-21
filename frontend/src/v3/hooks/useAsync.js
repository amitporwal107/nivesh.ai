import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Tiny async-data hook used by V3 adapters. Calls `fn` on mount (and on any
 * key change), tracks loading/error, and exposes a `refetch` callback.
 *
 *   const { data, loading, error, refetch } = useAsync(() => apiGet("/foo"), []);
 *
 * `fn` should return `{ data, error }` (the apiClient shape).
 * The hook unwraps that into a plain { data, error } pair plus loading.
 */
export function useAsync(fn, deps = [], { initialData = null } = {}) {
  const [state, setState] = useState({ data: initialData, loading: true, error: null });
  const mounted = useRef(true);

  // Capture deps as a stable key so refetch doesn't re-create the closure.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stableFn = useCallback(fn, deps);

  const run = useCallback(async () => {
    if (!mounted.current) return;
    setState((s) => ({ ...s, loading: true, error: null }));
    const res = await stableFn();
    if (!mounted.current) return;
    setState((prev) => ({
      // Keep previous data if request returns nothing usable, so screens don't flicker to empty.
      data: res?.data != null ? res.data : prev.data,
      loading: false,
      error: res?.error ?? null,
    }));
  }, [stableFn]);

  useEffect(() => {
    mounted.current = true;
    run();
    return () => {
      mounted.current = false;
    };
  }, [run]);

  return { ...state, refetch: run };
}
