/**
 * Query hooks for endpoints that had no react-query hook yet. Each wraps an
 * existing adapter (filings) or reads an existing backend route with `http`.
 * Reads only — nothing here changes data.
 */
import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { filingsService, type FeedParams } from "@/services/adapters/filings.adapter";
import { useThematicQueries } from "@/hooks/useThematicQueries";

// ── filings ──────────────────────────────────────────────────────────────

/** GET /api/filings/signals — the top material filings (today, or the latest). */
export function useFilingSignals(todayOnly: boolean) {
  return useQuery({
    queryKey: ["filings", "signals", todayOnly],
    queryFn: () => filingsService.getSignals(1, todayOnly),
    staleTime: 60_000,
  });
}

/** GET /api/filings/feed — classified filings with facet counts and a total. */
export function useFilingsFeed(params: FeedParams, enabled = true) {
  return useQuery({
    queryKey: ["filings", "feed", params],
    queryFn: () => filingsService.getFeed(params),
    enabled,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  });
}

/** GET /api/filings/alerts — the signed-in user's filing-alert preferences. */
export function useFilingAlerts() {
  return useQuery({
    queryKey: ["filings", "alerts"],
    queryFn: () => filingsService.getAlerts(),
    staleTime: 60_000,
  });
}

export interface HeldKeys {
  names: Set<string>;
  symbols: Set<string>;
}

/** Same normalisation the backend applies to holding names (routes/filings.py). */
function normName(x: string | null | undefined): string {
  return (x ?? "")
    .toLowerCase()
    .replace(/\b(limited|ltd|corporation|corp|company|co|pvt|private)\b/g, "")
    .replace(/[^a-z0-9]/g, "");
}

/** True when a company (by NSE symbol or name) is in the user's holdings. */
export function isHeld(held: HeldKeys | undefined, symbol?: string | null, name?: string | null): boolean {
  if (!held) return false;
  if (symbol && held.symbols.has(symbol.toUpperCase())) return true;
  const n = normName(name);
  return !!n && held.names.has(n);
}

/**
 * GET /api/filings/portfolio-held — match keys for the "You hold" badge. The
 * adapter answers with empty sets when there are no holdings or the call fails,
 * so a missing badge never blocks a table.
 */
export function useHeldKeys() {
  return useQuery({
    queryKey: ["filings", "portfolio-held"],
    queryFn: async (): Promise<HeldKeys> => {
      const h = await filingsService.getPortfolioHeld();
      return { names: new Set(h.names), symbols: new Set(h.symbols.map((s) => s.toUpperCase())) };
    },
    staleTime: 5 * 60_000,
  });
}

// ── thematic research questions (history + favourites) ───────────────────

const ThematicPrefsC = z.object({
  history: z.array(z.string()).default([]),
  favorites: z.array(z.string()).default([]),
});
export type ThematicPrefs = z.infer<typeof ThematicPrefsC>;

const THEMATIC_KEY = ["thematic", "prefs"] as const;
/** Same cap the backend and useThematicQueries apply to history. */
const HISTORY_CAP = 40;

/** GET /api/thematic/prefs — the user's research-question history and favourites. */
export function useThematicPrefs() {
  return useQuery({
    queryKey: THEMATIC_KEY,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/thematic/prefs", signal });
      return ThematicPrefsC.parse(res.data);
    },
    staleTime: 60_000,
  });
}

/**
 * The read query above plus the app's existing writers (useThematicQueries).
 * That hook keeps its own copy of the lists and exposes no loading or error
 * state, so the screen reads from the query and mirrors each write into the
 * query cache the same way the hook updates its own state.
 */
export function useThematicLibrary() {
  const prefs = useThematicPrefs();
  const { addHistory: writeHistory, removeHistory: dropHistory, toggleFavorite: writeFavorite } = useThematicQueries();
  const qc = useQueryClient();

  const patch = useCallback(
    (fn: (p: ThematicPrefs) => ThematicPrefs) => {
      qc.setQueryData<ThematicPrefs>(THEMATIC_KEY, (p) => (p ? fn(p) : p));
    },
    [qc],
  );

  const addHistory = useCallback(
    (question: string) => {
      const q = question.trim();
      if (!q) return;
      writeHistory(q);
      patch((p) => ({ ...p, history: [q, ...p.history.filter((x) => x !== q)].slice(0, HISTORY_CAP) }));
    },
    [writeHistory, patch],
  );

  const removeHistory = useCallback(
    (question: string) => {
      dropHistory(question);
      patch((p) => ({ ...p, history: p.history.filter((x) => x !== question) }));
    },
    [dropHistory, patch],
  );

  const toggleFavorite = useCallback(
    (question: string) => {
      const q = question.trim();
      if (!q) return;
      writeFavorite(q);
      patch((p) => ({
        ...p,
        favorites: p.favorites.includes(q) ? p.favorites.filter((x) => x !== q) : [q, ...p.favorites],
      }));
    },
    [writeFavorite, patch],
  );

  return { prefs, addHistory, removeHistory, toggleFavorite };
}

// ── one company's reported numbers ───────────────────────────────────────

const num = z.number().nullish();

const QuarterRowC = z.object({
  quarter: z.string().nullish(),
  period_end: z.string().nullish(),
  /** ₹ crore. */
  revenue_cr: num,
  ebitda_cr: num,
  pat_cr: num,
  /** ₹ per share. */
  eps_basic: num,
  /** Percent units. */
  ebitda_margin_pct: num,
  revenue_yoy_pct: num,
  pat_yoy_pct: num,
});
export type QuarterRow = z.infer<typeof QuarterRowC>;

const HoldingRowC = z.object({
  period: z.string().nullish(),
  period_end: z.string().nullish(),
  /** Percent of equity. */
  promoter_pct: num,
  promoter_pledged_pct: num,
  fii_pct: num,
  dii_pct: num,
  mf_pct: num,
  public_pct: num,
});
export type HoldingRow = z.infer<typeof HoldingRowC>;

const FeaturesC = z.object({
  pe_ttm: num,
  pb: num,
  /** Percent units. */
  roe_pct: num,
  debt_to_equity: num,
  /** ₹ crore. */
  market_cap_cr: num,
  market_cap_bucket: z.string().nullish(),
});
export type CompanyFeatures = z.infer<typeof FeaturesC>;

const CompanyFinancialsC = z.object({
  data: z
    .object({
      error: z.string().nullish(),
      /** Latest daily features; absent when the data platform has none for the symbol. */
      v3_score: FeaturesC.nullish(),
      /** Quarter rows, newest first, followed by shareholding rows tagged `_type`. */
      rows: z.array(z.record(z.unknown())).default([]),
    })
    .nullish(),
});

export interface CompanyNumbers {
  quarters: QuarterRow[];
  holdings: HoldingRow[];
  features: CompanyFeatures | null;
}

/**
 * POST /api/copilot/widgets/company_financials — reported quarterly results,
 * the shareholding pattern and the latest valuation features for one NSE symbol.
 * A read: the route only fetches from the data platform. The envelope's outlook
 * label and score are a heuristic and are deliberately not read here.
 */
export function useCompanyNumbers(symbol: string) {
  return useQuery({
    queryKey: ["copilot-widgets", "company-financials", symbol],
    enabled: !!symbol,
    staleTime: 5 * 60_000,
    queryFn: async ({ signal }): Promise<CompanyNumbers> => {
      const res = await http({
        method: "POST",
        path: "/api/copilot/widgets/company_financials",
        body: { symbol, quarters: 8 },
        signal,
      });
      const data = CompanyFinancialsC.parse(res.data).data;
      if (data?.error) throw new Error(data.error);
      const quarters: QuarterRow[] = [];
      const holdings: HoldingRow[] = [];
      for (const row of data?.rows ?? []) {
        if (row._type === "shareholding") {
          const h = HoldingRowC.safeParse(row);
          if (h.success) holdings.push(h.data);
        } else {
          const q = QuarterRowC.safeParse(row);
          if (q.success) quarters.push(q.data);
        }
      }
      return { quarters, holdings, features: data?.v3_score ?? null };
    },
  });
}
