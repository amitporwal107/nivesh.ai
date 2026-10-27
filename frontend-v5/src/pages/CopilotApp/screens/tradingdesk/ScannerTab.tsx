/**
 * Smart trading desk — 02 AI Opportunity scanner (PRD §5.1–§5.6, §5.8; design-spec §4, phone §11 M2).
 *
 *   GET /api/positional/watchlist?limit=30   setup buckets, close, trigger, stop, the rules and their version  (useDeskScanner)
 *   GET /api/positional/picks?limit=30       scored picks with entry, stop, target, engine versions             (useDeskScanner)
 *   GET /api/positional/scan-universe        momentum, unusual volume, results-day momentum and F&O candidates over the
 *       ?setups=&symbols=                    eligible universe; every exclusion counted; each row's end-of-day price, change,
 *                                            RVOL, volatility, ATR%, traded value, price band, F&O flag, results dates and
 *                                            the move-odds model's rank percentile within the eligible universe  (useScanUniverse)
 *   GET /api/fno/scan/buildup                futures OI build-up per F&O stock; every F&O-eligible row carries its line (FnoLine)  (useBuildup)
 *   GET /api/move-odds/latest?head=…         the model's run, its out-of-sample record, events per stock          (useDeskOdds)
 *   GET /api/watchlists, /api/watchlists/{id}  the user's own lists, for the "User watchlist" category  (usePersonalLists)
 *   POST /api/watchlists/{id}/symbols        Add to a list (AddToList, workspace/PersonalLists.tsx)
 *   POST /api/desk/paper-trades              Paper trade at the setup's levels (useAddPaperTrade, desk-trading.ts)
 *
 * Everything is end of day. The score is the scanner's rules-based score (final_score × 100), not a probability. The
 * model rank is a percentile, not a probability. A probability is shown only when its route marks it calibrated
 * (probabilityGate, desk-data.ts); the move-odds route does not, so the probability column says "Withheld" and why.
 * Every threshold shown comes from the route's `rules` block (backend setup_rules.py, versioned); none is kept here.
 * The category, the ranking and every filter live in the URL (sc_*), so a reload, a shared link or a trip to another
 * tab keeps them (PRD §5.8). Missing figures show "—" and a filter never treats them as passing.
 *
 * Above the list (the user's requirement of 2026-10-25): the market pulse (ScannerPulse.tsx — the latest events and FII / DII,
 * smart-money and sector indicators, opening Market Intelligence and Smart Money) and the Top 10 stock and F&O ideas
 * (ScannerTop10.tsx). Each loads on its own, from its own code chunk (the boards carry the Strategy Builder's payoff charts);
 * the list never waits for them.
 */
import { Flash } from "../../components/LiveBits";
import { closeLabel, useLiveOverlay, flashOf } from "../../lib/useLiveQuotes";
import { Suspense, lazy, useEffect, useId, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Btn, ErrorBlock, LoadingBlock, Pill, TONE_COLOR, fmtNum, fmtPct, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { Sparkline } from "../markets/parts";
import { SymbolCell } from "../desk/parts";
import { fmtDay, fmtPrice, fmtSigned } from "../trading/parts";
import { AddToList } from "../workspace/PersonalLists";
import { usePersonalList, usePersonalLists } from "../workspace/personal-lists";
import { STATUS_LABEL, lastMove, oddsLabel, scanDateLabel, setupLabel, type UpHead } from "./chart-data";
import { useDesk } from "./context";
import {
  probabilityGate, riskClassOf, scanBasisLine, useDeskOdds, useDeskScanner, useScanUniverse,
  type DeskOdds, type DeskSetup, type RiskClass, type ScanRules, type ScanUniverse, type SetupBucket, type UniverseCategory, type UniverseRow,
} from "./desk-data";
import { ENTRY_RULE_SHORT, entryRuleFor, useAddPaperTrade, writeProblem, type NewPaperTrade } from "./desk-trading";
import { BUILDUP_META, RISK_FLAG_LABEL, buildupRowFor, useBuildup, type Buildup } from "./fno-buildup";
import ReversalPanel from "./ReversalPanel";
import { RiskReduceOffer } from "./RiskReduce";
import { TrustLine } from "./trust";
import { Widget } from "./widget";
import { ChartinkTag, ChartinkTrust } from "./chartink/ChartinkParts";
import { hitsBySymbol, useChartink, type ChartinkState } from "./chartink/chartink-data";
import type { ChartinkHitSymbol } from "./chartink/chartink-contract";

// ── categories (PRD §5.2) ────────────────────────────────────────────────

type CatKey = "all" | "breakouts" | "near_breakout" | "momentum" | "pullbacks" | "accumulation" | "reversal"
  | "unusual_volume" | "results_day" | "fno" | "chartink" | "watchlist";

interface Cat { key: CatKey; label: string; plain: string; bucket?: SetupBucket; ucat?: UniverseCategory }

/** PRD §5.2's nine, in its order, with the scanner's two other buckets beside the one they belong to. */
const CATS: readonly Cat[] = [
  { key: "all", label: "All", plain: "All" },
  { key: "breakouts", label: "Breakouts", plain: "Broke out", bucket: "breakout_confirmed" },
  { key: "near_breakout", label: "Near breakout", plain: "About to break out", bucket: "pre_breakout" },
  { key: "momentum", label: "Momentum", plain: "Rising steadily", ucat: "momentum" },
  { key: "pullbacks", label: "Pullback continuation", plain: "Dip in an uptrend", bucket: "trend_continuation" },
  { key: "accumulation", label: "Accumulation", plain: "Quiet sideways range", bucket: "true_accumulation" },
  { key: "reversal", label: "Reversal candidates", plain: "Turning around" },
  { key: "unusual_volume", label: "Unusual volume", plain: "Heavy trading", ucat: "unusual_volume" },
  { key: "results_day", label: "Results-day momentum", plain: "Moving after results", ucat: "results_day" },
  { key: "fno", label: "F&O candidates", plain: "Has futures & options", ucat: "fno" },
  { key: "chartink", label: "Chartink scans", plain: "Your Chartink scans" },
  { key: "watchlist", label: "User watchlist", plain: "Your list" },
];
const CAT_KEYS = CATS.map((c) => c.key) as readonly string[];
const catOf = (k: CatKey) => CATS.find((c) => c.key === k) as Cat;
const UCAT_LABEL: Record<UniverseCategory, [string, string]> = {
  momentum: ["Momentum", "Rising steadily"],
  unusual_volume: ["Unusual volume", "Heavy trading"],
  results_day: ["Results-day momentum", "Moving after results"],
  fno: ["F&O candidate", "Has futures & options"],
};

// ── URL state (PRD §5.8: criteria are not lost unexpectedly) ─────────────

const Q = {
  cat: "sc_cat", rank: "sc_rank", liquid: "sc_liq", sector: "sc_sector", cap: "sc_cap", pmin: "sc_pmin", pmax: "sc_pmax",
  rvol: "sc_rvol", vol: "sc_vol", risk: "sc_risk", inst: "sc_inst", ck: "sc_ck", list: "sc_list",
} as const;
type QKey = keyof typeof Q;
const FILTER_KEYS: readonly QKey[] = ["liquid", "sector", "cap", "pmin", "pmax", "rvol", "vol", "risk", "inst", "ck"];

type RankBy = "score" | "m5" | "m10";
type Inst = "fno" | "cash" | "eligible";
type OnChartink = "yes" | "no";

interface Filters {
  liquid: boolean;
  sector: string | null;
  cap: string | null;
  pmin: number | null;
  pmax: number | null;
  rvol: number | null;
  vol: number | null;
  risk: RiskClass | null;
  inst: Inst | null;
  /** "On Chartink": only stocks that are (yes) or are not (no) in the user's Chartink hits. */
  ck: OnChartink | null;
}

const posNum = (v: string | null): number | null => {
  if (v == null || v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : null;
};

function useScanState() {
  const [params, setParams] = useSearchParams();
  const raw = (k: QKey) => params.get(Q[k]);
  const cat = raw("cat");
  const rank = raw("rank");
  const risk = raw("risk");
  const inst = raw("inst");
  const ckRaw = raw("ck");
  const filters: Filters = {
    liquid: raw("liquid") === "1",
    sector: raw("sector"),
    cap: raw("cap"),
    pmin: posNum(raw("pmin")),
    pmax: posNum(raw("pmax")),
    rvol: posNum(raw("rvol")),
    vol: posNum(raw("vol")),
    risk: risk === "low" || risk === "medium" || risk === "high" ? risk : null,
    inst: inst === "fno" || inst === "cash" || inst === "eligible" ? inst : null,
    ck: ckRaw === "yes" || ckRaw === "no" ? ckRaw : null,
  };
  const set = (patch: Partial<Record<QKey, string | null>>) =>
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(patch) as Array<[QKey, string | null]>) {
        if (v == null || v === "") p.delete(Q[k]);
        else p.set(Q[k], v);
      }
      return p;
    }, { replace: true });
  return {
    cat: (cat && CAT_KEYS.includes(cat) ? cat : "all") as CatKey,
    rank: (rank === "m5" || rank === "m10" ? rank : "score") as RankBy,
    list: raw("list"),
    filters,
    set,
  };
}

// ── rows ─────────────────────────────────────────────────────────────────

interface Row {
  symbol: string;
  /** The scanner's own setup (watchlist / picks), when it has the stock. */
  s: DeskSetup | null;
  /** The stock's universe row (end-of-day figures, eligibility, model rank), when the universe route sent one. */
  u: UniverseRow | null;
  name: string | null;
  price: number | null;
  change: number | null;
  changePct: number | null;
  rank5: number | null;
  rank10: number | null;
  /** Events on record for the stock in the model's run. */
  events: number | null;
  toTarget: number | null;
  tradedCr: number | null;
  atrPct: number | null;
  risk: RiskClass | null;
  sector: string | null;
  /** The stock's row in the user's Chartink hits, when Chartink is connected and the stock is in them. */
  ck: ChartinkHitSymbol | null;
  /** True once Chartink's hits are loaded: a stock without `ck` is then known not to be on Chartink (else it is unknown). */
  ckKnown: boolean;
}

/** Descending, with missing values last. */
function desc(a: number | null, b: number | null): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return b - a;
}

const UNIVERSE_FIELD: Record<string, (u: UniverseRow) => number | null> = {
  return_20d_pct: (u) => u.return20d,
  vol_z20: (u) => u.volZ20,
  return_5d_pct: (u) => u.return5d,
  traded_value_cr_20d: (u) => u.tradedCr,
};

function buildRow(symbol: string, s: DeskSetup | null, u: UniverseRow | null, odds: Map<string, { events: number }> | null, rules: ScanRules | null, name: string | null): Row {
  const move = s ? lastMove(s.spark) : null;
  let price: number | null = null;
  let change: number | null = null;
  let changePct: number | null = null;
  if (move) {
    price = move.close;
    change = move.change;
    changePct = move.changePct;
  } else if (u?.close != null && u.prevClose != null) {
    price = u.close;
    change = u.close - u.prevClose;
    changePct = (change / u.prevClose) * 100;
  } else price = s?.close ?? s?.entry ?? u?.close ?? null;
  const base = s?.close ?? s?.entry ?? null;
  const toTarget = s?.target != null && base != null && base > 0 ? ((s.target - base) / base) * 100 : null;
  const atrPct = s?.atrPct ?? u?.atrPct ?? null;
  return {
    symbol, s, u, name, price, change, changePct,
    rank5: u?.modelRank.p_up5_1d ?? null, rank10: u?.modelRank.p_up10_1d ?? null,
    events: odds?.get(symbol)?.events ?? null, toTarget,
    tradedCr: s?.avgTradedCr ?? u?.tradedCr ?? null,
    atrPct, risk: riskClassOf(atrPct, rules), sector: s?.sector ?? u?.sector ?? u?.industry ?? null, ck: null, ckKnown: false,
  };
}

function inCat(r: Row, c: Cat, uni: ScanUniverse | undefined): boolean {
  if (c.bucket) return r.s?.bucket === c.bucket;
  if (c.ucat) return !!r.u?.categories.includes(c.ucat) || !!uni?.categories[c.ucat]?.symbols.includes(r.symbol);
  return false;
}

// ── filters (PRD §5.2, §16.2) ────────────────────────────────────────────

interface FilterDef {
  key: QKey;
  active: (f: Filters) => boolean;
  /** true / false, or null when the row has no figure (hidden while the filter is on, and counted). */
  test: (r: Row, f: Filters, liqMin: number | null) => boolean | null;
  lacks: string;
}

const FILTERS: readonly FilterDef[] = [
  { key: "liquid", active: (f) => f.liquid, test: (r, _f, min) => (r.tradedCr == null || min == null ? null : r.tradedCr >= min), lacks: "no 20-session traded value" },
  { key: "sector", active: (f) => f.sector != null, test: (r, f) => (r.sector == null ? null : r.sector === f.sector), lacks: "no sector" },
  { key: "cap", active: (f) => f.cap != null, test: (r, f) => (r.u?.marketCapBucket == null ? null : r.u.marketCapBucket === f.cap), lacks: "no market-cap bucket" },
  { key: "pmin", active: (f) => f.pmin != null, test: (r, f) => (r.price == null ? null : r.price >= (f.pmin as number)), lacks: "no price" },
  { key: "pmax", active: (f) => f.pmax != null, test: (r, f) => (r.price == null ? null : r.price <= (f.pmax as number)), lacks: "no price" },
  { key: "rvol", active: (f) => f.rvol != null, test: (r, f) => (r.u?.rvol20 == null ? null : r.u.rvol20 >= (f.rvol as number)), lacks: "no relative volume" },
  { key: "vol", active: (f) => f.vol != null, test: (r, f) => (r.u?.volatility1y == null ? null : r.u.volatility1y <= (f.vol as number)), lacks: "no 1-year volatility" },
  { key: "risk", active: (f) => f.risk != null, test: (r, f) => (r.risk == null ? null : r.risk === f.risk), lacks: "no ATR figure" },
  {
    key: "inst", active: (f) => f.inst != null, lacks: "no NSE reference row",
    test: (r, f) => {
      if (!r.u || !r.u.hasReference) return null;
      if (f.inst === "fno") return r.u.fnoEligible === true;
      if (f.inst === "cash") return r.u.fnoEligible === false;
      return r.u.eligible;
    },
  },
  // Not knowing whether the hits loaded hides the row and counts it, as the other filters do for a missing figure.
  { key: "ck", active: (f) => f.ck != null, lacks: "no Chartink data (not connected or not loaded)", test: (r, f) => (!r.ckKnown ? null : f.ck === "yes" ? r.ck != null : r.ck == null) },
];

const RVOL_OPTIONS = [1.5, 2, 3];
const VOL_OPTIONS = [25, 35, 50];
const CAP_OPTIONS: Array<[string, string]> = [["LARGE_CAP", "Large cap"], ["MID_CAP", "Mid cap"], ["SMALL_CAP", "Small cap"], ["MICRO_CAP", "Micro cap"]];
const RISK_LABEL: Record<RiskClass, string> = { low: "Low", medium: "Medium", high: "High" };
const INST_LABEL: Record<Inst, string> = { fno: "F&O eligible", cash: "Cash only (no F&O)", eligible: "In the eligible universe" };

// ── wording ──────────────────────────────────────────────────────────────

const EXCLUSION_TEXT: Record<string, string> = {
  missing_price: "no close for the scan date",
  no_traded_value: "fewer than 20 sessions of traded value",
  no_reference: "no NSE reference row",
  series: "not in the EQ or BE series",
  etf: "an ETF",
  price_band: "a tight price band",
  at_band_limit: "closed at its price-band limit",
  illiquid: "below the liquidity gate",
};

const pctOrd = (p: number | null) => {
  if (p == null) return "—";
  const n = Math.round(p);
  const t = n % 100;
  const suf = t >= 11 && t <= 13 ? "th" : n % 10 === 1 ? "st" : n % 10 === 2 ? "nd" : n % 10 === 3 ? "rd" : "th";
  return `${n}${suf}`;
};

const tradedText = (cr: number | null) => (cr == null ? "No traded value" : `₹${fmtNum(cr, cr >= 100 ? 0 : 1)} Cr a day`);

/** A threshold from the route's rules as plain text ("1.5", "−2"); "—" when the route did not send it. */
const th = (t: Record<string, unknown> | undefined, k: string, digits = 2) => {
  const v = t?.[k];
  return typeof v === "number" ? fmtNum(v, digits).replace(/\.?0+$/, "") : "—";
};

function bucketRule(b: SetupBucket, rules: ScanRules | null): string {
  const t = rules?.buckets[b];
  if (!t) return "The route did not send this bucket's thresholds.";
  if (b === "breakout_confirmed") return `Closed ${th(t, "dist_breakout_pct_min")}–${th(t, "dist_breakout_pct_max")}% above the breakout level on at least ${th(t, "volume_spike_min")}× the 20-day average volume (last 3 sessions), and not on a gap of more than ${th(t, "max_gap_up_pct")}% above the previous close.`;
  if (b === "pre_breakout") return `Within ${th(t, "dist_breakout_pct_min").replace(/^[−-]/, "")}% below resistance with volume at least ${th(t, "volume_spike_min")}× the 20-day average.`;
  if (b === "trend_continuation") return `Close above the 20-day EMA, which is above the 50-day average, and ${th(t, "dist_ema20_min_pct")}–${th(t, "dist_ema20_max_pct")}% above the 20-day EMA.`;
  return `15-day range under ${th(t, "range_15d_below_pct")}%, volume contracting, at least ${th(t, "higher_lows_min")} higher low and small upper wicks.`;
}

function universeRule(c: UniverseCategory, rules: ScanRules | null): string {
  const t = rules?.categories[c];
  if (!t) return "The route did not send this rule's thresholds.";
  if (c === "momentum") {
    const rsi = typeof t.rsi14_min === "number" && typeof t.rsi14_max === "number" ? ` RSI(14) between ${th(t, "rsi14_min")} and ${th(t, "rsi14_max")},` : "";
    return `20-day return of at least ${th(t, "return_20d_min_pct")}%,${rsi} close above the 50-day average, and the 50-day average rising (slope above ${th(t, "sma50_slope_above")}% a day). Ranked by 20-day return.`;
  }
  if (c === "unusual_volume") return `The day's volume at least ${th(t, "vol_z20_min")} standard deviations above its 20-day average (volume z-score). Ranked by the z-score.`;
  if (c === "results_day") return `Quarterly results (NSE event calendar) dated in the ${th(t, "window_calendar_days")} calendar days up to the scan date, a 5-day return of at least ${th(t, "return_5d_min_pct")}%, and volume at least ${th(t, "vol_z20_min")} standard deviation above normal. Ranked by 5-day return.`;
  return "F&O-eligible (NSE lot-size file) and in another category or a scanner setup. Ranked by traded value.";
}

// ── controls ─────────────────────────────────────────────────────────────

const eyebrow95: CSSProperties = { fontSize: 9.5 };
const noteStyle: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const selectStyle: CSSProperties = {
  height: 30, minWidth: 0, maxWidth: "100%", padding: "0 8px", borderRadius: 8, border: "1px solid var(--line-2)",
  background: "var(--bg-2)", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 12,
};
const linkBtn: CSSProperties = { padding: 0, border: 0, background: "none", font: "inherit", color: "var(--cp-ink)", cursor: "pointer", textDecoration: "underline" };

function RankBySwitch({ value, onChange, ready, plain, small }: { value: RankBy; onChange: (v: RankBy) => void; ready: boolean; plain: boolean; small?: boolean }) {
  const why = ready ? undefined : "Needs the model's rank: the model is not published, not enabled for this account, or the universe did not load";
  const options: Array<{ key: RankBy; label: string; disabled?: boolean; title?: string }> = [
    { key: "score", label: "Score", title: "The scanner’s rules-based score, 0–100" },
    { key: "m5", label: plain ? "Model rank +5% day" : "Model rank +5%", disabled: !ready, title: why ?? "Percentile of the model's +5% next-session estimate among eligible stocks" },
    { key: "m10", label: plain ? "Model rank +10% day" : "Model rank +10%", disabled: !ready, title: why ?? "Percentile of the model's +10% next-session estimate among eligible stocks" },
  ];
  return (
    <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
      <span className="cp-eyebrow" style={eyebrow95}>Rank by</span>
      <div role="group" aria-label="Rank by" className="inline-flex max-w-full flex-wrap"
        style={{ gap: 2, padding: small ? 2 : 3, borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}>
        {options.map((o) => {
          const on = o.key === value;
          return (
            <button key={o.key} type="button" aria-pressed={on} disabled={o.disabled} title={o.title} data-testid={`desk-scan-rank-${o.key}`} onClick={() => onChange(o.key)}
              style={{
                padding: small ? "5px 9px" : "6px 12px", borderRadius: 999, border: 0, whiteSpace: "nowrap",
                fontFamily: "var(--mono)", fontSize: small ? 9.5 : 10.5, letterSpacing: "0.08em",
                cursor: o.disabled ? "not-allowed" : "pointer", opacity: o.disabled ? 0.45 : 1,
                background: on ? "var(--bg-4)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
              }}>
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Filter chip (design-spec §1): 5px 11px, 12px; ON mint-soft, mint text, mint-line border. A category with no rule is dashed. */
function Chip({ on, onClick, testId, children, title, unavailable }: { on: boolean; onClick: () => void; testId: string; children: ReactNode; title?: string; unavailable?: boolean }) {
  return (
    <button type="button" aria-pressed={on} data-testid={testId} data-unavailable={unavailable ? "true" : undefined} title={title} onClick={onClick}
      style={{
        flex: "none", padding: "5px 11px", borderRadius: 999, fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)", whiteSpace: "nowrap",
        border: `1px ${unavailable ? "dashed" : "solid"} ${on ? "var(--mint-line)" : "var(--line-2)"}`,
        color: on ? "var(--mint)" : unavailable ? "var(--cp-ink-3)" : "var(--cp-ink-2)",
        background: on ? "var(--mint-soft)" : "transparent",
      }}>
      {children}
    </button>
  );
}

function CategoryChips({ value, onChange, plain, scroll }: { value: CatKey; onChange: (c: CatKey) => void; plain: boolean; scroll: boolean }) {
  return (
    <div role="group" aria-label="Scanner category" data-testid="desk-scan-cats"
      className={scroll ? "cp-scroll flex overflow-x-auto" : "flex flex-wrap"} style={{ gap: 6, paddingBottom: scroll ? 2 : 0, minWidth: 0, maxWidth: "100%" }}>
      {CATS.map((c) => (
        <Chip key={c.key} on={c.key === value} onClick={() => onChange(c.key)} testId={`desk-scan-cat-${c.key}`}>
          {plain ? c.plain : c.label}
        </Chip>
      ))}
    </div>
  );
}

/** The design's toggle switch: track 30 × 18, knob 12 × 12 sliding from 2px to 14px, label beside it. */
function LiquidSwitch({ on, onChange, minCr, phone }: { on: boolean; onChange: (v: boolean) => void; minCr: number | null; phone?: boolean }) {
  const label = minCr == null ? "Liquid only · threshold not sent" : phone ? `Liquid · ₹${fmtNum(minCr)} Cr+` : `Liquid only · ADV ≥ ₹${fmtNum(minCr)} Cr`;
  return (
    <button type="button" aria-pressed={on} data-testid="desk-scan-liquid" disabled={minCr == null}
      title={minCr == null ? "The scanner routes did not send the liquidity threshold" : `Average daily traded value (close × volume) over the last 20 sessions of at least ₹${fmtNum(minCr)} Cr`}
      onClick={() => onChange(!on)} className="inline-flex items-center"
      style={{ gap: 8, padding: 0, border: 0, background: "none", cursor: minCr == null ? "not-allowed" : "pointer", fontFamily: "var(--sans)", fontSize: 12, color: "var(--cp-ink-2)", whiteSpace: "nowrap" }}>
      <span aria-hidden style={{ position: "relative", width: 30, height: 18, flex: "none", borderRadius: 999, border: "1px solid var(--line-2)", background: on ? "var(--mint-soft)" : "var(--bg-3)" }}>
        <span style={{ position: "absolute", top: 2, left: on ? 14 : 2, width: 12, height: 12, borderRadius: 999, background: on ? "var(--mint)" : "var(--cp-ink-3)", transition: "left .15s ease" }} />
      </span>
      <span data-testid="desk-scan-liquid-label">{label}</span>
    </button>
  );
}

function Field({ label, children, note, htmlFor }: { label: string; children: ReactNode; note?: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <label htmlFor={htmlFor} className="cp-eyebrow" style={{ fontSize: 9 }}>{label}</label>
      {children}
      {note && <span style={{ fontSize: 11, lineHeight: 1.4, color: "var(--cp-ink-3)" }}>{note}</span>}
    </div>
  );
}

interface FilterPanelProps {
  f: Filters;
  set: (patch: Partial<Record<QKey, string | null>>) => void;
  sectors: string[];
  capReady: boolean;
  rules: ScanRules | null;
  gateReason: string;
  phone: boolean;
  /** Whether Chartink's hits are loaded, for the "On Chartink" filter. */
  ckReady: boolean;
}

function FilterPanel({ f, set, sectors, capReady, rules, gateReason, phone, ckReady }: FilterPanelProps) {
  const id = useId();
  const [pmin, setPmin] = useState(f.pmin != null ? String(f.pmin) : "");
  const [pmax, setPmax] = useState(f.pmax != null ? String(f.pmax) : "");
  useEffect(() => setPmin(f.pmin != null ? String(f.pmin) : ""), [f.pmin]);
  useEffect(() => setPmax(f.pmax != null ? String(f.pmax) : ""), [f.pmax]);
  const bands = rules?.riskBands;
  const commit = (k: "pmin" | "pmax", v: string) => {
    const n = posNum(v);
    set({ [k]: n != null ? String(n) : null });
  };
  return (
    <div data-testid="desk-scan-filter-panel" className="grid" style={{ gap: 12, gridTemplateColumns: phone ? "minmax(0,1fr) minmax(0,1fr)" : "repeat(auto-fill, minmax(170px, 1fr))", padding: phone ? 12 : "12px 18px", borderBottom: "1px solid var(--cp-line)", background: "var(--bg-0)" }}>
      <Field label="Sector / industry" htmlFor={`${id}-sector`}>
        <select id={`${id}-sector`} data-testid="desk-scan-f-sector" value={f.sector ?? ""} onChange={(e) => set({ sector: e.target.value || null })} style={selectStyle}>
          <option value="">Any</option>
          {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </Field>
      <Field label="Market cap" htmlFor={`${id}-cap`} note={capReady ? undefined : <span data-testid="desk-scan-f-cap-why">Not available: no stock here carries a market-cap bucket (filled on none on the latest features date), and the Midcap 150 / Smallcap 250 lists are not loaded.</span>}>
        <select id={`${id}-cap`} data-testid="desk-scan-f-cap" disabled={!capReady} value={f.cap ?? ""} onChange={(e) => set({ cap: e.target.value || null })} style={selectStyle}>
          <option value="">Any</option>
          {CAP_OPTIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </Field>
      <Field label="Price ₹ (min – max)">
        <span className="flex min-w-0 items-center" style={{ gap: 6 }}>
          <input aria-label="Lowest price, ₹" data-testid="desk-scan-f-pmin" inputMode="decimal" value={pmin} placeholder="Min"
            onChange={(e) => setPmin(e.target.value)} onBlur={() => commit("pmin", pmin)} onKeyDown={(e) => { if (e.key === "Enter") commit("pmin", pmin); }}
            style={{ ...selectStyle, width: "100%" }} />
          <input aria-label="Highest price, ₹" data-testid="desk-scan-f-pmax" inputMode="decimal" value={pmax} placeholder="Max"
            onChange={(e) => setPmax(e.target.value)} onBlur={() => commit("pmax", pmax)} onKeyDown={(e) => { if (e.key === "Enter") commit("pmax", pmax); }}
            style={{ ...selectStyle, width: "100%" }} />
        </span>
      </Field>
      <Field label="Relative volume" htmlFor={`${id}-rvol`} note="The day's volume ÷ its 20-session average.">
        <select id={`${id}-rvol`} data-testid="desk-scan-f-rvol" value={f.rvol ?? ""} onChange={(e) => set({ rvol: e.target.value || null })} style={selectStyle}>
          <option value="">Any</option>
          {RVOL_OPTIONS.map((v) => <option key={v} value={v}>≥ {v}×</option>)}
        </select>
      </Field>
      <Field label="Volatility (1 year)" htmlFor={`${id}-vol`} note="Annualised volatility of daily returns.">
        <select id={`${id}-vol`} data-testid="desk-scan-f-vol" value={f.vol ?? ""} onChange={(e) => set({ vol: e.target.value || null })} style={selectStyle}>
          <option value="">Any</option>
          {VOL_OPTIONS.map((v) => <option key={v} value={v}>≤ {v}%</option>)}
        </select>
      </Field>
      <Field label="Risk category" htmlFor={`${id}-risk`} note={bands ? <span data-testid="desk-scan-f-risk-bands">ATR(14) % of price: low under {fmtNum(bands.lowBelowPct)}%, high over {fmtNum(bands.highAbovePct)}%.</span> : "The route did not send the risk bands."}>
        <select id={`${id}-risk`} data-testid="desk-scan-f-risk" disabled={!bands} value={f.risk ?? ""} onChange={(e) => set({ risk: e.target.value || null })} style={selectStyle}>
          <option value="">Any</option>
          {(["low", "medium", "high"] as RiskClass[]).map((k) => <option key={k} value={k}>{RISK_LABEL[k]}</option>)}
        </select>
      </Field>
      <Field label="Instrument" htmlFor={`${id}-inst`}>
        <select id={`${id}-inst`} data-testid="desk-scan-f-inst" value={f.inst ?? ""} onChange={(e) => set({ inst: e.target.value || null })} style={selectStyle}>
          <option value="">Any</option>
          {(Object.keys(INST_LABEL) as Inst[]).map((k) => <option key={k} value={k}>{INST_LABEL[k]}</option>)}
        </select>
      </Field>
      <Field label="On Chartink" htmlFor={`${id}-ck`} note={ckReady ? undefined : <span data-testid="desk-scan-f-ck-why">Not available: connect your Chartink dashboard (More · Chartink scans) and its hits must load.</span>}>
        <select id={`${id}-ck`} data-testid="desk-scan-f-ck" disabled={!ckReady} value={f.ck ?? ""} onChange={(e) => set({ ck: e.target.value || null })} style={selectStyle}>
          <option value="">Any</option>
          <option value="yes">On Chartink</option>
          <option value="no">Not on Chartink</option>
        </select>
      </Field>
      <Field label="Prediction horizon" htmlFor={`${id}-hz`} note={<span data-testid="desk-scan-f-horizon-why">The model has next-session estimates only; longer horizons need model work.</span>}>
        <select id={`${id}-hz`} data-testid="desk-scan-f-horizon" disabled value="1d" onChange={() => undefined} style={selectStyle}>
          <option value="1d">Next session</option>
        </select>
      </Field>
      <Field label="Model probability" htmlFor={`${id}-p`} note={<span data-testid="desk-scan-f-prob-why">{gateReason}</span>}>
        <select id={`${id}-p`} data-testid="desk-scan-f-prob" disabled value="" onChange={() => undefined} style={selectStyle}>
          <option value="">Any</option>
        </select>
      </Field>
    </div>
  );
}

function filterChipText(k: QKey, f: Filters, minCr: number | null): string {
  if (k === "liquid") return `Liquid ≥ ₹${fmtNum(minCr)} Cr`;
  if (k === "sector") return `Sector: ${f.sector}`;
  if (k === "cap") return `Cap: ${CAP_OPTIONS.find(([v]) => v === f.cap)?.[1] ?? f.cap}`;
  if (k === "pmin") return `Price ≥ ${fmtPrice(f.pmin)}`;
  if (k === "pmax") return `Price ≤ ${fmtPrice(f.pmax)}`;
  if (k === "rvol") return `RVOL ≥ ${f.rvol}×`;
  if (k === "vol") return `Volatility ≤ ${f.vol}%`;
  if (k === "risk") return `Risk: ${f.risk ? RISK_LABEL[f.risk] : ""}`;
  if (k === "ck") return f.ck === "yes" ? "On Chartink" : "Not on Chartink";
  return `Instrument: ${f.inst ? INST_LABEL[f.inst] : ""}`;
}

// ── cells ────────────────────────────────────────────────────────────────

function ScoreText({ score, size = 23 }: { score: number | null; size?: number }) {
  if (score == null) return <span data-testid="desk-scan-score" title="Only the scanner's own setups have a score" style={{ color: "var(--cp-ink-3)" }}>—</span>;
  return (
    <span data-testid="desk-scan-score" style={{ fontFamily: "var(--display)", fontSize: size, lineHeight: 1, color: score >= 80 ? "var(--mint)" : "var(--cp-indigo)" }}>
      {fmtNum(score, 0)}
    </span>
  );
}

/** The probability slot: "Withheld" (and why) unless the route marks the estimate calibrated. */
function ProbCell({ gate, head, small }: { gate: { shown: false; reason: string }; head: UpHead; small?: boolean }) {
  return (
    <span data-testid="desk-scan-odds" data-head={head} data-state="withheld" title={gate.reason}
      style={{ fontFamily: "var(--mono)", fontSize: small ? 9.5 : 11, letterSpacing: "0.04em", color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>
      Withheld<span className="sr-only">: {gate.reason}</span>
    </span>
  );
}

function rankReason(r: Row, head: UpHead, uni: ScanUniverse | undefined, uniError: boolean): string {
  if (uniError) return "The universe route did not load, so there is no model rank.";
  if (!uni) return "Loading the universe.";
  if (uni.model.status !== "final") return uni.model.reason ?? "The model's run is not available.";
  if (!r.u) return "Not in the latest feature snapshot.";
  if (!r.u.eligible) return `Not in the eligible universe: ${EXCLUSION_TEXT[r.u.exclusion ?? ""] ?? r.u.exclusion ?? "excluded"}.`;
  return head === "p_up10_1d" ? "The model did not score this stock for +10%." : "The model did not score this stock.";
}

function RankCell({ r, head, uni, uniError }: { r: Row; head: UpHead; uni: ScanUniverse | undefined; uniError: boolean }) {
  const v = head === "p_up10_1d" ? r.rank10 : r.rank5;
  const n = uni?.model.rankedEligible;
  const title = v == null
    ? rankReason(r, head, uni, uniError)
    : `Model rank: the stock's ${head === "p_up10_1d" ? "+10%" : "+5%"} next-session estimate is above ${fmtNum(v, 1)}% of the ${n != null ? `${fmtNum(n)} ` : ""}eligible stocks the model scored. A percentile, not a probability.`;
  return (
    <span data-testid="desk-scan-mrank" data-head={head} data-value={v == null ? "" : String(v)} title={title} className="cp-num"
      style={{ fontSize: 12, color: v == null ? "var(--cp-ink-3)" : "var(--cp-ink)", whiteSpace: "nowrap" }}>
      {pctOrd(v)}{v != null && <span style={{ fontSize: 9, color: "var(--cp-ink-3)" }}> pct</span>}
      {v == null && <span className="sr-only">: {title}</span>}
    </span>
  );
}

function patternText(r: Row, plain: boolean): string {
  if (r.s) return setupLabel(r.s, plain);
  const c = r.u?.categories[0];
  if (c) return UCAT_LABEL[c][plain ? 1 : 0];
  return plain ? "On your list" : "Watchlist stock";
}

/** The catalyst: quarterly results in or near the scan window, and the model's events on record. */
function catalystText(r: Row, uni: ScanUniverse | undefined, plain: boolean): string | null {
  const parts: string[] = [];
  const u = r.u;
  const short = (iso: string) => fmtDay(iso).replace(/ \d{4}$/, "");
  if (u?.lastResults && uni?.resultsWindow && u.lastResults >= uni.resultsWindow.from) parts.push(`${plain ? "Results out" : "Results"} ${short(u.lastResults)}`);
  else if (u?.nextResults) parts.push(`Results due ${short(u.nextResults)}`);
  if (r.events != null && r.events > 0) parts.push(`+ ${fmtNum(r.events)} ${plain ? (r.events === 1 ? "news item" : "news items") : r.events === 1 ? "event" : "events"}`);
  return parts.length ? parts.join(" · ") : null;
}

function PatternCell({ r, uni, plain, rules }: { r: Row; uni: ScanUniverse | undefined; plain: boolean; rules: ScanRules | null }) {
  const why = r.s?.why ?? r.s?.reasons[0] ?? null;
  const cat = catalystText(r, uni, plain);
  const rule = r.s?.bucket ? bucketRule(r.s.bucket, rules) : r.u?.categories[0] ? universeRule(r.u.categories[0], rules) : undefined;
  return (
    <span className="flex flex-col" style={{ gap: 2, minWidth: 0 }} title={[rule, why].filter(Boolean).join(" ")}>
      <span data-testid="desk-scan-setup" style={{ fontSize: 13, fontWeight: 500, color: "var(--cp-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{patternText(r, plain)}</span>
      {(why || cat) && (
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {cat && <span data-testid="desk-scan-catalyst" style={{ color: "var(--cp-ink-2)" }}>{cat}{why ? " · " : ""}</span>}
          {why && <span data-testid="desk-scan-why">{why}</span>}
        </span>
      )}
    </span>
  );
}

/** The evidence behind the row: the setup's status and volume, or the universe rule's own figures; a failed gate in words. */
function ConfirmCell({ r }: { r: Row }) {
  const lines: string[] = [];
  let pill: { label: string; tone: Tone; status: string } | null = null;
  if (r.s) {
    const st = STATUS_LABEL[r.s.status];
    pill = { label: st.label, tone: st.tone, status: r.s.status };
    const spike = r.s.signals.volume_spike_3v20;
    if (spike != null) lines.push(`Vol ${fmtNum(spike, 1)}×`);
    const gap = r.s.signals.gap_up_pct;
    if (gap != null) lines.push(`Gap ${fmtSigned(gap, 1)}%`);
  } else if (r.u && r.u.categories.length) {
    pill = { label: "Rule met", tone: "indigo", status: "rule" };
  }
  const u = r.u;
  if (u) {
    if (u.categories.includes("momentum")) lines.push(`20d ${fmtSigned(u.return20d, 1)}%`);
    if (u.categories.includes("unusual_volume")) lines.push(`Vol z ${fmtNum(u.volZ20, 1)}`);
    if (u.categories.includes("results_day")) lines.push(`5d ${fmtSigned(u.return5d, 1)}%`);
    if (u.rvol20 != null && !r.s) lines.push(`RVOL ${fmtNum(u.rvol20, 1)}×`);
  }
  const warn = u && !u.eligible ? `Excluded: ${EXCLUSION_TEXT[u.exclusion ?? ""] ?? u.exclusion ?? "fails a gate"}` : null;
  return (
    <span data-testid="desk-scan-confirm" className="flex min-w-0 flex-col items-start" style={{ gap: 3 }}>
      {pill
        ? <span data-testid="desk-scan-status" data-status={pill.status}><Pill tone={pill.tone}>{pill.label}</Pill></span>
        : <span data-testid="desk-scan-status" data-status="none" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>No setup</span>}
      {lines.length > 0 && <span data-testid="desk-scan-evidence" className="cp-num" title={lines.join(" · ")} style={{ fontSize: 10.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>{lines.join(" · ")}</span>}
      {warn && <span data-testid="desk-scan-excluded" title={warn} style={{ fontSize: 10.5, color: "var(--amber)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>⚠ {warn}</span>}
    </span>
  );
}

function tradability(u: UniverseRow | null): string | null {
  if (!u || !u.hasReference) return null;
  if (u.fnoEligible) return "F&O";
  if (u.priceBandPct != null) return `Band ${fmtNum(u.priceBandPct)}%`;
  return u.bandRaw;
}

function LiquidityCell({ r, minCr, plain }: { r: Row; minCr: number | null; plain: boolean }) {
  const cls = r.tradedCr == null || minCr == null ? null : r.tradedCr >= minCr ? (plain ? "Easy to trade" : "Liquid") : (plain ? "Thinly traded" : "Thin");
  const t = tradability(r.u);
  return (
    <span data-testid="desk-scan-liq" data-class={cls ?? ""} className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <span data-testid="desk-scan-traded" className="cp-num" style={{ fontSize: 11.5, color: r.tradedCr == null ? "var(--cp-ink-3)" : "var(--cp-ink-2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{tradedText(r.tradedCr)}</span>
      <span data-testid="desk-scan-liq-class" style={{ fontSize: 10.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{[cls ?? "—", t].filter(Boolean).join(" · ")}</span>
    </span>
  );
}

/** Risk class from ATR% (the route's bands) and the ATR% itself; `inline` puts both on one line (the table's shared column). */
function RiskCell({ r, inline }: { r: Row; inline?: boolean }) {
  return (
    <span data-testid="desk-scan-risk" data-class={r.risk ?? ""} className={inline ? "flex min-w-0 items-baseline" : "flex min-w-0 flex-col"} style={{ gap: inline ? 6 : 2 }}>
      <span style={{ fontSize: inline ? 11.5 : 12, color: r.risk === "high" ? "var(--amber)" : r.risk ? "var(--cp-ink-2)" : "var(--cp-ink-3)", whiteSpace: "nowrap" }}>{inline ? "Risk " : ""}{r.risk ? RISK_LABEL[r.risk] : "—"}</span>
      <span className="cp-num" style={{ fontSize: 10.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>{r.atrPct != null ? `ATR ${fmtNum(r.atrPct, 1)}%` : "No ATR"}</span>
    </span>
  );
}

/** "₹510.00 +3.00 +0.6%": the last close and its change in rupees and percent. */
function StockSub({ r: row }: { r: Row }) {
  const scanQ = useDeskScanner();
  const live = useLiveOverlay(row.symbol, scanQ.data?.watchAsOf ?? scanQ.data?.signalDate ?? null);                 // Kite, only while the feed is LIVE; otherwise the scan's end-of-day figures
  const r: Row = live ? { ...row, price: live.ltp, change: live.change, changePct: live.changePct } : row;
  if (r.price == null) return <>{r.sector ?? ""}</>;
  if (r.change == null && r.changePct != null) {
    // A Chartink hit sends the close and the % change but no rupee change.
    return (
      <span className="cp-num">
        {fmtPrice(r.price)}{" "}
        <span data-testid="desk-scan-change" style={{ color: TONE_COLOR[r.changePct > 0 ? "mint" : r.changePct < 0 ? "danger" : "ink"] }}>{fmtPct(r.changePct, { signed: true, digits: 1 })}</span>
      </span>
    );
  }
  if (r.change == null || r.changePct == null) return <span className="cp-num">{r.s?.close == null && r.s?.entry != null ? "Entry " : "Close "}{fmtPrice(r.price)}</span>;
  const tone = TONE_COLOR[r.change > 0 ? "mint" : r.change < 0 ? "danger" : "ink"];
  return (
    <span className="cp-num">
      <Flash value={flashOf(live)}>{fmtPrice(r.price)}</Flash>{live ? <sup data-testid="desk-scan-live" data-kind={live.kind} aria-label={live.kind === "close" ? closeLabel(live) : "live price"} title={live.kind === "close" ? closeLabel(live) : "Live · Kite"} style={{ color: live.kind === "close" ? "var(--cp-ink-3)" : "var(--mint)", fontSize: 8, marginLeft: 2 }}>{live.kind === "close" ? "◐" : "●"}</sup> : null}{" "}
      <span data-testid="desk-scan-change-abs" style={{ color: tone }}>{fmtSigned(r.change, 2)}</span>{" "}
      <span data-testid="desk-scan-change" style={{ color: tone }}>{fmtPct(r.changePct, { signed: true, digits: 1 })}</span>
    </span>
  );
}

function StockCell({ r, size = 24 }: { r: Row; size?: number }) {
  return (
    <span className="block min-w-0">
      <SymbolCell symbol={r.symbol} name={r.name} sub={<StockSub r={r} />} testId="desk-scan-symbol" size={size}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 12.5 }}>{r.symbol}</span>
        {r.s?.priceBasis === "raw_no_factors" && (
          <span data-testid="desk-scan-raw-prices" className="cp-mono-note" title="No split/bonus factors for this stock: the scanner scored it on raw NSE prices"
            style={{ fontSize: 10, marginLeft: 6 }}>raw prices</span>
        )}
      </SymbolCell>
    </span>
  );
}

function SparkCell({ s, width, height = 24 }: { s: DeskSetup | null; width: number; height?: number }) {
  const n = s?.spark.length ?? 0;
  if (!s || n < 2) return <span data-testid="desk-scan-spark-none" className="cp-mono-note">No line</span>;
  const tone: Tone = s.spark[n - 1] > s.spark[0] ? "mint" : s.spark[n - 1] < s.spark[0] ? "danger" : "ink";
  return (
    <span data-testid="desk-scan-spark" data-points={n} data-tone={tone} title={`Last ${n} daily closes${s.sparkEnd ? ` to ${fmtDay(s.sparkEnd)}` : ""} (end of day)`} style={{ display: "block", width, maxWidth: "100%" }}>
      <Sparkline values={s.spark} tone={tone} height={height} />
    </span>
  );
}

const targetText = (r: Row) => fmtPct(r.toTarget, { signed: true, digits: 1 });

// ── actions: open analysis, add to a list, paper trade (PRD §5.3, §2.2 Journey 1) ──

function PaperTrade({ r, signalDate }: { r: Row; signalDate: string | null }) {
  const paper = useAddPaperTrade();
  const [qty, setQty] = useState("");
  const id = useId();
  const s = r.s;
  const entry = s?.entry ?? null;
  const stop = s?.stop ?? null;
  const target = s?.target ?? null;
  if (!s || entry == null || stop == null || !(entry > stop)) {
    return <span data-testid="desk-scan-paper-none" style={noteStyle}>Paper trade needs a scanner setup with an entry and a stop below it; {r.symbol} has none on this scan.</span>;
  }
  const sendTarget = target != null && target > entry ? target : null;
  const rule = entryRuleFor(entry, s.close, { stage: s.stage, bucket: s.bucket });
  const q = Number(qty.trim());
  const qtyOk = /^\d+$/.test(qty.trim()) && q >= 1 && q <= 1_000_000;
  const body: NewPaperTrade | null = qtyOk ? {
    symbol: r.symbol, quantity: q, entry_price: entry, stop_price: stop, target_price: sendTarget,
    source: { kind: "scanner", ...(s.bucket ? { bucket: s.bucket } : {}), ...(signalDate ? { signal_date: signalDate } : {}) },
    entry_rule: rule,
  } : null;
  const done = paper.variables?.symbol === r.symbol ? paper : null;
  return (
    <span className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <span className="flex min-w-0 flex-wrap items-center" style={{ gap: 8 }}>
        <label htmlFor={id} style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>Paper trade · shares</label>
        <input id={id} data-testid="desk-scan-paper-qty" inputMode="numeric" value={qty} onChange={(e) => { paper.reset(); setQty(e.target.value); }} placeholder="Qty"
          style={{ ...selectStyle, width: 80 }} />
        <Btn variant="primary" data-testid="desk-scan-paper-add" disabled={!body || paper.isPending} onClick={() => { if (body) paper.mutate(body); }} style={{ padding: "6px 12px", fontSize: 12 }}>
          {paper.isPending ? "Adding…" : "Add paper trade"}
        </Btn>
      </span>
      <span data-testid="desk-scan-paper-note" style={noteStyle}>
        Hypothetical, at the setup’s levels: entry {fmtPrice(entry)} (<span data-testid="desk-scan-paper-rule" data-rule={rule}>{ENTRY_RULE_SHORT[rule]}</span>), stop {fmtPrice(stop)}{sendTarget != null ? `, target ${fmtPrice(sendTarget)}` : ", no target"}. No order is placed and nothing is sent to a broker; it is marked against end-of-day closes.
      </span>
      {done?.isSuccess && <span role="status" data-testid="desk-scan-paper-done" style={{ fontSize: 12, color: "var(--mint)" }}>Paper trade added: {fmtNum(done.variables?.quantity ?? null)} {r.symbol} at {fmtPrice(done.variables?.entry_price ?? null)}. No order is placed.</span>}
      {done?.isError && <span role="alert" data-testid="desk-scan-paper-error" style={{ fontSize: 12, color: "var(--cp-danger)" }}>Not added — {writeProblem(done.error)}</span>}
      {done?.isError && (
        <RiskReduceOffer error={done.error} testId="desk-scan-paper-reduce"
          onAccept={(n) => { const last = done.variables; if (!last) return; setQty(String(n)); paper.mutate({ ...last, quantity: n }); }} />
      )}
    </span>
  );
}

function ActionPanel({ r, signalDate, onOpen, plain }: { r: Row; signalDate: string | null; onOpen: (sym: string) => void; plain: boolean }) {
  const { openStrategy } = useDesk();
  return (
    <div data-testid={`desk-scan-actions-${r.symbol}`} className="flex min-w-0 flex-col" style={{ gap: 10, padding: "10px 0 2px" }}>
      <span className="flex min-w-0 flex-wrap items-center" style={{ gap: 12 }}>
        <Btn data-testid="desk-scan-act-open" onClick={() => onOpen(r.symbol)} style={{ padding: "6px 12px", fontSize: 12 }}>{plain ? "See the chart ›" : "Open analysis ›"}</Btn>
        <Btn data-testid="desk-scan-act-strategy" onClick={() => openStrategy(r.symbol, { kind: "scanner", bucket: r.s?.bucket ?? null, date: signalDate })} style={{ padding: "6px 12px", fontSize: 12 }}>Build a strategy ›</Btn>
        <span data-testid="desk-scan-act-list" className="min-w-0"><AddToList symbol={r.symbol} name={r.name ?? r.symbol} /></span>
      </span>
      <PaperTrade r={r} signalDate={signalDate} />
    </div>
  );
}

// ── table (wide), cards (narrow box and phone) ───────────────────────────

/**
 * # · Stock · Score · P · Model rank · Pattern / catalyst · Confirmation · Liquidity · risk · To target · 24 sessions · Action.
 * Liquidity and risk share a column (each on its own labelled line) so the PRD's fields fit the desk at 1280px.
 */
const COLS = "22px minmax(0,1.3fr) 40px 62px 54px minmax(0,1.5fr) 92px 120px 52px 52px 44px";
const COL_GAP = 8;
const cellStyle: CSSProperties = { minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
/** Width the eleven columns need; a narrower box (the desk beside the docked Copilot) shows the rows as cards. */
const TABLE_MIN_WIDTH = 940;

function useNarrowBox(box: HTMLElement | null, below: number, initial: boolean): boolean {
  const [narrow, setNarrow] = useState(initial);
  useEffect(() => {
    if (!box || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setNarrow(w < below);
    });
    ro.observe(box);
    return () => ro.disconnect();
  }, [box, below]);
  return narrow;
}

/** Every field's label, trader or investor wording. */
function fieldLabels(head: UpHead, plain: boolean): Record<string, string> {
  return {
    rank: "#", stock: "Stock", score: "Score", odds: oddsLabel(head, plain), mrank: "Model rank",
    setup: plain ? "Why it shows up" : "Pattern / catalyst", confirm: plain ? "What backs it" : "Confirmation",
    liquidity: plain ? "Easy to trade" : "Liquidity", risk: "Risk", target: "To target", spark: "24 sessions", action: "Action",
  };
}

const TABLE_COLUMNS = ["rank", "stock", "score", "odds", "mrank", "setup", "confirm", "liqrisk", "target", "spark", "action"] as const;

function tableHeads(head: UpHead, plain: boolean): Array<[string, string]> {
  const l = fieldLabels(head, plain);
  return TABLE_COLUMNS.map((k) => [k, k === "liqrisk" ? `${l.liquidity} · ${l.risk.toLowerCase()}` : l[k]]);
}

const rankText = (i: number) => String(i + 1).padStart(2, "0");

interface ListProps {
  rows: Row[];
  selected: string | null;
  onOpen: (sym: string) => void;
  head: UpHead;
  plain: boolean;
  gate: { shown: false; reason: string };
  uni: ScanUniverse | undefined;
  uniError: boolean;
  minCr: number | null;
  rules: ScanRules | null;
  signalDate: (r: Row) => string | null;
  fno: FnoState;
}

/** The F&O build-up scan as the rows need it: its data, and whether it is still loading or failed. */
interface FnoState {
  data: Buildup | undefined;
  pending: boolean;
  error: boolean;
}

/**
 * The F&O analysis of a stock, shown on every row whose stock is F&O-eligible (the universe's NSE lot-size flag, or the
 * build-up scan's own eligibility) and on no other. End of day, from the futures build-up scan: the build-up reading,
 * OI change, whether the futures agree with the cash move, the near expiry and the scan's risk flags. A figure the
 * scan lacks is "—", never 0.
 */
const isFno = (r: Row, fno: FnoState) => r.u?.fnoEligible === true || buildupRowFor(fno.data, r.symbol)?.fnoEligible === true;

function FnoLine({ r, fno, plain }: { r: Row; fno: FnoState; plain: boolean }) {
  if (!isFno(r, fno)) return null;
  const b = buildupRowFor(fno.data, r.symbol);
  const meta = b?.label ? BUILDUP_META[b.label] : null;
  const dim: CSSProperties = { color: "var(--cp-ink-3)" };
  let body: ReactNode;
  if (fno.pending) body = <span style={dim}>Loading the futures scan…</span>;
  else if (fno.error && !fno.data) body = <span style={dim}>The futures scan didn’t load, so this stock’s F&O analysis is not shown.</span>;
  else if (!b) body = <span style={dim}>Eligible for F&O, but the futures scan has no row for it on {fmtDay(fno.data?.asOf)}.</span>;
  else {
    const parts: string[] = [];
    parts.push(`OI ${fmtPct(b.oiChgPct, { signed: true, digits: 1 })}`);
    if (b.cashConfirmation) parts.push(b.cashConfirmation === "confirms" ? (plain ? "Futures agree with the cash price" : "Futures confirm cash") : (plain ? "Futures disagree with the cash price" : "Futures diverge from cash"));
    if (b.nearExpiry) parts.push(`Expiry ${fmtDay(b.nearExpiry)}${b.daysToExpiry != null ? ` (${fmtNum(b.daysToExpiry)}d)` : ""}`);
    if (b.futTurnoverCr != null) parts.push(`Futures ₹${fmtNum(b.futTurnoverCr)} Cr`);
    for (const f of b.riskFlags) parts.push(RISK_FLAG_LABEL[f] ?? f);
    body = (
      <>
        <span data-testid="desk-scan-fno-label" data-label={b.label ?? ""} style={{ color: meta ? TONE_COLOR[meta.tone] : "var(--cp-ink-3)" }} title={meta ? (plain ? meta.rule : meta.plain) : undefined}>
          {meta ? (plain ? meta.plain : meta.label) : "No build-up reading"}
        </span>
        <span data-testid="desk-scan-fno-detail" className="cp-num" style={dim}>{parts.join(" · ")}</span>
      </>
    );
  }
  return (
    <span data-testid="desk-scan-fno" className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "2px 10px", fontSize: 11.5 }}>
      <span className="cp-eyebrow" style={{ fontSize: 8.5 }}>F&O{fno.data?.asOf ? ` · ${fmtDay(fno.data.asOf)}` : ""}</span>
      {body}
    </span>
  );
}

function ScanTable({ rows, selected, onOpen, head, plain, gate, uni, uniError, minCr, rules, signalDate, fno }: ListProps) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div role="table" aria-label="Scanner opportunities" data-testid="desk-scan-table" data-layout="table">
      <div role="row" className="grid" style={{ gridTemplateColumns: COLS, gap: COL_GAP, padding: "10px 18px" }}>
        {tableHeads(head, plain).map(([k, label]) => (
          // Headers wrap rather than cut: the probability's header is its exact outcome definition.
          <span key={k} role="columnheader" data-testid={`desk-scan-col-${k}`} style={{ minWidth: 0, alignSelf: "end", lineHeight: 1.35, fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>{label}</span>
        ))}
      </div>
      {rows.map((r, i) => {
        const on = r.symbol === selected;
        const expanded = open === r.symbol;
        return (
          <div key={r.symbol} role="rowgroup" style={{ borderTop: "1px solid var(--cp-line)", background: on ? "var(--bg-2)" : undefined }}>
            <div role="row" tabIndex={0} data-testid={`desk-scan-row-${r.symbol}`} data-selected={on} aria-current={on ? "true" : undefined}
              onClick={() => onOpen(r.symbol)}
              onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onOpen(r.symbol); } }}
              className="cp-row-link grid items-center"
              style={{ gridTemplateColumns: COLS, gap: COL_GAP, padding: "10px 18px", fontSize: 13, color: "var(--cp-ink-2)" }}>
              <span role="cell" data-testid="desk-scan-rank" className="cp-num" style={{ ...cellStyle, fontSize: 11, color: on ? "var(--mint)" : "var(--cp-ink-3)" }}>{rankText(i)}</span>
              <span role="cell" style={cellStyle}><StockCell r={r} /></span>
              <span role="cell" style={cellStyle}><ScoreText score={r.s?.score ?? null} /></span>
              <span role="cell" style={cellStyle}><ProbCell gate={gate} head={head} /></span>
              <span role="cell" style={cellStyle}><RankCell r={r} head={head} uni={uni} uniError={uniError} /></span>
              <span role="cell" style={cellStyle}><PatternCell r={r} uni={uni} plain={plain} rules={rules} /></span>
              <span role="cell" style={cellStyle}><ConfirmCell r={r} /></span>
              <span role="cell" className="flex flex-col" style={{ ...cellStyle, gap: 4 }}>
                <LiquidityCell r={r} minCr={minCr} plain={plain} />
                <RiskCell r={r} inline />
              </span>
              <span role="cell" data-testid="desk-scan-target" className="cp-num" style={{ ...cellStyle, fontSize: 12, color: r.toTarget == null ? "var(--cp-ink-3)" : TONE_COLOR.mint }}>{targetText(r)}</span>
              <span role="cell" style={cellStyle}><SparkCell s={r.s} width={52} /></span>
              <span role="cell" style={cellStyle}>
                <button type="button" data-testid="desk-scan-act" aria-expanded={expanded} aria-controls={`desk-scan-actions-${r.symbol}`}
                  onClick={(e) => { e.stopPropagation(); setOpen(expanded ? null : r.symbol); }}
                  onKeyDown={(e) => e.stopPropagation()}
                  style={{ padding: "4px 8px", borderRadius: 999, border: "1px solid var(--line-2)", background: expanded ? "var(--bg-3)" : "transparent", color: "var(--cp-ink-2)", fontSize: 11, cursor: "pointer", fontFamily: "var(--sans)" }}>
                  {expanded ? "Close" : "Act ▾"}
                </button>
              </span>
            </div>
            {isFno(r, fno) && <div style={{ padding: "0 18px 8px 50px" }}><FnoLine r={r} fno={fno} plain={plain} /></div>}
            {r.ck && <div style={{ padding: "0 18px 8px 50px" }}><ChartinkTag hit={r.ck} /></div>}
            {expanded && (
              <div id={`desk-scan-actions-${r.symbol}`} style={{ padding: "0 18px 12px 50px" }}>
                <ActionPanel r={r} signalDate={signalDate(r)} onOpen={onOpen} plain={plain} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** The same fields as compact cards: a narrow desk box (beside the docked Copilot) and the phone (PRD §5.3, design §11 M2). */
function ScanCards({ rows, selected, onOpen, head, plain, gate, uni, uniError, minCr, rules, signalDate, fno, phone }: ListProps & { phone: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  const heads = fieldLabels(head, plain);
  return (
    <div role="list" aria-label="Scanner opportunities" className="flex min-w-0 flex-col" data-testid={phone ? "desk-scan-table" : "desk-scan-cards"} data-layout={phone ? "phone" : "cards"}>
      {rows.map((r, i) => {
        const on = r.symbol === selected;
        const expanded = open === r.symbol;
        return (
          <div key={r.symbol} role="listitem" data-testid={`desk-scan-row-${r.symbol}`} data-selected={on} aria-current={on ? "true" : undefined}
            // A click anywhere on the card but its own controls opens the analysis (the head button does the same by keyboard).
            onClick={(e) => { if (!(e.target as HTMLElement).closest("button, a, input, select, label, summary, [role='status'], [role='alert']")) onOpen(r.symbol); }}
            className="cp-row-link flex min-w-0 flex-col" style={{ cursor: "pointer", gap: 8, padding: phone ? 12 : "12px 18px", borderTop: i || !phone ? "1px solid var(--cp-line)" : undefined, background: on ? "var(--bg-2)" : undefined }}>
            <button type="button" data-testid="desk-scan-open" onClick={() => onOpen(r.symbol)} className="cp-row-link flex w-full min-w-0 items-center"
              style={{ gap: 10, padding: 0, border: 0, background: "transparent", textAlign: "left", color: "var(--cp-ink-2)", fontFamily: "var(--sans)", fontSize: 13 }}>
              <span data-testid="desk-scan-rank" className="cp-num" style={{ flex: "none", width: 18, fontSize: 10.5, color: on ? "var(--mint)" : "var(--cp-ink-3)" }}>{phone ? i + 1 : rankText(i)}</span>
              <span style={{ flex: "1 1 auto", minWidth: 0 }}><StockCell r={r} size={phone ? 20 : 24} /></span>
              <span style={{ flex: "none" }}><ScoreText score={r.s?.score ?? null} size={phone ? 18 : 23} /></span>
            </button>
            <span className="flex w-full min-w-0 items-start justify-between" style={{ gap: 10 }}>
              <span style={{ minWidth: 0, flex: "1 1 auto" }}><PatternCell r={r} uni={uni} plain={plain} rules={rules} /></span>
              <span style={{ flex: "none", maxWidth: "45%" }}><ConfirmCell r={r} /></span>
            </span>
            <span className="grid w-full min-w-0" style={{ gridTemplateColumns: phone ? "repeat(2, minmax(0,1fr))" : "repeat(5, minmax(0,1fr))", gap: "8px 12px" }}>
              {([
                ["odds", <ProbCell key="p" gate={gate} head={head} small />],
                ["mrank", <RankCell key="m" r={r} head={head} uni={uni} uniError={uniError} />],
                ["liquidity", <LiquidityCell key="l" r={r} minCr={minCr} plain={plain} />],
                ["risk", <RiskCell key="k" r={r} />],
                ["target", <span key="t" data-testid="desk-scan-target" className="cp-num" style={{ fontSize: 12, color: r.toTarget == null ? "var(--cp-ink-3)" : TONE_COLOR.mint }}>{targetText(r)}</span>],
              ] as Array<[string, ReactNode]>).map(([k, node]) => (
                <span key={k} className="flex min-w-0 flex-col" style={{ gap: 3 }}>
                  <span className="cp-eyebrow" style={{ fontSize: 8.5, ...cellStyle }}>{heads[k]}</span>
                  {node}
                </span>
              ))}
            </span>
            <FnoLine r={r} fno={fno} plain={plain} />
            {r.ck && <ChartinkTag hit={r.ck} />}
            <span className="flex min-w-0 flex-wrap items-center" style={{ gap: 8 }}>
              <button type="button" data-testid="desk-scan-act" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : r.symbol)}
                style={{ padding: "4px 10px", borderRadius: 999, border: "1px solid var(--line-2)", background: expanded ? "var(--bg-3)" : "transparent", color: "var(--cp-ink-2)", fontSize: 11.5, cursor: "pointer", fontFamily: "var(--sans)" }}>
                {expanded ? "Close actions" : "Actions ▾"}
              </button>
              {!phone && <SparkCell s={r.s} width={84} />}
            </span>
            {expanded && <ActionPanel r={r} signalDate={signalDate(r)} onOpen={onOpen} plain={plain} />}
          </div>
        );
      })}
    </div>
  );
}

// ── Chartink-only rows ───────────────────────────────────────────────────

const CK_COLS = "22px minmax(0,1.4fr) minmax(0,2fr) 76px 120px";

/**
 * The "Chartink scans" category: stocks the user's Chartink scans hit that the AI scanner does not list. Each shows its
 * scan names, the hit's close and % change, and liquidity where the universe knows it. There is no AI score or probability.
 */
function CkRows({ rows, selected, onOpen, minCr, plain, cards }: { rows: Row[]; selected: string | null; onOpen: (sym: string) => void; minCr: number | null; plain: boolean; cards: boolean }) {
  const open = (e: React.KeyboardEvent, sym: string) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onOpen(sym); } };
  const names = (r: Row) => (r.ck?.scans ?? []).map((x) => x.name).join(", ");
  const noScore = <span data-testid="desk-scan-ck-noscore" title="The AI scanner does not list this stock, so it has no AI score or probability" className="cp-num" style={{ fontSize: 10.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>No AI score</span>;
  if (cards) {
    return (
      <div role="list" aria-label="Chartink scan hits" data-testid="desk-scan-table" data-layout="ck-cards" className="flex min-w-0 flex-col">
        {rows.map((r, i) => (
          <div key={r.symbol} role="listitem" tabIndex={0} data-testid={`desk-scan-row-${r.symbol}`} data-selected={r.symbol === selected} onClick={() => onOpen(r.symbol)} onKeyDown={(e) => open(e, r.symbol)}
            className="cp-row-link flex min-w-0 flex-col" style={{ cursor: "pointer", gap: 6, padding: "12px 14px", borderTop: i ? "1px solid var(--cp-line)" : undefined }}>
            <span className="flex min-w-0 items-center justify-between" style={{ gap: 10 }}>
              <span style={{ minWidth: 0 }}><StockCell r={r} size={22} /></span>
              {noScore}
            </span>
            <span data-testid="desk-scan-ck-scans" style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>Chartink: {names(r) || "—"}</span>
            <span className="flex flex-wrap items-center" style={{ gap: "2px 12px", fontSize: 11.5, color: "var(--cp-ink-3)" }}>
              <span data-testid="desk-scan-ck-liq">{r.tradedCr != null ? `${minCr != null ? (r.tradedCr >= minCr ? (plain ? "Easy to trade" : "Liquid") : (plain ? "Thinly traded" : "Thin")) + " · " : ""}${tradedText(r.tradedCr)}` : "Liquidity —"}</span>
              {r.u?.fnoEligible && <span data-testid="desk-scan-ck-fno">F&amp;O</span>}
            </span>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div role="table" aria-label="Chartink scan hits" data-testid="desk-scan-table" data-layout="ck-table">
      <div role="row" className="grid" style={{ gridTemplateColumns: CK_COLS, gap: COL_GAP, padding: "10px 18px" }}>
        {["#", "Stock", "Your Chartink scans", "AI score", "Liquidity"].map((h) => (
          <span key={h} role="columnheader" style={{ minWidth: 0, fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>{h}</span>
        ))}
      </div>
      {rows.map((r, i) => (
        <div key={r.symbol} role="row" tabIndex={0} data-testid={`desk-scan-row-${r.symbol}`} data-selected={r.symbol === selected} onClick={() => onOpen(r.symbol)} onKeyDown={(e) => open(e, r.symbol)}
          className="cp-row-link grid items-center" style={{ gridTemplateColumns: CK_COLS, gap: COL_GAP, padding: "10px 18px", fontSize: 13, color: "var(--cp-ink-2)", borderTop: "1px solid var(--cp-line)", cursor: "pointer" }}>
          <span role="cell" className="cp-num" style={{ ...cellStyle, fontSize: 11, color: "var(--cp-ink-3)" }}>{rankText(i)}</span>
          <span role="cell" style={cellStyle}><StockCell r={r} /></span>
          <span role="cell" data-testid="desk-scan-ck-scans" title={names(r)} style={{ fontSize: 12, lineHeight: 1.4, overflowWrap: "anywhere" }}>{names(r) || "—"}</span>
          <span role="cell">{noScore}</span>
          <span role="cell" data-testid="desk-scan-ck-liq" className="cp-num" style={{ ...cellStyle, fontSize: 11.5, color: r.tradedCr == null ? "var(--cp-ink-3)" : "var(--cp-ink-2)" }}>{tradedText(r.tradedCr)}{r.u?.fnoEligible ? " · F&O" : ""}</span>
        </div>
      ))}
    </div>
  );
}

function ckBodyState(ck: ChartinkState, openChartink: () => void): ReactNode | null {
  if (ck.kind === "loading" || ck.kind === "hits_loading") return <div style={{ padding: 18 }}><LoadingBlock label="Loading your Chartink scans" rows={2} /></div>;
  if (ck.kind === "not_connected") {
    return (
      <div data-testid="desk-scan-ck-connect" style={{ padding: "14px 18px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        Connect your Chartink dashboard to list your scans here.{" "}
        <button type="button" data-testid="ck-connect-link" onClick={openChartink} style={{ ...linkBtn, color: "var(--mint)" }}>Connect your Chartink dashboard ›</button>
      </div>
    );
  }
  if (ck.kind === "source_error" || ck.kind === "hits_error") {
    return <div data-testid="desk-scan-ck-error" style={{ padding: 18 }}><ErrorBlock title="Your Chartink scans didn’t load" error={ck.error} onRetry={ck.retry} /></div>;
  }
  return null;
}

// ── disclosures (PRD §5.4, §5.8) ─────────────────────────────────────────

function UniverseNote({ uni, uniError, onRetry, rules, minCr }: { uni: ScanUniverse | undefined; uniError: boolean; onRetry: () => void; rules: ScanRules | null; minCr: number | null }) {
  const cand = rules?.candidates;
  const order = rules?.universe?.order.length ? rules.universe.order : Object.keys(EXCLUSION_TEXT);
  const sessions = rules?.liquidity?.sessions ?? null;
  const ruleText: Record<string, string> = {
    missing_price: "no close (or previous close) for the scan date",
    no_traded_value: `fewer than ${fmtNum(sessions)} sessions of close × volume, so no traded value`,
    no_reference: "no NSE security reference row (series, price band, F&O flag)",
    series: `not in the ${rules?.universe?.series.join(" or ") ?? "—"} series`,
    etf: "an ETF",
    price_band: `a price band under ${fmtNum(rules?.universe?.minPriceBandPct ?? null)}% (NSE's tight circuit limits)`,
    at_band_limit: `closed within ${fmtNum(rules?.universe?.bandLimitTolerancePct ?? null, 1)} point of its band limit`,
    illiquid: `average traded value under ₹${fmtNum(minCr)} Cr a day over ${fmtNum(sessions)} sessions`,
  };
  return (
    <details data-testid="desk-scan-universe" style={{ fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
      <summary data-testid="desk-scan-universe-toggle" style={{ cursor: "pointer", color: "var(--cp-ink-2)" }}>
        {uni
          ? <>Eligible universe: <span data-testid="desk-scan-universe-count">{fmtNum(uni.universe.eligible)} of {fmtNum(uni.universe.total)}</span> stocks on {fmtDay(uni.asOf)} · how stocks are excluded</>
          : uniError ? "Eligible universe: did not load" : "Eligible universe: loading"}
      </summary>
      <span className="flex flex-col" style={{ gap: 4, paddingTop: 6 }}>
        {uniError && (
          <span role="alert" style={{ color: "var(--cp-danger)" }}>
            GET /api/positional/scan-universe did not answer, so momentum, unusual volume, results-day and F&O candidates, the model rank and the exclusion counts are not shown.{" "}
            <button type="button" data-testid="desk-scan-universe-retry" onClick={onRetry} style={linkBtn}>Retry</button>
          </span>
        )}
        {uni && (
          <>
            <span>The universe categories and the model rank use each NSE stock’s latest end-of-day feature row in the data platform ({fmtNum(uni.universe.total)} on {fmtDay(uni.asOf)}), with that day’s bhavcopy price. A stock is left out for the first of these it meets; missing data never counts as passing:</span>
            <ul data-testid="desk-scan-exclusions" className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 18 }}>
              {order.map((k) => (
                <li key={k} data-testid={`desk-scan-excl-${k}`}>{ruleText[k] ?? k}: <span className="cp-num">{uni.universe.excluded[k] != null ? fmtNum(uni.universe.excluded[k]) : "—"}</span></li>
              ))}
            </ul>
            <span data-testid="desk-scan-universe-fno">F&O eligible in the eligible universe: {fmtNum(uni.universe.fnoEligible)} (NSE lot-size file, reference of {fmtDay(uni.referenceAsOf)}).</span>
          </>
        )}
        {cand && (
          <span data-testid="desk-scan-setup-universe">
            Setups come from the positional scanner: the top {fmtNum(cand.topByScore)} stocks by score above ₹{fmtNum(cand.minClose)} whose stage is not {cand.excludedStages.join(" or ")}, with at least {fmtNum(cand.minBars)} sessions of bars.
          </span>
        )}
      </span>
    </details>
  );
}

function AboutModel({ odds, uni, engineVersions, classifier, rulesVersion }: { odds: DeskOdds | undefined; uni: ScanUniverse | undefined; engineVersions: string[]; classifier: string | null; rulesVersion: string | null }) {
  const run = odds?.kind === "final" ? odds.data.run : null;
  const record = odds?.kind === "final" ? odds.data.record : null;
  const b: CSSProperties = { color: "var(--cp-ink-2)", fontWeight: 500 };
  return (
    <details data-testid="desk-scan-about-model" style={{ fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
      <summary data-testid="desk-scan-about-toggle" style={{ cursor: "pointer", color: "var(--cp-ink-2)" }}>About the model</summary>
      <span className="flex flex-col" style={{ gap: 6, paddingTop: 6 }}>
        <span><b style={b}>Score</b> is the end-of-day positional scanner’s rules-based score (final_score × 100) from its trend, breakout, volume and accumulation checks. It ranks setups; it is not a probability.{engineVersions.length ? ` Engine ${engineVersions.join(", ")}.` : ""}{classifier ? ` Classifier ${classifier}.` : ""}{rulesVersion ? ` Rules ${rulesVersion}.` : ""} <span className="cp-mono-note">backend/services/positional_engine/ · setup_rules.py</span></span>
        <span data-testid="desk-scan-about-odds"><b style={b}>Move-odds model</b> gives next-session estimates only: the chance the next session’s high reaches the previous close plus 5% or 10%. Each night’s estimates are frozen as a hashed snapshot and published unchanged; its record comes from a pre-registered test window.{run ? ` Published run: model ${run.model}${run.refit ? `, ${run.refit} refit` : ""}${run.train_end ? `, trained to ${fmtDay(run.train_end)}` : ""}, ${fmtNum(run.scored)} of ${fmtNum(run.universe_size)} stocks scored on data of ${fmtDay(run.data_as_of)}.` : " No published run is available to this view, so none of its figures are shown."}{record ? ` Out-of-sample window: ${record.window_label}.` : ""} <span className="cp-mono-note">backend/nidp/migrations/149_tpd_move_odds_publish.sql</span></span>
        <span><b style={b}>Model rank</b> is the stock’s estimate as a percentile among the eligible stocks the model scored{uni?.model.rankedEligible != null ? ` (${fmtNum(uni.model.rankedEligible)} on this scan)` : ""}. It is an order, not a probability. <span className="cp-mono-note">setup_rules.py · rank_percentiles</span></span>
        <span><b style={b}>Probability</b> is shown only when its route marks it calibrated (PRD §5.8). The move-odds route sends a band record but no calibration flag, so the column says “Withheld”.</span>
        <span>The baseline configuration the PRD names (a HistGradientBoostingClassifier, §5.4) could not be matched to code in this repo, and PRD §5.5 Tasks B (return after costs) and C (trade outcome) have no model yet.</span>
        <span data-testid="desk-scan-model-limit" style={{ color: "var(--amber)" }}>Limitation (PRD §5.4): “Prior evaluation identified substantial dependence on volatility features and gaps in stock-universe coverage. Therefore, the initial scanner must not assume that the model's ranking is a reliable estimate of profitability.”</span>
      </span>
    </details>
  );
}

const PARTIAL_NOTE: Record<"watchlist" | "picks", string> = {
  watchlist: "The setup watchlist (GET /api/positional/watchlist) did not answer, so only the scanner’s picks are listed.",
  picks: "The scanner picks (GET /api/positional/picks) did not answer, so only the setup watchlist is listed and no stock has a target.",
};

// ── the tab ──────────────────────────────────────────────────────────────

const ScannerPulse = lazy(() => import("./ScannerPulse").then((m) => ({ default: m.ScannerPulse })));
const ScannerTop10 = lazy(() => import("./ScannerTop10").then((m) => ({ default: m.ScannerTop10 })));

/** The tab: the market pulse and the Top 10 boards (each loads on its own), then the scanner list. */
export default function ScannerTab() {
  const { mobile } = useCopilotShell();
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: mobile ? 12 : 16 }}>
      <Suspense fallback={<LoadingBlock label="Loading the market pulse" rows={1} />}><ScannerPulse /></Suspense>
      <Suspense fallback={<LoadingBlock label="Loading the Top 10 ideas" rows={2} />}><ScannerTop10 /></Suspense>
      <ScannerList />
    </div>
  );
}

function ScannerList() {
  const { mobile } = useCopilotShell();
  const { symbol, openChart, openTab, openChartink, persona } = useDesk();
  const plain = persona === "investor";
  const st = useScanState();
  const ck = useChartink();
  const ckHits = ck.kind === "ready" ? ck.hits : null;
  const ckMap = useMemo(() => hitsBySymbol(ckHits), [ckHits]);
  // Chartink-only stocks get a universe row too (liquidity, F&O, sector), asked for with the user's list symbols.
  const ckSyms = useMemo(() => (ckHits?.symbols ?? []).filter((x) => x.in_ai_scanner === false).slice(0, 60).map((x) => x.symbol), [ckHits]);
  const { cat, rank, filters: f, set } = st;
  const scan = useDeskScanner();
  const odds5Q = useDeskOdds("p_up5_1d");
  const odds10Q = useDeskOdds("p_up10_1d");
  const lists = usePersonalLists();
  const [listBox, setListBox] = useState<HTMLDivElement | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const asCards = useNarrowBox(listBox, TABLE_MIN_WIDTH, true);

  // User watchlist: the chosen list (sc_list), else the first one.
  const listId = cat === "watchlist" ? (st.list ?? lists.data?.lists[0]?.watchlist_id ?? null) : null;
  const listQ = usePersonalList(listId);
  const listStocks = useMemo(() => (cat === "watchlist" ? listQ.data?.stocks ?? [] : []), [cat, listQ.data]);

  const setups = scan.data?.setups;
  const setupSyms = useMemo(() => (setups ?? []).map((s) => s.symbol), [setups]);
  const listSyms = useMemo(() => [...listStocks.map((s) => s.symbol), ...ckSyms], [listStocks, ckSyms]);
  const uniQ = useScanUniverse(setupSyms, listSyms, !scan.isPending);
  const buildupQ = useBuildup(true);
  const fno: FnoState = { data: buildupQ.data, pending: buildupQ.isPending, error: buildupQ.isError };
  const uni = uniQ.data;
  const uniError = uniQ.isError && !uni;

  const rules = scan.data?.rules ?? uni?.rules ?? null;
  const minCr = rules?.liquidity?.minCr ?? null;
  const modelReady = !!uni && uni.model.status === "final";
  const rankBy: RankBy = rank !== "score" && !modelReady ? "score" : rank;
  const head: UpHead = rankBy === "m10" ? "p_up10_1d" : "p_up5_1d";
  const oddsQ = head === "p_up10_1d" ? odds10Q : odds5Q;
  const gate = probabilityGate(oddsQ.data, plain);
  const bySym5 = odds5Q.data?.kind === "final" ? odds5Q.data.bySymbol : null;

  // Every stock any category can show, once.
  const rowsAll = useMemo(() => {
    const out = new Map<string, Row>();
    const setupBy = new Map((setups ?? []).map((s) => [s.symbol.toUpperCase(), s]));
    const names = new Map(listStocks.map((s) => [s.symbol.toUpperCase(), s.company_name]));
    const syms = new Set<string>(setupBy.keys());
    for (const c of Object.values(uni?.categories ?? {})) for (const s of c?.symbols ?? []) syms.add(s);
    for (const s of names.keys()) syms.add(s);
    for (const k of ckMap.keys()) syms.add(k);
    for (const sym of syms) {
      const row = buildRow(sym, setupBy.get(sym) ?? null, uni?.rows.get(sym) ?? null, bySym5, rules, names.get(sym) ?? ckMap.get(sym)?.name ?? null);
      if (ckHits) {
        row.ckKnown = true;
        row.ck = ckMap.get(sym) ?? null;
        // The hit's own close and % change stand in only where the scanner and universe have none.
        if (row.ck && row.price == null) row.price = row.ck.close;
        if (row.ck && row.changePct == null) row.changePct = row.ck.pct_change;
      }
      out.set(sym, row);
    }
    return out;
  }, [setups, uni, listStocks, bySym5, rules, ckMap, ckHits]);

  const catDef = catOf(cat);
  const inCategory = useMemo(() => {
    const all = [...rowsAll.values()];
    if (cat === "all") return all.filter((r) => r.s || (r.ck && r.ck.in_ai_scanner === false) || CATS.some((c) => c.ucat && inCat(r, c, uni)));
    if (cat === "chartink") return all.filter((r) => r.ck && r.ck.in_ai_scanner === false);
    if (cat === "watchlist") return listStocks.map((s) => rowsAll.get(s.symbol.toUpperCase())).filter((r): r is Row => !!r);
    return all.filter((r) => inCat(r, catDef, uni));
  }, [rowsAll, cat, catDef, uni, listStocks]);

  // Filters: a row without the figure a filter reads is hidden while that filter is on, and counted (never passed).
  const { rows, lacking } = useMemo(() => {
    const active = FILTERS.filter((d) => d.active(f));
    const lack = new Map<string, number>();
    const kept = inCategory.filter((r) => {
      for (const d of active) {
        const t = d.test(r, f, minCr);
        if (t == null) {
          lack.set(d.lacks, (lack.get(d.lacks) ?? 0) + 1);
          return false;
        }
        if (!t) return false;
      }
      return true;
    });
    const catField = catDef.ucat ? UNIVERSE_FIELD[uni?.categories[catDef.ucat]?.rankBy ?? ""] : undefined;
    const cv = (r: Row) => (catField && r.u ? catField(r.u) : null);
    const byScore = (a: Row, b: Row) => desc(a.s?.score ?? null, b.s?.score ?? null) || desc(cv(a), cv(b)) || desc(a.rank5, b.rank5) || desc(a.tradedCr, b.tradedCr) || a.symbol.localeCompare(b.symbol);
    const byChartink = (a: Row, b: Row) => desc(a.ck?.count ?? null, b.ck?.count ?? null) || desc(a.ck?.pct_change ?? null, b.ck?.pct_change ?? null) || a.symbol.localeCompare(b.symbol);
    const sorted = [...kept].sort((a, b) => {
      if (cat === "chartink") return byChartink(a, b);
      if (rankBy === "score") return byScore(a, b);
      return desc(rankBy === "m10" ? a.rank10 : a.rank5, rankBy === "m10" ? b.rank10 : b.rank5) || byScore(a, b);
    });
    return { rows: sorted, lacking: lack };
  }, [inCategory, f, minCr, rankBy, catDef, uni, cat]);

  // Reversal candidates have their own route and row shape (reversal-rules.v1); the category chips stay shared.
  if (cat === "reversal") {
    return <ReversalPanel chips={<CategoryChips value={cat} onChange={(c) => set({ cat: c === "all" ? null : c })} plain={plain} scroll={mobile} />}
      plain={plain} selected={symbol} onOpen={openChart} />;
  }

  if (scan.isPending || (scan.isError && uniQ.isPending)) return <LoadingBlock label="Loading the scanner" rows={5} />;
  if (scan.isError && uniError) {
    return (
      <div data-testid="desk-scan-error">
        <ErrorBlock title="The scanner didn’t load: neither the setup watchlist nor the scanner picks answered" error={scan.error} onRetry={() => { scan.refetch(); uniQ.refetch(); }} />
      </div>
    );
  }

  const data = scan.data;
  const date = data ? scanDateLabel(data.watchAsOf, data.signalDate) : null;
  const dayLabel = date ?? (uni ? fmtDay(uni.asOf) : null);
  const activeFilters = FILTERS.filter((d) => d.active(f));
  const sectors = [...new Set([...rowsAll.values()].map((r) => r.sector).filter((s): s is string => !!s))].sort();
  const capReady = [...rowsAll.values()].some((r) => r.u?.marketCapBucket);
  const filterCount = activeFilters.length;
  const shown = `${fmtNum(rows.length)} of ${fmtNum(inCategory.length)} shown`;
  const signalDateOf = (r: Row) => (r.s ? (r.s.inPicks ? data?.signalDate : data?.watchAsOf) ?? null : null);
  const versions = [data?.rulesVersion ?? rules?.version, data?.classifierVersion, ...(data?.engineVersions ?? [])].filter(Boolean).join(" · ");
  const hiddenNote = lacking.size > 0
    ? `Hidden because a filter needs a figure they do not have: ${[...lacking.entries()].map(([why, n]) => `${fmtNum(n)} with ${why}`).join(", ")}.`
    : null;

  // The category's rule, with the thresholds and version the route sent (PRD §5.6).
  const catCount = catDef.ucat ? uni?.categories[catDef.ucat] : undefined;
  const catRule: ReactNode = cat === "all"
    ? <>Every scanner setup and every stock in a universe category, ranked by {rankBy === "score" ? "score" : "model rank"}.</>
    : cat === "watchlist" ? <>Your own list, with each stock’s scanner and universe figures where they exist.</>
      : cat === "chartink" ? <span data-testid="desk-scan-ck-rule">Stocks your enabled Chartink scans list that the AI scanner does not. They come from your own scan rules, so they have no AI score or probability and are not validated signals. Most hits first.</span>
        : catDef.bucket ? <>{bucketRule(catDef.bucket, rules)}</>
          : (
            <>
              {universeRule(catDef.ucat as UniverseCategory, rules)} Eligible universe only.
              {catCount && <> <span data-testid="desk-scan-cat-count">{fmtNum(catCount.total)} match{catCount.total > catCount.shown ? `; the top ${fmtNum(catCount.shown)} are listed` : ""}{catCount.missing ? `; ${fmtNum(catCount.missing)} could not be judged for missing figures` : ""}.</span></>}
              {cat === "fno" && <> <button type="button" data-testid="desk-scan-open-lab" onClick={() => openTab("fno")} style={{ ...linkBtn, color: "var(--mint)", textDecoration: "none" }}>Open the Options & futures lab ›</button></>}
            </>
          );

  const listPicker = cat === "watchlist" && (lists.data?.lists.length ?? 0) > 0 && (
    <label className="inline-flex items-center" style={{ gap: 6, fontSize: 12, color: "var(--cp-ink-3)" }}>
      List
      <select data-testid="desk-scan-list-pick" value={listId ?? ""} onChange={(e) => set({ list: e.target.value || null })} style={selectStyle}>
        {lists.data?.lists.map((l) => <option key={l.watchlist_id} value={l.watchlist_id}>{l.name}</option>)}
      </select>
    </label>
  );

  let body: ReactNode;
  const listProps: ListProps = { rows, selected: symbol, onOpen: openChart, head, plain, gate, uni, uniError, minCr, rules, signalDate: signalDateOf, fno };
  const emptyStyle: CSSProperties = { padding: "14px 18px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)", borderTop: mobile ? undefined : "1px solid var(--cp-line)" };
  if (cat === "watchlist" && (lists.isPending || (listId && listQ.isPending))) body = <div style={{ padding: 18 }}><LoadingBlock label="Loading your list" rows={2} /></div>;
  else if (cat === "watchlist" && (lists.isError || listQ.isError)) body = <div style={{ padding: 18 }}><ErrorBlock title="Your lists didn’t load" error={lists.error ?? listQ.error} onRetry={() => { lists.refetch(); listQ.refetch(); }} /></div>;
  else if (cat === "watchlist" && !listId) body = <div data-testid="desk-scan-cat-empty" style={emptyStyle}>You have no lists yet. Make one under Watchlist & alerts, then add stocks to it.</div>;
  else if (cat === "chartink" && ckBodyState(ck, openChartink)) body = ckBodyState(ck, openChartink);
  else if (catDef.ucat && uniError) body = <div data-testid="desk-scan-cat-error" style={{ padding: 18 }}><ErrorBlock title="This category needs the universe scan, which didn’t load" error={uniQ.error} onRetry={() => uniQ.refetch()} /></div>;
  else if (catDef.ucat && !uni) body = <div style={{ padding: 18 }}><LoadingBlock label="Loading the universe scan" rows={3} /></div>;
  else if (rows.length === 0) {
    body = (
      <div data-testid="desk-scan-cat-empty" style={emptyStyle}>
        {inCategory.length === 1 ? "The one stock in this category does not pass the filters."
            : inCategory.length > 1 ? `None of the ${fmtNum(inCategory.length)} stocks in this category passes the filters.`
            : cat === "chartink" ? (inCategory.length === 0 ? "None of your Chartink hits is outside the AI scan: there is nothing to list here." : "")
            : cat === "all" ? `No setups or universe matches on the ${dayLabel ?? "latest"} scan.`
              : catDef.bucket ? `No setup in this group on the ${dayLabel ?? "latest"} scan.`
                : cat === "watchlist" ? "This list has no stocks." : "No stock meets this rule on the latest scan."}
      </div>
    );
  } else if (cat === "chartink") body = <CkRows rows={rows} selected={symbol} onOpen={openChart} minCr={minCr} plain={plain} cards={mobile || asCards} />;
  else body = mobile ? <ScanCards {...listProps} phone /> : asCards ? <ScanCards {...listProps} phone={false} /> : <ScanTable {...listProps} />;

  const notes = (
    <>
      {data?.partial.map((p) => <span key={p} data-testid="desk-scan-partial" role="status" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>{PARTIAL_NOTE[p]}</span>)}
      {scan.isError && <span data-testid="desk-scan-setups-error" role="alert" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-danger)" }}>The scanner’s own setups (GET /api/positional/watchlist, /picks) didn’t load; only the universe categories are listed. <button type="button" onClick={() => scan.refetch()} style={linkBtn}>Retry</button></span>}
      {f.liquid && minCr != null && <span data-testid="desk-scan-liquid-note" role="status" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>Liquid only: average daily traded value (close × volume) over the last {fmtNum(rules?.liquidity?.sessions ?? null)} sessions of at least ₹{fmtNum(minCr)} Cr{rules?.version ? ` (${rules.version})` : ""}.</span>}
      {(ck.kind === "source_error" || ck.kind === "hits_error") && cat !== "chartink" && (
        <span data-testid="desk-scan-ck-note" role="status" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          Your Chartink scans didn’t load, so the AI scanner is shown alone. <button type="button" onClick={ck.retry} style={linkBtn}>Retry</button>
        </span>
      )}
      {hiddenNote && <span data-testid="desk-scan-hidden" role="status" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>{hiddenNote}</span>}
    </>
  );

  const filterBar = (
    <div data-testid="desk-scan-filters" className="flex min-w-0 flex-wrap items-center" style={{ gap: 8, padding: mobile ? 0 : "10px 18px", borderBottom: mobile ? undefined : "1px solid var(--cp-line)" }}>
      <button type="button" data-testid="desk-scan-filters-toggle" aria-expanded={panelOpen} onClick={() => setPanelOpen(!panelOpen)}
        style={{ padding: "5px 11px", borderRadius: 999, border: "1px solid var(--line-2)", background: panelOpen ? "var(--bg-3)" : "transparent", color: "var(--cp-ink-2)", fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)" }}>
        Filters{filterCount ? ` · ${filterCount}` : ""} {panelOpen ? "▴" : "▾"}
      </button>
      {activeFilters.map((d) => (
        <button key={d.key} type="button" data-testid={`desk-scan-fchip-${d.key}`} aria-label={`Clear ${filterChipText(d.key, f, minCr)}`} onClick={() => set({ [d.key]: null })}
          style={{ padding: "4px 10px", borderRadius: 999, border: "1px solid var(--mint-line)", background: "var(--mint-soft)", color: "var(--mint)", fontSize: 11.5, cursor: "pointer", fontFamily: "var(--sans)", whiteSpace: "nowrap" }}>
          {filterChipText(d.key, f, minCr)} ×
        </button>
      ))}
      <button type="button" data-testid="desk-scan-reset" disabled={!filterCount} onClick={() => set(Object.fromEntries(FILTER_KEYS.map((k) => [k, null])))}
        style={{ padding: 0, border: 0, background: "none", fontSize: 12, color: filterCount ? "var(--cp-ink)" : "var(--cp-ink-4)", cursor: filterCount ? "pointer" : "not-allowed", fontFamily: "var(--sans)", textDecoration: filterCount ? "underline" : undefined }}>
        Reset filters
      </button>
    </div>
  );

  const ruleLine = (
    <div data-testid="desk-scan-cat-rule" style={{ fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
      <span className="cp-eyebrow" style={{ fontSize: 9, marginRight: 8 }}>{plain ? catDef.plain : catDef.label} · rule</span>
      {catRule}
      {rules?.version && (catDef.bucket || catDef.ucat) && <span className="cp-mono-note" data-testid="desk-scan-rules-version"> · {rules.version}</span>}
    </div>
  );

  const odds = oddsQ.data;
  const runInfo = odds?.kind === "final" ? odds.data : null;
  const trust = (
    <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <TrustLine testId="desk-scan-trust" source="NSE end-of-day scanner · NIDP feature store" mode="eod" asOf={dayLabel} maker="rules"
        method={versions || null} status={scan.isError || uniError || (data?.partial.length ?? 0) > 0 ? "failed" : "ok"} />
      {data && (
        <span className="cp-mono-note" data-testid="desk-scan-basis" data-price-basis={data.scanBasis?.priceBasis ?? ""}
          data-quality={data.scanBasis?.dataQuality ?? ""} style={{ lineHeight: 1.6, overflowWrap: "anywhere" }}
          title={[data.scanBasis?.rawSymbols.length ? `On raw prices: ${data.scanBasis.rawSymbols.join(", ")}.` : "",
            data.scanBasis?.notScored?.length ? `Not scored after a price break: ${data.scanBasis.notScored.join(", ")}.` : ""].filter(Boolean).join(" ") || undefined}>
          {scanBasisLine(data.scanBasis, data.engineVersions)}
        </span>
      )}
      {ckHits && <ChartinkTrust hits={ckHits} testId="desk-scan-trust-ck" />}
      <TrustLine testId="desk-scan-trust-model" source="Move-odds model" mode="eod" asOf={runInfo ? fmtDay(runInfo.run.data_as_of) : null} maker="model"
        method={runInfo ? `Move-odds ${runInfo.run.model}${runInfo.record ? ` · out-of-sample ${runInfo.record.window_label}` : ""} · probability withheld, not marked calibrated` : gate.reason}
        status={oddsQ.isError ? "failed" : "ok"} />
    </span>
  );

  const footnote = (
    <span className="flex flex-col" style={{ gap: 6 }}>
      <span data-testid="desk-scan-footnote">
        {plain
          ? <>Score is a rules-based rank from the end-of-day scan, 0–100; it is not a chance of anything. {oddsLabel(head, plain)}: the chance the next trading day’s high gets {head === "p_up10_1d" ? "10" : "5"}% above the last close — one day only. It is held back because it is not marked as checked against real outcomes. Model rank: where the model puts the stock among eligible stocks. Past record: no track record per idea is published yet.</>
          : <>Score: the end-of-day scanner’s rules-based score, 0–100; it ranks setups and it is not a probability. {oddsLabel(head, plain)}: the move-odds model’s estimate that the next session’s high reaches the previous close plus {head === "p_up10_1d" ? "10" : "5"}%, one session only — withheld unless the route marks it calibrated. Model rank: that estimate’s percentile among eligible stocks. Hit rate · n: no per-setup back-tested record is published.</>}
        {" "}Entry, stop and target are hypothetical and never sent to a broker.
      </span>
      <span>Sources: NSE end-of-day scanner (GET /api/positional/watchlist, /picks) · NIDP feature store (GET /api/positional/scan-universe) · move-odds model (GET /api/move-odds/latest).</span>
      <UniverseNote uni={uni} uniError={uniError} onRetry={() => uniQ.refetch()} rules={rules} minCr={minCr} />
      <AboutModel odds={odds5Q.data} uni={uni} engineVersions={data?.engineVersions ?? []} classifier={data?.classifierVersion ?? null} rulesVersion={data?.rulesVersion ?? rules?.version ?? null} />
    </span>
  );

  const panel = panelOpen && <FilterPanel f={f} set={set} sectors={sectors} capReady={capReady} rules={rules} gateReason={gate.reason} phone={mobile} ckReady={ckHits != null} />;
  const pickCat = (c: CatKey) => set({ cat: c === "all" ? null : c });
  const pickRank = (v: RankBy) => set({ rank: v === "score" ? null : v });
  const pickLiquid = (v: boolean) => set({ liquid: v ? "1" : null });

  // ── phone (design-spec §11 M2; PRD §5.3 compact cards) ──
  if (mobile) {
    const confirmed = inCategory.filter((r) => r.s?.status === "confirmed").length;
    return (
      <div data-testid="desk-scanner" data-layout="phone" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
        <CategoryChips value={cat} onChange={pickCat} plain={plain} scroll />
        <span className="flex min-w-0 flex-wrap items-center justify-between" style={{ gap: 8 }}>
          <RankBySwitch value={rankBy} onChange={pickRank} ready={modelReady} plain={plain} small />
          <LiquidSwitch on={f.liquid} onChange={pickLiquid} minCr={minCr} phone />
        </span>
        {filterBar}
        {panel && <div className="cp-card" style={{ overflow: "hidden" }}>{panel}</div>}
        {listPicker}
        {ruleLine}
        {notes}
        <span data-testid="desk-scan-eyebrow" className="cp-eyebrow" style={{ fontSize: 9, color: "var(--cp-ink-4)" }}>NSE · end of day{dayLabel ? ` ${dayLabel}` : ""} · {shown}</span>
        <Widget id="scanner.opps.phone" title="Scanner opportunities" data={{ "aria-label": "Scanner opportunities" }} headPad="12px 14px">{body}</Widget>
        <Widget id="scanner.insights.phone" testId="desk-scan-insights" title="Scanner insights" headPad="12px 14px" bodyStyle={{ gap: 8, padding: 14 }}>
          <p className="m-0" style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
            {fmtNum(inCategory.length)} {plain ? "ideas" : "stocks"} in {plain ? catDef.plain : catDef.label} on the {dayLabel ?? "latest"} scan{confirmed ? `; ${fmtNum(confirmed)} confirmed ${confirmed === 1 ? "setup" : "setups"}` : ""}.
            {uni ? ` ${fmtNum(uni.universe.eligible)} of ${fmtNum(uni.universe.total)} stocks pass the eligibility gates.` : ""}
          </p>
          {trust}
          <details style={{ fontSize: 11, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            <summary data-testid="desk-scan-footnote-toggle" style={{ cursor: "pointer", color: "var(--cp-ink-2)" }}>How these figures are worked out</summary>
            <span style={{ display: "block", paddingTop: 6 }}>{footnote}</span>
          </details>
        </Widget>
      </div>
    );
  }

  // ── desk (design-spec §4) ──
  return (
    <Widget
      id="scanner.opps"
      testId="desk-scanner"
      data={{ "data-layout": "desk" }}
      num="02"
      title="AI Opportunity scanner"
      headTestId="desk-scan-title"
      meta={<span data-testid="desk-scan-eyebrow" style={{ ...eyebrow95 }}>NSE · end of day{dayLabel ? ` ${dayLabel}` : ""} · {shown}</span>}
      actions={
        <span data-testid="desk-scan-record" data-state={oddsQ.isError ? "error" : odds?.kind ?? "loading"} className="cp-eyebrow" style={{ ...eyebrow95, color: "var(--cp-ink-4)" }}>
          {runInfo ? `Move-odds ${runInfo.run.model}${runInfo.record ? ` · out-of-sample ${runInfo.record.window_label}` : ""}`
            : odds?.kind === "no_access" ? "Move-odds · not enabled for this account"
              : odds?.kind === "not_published" ? `Move-odds · not published for ${fmtDay(odds.expectedSession)}`
                : odds?.kind === "withheld" ? "Move-odds · run withheld"
                  : oddsQ.isError ? "Move-odds didn’t load" : "Move-odds · loading"}
        </span>
      }
    >
      <div style={{ padding: "10px 18px", borderBottom: "1px solid var(--cp-line)" }}>{trust}</div>

      <div data-testid="desk-scan-controls" className="flex flex-wrap items-center" style={{ gap: 12, padding: "12px 18px", borderBottom: "1px solid var(--cp-line)" }}>
        <RankBySwitch value={rankBy} onChange={pickRank} ready={modelReady} plain={plain} />
        <span aria-hidden style={{ width: 1, height: 20, background: "var(--line-2)" }} />
        <span style={{ flex: "1 1 360px", minWidth: 0 }}><CategoryChips value={cat} onChange={pickCat} plain={plain} scroll={false} /></span>
        <span style={{ marginLeft: "auto" }}><LiquidSwitch on={f.liquid} onChange={pickLiquid} minCr={minCr} /></span>
        <div className="flex flex-col" style={{ gap: 4, flexBasis: "100%" }}>
          {listPicker}
          {ruleLine}
          {notes}
        </div>
      </div>
      {filterBar}
      {panel}

      <div ref={setListBox}>{body}</div>

      <div className="flex flex-col" style={{ gap: 4, padding: "12px 18px", borderTop: "1px solid var(--cp-line)", fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
        {footnote}
      </div>
    </Widget>
  );
}
