/**
 * Market Overview (desk tab 01, the redesign of 2026-10-27, docs/desk_redesign_20261027/PLAN.md step 2): the reads
 * this tab adds and the pure rules behind its lines. Every other read is an existing hook, shared with the screens
 * that already use it (React Query caches): GET /api/markets/home (useMarketOverview), GET /api/markets/sector-returns
 * (useSectorReturns), GET /api/risk/profile (useRiskProfile), the Top 10 boards and the stored AI watchlist.
 *
 *   GET /api/risk/freshness   (no symbol) the market state the universal risk service sizes and gates with: the regime
 *                             (BULL / BEAR / SIDEWAYS), its key, India VIX, the as-of date, its age in sessions against
 *                             the budget and ok / stale / unknown, plus the reference session (the newest weekday whose
 *                             end-of-day data must exist now). Built by the same functions a decision uses (backend
 *                             routes/risk_controls.py `freshness`), so the strip shows what sizing uses. Read-only.
 *
 * The BEAR rule is the governor's (services/ai_trader/risk_governor.py): in a BEAR regime the size limits of a new
 * trade are multiplied by 0.5 (`bear_regime_size_factor`); with India VIX from 25 up to 35 they are halved too
 * (`vix_reduce_at`, `vix_size_factor`). Nothing here sizes anything: the decision cards show the risk service's sizes.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import type { IntelEvent } from "../../intel-data";
import type { SectorReturn, SectorReturns } from "../../overview-data";
import type { RiskProfileView } from "../../risk-profile";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

// ── GET /api/risk/freshness ──────────────────────────────────────────────

export type FreshnessStatus = "ok" | "stale" | "unknown";

export interface MarketState {
  /** BULL | BEAR | SIDEWAYS (the governor's words), null when it could not be read. */
  regime: string | null;
  /** The desk regime's own key (bearish, high_volatility, …). */
  key: string | null;
  vix: number | null;
  asOf: string | null;
  ageSessions: number | null;
  budget: number | null;
  status: FreshnessStatus;
  reason: string | null;
  source: string | null;
}

export interface RiskFreshness {
  market: MarketState;
  /** The newest weekday whose end-of-day data must exist now (backend data_freshness.reference_session). */
  referenceSession: string | null;
  asOf: string | null;
}

export function readRiskFreshness(body: unknown): RiskFreshness {
  const d = rec(body);
  const inputs = rec(d.inputs);
  if (!Object.keys(rec(inputs.market_state)).length) throw ApiError.contractDrift("risk.freshness: no inputs.market_state");
  const m = rec(inputs.market_state);
  const raw = str(m.status);
  const status: FreshnessStatus = raw === "ok" || raw === "stale" ? raw : "unknown";
  return {
    market: {
      regime: str(m.regime)?.toUpperCase() ?? null, key: str(m.key), vix: num(m.vix), asOf: str(m.as_of),
      ageSessions: num(m.age_sessions), budget: num(m.budget), status, reason: str(m.reason), source: str(m.source),
    },
    referenceSession: str(d.reference_session),
    asOf: str(d.as_of),
  };
}

export const FRESHNESS_KEY = ["copilot", "desk", "risk", "freshness"] as const;

export function useRiskFreshness() {
  return useQuery<RiskFreshness>({
    queryKey: FRESHNESS_KEY,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: (n, e) => !(e instanceof ApiError && (e.status === 401 || e.status === 403 || e.kind === "contract_drift")) && n < 1,
    queryFn: async ({ signal }) => readRiskFreshness((await http({ path: "/api/risk/freshness", signal, noRetry: true })).data),
  });
}

// ── GET /api/desk/paper-account (read-only: cash, capital at risk, starting capital) ──

export interface PaperAccount { startingRs: number | null; cashRs: number | null; blockedRs: number | null; availableRs: number | null; stored: boolean }

export function readPaperAccount(body: unknown): PaperAccount {
  const d = rec(body);
  return { startingRs: num(d.starting_capital_rs), cashRs: num(d.cash_rs), blockedRs: num(d.blocked_rs), availableRs: num(d.available_rs), stored: d.stored === true };
}

export function usePaperAccount() {
  return useQuery<PaperAccount>({
    queryKey: ["copilot", "desk", "paper-account"],
    staleTime: 30_000,
    retry: (n, e) => !(e instanceof ApiError && (e.status === 401 || e.status === 403)) && n < 1,
    queryFn: async ({ signal }) => readPaperAccount((await http({ path: "/api/desk/paper-account", signal, noRetry: true })).data),
  });
}

// ── the regime line ──────────────────────────────────────────────────────

export const BEAR_NOTE = "New-trade size limits are halved in BEAR.";
export const NO_CUT_NOTE = "No regime cut on new-trade size limits (only BEAR halves them).";
/** The governor's volatility band (risk_governor.Limits vix_reduce_at / vix_defer_at). */
export const VIX_REDUCE_AT = 25;
export const VIX_DEFER_AT = 35;

/** The size note for the market state the risk service reads: BEAR halves the limits; VIX 25–35 halves them too. */
export function sizeNotes(m: MarketState): { bear: boolean; text: string; vix: string | null } {
  const bear = m.regime === "BEAR";
  let vix: string | null = null;
  if (m.vix != null && m.vix >= VIX_DEFER_AT) vix = `India VIX at ${VIX_DEFER_AT} or above: the governor defers new positions.`;
  else if (m.vix != null && m.vix >= VIX_REDUCE_AT) vix = `India VIX at ${VIX_REDUCE_AT} or above halves them as well.`;
  return { bear, text: bear ? BEAR_NOTE : NO_CUT_NOTE, vix };
}

// ── sectors ──────────────────────────────────────────────────────────────

/** The day's leaders and laggards by 1-day return: up to `n` each, never the same sector in both lists. */
export function sectorMoves(d: SectorReturns | undefined, n = 3): { up: SectorReturn[]; down: SectorReturn[] } {
  const rows = (d?.sectors ?? []).filter((s) => s.ret["1d"] != null).sort((a, b) => (b.ret["1d"] as number) - (a.ret["1d"] as number));
  const up = rows.slice(0, Math.min(n, Math.ceil(rows.length / 2)));
  const rest = rows.slice(up.length);
  return { up, down: rest.slice(-Math.min(n, rest.length)).reverse() };
}

// ── the one line to Trade Desk (GET /api/risk/profile) ───────────────────

/** "1.2%" / "3%" / "0%": one decimal at most, no trailing zero. */
export function pctText(n: number): string {
  return `${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 }).format(Math.round(n * 10) / 10)}%`;
}

export interface TradeDeskLine {
  /** "3 open positions · open risk 1.2% of 3%" — or why it cannot be said. */
  text: string;
  positions: number | null;
  openRiskPct: number | null;
  limitPct: number | null;
}

/**
 * The open book as the risk service counts it (services/risk_book.py): open desk paper trades and F&O structures, plus
 * any open journal trades (they count against the same limits). Open risk = the reserved and estimated risk of those
 * positions as a % of paper equity; the limit is the profile's max_open_risk_pct.
 */
export function tradeDeskLine(v: RiskProfileView): TradeDeskLine {
  const limitPct = v.profile.limits.max_open_risk_pct ?? null;
  const live = v.live;
  if (!live) return { text: `Open positions and open risk unavailable: ${v.liveError ?? "the account could not be read"}`, positions: null, openRiskPct: null, limitPct };
  const n = live.open.positions;
  const head = n == null ? "Open positions unknown" : n === 0 ? "No open positions" : `${n} open position${n === 1 ? "" : "s"}`;
  const risk = live.open.riskRs;
  const eq = live.equityRs;
  const pct = risk != null && eq != null && eq > 0 ? (risk / eq) * 100 : null;
  const limit = limitPct != null ? ` of ${pctText(limitPct)}` : "";
  const riskText = pct != null
    ? `open risk ${pctText(pct)}${limit}`
    : risk != null
      ? `open risk ₹${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(risk)} (paper equity unknown)${limit ? `, limit${limit.replace(" of", "")}` : ""}`
      : "open risk unknown";
  return { text: `${head} · ${riskText}`, positions: n, openRiskPct: pct, limitPct };
}

// ── events today ─────────────────────────────────────────────────────────

/** The IST calendar day of an ISO time or a bare date. */
export function istDayOf(iso: string | null | undefined): string | null {
  if (!iso) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso;
  const t = new Date(iso);
  return Number.isNaN(t.getTime()) ? null : t.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

export const EVENTS_SHOWN = 5;

/** Today's (IST) filings — results first, then the newest — about the watched names, at most EVENTS_SHOWN. */
export function eventsToday(events: IntelEvent[], names: ReadonlySet<string>, today: string): IntelEvent[] {
  const seen = new Set<string>();
  return events
    .filter((e) => {
      if (!e.filing || !e.symbol || !names.has(e.symbol.toUpperCase()) || istDayOf(e.at) !== today || seen.has(e.id)) return false;
      seen.add(e.id);
      return true;
    })
    .sort((a, b) => Number(b.group === "results") - Number(a.group === "results") || b.sortAt - a.sortAt)
    .slice(0, EVENTS_SHOWN);
}

// ── the ideas' basis ─────────────────────────────────────────────────────

/** A scan (or chain) day older than the reference session is stale: the newest close that must exist is not in it. */
export function isStaleDay(day: string | null | undefined, referenceSession: string | null | undefined): boolean {
  return !!day && !!referenceSession && day.slice(0, 10) < referenceSession.slice(0, 10);
}

/** The 22:45 IST note when the stored list is empty and the route sent no reason of its own (routes/ai_watchlist.NO_LIST_YET). */
export const NO_LIST_YET = "No list is stored yet. The job runs each weekday at 22:45 IST, after the AI scanner's run and the day's NSE F&O bhavcopy, and keeps every day's list.";
