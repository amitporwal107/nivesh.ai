/**
 * Smart trading desk — the data every tab shares: the opportunity list.
 *
 *   GET /api/positional/watchlist?limit=30   four setup buckets with a trigger and a stop  (stock_technical_features + 60 daily bars),
 *                                            the next resistance / support, and per row the last 24 daily closes
 *                                            (spark_closes, spark_end) and the 20-session average traded value
 *                                            (avg_traded_value_cr_20d, ₹ crore a day) from stock_ohlcv; `rules` (every
 *                                            threshold with its version) and the engine versions behind the rows
 *   GET /api/positional/picks?limit=30       scored scanner signals with entry, stop, target (positional_signals),
 *                                            with the same spark and traded-value fields, the rules version and engine versions
 *   GET /api/positional/scan-universe        the universe categories (momentum, unusual volume, results-day momentum, F&O
 *       ?setups=&symbols=                    candidates), the eligible universe with every exclusion counted, each row's
 *                                            end-of-day figures, risk and liquidity class, and the move-odds model's rank
 *                                            percentile within the eligible universe   (useScanUniverse; DaaS feature store)
 *   GET /api/move-odds/latest?head=…         the move-odds model's next-session estimates   (DaaS nidp.tpd_*, flag move_odds)
 *
 * All are end of day. The two scanner routes are read once for the desk and the Trader screens
 * (useScannerRoutes, trading/queries.ts) and merged here by symbol: a stock can be in both, in which case the
 * pick's plan (entry, stop, target) is used and the bucket says where the setup stands. The move-odds model is a
 * separate model; its figure is joined by symbol and is a one-session estimate ("P(+5% next session)"), never a
 * multi-day one, and the desk shows it only when the route marks it calibrated (PRD §5.8; see probabilityGate).
 *
 * Nothing here trusts the response shape: a missing or non-numeric field is null, never 0, and a body without the
 * list the route always sends throws.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { moveOddsService, type MoveFinal, type MoveHead } from "@/services/adapters/moveOdds.adapter";
import { useScannerRoutes, type ScannerRoutes } from "../trading/queries";
import { fmtDay } from "../trading/parts";

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

/** The last daily closes, oldest first; only positive numbers are kept (a missing bar is dropped, not drawn as 0). */
function closes(v: unknown): number[] {
  return arr(v).flatMap((x) => {
    const n = price(x);
    return n == null ? [] : [n];
  });
}

/** A non-negative figure (a traded value), or null. */
const nonNeg = (v: unknown): number | null => {
  const n = num(v);
  return n != null && n >= 0 ? n : null;
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
  /** The watchlist's next resistance above / support below the close (watchlist only). */
  resistance: number | null;
  support: number | null;
  /** The last daily closes (up to 24), oldest first; empty when the route sent none. */
  spark: number[];
  /** Session of the last close in `spark`. */
  sparkEnd: string | null;
  /** Mean of close × volume over the last 20 sessions, ₹ crore a day; null when the route sent none. */
  avgTradedCr: number | null;
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
  /** The thresholds the watchlist used, with their version (backend setup_rules.py); null when the route sent none. */
  rules: ScanRules | null;
  /** The watchlist classifier ("smart_v2"), the rules version the picks route names, and the engine versions behind the rows. */
  classifierVersion: string | null;
  rulesVersion: string | null;
  engineVersions: string[];
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
  sma50: number | null; why: string | null; signals: Record<string, number | null>; resistance: number | null; support: number | null;
  spark: number[]; sparkEnd: string | null; avgTradedCr: number | null;
}

interface PickItem {
  symbol: string; stage: string | null; confidence: string | null; score: number | null; entry: number | null; stop: number | null;
  target: number | null; riskReward: number | null; daysMin: number | null; daysMax: number | null; reasons: string[]; scans: string[];
  spark: number[]; sparkEnd: string | null; avgTradedCr: number | null;
}

/** GET /api/positional/watchlist's body (its `buckets` already checked by the shared read). */
function parseWatch(d: Raw): { asOf: string | null; items: WatchItem[] } {
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
        why: str(r.why), signals, resistance: price(r.resistance_level), support: price(r.support_level),
        spark: closes(r.spark_closes), sparkEnd: str(r.spark_end), avgTradedCr: nonNeg(r.avg_traded_value_cr_20d),
      });
    }
  }
  return { asOf: str(d.as_of_date), items };
}

/** GET /api/positional/picks's body (its `picks` list already checked by the shared read). */
function parsePicks(d: Raw): { signalDate: string | null; items: PickItem[] } {
  const items: PickItem[] = [];
  for (const v of arr(d.picks)) {
    const p = rec(v);
    const symbol = str(p.nse_symbol);
    if (!symbol) continue;
    const score = num(p.final_score);
    items.push({
      symbol, stage: str(p.stage), confidence: str(p.confidence), score: score != null ? score * 100 : null,
      entry: price(p.entry_price), stop: price(p.stoploss), target: price(p.target_price), riskReward: num(p.risk_reward),
      daysMin: num(p.timeframe_days_min), daysMax: num(p.timeframe_days_max), reasons: strList(p.reasons), scans: strList(p.source_scans),
      spark: closes(p.spark_closes), sparkEnd: str(p.spark_end), avgTradedCr: nonNeg(p.avg_traded_value_cr_20d),
    });
  }
  return { signalDate: str(d.signal_date), items };
}

/**
 * ₹10 Cr a day, the desk's liquidity gate (owner decision 2026-10-14). The scanner takes the threshold from the route
 * (`rules.liquidity.minCr`, backend setup_rules.py LIQUIDITY); this copy is kept for the screens that do not read the
 * rules yet and must equal that value.
 */
export const LIQUID_MIN_CR = 10;

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
      resistance: w.resistance, support: w.support, spark: w.spark, sparkEnd: w.sparkEnd, avgTradedCr: w.avgTradedCr,
    });
  }
  for (const p of picks) {
    const have = bySym.get(p.symbol);
    const base: DeskSetup = have ?? {
      symbol: p.symbol, sector: null, bucket: null, stage: p.stage, status: statusOf(null, p.stage), score: p.score,
      confidence: p.confidence, close: null, trigger: null, entry: null, stop: null, target: null, riskReward: null,
      daysMin: null, daysMax: null, atrPct: null, rsi14: null, ema20: null, sma50: null, why: null, reasons: [], scans: [],
      signals: {}, inPicks: true, inWatchlist: false, resistance: null, support: null, spark: [], sparkEnd: null, avgTradedCr: null,
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
      // Both routes read the same daily bars; the watchlist's figures are used when it has the stock.
      spark: base.spark.length > 1 ? base.spark : p.spark,
      sparkEnd: base.spark.length > 1 ? base.sparkEnd : p.sparkEnd,
      avgTradedCr: base.avgTradedCr ?? p.avgTradedCr,
    });
  }
  for (const s of bySym.values()) {
    if (s.riskReward == null) s.riskReward = rewardToRisk(s.entry, s.stop, s.target);
  }
  return [...bySym.values()].sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
}

/** The desk's view of the shared scanner read. Both routes failing is the shared read's own error. */
export function toDeskScanner(r: ScannerRoutes): DeskScanner {
  const watch = r.watch ? parseWatch(r.watch) : { asOf: null, items: [] };
  const picks = r.picks ? parsePicks(r.picks) : { signalDate: null, items: [] };
  const partial: DeskScanner["partial"] = [];
  if (!r.watch) partial.push("watchlist");
  if (!r.picks) partial.push("picks");
  const versions = new Set<string>();
  for (const body of [r.watch, r.picks]) for (const v of arr(rec(body).engine_versions)) if (typeof v === "string" && v) versions.add(v);
  const rules = parseRules(rec(r.watch).rules);
  return {
    watchAsOf: watch.asOf, signalDate: picks.signalDate, setups: mergeSetups(watch.items, picks.items), partial,
    rules,
    classifierVersion: str(rec(r.watch)._classifier_version),
    rulesVersion: rules?.version ?? str(rec(r.picks).rules_version),
    engineVersions: [...versions].sort(),
  };
}

/**
 * The opportunity list. Either route may fail on its own; the other's rows are still shown and `partial` names the
 * one that did not answer. Both failing is an error. One read with the Trader screens (D9).
 */
export function useDeskScanner() {
  return useScannerRoutes(toDeskScanner);
}

// ── the rules the routes send (backend/services/positional_engine/setup_rules.py) ──

export type RiskClass = "low" | "medium" | "high";

export interface ScanRules {
  version: string;
  liquidity: { minCr: number; sessions: number | null; definition: string | null } | null;
  riskBands: { lowBelowPct: number; highAbovePct: number; basis: string | null } | null;
  /** Each watchlist bucket's thresholds, as sent (keys as in setup_rules.WATCHLIST). */
  buckets: Partial<Record<SetupBucket, Record<string, number | string[] | null>>>;
  candidates: { minClose: number | null; excludedStages: string[]; topByScore: number | null; minBars: number | null } | null;
  stopAtrMultiple: number | null;
  universe: { series: string[]; excludeEtf: boolean; minPriceBandPct: number | null; bandLimitTolerancePct: number | null; order: string[] } | null;
  categories: Partial<Record<UniverseCategory, Record<string, number | string | boolean | null>>>;
  maxRowsPerCategory: number | null;
}

const strs = (v: unknown): string[] => arr(v).filter((x): x is string => typeof x === "string");

function flat(v: unknown): Record<string, number | string | boolean | string[] | null> {
  const out: Record<string, number | string | boolean | string[] | null> = {};
  for (const [k, x] of Object.entries(rec(v))) {
    if (typeof x === "number" || typeof x === "string" || typeof x === "boolean") out[k] = x;
    else if (Array.isArray(x)) out[k] = strs(x);
    else out[k] = null;
  }
  return out;
}

/** The `rules` block of the scanner routes; null when absent (an older backend) or without a version. */
export function parseRules(v: unknown): ScanRules | null {
  const d = rec(v);
  const version = str(d.version);
  if (!version) return null;
  const liq = rec(d.liquidity);
  const minCr = num(liq.min_traded_value_cr);
  const rb = rec(d.risk_bands);
  const lo = num(rb.low_below_pct);
  const hi = num(rb.high_above_pct);
  const wl = rec(d.watchlist);
  const cand = rec(wl.candidates);
  const uni = rec(d.universe);
  const buckets: ScanRules["buckets"] = {};
  for (const b of SETUP_BUCKETS) if (b in wl) buckets[b] = flat(wl[b]) as Record<string, number | string[] | null>;
  const categories: ScanRules["categories"] = {};
  for (const c of UNIVERSE_CATEGORIES) if (c in rec(d.categories)) categories[c] = flat(rec(d.categories)[c]) as Record<string, number | string | boolean | null>;
  return {
    version,
    liquidity: minCr != null ? { minCr, sessions: num(liq.sessions), definition: str(liq.definition) } : null,
    riskBands: lo != null && hi != null ? { lowBelowPct: lo, highAbovePct: hi, basis: str(rb.basis) } : null,
    buckets,
    candidates: "candidates" in wl
      ? { minClose: num(cand.min_close), excludedStages: strs(cand.excluded_stages), topByScore: num(cand.top_by_score), minBars: num(cand.min_bars) }
      : null,
    stopAtrMultiple: num(wl.stop_atr_multiple),
    universe: "series" in uni
      ? { series: strs(uni.series), excludeEtf: uni.exclude_etf === true, minPriceBandPct: num(uni.min_price_band_pct),
          bandLimitTolerancePct: num(uni.band_limit_tolerance_pct), order: strs(uni.exclusion_order) }
      : null,
    categories,
    maxRowsPerCategory: num(d.max_rows_per_category),
  };
}

/** Low / medium / high from ATR% with the route's bands; null without a figure or without the bands. */
export function riskClassOf(atrPct: number | null, rules: ScanRules | null): RiskClass | null {
  const b = rules?.riskBands;
  if (atrPct == null || atrPct < 0 || !b) return null;
  if (atrPct < b.lowBelowPct) return "low";
  if (atrPct > b.highAbovePct) return "high";
  return "medium";
}

// ── the eligible universe: GET /api/positional/scan-universe ─────────────

/** The universe categories the route computes (setup_rules.CATEGORIES). */
export const UNIVERSE_CATEGORIES = ["momentum", "unusual_volume", "results_day", "fno"] as const;
export type UniverseCategory = (typeof UNIVERSE_CATEGORIES)[number];

export interface UniverseRow {
  symbol: string;
  sector: string | null;
  /** NSE index-constituent industry, where the stock is in an index list. */
  industry: string | null;
  close: number | null;
  prevClose: number | null;
  open: number | null;
  high: number | null;
  return5d: number | null;
  return20d: number | null;
  sma50: number | null;
  sma50Slope: number | null;
  volZ20: number | null;
  /** The day's volume ÷ its 20-session average. */
  rvol20: number | null;
  atrPct: number | null;
  volatility1y: number | null;
  marketCapBucket: string | null;
  tradedCr: number | null;
  series: string | null;
  priceBandPct: number | null;
  /** The band as NSE writes it ("20", "No Band"). */
  bandRaw: string | null;
  fnoEligible: boolean | null;
  isEtf: boolean | null;
  hasReference: boolean;
  lastResults: string | null;
  nextResults: string | null;
  eligible: boolean;
  /** The first eligibility gate the stock fails (setup_rules.UNIVERSE exclusion_order). */
  exclusion: string | null;
  riskClass: RiskClass | null;
  liquidityClass: "liquid" | "thin" | null;
  categories: UniverseCategory[];
  /** The move-odds estimate as a percentile among the eligible stocks the model scored; null when not ranked. */
  modelRank: Record<"p_up5_1d" | "p_up10_1d", number | null>;
}

export interface CategoryCount {
  total: number;
  shown: number;
  symbols: string[];
  rankBy: string | null;
  /** Eligible stocks without a figure the rule needs (not in the category, never counted as passing). */
  missing: number | null;
}

export type ModelStatus = "final" | "not_published" | "withheld" | "no_access" | "unavailable";

export interface ScanUniverse {
  asOf: string;
  referenceAsOf: string | null;
  source: string | null;
  sessions: number | null;
  rules: ScanRules | null;
  resultsWindow: { from: string; to: string } | null;
  universe: { total: number; eligible: number; fnoEligible: number | null; excluded: Record<string, number> };
  categories: Partial<Record<UniverseCategory, CategoryCount>>;
  model: { status: ModelStatus; reason: string | null; run: Record<string, string | number | null> | null; rankedEligible: number | null };
  rows: Map<string, UniverseRow>;
  notFound: string[];
}

const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
const MODEL_STATUS: readonly ModelStatus[] = ["final", "not_published", "withheld", "no_access", "unavailable"];

function readUniverseRow(v: unknown): UniverseRow | null {
  const r = rec(v);
  const symbol = str(r.symbol);
  if (!symbol) return null;
  const rank = rec(r.model_rank_pct);
  const rc = str(r.risk_class);
  const lc = str(r.liquidity_class);
  return {
    symbol: symbol.toUpperCase(), sector: str(r.sector), industry: str(r.industry),
    close: price(r.close_price) ?? price(r.close), prevClose: price(r.prev_close), open: price(r.open_price), high: price(r.high_price),
    return5d: num(r.return_5d_pct), return20d: num(r.return_20d_pct), sma50: price(r.sma50), sma50Slope: num(r.sma50_slope),
    volZ20: num(r.vol_z20), rvol20: nonNeg(r.rvol20), atrPct: nonNeg(r.atr_pct), volatility1y: nonNeg(r.volatility_1y_pct),
    marketCapBucket: str(r.market_cap_bucket), tradedCr: nonNeg(r.traded_value_cr_20d), series: str(r.series),
    priceBandPct: nonNeg(r.price_band_pct), bandRaw: str(r.band_raw), fnoEligible: bool(r.fno_eligible), isEtf: bool(r.is_etf),
    hasReference: r.has_reference === true, lastResults: str(r.last_results_date), nextResults: str(r.next_results_date),
    eligible: r.eligible === true, exclusion: str(r.exclusion),
    riskClass: rc === "low" || rc === "medium" || rc === "high" ? rc : null,
    liquidityClass: lc === "liquid" || lc === "thin" ? lc : null,
    categories: strs(r.categories).filter((c): c is UniverseCategory => (UNIVERSE_CATEGORIES as readonly string[]).includes(c)),
    modelRank: { p_up5_1d: num(rank.p_up5_1d), p_up10_1d: num(rank.p_up10_1d) },
  };
}

export function parseUniverse(body: unknown): ScanUniverse {
  const d = rec(body);
  const asOf = str(d.as_of);
  if (!asOf || !Array.isArray(d.rows) || !d.universe || typeof d.universe !== "object") throw drift("positional.scan-universe: no rows");
  const u = rec(d.universe);
  const excluded: Record<string, number> = {};
  for (const [k, v] of Object.entries(rec(u.excluded))) {
    const n = num(v);
    if (n != null) excluded[k] = n;
  }
  const categories: ScanUniverse["categories"] = {};
  for (const c of UNIVERSE_CATEGORIES) {
    const x = rec(rec(d.categories)[c]);
    const total = num(x.total);
    if (total == null) continue;
    categories[c] = { total, shown: num(x.shown) ?? 0, symbols: strs(x.symbols).map((s) => s.toUpperCase()), rankBy: str(x.rank_by), missing: num(x.missing) };
  }
  const m = rec(d.model);
  const status = (MODEL_STATUS as readonly string[]).includes(String(m.status)) ? (m.status as ModelStatus) : "unavailable";
  const head = rec(rec(m.heads).p_up5_1d);
  const run: Record<string, string | number | null> = {};
  for (const [k, v] of Object.entries(rec(head.run))) run[k] = typeof v === "string" || typeof v === "number" ? v : null;
  const rows = new Map<string, UniverseRow>();
  for (const v of d.rows) {
    const row = readUniverseRow(v);
    if (row && !rows.has(row.symbol)) rows.set(row.symbol, row);
  }
  const win = rec(d.results_window);
  return {
    asOf, referenceAsOf: str(d.reference_as_of), source: str(d.source), sessions: num(d.sessions), rules: parseRules(d.rules),
    resultsWindow: str(win.from) && str(win.to) ? { from: str(win.from) as string, to: str(win.to) as string } : null,
    universe: { total: num(u.total) ?? 0, eligible: num(u.eligible) ?? 0, fnoEligible: num(u.fno_eligible), excluded },
    categories,
    model: { status, reason: str(m.reason), run: Object.keys(run).length ? run : null, rankedEligible: num(head.ranked_eligible) },
    rows,
    notFound: strs(d.not_found),
  };
}

/**
 * The universe categories and the eligible universe. `setups` are the scanner's own setups (they count toward F&O
 * candidates and get their universe figures and model rank); `symbols` are other stocks to look up (a watchlist).
 * Waits until `enabled` (the setups are known), so it is asked once per list.
 */
export function useScanUniverse(setups: string[], symbols: string[], enabled = true) {
  const s = [...new Set(setups.map((x) => x.toUpperCase()))].sort();
  const o = [...new Set(symbols.map((x) => x.toUpperCase()))].filter((x) => !s.includes(x)).sort();
  return useQuery<ScanUniverse>({
    queryKey: ["copilot", "desk", "scan-universe", s.join(","), o.join(",")],
    enabled,
    staleTime: 5 * 60_000,
    // A new list of stocks to look up keeps the last answer on screen until the new one arrives.
    placeholderData: keepPreviousData,
    retry,
    queryFn: async ({ signal }) => {
      const query: Record<string, string> = {};
      if (s.length) query.setups = s.join(",");
      if (o.length) query.symbols = o.join(",");
      const res = await http({ path: "/api/positional/scan-universe", query, timeoutMs: 30_000, signal });
      return parseUniverse(res.data);
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

/**
 * PRD §5.8: "A probability is displayed only when supported by an appropriate calibration process." The desk shows a
 * model probability only when its route marks the estimate calibrated. GET /api/move-odds/latest publishes the
 * model's out-of-sample record (record.bands: how each probability band turned out in its 2025 test window) but no
 * flag saying the estimates are calibrated, so every figure is withheld here and the model rank — a percentile, not
 * a probability — is shown instead. Whether that band record counts as calibration is the owner's decision (gap
 * matrix U4). Until a route sends such a flag the answer is always "not shown", and the type says so.
 */
export function probabilityGate(odds: DeskOdds | undefined, plain = false, stockEstimate = false): { shown: false; reason: string } {
  if (!odds) return { shown: false, reason: plain ? "Loading the model." : "Loading the move-odds model." };
  // `stockEstimate`: the per-stock route (GET /api/move-odds/stocks/{symbol}) answered with an estimate when the run
  // list did not carry the stock. It has no calibration flag either, so it is withheld for the same reason.
  if (odds.kind === "final" || (stockEstimate && odds.kind === "not_published")) {
    return {
      shown: false,
      reason: plain
        ? "Not shown: the model's chances are not marked as checked against real outcomes (calibrated), so they are held back."
        : "Withheld: GET /api/move-odds/latest does not mark these estimates as calibrated (it sends a 2025 band record, not a calibration flag), so no probability is shown (PRD §5.8).",
    };
  }
  if (odds.kind === "not_published") return { shown: false, reason: `Not published for ${odds.expectedSession} yet.` };
  if (odds.kind === "withheld") return { shown: false, reason: `The model's run was withheld: ${odds.reason}.` };
  return { shown: false, reason: "Move probabilities are not enabled for this account." };
}

/** The one word every place prints where a probability would go. */
export const PROBABILITY_WITHHELD = "Withheld";

/**
 * The model's evidence, shown in place of a probability: its version, the run date and the out-of-sample record.
 * It describes the model, not this stock, and it is not a probability. Null when the run is not available.
 */
export function modelEvidence(run: MoveFinal["run"] | null | undefined, record: MoveFinal["record"] | null | undefined, plain = false): string | null {
  if (!run) return null;
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
  const out = [`${plain ? "Model" : "Move-odds"} ${run.model}`, `data as of ${fmtDay(run.data_as_of)}`, `for ${fmtDay(run.target_session)}`];
  if (record) out.push(`out of sample ${record.window_label}: top-10 hit rate ${pct(record.top10_hit_rate)} vs a base rate of ${pct(record.base_rate)} over ${record.sessions} sessions`);
  return out.join(" · ");
}
