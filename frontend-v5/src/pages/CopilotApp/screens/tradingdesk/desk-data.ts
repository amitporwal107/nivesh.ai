/**
 * Smart trading desk — the data every tab shares: the opportunity list.
 *
 *   GET /api/positional/watchlist?limit=30   four setup buckets with a trigger and a stop  (stock_technical_features + 60 daily bars)
 *   GET /api/positional/picks?limit=30       scored scanner signals with entry, stop, target (positional_signals)
 *   GET /api/move-odds/latest?head=…         the move-odds model's next-session estimates   (DaaS nidp.tpd_*, flag move_odds)
 *
 * All three are end of day. The two scanner routes are merged by symbol: a
 * stock can be in both, in which case the pick's plan (entry, stop, target)
 * is used and the bucket says where the setup stands. The move-odds model is
 * a separate, validated model; its figure is joined by symbol and is a
 * one-session estimate ("P(+5% next session)"), never a multi-day one.
 *
 * Nothing here trusts the response shape: a missing or non-numeric field is
 * null, never 0, and a body without the list the route always sends throws.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { moveOddsService, type MoveFinal, type MoveHead } from "@/services/adapters/moveOdds.adapter";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

export function num(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** A positive price, or null (the scanner stores 0 for "not set"). */
const price = (v: unknown): number | null => {
  const n = num(v);
  return n != null && n > 0 ? n : null;
};

/** A list of strings that may arrive as an array or as a JSON-encoded array (JSONB read without a codec). */
function strList(v: unknown): string[] {
  let raw: unknown = v;
  if (typeof v === "string") {
    try {
      raw = JSON.parse(v);
    } catch {
      return v.trim() ? [v.trim()] : [];
    }
  }
  return arr(raw).filter((x): x is string => typeof x === "string" && x.trim() !== "");
}

const drift = (what: string) => ApiError.contractDrift(what);
const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1;

// ── setups ───────────────────────────────────────────────────────────────

/** The four buckets of GET /api/positional/watchlist, in the route's order of precedence. */
export const SETUP_BUCKETS = ["breakout_confirmed", "pre_breakout", "trend_continuation", "true_accumulation"] as const;
export type SetupBucket = (typeof SETUP_BUCKETS)[number];

export const BUCKET_LABEL: Record<SetupBucket, string> = {
  breakout_confirmed: "Breakout confirmed",
  pre_breakout: "Near breakout",
  trend_continuation: "Trend pullback",
  true_accumulation: "Accumulation",
};

/** The rule each bucket applies (backend/routes/positional.py, get_watchlist), in one line. */
export const BUCKET_RULE: Record<SetupBucket, string> = {
  breakout_confirmed: "Closed 0–3% above the breakout level on at least 1.5× the 20-day average volume.",
  pre_breakout: "Within 2% below resistance with volume at least 1.2× the 20-day average.",
  trend_continuation: "Close above the 20-day EMA, which is above the 50-day average, and within 4% of the 20-day EMA.",
  true_accumulation: "15-day range under 8%, volume contracting, higher lows and small upper wicks.",
};

/** Where a setup stands. "confirmed" = the breakout has happened; the rest are waiting for a trigger. */
export type SetupStatus = "confirmed" | "awaiting" | "forming";

export interface DeskSetup {
  symbol: string;
  sector: string | null;
  /** The watchlist bucket, or null when only the picks route has the stock. */
  bucket: SetupBucket | null;
  /** ACCUMULATION | EARLY_BREAKOUT | BREAKOUT — the scanner's stage. */
  stage: string | null;
  status: SetupStatus;
  /** Rules-based scanner score, 0–100 (final_score × 100). */
  score: number | null;
  /** HIGH | MEDIUM | LOW — the scanner's own grade. */
  confidence: string | null;
  /** End-of-day close on the scan date (watchlist only). */
  close: number | null;
  /** The breakout level the watchlist tracks. */
  trigger: number | null;
  /** The plan: the pick's entry, else the watchlist trigger. */
  entry: number | null;
  /** The pick's stop, else the watchlist's suggested stop (1.5 × ATR below a reference level). */
  stop: number | null;
  /** The pick's target; the watchlist has none. */
  target: number | null;
  /** The pick's reward-to-risk as stored, else (target − entry) ÷ (entry − stop) when all three exist. */
  riskReward: number | null;
  daysMin: number | null;
  daysMax: number | null;
  /** ATR(14) as a percent of the close. */
  atrPct: number | null;
  rsi14: number | null;
  ema20: number | null;
  sma50: number | null;
  /** The watchlist's one-line reason ("Broke above ₹… on 1.8× avg volume"). */
  why: string | null;
  /** The pick's reasons, as stored. */
  reasons: string[];
  /** The scans that matched (picks). */
  scans: string[];
  /** The structural signals the watchlist gate measured (range, volume slope, …), as stored. */
  signals: Record<string, number | null>;
  /** Which routes have this stock. */
  inPicks: boolean;
  inWatchlist: boolean;
}

export interface DeskScanner {
  /** Session the watchlist was computed for. */
  watchAsOf: string | null;
  /** Session of the picks. */
  signalDate: string | null;
  setups: DeskSetup[];
  /** A route that failed while the other answered: the list is partial. */
  partial: Array<"watchlist" | "picks">;
}

function statusOf(bucket: SetupBucket | null, stage: string | null): SetupStatus {
  if (bucket === "breakout_confirmed") return "confirmed";
  if (bucket === "pre_breakout" || bucket === "trend_continuation") return "awaiting";
  if (bucket === "true_accumulation") return "forming";
  const s = (stage ?? "").toUpperCase();
  if (s === "BREAKOUT") return "confirmed";
  if (s === "EARLY_BREAKOUT") return "awaiting";
  return "forming";
}

interface WatchItem {
  symbol: string; bucket: SetupBucket; sector: string | null; stage: string | null; confidence: string | null; score: number | null;
  close: number | null; trigger: number | null; stop: number | null; atrPct: number | null; rsi14: number | null; ema20: number | null;
  sma50: number | null; why: string | null; signals: Record<string, number | null>;
}

interface PickItem {
  symbol: string; stage: string | null; confidence: string | null; score: number | null; entry: number | null; stop: number | null;
  target: number | null; riskReward: number | null; daysMin: number | null; daysMax: number | null; reasons: string[]; scans: string[];
}

async function fetchWatch(signal?: AbortSignal): Promise<{ asOf: string | null; items: WatchItem[] }> {
  // The route re-reads 60 bars per candidate, so it can be slow on a cold cache.
  const res = await http({ path: "/api/positional/watchlist", query: { limit: 30 }, timeoutMs: 30_000, signal });
  const d = rec(res.data);
  if (!("buckets" in d)) throw drift("positional.watchlist: no buckets");
  const buckets = rec(d.buckets);
  const items: WatchItem[] = [];
  for (const bucket of SETUP_BUCKETS) {
    for (const v of arr(buckets[bucket])) {
      const r = rec(v);
      const symbol = str(r.nse_symbol);
      if (!symbol) continue;
      const sig = rec(r.signals);
      const signals: Record<string, number | null> = {};
      for (const k of Object.keys(sig)) signals[k] = num(sig[k]);
      const score = num(r.final_score);
      items.push({
        symbol, bucket, sector: str(r.sector), stage: str(r.stage), confidence: str(r.confidence),
        score: score != null ? score * 100 : null,
        close: price(r.close_price), trigger: price(r.trigger_price), stop: price(r.stop_price),
        atrPct: num(r.atr_pct), rsi14: num(r.rsi_14), ema20: price(r.ema_20), sma50: price(r.sma_50),
        why: str(r.why), signals,
      });
    }
  }
  return { asOf: str(d.as_of_date), items };
}

async function fetchPicks(signal?: AbortSignal): Promise<{ signalDate: string | null; items: PickItem[] }> {
  const res = await http({ path: "/api/positional/picks", query: { limit: 30 }, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.picks)) throw drift("positional.picks: no picks list");
  const items: PickItem[] = [];
  for (const v of d.picks) {
    const p = rec(v);
    const symbol = str(p.nse_symbol);
    if (!symbol) continue;
    const score = num(p.final_score);
    items.push({
      symbol, stage: str(p.stage), confidence: str(p.confidence), score: score != null ? score * 100 : null,
      entry: price(p.entry_price), stop: price(p.stoploss), target: price(p.target_price), riskReward: num(p.risk_reward),
      daysMin: num(p.timeframe_days_min), daysMax: num(p.timeframe_days_max), reasons: strList(p.reasons), scans: strList(p.source_scans),
    });
  }
  return { signalDate: str(d.signal_date), items };
}

/** Reward to risk from three levels, or null when it cannot be worked out (no target, or the stop is not below the entry). */
export function rewardToRisk(entry: number | null, stop: number | null, target: number | null): number | null {
  if (entry == null || stop == null || target == null) return null;
  const risk = entry - stop;
  const reward = target - entry;
  return risk > 0 && reward > 0 ? reward / risk : null;
}

/** Merge the two scanner routes by symbol. Exported for tests of the rule. */
export function mergeSetups(watch: WatchItem[], picks: PickItem[]): DeskSetup[] {
  const bySym = new Map<string, DeskSetup>();
  for (const w of watch) {
    if (bySym.has(w.symbol)) continue; // the route already applies bucket precedence; first wins
    bySym.set(w.symbol, {
      symbol: w.symbol, sector: w.sector, bucket: w.bucket, stage: w.stage, status: statusOf(w.bucket, w.stage),
      score: w.score, confidence: w.confidence, close: w.close, trigger: w.trigger, entry: w.trigger, stop: w.stop, target: null,
      riskReward: null, daysMin: null, daysMax: null, atrPct: w.atrPct, rsi14: w.rsi14, ema20: w.ema20, sma50: w.sma50,
      why: w.why, reasons: [], scans: [], signals: w.signals, inPicks: false, inWatchlist: true,
    });
  }
  for (const p of picks) {
    const have = bySym.get(p.symbol);
    const base: DeskSetup = have ?? {
      symbol: p.symbol, sector: null, bucket: null, stage: p.stage, status: statusOf(null, p.stage), score: p.score,
      confidence: p.confidence, close: null, trigger: null, entry: null, stop: null, target: null, riskReward: null,
      daysMin: null, daysMax: null, atrPct: null, rsi14: null, ema20: null, sma50: null, why: null, reasons: [], scans: [],
      signals: {}, inPicks: true, inWatchlist: false,
    };
    // The pick's plan wins when it has one; the bucket keeps saying where the setup stands.
    const entry = p.entry ?? base.entry;
    const stop = p.stop ?? base.stop;
    const target = p.target ?? base.target;
    bySym.set(p.symbol, {
      ...base,
      stage: base.stage ?? p.stage,
      score: p.score ?? base.score,
      confidence: p.confidence ?? base.confidence,
      entry, stop, target,
      riskReward: p.riskReward ?? rewardToRisk(entry, stop, target),
      daysMin: p.daysMin, daysMax: p.daysMax, reasons: p.reasons, scans: p.scans, inPicks: true,
    });
  }
  for (const s of bySym.values()) {
    if (s.riskReward == null) s.riskReward = rewardToRisk(s.entry, s.stop, s.target);
  }
  return [...bySym.values()].sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
}

/**
 * The opportunity list. Either route may fail on its own; the other's rows
 * are still shown and `partial` names the one that did not answer. Both
 * failing is an error.
 */
export function useDeskScanner() {
  return useQuery<DeskScanner>({
    queryKey: ["copilot", "desk", "scanner"],
    staleTime: 5 * 60_000,
    retry,
    queryFn: async ({ signal }) => {
      const [w, p] = await Promise.allSettled([fetchWatch(signal), fetchPicks(signal)]);
      if (w.status === "rejected" && p.status === "rejected") throw w.reason;
      const watch = w.status === "fulfilled" ? w.value : { asOf: null, items: [] };
      const picks = p.status === "fulfilled" ? p.value : { signalDate: null, items: [] };
      const partial: DeskScanner["partial"] = [];
      if (w.status === "rejected") partial.push("watchlist");
      if (p.status === "rejected") partial.push("picks");
      return { watchAsOf: watch.asOf, signalDate: picks.signalDate, setups: mergeSetups(watch.items, picks.items), partial };
    },
  });
}

// ── move-odds model (next session) ───────────────────────────────────────

export type DeskOdds =
  | { kind: "final"; data: MoveFinal; bySymbol: Map<string, { p: number; events: number }> }
  | { kind: "not_published"; expectedSession: string; lastPublishedFor: string | null }
  | { kind: "withheld"; reason: string }
  | { kind: "no_access" };

/**
 * GET /api/move-odds/latest?head= — one head of the move-odds model for the
 * next session. 403 (account not on the move_odds allowlist), not published
 * and withheld are answers, not errors; anything else throws.
 */
export function useDeskOdds(head: MoveHead = "p_up5_1d") {
  return useQuery<DeskOdds>({
    queryKey: ["copilot", "desk", "odds", head],
    staleTime: 10 * 60_000,
    retry: (count) => count < 1,
    queryFn: async () => {
      const r = await moveOddsService.latest(head);
      if (r.kind === "final") {
        const bySymbol = new Map<string, { p: number; events: number }>();
        for (const row of r.data.rows) bySymbol.set(row.symbol.toUpperCase(), { p: row.p, events: row.events_on_record });
        return { kind: "final", data: r.data, bySymbol };
      }
      if (r.kind === "not_published") return { kind: "not_published", expectedSession: r.data.expected_session, lastPublishedFor: r.data.last_published_for };
      if (r.kind === "withheld") return { kind: "withheld", reason: r.reason };
      if (r.kind === "no_access") return { kind: "no_access" };
      throw new Error(r.message);
    },
  });
}

/** "p_up5_1d" → "P(+5% next session)". */
export function headLabel(head: MoveHead): string {
  const m = /^p_(up|down)(\d+)_1d$/.exec(head);
  if (!m) return head;
  return `P(${m[1] === "up" ? "+" : "−"}${m[2]}% next session)`;
}
