/**
 * Options lab. Design: NVOptionsLab.dc.html.
 *
 * Data (all end of day, from the NSE F&O bhavcopy; see trading/fno.ts):
 *   underlying, expiry   GET /api/fno/{symbol}/expiries
 *   chain, open interest GET /api/fno/{symbol}/chain?expiry=
 *   header spot          the chain's end-of-day underlying price. The index quote from
 *                        GET /api/markets/home (useMarketsHome) is shown only when no chain loaded.
 *   VIX                  GET /api/markets/home
 *   strategy builder     a calculator on the legs (trading/payoff.ts). With a chain loaded,
 *                        picking a structure fills strikes around the money and each
 *                        contract's end-of-day closing price; every value stays editable.
 *                        Without a chain the legs start empty, as before.
 *
 *   model estimates      implied volatility and the Greeks per strike, ATM IV, the forward
 *                        and the ATM straddle: worked out by the chain route with Black-76
 *                        from end-of-day prices (backend/services/option_pricing.py). The
 *                        builder adds the legs' net Greeks and a model chance of profit
 *                        (trading/odds.ts). Each is labelled a model estimate, and reads
 *                        "Not available" when the route sent none.
 *
 * Not connected: margin, prices that move during the session and today's
 * payoff curve. The lot size is filled from the chain when the route sends one
 * (the exchange file carries it); otherwise the user types it, and a typed
 * value is never replaced.
 */
import { useState, type FormEvent, type ReactNode } from "react";
import { useMarketsHome } from "@/hooks/use-markets";
import { StockIcon, StockName } from "../components/EntityIcon";
import { Btn, EmptyBlock, LoadingBlock, NotConnected, Pill, Screen, ScreenHeader, TONE_COLOR, fmtINR, fmtNum, fmtPct, signTone } from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { SymbolSearch } from "./tradingdesk/SymbolSearch";
import { LegModel, ModelStrip } from "./trading/ModelViews";
import { ChainGate, ChainTable, OpenInterestPanel } from "./trading/OptionChainViews";
import { FNO_INDICES, cleanSymbol, indexNameForSymbol, isIndexUnderlying, legFromChain, useOptionChain, type ChainState, type FnoChain } from "./trading/fno";
import { Choices, INPUT_STYLE, QueryProblem, SEBI_FNO_NOTE, fmtDay, fmtPrice } from "./trading/parts";
import {
  MARKET_VIEWS, STRUCTURES, analysePayoff, shapePoints, strikeHint,
  type Leg, type MarketView, type OptionType, type Side, type Structure,
} from "./trading/payoff";
import { PayoffResult, fmtLevel } from "./trading/PayoffResult";

type Tab = "chain" | "oi" | "builder";
const TABS: Array<{ id: Tab; label: string }> = [
  { id: "chain", label: "Option chain" },
  { id: "oi", label: "Open interest" },
  { id: "builder", label: "Strategy builder" },
];

const ANALYTICS_NEEDS = [
  "Margin (SPAN and exposure): a broker margin calculation for the legs, or the clearing corporation’s daily risk-parameter files ingested by the data platform. Neither is connected.",
  "Intraday option prices and open interest: a broker market-data session or a licensed feed. The F&O data is one exchange file a day, after the close.",
  "Today’s payoff curve: each leg re-priced across spot levels at the day’s implied volatility. The pricing model exists on the server; no route or screen draws the curve yet.",
];

type OptionChain = ReturnType<typeof useOptionChain>;

// ── underlying and expiry ────────────────────────────────────────────────

function UnderlyingPicker({ symbol, onPick }: { symbol: string; onPick: (s: string) => void }) {
  const [typed, setTyped] = useState("");
  const [bad, setBad] = useState(false);
  const options: Array<{ value: string; label: ReactNode }> = FNO_INDICES.map((i) => ({ value: i.symbol, label: i.symbol }));
  // An underlying the user loaded sits beside the two indices while it is the one shown; a company gets its icon.
  if (!options.some((o) => o.value === symbol)) {
    options.push({ value: symbol, label: isIndexUnderlying(symbol) ? symbol : <StockName symbol={symbol} size={18} testId="optlab-symbol-stock" /> });
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const s = cleanSymbol(typed);
    setBad(s == null);
    if (s == null) return;
    setTyped("");
    onPick(s);
  };

  return (
    <div className="flex flex-wrap items-center" style={{ gap: "8px 10px", flex: "1 1 520px", minWidth: 0 }}>
      <span className="cp-eyebrow">Underlying</span>
      <Choices label="Underlying" testId="optlab-symbol" value={symbol} onChange={onPick} options={options} />
      <form onSubmit={submit} className="flex items-center" style={{ gap: 6, flex: "0 1 300px", minWidth: 0 }}>
        <SymbolSearch
          value={typed}
          onChange={(v) => { setTyped(v); setBad(false); }}
          onSelect={(sym) => { setTyped(""); setBad(false); onPick(sym); }}
          persona="trader"
          fnoOnly
          testIdPrefix="optlab-symsearch"
          inputTestId="optlab-symbol-input"
          ariaLabel="Stock ticker"
          invalid={bad}
          placeholder="Stock ticker, e.g. RELIANCE"
          maxLength={40}
          inputStyle={INPUT_STYLE}
        />
        <Btn type="submit" data-testid="optlab-symbol-load" style={{ flex: "none" }}>Load</Btn>
      </form>
      {bad && (
        <span role="alert" data-testid="optlab-symbol-error" style={{ fontSize: 12, color: "var(--cp-danger)" }}>
          A ticker is letters, digits, &amp; or -, up to 20 characters.
        </span>
      )}
    </div>
  );
}

function ExpiryPicker({ oc, onPick }: { oc: OptionChain; onPick: (expiry: string) => void }) {
  const { expiries, list, expiry } = oc;
  if (expiries.isPending) return <span className="cp-mono-note">Loading expiries</span>;
  if (expiries.isError) {
    return (
      <span data-testid="optlab-expiry-error" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>
        The expiry list didn’t load, so only the nearest expiry can be shown.{" "}
        <button type="button" onClick={() => expiries.refetch()} style={{ padding: 0, border: 0, background: "none", fontSize: 12, color: "var(--cp-ink)", cursor: "pointer" }}>Retry ›</button>
      </span>
    );
  }
  if (!list.length || expiry == null) return null;
  return (
    <label className="flex items-center" style={{ gap: 8, minWidth: 0 }}>
      <span className="cp-eyebrow">Expiry</span>
      <select data-testid="optlab-expiry" value={expiry} onChange={(e) => onPick(e.target.value)} style={{ ...INPUT_STYLE, width: "auto" }}>
        {list.map((e) => (
          <option key={e.expiry} value={e.expiry}>{fmtDay(e.expiry)}{e.days_to_expiry === 0 ? " · expired at this close" : ""}</option>
        ))}
      </select>
    </label>
  );
}

// ── header spot ──────────────────────────────────────────────────────────

function useIndexQuote(indexName: string | null) {
  const home = useMarketsHome();
  const idx = indexName == null ? undefined : home.data?.indices.find((i) => i.name === indexName && !i.is_vix && i.value != null);
  const vix = home.data?.indices.find((i) => i.is_vix && i.value != null);
  return { home, idx, vix };
}

function SpotBadge({ symbol, state }: { symbol: string; state: ChainState }) {
  const { mobile } = useCopilotShell();
  const indexName = indexNameForSymbol(symbol);
  const { home, idx, vix } = useIndexQuote(indexName);
  const box = { flex: "0 1 280px", minWidth: 0 };
  const column = { alignItems: mobile ? "flex-start" : "flex-end", gap: 4 } as const;

  if (state.status === "loading") return <div style={box}><LoadingBlock label={`Loading the ${symbol} chain`} rows={1} /></div>;

  const summary = state.status === "ok" ? state.chain.summary : null;
  const asOf = summary && (
    <span data-testid="optlab-asof" className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>End-of-day data · as of {fmtDay(summary.as_of)}</span>
  );
  const vixLine = vix?.value != null && (
    <span data-testid="optlab-vix" className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>India VIX {fmtNum(vix.value, 2)}</span>
  );

  if (summary?.spot != null) {
    return (
      <div className="flex flex-col" style={column}>
        <span className="cp-num flex items-center" style={{ gap: 6, fontSize: 11, color: "var(--cp-ink-3)" }}>
          {!isIndexUnderlying(symbol) && <StockIcon symbol={symbol} size={18} />}
          {symbol} · SPOT
        </span>
        <span data-testid="optlab-spot" className="cp-metric">{fmtNum(summary.spot, 2)}</span>
        {asOf}
        {vixLine}
      </div>
    );
  }

  // No chain (it failed, or the underlying has none): the index quote from the markets feed, as before.
  if (indexName == null) return null;
  if (home.isPending) return <div style={box}><LoadingBlock label={`Loading the ${indexName} spot`} rows={1} /></div>;
  if (home.isError) return <div style={box}><QueryProblem what="The spot price" error={home.error} onRetry={() => home.refetch()} /></div>;
  if (!idx) return <div style={box}><EmptyBlock title={`No ${indexName} quote right now`} body="The markets feed returned no value for it." /></div>;

  return (
    <div className="flex flex-col" style={column}>
      <span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{indexName.toUpperCase()} · SPOT</span>
      <span className="flex items-baseline" style={{ gap: 8 }}>
        <span data-testid="optlab-spot" className="cp-metric">{fmtNum(idx.value, 2)}</span>
        <span className="cp-num" style={{ fontSize: 12, color: TONE_COLOR[signTone(idx.change_pct)] }}>{fmtPct(idx.change_pct, { signed: true, digits: 2 })}</span>
      </span>
      {asOf}
      {vixLine}
    </div>
  );
}

// ── strategy builder ─────────────────────────────────────────────────────

interface LegDraft {
  id: number;
  side: Side;
  type: OptionType;
  lots: string;
  strike: string;
  premium: string;
  /** Where this strike sits in the chosen structure; shown as the input's placeholder. */
  hint: string;
}

/** The chain a set of legs was filled from. */
interface FillSource {
  symbol: string;
  expiry: string;
  asOf: string;
}

let nextLegId = 1;

const sourceOf = (c: FnoChain): FillSource => ({ symbol: c.symbol, expiry: c.summary.expiry, asOf: c.summary.as_of });
const sourceKey = (s: FillSource | null) => (s ? `${s.symbol}|${s.expiry}|${s.asOf}` : null);

/**
 * A structure's legs. With a chain, each leg gets the strike that many steps
 * from the money and that contract's end-of-day closing price; a leg the chain
 * cannot price is left blank. Without a chain every strike and premium is blank.
 */
function draftsFor(structure: Structure, chain: FnoChain | null): LegDraft[] {
  return structure.legs.map((t) => {
    const fill = chain ? legFromChain(chain, t.type, t.offset) : null;
    return {
      id: nextLegId++,
      side: t.side,
      type: t.type,
      lots: String(t.lots),
      strike: fill ? String(fill.strike) : "",
      premium: fill?.premium != null ? String(fill.premium) : "",
      hint: strikeHint(structure, t),
    };
  });
}

function toNumber(s: string): number | null {
  const n = Number(s);
  return s.trim() !== "" && Number.isFinite(n) ? n : null;
}
const positive = (s: string) => {
  const n = toNumber(s);
  return n != null && n > 0 ? n : null;
};
const wholePositive = (s: string) => {
  const n = positive(s);
  return n != null && Number.isInteger(n) ? n : null;
};
const notNegative = (s: string) => {
  const n = toNumber(s);
  return n != null && n >= 0 ? n : null;
};

function parseLeg(l: LegDraft): Leg | null {
  const strike = positive(l.strike);
  const premium = notNegative(l.premium);
  const lots = wholePositive(l.lots);
  return strike != null && premium != null && lots != null ? { side: l.side, type: l.type, strike, premium, lots } : null;
}

function Builder({ symbol, chain }: { symbol: string; chain: FnoChain | null }) {
  const { ask } = useCopilotShell();
  const { idx } = useIndexQuote(indexNameForSymbol(symbol));
  const [view, setView] = useState<MarketView>("Bullish");
  const [structure, setStructure] = useState<Structure>(STRUCTURES.Bullish[0]);
  const [legs, setLegs] = useState<LegDraft[]>(() => draftsFor(STRUCTURES.Bullish[0], null));
  const [lotSize, setLotSize] = useState("");
  /** True once the user typed a lot size; a typed value is never replaced by the chain's. */
  const [lotTyped, setLotTyped] = useState(false);
  /** True once legs were added, removed or flipped, so the picked name no longer describes them. */
  const [edited, setEdited] = useState(false);
  /** True once the user changed any leg value; such legs are never overwritten by a newly loaded chain. */
  const [touched, setTouched] = useState(false);
  /** The chain the current legs were filled from; null when they were not filled. */
  const [filled, setFilled] = useState<FillSource | null>(null);
  const [seenChain, setSeenChain] = useState<string | null>(null);

  const chainKey = sourceKey(chain ? sourceOf(chain) : null);
  if (chainKey !== seenChain) {
    // A different chain arrived (or the chain went away). Legs the user has not
    // typed in follow it; legs the user changed are left exactly as they are.
    setSeenChain(chainKey);
    if (!lotTyped) setLotSize(chain?.lot_size ? String(chain.lot_size) : "");
    if (!touched) {
      setLegs(draftsFor(structure, chain));
      setFilled(chain ? sourceOf(chain) : null);
    }
  }

  const pick = (s: Structure) => {
    setStructure(s);
    setLegs(draftsFor(s, chain));
    setFilled(chain ? sourceOf(chain) : null);
    setEdited(false);
    setTouched(false);
  };
  const pickView = (v: MarketView) => {
    setView(v);
    pick(STRUCTURES[v][0]);
  };
  const patch = (id: number, change: Partial<LegDraft>, reshapes = false) => {
    setLegs((ls) => ls.map((l) => (l.id === id ? { ...l, ...change } : l)));
    setTouched(true);
    if (reshapes) setEdited(true);
  };
  const addLeg = () => {
    setLegs((ls) => [...ls, { id: nextLegId++, side: "buy", type: "CE", lots: "1", strike: "", premium: "", hint: "Strike" }]);
    setTouched(true);
    setEdited(true);
  };
  const removeLeg = (id: number) => {
    setLegs((ls) => ls.filter((l) => l.id !== id));
    setTouched(true);
    setEdited(true);
  };

  const name = edited ? "Custom structure" : structure.name;
  const size = wholePositive(lotSize);
  const parsed = legs.map(parseLeg);
  const complete = parsed.filter((l): l is Leg => l != null);
  const payoff = size != null && complete.length > 0 && complete.length === legs.length ? analysePayoff(complete, size) : null;
  const chainSpot = chain?.summary.spot ?? null;
  const hasBlank = legs.some((l) => l.strike === "" || l.premium === "");

  const explain = () => {
    if (!payoff || size == null) {
      ask(`Explain the risk of a ${symbol} ${name.toLowerCase()}`);
      return;
    }
    const legText = complete.map((l) => `${l.side} ${l.lots} lot${l.lots > 1 ? "s" : ""} of the ${fmtLevel(l.strike)} ${l.type} at ${fmtPrice(l.premium)}`).join(", ");
    ask(
      `Explain the risk of this ${symbol} ${name.toLowerCase()}: ${legText}; lot size ${fmtNum(size)}. At expiry the max profit is ${payoff.maxProfit == null ? "unlimited" : fmtINR(payoff.maxProfit)}, the max loss is ${payoff.maxLoss == null ? "unlimited" : fmtINR(payoff.maxLoss)} and the breakeven is ${payoff.breakevens.length ? payoff.breakevens.map(fmtLevel).join(" and ") : "none"}.`,
    );
  };

  return (
    <div className="grid items-start" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: 14 }}>
      <div className="cp-card flex flex-col min-w-0" style={{ gap: 12, padding: 16 }}>
        <Choices label="Market view" testId="optlab-view" value={view} onChange={pickView} options={MARKET_VIEWS.map((v) => ({ value: v, label: v }))} />
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(104px,1fr))", gap: 8 }}>
          {STRUCTURES[view].map((s) => {
            const active = !edited && s.name === structure.name;
            return (
              <button
                key={s.name}
                type="button"
                aria-pressed={active}
                data-testid="optlab-structure"
                onClick={() => pick(s)}
                className="flex flex-col items-center"
                style={{ gap: 6, padding: "10px 8px", borderRadius: 12, cursor: "pointer", color: "var(--cp-ink)", border: `1px solid ${active ? "var(--mint-line)" : "var(--cp-line)"}`, background: active ? "var(--mint-soft)" : "var(--bg-2)" }}
              >
                <svg aria-hidden viewBox="0 0 64 32" style={{ width: 64, height: 32, overflow: "visible" }}>
                  <polyline points={shapePoints(s)} fill="none" stroke="var(--mint)" strokeWidth="1.8" strokeLinejoin="round" />
                </svg>
                <span style={{ fontSize: 12, textAlign: "center", lineHeight: 1.3 }}>{s.name}</span>
              </button>
            );
          })}
        </div>
        <span data-testid="optlab-builder-help" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          {chain
            ? `Pick a ready-made structure. Its legs are filled with strikes around the money and each contract’s end-of-day closing price from the ${chain.symbol} ${fmtDay(chain.summary.expiry)} chain, as of ${fmtDay(chain.summary.as_of)}. Every value can be edited. The small curves show each structure’s shape only.`
            : `Pick a ready-made structure, then enter each leg’s strike and premium from your broker’s option chain. No end-of-day chain is loaded for ${symbol}, so no price is filled in for you. The small curves show each structure’s shape only.`}
        </span>
      </div>

      <div className="flex flex-col min-w-0" style={{ gap: 12 }}>
        <div className="cp-card flex flex-col" style={{ gap: 10, padding: 16 }}>
          <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
            <span data-testid="optlab-structure-name" className="cp-eyebrow">{name} · legs</span>
            <button type="button" data-testid="optlab-add-leg" onClick={addLeg} style={{ padding: 0, border: 0, background: "none", fontSize: 12, color: "var(--mint)", cursor: "pointer" }}>＋ Add leg</button>
          </div>
          {filled && (
            <span data-testid="optlab-prefill-note" style={{ padding: "8px 10px", borderRadius: 8, background: "var(--bg-2)", fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
              Strikes and premiums were filled from the {filled.symbol} {fmtDay(filled.expiry)} chain: end-of-day closing prices as of {fmtDay(filled.asOf)}. They do not update during the session, so edit any value to match your broker.
              {!touched && hasBlank && " A leg left blank has no strike that far from the money, or no closing price, in that chain."}
              {sourceKey(filled) !== chainKey && " The lab now shows a different chain; pick the structure again to refill from it."}
            </span>
          )}
          <label className="flex flex-col" style={{ gap: 4, minWidth: 0, maxWidth: 260 }}>
            <span className="cp-mono-note">Lot size · units per lot</span>
            <input data-testid="optlab-lot-size" type="number" inputMode="numeric" min="1" step="1" placeholder="From the contract" value={lotSize} onChange={(e) => { setLotSize(e.target.value); setLotTyped(true); }} style={INPUT_STYLE} />
            {!lotTyped && chain?.lot_size != null && lotSize !== "" && (
              <span data-testid="optlab-lot-source" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>From the exchange’s contract file for {symbol}. Edit it if your broker shows a different lot.</span>
            )}
          </label>
          {legs.map((l, i) => (
            <div key={l.id} role="group" aria-label={`Leg ${i + 1}`} data-testid="optlab-leg" className="grid items-end" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(84px,1fr))", gap: 8, paddingTop: 10, borderTop: "1px solid var(--cp-line)" }}>
              <div className="flex flex-col" style={{ gap: 4, minWidth: 0 }}>
                <span className="cp-mono-note">Leg {i + 1}</span>
                <button
                  type="button"
                  className="cp-pill"
                  data-tone={l.side === "buy" ? "mint" : "danger"}
                  data-testid={`optlab-leg-${i}-side`}
                  aria-label={`Leg ${i + 1} is a ${l.side}. Switch to ${l.side === "buy" ? "sell" : "buy"}`}
                  onClick={() => patch(l.id, { side: l.side === "buy" ? "sell" : "buy" }, true)}
                  style={{ justifyContent: "center", padding: "9px 9px", background: "transparent", cursor: "pointer" }}
                >
                  {l.side}
                </button>
              </div>
              <label className="flex flex-col" style={{ gap: 4, minWidth: 0 }}>
                <span className="cp-mono-note">Type</span>
                <select data-testid={`optlab-leg-${i}-type`} aria-label={`Leg ${i + 1} option type`} value={l.type} onChange={(e) => patch(l.id, { type: e.target.value === "PE" ? "PE" : "CE" }, true)} style={INPUT_STYLE}>
                  <option value="CE">CE · call</option>
                  <option value="PE">PE · put</option>
                </select>
              </label>
              <label className="flex flex-col" style={{ gap: 4, minWidth: 0 }}>
                <span className="cp-mono-note">Lots</span>
                <input data-testid={`optlab-leg-${i}-lots`} aria-label={`Leg ${i + 1} lots`} type="number" inputMode="numeric" min="1" step="1" value={l.lots} onChange={(e) => patch(l.id, { lots: e.target.value })} style={INPUT_STYLE} />
              </label>
              <label className="flex flex-col" style={{ gap: 4, minWidth: 0 }}>
                <span className="cp-mono-note">Strike</span>
                <input data-testid={`optlab-leg-${i}-strike`} aria-label={`Leg ${i + 1} strike`} type="number" inputMode="decimal" min="0" step="any" placeholder={l.hint} value={l.strike} onChange={(e) => patch(l.id, { strike: e.target.value })} style={INPUT_STYLE} />
              </label>
              <label className="flex flex-col" style={{ gap: 4, minWidth: 0 }}>
                <span className="cp-mono-note">Premium ₹</span>
                <input data-testid={`optlab-leg-${i}-premium`} aria-label={`Leg ${i + 1} premium in rupees`} type="number" inputMode="decimal" min="0" step="any" placeholder="Per unit" value={l.premium} onChange={(e) => patch(l.id, { premium: e.target.value })} style={INPUT_STYLE} />
              </label>
              <Btn variant="ghost" aria-label={`Remove leg ${i + 1}`} disabled={legs.length === 1} title={legs.length === 1 ? "A structure needs at least one leg" : undefined} onClick={() => removeLeg(l.id)}>Remove</Btn>
            </div>
          ))}
        </div>

        {payoff && size != null ? (
          <PayoffResult
            payoff={payoff}
            lotSize={size}
            spot={chainSpot ?? idx?.value ?? null}
            spotLabel={chainSpot != null ? "END-OF-DAY SPOT" : "SPOT"}
            underlying={symbol}
          />
        ) : (
          <div data-testid="optlab-payoff-empty">
            <EmptyBlock
              title="Enter the legs to see the payoff"
              body="Fill in the lot size and a strike and premium for every leg. Max profit, max loss, breakevens and the payoff at expiry are then worked out from exactly those numbers."
            />
          </div>
        )}

        {payoff && size != null && <LegModel chain={chain} legs={complete} lotSize={size} />}

        <NotConnected
          testId="optlab-analytics-not-connected"
          title="Margin, intraday prices and today’s payoff curve"
          body="The design also shows a margin estimate, prices that move during the session and the payoff curve for today. Margin needs a broker or exchange source, the data here is end of day only, and today’s curve is not built. None of them is estimated from a guess."
          needs={ANALYTICS_NEEDS}
        />

        <div className="flex flex-wrap" style={{ gap: 8 }}>
          <Btn variant="primary" disabled title="Options paper trading is not available. The paper engine records only its own frozen equity selections.">Paper trade this</Btn>
          <Btn data-testid="optlab-explain" onClick={explain}>Ask Copilot to explain the risk</Btn>
        </div>
      </div>
    </div>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

export default function OptionsLabScreen() {
  const [tab, setTab] = useState<Tab>("builder");
  const [symbol, setSymbol] = useState<string>(FNO_INDICES[0].symbol);
  /** The expiry the user chose for `symbol`; null = the default (nearest still to come). */
  const [picked, setPicked] = useState<string | null>(null);
  const oc = useOptionChain(symbol, picked);

  const pickSymbol = (s: string) => {
    setSymbol(s);
    setPicked(null);
  };

  return (
    <Screen testId="screen-tool-optlab">
      <div className="flex flex-wrap items-end justify-between" style={{ gap: 14 }}>
        <div style={{ flex: "1 1 320px", minWidth: 0 }}>
          <ScreenHeader
            eyebrow="Options lab · NSE F&O"
            pills={<><Pill tone="mint">Trader mode</Pill><Pill tone="indigo">Analysis only</Pill><Pill>End-of-day data</Pill></>}
            title={<>Build, test and understand <em>option trades</em>.</>}
          />
        </div>
        <SpotBadge symbol={symbol} state={oc.state} />
      </div>

      <div className="flex flex-wrap items-center" style={{ gap: "10px 20px" }}>
        <UnderlyingPicker symbol={symbol} onPick={pickSymbol} />
        <ExpiryPicker oc={oc} onPick={setPicked} />
      </div>

      {oc.state.status === "ok" && <ModelStrip chain={oc.state.chain} />}

      <div role="tablist" aria-label="Options lab" className="cp-scroll flex overflow-x-auto" style={{ gap: 24, borderBottom: "1px solid var(--cp-line)" }}>
        {TABS.map((t) => {
          const on = t.id === tab;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`optlab-tab-${t.id}`}
              data-testid={`optlab-tab-${t.id}`}
              aria-selected={on}
              aria-controls="optlab-panel"
              onClick={() => setTab(t.id)}
              style={{ padding: "10px 0 12px", border: 0, borderBottom: `2px solid ${on ? "var(--cp-ink)" : "transparent"}`, background: "none", fontFamily: "var(--sans)", fontSize: 14, whiteSpace: "nowrap", cursor: "pointer", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)" }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      <div role="tabpanel" id="optlab-panel" aria-labelledby={`optlab-tab-${tab}`} className="flex flex-col min-w-0" style={{ gap: 12 }}>
        {tab === "chain" && (
          <ChainGate state={oc.state} what="The option chain" testId="optlab-chain">
            {(chain) => <ChainTable chain={chain} />}
          </ChainGate>
        )}
        {tab === "oi" && (
          <ChainGate state={oc.state} what="Open interest" testId="optlab-oi">
            {(chain) => <OpenInterestPanel chain={chain} />}
          </ChainGate>
        )}
        {/* Kept mounted so the legs survive a look at the other tabs. */}
        <div hidden={tab !== "builder"}>
          <Builder symbol={symbol} chain={oc.state.status === "ok" ? oc.state.chain : null} />
        </div>
      </div>

      <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-danger)" }}>
        {SEBI_FNO_NOTE} Nivesh cannot place orders; everything here is analysis.
      </span>
    </Screen>
  );
}
