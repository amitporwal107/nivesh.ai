/**
 * Smart trading desk — 05 AI Risk desk, beside the chart (design-spec §5), and
 * the phone's "05 · Trade scenario" card (§11 M4).
 *
 *   levels, reward / risk   the scanner setup (useDeskScanner: GET /api/positional/picks, else /watchlist)
 *   move probability        GET /api/move-odds/latest?head=p_up5_1d (useDeskOdds), else
 *                           GET /api/move-odds/stocks/{symbol} (useStockOdds) — a next-session estimate
 *   validation gate         the model's run, its out-of-sample record (in /latest), the stock's events on
 *                           record, and the scanner row's 20-session traded value (avg_traded_value_cr_20d)
 *   last close, gap risk    the chart's daily bars (GET /api/research/chart-live/{symbol}/ohlcv, end of day)
 *   Add to paper trades     POST /api/desk/paper-trades { symbol, quantity (the calculator's), entry_price,
 *                           stop_price, target_price, source: { kind: "scanner", bucket, signal_date } }
 *   Alert on trigger        POST /api/desk/alerts { symbol, condition: "above", level: the trigger, else the entry }
 *
 * Shown as "—" with the reason, because no route publishes them: a trade win
 * rate for the setup (entry-to-target before the stop, back-tested), and the
 * stock's correlation with a new position. A gate check whose source is
 * missing shows "—" and does not count as passed.
 *
 * The position-size calculator works on the levels in the browser. The two
 * buttons are the only writes: a paper trade is simulated (marked against
 * end-of-day closes; no order is placed) and an alert is checked after each
 * close. Both lists are on the Portfolio & risk tab. Nivesh does not place orders.
 */
import { useState, type ReactNode } from "react";
import { Btn, Pill, TONE_COLOR, fmtINR, fmtNum, fmtPct, type Tone } from "../../components/ui";
import { fmtDay, fmtPrice } from "../trading/parts";
import { setupLabel, useStockOdds } from "./chart-data";
import { useDesk } from "./context";
import { LIQUID_MIN_CR, useDeskOdds, useDeskScanner, type DeskSetup, type SetupStatus } from "./desk-data";
import { useAddAlert, useAddPaperTrade, writeProblem, type NewAlert, type NewPaperTrade } from "./desk-trading";
import { largestGap, type DailyBar } from "./indicators";

const CAPITALS = [
  { value: 200_000, label: "₹2L", id: "2l" },
  { value: 500_000, label: "₹5L", id: "5l" },
  { value: 1_000_000, label: "₹10L", id: "10l" },
] as const;

/** Risk per trade in basis points of capital, so the rupee budget is exact. */
const RISKS = [
  { value: 50, label: "0.5%", id: "0-5" },
  { value: 100, label: "1%", id: "1" },
  { value: 200, label: "2%", id: "2" },
] as const;

const DEFAULT_CAPITAL = 500_000;
const DEFAULT_RISK_BPS = 100;

/** Capital used above this share of capital gets a warning. */
const SINGLE_STOCK_LIMIT = 0.25;

/** Sessions the gap-risk check looks back over (about 3 months). */
const GAP_SESSIONS = 63;

/** Absorbs float noise in a quotient that should be whole (25.000000000000004 → 25), so floor never drops a share. */
const EPS = 1e-9;

export interface Sizing {
  perShare: number;
  riskBudget: number;
  qty: number;
  used: number;
  usedPct: number;
  maxLoss: number;
  atTarget: number | null;
  /** Shares that keep capital used within the single-stock limit. */
  limitQty: number;
  overLimit: boolean;
}

/** quantity = floor(capital × risk% ÷ (entry − stop)). Null without an entry above the stop. */
export function sizePosition(capital: number, riskBps: number, entry: number | null, stop: number | null, target: number | null): Sizing | null {
  if (entry == null || stop == null || !(entry > stop) || capital <= 0) return null;
  const perShare = entry - stop;
  const riskBudget = (capital * riskBps) / 10_000;
  const qty = Math.floor(riskBudget / perShare + EPS);
  const used = qty * entry;
  return {
    perShare, riskBudget, qty, used,
    usedPct: (used / capital) * 100,
    maxLoss: qty * perShare,
    atTarget: target != null && target > entry ? qty * (target - entry) : null,
    limitQty: Math.floor((capital * SINGLE_STOCK_LIMIT) / entry + EPS),
    overLimit: used > capital * SINGLE_STOCK_LIMIT,
  };
}

const pct1 = (p: number | null | undefined) => (p == null ? "—" : fmtPct(p * 100, { digits: 1 }));
const crText = (cr: number) => `₹${fmtNum(cr, cr >= 100 ? 0 : 1)} Cr`;
const rrText = (rr: number | null) => (rr != null ? `${fmtNum(rr, 1)} : 1` : "—");

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
  const publishedOk: boolean | null = run ? true : odds?.kind === "not_published" || withheld ? false : null;
  const checks: GateCheck[] = [
    {
      key: "published",
      label: plain ? "Model ran for the next day" : "Model run for the next session",
      value: run ? fmtDay(run.target_session) : odds?.kind === "not_published" ? "Not published" : withheld ? "Withheld" : "—",
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
    pValue = pct1(p);
    if (allPassed) {
      pTone = "mint";
      pNote = <>{head} · {run ? fmtDay(run.target_session) : "next session"}{odds?.kind === "final" ? <> · base rate {pct1(odds.data.base_rate)}</> : null}</>;
    } else {
      pNote = <>{head}. Not shown as high-confidence: {passed} of {checks.length} gate checks passed.</>;
    }
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

function riskChecks(sizing: Sizing | null, capital: number, riskBps: number, setup: DeskSetup | null, bars: DailyBar[] | null, plain: boolean): RiskCheck[] {
  const riskLabel = RISKS.find((r) => r.value === riskBps)?.label ?? `${riskBps / 100}%`;
  const out: RiskCheck[] = [];
  out.push(sizing
    ? { key: "size", label: plain ? "Size" : "Position size", tone: "mint", text: <>{fmtINR(sizing.riskBudget)} at risk ({riskLabel} of {fmtINR(capital)}); {plain ? "if wrong you lose" : "max loss"} {fmtINR(sizing.maxLoss)} at the {plain ? "exit" : "stop"}.</> }
    : { key: "size", label: plain ? "Size" : "Position size", tone: "na", text: "— Needs an entry with a stop below it." });
  out.push(sizing
    ? sizing.overLimit
      ? { key: "concentration", label: plain ? "One-stock share" : "Concentration", tone: "amber", text: <>{fmtPct(sizing.usedPct, { digits: 1 })} of capital in one stock, above the 25% single-stock limit; {fmtNum(sizing.limitQty)} shares keeps it inside.</> }
      : { key: "concentration", label: plain ? "One-stock share" : "Concentration", tone: "mint", text: <>{fmtPct(sizing.usedPct, { digits: 1 })} of capital, within the 25% single-stock limit.</> }
    : { key: "concentration", label: plain ? "One-stock share" : "Concentration", tone: "na", text: "— Needs a position size." });
  out.push({ key: "correlation", label: plain ? "Moves with" : "Correlation", tone: "na", text: "— Not worked out for a new position; your holdings’ correlations are on Portfolio & risk." });
  const recent = bars ? bars.slice(-(GAP_SESSIONS + 1)) : null;
  const gap = recent ? largestGap(recent) : null;
  const entry = setup?.entry ?? null;
  const stop = setup?.stop ?? null;
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
  return (
    <div data-testid="desk-risk-gate" style={{ borderRadius: 12, border: "1px solid var(--cp-line)", overflow: "hidden" }}>
      <div className="flex items-center justify-between" style={{ gap: 8, padding: "9px 14px", background: "var(--bg-0)", borderBottom: "1px solid var(--cp-line)" }}>
        <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Validation gate</span>
        <span data-testid="desk-risk-gate-count" className="cp-num" style={{ fontSize: 11, color: all ? "var(--mint)" : "var(--cp-danger)" }}>{passed} of {checks.length} passed</span>
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
    </div>
  );
}

// ── desktop: 05 · AI Risk desk ───────────────────────────────────────────

export function RiskDesk({ symbol, setup, bars }: { symbol: string; setup: DeskSetup | null; bars: DailyBar[] | null }) {
  const f = useRiskFigures(symbol, setup);
  const { plain } = f;
  const [capital, setCapital] = useState<number>(DEFAULT_CAPITAL);
  const [riskBps, setRiskBps] = useState<number>(DEFAULT_RISK_BPS);
  const sym = symbol.toUpperCase();

  const entry = setup?.entry ?? null;
  const stop = setup?.stop ?? null;
  const target = setup?.target ?? null;
  const sizing = sizePosition(capital, riskBps, entry, stop, target);
  const rr = setup?.riskReward ?? null;
  const ltp = bars?.length ? bars[bars.length - 1].close : setup?.close ?? null;
  const record = f.record;

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

        {setup && entry != null && stop != null && entry > stop ? (
          <RangeBar entry={entry} stop={stop} target={target} ltp={ltp} plain={plain} />
        ) : (
          <span data-testid="desk-risk-nolevels" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            {setup ? "This setup has no entry with a stop below it, so there is no range to draw." : "Not on today’s scanner — no levels."}
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
            <Segmented label="Capital" value={capital} options={CAPITALS} onChange={setCapital} idPrefix="desk-risk-capital" small />
            <Segmented label="Risk per trade" value={riskBps} options={RISKS} onChange={setRiskBps} idPrefix="desk-risk-pct" small />
          </div>
          {sizing ? (
            <>
              <div className="grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
                <StatTile k={plain ? "Shares" : "Quantity"} v={<span data-testid="desk-risk-qty">{fmtNum(sizing.qty)}</span>} s="shares" testId="desk-risk-qty-tile" />
                <StatTile
                  k={plain ? "Money used" : "Capital used"}
                  v={<span data-testid="desk-risk-used">{fmtINR(sizing.used)}</span>}
                  s={<><span data-testid="desk-risk-used-pct">{fmtPct(sizing.usedPct, { digits: 1 })}</span> of {fmtINR(capital)}</>}
                  tone={sizing.overLimit ? "amber" : "ink"}
                  testId="desk-risk-used-tile"
                />
                <StatTile k={plain ? "If wrong" : "Max loss"} v={<span data-testid="desk-risk-maxloss">{fmtINR(sizing.maxLoss)}</span>} s={`at the ${plain ? "exit" : "stop"}, before costs`} tone="danger" testId="desk-risk-maxloss-tile" />
                <StatTile
                  k={plain ? "If right" : "At target"}
                  v={<span data-testid="desk-risk-attarget">{sizing.atTarget != null ? fmtINR(sizing.atTarget, { signed: true }) : "—"}</span>}
                  s={sizing.atTarget != null ? "at the target, before costs" : "No target on this setup"}
                  tone={sizing.atTarget != null ? "mint" : "ink"}
                  testId="desk-risk-attarget-tile"
                />
              </div>
              <span className="cp-mono-note" style={{ lineHeight: 1.6 }}>
                {fmtINR(capital)} × {RISKS.find((r) => r.value === riskBps)?.label} = {fmtINR(sizing.riskBudget)} at risk ÷ {fmtPrice(sizing.perShare)} a share (entry − stop). Max loss is before brokerage and taxes.
              </span>
              {sizing.qty === 0 && (
                <span data-testid="desk-risk-zero" style={{ fontSize: 12, color: "var(--amber)" }}>The risk budget is smaller than one share’s risk, so no whole share fits.</span>
              )}
            </>
          ) : (
            <span data-testid="desk-risk-nosize" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
              Sizing needs both an entry and a stop below it{setup ? "; this setup does not have both." : ", and this stock has no scanner levels."}
            </span>
          )}
        </div>

        <CheckList checks={riskChecks(sizing, capital, riskBps, setup, bars, plain)} />

        <DeskActions symbol={sym} setup={setup} sizing={sizing} />
      </div>
    </section>
  );
}

// ── phone: 05 · Trade scenario (design-spec §11 M4) ──────────────────────

export function TradeScenarioCard({ symbol, setup }: { symbol: string; setup: DeskSetup | null }) {
  const f = useRiskFigures(symbol, setup);
  const { plain } = f;
  const sym = symbol.toUpperCase();
  const entry = setup?.entry ?? null;
  const stop = setup?.stop ?? null;
  const target = setup?.target ?? null;
  const rr = setup?.riskReward ?? null;
  // The phone has no calculator: the trade is sized at the desk's defaults, and the note says so.
  const sizing = sizePosition(DEFAULT_CAPITAL, DEFAULT_RISK_BPS, entry, stop, target);
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
        {setup && entry != null && stop != null ? (
          <div data-testid="desk-risk-levels" className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 10px" }}>
            <span data-testid="desk-risk-stop" className="cp-eyebrow" style={{ fontSize: 9.5, color: "var(--cp-danger)" }}>{plain ? "Exit if wrong" : "Stop"} {fmtPrice(stop)}</span>
            <span data-testid="desk-risk-entry" className="cp-eyebrow" style={{ fontSize: 9.5, color: "var(--cp-ink-2)" }}>{plain ? "Buy above" : "Entry"} {fmtPrice(entry)}</span>
            <span data-testid="desk-risk-target" className="cp-eyebrow" style={{ fontSize: 9.5, color: target != null ? "var(--mint)" : "var(--cp-ink-4)" }}>{target != null ? `Target ${fmtPrice(target)}` : "No target"}</span>
          </div>
        ) : (
          <span data-testid="desk-risk-nolevels" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>{setup ? "No entry with a stop below it on this setup." : "Not on today’s scanner — no levels."}</span>
        )}
        <DeskActions symbol={sym} setup={setup} sizing={sizing} phone />
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
 * "Add to paper trades" (the calculator's quantity at the setup's levels) and
 * "Alert on trigger" (desk only). Each is disabled while its request is in
 * flight, says why when it cannot be used, and shows the server's words when it fails.
 */
function DeskActions({ symbol, setup, sizing, phone }: { symbol: string; setup: DeskSetup | null; sizing: Sizing | null; phone?: boolean }) {
  const { openTab } = useDesk();
  const scan = useDeskScanner();
  const paper = useAddPaperTrade();
  const alert = useAddAlert();

  const entry = setup?.entry ?? null;
  const stop = setup?.stop ?? null;
  const target = setup?.target ?? null;
  // The route takes a target only above the entry.
  const sendTarget = target != null && entry != null && target > entry ? target : null;
  const signalDate = setup ? (setup.inPicks ? scan.data?.signalDate : scan.data?.watchAsOf) ?? null : null;

  let paperBody: NewPaperTrade | null = null;
  let paperWhy: string;
  if (!setup) paperWhy = "Needs a scanner setup: this stock has no entry or stop.";
  else if (entry == null || stop == null || !(entry > stop)) paperWhy = "Needs an entry with a stop below it; this setup does not have both.";
  else if (!sizing || sizing.qty < 1) paperWhy = "The risk budget fits no whole share; pick more capital or a larger risk.";
  else {
    paperBody = {
      symbol,
      quantity: sizing.qty,
      entry_price: entry,
      stop_price: stop,
      target_price: sendTarget,
      source: { kind: "scanner", ...(setup.bucket ? { bucket: setup.bucket } : {}), ...(signalDate ? { signal_date: signalDate } : {}) },
    };
    paperWhy = `Simulated: ${fmtNum(sizing.qty)} shares at ${fmtPrice(entry)}, stop ${fmtPrice(stop)}${sendTarget != null ? `, target ${fmtPrice(sendTarget)}` : ", no target"}${phone ? ` (sized at ${fmtINR(DEFAULT_CAPITAL)} with 1% risk)` : ""}. No order is placed; it is marked against end-of-day closes.`;
  }

  const level = setup?.trigger ?? entry;
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
