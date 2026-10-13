/**
 * Options lab. Design: NVOptionsLab.dc.html.
 *
 * Data:
 *   header spot, VIX   GET /api/markets/home (useMarketsHome)
 *   strategy builder   a calculator on what the user types (trading/payoff.ts)
 *
 * Not connected: the option chain and open interest tabs, and in the builder
 * the Greeks, chance of profit, margin and today's curve. All of them need an
 * option-chain feed the app does not have, so legs start with empty strike and
 * premium inputs and nothing is pre-filled.
 */
import { useState } from "react";
import { useMarketsHome } from "@/hooks/use-markets";
import { Btn, EmptyBlock, Footnote, LoadingBlock, NotConnected, Pill, Screen, ScreenHeader, TONE_COLOR, fmtINR, fmtNum, fmtPct, signTone } from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { FNO_INDEX_NAMES } from "./trading/FnoAnalyser";
import { Choices, INPUT_STYLE, QueryProblem, SEBI_FNO_NOTE, fmtPrice } from "./trading/parts";
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

/** Picked when the legs are for something the markets feed has no quote for. */
const OTHER = "Other";
const UNDERLYINGS = [...FNO_INDEX_NAMES, OTHER];

const CHAIN_NEEDS = [
  "An /api route over the F&O chain. The data platform keeps an end-of-day chain (DaaS /v1/fno/{symbol}/chain), which the backend reads only to price a hedge in POST /api/positional/basket.",
  "Per strike: call and put last price, IV, open interest and change in open interest.",
  "The list of expiries and the lot size for each underlying.",
  "The snapshot time, and an intraday refresh if the chain is to be more than end of day.",
];
const OI_NEEDS = [
  "Open interest and change in open interest per strike, for calls and puts.",
  "Totals per expiry, to derive the put-call ratio and max pain.",
  "The time of the exchange snapshot the figures were taken from.",
];
const ANALYTICS_NEEDS = [
  "Implied volatility for each strike and the underlying’s spot from an option-chain endpoint, for the Greeks, the chance of profit and today’s curve.",
  "Days to expiry, from an expiry calendar.",
  "A margin calculation (SPAN and exposure) from a broker or exchange source.",
];

// ── header spot ──────────────────────────────────────────────────────────

function useSpot(underlying: string) {
  const home = useMarketsHome();
  const idx = underlying === OTHER ? undefined : home.data?.indices.find((i) => i.name === underlying && !i.is_vix && i.value != null);
  const vix = home.data?.indices.find((i) => i.is_vix && i.value != null);
  return { home, idx, vix };
}

function SpotBadge({ underlying }: { underlying: string }) {
  const { mobile } = useCopilotShell();
  const { home, idx, vix } = useSpot(underlying);
  if (underlying === OTHER) return null;

  const box = { flex: "0 1 280px", minWidth: 0 };
  if (home.isPending) return <div style={box}><LoadingBlock label={`Loading the ${underlying} spot`} rows={1} /></div>;
  if (home.isError) return <div style={box}><QueryProblem what="The spot price" error={home.error} onRetry={() => home.refetch()} /></div>;
  if (!idx) return <div style={box}><EmptyBlock title={`No ${underlying} quote right now`} body="The markets feed returned no value for it." /></div>;

  return (
    <div className="flex flex-col" style={{ alignItems: mobile ? "flex-start" : "flex-end", gap: 4 }}>
      <span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{underlying.toUpperCase()} · SPOT</span>
      <span className="flex items-baseline" style={{ gap: 8 }}>
        <span data-testid="optlab-spot" className="cp-metric">{fmtNum(idx.value, 2)}</span>
        <span className="cp-num" style={{ fontSize: 12, color: TONE_COLOR[signTone(idx.change_pct)] }}>{fmtPct(idx.change_pct, { signed: true, digits: 2 })}</span>
      </span>
      {vix?.value != null && <span data-testid="optlab-vix" className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>India VIX {fmtNum(vix.value, 2)}</span>}
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

let nextLegId = 1;

function draftsFor(structure: Structure): LegDraft[] {
  return structure.legs.map((t) => ({ id: nextLegId++, side: t.side, type: t.type, lots: String(t.lots), strike: "", premium: "", hint: strikeHint(structure, t) }));
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

function Builder({ underlying, onUnderlying }: { underlying: string; onUnderlying: (u: string) => void }) {
  const { ask } = useCopilotShell();
  const { idx } = useSpot(underlying);
  const [view, setView] = useState<MarketView>("Bullish");
  const [structure, setStructure] = useState<Structure>(STRUCTURES.Bullish[0]);
  const [legs, setLegs] = useState<LegDraft[]>(() => draftsFor(STRUCTURES.Bullish[0]));
  const [lotSize, setLotSize] = useState("");
  /** True once legs were added, removed or flipped, so the picked name no longer describes them. */
  const [edited, setEdited] = useState(false);

  const pick = (s: Structure) => {
    setStructure(s);
    setLegs(draftsFor(s));
    setEdited(false);
  };
  const pickView = (v: MarketView) => {
    setView(v);
    pick(STRUCTURES[v][0]);
  };
  const patch = (id: number, change: Partial<LegDraft>, reshapes = false) => {
    setLegs((ls) => ls.map((l) => (l.id === id ? { ...l, ...change } : l)));
    if (reshapes) setEdited(true);
  };
  const addLeg = () => {
    setLegs((ls) => [...ls, { id: nextLegId++, side: "buy", type: "CE", lots: "1", strike: "", premium: "", hint: "Strike" }]);
    setEdited(true);
  };
  const removeLeg = (id: number) => {
    setLegs((ls) => ls.filter((l) => l.id !== id));
    setEdited(true);
  };

  const name = edited ? "Custom structure" : structure.name;
  const size = wholePositive(lotSize);
  const parsed = legs.map(parseLeg);
  const complete = parsed.filter((l): l is Leg => l != null);
  const payoff = size != null && complete.length > 0 && complete.length === legs.length ? analysePayoff(complete, size) : null;
  const on = underlying === OTHER ? "" : `${underlying} `;

  const explain = () => {
    if (!payoff || size == null) {
      ask(`Explain the risk of a ${on}${name.toLowerCase()}`);
      return;
    }
    const legText = complete.map((l) => `${l.side} ${l.lots} lot${l.lots > 1 ? "s" : ""} of the ${fmtLevel(l.strike)} ${l.type} at ${fmtPrice(l.premium)}`).join(", ");
    ask(
      `Explain the risk of this ${on}${name.toLowerCase()}: ${legText}; lot size ${fmtNum(size)}. At expiry the max profit is ${payoff.maxProfit == null ? "unlimited" : fmtINR(payoff.maxProfit)}, the max loss is ${payoff.maxLoss == null ? "unlimited" : fmtINR(payoff.maxLoss)} and the breakeven is ${payoff.breakevens.length ? payoff.breakevens.map(fmtLevel).join(" and ") : "none"}.`,
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
        <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          Pick a ready-made structure, then enter each leg’s strike and premium from your broker’s option chain. No chain is connected here, so no price is filled in for you. The small curves show each structure’s shape only.
        </span>
      </div>

      <div className="flex flex-col min-w-0" style={{ gap: 12 }}>
        <div className="cp-card flex flex-col" style={{ gap: 10, padding: 16 }}>
          <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
            <span data-testid="optlab-structure-name" className="cp-eyebrow">{name} · legs</span>
            <button type="button" data-testid="optlab-add-leg" onClick={addLeg} style={{ padding: 0, border: 0, background: "none", fontSize: 12, color: "var(--mint)", cursor: "pointer" }}>＋ Add leg</button>
          </div>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 8 }}>
            <label className="flex flex-col" style={{ gap: 4, minWidth: 0 }}>
              <span className="cp-mono-note">Underlying</span>
              <select data-testid="optlab-underlying" value={underlying} onChange={(e) => onUnderlying(e.target.value)} style={INPUT_STYLE}>
                {UNDERLYINGS.map((u) => <option key={u} value={u}>{u}</option>)}
              </select>
            </label>
            <label className="flex flex-col" style={{ gap: 4, minWidth: 0 }}>
              <span className="cp-mono-note">Lot size · units per lot</span>
              <input data-testid="optlab-lot-size" type="number" inputMode="numeric" min="1" step="1" placeholder="From the contract" value={lotSize} onChange={(e) => setLotSize(e.target.value)} style={INPUT_STYLE} />
            </label>
          </div>
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
          <PayoffResult payoff={payoff} lotSize={size} spot={idx?.value ?? null} underlying={underlying === OTHER ? null : underlying} />
        ) : (
          <div data-testid="optlab-payoff-empty">
            <EmptyBlock
              title="Enter the legs to see the payoff"
              body="Fill in the lot size and a strike and premium for every leg. Max profit, max loss, breakevens and the payoff at expiry are then worked out from exactly those numbers."
            />
          </div>
        )}

        <NotConnected
          testId="optlab-analytics-not-connected"
          title="Greeks, chance of profit and margin"
          body="The design also shows Delta, Gamma, Theta and Vega, a modelled chance of profit, a margin estimate and today’s payoff curve. Each needs market inputs the app does not have, so none is calculated from a guess."
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
  const [underlying, setUnderlying] = useState<string>(UNDERLYINGS[0]);

  return (
    <Screen testId="screen-tool-optlab">
      <div className="flex flex-wrap items-end justify-between" style={{ gap: 14 }}>
        <div style={{ flex: "1 1 320px", minWidth: 0 }}>
          <ScreenHeader
            eyebrow="Options lab · NSE F&O"
            pills={<><Pill tone="mint">Trader mode</Pill><Pill tone="indigo">Analysis only</Pill></>}
            title={<>Build, test and understand <em>option trades</em>.</>}
          />
        </div>
        <SpotBadge underlying={underlying} />
      </div>

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
          <NotConnected
            testId="optlab-chain-not-connected"
            title="The option chain is not connected"
            body="This tab is designed to list calls and puts by strike, with open interest, change in open interest, IV and last price, and the row nearest the spot marked. No app route returns a chain, so no strikes or prices are shown."
            needs={CHAIN_NEEDS}
          />
        )}
        {tab === "oi" && (
          <>
            <NotConnected
              testId="optlab-oi-not-connected"
              title="Open interest is not connected"
              body="This tab is designed to chart call and put open interest by strike around the money, with totals, the put-call ratio and max pain. It needs the same option chain as the first tab."
              needs={OI_NEEDS}
            />
            <Footnote>The exchange updates open interest every few minutes, so no source has truly real-time OI.</Footnote>
          </>
        )}
        {/* Kept mounted so the legs survive a look at the other tabs. */}
        <div hidden={tab !== "builder"}>
          <Builder underlying={underlying} onUnderlying={setUnderlying} />
        </div>
      </div>

      <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-danger)" }}>
        {SEBI_FNO_NOTE} Nivesh cannot place orders; everything here is analysis.
      </span>
    </Screen>
  );
}
