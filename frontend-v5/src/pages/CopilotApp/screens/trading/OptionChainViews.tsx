/**
 * Option chain views for the Options lab and the F&O analyser card.
 *
 * Every figure comes from GET /api/fno/{symbol}/chain (trading/fno.ts): the
 * NSE F&O bhavcopy's end-of-day closing prices, open interest and volume for
 * one expiry. Totals, the put-call ratio, max pain and the heaviest strikes
 * are the route's `summary`, worked out over every strike of the expiry; the
 * tables and bars show a window of strikes around the money.
 *
 * Implied volatility and the Greeks in the chain table are the route's model
 * estimates (Black-76 on end-of-day prices). They are labelled as such under
 * the table, and a contract the model gave none for reads "Not available".
 *
 * Calls are drawn in the danger colour and puts in mint, as in the design.
 */
import { useState, type ReactNode } from "react";
import { StockIcon } from "../../components/EntityIcon";
import { EmptyBlock, LoadingBlock, TONE_COLOR, fmtNum, signTone } from "../../components/ui";
import { fmtLevel } from "./PayoffResult";
import { NOT_AVAILABLE, forwardNote, modelLabel, noModelReason } from "./ModelViews";
import { Choices, QueryProblem, fmtDay, fmtQty, fmtSigned } from "./parts";
import { atmIndex, inTheMoney, isIndexUnderlying, strikesAround, type ChainState, type FnoChain, type FnoSide, type FnoStrike } from "./fno";

const CALL_COLOR = "var(--cp-danger)";
const PUT_COLOR = "var(--mint)";

// ── loading / error / no data ────────────────────────────────────────────

/**
 * Renders `children` once the chain has loaded; before that, the loading,
 * error (with retry) or no-data state, wrapped in `${testId}-loading`,
 * `${testId}-error` or `${testId}-empty`.
 */
export function ChainGate({ state, what, testId, children }: {
  state: ChainState;
  /** Sentence subject for the error line, e.g. "The option chain". */
  what: string;
  testId: string;
  children: (chain: FnoChain) => ReactNode;
}) {
  if (state.status === "loading") {
    return <div data-testid={`${testId}-loading`}><LoadingBlock label={`Loading ${what.toLowerCase()}`} rows={4} /></div>;
  }
  if (state.status === "error") {
    return <div data-testid={`${testId}-error`}><QueryProblem what={what} error={state.error} onRetry={state.retry} /></div>;
  }
  if (state.status === "none") {
    return (
      <div data-testid={`${testId}-empty`}>
        <EmptyBlock
          title={state.message}
          body="The end-of-day F&O file has no option contracts for it. Only indices and stocks in NSE’s F&O segment have a chain, so check the ticker."
        />
      </div>
    );
  }
  return <>{children(state.chain)}</>;
}

// ── chain table ──────────────────────────────────────────────────────────

type ChainWindow = "10" | "20" | "all";
/** Which figures the table shows for each contract. */
type ChainView = "prices" | "greeks" | "day";

/** A signed figure with the app's minus sign ("−0.40"), or "—". */
const signedNum = (n: number | null | undefined, digits: number) => (n == null ? "—" : n < 0 ? `−${fmtNum(-n, digits)}` : fmtNum(n, digits));

function Cell({ col, itm, right, color, children }: { col: string; itm: boolean; right?: boolean; color?: string; children: ReactNode }) {
  return (
    <span
      role="cell"
      data-col={col}
      data-itm={itm ? "true" : undefined}
      className="cp-num"
      style={{ minWidth: 0, padding: "2px 6px", borderRadius: 4, whiteSpace: "nowrap", textAlign: right ? "right" : "left", background: itm ? "var(--bg-3)" : undefined, color: color ?? "var(--cp-ink-2)" }}
    >
      {children}
    </span>
  );
}

interface ChainColumn {
  /** `data-col` is `call-${key}` or `put-${key}`. */
  key: string;
  head: string;
  /** The call side names its outermost column "Call OI"; the put side "Put OI". */
  headFor?: (prefix: "call" | "put") => string;
  cell: (side: FnoSide | null) => { text: ReactNode; color?: string };
}

/** Implied volatility for one contract: the figure, or "Not available" in words when the model gave none. */
function ivCell(side: FnoSide | null): { text: ReactNode; color?: string } {
  if (side == null) return { text: "—" };
  if (side.iv == null) return { text: <span data-testid="optlab-iv-missing" style={{ fontSize: 10, whiteSpace: "normal", lineHeight: 1.15, color: "var(--cp-ink-3)" }}>{NOT_AVAILABLE}</span> };
  return { text: fmtNum(side.iv, 2), color: "var(--cp-ink)" };
}

const tone = (n: number | null | undefined) => (n ? TONE_COLOR[signTone(n)] : undefined);
const IV_COL: ChainColumn = { key: "iv", head: "IV %", cell: ivCell };
const PRICE_COL: ChainColumn = { key: "price", head: "Close ₹", cell: (x) => ({ text: x?.close == null ? "—" : fmtNum(x.close, 2), color: "var(--cp-ink)" }) };

/** Each view's columns for one side, from the outside of the table in to the strike. */
const CHAIN_COLUMNS: Record<ChainView, ChainColumn[]> = {
  prices: [
    { key: "oi", head: "OI", headFor: (p) => (p === "call" ? "Call OI" : "Put OI"), cell: (x) => ({ text: fmtQty(x?.oi) }) },
    { key: "oi-change", head: "Chg in OI", cell: (x) => ({ text: fmtQty(x?.change_in_oi, { signed: true }), color: tone(x?.change_in_oi) }) },
    { key: "volume", head: "Volume", cell: (x) => ({ text: fmtQty(x?.volume) }) },
    IV_COL,
    PRICE_COL,
  ],
  greeks: [
    { key: "vega", head: "Vega", cell: (x) => ({ text: signedNum(x?.vega, 2) }) },
    { key: "theta", head: "Theta", cell: (x) => ({ text: signedNum(x?.theta, 2) }) },
    { key: "gamma", head: "Gamma", cell: (x) => ({ text: signedNum(x?.gamma, 5) }) },
    { key: "delta", head: "Delta", cell: (x) => ({ text: signedNum(x?.delta, 2), color: "var(--cp-ink)" }) },
    IV_COL,
  ],
  day: [
    { key: "buildup", head: "OI build-up", cell: (x) => ({ text: x?.oi_buildup ?? "—" }) },
    { key: "change-pct", head: "Chg %", cell: (x) => ({ text: x?.change_pct == null ? "—" : `${fmtSigned(x.change_pct)}%`, color: tone(x?.change_pct) }) },
    { key: "change", head: "Chg ₹", cell: (x) => ({ text: fmtSigned(x?.change), color: tone(x?.change) }) },
    PRICE_COL,
  ],
};

const CHAIN_MIN_WIDTH: Record<ChainView, number> = { prices: 880, greeks: 880, day: 900 };

/** The cells of one side: outside-in for calls, mirrored for puts. */
function sideCells(view: ChainView, prefix: "call" | "put", side: FnoSide | null, itm: boolean): ReactNode[] {
  const right = prefix === "put";
  const cells = CHAIN_COLUMNS[view].map((c) => {
    const { text, color } = c.cell(side);
    return <Cell key={c.key} col={`${prefix}-${c.key}`} itm={itm} right={right} color={color}>{text}</Cell>;
  });
  return right ? cells.reverse() : cells;
}

const hasDayChange = (chain: FnoChain) => chain.strikes.some((r) => r.call?.change != null || r.put?.change != null);

export function ChainTable({ chain }: { chain: FnoChain }) {
  const [win, setWin] = useState<ChainWindow>("10");
  const [view, setView] = useState<ChainView>("prices");
  const s = chain.summary;
  const rows = win === "all" ? chain.strikes : strikesAround(chain, Number(win));
  const cols = CHAIN_COLUMNS[view];
  const template = `repeat(${cols.length},minmax(0,1fr)) 96px repeat(${cols.length},minmax(0,1fr))`;
  const head = (key: string, label: string, right = false, center = false) => (
    <span key={key} role="columnheader" className="cp-mono-note" style={{ padding: "0 6px", textAlign: center ? "center" : right ? "right" : "left" }}>{label}</span>
  );
  const noModel = noModelReason(s);
  const dayMissing = view === "day" && !hasDayChange(chain);
  return (
    <div data-testid="optlab-chain" className="cp-card flex flex-col min-w-0" style={{ overflow: "hidden" }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px", padding: "12px 16px", borderBottom: "1px solid var(--cp-line)" }}>
        <span className="cp-eyebrow flex items-center" style={{ gap: 8 }}>
          {!isIndexUnderlying(chain.symbol) && <StockIcon symbol={chain.symbol} size={18} />}
          <span>{chain.symbol} · {fmtDay(s.expiry)} expiry · calls and puts by strike</span>
        </span>
        <div className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
          <Choices<ChainView>
            label="Figures shown"
            testId="optlab-chain-view"
            value={view}
            onChange={setView}
            options={[{ value: "prices", label: "Prices, OI and IV" }, { value: "greeks", label: "Greeks" }, { value: "day", label: "Day change" }]}
          />
          <Choices<ChainWindow>
            label="Strikes shown"
            testId="optlab-chain-window"
            value={win}
            onChange={setWin}
            options={[{ value: "10", label: "±10 strikes" }, { value: "20", label: "±20" }, { value: "all", label: `All ${fmtNum(chain.strikes.length)}` }]}
          />
        </div>
      </div>
      {dayMissing ? (
        <div data-testid="optlab-chain-day-missing" style={{ padding: "14px 16px", fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          {NOT_AVAILABLE}. The day’s price change and the open-interest build-up need each contract’s previous close. The exchange file has it, but the data platform does not send it to the app yet.
        </div>
      ) : (
        <div className="cp-scroll overflow-x-auto" role="table" aria-label={`${chain.symbol} option chain, ${fmtDay(s.expiry)} expiry`}>
          <div style={{ minWidth: CHAIN_MIN_WIDTH[view] }}>
            <div role="row" className="grid" style={{ gridTemplateColumns: template, gap: 8, padding: "10px 16px" }}>
              {cols.map((c) => head(`call-${c.key}`, c.headFor?.("call") ?? c.head))}
              {head("strike", "Strike", false, true)}
              {[...cols].reverse().map((c) => head(`put-${c.key}`, c.headFor?.("put") ?? c.head, true))}
            </div>
            {rows.map((r) => {
              const atm = r.strike === s.atm_strike;
              return (
                <div
                  key={r.strike}
                  role="row"
                  data-testid="optlab-chain-row"
                  data-strike={r.strike}
                  data-atm={atm ? "true" : undefined}
                  className="grid items-center"
                  style={{ gridTemplateColumns: template, gap: 8, padding: "7px 16px", borderTop: "1px solid var(--cp-line)", fontSize: 13, background: atm ? "var(--mint-soft)" : undefined }}
                >
                  {sideCells(view, "call", r.call, inTheMoney("CE", r.strike, s.spot))}
                  <span role="cell" data-col="strike" className="cp-num flex items-center justify-center" style={{ gap: 6, fontSize: 12, fontWeight: 500, color: "var(--cp-ink)" }}>
                    {fmtLevel(r.strike)}
                    {atm && <span data-testid="optlab-chain-atm" className="cp-pill" data-tone="mint" style={{ padding: "1px 5px", fontSize: 9 }}>ATM</span>}
                  </span>
                  {sideCells(view, "put", r.put, inTheMoney("PE", r.strike, s.spot))}
                </div>
              );
            })}
          </div>
        </div>
      )}
      <div data-testid="optlab-chain-note" style={{ padding: "10px 16px", borderTop: "1px solid var(--cp-line)", fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        End-of-day closing prices, open interest and volume from the NSE F&O bhavcopy, as of {fmtDay(s.as_of)}; nothing here moves during the session.
        {s.spot != null && s.atm_strike != null
          ? ` Tinted cells are in the money against the end-of-day spot of ${fmtNum(s.spot, 2)}; the marked row is the strike nearest it.`
          : " The file carries no spot for this day, so no row is marked and no cell is tinted."}
        {` Showing ${fmtNum(rows.length)} of this expiry’s ${fmtNum(chain.strike_count)} strikes.`}
      </div>
      <div data-testid="optlab-chain-model-label" style={{ padding: "0 16px 12px", fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        IV and the Greeks: {modelLabel(s)}. The exchange file carries neither; each is worked out from the contract’s settle price (its close when it has none).{" "}
        {noModel ?? `${forwardNote(s)} “${NOT_AVAILABLE}” marks a contract that did not trade and has no open interest, or whose price is at or below its intrinsic value: no volatility prices it.`}
        {view === "greeks" && " Delta and gamma are per one-point move in the forward, theta per calendar day and vega per one point of IV, all per unit."}
        {view === "day" && !dayMissing && " OI build-up reads the day’s price change and change in open interest together (price up and OI up: long build-up; price down and OI up: short build-up; price up and OI down: short covering; price down and OI down: long unwinding). It describes two figures, not who traded."}
      </div>
    </div>
  );
}

// ── open interest ────────────────────────────────────────────────────────

type OiWindow = "5" | "10" | "15" | "20";
type OiMode = "oi" | "change";
const SLOT = 40; // viewBox units per strike
const BAR = 10;

function OiChart({ rows, mode, atm }: { rows: FnoStrike[]; mode: OiMode; atm: number | null }) {
  const value = (side: FnoSide | null) => (mode === "oi" ? side?.oi : side?.change_in_oi) ?? 0;
  const vals = rows.flatMap((r) => [value(r.call), value(r.put)]);
  const lo = Math.min(0, ...vals);
  const hi = Math.max(0, ...vals);
  const Y = (v: number) => 190 - ((v - lo) / (hi - lo || 1)) * 180;
  const what = mode === "oi" ? "open interest" : "change in open interest";
  const bar = (r: FnoStrike, i: number, side: "put" | "call") => {
    const v = value(side === "put" ? r.put : r.call);
    return (
      <rect
        data-testid="optlab-oi-bar"
        data-strike={r.strike}
        data-side={side}
        data-value={v}
        x={i * SLOT + SLOT / 2 + (side === "put" ? -BAR - 1 : 1)}
        y={Math.min(Y(v), Y(0))}
        width={BAR}
        height={Math.abs(Y(v) - Y(0))}
        fill={side === "put" ? PUT_COLOR : CALL_COLOR}
      >
        <title>{`${fmtLevel(r.strike)} ${side} ${what}: ${fmtQty(v, { signed: mode === "change" })}`}</title>
      </rect>
    );
  };
  return (
    <div className="cp-scroll overflow-x-auto">
      <div style={{ minWidth: rows.length * 34 }}>
        <svg
          data-testid="optlab-oi-chart"
          data-mode={mode}
          role="img"
          aria-label={`Call and put ${what} for ${rows.length} strikes${atm != null ? ` around ${fmtLevel(atm)}` : ""}`}
          viewBox={`0 0 ${rows.length * SLOT} 200`}
          preserveAspectRatio="none"
          style={{ width: "100%", height: 200, display: "block" }}
        >
          {rows.map((r, i) => (r.strike === atm ? <rect key={r.strike} x={i * SLOT} y="0" width={SLOT} height="200" fill="var(--bg-2)" /> : null))}
          <line x1="0" y1={Y(0)} x2={rows.length * SLOT} y2={Y(0)} stroke="var(--line-3)" vectorEffect="non-scaling-stroke" />
          {rows.map((r, i) => <g key={r.strike}>{bar(r, i, "put")}{bar(r, i, "call")}</g>)}
        </svg>
        <div className="cp-num flex" style={{ paddingTop: 6, fontSize: 9 }}>
          {rows.map((r) => (
            <span key={r.strike} style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden", textAlign: "center", whiteSpace: "nowrap", color: r.strike === atm ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>{fmtLevel(r.strike)}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({ k, testId, children }: { k: string; testId: string; children: ReactNode }) {
  return (
    <div className="flex justify-between" style={{ gap: 10 }}>
      <span style={{ color: "var(--cp-ink-3)" }}>{k}</span>
      <span data-testid={testId} className="cp-num" style={{ textAlign: "right", color: "var(--cp-ink)" }}>{children}</span>
    </div>
  );
}

/** "25,500 · 1.23 Cr", or "—" when no strike on that side has open interest. */
const topOi = (t: FnoChain["summary"]["max_call_oi"]) => (t ? `${fmtLevel(t.strike)} · ${fmtQty(t.oi)}` : "—");

export function OpenInterestPanel({ chain }: { chain: FnoChain }) {
  const [win, setWin] = useState<OiWindow>("5");
  const [mode, setMode] = useState<OiMode>("oi");
  const s = chain.summary;
  const rows = strikesAround(chain, Number(win));
  const changeOn = mode === "change";
  return (
    <div data-testid="optlab-oi" className="flex flex-wrap items-start" style={{ gap: 12 }}>
      <div className="cp-card flex flex-col" style={{ flex: "1 1 240px", minWidth: 0, gap: 12, padding: 16 }}>
        <span className="cp-eyebrow">Strikes each side of the money</span>
        <Choices<OiWindow>
          label="Strikes each side of the money"
          testId="optlab-oi-window"
          value={win}
          onChange={setWin}
          options={[{ value: "5", label: "±5" }, { value: "10", label: "±10" }, { value: "15", label: "±15" }, { value: "20", label: "±20" }]}
        />
        <button
          type="button"
          role="switch"
          aria-checked={changeOn}
          data-testid="optlab-oi-change-toggle"
          onClick={() => setMode(changeOn ? "oi" : "change")}
          className="flex items-center justify-between"
          style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13, cursor: "pointer" }}
        >
          <span>Show change in OI</span>
          <span aria-hidden style={{ position: "relative", display: "block", flex: "none", width: 34, height: 20, borderRadius: 999, background: changeOn ? "var(--mint)" : "var(--bg-4)" }}>
            <span style={{ position: "absolute", top: 2, left: changeOn ? 16 : 2, width: 16, height: 16, borderRadius: "50%", background: "var(--cp-ink)" }} />
          </span>
        </button>
        <div className="flex flex-col" style={{ gap: 6, fontSize: 13 }}>
          <Stat k="Total call OI" testId="optlab-oi-total-call">{fmtQty(s.total_call_oi)}</Stat>
          <Stat k="Total put OI" testId="optlab-oi-total-put">{fmtQty(s.total_put_oi)}</Stat>
          <Stat k="Put-call ratio" testId="optlab-oi-pcr">{s.pcr == null ? "—" : fmtNum(s.pcr, 2)}</Stat>
          <Stat k="Max pain" testId="optlab-oi-max-pain">{s.max_pain == null ? "—" : fmtLevel(s.max_pain)}</Stat>
          <Stat k="Highest call OI" testId="optlab-oi-top-call">{topOi(s.max_call_oi)}</Stat>
          <Stat k="Highest put OI" testId="optlab-oi-top-put">{topOi(s.max_put_oi)}</Stat>
          <Stat k="Change in call OI" testId="optlab-oi-change-call">{fmtQty(s.total_call_oi_change, { signed: true })}</Stat>
          <Stat k="Change in put OI" testId="optlab-oi-change-put">{fmtQty(s.total_put_oi_change, { signed: true })}</Stat>
        </div>
        <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          These figures cover all {fmtNum(chain.strike_count)} strikes of the expiry, not only the bars shown. Put-call ratio is total put open interest ÷ total call open interest. Max pain is the strike at which the combined intrinsic value of every open call and put would be smallest at expiry.
        </span>
      </div>

      <div className="cp-card flex flex-col" style={{ flex: "2 1 420px", minWidth: 0, gap: 10, padding: 16 }}>
        <div className="flex flex-wrap justify-between" style={{ gap: 10 }}>
          <span className="cp-eyebrow flex items-center" style={{ gap: 8 }}>
            {!isIndexUnderlying(chain.symbol) && <StockIcon symbol={chain.symbol} size={18} />}
            <span data-testid="optlab-oi-title">{chain.symbol} · {changeOn ? "Change in open interest" : "Open interest"} by strike · {fmtDay(s.expiry)} expiry</span>
          </span>
          <span className="cp-num flex" style={{ gap: 12, fontSize: 10 }}>
            <span style={{ color: PUT_COLOR }}>● PUTS</span>
            <span style={{ color: CALL_COLOR }}>● CALLS</span>
          </span>
        </div>
        <OiChart rows={rows} mode={mode} atm={atmIndex(chain) >= 0 ? s.atm_strike : null} />
        <span data-testid="optlab-oi-read" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {s.max_call_oi && s.max_put_oi
            ? `The most call open interest sits at ${fmtLevel(s.max_call_oi.strike)} and the most put open interest at ${fmtLevel(s.max_put_oi.strike)}. These are open-interest levels at the close, not price targets.`
            : "This expiry has no open interest on one side, so there is no heaviest strike to name."}
        </span>
        <span data-testid="optlab-oi-note" className="cp-mono-note" style={{ lineHeight: 1.6 }}>
          End-of-day data · as of {fmtDay(s.as_of)} · NSE F&O bhavcopy · does not move during the session
        </span>
      </div>
    </div>
  );
}

// ── compact open interest rows (F&O analyser) ────────────────────────────

function HBar({ share, fill, fromRight }: { share: number; fill: string; fromRight?: boolean }) {
  const w = Math.max(0, Math.min(1, share)) * 100;
  return (
    <svg aria-hidden width="100%" height="8" style={{ flex: "1 1 0", minWidth: 0, display: "block" }}>
      <rect x={fromRight ? `${100 - w}%` : "0"} y="0" width={`${w}%`} height="8" rx="2" fill={fill} />
    </svg>
  );
}

/** Call and put open interest for `each` strikes either side of the money: calls to the left, puts to the right. */
export function OiRows({ chain, each, testId }: { chain: FnoChain; each: number; testId: string }) {
  const rows = strikesAround(chain, each);
  const max = Math.max(1, ...rows.flatMap((r) => [r.call?.oi ?? 0, r.put?.oi ?? 0]));
  const figure = { flex: "none", fontSize: 9, color: "var(--cp-ink-3)", whiteSpace: "nowrap" } as const;
  return (
    <div data-testid={testId} className="flex flex-col" style={{ gap: 2 }}>
      {rows.map((r) => {
        const atm = r.strike === chain.summary.atm_strike;
        return (
          <div
            key={r.strike}
            data-testid={`${testId}-row`}
            data-strike={r.strike}
            data-atm={atm ? "true" : undefined}
            className="grid items-center"
            style={{ gridTemplateColumns: "minmax(0,1fr) 64px minmax(0,1fr)", gap: 8, padding: "2px 4px", borderRadius: 4, background: atm ? "var(--bg-2)" : undefined }}
          >
            <div className="flex items-center" style={{ gap: 6, minWidth: 0 }}>
              <span data-col="call-oi" className="cp-num" style={figure}>{fmtQty(r.call?.oi)}</span>
              <HBar share={(r.call?.oi ?? 0) / max} fill={CALL_COLOR} fromRight />
            </div>
            <span className="cp-num" style={{ textAlign: "center", fontSize: 11, color: atm ? "var(--cp-ink)" : "var(--cp-ink-2)" }}>{fmtLevel(r.strike)}</span>
            <div className="flex items-center" style={{ gap: 6, minWidth: 0 }}>
              <HBar share={(r.put?.oi ?? 0) / max} fill={PUT_COLOR} />
              <span data-col="put-oi" className="cp-num" style={figure}>{fmtQty(r.put?.oi)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
