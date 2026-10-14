/**
 * Smart trading desk — Options & futures lab: the pieces the tab draws from an
 * end-of-day chain and the futures list (trading/fno.ts):
 *
 *   GET /api/fno/{symbol}/chain?expiry=   one expiry by strike, plus a summary over every strike
 *   GET /api/fno/{symbol}/futures         the latest day's futures, each with its basis to the spot
 *
 * Everything is one NSE F&O bhavcopy a day, after the close. Implied volatility
 * and the expected move are the chain route's model estimates (Black-76 on
 * end-of-day prices) and read "Not available" when the route sent none. The
 * call wall (R) and put wall (S) are the strikes with the most call and put
 * open interest over the whole expiry; max pain (MP) is the route's own. They
 * describe positions at the close; nothing here calls them targets.
 *
 * Calls are drawn in the danger colour and puts in mint, as on the Options lab.
 */
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { EmptyBlock, LoadingBlock, TONE_COLOR, fmtNum, signTone, type Tone } from "../../components/ui";
import { fmtIv, fmtMove } from "../trading/ModelViews";
import { fmtLevel } from "../trading/PayoffResult";
import { nearestFuture, strikesAround, type ChainState, type FnoChain, type FnoFuture, type FnoFutures, type FnoResult, type FnoSide, type FnoSummary } from "../trading/fno";
import { Choices, QueryProblem, fmtDay, fmtQty, fmtSigned } from "../trading/parts";

const CALL_COLOR = "var(--cp-danger)";
const PUT_COLOR = "var(--mint)";

/** The sentence for an underlying with no F&O rows; the brief's wording, used by the tab and the spec. */
export const noRowsTitle = (symbol: string) => `No F&O rows for ${symbol} on the latest day`;

// ── loading / error / no rows ────────────────────────────────────────────

/** The chain's loading, error (with retry) and no-rows states; `children` once it has loaded. */
export function FnoGate({ symbol, state, testId, children }: { symbol: string; state: ChainState; testId: string; children: (chain: FnoChain) => ReactNode }) {
  if (state.status === "loading") return <div data-testid={`${testId}-loading`}><LoadingBlock label={`Loading the ${symbol} chain`} rows={3} /></div>;
  if (state.status === "error") return <div data-testid={`${testId}-error`}><QueryProblem what={`The ${symbol} option chain`} error={state.error} onRetry={state.retry} /></div>;
  if (state.status === "none") {
    return (
      <div data-testid={`${testId}-none`}>
        <EmptyBlock
          title={noRowsTitle(symbol)}
          body={`The server said: “${state.message}”. Only indices and stocks in NSE’s F&O segment have contracts in the end-of-day file, so check the ticker.`}
        />
      </div>
    );
  }
  return <>{children(state.chain)}</>;
}

// ── futures ──────────────────────────────────────────────────────────────

export interface NearFuture {
  future: FnoFuture;
  spot: number | null;
  asOf: string;
}

/** The nearest future from a loaded futures list; null while loading, on an error, for no rows or no contract. */
export function nearFutureOf(data: FnoResult<FnoFutures> | undefined): NearFuture | null {
  if (!data || data.kind !== "ok") return null;
  const f = nearestFuture(data.data);
  return f ? { future: f, spot: data.data.spot, asOf: data.data.as_of } : null;
}

/** "Premium to" / "Discount to" / "Level with" the spot, from the basis; null without one. */
export function basisWords(basis: number | null): string | null {
  if (basis == null) return null;
  return basis > 0 ? "premium" : basis < 0 ? "discount" : "level";
}

// ── stats grid ───────────────────────────────────────────────────────────

export interface StatTile {
  k: string;
  v: ReactNode;
  s: ReactNode;
  testId: string;
  tone?: Tone;
}

/** Headline tiles: serif figure, one quiet line under it, in `columns` columns (two on a phone, four otherwise). */
export function StatGrid({ tiles, testId, columns }: { tiles: StatTile[]; testId?: string; columns: number }) {
  return (
    <div data-testid={testId} className="grid" style={{ gridTemplateColumns: `repeat(${columns},minmax(0,1fr))`, gap: 8 }}>
      {tiles.map((t) => (
        <div key={t.k} className="cp-card flex flex-col min-w-0" style={{ gap: 4, padding: "12px 14px" }}>
          <span className="cp-eyebrow">{t.k}</span>
          <span data-testid={t.testId} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 21, lineHeight: 1.15, color: TONE_COLOR[t.tone ?? "ink"], overflowWrap: "anywhere" }}>{t.v}</span>
          <span style={{ fontSize: 11, lineHeight: 1.4, color: "var(--cp-ink-3)" }}>{t.s}</span>
        </div>
      ))}
    </div>
  );
}

/** The eight tiles of the design, from the chain summary and the nearest future. */
export function chainTiles(s: FnoSummary, near: NearFuture | null, futuresNote: string): StatTile[] {
  const basis = near?.future.basis ?? null;
  const words = basisWords(basis);
  return [
    {
      k: "ATM implied volatility",
      v: fmtIv(s.atm_iv),
      s: s.atm_iv != null && s.atm_strike != null ? `A year · model estimate at the ${fmtLevel(s.atm_strike)} strike` : "No model estimate at the ATM strike",
      testId: "desk-fno-atm-iv",
    },
    {
      k: "Expected move to expiry",
      v: fmtMove(s.expected_move),
      s: s.expected_move != null
        ? `${s.expected_move_pct != null ? `${fmtNum(s.expected_move_pct, 2)}% of spot · ` : ""}ATM straddle at the close`
        : "Needs a call and a put close at the ATM strike",
      testId: "desk-fno-expected-move",
    },
    {
      k: "Futures · nearest",
      v: near?.future.settle != null ? fmtNum(near.future.settle, 2) : "—",
      s: near
        ? `${fmtDay(near.future.expiry)} · ${words == null ? "no basis" : words === "level" ? "level with the spot" : `${fmtSigned(basis)} ${words} to spot`}`
        : futuresNote,
      testId: "desk-fno-futures",
    },
    {
      k: "Days to expiry",
      v: s.days_to_expiry == null ? "—" : fmtNum(s.days_to_expiry),
      s: `Calendar days, ${fmtDay(s.as_of)} to ${fmtDay(s.expiry)}`,
      testId: "desk-fno-days",
    },
    {
      k: "Put-call ratio · OI",
      v: s.pcr == null ? "—" : fmtNum(s.pcr, 2),
      s: "Put OI ÷ call OI, every strike",
      testId: "desk-fno-pcr",
    },
    {
      k: "Max pain",
      v: s.max_pain == null ? "—" : fmtLevel(s.max_pain),
      s: "Strike where open options pay out least at expiry",
      testId: "desk-fno-max-pain",
    },
    {
      k: "OI range",
      v: s.max_put_oi && s.max_call_oi ? `${fmtLevel(s.max_put_oi.strike)} – ${fmtLevel(s.max_call_oi.strike)}` : "—",
      s: "Most put OI → most call OI",
      testId: "desk-fno-oi-range",
    },
    {
      k: "Futures OI change",
      v: near ? fmtQty(near.future.change_in_oi, { signed: true }) : "—",
      s: near ? `Nearest future · ${fmtDay(near.future.expiry)}` : futuresNote,
      testId: "desk-fno-fut-oi-change",
      tone: near ? signTone(near.future.change_in_oi) : "ink",
    },
  ];
}

// ── option chain, open interest by strike ────────────────────────────────

type ChainWindow = "5" | "10" | "20";

function OiBar({ share, color, leftwards }: { share: number; color: string; leftwards?: boolean }) {
  const w = Math.max(0, Math.min(1, share)) * 100;
  return (
    <span aria-hidden="true" style={{ position: "relative", display: "block", flex: "1 1 0", minWidth: 24, height: 8, borderRadius: 2, background: "var(--bg-2)" }}>
      <span style={{ position: "absolute", top: 0, bottom: 0, [leftwards ? "right" : "left"]: 0, width: `${w}%`, borderRadius: 2, background: color }} />
    </span>
  );
}

const TAG_TONE: Record<string, Tone> = { ATM: "indigo", R: "danger", S: "mint", MP: "ink" };
const TAG_TITLE: Record<string, string> = {
  ATM: "Strike nearest the end-of-day spot",
  R: "Call wall: the strike with the most call open interest in the expiry",
  S: "Put wall: the strike with the most put open interest in the expiry",
  MP: "Max pain",
};

/** Which of ATM, R, S and MP a strike is. */
export function strikeTags(s: FnoSummary, strike: number): string[] {
  const tags: string[] = [];
  if (s.atm_strike === strike) tags.push("ATM");
  if (s.max_call_oi?.strike === strike) tags.push("R");
  if (s.max_put_oi?.strike === strike) tags.push("S");
  if (s.max_pain === strike) tags.push("MP");
  return tags;
}

/** One plain read of the summary: where the open interest sits, the PCR and max pain. Facts only. */
export function chainRead(s: FnoSummary): string {
  const parts: string[] = [];
  if (s.max_call_oi) parts.push(`the most call open interest is at ${fmtLevel(s.max_call_oi.strike)} (${fmtQty(s.max_call_oi.oi)})`);
  if (s.max_put_oi) parts.push(`the most put open interest at ${fmtLevel(s.max_put_oi.strike)} (${fmtQty(s.max_put_oi.oi)})`);
  if (s.pcr != null) parts.push(`the put-call ratio on open interest is ${fmtNum(s.pcr, 2)}`);
  if (s.max_pain != null) parts.push(`max pain is ${fmtLevel(s.max_pain)}`);
  if (!parts.length) return "This expiry has no open interest to read.";
  let out = `For the ${fmtDay(s.expiry)} expiry, ${parts.join(", ")}.`;
  out = out.charAt(0).toUpperCase() + out.slice(1);
  if (s.spot != null && s.max_call_oi && s.max_put_oi) {
    const lo = Math.min(s.max_put_oi.strike, s.max_call_oi.strike);
    const hi = Math.max(s.max_put_oi.strike, s.max_call_oi.strike);
    const where = s.spot < lo ? "below both" : s.spot > hi ? "above both" : "between the two";
    out += ` The end-of-day spot of ${fmtNum(s.spot, 2)} is ${where}.`;
  }
  return `${out} These are positions at the close, not price targets.`;
}

const signedQty = (n: number | null | undefined) => fmtQty(n, { signed: true });

function sideFigures(side: FnoSide | null) {
  return { oi: side?.oi ?? null, change: side?.change_in_oi ?? null, close: side?.close ?? null };
}

export function ChainOiTable({ chain }: { chain: FnoChain }) {
  const [win, setWin] = useState<ChainWindow>("10");
  // On a narrow screen the table scrolls sideways; start it centred on the strike column, so calls sit to the left and puts to the right.
  const scroller = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && el.scrollWidth > el.clientWidth) el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2;
  }, [chain, win]);
  const s = chain.summary;
  const rows = strikesAround(chain, Number(win));
  const max = Math.max(1, ...rows.flatMap((r) => [r.call?.oi ?? 0, r.put?.oi ?? 0]));
  const template = "minmax(0,0.9fr) minmax(0,1.4fr) minmax(0,0.8fr) 118px minmax(0,0.8fr) minmax(0,1.4fr) minmax(0,0.9fr)";
  const head = (key: string, label: string, align: "left" | "right" | "center") => (
    <span key={key} role="columnheader" className="cp-mono-note" style={{ textAlign: align, minWidth: 0 }}>{label}</span>
  );
  const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;
  return (
    <div data-testid="desk-fno-chain" className="cp-card flex flex-col min-w-0" style={{ overflow: "hidden" }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px", padding: "12px 16px", borderBottom: "1px solid var(--cp-line)" }}>
        <span className="cp-eyebrow">{chain.symbol} · {fmtDay(s.expiry)} expiry · open interest by strike</span>
        <Choices<ChainWindow>
          label="Strikes shown"
          testId="desk-fno-window"
          value={win}
          onChange={setWin}
          options={[{ value: "5", label: "±5" }, { value: "10", label: "±10" }, { value: "20", label: "±20" }]}
        />
      </div>
      <div ref={scroller} data-testid="desk-fno-chain-scroll" className="cp-scroll overflow-x-auto" role="table" aria-label={`${chain.symbol} open interest by strike, ${fmtDay(s.expiry)} expiry`}>
        <div style={{ minWidth: 760 }}>
          <div role="row" className="grid" style={{ gridTemplateColumns: template, gap: 10, padding: "10px 16px" }}>
            {head("call-chg", "Call OI chg", "left")}
            {head("call-oi", "Call OI", "left")}
            {head("call-close", "Call close ₹", "right")}
            {head("strike", "Strike", "center")}
            {head("put-close", "Put close ₹", "left")}
            {head("put-oi", "Put OI", "right")}
            {head("put-chg", "Put OI chg", "right")}
          </div>
          {rows.map((r) => {
            const c = sideFigures(r.call);
            const p = sideFigures(r.put);
            const tags = strikeTags(s, r.strike);
            const atm = tags.includes("ATM");
            return (
              <div
                key={r.strike}
                role="row"
                data-testid="desk-fno-chain-row"
                data-strike={r.strike}
                data-atm={atm ? "true" : undefined}
                className="grid items-center"
                style={{ gridTemplateColumns: template, gap: 10, padding: "7px 16px", borderTop: "1px solid var(--cp-line)", fontSize: 12.5, background: atm ? "var(--cp-indigo-soft)" : undefined }}
              >
                <span role="cell" data-col="call-oi-change" className="cp-num" style={{ color: c.change ? TONE_COLOR[signTone(c.change)] : "var(--cp-ink-3)" }}>{signedQty(c.change)}</span>
                <span role="cell" data-col="call-oi" className="flex items-center" style={{ gap: 6, minWidth: 0 }}>
                  <span className="cp-num" style={{ flex: "none", fontSize: 11, color: "var(--cp-ink-2)" }}>{fmtQty(c.oi)}</span>
                  <OiBar share={(c.oi ?? 0) / max} color={CALL_COLOR} leftwards />
                </span>
                <span role="cell" data-col="call-close" className="cp-num" style={{ textAlign: "right", color: "var(--cp-ink)" }}>{c.close == null ? "—" : fmtNum(c.close, 2)}</span>
                <span role="cell" data-col="strike" className="flex flex-col items-center" style={{ gap: 3 }}>
                  <span style={{ fontFamily: "var(--display)", fontSize: 17, lineHeight: 1, color: "var(--cp-ink)" }}>{fmtLevel(r.strike)}</span>
                  {tags.length > 0 && (
                    <span className="flex flex-wrap justify-center" style={{ gap: 3 }}>
                      {tags.map((t) => (
                        <span key={t} data-testid={`desk-fno-tag-${t.toLowerCase()}`} title={TAG_TITLE[t]} className="cp-pill" data-tone={TAG_TONE[t]} style={{ padding: "1px 5px", fontSize: 8.5 }}>{t}</span>
                      ))}
                    </span>
                  )}
                </span>
                <span role="cell" data-col="put-close" className="cp-num" style={{ color: "var(--cp-ink)" }}>{p.close == null ? "—" : fmtNum(p.close, 2)}</span>
                <span role="cell" data-col="put-oi" className="flex items-center" style={{ gap: 6, minWidth: 0 }}>
                  <OiBar share={(p.oi ?? 0) / max} color={PUT_COLOR} />
                  <span className="cp-num" style={{ flex: "none", fontSize: 11, color: "var(--cp-ink-2)" }}>{fmtQty(p.oi)}</span>
                </span>
                <span role="cell" data-col="put-oi-change" className="cp-num" style={{ textAlign: "right", color: p.change ? TONE_COLOR[signTone(p.change)] : "var(--cp-ink-3)" }}>{signedQty(p.change)}</span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="flex flex-col" style={{ gap: 6, padding: "12px 16px", borderTop: "1px solid var(--cp-line)" }}>
        <span data-testid="desk-fno-chain-read" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{chainRead(s)}</span>
        <span style={quiet}>
          ATM: the strike nearest the end-of-day spot. R (call wall) and S (put wall): the strikes with the most call and put open interest in the whole expiry. MP: max pain.
          {` Showing ${fmtNum(rows.length)} of the expiry’s ${fmtNum(chain.strike_count)} strikes; the tags and the totals cover all of them.`}
          {" Close is the end-of-day closing price, not a live quote."}
        </span>
        <span className="cp-mono-note" style={{ lineHeight: 1.6 }}>NSE F&amp;O bhavcopy · end of day · as of {fmtDay(s.as_of)}</span>
      </div>
    </div>
  );
}

// ── NIFTY & BANKNIFTY ────────────────────────────────────────────────────

/** Put wall, call wall, the spot and the expected-move band on one line. */
export function OiRangeBar({ s, testId }: { s: FnoSummary; testId: string }) {
  const put = s.max_put_oi?.strike ?? null;
  const call = s.max_call_oi?.strike ?? null;
  const spot = s.spot;
  const em = s.expected_move ?? null;
  const pts = [put, call, spot, spot != null && em != null ? spot - em : null, spot != null && em != null ? spot + em : null].filter((x): x is number => x != null);
  if (pts.length < 2) return null;
  const lo0 = Math.min(...pts);
  const hi0 = Math.max(...pts);
  const pad = (hi0 - lo0) * 0.08 || Math.abs(hi0) * 0.01 || 1;
  const lo = lo0 - pad;
  const hi = hi0 + pad;
  const at = (x: number) => `${((x - lo) / (hi - lo)) * 100}%`;
  const mark = (x: number, color: string, label: string, key: string) => (
    <span key={key} title={label} aria-hidden="true" style={{ position: "absolute", top: -4, bottom: -4, left: at(x), width: 3, marginLeft: -1.5, borderRadius: 2, background: color }} />
  );
  const legend: Array<{ k: string; v: string; color: string; testId: string }> = [];
  if (put != null) legend.push({ k: "Put wall", v: fmtLevel(put), color: PUT_COLOR, testId: `${testId}-put-wall` });
  if (spot != null) legend.push({ k: "Spot", v: fmtNum(spot, 2), color: "var(--cp-ink)", testId: `${testId}-bar-spot` });
  if (call != null) legend.push({ k: "Call wall", v: fmtLevel(call), color: CALL_COLOR, testId: `${testId}-call-wall` });
  const label = [
    put != null ? `put wall ${fmtLevel(put)}` : null,
    spot != null ? `spot ${fmtNum(spot, 2)}` : null,
    call != null ? `call wall ${fmtLevel(call)}` : null,
    spot != null && em != null ? `expected move ${fmtNum(spot - em, 2)} to ${fmtNum(spot + em, 2)}` : null,
  ].filter(Boolean).join(", ");
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <div role="img" aria-label={`Open-interest range: ${label}`} style={{ position: "relative", height: 10, margin: "4px 2px", borderRadius: 5, background: "var(--bg-2)" }}>
        {spot != null && em != null && (
          <span title={`Expected move ${fmtNum(spot - em, 2)} – ${fmtNum(spot + em, 2)}`} aria-hidden="true" style={{ position: "absolute", top: 0, bottom: 0, left: at(spot - em), width: `${((2 * em) / (hi - lo)) * 100}%`, borderRadius: 5, background: "var(--indigo-line)" }} />
        )}
        {put != null && mark(put, PUT_COLOR, `Put wall ${fmtLevel(put)}`, "put")}
        {call != null && mark(call, CALL_COLOR, `Call wall ${fmtLevel(call)}`, "call")}
        {spot != null && (
          <span title={`Spot ${fmtNum(spot, 2)}`} aria-hidden="true" style={{ position: "absolute", top: "50%", left: at(spot), width: 12, height: 12, margin: "-6px 0 0 -6px", borderRadius: "50%", background: "var(--cp-ink)", boxShadow: "0 0 0 2px var(--bg-1)" }} />
        )}
      </div>
      <div className="flex flex-wrap" style={{ gap: "4px 14px", fontSize: 11 }}>
        {legend.map((l) => (
          <span key={l.k} className="flex items-center" style={{ gap: 6, color: "var(--cp-ink-3)" }}>
            <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2, background: l.color }} />
            {l.k} <span data-testid={l.testId} className="cp-num" style={{ color: "var(--cp-ink)" }}>{l.v}</span>
          </span>
        ))}
        {spot != null && em != null && (
          <span className="flex items-center" style={{ gap: 6, color: "var(--cp-ink-3)" }}>
            <span aria-hidden="true" style={{ width: 14, height: 8, borderRadius: 2, background: "var(--indigo-line)" }} />
            Expected move <span className="cp-num" style={{ color: "var(--cp-ink)" }}>{fmtNum(spot - em, 2)}–{fmtNum(spot + em, 2)}</span>
          </span>
        )}
      </div>
    </div>
  );
}

/** A label and a figure on one line of an index card. */
export function CardRow({ k, children, testId }: { k: string; children: ReactNode; testId: string }) {
  return (
    <div className="flex justify-between" style={{ gap: 12, padding: "7px 0", borderTop: "1px solid var(--cp-line)", fontSize: 13 }}>
      <span style={{ color: "var(--cp-ink-3)" }}>{k}</span>
      <span data-testid={testId} className="cp-num" style={{ textAlign: "right", color: "var(--cp-ink)", minWidth: 0, overflowWrap: "anywhere" }}>{children}</span>
    </div>
  );
}
