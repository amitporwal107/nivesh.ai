/**
 * Smart trading desk — 05 AI Risk desk, beside the chart (design-spec §5), and
 * the phone's "05 · Trade scenario" card (§11 M4).
 *
 *   levels, reward / risk   the scanner setup (useDeskScanner: GET /api/positional/picks, else /watchlist)
 *   move probability        GET /api/move-odds/latest?head=p_up5_1d (useDeskOdds), else
 *                           GET /api/move-odds/stocks/{symbol} (useStockOdds) — a next-session estimate
 *   validation gate         the model's run, its out-of-sample record (in /latest), the stock's events on
 *                           record, and the scanner row's 20-session traded value (avg_traded_value_cr_20d).
 *                           These are model checks, not the historical validation of §7.6 (that is the
 *                           opportunity detail's section 8).
 *   trade scenario          GET /api/positional/scenario (useScenario): the one sizing rule, on the server
 *                           (PRD §8.5): per-share downside and upside, reward : risk, quantity under the risk
 *                           budget, the allocation cap, a maximum quantity and the lot size, gross exposure,
 *                           costs (strategy_engine model: 0.05% slippage + ₹20 brokerage per side, editable),
 *                           loss at the stop and profit at the target before and after costs. A read: it stores
 *                           nothing and sends nothing to a broker.
 *   your portfolio (§8.6)   GET /api/portfolio/holdings-enriched (useHoldingsEnriched): the stock and its sector
 *                           already held, related holdings; the scenario route adds the weights after the buy
 *                           and the impact at the stop and the target on the portfolio's value
 *   last close, gap risk    the chart's daily bars (GET /api/research/chart-live/{symbol}/ohlcv, end of day)
 *   Add to paper trades     POST /api/desk/paper-trades { symbol, quantity (the scenario's), entry_price,
 *                           stop_price, target_price, source: { kind: "scanner", bucket, signal_date } }
 *   Alert on trigger        POST /api/desk/alerts { symbol, condition: "above", level: the trigger, else the entry }
 *
 * Shown as "—" with the reason, because no route publishes them: a trade win rate for the setup (entry-to-target
 * before the stop, back-tested), and the correlation of a new position with the holdings. A gate check whose
 * source is missing shows "—" and does not count as passed.
 *
 * The two buttons are the only writes: a paper trade is simulated (marked against end-of-day closes; no order is
 * placed) and an alert is checked after each close. Both lists are on the Portfolio & risk tab. Nivesh does not
 * place orders.
 */
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { useDebounce } from "@/hooks/use-debounce";
import { useHoldingsEnriched } from "@/hooks/use-portfolio";
import { StockName } from "../../components/EntityIcon";
import { Btn, ErrorBlock, Pill, TONE_COLOR, fmtINR, fmtNum, fmtPct, type Tone } from "../../components/ui";
import { fmtDay, fmtPrice } from "../trading/parts";
import { setupLabel, useDeskLevels, useScenario, useStockOdds, type DeskLevels, type Scenario, type ScenarioInputs } from "./chart-data";
import { useDesk } from "./context";
import { LIQUID_MIN_CR, PROBABILITY_WITHHELD, modelEvidence, probabilityGate, useDeskOdds, useDeskScanner, type DeskSetup, type SetupStatus } from "./desk-data";
import { useAddAlert, useAddPaperTrade, writeProblem, type NewAlert, type NewPaperTrade } from "./desk-trading";
import { largestGap, type DailyBar } from "./indicators";
import { TrustLine } from "./trust";

const CAPITALS = [
  { value: "200000", label: "₹2L", id: "2l" },
  { value: "500000", label: "₹5L", id: "5l" },
  { value: "1000000", label: "₹10L", id: "10l" },
] as const;

/** Risk per trade, percent of capital. */
const RISKS = [
  { value: "0.5", label: "0.5%", id: "0-5" },
  { value: "1", label: "1%", id: "1" },
  { value: "2", label: "2%", id: "2" },
] as const;

const DEFAULT_CAPITAL = "500000";
const DEFAULT_RISK_PCT = "1";
/** The largest share of capital in one stock the calculator allows by default, percent. */
const DEFAULT_MAX_ALLOC = "25";
/** strategy_engine cost model defaults (backend/services/strategy_engine/backtest.py): the route uses the same. */
const DEFAULT_SLIPPAGE = "0.05";
const DEFAULT_BROKERAGE = "20";

/** Sessions the gap-risk check looks back over (about 3 months). */
const GAP_SESSIONS = 63;

const STOP_NOTE = "A stop does not guarantee the exit price: a gap or thin trading can fill the exit beyond the stop, so the loss can be larger than shown.";

const pct1 = (p: number | null | undefined) => (p == null ? "—" : fmtPct(p * 100, { digits: 1 }));
const crText = (cr: number) => `₹${fmtNum(cr, cr >= 100 ? 0 : 1)} Cr`;
const rrText = (rr: number | null) => (rr != null ? `${fmtNum(rr, 1)} : 1` : "—");
/** A number with at most two decimals and no trailing zeros ("1", "0.5", "0.05"). */
const plainNum = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(v));

/** The risk desk's status words (the design says "Awaiting confirmation" here). */
export const RISK_STATUS: Record<SetupStatus, { label: string; tone: Tone }> = {
  confirmed: { label: "Confirmed", tone: "mint" },
  awaiting: { label: "Awaiting confirmation", tone: "amber" },
  forming: { label: "Forming", tone: "ink" },
};

// ── primitives shared with the Chart tab ─────────────────────────────────

/** Segmented control (design-spec §1): a pill track with mono items; ON is bg-4 and ink. */
export function Segmented<T extends string | number>({ label, value, options, onChange, idPrefix, small }: {
  label: string;
  value: T;
  options: ReadonlyArray<{ value: T; label: ReactNode; id: string; disabled?: boolean; title?: string }>;
  onChange: (v: T) => void;
  idPrefix: string;
  small?: boolean;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex max-w-full flex-wrap"
      style={{ gap: 2, padding: small ? 2 : 3, borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}
    >
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.id}
            type="button"
            aria-pressed={on}
            disabled={o.disabled}
            title={o.title}
            data-testid={`${idPrefix}-${o.id}`}
            onClick={() => onChange(o.value)}
            style={{
              padding: small ? "5px 10px" : "6px 12px", borderRadius: 999, border: 0, whiteSpace: "nowrap",
              fontFamily: "var(--mono)", fontSize: small ? 9.5 : 10.5, letterSpacing: "0.08em",
              cursor: o.disabled ? "not-allowed" : "pointer", opacity: o.disabled ? 0.45 : 1,
              background: on ? "var(--bg-4)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** A module card's header bar (design-spec §1): "<mint>NN</mint> · Title" on bg-0, anything else pushed right. */
export function CardHead({ num, title, children, padding = "13px 18px", testId }: { num: string; title: string; children?: ReactNode; padding?: string; testId?: string }) {
  return (
    <div
      className="flex flex-wrap items-center"
      style={{ gap: "8px 12px", padding, borderBottom: "1px solid var(--cp-line)", background: "var(--bg-0)", borderRadius: "14px 14px 0 0" }}
    >
      <span data-testid={testId} className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}>
        <span style={{ color: "var(--mint)" }}>{num}</span> · {title}
      </span>
      {children != null && <div className="flex flex-wrap items-center" style={{ gap: 8, marginLeft: "auto" }}>{children}</div>}
    </div>
  );
}

/** Stat tile (design-spec §1): eyebrow, serif value, short sub line. */
function StatTile({ k, v, s, tone = "ink", size = 22, testId, subTestId }: { k: string; v: ReactNode; s?: ReactNode; tone?: Tone; size?: number; testId: string; subTestId?: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 4, padding: "11px 12px", borderRadius: 10, border: "1px solid var(--cp-line)", background: "var(--bg-2)" }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{k}</span>
      <span data-testid={testId} style={{ fontFamily: "var(--display)", fontSize: size, lineHeight: 1.05, letterSpacing: "-0.02em", color: TONE_COLOR[tone], fontVariantNumeric: "tabular-nums" }}>{v}</span>
      {s != null && <span data-testid={subTestId ?? `${testId}-note`} style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{s}</span>}
    </div>
  );
}

// ── the model's figures and the validation gate ──────────────────────────

export interface GateCheck {
  key: "published" | "record" | "edge" | "events" | "liquidity";
  label: string;
  value: string;
  /** null: no source to judge it, shown "—" and not counted. */
  ok: boolean | null;
}

/** P(+5% next session) for the stock, the model's record, and the five gate checks — all from real reads. */
function useRiskFigures(symbol: string, setup: DeskSetup | null) {
  const { persona } = useDesk();
  const plain = persona === "investor";
  const oddsQ = useDeskOdds("p_up5_1d");
  const stockQ = useStockOdds(symbol);
  const odds = oddsQ.data;
  const stock = stockQ.data;
  const sym = symbol.toUpperCase();
  const fromLatest = odds?.kind === "final" ? odds.bySymbol.get(sym) ?? null : null;
  const stockData = stock?.kind === "ok" ? stock.data : null;
  const p = fromLatest?.p ?? stockData?.estimates.p_up5_1d ?? null;
  const events = fromLatest?.events ?? (stockData ? stockData.events.length : null);
  const run = odds?.kind === "final" ? odds.data.run : stockData?.run ?? null;
  const record = odds?.kind === "final" ? odds.data.record : null;
  const locked = odds?.kind === "no_access" || stock?.kind === "locked";
  const withheld = odds?.kind === "withheld" ? odds.reason : stock?.kind === "withheld" ? stock.reason : null;
  const loading = oddsQ.isPending || stockQ.isPending;

  // A check is judged only when its source answered; otherwise it is "—" and not counted.
  // A run that is not out yet is "not applicable", not a failed check: it says nothing about this stock's setup.
  const publishedOk: boolean | null = run ? true : withheld ? false : null;
  const checks: GateCheck[] = [
    {
      key: "published",
      label: plain ? "Model ran for the next day" : "Model run for the next session",
      value: run ? fmtDay(run.target_session) : odds?.kind === "not_published" ? "Not published yet" : withheld ? "Withheld" : "—",
      ok: publishedOk,
    },
    {
      key: "record",
      label: plain ? "Tested on past data" : "Out-of-sample record",
      value: record ? `${fmtNum(record.sessions)} sessions` : "—",
      ok: odds?.kind === "final" ? record != null : null,
    },
    {
      key: "edge",
      label: plain ? "Beat the average stock" : "Top-10 hit rate above base rate",
      value: record ? `${pct1(record.top10_hit_rate)} vs ${pct1(record.base_rate)}` : "—",
      ok: record ? record.top10_hit_rate > record.base_rate : null,
    },
    {
      key: "events",
      label: plain ? `News or filings on record · ${sym}` : `Events on record · ${sym}`,
      value: events == null ? "—" : fmtNum(events),
      ok: events == null ? null : events > 0,
    },
    {
      key: "liquidity",
      label: plain ? `Easy to trade · ₹${LIQUID_MIN_CR} Cr+ a day` : `Liquidity · ADV ≥ ₹${LIQUID_MIN_CR} Cr`,
      value: setup?.avgTradedCr != null ? `${crText(setup.avgTradedCr)} a day` : "—",
      ok: setup?.avgTradedCr != null ? setup.avgTradedCr >= LIQUID_MIN_CR : null,
    },
  ];
  const passed = checks.filter((c) => c.ok === true).length;
  const allPassed = passed === checks.length;

  // ── move probability ──
  let pValue = "—";
  let pNote: ReactNode;
  let pTone: Tone = "ink";
  const head = plain ? "Chance of +5% next day" : "P(+5% next session)";
  if (p != null) {
    // The one probability gate (desk-data.ts): the estimate is not marked calibrated, so the number is never printed,
    // whatever the five checks say. The checks still run, and the model's version, run date and record stay on screen.
    const gate = probabilityGate(odds, plain, stock?.kind === "ok");
    const evidence = modelEvidence(run, record, plain);
    pValue = PROBABILITY_WITHHELD;
    pNote = <>{head} · {gate.reason}{evidence ? <> Evidence, not a probability: {evidence}.</> : null} {passed} of {checks.length} gate checks passed.</>;
  } else if (locked) {
    pNote = "Move probabilities are not enabled for this account.";
  } else if (withheld) {
    pNote = <>Withheld: {withheld}.</>;
  } else if (odds?.kind === "not_published") {
    pNote = <>The model has not published for {fmtDay(odds.expectedSession)} yet.</>;
  } else if (loading) {
    pValue = "…";
    pNote = "Loading the move-odds model.";
  } else if (oddsQ.isError && stockQ.isError) {
    pNote = "The move-odds model didn’t load.";
  } else {
    pNote = `No estimate for ${sym} in the published run.`;
  }

  return { plain, p, pValue, pNote, pTone, record, run, checks, passed, allPassed, locked };
}

// ── your portfolio and this idea (PRD §8.6) ──────────────────────────────

interface Related { symbol: string; name: string; valueRs: number | null; weightPct: number | null }

interface PortfolioIdea {
  state: "loading" | "error" | "empty" | "ok";
  error?: unknown;
  retry?: () => void;
  totalValue: number | null;
  /** This stock, summed across accounts. */
  existingValue: number | null;
  existingWeightPct: number | null;
  sector: string | null;
  /** Direct stocks in the same sector (this one included); funds are not looked through. */
  sectorValue: number | null;
  sectorWeightPct: number | null;
  related: Related[];
  stockCount: number;
}

const isStockHolding = (t: string) => {
  const x = t.trim().toLowerCase();
  return x === "equity" || x === "stock";
};

/** The stock and its sector in the user's holdings (GET /api/portfolio/holdings-enriched). Missing figures stay null. */
function usePortfolioIdea(symbol: string, sector: string | null): PortfolioIdea {
  const q = useHoldingsEnriched();
  return useMemo(() => {
    const blank = { totalValue: null, existingValue: null, existingWeightPct: null, sector, sectorValue: null, sectorWeightPct: null, related: [], stockCount: 0 };
    if (q.isPending) return { state: "loading", ...blank };
    if (q.isError || !q.data) return { state: "error", error: q.error, retry: () => q.refetch(), ...blank };
    const d = q.data;
    const total = d.totals?.value_rs ?? null;
    if (!d.holdings.length || total == null || !(total > 0)) return { state: "empty", ...blank };
    const sym = symbol.toUpperCase();
    const stocks = d.holdings.filter((h) => isStockHolding(h.asset_type));
    const mine = stocks.filter((h) => (h.nse_symbol ?? "").toUpperCase() === sym);
    const existing = mine.reduce((s, h) => s + (h.value_rs ?? 0), 0);
    const sec = sector?.trim().toLowerCase() || null;
    const inSector = sec ? stocks.filter((h) => (h.sector ?? "").trim().toLowerCase() === sec) : [];
    const sectorValue = sec ? inSector.reduce((s, h) => s + (h.value_rs ?? 0), 0) : null;
    const related = inSector
      .filter((h) => (h.nse_symbol ?? "").toUpperCase() !== sym)
      .map((h) => ({ symbol: (h.nse_symbol ?? h.name).toUpperCase(), name: h.name, valueRs: h.value_rs ?? null, weightPct: h.weight_pct ?? null }))
      .sort((a, b) => (b.valueRs ?? -1) - (a.valueRs ?? -1));
    return {
      state: "ok",
      totalValue: total,
      existingValue: existing,
      existingWeightPct: (existing / total) * 100,
      sector,
      sectorValue,
      sectorWeightPct: sectorValue != null ? (sectorValue / total) * 100 : null,
      related,
      stockCount: stocks.length,
    };
  }, [q.isPending, q.isError, q.data, q.error, symbol, sector]); // eslint-disable-line react-hooks/exhaustive-deps
}

// ── the trade scenario: inputs, the server's answer ──────────────────────

interface Fields {
  entry: string; stop: string; target: string;
  capital: string; riskPct: string; maxAllocPct: string;
  slippagePct: string; brokerage: string; maxQty: string; lotSize: string;
}
type FieldKey = keyof Fields;

const priceText = (v: number | null) => (v != null ? String(v) : "");

function levelFields(lv: DeskLevels): Pick<Fields, "entry" | "stop" | "target"> {
  return { entry: priceText(lv.entry), stop: priceText(lv.stop), target: priceText(lv.target) };
}

/** A typed number: null when blank, NaN when not a number (shown as an input problem). */
function parseField(s: string): number | null {
  const t = s.replace(/[,₹\s]/g, "");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : Number.NaN;
}

interface InputProblem { field: FieldKey; message: string; /** The field is empty (not mistyped). */ blank?: boolean }

/** The inputs as numbers, and what is wrong with their FORMAT. Price direction is the route's to judge. */
function readFields(f: Fields): { inputs: Omit<ScenarioInputs, "portfolioValue" | "existingValue" | "sectorValue"> | null; problems: InputProblem[] } {
  const problems: InputProblem[] = [];
  const pos = (k: FieldKey, label: string, required: boolean) => {
    const n = parseField(f[k]);
    if (n == null) {
      if (required) problems.push({ field: k, message: `Enter ${label}.`, blank: true });
      return null;
    }
    if (!(n > 0)) {
      problems.push({ field: k, message: `${label[0].toUpperCase()}${label.slice(1)} must be a number above zero.` });
      return null;
    }
    return n;
  };
  const entry = pos("entry", "an entry price", true);
  const stop = pos("stop", "a stop price", true);
  const target = pos("target", "the target", false);
  const capital = pos("capital", "the capital", true);
  const riskPct = pos("riskPct", "the risk per trade", true);
  const maxAlloc = pos("maxAllocPct", "the maximum allocation", true);
  const slip = parseField(f.slippagePct);
  if (slip != null && !(slip >= 0 && slip <= 5)) problems.push({ field: "slippagePct", message: "Slippage must be between 0% and 5% a side." });
  const brk = parseField(f.brokerage);
  if (brk != null && !(brk >= 0)) problems.push({ field: "brokerage", message: "Brokerage must be zero or more." });
  const maxQty = pos("maxQty", "the maximum quantity", false);
  const lot = pos("lotSize", "the lot size", false);
  if (riskPct != null && riskPct > 100) problems.push({ field: "riskPct", message: "Risk per trade cannot be above 100%." });
  if (maxAlloc != null && maxAlloc > 100) problems.push({ field: "maxAllocPct", message: "The maximum allocation cannot be above 100%." });
  if (maxQty != null && !Number.isInteger(maxQty)) problems.push({ field: "maxQty", message: "The maximum quantity is a whole number of shares." });
  if (lot != null && !Number.isInteger(lot)) problems.push({ field: "lotSize", message: "The lot size is a whole number of shares." });
  if (problems.length || entry == null || stop == null || capital == null || riskPct == null || maxAlloc == null) return { inputs: null, problems };
  return {
    inputs: {
      entry, stop, target, capital, riskPct, maxAllocPct: maxAlloc,
      slippagePct: slip ?? Number(DEFAULT_SLIPPAGE), brokeragePerSide: brk ?? Number(DEFAULT_BROKERAGE),
      maxQty, lotSize: lot ?? 1,
    },
    problems,
  };
}

/** One scenario per stock: editable fields (levels from the setup), the portfolio, and the route's answer. */
function useScenarioState(symbol: string, setup: DeskSetup | null, lv: DeskLevels) {
  const [fields, setFields] = useState<Fields>(() => ({
    ...levelFields(lv), capital: DEFAULT_CAPITAL, riskPct: DEFAULT_RISK_PCT, maxAllocPct: DEFAULT_MAX_ALLOC,
    slippagePct: DEFAULT_SLIPPAGE, brokerage: DEFAULT_BROKERAGE, maxQty: "", lotSize: "1",
  }));
  // A new stock (or new levels for it) starts from its own levels; the sizing choices carry over.
  const levelKey = `${symbol}|${lv.source ?? ""}|${lv.entry ?? ""}|${lv.stop ?? ""}|${lv.target ?? ""}`;
  useEffect(() => {
    setFields((f) => ({ ...f, ...levelFields(lv) }));
  }, [levelKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: FieldKey, v: string) => setFields((f) => ({ ...f, [k]: v }));
  const reset = () => setFields((f) => ({ ...f, ...levelFields(lv) }));

  const portfolio = usePortfolioIdea(symbol, setup?.sector ?? null);
  const read = readFields(fields);
  const withPortfolio: ScenarioInputs | null = read.inputs
    ? {
        ...read.inputs,
        portfolioValue: portfolio.state === "ok" ? portfolio.totalValue : null,
        existingValue: portfolio.state === "ok" ? portfolio.existingValue : null,
        sectorValue: portfolio.state === "ok" ? portfolio.sectorValue : null,
      }
    : null;
  // Typing is debounced; the previous answer stays until the new one arrives.
  const key = useDebounce(withPortfolio ? JSON.stringify(withPortfolio) : "", 300);
  const debounced = useMemo<ScenarioInputs | null>(() => (key ? (JSON.parse(key) as ScenarioInputs) : null), [key]);
  const q = useScenario(debounced);
  const current = !!debounced && !!withPortfolio && JSON.stringify(withPortfolio) === key && !q.isPlaceholderData;
  return { fields, set, reset, read, portfolio, q, sent: debounced, current, levels: lv };
}

type ScenarioState = ReturnType<typeof useScenarioState>;

const BINDING: Record<string, string> = {
  risk_budget: "the risk budget",
  max_allocation: "the maximum allocation",
  max_qty: "the maximum quantity",
  lot_size: "the lot size",
};

function ScenarioField({ k, label, value, onChange, suffix, problem, hint }: {
  k: FieldKey; label: string; value: string; onChange: (v: string) => void; suffix?: string; problem?: string; hint?: string;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <span className="cp-eyebrow" style={{ fontSize: 9 }}>{label}</span>
      <span className="flex items-center" style={{ gap: 4, padding: "6px 9px", borderRadius: 9, border: `1px solid ${problem ? "var(--danger-line)" : "var(--line-2)"}`, background: "var(--bg-2)" }}>
        <input
          id={id}
          data-testid={`desk-scn-${k}`}
          inputMode="decimal"
          value={value}
          aria-invalid={!!problem}
          title={hint}
          onChange={(e) => onChange(e.target.value)}
          style={{ minWidth: 0, width: "100%", border: 0, outline: "none", background: "transparent", color: "var(--cp-ink)", fontFamily: "var(--mono)", fontSize: 12 }}
        />
        {suffix && <span className="cp-mono-note" style={{ fontSize: 9.5 }}>{suffix}</span>}
      </span>
    </label>
  );
}

/** Every input of PRD §8.5, editable, with the route's full answer under it. */
function ScenarioEditor({ st, setup }: { st: ScenarioState; setup: DeskSetup | null }) {
  const { persona } = useDesk();
  const plain = persona === "investor";
  const s = st.q.data ?? null;
  const fieldProblem = (k: FieldKey) =>
    st.read.problems.find((p) => p.field === k)?.message ?? (st.current && s ? s.problems.find((p) => p.field === k)?.message : undefined);
  const f = st.fields;
  const base = st.levels;
  const levelsEdited = base.source && (f.entry !== priceText(base.entry) || f.stop !== priceText(base.stop) || f.target !== priceText(base.target));
  const grid = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 112px), 1fr))", gap: 8 } as const;
  const serverProblems = st.current && s && !s.valid ? s.problems : [];
  return (
    <div data-testid="desk-scn-editor" className="flex flex-col" style={{ gap: 10 }}>
      <div style={grid}>
        <ScenarioField k="entry" label={plain ? "Buy at ₹" : "Entry ₹"} value={f.entry} onChange={(v) => st.set("entry", v)} problem={fieldProblem("entry")} />
        <ScenarioField k="stop" label={plain ? "Exit if wrong ₹" : "Stop ₹"} value={f.stop} onChange={(v) => st.set("stop", v)} problem={fieldProblem("stop")} />
        <ScenarioField k="target" label="Target ₹" value={f.target} onChange={(v) => st.set("target", v)} problem={fieldProblem("target")} hint="Optional" />
      </div>
      <div style={grid}>
        <ScenarioField k="capital" label={plain ? "Money you have ₹" : "Capital ₹"} value={f.capital} onChange={(v) => st.set("capital", v)} problem={fieldProblem("capital") ?? fieldProblem("risk" as FieldKey)} />
        <ScenarioField k="riskPct" label={plain ? "Willing to lose" : "Risk per trade"} value={f.riskPct} suffix="%" onChange={(v) => st.set("riskPct", v)} problem={fieldProblem("riskPct")} />
        <ScenarioField k="maxAllocPct" label={plain ? "Most in one stock" : "Max allocation"} value={f.maxAllocPct} suffix="%" onChange={(v) => st.set("maxAllocPct", v)} problem={fieldProblem("maxAllocPct")} />
      </div>
      <div style={grid}>
        <ScenarioField k="slippagePct" label="Slippage a side" value={f.slippagePct} suffix="%" onChange={(v) => st.set("slippagePct", v)} problem={fieldProblem("slippagePct")} />
        <ScenarioField k="brokerage" label="Brokerage a side ₹" value={f.brokerage} onChange={(v) => st.set("brokerage", v)} problem={fieldProblem("brokerage")} />
        <ScenarioField k="maxQty" label="Max shares" value={f.maxQty} onChange={(v) => st.set("maxQty", v)} problem={fieldProblem("maxQty")} hint="Optional" />
        <ScenarioField k="lotSize" label="Lot size" value={f.lotSize} onChange={(v) => st.set("lotSize", v)} problem={fieldProblem("lotSize")} />
      </div>
      {levelsEdited && (
        <button type="button" data-testid="desk-scn-reset" onClick={st.reset} style={{ alignSelf: "flex-start", padding: 0, border: 0, background: "none", color: "var(--mint)", fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)" }}>
          {base.source === "rule" ? "Back to the rule’s levels" : "Back to the scanner’s levels"}
        </button>
      )}
      {(st.read.problems.length > 0 || serverProblems.length > 0) && (
        <ul data-testid="desk-scn-problems" role="alert" className="m-0 flex flex-col" style={{ padding: "8px 10px", listStyle: "none", gap: 3, borderRadius: 10, border: "1px solid var(--danger-line)", background: "var(--cp-danger-soft)" }}>
          {[...st.read.problems.map((p) => ({ key: `in-${p.field}`, message: p.message })), ...serverProblems.map((p) => ({ key: `srv-${p.code}`, message: p.message }))].map((p) => (
            <li key={p.key} data-testid={`desk-scn-problem-${p.key}`} style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-2)" }}>{p.message}</li>
          ))}
        </ul>
      )}
      <ScenarioOutputs st={st} />
    </div>
  );
}

function OutRow({ k, v, sub, testId }: { k: string; v: ReactNode; sub?: ReactNode; testId: string }) {
  return (
    <li data-testid={testId} className="flex flex-wrap items-baseline" style={{ gap: "2px 12px", padding: "5px 0", borderTop: "1px solid var(--cp-line)", fontSize: 12.5 }}>
      <span style={{ flex: "1 1 150px", minWidth: 0, color: "var(--cp-ink-2)" }}>{k}</span>
      <span data-testid={`${testId}-v`} className="cp-num" style={{ color: "var(--cp-ink)" }}>{v}</span>
      {sub && <span style={{ flexBasis: "100%", fontSize: 11, color: "var(--cp-ink-3)" }}>{sub}</span>}
    </li>
  );
}

function ScenarioOutputs({ st }: { st: ScenarioState }) {
  const s = st.q.data ?? null;
  if (st.q.isError) return <ErrorBlock title="The scenario didn’t compute" error={st.q.error} onRetry={() => st.q.refetch()} />;
  if (!s) return st.sent ? <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>Working it out…</span> : null;
  if (!s.valid) return null;
  const ps = s.per_share;
  const z = s.sizing;
  const c = s.costs;
  const o = s.outcomes;
  return (
    <ul data-testid="desk-scn-out" data-current={st.current} className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none", opacity: st.current ? 1 : 0.6 }}>
      <OutRow testId="desk-scn-out-down" k="Downside a share (entry − stop)" v={fmtPrice(ps?.risk ?? null)} />
      <OutRow testId="desk-scn-out-up" k="Upside a share (target − entry)" v={fmtPrice(ps?.reward ?? null)} sub={ps?.reward == null ? "No target entered." : undefined} />
      <OutRow testId="desk-scn-out-rr" k="Reward : risk" v={rrText(ps?.reward_to_risk ?? null)} />
      <OutRow testId="desk-scn-out-qty" k="Illustrative quantity" v={z ? `${fmtNum(z.quantity)} shares` : "—"} sub={z ? `Limited by ${BINDING[z.binding] ?? z.binding}: risk budget ${fmtINR(z.risk_budget)} → ${fmtNum(z.qty_by_risk)} shares${z.qty_by_allocation != null ? `; ${fmtNum(z.max_alloc_pct)}% cap → ${fmtNum(z.qty_by_allocation)}` : ""}${z.qty_by_max != null ? `; max ${fmtNum(z.qty_by_max)}` : ""}${z.lot_size > 1 ? `; lots of ${fmtNum(z.lot_size)}` : ""}.` : undefined} />
      <OutRow testId="desk-scn-out-gross" k="Gross exposure" v={z ? fmtINR(z.gross_exposure) : "—"} sub={z?.allocation_pct != null ? `${fmtPct(z.allocation_pct, { digits: 1 })} of capital` : undefined} />
      <OutRow testId="desk-scn-out-costs" k="Estimated costs · round trip" v={c ? `${fmtINR(c.round_trip_at_stop)} at the stop · ${c.round_trip_at_target != null ? `${fmtINR(c.round_trip_at_target)} at the target` : "no target"}` : "—"}
        sub={`${plainNum(s.cost_model.slippage_pct_per_side)}% slippage + ₹${fmtNum(s.cost_model.brokerage_inr_per_side)} brokerage a side (strategy_engine cost model); taxes not included.`} />
      <OutRow testId="desk-scn-out-loss" k="Loss at the stop" v={o ? `−${fmtINR(o.loss_at_stop_net)} after costs` : "—"} sub={o ? `−${fmtINR(o.loss_at_stop)} before costs` : undefined} />
      <OutRow testId="desk-scn-out-profit" k="Profit at the target" v={o?.profit_at_target_net != null ? `${fmtINR(o.profit_at_target_net, { signed: true })} after costs` : "—"} sub={o?.profit_at_target != null ? `${fmtINR(o.profit_at_target, { signed: true })} before costs` : "No target entered."} />
      {s.warnings.map((w) => <li key={w.code} data-testid={`desk-scn-warn-${w.code}`} style={{ fontSize: 12, color: "var(--amber)", paddingTop: 4 }}>{w.message}</li>)}
    </ul>
  );
}

// ── range bar ────────────────────────────────────────────────────────────

/**
 * Stop → entry (red, flex 1) and entry → target (green, flex = reward ÷ risk), with the last close marked at its
 * price. Without a target only the red part is drawn.
 */
function RangeBar({ entry, stop, target, ltp, plain }: { entry: number; stop: number; target: number | null; ltp: number | null; plain: boolean }) {
  const rr = target != null && target > entry ? (target - entry) / (entry - stop) : null;
  const red = rr != null ? 1 / (1 + rr) : 1;
  let at: number | null = null;
  if (ltp != null) {
    if (ltp <= entry) at = Math.max(0, ((ltp - stop) / (entry - stop)) * red);
    else if (rr != null && target != null) at = Math.min(1, red + ((ltp - entry) / (target - entry)) * (1 - red));
    else at = 1;
  }
  const where = ltp == null ? "" : ltp < stop ? " · below the stop" : target != null && ltp > target ? " · above the target" : target == null && ltp > entry ? " · above the entry" : "";
  return (
    <div data-testid="desk-risk-bar" className="flex flex-col" style={{ gap: 8 }}>
      <div style={{ position: "relative", paddingTop: ltp != null ? 16 : 0 }}>
        <div className="flex" style={{ height: 10, borderRadius: 999, overflow: "hidden", gap: 2 }}>
          <div title="Risk: entry to stop" style={{ flex: 1, background: "var(--cp-danger-soft)", border: "1px solid var(--danger-line)", borderRadius: rr != null ? "999px 0 0 999px" : 999 }} />
          {rr != null && <div title="Reward: entry to target" style={{ flex: rr, background: "var(--mint-soft)", border: "1px solid var(--mint-line)", borderRadius: "0 999px 999px 0" }} />}
        </div>
        {ltp != null && at != null && (
          <div
            data-testid="desk-risk-ltp"
            data-at={at.toFixed(4)}
            title={`Last close ${fmtPrice(ltp)}${where}`}
            style={{ position: "absolute", top: 0, left: `${at * 100}%`, transform: "translateX(-1px)", display: "flex", flexDirection: "column", alignItems: at > 0.75 ? "flex-end" : "flex-start" }}
          >
            <span className="cp-num" style={{ position: "absolute", top: -1, [at > 0.75 ? "right" : "left"]: 5, fontSize: 9.5, lineHeight: 1.2, whiteSpace: "nowrap", color: "var(--cp-ink)" }}>
              Close {fmtPrice(ltp)}{where}
            </span>
            <span style={{ position: "absolute", top: 12, left: 0, width: 2, height: 18, background: "var(--cp-ink)" }} />
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-baseline" style={{ gap: "2px 12px" }}>
        <span data-testid="desk-risk-stop" className="cp-eyebrow" style={{ fontSize: 9.5, color: "var(--cp-danger)" }}>{plain ? "Exit if wrong" : "Stop"} {fmtPrice(stop)}</span>
        <span data-testid="desk-risk-entry" className="cp-eyebrow" style={{ fontSize: 9.5, color: "var(--cp-ink-2)" }}>{plain ? "Buy above" : "Entry"} {fmtPrice(entry)}</span>
        <span data-testid="desk-risk-target" className="cp-eyebrow" style={{ fontSize: 9.5, marginLeft: "auto", color: target != null ? "var(--mint)" : "var(--cp-ink-4)" }}>
          {target != null ? `Target ${fmtPrice(target)}` : "No target"}
        </span>
      </div>
    </div>
  );
}

// ── checks ───────────────────────────────────────────────────────────────

interface RiskCheck { key: string; label: string; text: ReactNode; tone: Tone | "na" }

function riskChecks(st: ScenarioState, setup: DeskSetup | null, bars: DailyBar[] | null, plain: boolean): RiskCheck[] {
  const s = st.current && st.q.data?.valid ? st.q.data : null;
  const z = s?.sizing ?? null;
  const o = s?.outcomes ?? null;
  const pf = s?.portfolio ?? null;
  const capital = st.sent?.capital ?? null;
  const out: RiskCheck[] = [];
  out.push(z && o
    ? { key: "size", label: plain ? "Size" : "Position size", tone: "mint", text: <>{fmtINR(z.risk_budget)} at risk ({plainNum(st.sent?.riskPct)}% of {fmtINR(capital)}); {plain ? "if wrong you lose" : "max loss"} {fmtINR(o.loss_at_stop_net)} at the {plain ? "exit" : "stop"} after costs.</> }
    : { key: "size", label: plain ? "Size" : "Position size", tone: "na", text: z ? "— The risk budget fits no whole share." : "— Needs an entry with a stop below it, a capital and a risk per trade." });
  if (pf && z && z.quantity > 0) {
    const limit = z.max_alloc_pct;
    const over = pf.stock_weight_after_pct > limit;
    out.push({
      key: "concentration", label: plain ? "One-stock share" : "Concentration", tone: over ? "amber" : "mint",
      text: <>{fmtPct(pf.stock_weight_after_pct, { digits: 1 })} of your portfolio after the buy ({fmtPct(pf.stock_weight_before_pct, { digits: 1 })} now){over ? `, above the ${fmtNum(limit)}% limit` : `, within the ${fmtNum(limit)}% limit`}.</>,
    });
  } else if (z && z.quantity > 0 && z.allocation_pct != null) {
    const capped = z.binding === "max_allocation";
    out.push({
      key: "concentration", label: plain ? "One-stock share" : "Concentration", tone: capped ? "amber" : "mint",
      text: capped
        ? <>The {fmtNum(z.max_alloc_pct)}% single-stock limit caps it at {fmtNum(z.quantity)} shares ({fmtPct(z.allocation_pct, { digits: 1 })} of capital); the risk budget alone would buy {fmtNum(z.qty_by_risk)}.</>
        : <>{fmtPct(z.allocation_pct, { digits: 1 })} of capital, within the {fmtNum(z.max_alloc_pct)}% single-stock limit.</>,
    });
  } else {
    out.push({ key: "concentration", label: plain ? "One-stock share" : "Concentration", tone: "na", text: "— Needs a position size." });
  }
  out.push({ key: "correlation", label: plain ? "Moves with" : "Correlation", tone: "na", text: "— Not worked out for a new position; your holdings’ correlations are on Portfolio & risk." });
  const recent = bars ? bars.slice(-(GAP_SESSIONS + 1)) : null;
  const gap = recent ? largestGap(recent) : null;
  const entry = st.sent?.entry ?? setup?.entry ?? null;
  const stop = st.sent?.stop ?? setup?.stop ?? null;
  const stopDist = entry != null && stop != null && entry > stop ? ((entry - stop) / entry) * 100 : null;
  if (gap && recent) {
    const big = stopDist != null && Math.abs(gap.pct) >= stopDist;
    out.push({
      key: "gap", label: plain ? "Sudden jumps" : "Gap risk", tone: big ? "amber" : "mint",
      text: <>Largest opening gap in the last {fmtNum(recent.length - 1)} sessions: {fmtPct(gap.pct, { signed: true, digits: 1 })} ({fmtDay(gap.day)}){stopDist != null ? <>; the {plain ? "exit" : "stop"} is {fmtPct(stopDist, { digits: 1 })} below the {plain ? "buy level" : "entry"}{big ? ", so a gap that size would jump past it" : ""}.</> : "."}</>,
    });
  } else {
    out.push({ key: "gap", label: plain ? "Sudden jumps" : "Gap risk", tone: "na", text: "— Needs the stock’s daily bars." });
  }
  return out;
}

function CheckList({ checks }: { checks: RiskCheck[] }) {
  return (
    <ul data-testid="desk-risk-checks" className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
      {checks.map((c, i) => (
        <li
          key={c.key}
          data-testid={`desk-risk-chk-${c.key}`}
          data-tone={c.tone}
          className="flex items-start"
          style={{ gap: 10, padding: "8px 0", borderTop: i ? "1px solid var(--cp-line)" : undefined }}
        >
          <span aria-hidden style={{ flex: "none", width: 7, height: 7, marginTop: 5, borderRadius: 999, background: c.tone === "na" ? "var(--cp-ink-4)" : c.tone === "ink" ? "var(--cp-ink-3)" : TONE_COLOR[c.tone] }} />
          <span className="cp-eyebrow" style={{ flex: "none", width: 96, fontSize: 9.5, paddingTop: 2 }}>{c.label}</span>
          <span style={{ flex: "1 1 auto", minWidth: 0, fontSize: 12.5, lineHeight: 1.5, color: c.tone === "na" ? "var(--cp-ink-3)" : "var(--cp-ink-2)" }}>{c.text}</span>
        </li>
      ))}
    </ul>
  );
}

function Gate({ checks, passed }: { checks: GateCheck[]; passed: number }) {
  const all = passed === checks.length;
  const judged = checks.filter((c) => c.ok != null).length;
  return (
    <div data-testid="desk-risk-gate" style={{ borderRadius: 12, border: "1px solid var(--cp-line)", overflow: "hidden" }}>
      <div className="flex items-center justify-between" style={{ gap: 8, padding: "9px 14px", background: "var(--bg-0)", borderBottom: "1px solid var(--cp-line)" }}>
        <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Validation gate · model checks</span>
        <span data-testid="desk-risk-gate-count" className="cp-num" style={{ fontSize: 11, color: judged === 0 ? "var(--cp-ink-3)" : all ? "var(--mint)" : "var(--cp-danger)" }}>{judged === 0 ? "—" : `${passed} of ${checks.length} passed`}</span>
      </div>
      <ul className="m-0 flex flex-col" style={{ padding: "4px 14px", listStyle: "none" }}>
        {checks.map((c, i) => (
          <li
            key={c.key}
            data-testid={`desk-risk-check-${c.key}`}
            data-ok={c.ok == null ? "na" : String(c.ok)}
            className="flex items-center"
            style={{ gap: 10, padding: "7px 0", borderTop: i ? "1px solid var(--cp-line)" : undefined, fontSize: 12.5, color: "var(--cp-ink-2)" }}
          >
            <span
              aria-hidden
              style={{
                flex: "none", width: 16, height: 16, borderRadius: 999, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 9.5,
                fontFamily: "var(--mono)",
                color: c.ok == null ? "var(--cp-ink-4)" : c.ok ? "var(--mint)" : "var(--cp-danger)",
                background: c.ok == null ? "var(--bg-2)" : c.ok ? "var(--mint-soft)" : "var(--cp-danger-soft)",
                border: `1px solid ${c.ok == null ? "var(--line-2)" : c.ok ? "var(--mint-line)" : "var(--danger-line)"}`,
              }}
            >
              {c.ok == null ? "–" : c.ok ? "✓" : "✕"}
            </span>
            <span className="sr-only">{c.ok == null ? "Not available: " : c.ok ? "Passed: " : "Failed: "}</span>
            <span style={{ flex: "1 1 auto", minWidth: 0 }}>{c.label}</span>
            <span data-testid={`desk-risk-check-${c.key}-value`} className="cp-num" style={{ flex: "none", fontSize: 11.5, color: "var(--cp-ink)", textAlign: "right" }}>{c.value}</span>
          </li>
        ))}
      </ul>
      {judged === 0 && (
        <span data-testid="desk-risk-gate-none" className="cp-mono-note" style={{ display: "block", padding: "0 14px 9px", lineHeight: 1.5 }}>
          None of these checks applies yet: the model has not published a run and the stock is not on the scanner. “—” means not judged, not failed.
        </span>
      )}
    </div>
  );
}

// ── the sizing tiles (the design's 2 × 2) ────────────────────────────────

function SizeTiles({ st, plain }: { st: ScenarioState; plain: boolean }) {
  const s = st.q.data ?? null;
  if (st.read.problems.length || (s && !s.valid && st.current)) {
    return <span data-testid="desk-risk-nosize" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>Sizing needs an entry with a stop below it, a capital and a risk per trade; see the problems under “Edit the scenario”.</span>;
  }
  if (st.q.isError) return <ErrorBlock title="The scenario didn’t compute" error={st.q.error} onRetry={() => st.q.refetch()} />;
  if (!s || !s.valid || !s.sizing) return <span data-testid="desk-risk-sizing" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>Working out the size…</span>;
  const z = s.sizing;
  const o = s.outcomes;
  return (
    <>
      <div className="grid" data-current={st.current} style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8, opacity: st.current ? 1 : 0.6 }}>
        <StatTile k={plain ? "Shares" : "Quantity"} v={<span data-testid="desk-risk-qty">{fmtNum(z.quantity)}</span>} s={`shares · limited by ${BINDING[z.binding] ?? z.binding}`} testId="desk-risk-qty-tile" />
        <StatTile
          k={plain ? "Money used" : "Capital used"}
          v={<span data-testid="desk-risk-used">{fmtINR(z.gross_exposure)}</span>}
          s={z.allocation_pct != null ? <><span data-testid="desk-risk-used-pct">{fmtPct(z.allocation_pct, { digits: 1 })}</span> of {fmtINR(st.sent?.capital ?? null)}</> : "gross exposure"}
          tone={z.binding === "max_allocation" ? "amber" : "ink"}
          testId="desk-risk-used-tile"
        />
        <StatTile k={plain ? "If wrong" : "Max loss"} v={<span data-testid="desk-risk-maxloss">{o ? fmtINR(o.loss_at_stop_net) : "—"}</span>} s={o ? `at the ${plain ? "exit" : "stop"}, after costs (${fmtINR(o.loss_at_stop)} before)` : "No whole share fits"} tone="danger" testId="desk-risk-maxloss-tile" />
        <StatTile
          k={plain ? "If right" : "At target"}
          v={<span data-testid="desk-risk-attarget">{o?.profit_at_target_net != null ? fmtINR(o.profit_at_target_net, { signed: true }) : "—"}</span>}
          s={o?.profit_at_target != null ? `at the target, after costs (${fmtINR(o.profit_at_target, { signed: true })} before)` : "No target on this scenario"}
          tone={o?.profit_at_target_net != null ? "mint" : "ink"}
          testId="desk-risk-attarget-tile"
        />
      </div>
      <span data-testid="desk-risk-formula" className="cp-mono-note" style={{ lineHeight: 1.6 }}>
        {fmtINR(st.sent?.capital ?? null)} × {plainNum(st.sent?.riskPct)}% = {fmtINR(z.risk_budget)} at risk ÷ {fmtPrice(s.per_share?.risk ?? null)} a share (entry − stop), capped at {fmtNum(z.max_alloc_pct)}% of capital. Costs: {plainNum(s.cost_model.slippage_pct_per_side)}% + ₹{fmtNum(s.cost_model.brokerage_inr_per_side)} a side.
      </span>
      {z.quantity === 0 && <span data-testid="desk-risk-zero" style={{ fontSize: 12, color: "var(--amber)" }}>The risk budget is smaller than one share’s risk, so no whole share fits.</span>}
    </>
  );
}

// ── your portfolio and this idea (PRD §8.6) ──────────────────────────────

function PortfolioIdeaBlock({ st, symbol, plain }: { st: ScenarioState; symbol: string; plain: boolean }) {
  const pf = st.portfolio;
  const s = st.current && st.q.data?.valid ? st.q.data : null;
  const after = s?.portfolio ?? null;
  const row = (k: string, v: ReactNode, sub: ReactNode, testId: string) => (
    <li data-testid={testId} className="flex flex-wrap items-baseline" style={{ gap: "2px 12px", padding: "6px 0", borderTop: "1px solid var(--cp-line)", fontSize: 12.5 }}>
      <span style={{ flex: "1 1 140px", minWidth: 0, color: "var(--cp-ink-2)" }}>{k}</span>
      <span data-testid={`${testId}-v`} className="cp-num" style={{ color: "var(--cp-ink)", textAlign: "right" }}>{v}</span>
      {sub && <span style={{ flexBasis: "100%", fontSize: 11, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{sub}</span>}
    </li>
  );
  let body: ReactNode;
  if (pf.state === "loading") body = <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>Loading your holdings…</span>;
  else if (pf.state === "error") body = <ErrorBlock title="Your holdings didn’t load" error={pf.error} onRetry={pf.retry} />;
  else if (pf.state === "empty") {
    body = (
      <span data-testid="desk-pf-empty" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        No portfolio on record, so there is nothing to weigh this idea against. Connect a broker (read-only) or upload your holdings on Portfolio & risk.
      </span>
    );
  } else {
    body = (
      <ul className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
        {row(plain ? `Already own ${symbol}` : `Existing exposure · ${symbol}`, pf.existingValue ? fmtINR(pf.existingValue) : "None",
          pf.existingValue ? `${fmtPct(pf.existingWeightPct, { digits: 2 })} of the portfolio, all accounts` : "Not in your holdings.", "desk-pf-existing")}
        {row(plain ? "Same kind of business" : `Sector exposure${pf.sector ? ` · ${pf.sector}` : ""}`,
          pf.sectorValue != null ? fmtPct(pf.sectorWeightPct, { digits: 2 }) : "—",
          pf.sector ? (after?.sector_weight_after_pct != null ? `${fmtPct(after.sector_weight_after_pct, { digits: 2 })} after the buy. Direct stocks only; funds are not looked through.` : "Direct stocks only; funds are not looked through.") : "— The scanner gives no sector for this stock.",
          "desk-pf-sector")}
        <li data-testid="desk-pf-related" className="flex flex-col" style={{ gap: 6, padding: "6px 0", borderTop: "1px solid var(--cp-line)", fontSize: 12.5 }}>
          <span style={{ color: "var(--cp-ink-2)" }}>{plain ? "Other holdings like it" : "Related holdings"}{pf.sector ? ` · ${pf.sector}` : ""}</span>
          {pf.related.length ? (
            <span className="flex flex-wrap" style={{ gap: "6px 14px" }}>
              {pf.related.slice(0, 5).map((r) => (
                <span key={r.symbol} data-testid={`desk-pf-related-${r.symbol}`} className="flex items-center" style={{ gap: 6 }}>
                  <StockName symbol={r.symbol} name={r.name} size={18} sub={r.weightPct != null ? `${fmtPct(r.weightPct, { digits: 2 })} of portfolio` : undefined} />
                </span>
              ))}
              {pf.related.length > 5 && <span className="cp-mono-note">+{pf.related.length - 5} more</span>}
            </span>
          ) : (
            <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>{pf.sector ? "No other stock you hold is in this sector." : "— Needs the stock’s sector."}</span>
          )}
        </li>
        {row(plain ? "Share of your money in it after buying" : "Incremental concentration",
          after ? `${fmtPct(after.stock_weight_before_pct, { digits: 2 })} → ${fmtPct(after.stock_weight_after_pct, { digits: 2 })}` : "—",
          after ? `${fmtPct(after.stock_weight_change_pct, { signed: true, digits: 2 })} points. ${after.assumption ?? ""}` : "Needs a valid scenario.", "desk-pf-incremental")}
        {row(plain ? "Effect on your whole portfolio" : "Scenario impact on portfolio value",
          after ? `${after.impact_at_stop_pct != null ? fmtPct(after.impact_at_stop_pct, { signed: true, digits: 2 }) : "—"} at the stop · ${after.impact_at_target_pct != null ? fmtPct(after.impact_at_target_pct, { signed: true, digits: 2 }) : "—"} at the target` : "—",
          after ? `Net of costs, against a portfolio of ${fmtINR(after.portfolio_value)}.` : "Needs a valid scenario.", "desk-pf-impact")}
      </ul>
    );
  }
  return (
    <div data-testid="desk-pf" className="flex flex-col" style={{ gap: 6 }}>
      <span className="cp-eyebrow">{plain ? "Your portfolio and this idea" : "Portfolio fit · your holdings"}</span>
      {body}
      {pf.state === "ok" && (
        <span data-testid="desk-pf-limits" style={{ fontSize: 11, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>
          Limits: holdings as last synced or uploaded; sectors matched by name; mutual funds and ETFs not looked through; correlation with your holdings is not worked out for a new stock. Informational only — nothing is rebalanced or traded.
        </span>
      )}
    </div>
  );
}

/** "Edit the scenario" — the inputs and the full answer, on demand (PRD §1.4.6). */
function EditorDisclosure({ st, setup, symbol, defaultOpen = false, withPortfolio = false }: { st: ScenarioState; setup: DeskSetup | null; symbol: string; defaultOpen?: boolean; withPortfolio?: boolean }) {
  const { persona } = useDesk();
  const plain = persona === "investor";
  const [open, setOpen] = useState(defaultOpen);
  const panel = useId();
  // Opens by itself when something typed is wrong; an empty field (a stock without levels) does not force it open.
  const hasProblem = st.read.problems.some((p) => !p.blank) || (st.current && st.q.data?.valid === false);
  return (
    <div data-testid="desk-risk-editor" className="flex flex-col" style={{ gap: 10 }}>
      <button
        type="button"
        aria-expanded={open || hasProblem}
        aria-controls={panel}
        data-testid="desk-risk-editor-toggle"
        onClick={() => setOpen(!open)}
        style={{ alignSelf: "flex-start", padding: 0, border: 0, background: "none", color: "var(--mint)", fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)" }}
      >
        {plain ? "Change the numbers" : "Edit the scenario"} — levels, capital, limits and costs {open || hasProblem ? "▴" : "▾"}
      </button>
      {(open || hasProblem) && (
        <div id={panel} className="flex flex-col" style={{ gap: 12 }}>
          <ScenarioEditor st={st} setup={setup} />
          {withPortfolio && <PortfolioIdeaBlock st={st} symbol={symbol} plain={plain} />}
        </div>
      )}
    </div>
  );
}

// ── desktop: 05 · AI Risk desk ───────────────────────────────────────────

export function RiskDesk({ symbol, setup, bars }: { symbol: string; setup: DeskSetup | null; bars: DailyBar[] | null }) {
  const f = useRiskFigures(symbol, setup);
  const { plain } = f;
  const lv = useDeskLevels(symbol, setup);
  const st = useScenarioState(symbol, setup, lv);
  const sym = symbol.toUpperCase();
  const scan = useDeskScanner();

  const entry = lv.entry;
  const stop = lv.stop;
  const target = lv.target;
  const rr = lv.riskReward;
  const ltp = bars?.length ? bars[bars.length - 1].close : setup?.close ?? null;
  const record = f.record;
  const capitalOpt = CAPITALS.find((c) => c.value === st.fields.capital)?.value ?? ("" as string);
  const riskOpt = RISKS.find((r) => r.value === st.fields.riskPct)?.value ?? ("" as string);

  return (
    <section data-testid="desk-risk" data-layout="desk" className="cp-card flex min-w-0 flex-col">
      <CardHead num="05" title="AI Risk desk" testId="desk-risk-title">
        {setup && <span data-testid="desk-risk-status" data-status={setup.status}><Pill tone={RISK_STATUS[setup.status].tone}>{RISK_STATUS[setup.status].label}</Pill></span>}
      </CardHead>

      <div className="flex flex-col" style={{ gap: 16, padding: "16px 18px" }}>
        <div className="flex flex-wrap items-end justify-between" style={{ gap: "8px 16px" }}>
          <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
            <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{plain ? "Idea" : "Scenario"} · {sym}</span>
            <span data-testid="desk-risk-scenario" style={{ fontSize: 13, color: "var(--cp-ink)" }}>{setup ? setupLabel(setup, plain) : "Not on today’s scanner"}</span>
          </div>
          <div className="flex flex-col items-end" style={{ gap: 2 }}>
            <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{plain ? "Reward for risk" : "Reward / risk"}</span>
            <span data-testid="desk-risk-rr" style={{ fontFamily: "var(--display)", fontSize: 30, lineHeight: 1, color: rr != null ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>{rrText(rr)}</span>
          </div>
        </div>

        {lv.source && entry != null && stop != null && entry > stop ? (
          <RangeBar entry={entry} stop={stop} target={target} ltp={ltp} plain={plain} />
        ) : (
          <span data-testid="desk-risk-nolevels" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            {setup ? "This setup has no entry with a stop below it, so there is no range to draw. Enter levels under “Edit the scenario” to size one." : "Not on today’s scanner — no levels. The scanner suggests an entry, stop and target only for stocks that pass its end-of-day rules, and nothing is made up for the rest. Enter your own under “Edit the scenario” and the calculator sizes them."}{lv.reason ? ` (${lv.reason})` : ""}
          </span>
        )}
        {lv.source === "rule" && lv.rule && (
          <span data-testid="desk-risk-rule" className="cp-mono-note" style={{ lineHeight: 1.5 }}>
            {lv.rule.label}. Rule {lv.rule.name} v{lv.rule.version}: entry = last close; stop = {plainNum(lv.rule.constants.atr_multiple)} × ATR({lv.rule.constants.atr_period}) below it, or the 20-session low when that is closer; target = entry + {plainNum(lv.rule.constants.reward_multiple)} × the risk. These levels are in the calculator below.
          </span>
        )}
        {setup && target == null && entry != null && (
          <span className="cp-mono-note">Reward / risk needs a target; only the scanner’s picks carry one.</span>
        )}

        <div className="grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
          <StatTile k={plain ? "Chance of +5%" : "Move probability"} v={f.pValue} s={f.pNote} tone={f.pTone} size={34} testId="desk-risk-p5" />
          <StatTile
            k={plain ? "Past trades that worked" : "Trade win rate"}
            v="—"
            s="No back-tested win rate for this setup is published."
            size={34}
            testId="desk-risk-winrate"
          />
        </div>
        <p data-testid="desk-risk-explain" className="m-0" style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          {plain
            ? "The chance is the model’s estimate that the next trading day’s high gets 5% above the last close — one day only. A win rate would count how often whole trades like this reached the target before the exit; nobody publishes that for this setup yet, so it shows —."
            : "Move probability is the move-odds model’s estimate that the next session’s high reaches the last close plus 5%, one session only. A trade win rate would count how often entry-to-target trades on this setup reached the target before the stop; none is published, so it shows —."}
          {" "}
          <span data-testid="desk-risk-record">
            {record
              ? <>The model’s out-of-sample record ({record.window_label}): top-10 hit rate {pct1(record.top10_hit_rate)} over {fmtNum(record.sessions)} sessions vs a base rate of {pct1(record.base_rate)} — the model’s record, not this stock’s.</>
              : f.locked ? "The model’s record is not enabled for this account." : "No out-of-sample record is published with this run."}
          </span>
        </p>

        <Gate checks={f.checks} passed={f.passed} />

        <div data-testid="desk-risk-size" className="flex flex-col" style={{ gap: 10 }}>
          <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <span className="cp-eyebrow" style={{ marginRight: "auto" }}>{plain ? "How much to buy" : "Position size"}</span>
            <Segmented label="Capital" value={capitalOpt} options={CAPITALS} onChange={(v) => st.set("capital", v)} idPrefix="desk-risk-capital" small />
            <Segmented label="Risk per trade" value={riskOpt} options={RISKS} onChange={(v) => st.set("riskPct", v)} idPrefix="desk-risk-pct" small />
          </div>
          <SizeTiles st={st} plain={plain} />
        </div>
        <span data-testid="desk-risk-stopnote" style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>
          {(st.q.data?.caveats ?? [STOP_NOTE])[0]}
        </span>

        <EditorDisclosure st={st} setup={setup} symbol={sym} defaultOpen={!setup} />

        <PortfolioIdeaBlock st={st} symbol={sym} plain={plain} />

        <CheckList checks={riskChecks(st, setup, bars, plain)} />

        <DeskActions symbol={sym} setup={setup} st={st} />

        <TrustLine
          testId="desk-risk-trust"
          source="Positional scanner levels · scenario route (server)"
          mode="eod"
          asOf={scan.data?.signalDate ? fmtDay(scan.data.signalDate) : scan.data?.watchAsOf ? fmtDay(scan.data.watchAsOf) : null}
          maker="rules"
          method={st.q.data ? `PRD §8.5 sizing · costs ${plainNum(st.q.data.cost_model.slippage_pct_per_side)}% + ₹${fmtNum(st.q.data.cost_model.brokerage_inr_per_side)} a side (strategy_engine)` : "PRD §8.5 sizing on the server"}
          status={st.q.isError ? "failed" : null}
        />
      </div>
    </section>
  );
}

// ── phone: 05 · Trade scenario (design-spec §11 M4) ──────────────────────

export function TradeScenarioCard({ symbol, setup }: { symbol: string; setup: DeskSetup | null }) {
  const f = useRiskFigures(symbol, setup);
  const { plain } = f;
  const lv = useDeskLevels(symbol, setup);
  const st = useScenarioState(symbol, setup, lv);
  const sym = symbol.toUpperCase();
  const entry = lv.entry;
  const stop = lv.stop;
  const target = lv.target;
  const rr = lv.riskReward;
  return (
    <section data-testid="desk-risk" data-layout="phone" className="cp-card flex min-w-0 flex-col">
      <div className="flex flex-wrap items-center" style={{ gap: 8, padding: "12px 14px", borderBottom: "1px solid var(--cp-line)" }}>
        <span data-testid="desk-risk-title" className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}><span style={{ color: "var(--mint)" }}>05</span> · Trade scenario</span>
        <span className="cp-eyebrow" style={{ marginLeft: "auto", fontSize: 9.5 }}>
          {plain ? "Reward for risk" : "Reward / risk"} <span data-testid="desk-risk-rr" style={{ fontFamily: "var(--display)", fontSize: 18, letterSpacing: 0, textTransform: "none", color: rr != null ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>{rrText(rr)}</span>
        </span>
      </div>
      <div className="flex flex-col" style={{ gap: 12, padding: 14 }}>
        <div className="grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
          <StatTile k={plain ? "Chance of +5%" : "Move probability"} v={f.pValue} s={f.pNote} tone={f.pTone} size={28} testId="desk-risk-p5" />
          <StatTile k={plain ? "Past trades that worked" : "Trade win rate"} v="—" s="No back-tested win rate is published." size={28} testId="desk-risk-winrate" />
        </div>
        {lv.source && entry != null && stop != null ? (
          <div data-testid="desk-risk-levels" className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 10px" }}>
            <span data-testid="desk-risk-stop" className="cp-eyebrow" style={{ fontSize: 9.5, color: "var(--cp-danger)" }}>{plain ? "Exit if wrong" : "Stop"} {fmtPrice(stop)}</span>
            <span data-testid="desk-risk-entry" className="cp-eyebrow" style={{ fontSize: 9.5, color: "var(--cp-ink-2)" }}>{plain ? "Buy above" : "Entry"} {fmtPrice(entry)}</span>
            <span data-testid="desk-risk-target" className="cp-eyebrow" style={{ fontSize: 9.5, color: target != null ? "var(--mint)" : "var(--cp-ink-4)" }}>{target != null ? `Target ${fmtPrice(target)}` : "No target"}</span>
          </div>
        ) : (
          <span data-testid="desk-risk-nolevels" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>{setup ? "No entry with a stop below it on this setup." : "Not on today’s scanner — no levels."}</span>
        )}
        {lv.source === "rule" && lv.rule && (
          <span data-testid="desk-risk-rule" className="cp-mono-note" style={{ lineHeight: 1.5 }}>{lv.rule.label}. Rule {lv.rule.name} v{lv.rule.version}.</span>
        )}
        <span data-testid="desk-risk-stopnote" style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{(st.q.data?.caveats ?? [STOP_NOTE])[0]}</span>
        <EditorDisclosure st={st} setup={setup} symbol={sym} withPortfolio />
        <DeskActions symbol={sym} setup={setup} st={st} phone />
        <TrustLine testId="desk-risk-trust" source="Positional scanner levels · scenario route (server)" mode="eod" maker="rules" method="PRD §8.5 sizing on the server" status={st.q.isError ? "failed" : null} />
      </div>
    </section>
  );
}

// ── paper trade and alert ────────────────────────────────────────────────

const noteStyle = { fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" } as const;
const linkStyle = { padding: 0, border: 0, background: "none", fontSize: 12, color: "var(--mint)", cursor: "pointer", fontFamily: "var(--sans)" } as const;

function Outcome({ ok, testId, children, onOpen, openLabel }: { ok: boolean; testId: string; children: ReactNode; onOpen?: () => void; openLabel?: string }) {
  return (
    <span
      data-testid={testId}
      role={ok ? "status" : "alert"}
      style={{
        fontSize: 12, lineHeight: 1.5, padding: "8px 10px", borderRadius: 10, color: "var(--cp-ink-2)",
        border: `1px solid ${ok ? "var(--mint-line)" : "var(--danger-line)"}`,
        background: ok ? "var(--mint-soft)" : "var(--cp-danger-soft)",
      }}
    >
      {children}
      {onOpen && openLabel && <>{" "}<button type="button" data-testid={`${testId}-open`} onClick={onOpen} style={linkStyle}>{openLabel}</button></>}
    </span>
  );
}

/**
 * "Add to paper trades" (the scenario's quantity at the scenario's levels) and "Alert on trigger" (desk only). Each
 * is disabled while its request is in flight, says why when it cannot be used, and shows the server's words when it
 * fails. Neither sends anything to a broker.
 */
function DeskActions({ symbol, setup, st, phone }: { symbol: string; setup: DeskSetup | null; st: ScenarioState; phone?: boolean }) {
  const { openTab } = useDesk();
  const scan = useDeskScanner();
  const paper = useAddPaperTrade();
  const alert = useAddAlert();

  const s: Scenario | null = st.current && st.q.data?.valid ? st.q.data : null;
  const sent = st.sent;
  const qty = s?.sizing?.quantity ?? null;
  // The route takes a target only above the entry; the scenario has already checked the direction.
  const sendTarget = sent?.target != null && sent.entry != null && sent.target > sent.entry ? sent.target : null;
  const signalDate = setup ? (setup.inPicks ? scan.data?.signalDate : scan.data?.watchAsOf) ?? null : null;

  let paperBody: NewPaperTrade | null = null;
  let paperWhy: string;
  if (!setup) paperWhy = "Needs a scanner setup: this stock has no entry or stop.";
  else if (setup.entry == null || setup.stop == null || !(setup.entry > setup.stop)) paperWhy = "Needs an entry with a stop below it; this setup does not have both.";
  else if (st.q.isError) paperWhy = "The scenario didn’t compute, so there is no quantity to add.";
  else if (!s || !sent) paperWhy = st.read.problems.length || (st.current && st.q.data?.valid === false) ? "Fix the scenario’s inputs first." : "Working out the quantity…";
  else if (qty == null || qty < 1) paperWhy = "The risk budget fits no whole share; pick more capital or a larger risk.";
  else {
    paperBody = {
      symbol,
      quantity: qty,
      entry_price: sent.entry,
      stop_price: sent.stop,
      target_price: sendTarget,
      source: { kind: "scanner", ...(setup.bucket ? { bucket: setup.bucket } : {}), ...(signalDate ? { signal_date: signalDate } : {}) },
    };
    paperWhy = `Simulated: ${fmtNum(qty)} shares at ${fmtPrice(sent.entry)}, stop ${fmtPrice(sent.stop)}${sendTarget != null ? `, target ${fmtPrice(sendTarget)}` : ", no target"}${phone ? ` (sized at ${fmtINR(sent.capital)} with ${plainNum(sent.riskPct)}% risk)` : ""}. No order is placed; it is marked against end-of-day closes.`;
  }

  const level = setup?.trigger ?? setup?.entry ?? null;
  const alertBody: NewAlert | null = level != null ? { symbol, condition: "above", level } : null;
  const alertWhy = alertBody
    ? `Watches for a session whose high reaches ${fmtPrice(alertBody.level)} (the ${setup?.trigger != null ? "trigger" : "entry"}), checked after each close. Shown in your alerts list only.`
    : "Needs a trigger or an entry level; this stock has neither on today’s scanner.";

  // An outcome belongs to the stock it was sent for; another stock starts clean.
  const paperDone = paper.variables?.symbol === symbol ? paper : null;
  const alertDone = alert.variables?.symbol === symbol ? alert : null;
  const alertSet = !!alertDone?.isSuccess;

  return (
    <div data-testid="desk-risk-actions" className="flex flex-col" style={{ gap: 8 }}>
      <div className="flex flex-wrap" style={{ gap: 8 }}>
        <Btn
          variant="primary"
          data-testid="desk-risk-paper"
          aria-describedby="desk-risk-paper-note"
          disabled={!paperBody || paper.isPending}
          onClick={() => { if (paperBody) paper.mutate(paperBody); }}
          style={{ flex: "1 1 150px" }}
        >
          {paper.isPending ? "Adding…" : "Add to paper trades"}
        </Btn>
        {!phone && (
          <Btn
            data-testid="desk-risk-alert"
            aria-describedby="desk-risk-alert-note"
            disabled={!alertBody || alert.isPending || alertSet}
            onClick={() => { if (alertBody) alert.mutate(alertBody); }}
            style={{ flex: "0 1 auto", ...(alertSet ? { color: "var(--mint)", borderColor: "var(--mint-line)", opacity: 1 } : null) }}
          >
            {alert.isPending ? "Setting…" : alertSet ? "Alert set ✓" : "Alert on trigger"}
          </Btn>
        )}
      </div>
      <span id="desk-risk-paper-note" data-testid="desk-risk-paper-note" style={noteStyle}>{paperWhy}</span>
      {!phone && <span id="desk-risk-alert-note" data-testid="desk-risk-alert-note" style={noteStyle}>{alertWhy}</span>}
      {paperDone?.isSuccess && (
        <Outcome ok testId="desk-risk-paper-done" onOpen={() => openTab("portfolio")} openLabel="See your paper trades ›">
          Paper trade added: {fmtNum(paperDone.variables?.quantity ?? null)} {symbol} at {fmtPrice(paperDone.variables?.entry_price ?? null)}. No order is placed.
        </Outcome>
      )}
      {paperDone?.isError && <Outcome ok={false} testId="desk-risk-paper-error">Not added — {writeProblem(paperDone.error)}</Outcome>}
      {alertDone?.isSuccess && (
        <Outcome ok testId="desk-risk-alert-done" onOpen={() => openTab("portfolio")} openLabel="See your alerts ›">
          Alert set: {symbol} above {fmtPrice(alertDone.variables?.level ?? null)}, checked against end-of-day highs.
        </Outcome>
      )}
      {alertDone?.isError && <Outcome ok={false} testId="desk-risk-alert-error">Not set — {writeProblem(alertDone.error)}</Outcome>}
      <span data-testid="desk-risk-note" style={noteStyle}>Paper trade only. Nivesh reads broker positions and cannot place orders.</span>
    </div>
  );
}
