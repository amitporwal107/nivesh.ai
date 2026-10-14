/**
 * Smart trading desk — 05 Risk desk, beside the chart (under it on narrow screens).
 *
 *   levels, reward : risk   the scanner setup (useDeskScanner: GET /api/positional/picks, else /watchlist)
 *   P(+5% next session)     GET /api/move-odds/latest?head=p_up5_1d (useDeskOdds), else
 *                           GET /api/move-odds/stocks/{symbol} (useStockOdds)
 *   model record            the out-of-sample record in /latest — the model's record, not this stock's
 *   last close              the chart's last daily bar (GET /api/research/chart-live/{symbol}/ohlcv)
 *
 * The position-size calculator works on the levels in the browser; nothing is
 * saved or sent. "Add to paper trades" and "Alert on trigger" have no backend
 * (paper trades are chosen by the model engine; there is no price-alert route),
 * so they are disabled and send nothing. Nivesh does not place orders.
 */
import { useState, type ReactNode } from "react";
import { Btn, Footnote, Pill, TONE_COLOR, fmtINR, fmtNum, fmtPct, type Tone } from "../../components/ui";
import { fmtDay, fmtPrice } from "../trading/parts";
import { STATUS_LABEL, setupLabel, useStockOdds } from "./chart-data";
import { useDeskOdds, type DeskSetup } from "./desk-data";

const CAPITALS = [
  { value: 200_000, label: "₹2L", id: "2l" },
  { value: 500_000, label: "₹5L", id: "5l" },
  { value: 1_000_000, label: "₹10L", id: "10l" },
] as const;

/** Risk per trade in basis points of capital, so the rupee budget is exact. */
const RISKS = [
  { bps: 50, label: "0.5%", id: "0-5" },
  { bps: 100, label: "1%", id: "1" },
  { bps: 200, label: "2%", id: "2" },
] as const;

/** Capital used above this share of capital gets a warning. */
const SINGLE_STOCK_LIMIT = 0.25;

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

function Toggle<T extends string | number>({ label, value, options, onChange, idPrefix }: {
  label: string;
  value: T;
  options: ReadonlyArray<{ value: T; label: string; id: string }>;
  onChange: (v: T) => void;
  idPrefix: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex flex-wrap" style={{ gap: 2, padding: 2, borderRadius: 10, border: "1px solid var(--line-2)" }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.id}
            type="button"
            aria-pressed={on}
            data-testid={`${idPrefix}-${o.id}`}
            onClick={() => onChange(o.value)}
            style={{
              padding: "5px 10px", borderRadius: 8, fontSize: 12, border: 0, cursor: "pointer", fontFamily: "var(--mono)",
              background: on ? "var(--bg-3)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-2)",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function MiniTile({ k, v, s, tone = "ink", testId }: { k: string; v: ReactNode; s?: ReactNode; tone?: Tone; testId: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 4, padding: "12px 14px", borderRadius: 12, border: "1px solid var(--cp-line)", background: "var(--bg-0)" }}>
      <span className="cp-eyebrow">{k}</span>
      <span data-testid={testId} className="cp-num" style={{ fontSize: 20, color: TONE_COLOR[tone] }}>{v}</span>
      {s != null && <span data-testid={`${testId}-note`} style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{s}</span>}
    </div>
  );
}

/** Stop → entry → target, widths in proportion to risk and reward, with the last close marked. */
function RiskBar({ entry, stop, target, ltp }: { entry: number; stop: number; target: number | null; ltp: number | null }) {
  const top = target ?? entry;
  const lo = Math.min(stop, ltp ?? stop);
  const hi = Math.max(top, ltp ?? top);
  const span = hi - lo || 1;
  const at = (v: number) => ((v - lo) / span) * 100;
  return (
    <div data-testid="desk-risk-bar" className="flex flex-col" style={{ gap: 6 }}>
      <div style={{ position: "relative", height: 26 }}>
        <div style={{ position: "absolute", top: 12, left: 0, right: 0, height: 6, borderRadius: 3, background: "var(--bg-2)" }} />
        <div title="Risk: entry to stop" style={{ position: "absolute", top: 12, height: 6, left: `${at(stop)}%`, width: `${at(entry) - at(stop)}%`, background: "var(--cp-danger)", opacity: 0.7, borderRadius: "3px 0 0 3px" }} />
        {target != null && (
          <div title="Reward: entry to target" style={{ position: "absolute", top: 12, height: 6, left: `${at(entry)}%`, width: `${at(target) - at(entry)}%`, background: "var(--mint)", opacity: 0.7, borderRadius: "0 3px 3px 0" }} />
        )}
        <div aria-hidden style={{ position: "absolute", top: 8, height: 14, width: 2, left: `calc(${at(entry)}% - 1px)`, background: "var(--cp-ink)" }} />
        {ltp != null && (
          <div data-testid="desk-risk-ltp" title={`Last close ${fmtPrice(ltp)}`} style={{ position: "absolute", top: 0, left: `${at(ltp)}%`, transform: "translateX(-50%)", display: "flex", flexDirection: "column", alignItems: "center" }}>
            <span style={{ width: 0, height: 0, borderLeft: "5px solid transparent", borderRight: "5px solid transparent", borderTop: "7px solid var(--cp-indigo)" }} />
            <span style={{ width: 2, height: 16, background: "var(--cp-indigo)" }} />
          </div>
        )}
      </div>
      <div className="flex flex-wrap justify-between" style={{ gap: "2px 8px", fontSize: 11.5 }}>
        <span data-testid="desk-risk-stop" className="cp-num" style={{ color: "var(--cp-danger)" }}>Stop {fmtPrice(stop)}</span>
        <span data-testid="desk-risk-entry" className="cp-num" style={{ color: "var(--cp-ink)" }}>Entry {fmtPrice(entry)}</span>
        <span data-testid="desk-risk-target" className="cp-num" style={{ color: target != null ? "var(--mint)" : "var(--cp-ink-3)" }}>{target != null ? `Target ${fmtPrice(target)}` : "No target"}</span>
      </div>
      {ltp != null && (
        <span className="cp-mono-note" style={{ color: "var(--cp-indigo)" }}>
          ▼ Last close {fmtPrice(ltp)}{ltp < stop ? " · below the stop" : target != null && ltp > target ? " · above the target" : ""}
        </span>
      )}
    </div>
  );
}

export function RiskDesk({ symbol, setup, lastClose }: { symbol: string; setup: DeskSetup | null; lastClose: number | null }) {
  const oddsQ = useDeskOdds("p_up5_1d");
  const stockQ = useStockOdds(symbol);
  const [capital, setCapital] = useState<number>(500_000);
  const [riskBps, setRiskBps] = useState<number>(100);

  const odds = oddsQ.data;
  const stock = stockQ.data;
  const sym = symbol.toUpperCase();
  const fromLatest = odds?.kind === "final" ? odds.bySymbol.get(sym) ?? null : null;
  const stockData = stock?.kind === "ok" ? stock.data : null;
  const p = fromLatest?.p ?? stockData?.estimates.p_up5_1d ?? null;
  const events = fromLatest?.events ?? (stockData ? stockData.events.length : null);
  const run = odds?.kind === "final" ? odds.data.run : stockData?.run ?? null;
  const record = odds?.kind === "final" ? odds.data.record : null;

  // ── validation gate ──
  const checks: Array<{ key: string; label: string; ok: boolean }> = [
    { key: "published", label: run ? `Model run published for the next session (${fmtDay(run.target_session)})` : "Model run published for the next session", ok: run != null },
    { key: "horizon", label: "Horizon: the next session only", ok: true },
    { key: "events", label: `Events on record for ${sym}: ${events == null ? "unknown" : fmtNum(events)}`, ok: events != null && events > 0 },
    { key: "record", label: "Out-of-sample record present", ok: record != null },
    { key: "verdict", label: "Run counts toward the official record", ok: run?.counts_toward_verdict === true },
  ];
  const passed = checks.filter((c) => c.ok).length;
  const allPassed = passed === checks.length;

  // ── P(+5% next session) tile ──
  let pValue: ReactNode = "—";
  let pNote: ReactNode;
  let pTone: Tone = "ink";
  const locked = odds?.kind === "no_access" || stock?.kind === "locked";
  const withheld = odds?.kind === "withheld" ? odds.reason : stock?.kind === "withheld" ? stock.reason : null;
  if (p != null) {
    pValue = pct1(p);
    if (allPassed) {
      pTone = "mint";
      pNote = <>Model estimate for {run ? fmtDay(run.target_session) : "the next session"}{odds?.kind === "final" ? <> · base rate {pct1(odds.data.base_rate)}</> : null}.</>;
    } else {
      pNote = <>Withheld from high-confidence display: {passed} of {checks.length} checks passed.</>;
    }
  } else if (locked) {
    pNote = "Move probabilities are not enabled for this account.";
  } else if (withheld) {
    pNote = <>Withheld: {withheld}.</>;
  } else if (odds?.kind === "not_published") {
    pNote = <>The model has not published for {fmtDay(odds.expectedSession)} yet.</>;
  } else if (oddsQ.isPending || stockQ.isPending) {
    pValue = "…";
    pNote = "Loading the move-odds model.";
  } else if (oddsQ.isError && stockQ.isError) {
    pNote = "The move-odds model didn’t load.";
  } else {
    pNote = `No estimate for ${sym} in the published run.`;
  }

  const recordTile = record
    ? { v: pct1(record.top10_hit_rate), s: <>Top-10 hit rate, out-of-sample {record.window_label} ({fmtNum(record.sessions)} sessions) vs base rate {pct1(record.base_rate)}. The model’s record, not this stock’s.</> }
    : { v: "—", s: odds?.kind === "final" ? "No out-of-sample record is published for this estimate." : locked ? "Not enabled for this account." : "Needs the model’s published run." };

  // ── levels and sizing ──
  const entry = setup?.entry ?? null;
  const stop = setup?.stop ?? null;
  const target = setup?.target ?? null;
  const sizing = sizePosition(capital, riskBps, entry, stop, target);
  const rr = setup?.riskReward ?? null;

  return (
    <section data-testid="desk-risk" className="cp-card flex min-w-0 flex-col">
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "6px 12px", padding: "14px 16px", borderBottom: "1px solid var(--cp-line)" }}>
        <span className="cp-eyebrow">05 · Risk desk</span>
        {setup && <span data-testid="desk-risk-status" data-status={setup.status}><Pill tone={STATUS_LABEL[setup.status].tone}>{STATUS_LABEL[setup.status].label}</Pill></span>}
      </div>

      <div className="flex flex-col" style={{ gap: 16, padding: 16 }}>
        <div className="flex flex-wrap items-end justify-between" style={{ gap: "8px 16px" }}>
          <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
            <span className="cp-mono-note">Scenario</span>
            <span data-testid="desk-risk-scenario" style={{ fontSize: 14, color: "var(--cp-ink)" }}>{setup ? setupLabel(setup) : "Not on today’s scanner"}</span>
          </div>
          <div className="flex flex-col items-end" style={{ gap: 2 }}>
            <span className="cp-mono-note">Reward : risk</span>
            <span data-testid="desk-risk-rr" style={{ fontFamily: "var(--display)", fontSize: 36, lineHeight: 1, color: rr != null ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>
              {rr != null ? `${fmtNum(rr, 2)} : 1` : "—"}
            </span>
          </div>
        </div>

        {setup && entry != null && stop != null && entry > stop ? (
          <RiskBar entry={entry} stop={stop} target={target} ltp={lastClose} />
        ) : (
          <span data-testid="desk-risk-nolevels" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            {setup ? "This setup has no entry with a stop below it, so there is nothing to draw." : "Not on today’s scanner — no levels."}
          </span>
        )}
        {setup && target == null && entry != null && (
          <span className="cp-mono-note">Reward : risk needs a target; only the scanner’s picks carry one.</span>
        )}

        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
          <MiniTile k="P(+5% next session)" v={pValue} s={pNote} tone={pTone} testId="desk-risk-p5" />
          <MiniTile k="Model record" v={recordTile.v} s={recordTile.s} testId="desk-risk-record" />
        </div>

        <div data-testid="desk-risk-gate" className="flex flex-col" style={{ gap: 8 }}>
          <div className="flex items-baseline justify-between" style={{ gap: 8 }}>
            <span className="cp-eyebrow">Validation gate</span>
            <span data-testid="desk-risk-gate-count" className="cp-num" style={{ fontSize: 12, color: allPassed ? "var(--mint)" : "var(--amber)" }}>{passed} of {checks.length} passed</span>
          </div>
          <ul className="m-0 flex flex-col" style={{ gap: 6, padding: 0, listStyle: "none" }}>
            {checks.map((c) => (
              <li key={c.key} data-testid={`desk-risk-check-${c.key}`} data-ok={c.ok} className="flex items-start" style={{ gap: 8, fontSize: 12.5, lineHeight: 1.45, color: "var(--cp-ink-2)" }}>
                <span aria-hidden style={{ flex: "none", width: 14, color: c.ok ? "var(--mint)" : "var(--cp-danger)", fontFamily: "var(--mono)" }}>{c.ok ? "✓" : "✕"}</span>
                <span><span className="sr-only">{c.ok ? "Passed: " : "Failed: "}</span>{c.label}</span>
              </li>
            ))}
          </ul>
        </div>

        <div data-testid="desk-risk-size" className="flex flex-col" style={{ gap: 10, paddingTop: 12, borderTop: "1px solid var(--cp-line)" }}>
          <span className="cp-eyebrow">Position size</span>
          <div className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
            <span className="cp-mono-note">Capital</span>
            <Toggle label="Capital" value={capital} options={CAPITALS} onChange={setCapital} idPrefix="desk-risk-capital" />
          </div>
          <div className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
            <span className="cp-mono-note">Risk per trade</span>
            <Toggle label="Risk per trade" value={riskBps} options={RISKS.map((r) => ({ value: r.bps, label: r.label, id: r.id }))} onChange={setRiskBps} idPrefix="desk-risk-pct" />
          </div>
          {sizing ? (
            <>
              <dl className="m-0 grid" style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: "6px 12px", fontSize: 12.5 }}>
                <dt style={{ color: "var(--cp-ink-3)" }}>Quantity</dt>
                <dd className="m-0 cp-num" style={{ textAlign: "right", color: "var(--cp-ink)" }}><span data-testid="desk-risk-qty">{fmtNum(sizing.qty)}</span> shares</dd>
                <dt style={{ color: "var(--cp-ink-3)" }}>Capital used</dt>
                <dd className="m-0 cp-num" style={{ textAlign: "right", color: sizing.overLimit ? "var(--amber)" : "var(--cp-ink)" }}>
                  <span data-testid="desk-risk-used">{fmtINR(sizing.used)}</span> · <span data-testid="desk-risk-used-pct">{fmtPct(sizing.usedPct, { digits: 1 })}</span>
                </dd>
                <dt style={{ color: "var(--cp-ink-3)" }}>Max loss at the stop</dt>
                <dd className="m-0 cp-num" style={{ textAlign: "right", color: "var(--cp-danger)" }}><span data-testid="desk-risk-maxloss">{fmtINR(sizing.maxLoss)}</span></dd>
                <dt style={{ color: "var(--cp-ink-3)" }}>At target</dt>
                <dd className="m-0 cp-num" style={{ textAlign: "right", color: sizing.atTarget != null ? "var(--mint)" : "var(--cp-ink-3)" }}>
                  <span data-testid="desk-risk-attarget">{sizing.atTarget != null ? fmtINR(sizing.atTarget, { signed: true }) : "—"}</span>
                </dd>
              </dl>
              <span className="cp-mono-note" style={{ lineHeight: 1.6 }}>
                {fmtINR(capital)} × {RISKS.find((r) => r.bps === riskBps)?.label} = {fmtINR(sizing.riskBudget)} at risk ÷ {fmtPrice(sizing.perShare)} a share (entry − stop). Max loss is before brokerage and taxes.
              </span>
              {sizing.qty === 0 && (
                <span data-testid="desk-risk-zero" style={{ fontSize: 12, color: "var(--amber)" }}>The risk budget is smaller than one share’s risk, so no whole share fits.</span>
              )}
              {sizing.overLimit && (
                <span data-testid="desk-risk-warn" role="status" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)", padding: "8px 10px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
                  Capital used is above a 25% single-stock limit; {fmtNum(sizing.limitQty)} shares keeps you inside it.
                </span>
              )}
            </>
          ) : (
            <span data-testid="desk-risk-nosize" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
              Sizing needs both an entry and a stop below it{setup ? "; this setup does not have both." : ", and this stock has no scanner levels."}
            </span>
          )}
        </div>

        <div className="flex flex-col" style={{ gap: 10, paddingTop: 12, borderTop: "1px solid var(--cp-line)" }}>
          <div className="flex flex-col" style={{ gap: 4 }}>
            <Btn disabled aria-describedby="desk-risk-paper-note" data-testid="desk-risk-paper">Add to paper trades</Btn>
            <span id="desk-risk-paper-note" data-testid="desk-risk-paper-note" style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>
              Not connected yet: paper trades are chosen by the model engine, and nothing here can add one.
            </span>
          </div>
          <div className="flex flex-col" style={{ gap: 4 }}>
            <Btn disabled aria-describedby="desk-risk-alert-note" data-testid="desk-risk-alert">Alert on trigger</Btn>
            <span id="desk-risk-alert-note" data-testid="desk-risk-alert-note" style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>
              Not connected yet: there is no price-alert service to watch the trigger.
            </span>
          </div>
        </div>

        <Footnote>Nivesh reads broker positions and cannot place orders. Sizing is worked out here from the scanner’s levels; nothing is saved.</Footnote>
      </div>
    </section>
  );
}
