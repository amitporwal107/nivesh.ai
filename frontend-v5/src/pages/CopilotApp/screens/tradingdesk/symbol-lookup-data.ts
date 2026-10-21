/**
 * Smart trading desk — the NSE symbol lookup's reads (GET only; nothing here changes data, nothing is stored server-side).
 *
 *   GET /api/markets/symbol-lookup?q=&limit=&fno_only=&recent=   ranked stocks for partial text (a symbol, a company-name
 *                                                                  fragment, an ISIN, or a typo); for empty text the scanner's
 *                                                                  top setups today. Source: DaaS /v1/symbols/universe
 *                                                                  (nidp.sector_master, prices_eod_adjusted, security_reference_daily).
 *
 * A failed lookup is never a failed screen: callers fall back to what they did before the lookup existed.
 */
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";

const Range = z.tuple([z.number(), z.number()]);
const ResultC = z.object({
  symbol: z.string(),
  name: z.string().nullable().optional(),
  isin: z.string().nullable().optional(),
  sector: z.string().nullable().optional(),
  industry: z.string().nullable().optional(),
  fno_eligible: z.boolean().nullable().optional(),
  in_scanner: z.boolean().nullable().optional(),
  last_price_date: z.string().nullable().optional(),
  has_prices: z.boolean().nullable().optional(),
  match: z.string().optional(),
  matched_on: z.string().optional(),
  highlight: z.object({ symbol: z.array(Range).catch([]), name: z.array(Range).catch([]) }).partial().optional(),
}).passthrough();
const LookupC = z.object({
  query: z.string().catch(""),
  exact: ResultC.nullable().catch(null),
  results: z.array(ResultC),
  reason: z.string().nullable().catch(null),
  popular: z.array(ResultC).catch([]),
  recent: z.array(ResultC).catch([]),
  source: z.string().nullable().catch(null),
  as_of: z.string().nullable().catch(null),
}).passthrough();

export type LookupResult = z.infer<typeof ResultC>;
export type LookupBody = z.infer<typeof LookupC>;

export interface LookupOpts { limit?: number; fnoOnly?: boolean }

export async function fetchLookup(q: string, opts: LookupOpts = {}, signal?: AbortSignal): Promise<LookupBody> {
  const res = await http({
    path: "/api/markets/symbol-lookup",
    query: { q, limit: opts.limit ?? 8, ...(opts.fnoOnly ? { fno_only: true } : {}) },
    signal,
    noRetry: true,
    timeoutMs: 6000,
  });
  const r = LookupC.safeParse(res.data);
  if (!r.success) throw new Error(`symbol-lookup: ${r.error.issues[0]?.message ?? "unexpected shape"}`);
  return r.data;
}

export type LookupState =
  | { status: "idle" }
  | { status: "loading"; prev: LookupBody | null }
  | { status: "ok"; data: LookupBody; q: string }
  | { status: "error"; q: string };

export const LOOKUP_DEBOUNCE_MS = 150;

/**
 * Debounced lookup of `text`. A newer text aborts the older request and an answer for an older text is never shown.
 * `enabled` false (the box is closed) sends nothing. Empty text asks for the popular list only when `wantEmpty`.
 */
export function useLookup(text: string, opts: LookupOpts & { enabled: boolean; wantEmpty: boolean }): LookupState {
  const [state, setState] = useState<LookupState>({ status: "idle" });
  const last = useRef<LookupBody | null>(null);
  const t = text.trim();
  const { enabled, wantEmpty, limit, fnoOnly } = opts;
  useEffect(() => {
    if (!enabled) return;                                    // closed: keep the last answer, so reopening with the arrow keys has rows
    if (!t && !wantEmpty) { setState({ status: "idle" }); return; }
    const ctrl = new AbortController();
    setState({ status: "loading", prev: last.current });
    const timer = setTimeout(() => {
      fetchLookup(t, { limit, fnoOnly }, ctrl.signal)
        .then((data) => { if (ctrl.signal.aborted) return; last.current = data; setState({ status: "ok", data, q: t }); })
        .catch(() => { if (!ctrl.signal.aborted) setState({ status: "error", q: t }); });
    }, t ? LOOKUP_DEBOUNCE_MS : 0);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [t, enabled, wantEmpty, limit, fnoOnly]);
  return state;
}

/**
 * Is `symbol` a stock the lookup knows? `unknown` only when it is NOT an exact match and the lookup offers stocks with prices
 * instead. A lookup that fails, or finds nothing at all, is never `unknown`: the symbol may be one the lookup merely cannot see.
 */
export async function checkSymbol(symbol: string, signal?: AbortSignal): Promise<{ unknown: boolean; suggestions: LookupResult[] }> {
  try {
    const body = await fetchLookup(symbol, { limit: 5 }, signal);
    if (body.results.some((r) => r.match === "exact" && r.symbol.toUpperCase() === symbol.toUpperCase())) return { unknown: false, suggestions: [] };
    const suggestions = suggestionsFor(body, symbol);
    return { unknown: suggestions.length > 0, suggestions };
  } catch {
    return { unknown: false, suggestions: [] };
  }
}

/** "Did you mean": the stocks that nearly match `symbol`, for a stock with no prices on record. Off until `enabled`. */
export function useDidYouMean(symbol: string | null, enabled: boolean) {
  return useQuery<LookupBody>({
    queryKey: ["copilot", "desk", "symbol-lookup", (symbol ?? "").toUpperCase()],
    enabled: enabled && !!symbol,
    staleTime: 5 * 60_000,
    retry: false,
    queryFn: ({ signal }) => fetchLookup((symbol ?? "").toUpperCase(), { limit: 5 }, signal),
  });
}

/** The suggestions to offer for a symbol that has no prices: results other than itself that do have prices. */
export function suggestionsFor(body: LookupBody | undefined, symbol: string): LookupResult[] {
  const s = symbol.toUpperCase();
  return (body?.results ?? []).filter((r) => r.symbol.toUpperCase() !== s && r.has_prices !== false);
}

// ── recents (this browser only) ──────────────────────────────────────────

export const RECENT_KEY = "nivesh.desk.symbol-recents";
export const RECENT_MAX = 8;
export interface Recent { symbol: string; name: string | null }

export function readRecents(): Recent[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.filter((r) => r && typeof r.symbol === "string").slice(0, RECENT_MAX).map((r) => ({ symbol: r.symbol, name: typeof r.name === "string" ? r.name : null })) : [];
  } catch { return []; }
}
export function pushRecent(r: Recent): Recent[] {
  const next = [r, ...readRecents().filter((x) => x.symbol !== r.symbol)].slice(0, RECENT_MAX);
  try { window.localStorage.setItem(RECENT_KEY, JSON.stringify(next)); } catch { /* storage blocked: recents just don't persist */ }
  return next;
}
export function clearRecents(): Recent[] {
  try { window.localStorage.removeItem(RECENT_KEY); } catch { /* nothing stored that we could remove */ }
  return [];
}
