/**
 * Chart Analysis v2 — OPTION CHAIN · <expiry> with OI | GREEKS (design item 6; test_reports/chart_analysis_v2_TESTCASES.md
 * U3, U4, U5, U11).
 *
 *   rows            the chain the page loaded (useAnalysisChain): ±6 strikes around the ATM strike (rowsAround)
 *   OI mode         OI (Indian units, as the desk's chain shows it) and OI Δ% = OI change / previous OI
 *   GREEKS mode     IV, VEGA, GAMMA, THETA, DELTA: the chain route's model estimates per unit (end of day)
 *   LTP             the contract's close in the NSE F&O bhavcopy (chain.asOf). In NSE hours, a live Kite quote replaces it
 *                   when that contract traded today (POST /api/live/fno-quotes via useFnoLive), marked and labelled
 *   B / S           basket.toggleOption at the price shown, with where that price came from
 *
 * Consolidated sums OI over the expiries, so it has no prices or Greeks and nothing can be picked from it. Nothing here is
 * sent to a broker.
 */
import { useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { fmtNum, fmtPct } from "../../../../../components/ui";
import { fmtDay, fmtQty } from "../../../../trading/parts";
import { inNseHours, istParts, useNow } from "../../../overview-data";
import { useFnoLive } from "../../../strategy/top-live";
import { useBasket, type BasketSide } from "./basket";
import { SLOT_NAME, rowsAround, type AnalysisChain, type SideRow, type StrikeRow } from "./chain-data";
import {
  CELL_LABEL, callCells, chainMinWidth, chainTemplate, contractKey, liveByContract, liveLegsFor, oiChangePct, pickBlock, putCells,
  type ChainCell, type ChainLiveQuote, type ChainMode, type OptionKind,
} from "./reco-data";

const DASH = "—";
const CALL_INK = "var(--cp-danger)";
const PUT_INK = "var(--mint)";
const mono = (size: number): CSSProperties => ({ fontFamily: "var(--mono)", fontSize: size });

export interface OptionChainProps {
  symbol: string;
  chain: AnalysisChain;
  selected: number | null;
  onSelect: (strike: number) => void;
  compact: boolean;
}

/** One cell's text and colour. */
function cell(k: ChainCell, s: SideRow | null): { text: string; color: string } {
  if (!s) return { text: DASH, color: "var(--cp-ink-4)" };
  switch (k) {
    case "oi": return { text: fmtQty(s.oi), color: "var(--cp-ink-2)" };
    case "oiPct": {
      const p = oiChangePct(s.oi, s.oiChange);
      return { text: p == null ? DASH : fmtPct(p, { signed: true, digits: 1 }), color: p == null ? "var(--cp-ink-4)" : p < 0 ? "var(--amber)" : "var(--cp-ink-2)" };
    }
    case "iv": return { text: s.iv == null ? DASH : fmtPct(s.iv, { digits: 1 }), color: "var(--cp-ink-2)" };
    case "vega": return { text: fmtNum(s.vega, 2), color: "var(--cp-ink-2)" };
    case "gamma": return { text: fmtNum(s.gamma, 4), color: "var(--cp-ink-2)" };
    case "theta": return { text: fmtNum(s.theta, 2), color: "var(--amber)" };
    case "delta": return { text: fmtNum(s.delta, 2), color: "var(--cp-ink-2)" };
    default: return { text: DASH, color: "var(--cp-ink-4)" };
  }
}

function ModeButton({ on, disabled, title, onClick, testId, children }: { on: boolean; disabled?: boolean; title?: string; onClick: () => void; testId: string; children: string }) {
  return (
    <button type="button" data-testid={testId} aria-pressed={on} disabled={disabled} title={title} onClick={onClick}
      style={{
        ...mono(10), letterSpacing: "0.1em", padding: "4px 10px", borderRadius: 6, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
        border: `1px solid ${on ? "var(--cp-indigo)" : "var(--line-3)"}`, background: on ? "var(--cp-indigo-soft)" : "transparent", color: on ? "var(--cp-indigo)" : "var(--cp-ink-2)",
      }}>{children}</button>
  );
}

function PickButton({ side, kind, strike, active, block, onClick }: { side: BasketSide; kind: OptionKind; strike: number; active: boolean; block: string | null; onClick: () => void }) {
  const buy = side === "B";
  const ink = buy ? "var(--mint)" : "var(--cp-danger)";
  const word = buy ? "Buy" : "Sell";
  return (
    <button type="button" data-testid={`ca-chain-${buy ? "b" : "s"}-${kind.toLowerCase()}`} aria-pressed={active} disabled={block != null}
      aria-label={`${word} the ${strike} ${kind}${active ? " (in the basket: press again to remove)" : ""}`}
      title={block ?? `${word} the ${strike} ${kind}: ${active ? "in the basket, press again to remove" : "add to the paper basket"}`}
      onClick={onClick}
      style={{
        width: 22, height: 22, justifySelf: "center", borderRadius: 5, padding: 0, ...mono(10), fontWeight: 600, cursor: block ? "not-allowed" : "pointer",
        opacity: block ? 0.35 : 1,
        border: `1px solid ${active ? ink : "var(--line-3)"}`, background: active ? ink : "transparent", color: active ? "var(--bg-0)" : ink,
      }}>{side}</button>
  );
}

export function OptionChain({ symbol, chain, selected, onSelect, compact }: OptionChainProps): JSX.Element {
  const basket = useBasket();
  const [modeRaw, setMode] = useState<ChainMode>("oi");
  const [touched, setTouched] = useState(false);
  const mode: ChainMode = chain.tradable ? modeRaw : "oi";
  const rows = useMemo(() => rowsAround(chain, 6), [chain]);
  const calls = callCells(mode, compact);
  const puts = putCells(mode, compact);
  const template = chainTemplate(calls.length, compact);
  const minWidth = chainMinWidth(calls.length, compact);

  // Live quotes in NSE hours only, and only for one expiry (Consolidated has no prices).
  const now = useNow(30_000);
  const ist = istParts(now);
  const liveOn = chain.tradable && chain.expiry != null && inNseHours(ist);
  const req = useMemo(() => liveLegsFor(symbol, chain.expiry, rows), [symbol, chain.expiry, rows]);
  const live = useFnoLive(req.legs, liveOn);
  const liveBy = useMemo(() => (liveOn ? liveByContract(req.at, live.data, ist.iso) : new Map<string, ChainLiveQuote>()), [liveOn, req.at, live.data, ist.iso]);

  // On a phone the grid scrolls inside its box: start it centred on the strike column.
  const scroller = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && el.scrollWidth > el.clientWidth) el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2;
  }, [chain, mode, compact]);

  const closeSource = `NSE F&O bhavcopy close, ${chain.asOf}`;
  const priceOf = (row: StrikeRow, kind: OptionKind) => {
    const q = liveBy.get(contractKey(kind, row.strike));
    if (q) return { value: q.last_price, live: true, source: `Kite live quote, last trade ${q.last_trade_time ?? ""} IST`.replace("  ", " ") };
    const s = kind === "CE" ? row.call : row.put;
    return { value: s?.close ?? null, live: false, source: closeSource };
  };
  const inBasket = (kind: OptionKind, strike: number, side: BasketSide) =>
    basket.legs.some((l) => l.kind === kind && l.strike === strike && l.expiry === chain.expiry && l.side === side);

  const pick = (row: StrikeRow, kind: OptionKind, side: BasketSide, price: { value: number | null; source: string }) => {
    if (price.value == null || chain.lotSize == null) return;
    setTouched(true);
    basket.toggleOption({ kind, side, qty: 1, strike: row.strike, expiry: chain.expiry, entry: price.value, priceSource: price.source, lotSize: chain.lotSize });
  };

  const expName = chain.slot === "consolidated"
    ? `${SLOT_NAME.consolidated} · ${chain.expiries.length} ${chain.expiries.length === 1 ? "expiry" : "expiries"}`
    : `${SLOT_NAME[chain.slot]}${chain.expiry ? ` · ${fmtDay(chain.expiry)}` : ""}`;
  const liveCount = liveBy.size;
  const readAt = live.data?.as_of ? new Date(live.data.as_of) : null;
  const liveAt = readAt && Number.isFinite(readAt.getTime()) ? istParts(readAt).time : null;
  const head: CSSProperties = { ...mono(9.5), color: "var(--cp-ink-3)", letterSpacing: "0.06em", whiteSpace: "nowrap", minWidth: 0 };

  return (
    <section data-testid="ca-chain" data-mode={mode} data-slot={chain.slot} aria-label={`Option chain, ${expName}`} className="flex min-w-0 flex-col">
      <div className="flex flex-wrap items-center" style={{ gap: 8, marginBottom: 8 }}>
        <div data-testid="ca-chain-title" style={{ flex: 1, ...mono(10), letterSpacing: "0.14em", color: "var(--cp-ink-3)", textTransform: "uppercase", minWidth: 0 }}>
          Option chain · {expName}
        </div>
        <div role="group" aria-label="Chain columns" className="flex" style={{ gap: 6 }}>
          <ModeButton testId="ca-chain-mode-oi" on={mode === "oi"} onClick={() => setMode("oi")}>OI</ModeButton>
          <ModeButton testId="ca-chain-mode-greeks" on={mode === "greeks"} disabled={!chain.tradable}
            title={chain.tradable ? "Implied volatility and Greeks, per unit" : "Consolidated has no prices or Greeks: the expiries differ."}
            onClick={() => setMode("greeks")}>GREEKS</ModeButton>
        </div>
      </div>

      <div ref={scroller} data-testid="ca-chain-scroll" className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%", minWidth: 0 }}
        role="table" aria-label={`${symbol} option chain by strike, ${expName}`}>
        <div style={{ minWidth }}>
          <div role="row" data-testid="ca-chain-header" style={{ display: "grid", gridTemplateColumns: template, alignItems: "center", gap: "0 2px", padding: "0 4px 6px", borderBottom: "1px solid var(--line-2)" }}>
            {calls.map((k) => <span key={`c-${k}`} role="columnheader" style={{ ...head, textAlign: "right" }}>{CELL_LABEL[k]}</span>)}
            <span role="columnheader" style={{ ...head, textAlign: "right", color: CALL_INK }}>LTP</span>
            <span role="columnheader" style={{ ...head, gridColumn: "span 2", textAlign: "center" }}>B · S</span>
            <span role="columnheader" style={{ ...head, textAlign: "center" }}>STRIKE</span>
            <span role="columnheader" style={{ ...head, gridColumn: "span 2", textAlign: "center" }}>B · S</span>
            <span role="columnheader" style={{ ...head, textAlign: "left", color: PUT_INK }}>LTP</span>
            {puts.map((k) => <span key={`p-${k}`} role="columnheader" style={{ ...head, textAlign: "left" }}>{CELL_LABEL[k]}</span>)}
          </div>

          {rows.map((r) => {
            const atm = chain.atm != null && r.strike === chain.atm;
            const isSel = selected != null && r.strike === selected;
            const ce = priceOf(r, "CE");
            const pe = priceOf(r, "PE");
            const ceBlock = pickBlock({ chain, side: r.call, kind: "CE", strike: r.strike, price: ce.value, live: ce.live });
            const peBlock = pickBlock({ chain, side: r.put, kind: "PE", strike: r.strike, price: pe.value, live: pe.live });
            const ltp = (p: typeof ce, s: SideRow | null, kind: OptionKind) => {
              const notTraded = !p.live && s?.volume === 0;
              return (
                <span role="cell" data-testid={`ca-chain-ltp-${kind.toLowerCase()}`} data-src={p.value == null ? "none" : p.live ? "live" : "close"} className="cp-num"
                  title={p.value == null ? undefined : notTraded ? `Not traded on ${chain.asOf}: the exchange's carried price, not a trade` : p.source}
                  style={{ textAlign: kind === "CE" ? "right" : "left", color: p.value == null || notTraded ? "var(--cp-ink-4)" : "var(--cp-ink)", whiteSpace: "nowrap", minWidth: 0 }}>
                  {p.live && kind === "PE" && <span aria-label="live" style={{ color: "var(--mint)" }}>• </span>}
                  {p.value == null ? DASH : fmtNum(p.value, 2)}
                  {p.live && kind === "CE" && <span aria-label="live" style={{ color: "var(--mint)" }}> •</span>}
                </span>
              );
            };
            return (
              <div key={r.strike} role="row" data-testid="ca-chain-row" data-strike={r.strike} data-atm={atm ? "true" : undefined} data-selected={isSel ? "true" : undefined}
                style={{
                  display: "grid", gridTemplateColumns: template, alignItems: "center", gap: "0 2px", padding: "5px 4px", borderBottom: "1px solid var(--cp-line)",
                  ...mono(11.5), background: isSel ? "var(--cp-indigo-soft)" : atm ? "var(--cp-line)" : undefined,
                }}>
                {calls.map((k) => { const c = cell(k, r.call); return <span key={`c-${k}`} role="cell" data-col={`call-${k}`} className="cp-num" style={{ textAlign: "right", color: c.color, whiteSpace: "nowrap", minWidth: 0 }}>{c.text}</span>; })}
                {ltp(ce, r.call, "CE")}
                <PickButton side="B" kind="CE" strike={r.strike} active={inBasket("CE", r.strike, "B")} block={ceBlock} onClick={() => pick(r, "CE", "B", ce)} />
                <PickButton side="S" kind="CE" strike={r.strike} active={inBasket("CE", r.strike, "S")} block={ceBlock} onClick={() => pick(r, "CE", "S", ce)} />
                <button type="button" data-testid="ca-chain-strike" aria-pressed={isSel} aria-label={`Select the ${r.strike} strike${atm ? " (at the money)" : ""}`}
                  onClick={() => onSelect(r.strike)} className="cp-num"
                  style={{ ...mono(11.5), fontWeight: atm || isSel ? 600 : 400, textAlign: "center", padding: "2px 0", border: 0, background: "none", cursor: "pointer",
                    color: isSel ? "var(--cp-indigo)" : "var(--cp-ink)" }}>
                  {fmtNum(r.strike, Number.isInteger(r.strike) ? 0 : 2)}
                </button>
                <PickButton side="B" kind="PE" strike={r.strike} active={inBasket("PE", r.strike, "B")} block={peBlock} onClick={() => pick(r, "PE", "B", pe)} />
                <PickButton side="S" kind="PE" strike={r.strike} active={inBasket("PE", r.strike, "S")} block={peBlock} onClick={() => pick(r, "PE", "S", pe)} />
                {ltp(pe, r.put, "PE")}
                {puts.map((k) => { const c = cell(k, r.put); return <span key={`p-${k}`} role="cell" data-col={`put-${k}`} className="cp-num" style={{ textAlign: "left", color: c.color, whiteSpace: "nowrap", minWidth: 0 }}>{c.text}</span>; })}
              </div>
            );
          })}
          {rows.length === 0 && <div data-testid="ca-chain-empty" style={{ padding: "12px 4px", fontSize: 12.5, color: "var(--cp-ink-3)" }}>The chain has no strikes for this expiry.</div>}
        </div>
      </div>

      <div className="flex flex-col" style={{ gap: 4, marginTop: 8 }}>
        {!chain.tradable && (
          <span data-testid="ca-chain-untradable" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>Pick an expiry to trade: legs need one expiry.</span>
        )}
        {touched && basket.refused && (
          <span data-testid="ca-chain-refused" role="status" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-danger)" }}>{basket.refused}</span>
        )}
        <span data-testid="ca-chain-source" className="cp-mono-note" style={{ lineHeight: 1.6, textTransform: "none", letterSpacing: "0.04em" }}>
          {chain.tradable
            ? <>Prices: NSE F&amp;O bhavcopy close, {fmtDay(chain.asOf)}
                {liveCount > 0 ? ` · • Kite quote${liveAt ? ` read at ${liveAt} IST` : ""} where the contract traded today (${liveCount} of ${req.legs.length})` : ""}
                {liveOn && live.data && !live.data.available && live.data.reason ? ` · live quotes off: ${live.data.reason}` : ""}
                {liveOn && (
                  <> · <button type="button" data-testid="ca-chain-live-refresh" disabled={live.isFetching} onClick={() => void live.refetch()}
                    style={{ padding: 0, border: 0, background: "none", font: "inherit", color: "var(--mint)", cursor: live.isFetching ? "wait" : "pointer" }}>
                    {live.isFetching ? "reading quotes…" : "refresh quotes"}</button></>
                )}</>
            : <>OI: {chain.source}. No prices or Greeks: the expiries differ.</>}
          {mode === "greeks" ? " · IV and Greeks: model estimates from the close, per unit." : ""}
        </span>
      </div>
    </section>
  );
}
