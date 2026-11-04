/**
 * Scan dashboard — the day's signals by company (contract: docs/scan_builder/DESIGN.md §11.1; owner 4 Nov ~14:30 IST: "group
 * signals by company symbol and timeline … search by company symbol and name, auto suggestion … by default it lists all signals
 * for that day").
 *
 *   useSignalsDay(enabled, marketOpen)   GET /api/scan-builder/signals/day   every list mark of the day (the dashboard's feed
 *                                         reads only the newest ones), grouped by company, newest activity first: each company's
 *                                         score now, its parts, reasons and penalties, its strong signal if it reached the line
 *                                         (with the plan frozen then), and its marks oldest first.
 *
 * Asked again every 30 s while the market is open (5 min otherwise); a hidden tab does not ask. Asked only when the dashboard's
 * answer carries `scores_meta` (a backend with signal strength). A 403 / 404 / 405 (the feature off, or a backend from before
 * this route) resolves to null and the panel stays hidden; any other failure is shown in the panel with the dashboard intact.
 * Lenient: unknown fields pass, a malformed company or mark is dropped rather than failing the answer.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { NumN, PartsC, PenaltyC, Str, keepGood } from "./market-dashboard-data";

export const SD_PATH = "/api/scan-builder/signals/day";
const KEY = ["copilot", "desk", "scan-dashboard", "signals-day"] as const;
export const DAY_REFRESH_OPEN_MS = 30_000;
export const DAY_REFRESH_CLOSED_MS = 300_000;

const MarkC = z.object({
  time: z.string(),                                   // "HH:MM:SS", IST
  list: z.string().catch("").default(""),             // widget id; its title is in `lists`
  price: NumN,
  direction: z.enum(["long", "short"]).catch("long").default("long"),
}).passthrough();

const DayStrongC = z.object({
  first_strong: z.string(),
  score_at: NumN,
  entry: NumN,
  stop_loss: NumN,
  target_1: NumN,
  target_2: NumN,
  risk_per_share: NumN,
  rr_1: NumN,
  rr_2: NumN,
  atr: NumN,
  sma20: NumN,
  trend_exit: Str.catch(null),
  plan_ok: z.boolean().catch(false).default(false),
  plan_note: Str.catch(null),
  rules: Str.catch(null),
}).passthrough();

export const CompanyC = z.object({
  symbol: z.string().min(1),
  name: z.string().nullable().catch("").default("").transform((v) => v ?? ""),
  score: z.number().nullable().catch(null).default(null),
  parts: PartsC.nullable().optional().catch(null),
  reasons: z.array(z.string()).catch([]).default([]),
  penalties: keepGood(PenaltyC),
  note: Str.catch(null),
  strong: DayStrongC.nullable().optional().catch(null),
  first_seen: Str.catch(null),
  last_seen: Str.catch(null),
  n: z.number().catch(0).default(0),
  marks: keepGood(MarkC),
}).passthrough();

export const SignalsDayC = z.object({
  ok: z.boolean().catch(true).default(true),
  day: z.string().catch("").default(""),
  count: z.number().catch(0).default(0),
  companies_count: z.number().nullable().optional().catch(null),
  threshold: z.number().catch(70).default(70),
  scores_as_of: Str.catch(null),
  lists: z.record(z.unknown()).catch({}).default({}).transform((m) => {
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(m)) if (typeof v === "string") out[k] = v;
    return out;
  }),
  warnings: z.array(z.string()).catch([]).default([]),
  companies: keepGood(CompanyC),
}).passthrough();

export type SignalsDay = z.infer<typeof SignalsDayC>;
export type DayCompany = z.infer<typeof CompanyC>;
export type DayMark = z.infer<typeof MarkC>;
export type DayStrong = z.infer<typeof DayStrongC>;

const drift = (cause: unknown) => new ApiError("contract_drift", "The day's signals were not in the expected form.", { cause });

/** The feature off (403), or a backend without this route (404 / 405): the panel is simply not shown. */
const absent = (e: unknown) => e instanceof ApiError && (e.status === 403 || e.status === 404 || e.status === 405);

export function useSignalsDay(enabled: boolean, marketOpen: boolean) {
  return useQuery<SignalsDay | null>({
    queryKey: [...KEY],
    enabled,
    queryFn: async ({ signal }) => {
      let res;
      try {
        res = await http({ path: SD_PATH, signal, timeoutMs: 30_000, noRetry: true });
      } catch (e) {
        if (absent(e)) return null;
        throw e;
      }
      const r = SignalsDayC.safeParse(res.data);
      if (!r.success) throw drift(r.error);
      return r.data;
    },
    refetchInterval: marketOpen ? DAY_REFRESH_OPEN_MS : DAY_REFRESH_CLOSED_MS,
    refetchIntervalInBackground: false,
    retry: false,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });
}

// ── search ───────────────────────────────────────────────────────────────────────────────────────────────────────────

const norm = (s: string) => s.toLowerCase().replace(/\s+/g, " ").trim();

/** How well a company matches a query (lower is better; null = no match): 0 symbol prefix, 1 a name word starts with it (or
 *  the name starts with the whole query), 2 symbol or name contains it. Case-insensitive; spaces collapsed. */
export function matchRank(c: Pick<DayCompany, "symbol" | "name">, query: string): number | null {
  const q = norm(query);
  if (!q) return 3;
  const sym = c.symbol.toLowerCase();
  const name = norm(c.name || "");
  if (sym.startsWith(q)) return 0;
  if (name.startsWith(q) || name.split(" ").some((w) => w.startsWith(q))) return 1;
  if (sym.includes(q) || name.includes(q)) return 2;
  return null;
}

/** The companies matching a query, best first (rank, then the symbol), at most `max`. */
export function suggest(companies: DayCompany[], query: string, max = 8): DayCompany[] {
  if (!norm(query)) return [];
  return companies
    .map((c) => ({ c, r: matchRank(c, query) }))
    .filter((x): x is { c: DayCompany; r: number } => x.r !== null)
    .sort((a, b) => a.r - b.r || a.c.symbol.localeCompare(b.c.symbol))
    .slice(0, max)
    .map((x) => x.c);
}
