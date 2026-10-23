/**
 * Smart trading desk — Options & futures lab · Paper strategies: the leg-based builder. Design: the "F&O Lab Candidates" canvas, artboards Strategies and StrategiesMobile.
 *
 *   structure tiles -> editable trades (B/S, strike, lots, price) -> POST /api/desk/strategy/payoff -> the payoff chart, the summary strip and the what-if controls
 *
 * The builder works out NO payoff, Greek, cost or capital figure: it builds the request from the chain's end-of-day option closes and shows what the route answered
 * (StrategyGraphs: PayoffChart, PayoffSummary, ScenarioControls). Probability of profit and margin are what the route says they are (unavailable). Prices are end-of-day closes,
 * never live quotes. Option spreads cannot be recorded as paper trades (the desk's paper trades hold long shares only), so recording is disabled with that reason, and nothing here
 * is sent to a broker. The mini payoff shapes on the tiles are illustrations of each structure, not figures.
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { LoadingBlock } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { fmtLevel } from "../trading/PayoffResult";
import type { ChainState, FnoChain, FnoStrike } from "../trading/fno";
import { fmtDay } from "../trading/parts";
import { useDesk } from "./context";
import { buildupRowFor, indexRowFor, useBuildup, type BuildupLabel } from "./fno-buildup";
import { isIndexUnderlying } from "../trading/fno";
import { DEFAULT_SCENARIO, buildScenarioRequest, type ScenarioInputs } from "./strategy/ScenarioControls";
import { StrategyGraphs } from "./strategy/StrategyGraphs";
import type { PayoffLeg, PayoffRequest } from "./strategy/strategy-contract";
import { usePayoff } from "./strategy/usePayoff";

type View = "bullish" | "bearish" | "neutral" | "others";
type Side = "buy" | "sell";
type Kind = "call" | "put";

interface Spec { s: Side; t: Kind; k: number; q?: number }
interface Template { id: string; name: string; view: View; legs: Spec[]; pts: string }

/** Each structure as legs: side, type, how many strikes from the ATM strike, and lots. */
export const TEMPLATES: Template[] = [
  { id: "buy_call", name: "Buy Call", view: "bullish", legs: [{ s: "buy", t: "call", k: 0 }], pts: "2,26 24,26 58,6" },
  { id: "sell_put", name: "Sell Put", view: "bullish", legs: [{ s: "sell", t: "put", k: 0 }], pts: "2,32 24,10 58,10" },
  { id: "bull_call_spread", name: "Bull Call Spread", view: "bullish", legs: [{ s: "buy", t: "call", k: 0 }, { s: "sell", t: "call", k: 2 }], pts: "2,26 22,26 40,8 58,8" },
  { id: "bull_put_spread", name: "Bull Put Spread", view: "bullish", legs: [{ s: "sell", t: "put", k: 0 }, { s: "buy", t: "put", k: -2 }], pts: "2,30 20,30 38,10 58,10" },
  { id: "buy_put", name: "Buy Put", view: "bearish", legs: [{ s: "buy", t: "put", k: 0 }], pts: "2,6 24,26 58,26" },
  { id: "sell_call", name: "Sell Call", view: "bearish", legs: [{ s: "sell", t: "call", k: 0 }], pts: "2,10 24,10 58,32" },
  { id: "bear_put_spread", name: "Bear Put Spread", view: "bearish", legs: [{ s: "buy", t: "put", k: 0 }, { s: "sell", t: "put", k: -2 }], pts: "2,8 20,8 38,28 58,28" },
  { id: "bear_call_spread", name: "Bear Call Spread", view: "bearish", legs: [{ s: "sell", t: "call", k: 0 }, { s: "buy", t: "call", k: 2 }], pts: "2,10 22,10 40,30 58,30" },
  { id: "short_straddle", name: "Short Straddle", view: "neutral", legs: [{ s: "sell", t: "call", k: 0 }, { s: "sell", t: "put", k: 0 }], pts: "2,28 30,8 58,28" },
  { id: "short_strangle", name: "Short Strangle", view: "neutral", legs: [{ s: "sell", t: "call", k: 2 }, { s: "sell", t: "put", k: -2 }], pts: "2,28 16,10 44,10 58,28" },
  { id: "iron_condor", name: "Iron Condor", view: "neutral", legs: [{ s: "sell", t: "put", k: -2 }, { s: "buy", t: "put", k: -4 }, { s: "sell", t: "call", k: 2 }, { s: "buy", t: "call", k: 4 }], pts: "2,28 12,28 22,10 38,10 48,28 58,28" },
  { id: "long_straddle", name: "Long Straddle", view: "others", legs: [{ s: "buy", t: "call", k: 0 }, { s: "buy", t: "put", k: 0 }], pts: "2,8 30,28 58,8" },
  { id: "long_strangle", name: "Long Strangle", view: "others", legs: [{ s: "buy", t: "call", k: 2 }, { s: "buy", t: "put", k: -2 }], pts: "2,8 16,26 44,26 58,8" },
  { id: "call_butterfly", name: "Long Call Butterfly", view: "others", legs: [{ s: "buy", t: "call", k: -2 }, { s: "sell", t: "call", k: 0, q: 2 }, { s: "buy", t: "call", k: 2 }], pts: "2,26 18,26 30,6 42,26 58,26" },
];

const VIEWS: Array<{ key: View; label: string }> = [{ key: "bullish", label: "Bullish" }, { key: "bearish", label: "Bearish" }, { key: "neutral", label: "Neutral" }, { key: "others", label: "Others" }];

/** The structure a build-up label suggests, by the same rule as the rule-based ideas: long build-up and short covering a bull call spread, short build-up and long unwinding a bear put spread. */
export function suggestedTemplate(label: BuildupLabel | null): string | null {
  if (label === "long_buildup" || label === "short_covering") return "bull_call_spread";
  if (label === "short_buildup" || label === "long_unwinding") return "bear_put_spread";
  return null;
}

interface LegRow { id: number; side: Side; kind: Kind; strike: number; lots: number; price: string }

const closeOf = (r: FnoStrike | undefined, k: Kind): number | null => {
  const s = r?.[k === "call" ? "call" : "put"];
  return s ? s.close ?? s.settle ?? null : null;
};

let nextId = 1;

/** The legs of a template at the chain's strikes, priced at the end-of-day close (blank when the contract has no close). */
export function legsFor(t: Template, chain: FnoChain): LegRow[] {
  const at = chain.strikes.findIndex((r) => r.strike === chain.summary.atm_strike);
  const mid = at >= 0 ? at : Math.floor(chain.strikes.length / 2);
  return t.legs.map((l) => {
    const row = chain.strikes[Math.min(chain.strikes.length - 1, Math.max(0, mid + l.k))];
    const px = closeOf(row, l.t);
    return { id: nextId++, side: l.s, kind: l.t, strike: row.strike, lots: l.q ?? 1, price: px == null ? "" : String(px) };
  });
}

const field = { padding: "7px 9px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink)", fontFamily: "var(--mono)", fontSize: 12, minHeight: 36, minWidth: 0 } as const;
const quiet = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;


// ── funds and margin: Zerodha's margin calculator, through the platform's Kite session ───────────────────────────────────────

export interface MarginCharges { brokerage: number | null; stt: number | null; exchange: number | null; sebi: number | null; stampDuty: number | null; gst: number | null; total: number | null }
export interface MarginAnswer { required: number | null; initial: number | null; charges: MarginCharges; source: string | null; note: string | null }
type MarginState = { kind: "ok"; data: MarginAnswer } | { kind: "unavailable"; reason: string };

const mnum = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

export function parseMargin(body: unknown): MarginAnswer {
  const b = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
  const ch = ((b.charges as Record<string, unknown> | undefined)?.total ?? {}) as Record<string, unknown>;
  if (!("required_margin" in b)) throw ApiError.contractDrift("fno.margin: no required_margin");
  return {
    required: mnum(b.required_margin), initial: mnum(b.initial_margin), source: typeof b.source === "string" ? b.source : null, note: typeof b.note === "string" ? b.note : null,
    charges: { brokerage: mnum(ch.brokerage), stt: mnum(ch.stt), exchange: mnum(ch.exchange), sebi: mnum(ch.sebi), stampDuty: mnum(ch.stamp_duty), gst: mnum(ch.gst), total: mnum(ch.total) },
  };
}

/** The margin for the legs on screen. A 503 (the platform is not logged in to Kite today) or any failure is "Unavailable" with the reason, never a guess. */
function useMargin(symbol: string, expiry: string | null, legs: LegRow[], enabled: boolean) {
  const key = JSON.stringify([symbol, expiry, legs.map((l) => [l.side, l.kind, l.strike, l.lots])]);
  return useQuery<MarginState>({
    queryKey: ["copilot", "desk", "fno-margin", key],
    enabled: enabled && !!expiry && legs.length > 0,
    staleTime: 60_000,
    retry: false,
    queryFn: async ({ signal }) => {
      try {
        const res = await http({ method: "POST", path: "/api/fno/margin", noRetry: true, timeoutMs: 20_000, signal,
          body: { underlying: symbol, legs: legs.map((l) => ({ side: l.side, option_type: l.kind, expiry, strike: l.strike, lots: l.lots })) } });
        return { kind: "ok", data: parseMargin(res.data) };
      } catch (e) {
        if (e instanceof ApiError && e.status === 503) return { kind: "unavailable", reason: "The platform is not logged in to Kite today, so the broker’s margin calculator cannot be asked." };
        if (e instanceof ApiError && e.status === 404) return { kind: "unavailable", reason: e.detail ?? "A contract is not listed." };
        return { kind: "unavailable", reason: "The margin calculator did not answer just now." };
      }
    },
  });
}

const inr = (n: number | null) => (n == null ? "—" : `₹${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(n)}`);

function MarginStrip({ state }: { state: ReturnType<typeof useMargin> }) {
  const m = state.data;
  return (
    <div data-testid="desk-builder-margin" className="flex flex-col" style={{ gap: 6, padding: "12px 14px", borderRadius: 12, background: "var(--bg-1)", border: "1px solid var(--line-2)" }}>
      <div className="flex flex-wrap items-baseline" style={{ gap: "6px 18px" }}>
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>Funds and margin needed</span>
        {state.isPending && state.fetchStatus !== "idle" && <span style={quiet}>Asking the margin calculator…</span>}
        {m?.kind === "ok" && <span data-testid="desk-builder-margin-required" style={{ fontFamily: "var(--mono)", fontSize: 16 }}>{inr(m.data.required)}</span>}
        {m?.kind === "unavailable" && <span data-testid="desk-builder-margin-unavailable" style={{ ...quiet, color: "var(--cp-ink-2)" }}>Unavailable · {m.reason}</span>}
      </div>
      {m?.kind === "ok" && (
        <>
          <span data-testid="desk-builder-charges" style={quiet}>
            Charges for the entry orders: {inr(m.data.charges.total)} (brokerage {inr(m.data.charges.brokerage)}, STT {inr(m.data.charges.stt)}, exchange {inr(m.data.charges.exchange)}, GST {inr(m.data.charges.gst)}). Initial margin {inr(m.data.initial)}.
          </span>
          <span style={quiet}>{m.data.source}. {m.data.note}</span>
        </>
      )}
    </div>
  );
}

export function BuilderView({ symbol, state }: { symbol: string; state: ChainState }) {
  const { mobile } = useCopilotShell();
  const { persona, openStrategy } = useDesk();
  const scan = useBuildup(true);
  const chain = state.status === "ok" ? state.chain : null;
  const row = isIndexUnderlying(symbol) ? indexRowFor(scan.data, symbol) : buildupRowFor(scan.data, symbol);
  const suggested = suggestedTemplate(row?.label ?? null);
  const [view, setView] = useState<View>("bullish");
  const [tpl, setTpl] = useState<string | null>(null);
  const [legs, setLegs] = useState<LegRow[]>([]);
  const [scn, setScn] = useState<ScenarioInputs>(DEFAULT_SCENARIO);
  const key = chain ? `${symbol}|${chain.summary.expiry}|${chain.summary.as_of}` : null;

  // A new underlying or expiry starts from the structure the build-up suggests (or nothing), once the chain and the scan are in.
  useEffect(() => {
    setLegs([]); setTpl(null); setScn(DEFAULT_SCENARIO);
    if (!chain || scan.isPending) return;
    const t = TEMPLATES.find((x) => x.id === suggested);
    if (t) { setTpl(t.id); setView(t.view); setLegs(legsFor(t, chain)); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, scan.isPending, suggested]);

  const lot = chain?.lot_size ?? null;
  const problem = useMemo(() => {
    if (!legs.length) return "Pick a structure to load its trades.";
    if (lot == null) return "The contract’s lot size is not available, so a payoff cannot be worked out.";
    const bad = legs.find((l) => !(Number(l.price) > 0));
    if (bad) return `The ${fmtLevel(bad.strike)} ${bad.kind === "call" ? "call" : "put"} has no end-of-day close: enter a price to continue.`;
    if (legs.some((l) => !(l.lots > 0))) return "Every trade needs at least one lot.";
    return null;
  }, [legs, lot]);

  const base = useMemo<PayoffRequest | null>(() => {
    if (!chain || problem || chain.summary.spot == null || lot == null) return null;
    const payoffLegs: PayoffLeg[] = legs.map((l) => ({
      kind: "option", side: l.side, quantity: l.lots, lot_size: lot, entry_price: Number(l.price), expiry: chain.summary.expiry, strike: l.strike,
      option_type: l.kind, price_source: "end-of-day close", underlying: symbol,
    }));
    return { underlying: symbol, reference_price: chain.summary.spot, as_of: chain.summary.as_of, legs: payoffLegs, grid: { from_pct: -12, to_pct: 12, points: 121 } };
  }, [chain, legs, lot, problem, symbol]);
  const changed = scn.underlyingPrice != null || scn.size != null || scn.evalDate != null || scn.ivShiftPct !== 0;
  const request = base ? (changed ? buildScenarioRequest(base, scn) : base) : null;
  const pay = usePayoff(request);
  const marginQ = useMargin(symbol, chain?.summary.expiry ?? null, legs, !problem && !!chain);

  if (state.status === "loading") return <LoadingBlock label={`Loading the ${symbol} chain`} rows={4} />;
  if (!chain) return <span data-testid="desk-builder-nochain" style={quiet}>{state.status === "none" ? state.message : `The ${symbol} chain didn’t load, so there is nothing to build on.`}</span>;

  const setLeg = (id: number, patch: Partial<LegRow>) => setLegs((ls) => ls.map((l) => (l.id === id ? { ...l, ...patch } : l)));
  const pickStrike = (id: number, kind: Kind, strike: number) => {
    const px = closeOf(chain.strikes.find((r) => r.strike === strike), kind);
    setLeg(id, { strike, price: px == null ? "" : String(px) });
  };
  const load = (t: Template) => { setTpl(t.id); setLegs(legsFor(t, chain)); setScn(DEFAULT_SCENARIO); };
  const tiles = TEMPLATES.filter((t) => t.view === view);
  const response = pay.data;
  const netLabel = response?.expiry?.net_premium != null ? (response.expiry.net_premium < 0 ? "Net debit" : "Net credit") : null;

  return (
    <div data-testid="desk-builder" data-symbol={symbol} className="flex min-w-0 flex-wrap" style={{ gap: 16, alignItems: "flex-start" }}>
      <div className="flex min-w-0 flex-col" style={{ flex: mobile ? "1 1 100%" : "1 1 400px", maxWidth: mobile ? "100%" : 470, gap: 14 }}>
        <section className="cp-card flex flex-col" style={{ gap: 12, padding: 14 }}>
          <div className="flex flex-wrap items-center justify-between" style={{ gap: 6 }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>Trades{tpl ? ` · ${TEMPLATES.find((t) => t.id === tpl)?.name}` : ""}</span>
            <span className="cp-mono-note">{fmtDay(chain.summary.expiry)} expiry · lot {lot ?? "—"}</span>
          </div>
          {suggested && tpl === suggested && <span data-testid="desk-builder-suggested" style={quiet}>Suggested by the {row?.label?.replace("_", " ")}; your view decides. End-of-day closes, not live quotes.</span>}
          {legs.length === 0 ? <span data-testid="desk-builder-empty" style={quiet}>No trades yet. Pick a structure below, or add a trade.</span> : (
            <div className="flex flex-col" style={{ gap: 8 }}>
              {legs.map((l) => (
                <div key={l.id} data-testid="desk-builder-leg" data-side={l.side} data-kind={l.kind} className="grid items-center" style={{ gridTemplateColumns: "auto minmax(0,1.2fr) minmax(0,0.7fr) minmax(0,0.9fr) auto", gap: 6 }}>
                  <button type="button" aria-label={`${l.side === "buy" ? "Buy" : "Sell"}: switch`} data-testid="desk-builder-side" onClick={() => setLeg(l.id, { side: l.side === "buy" ? "sell" : "buy" })}
                    style={{ ...field, width: 44, cursor: "pointer", fontWeight: 600, color: l.side === "buy" ? "var(--mint)" : "var(--cp-danger)" }}>{l.side === "buy" ? "BUY" : "SELL"}</button>
                  <span className="flex items-center" style={{ gap: 4 }}>
                    <select aria-label="Strike" data-testid="desk-builder-strike" value={l.strike} onChange={(e) => pickStrike(l.id, l.kind, Number(e.target.value))} style={{ ...field, flex: "1 1 auto" }}>
                      {chain.strikes.filter((r) => r[l.kind === "call" ? "call" : "put"]).map((r) => <option key={r.strike} value={r.strike}>{fmtLevel(r.strike)}</option>)}
                    </select>
                    <button type="button" aria-label={`Type: ${l.kind}; switch`} data-testid="desk-builder-type" onClick={() => { const k: Kind = l.kind === "call" ? "put" : "call"; const px = closeOf(chain.strikes.find((r) => r.strike === l.strike), k); setLeg(l.id, { kind: k, price: px == null ? "" : String(px) }); }}
                      style={{ ...field, width: 40, cursor: "pointer" }}>{l.kind === "call" ? "CE" : "PE"}</button>
                  </span>
                  <input aria-label="Lots" data-testid="desk-builder-lots" type="number" min={1} step={1} value={l.lots} onChange={(e) => setLeg(l.id, { lots: Math.max(0, Math.floor(Number(e.target.value) || 0)) })} style={field} />
                  <input aria-label="Price" data-testid="desk-builder-price" inputMode="decimal" value={l.price} placeholder="no close" onChange={(e) => setLeg(l.id, { price: e.target.value })} style={field} />
                  <button type="button" aria-label="Remove trade" data-testid="desk-builder-remove" onClick={() => setLegs((ls) => ls.filter((x) => x.id !== l.id))} style={{ ...field, width: 36, cursor: "pointer", color: "var(--cp-ink-3)" }}>×</button>
                </div>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <button type="button" data-testid="desk-builder-add" className="cp-btn" data-variant="ghost" onClick={() => {
              const at = chain.strikes.find((r) => r.strike === chain.summary.atm_strike) ?? chain.strikes[0];
              setLegs((ls) => [...ls, { id: nextId++, side: "buy", kind: "call", strike: at.strike, lots: 1, price: closeOf(at, "call") == null ? "" : String(closeOf(at, "call")) }]);
            }}>Add a trade</button>
            {legs.length > 0 && <button type="button" className="cp-btn" data-variant="ghost" data-testid="desk-builder-clear" onClick={() => { setLegs([]); setTpl(null); setScn(DEFAULT_SCENARIO); }}>Clear</button>}
            <button type="button" disabled data-testid="desk-builder-record" className="cp-btn" data-variant="ghost" style={{ opacity: 0.5, cursor: "not-allowed" }}>Record as paper trade</button>
            <button type="button" data-testid="desk-builder-full" className="cp-btn" data-variant="ghost" onClick={() => openStrategy(symbol, { kind: "lab", date: chain.summary.as_of })}>Open the full Strategy Builder ›</button>
          </div>
          <span data-testid="desk-builder-record-why" style={quiet}>Recording is off for option structures: the desk’s paper trades hold long shares only. Nothing is sent to a broker.</span>
        </section>

        <section className="cp-card flex flex-col" style={{ gap: 12, padding: 14 }}>
          <div role="group" aria-label="Market view" className="flex flex-wrap" style={{ gap: 6 }}>
            {VIEWS.map((v) => (
              <button key={v.key} type="button" aria-pressed={view === v.key} data-testid={`desk-builder-view-${v.key}`} onClick={() => setView(v.key)}
                style={{ padding: "6px 12px", minHeight: 36, borderRadius: 999, fontSize: 13, cursor: "pointer", border: `1px solid ${view === v.key ? "var(--mint-line)" : "var(--line-2)"}`, background: view === v.key ? "var(--mint-soft)" : "transparent", color: view === v.key ? "var(--mint)" : "var(--cp-ink-2)" }}>{v.label}</button>
            ))}
          </div>
          <span style={quiet}>Pick a structure to load it. A view is your own; no structure is shown as better than another. The shapes are illustrations.</span>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(88px,1fr))", gap: 10 }}>
            {tiles.map((t) => (
              <button key={t.id} type="button" aria-pressed={tpl === t.id} data-testid={`desk-builder-tile-${t.id}`} onClick={() => load(t)}
                className="flex flex-col items-center" style={{ gap: 6, padding: "10px 6px", minHeight: 88, borderRadius: 10, cursor: "pointer", background: "var(--bg-1)", border: `1px solid ${tpl === t.id ? "var(--mint-line)" : "var(--line-2)"}` }}>
                <svg viewBox="0 0 60 40" aria-hidden="true" style={{ width: 60, height: 40 }}><line x1="0" y1="18" x2="60" y2="18" stroke="currentColor" strokeOpacity="0.25" strokeDasharray="3 3" /><polyline points={t.pts} fill="none" stroke="var(--mint)" strokeWidth="2" /></svg>
                <span style={{ fontSize: 11, lineHeight: 1.25, color: "var(--cp-ink-2)", textAlign: "center" }}>{t.name}</span>
              </button>
            ))}
          </div>
        </section>
      </div>

      <div className="flex min-w-0 flex-col" style={{ flex: "999 1 520px", gap: 12 }}>
        {problem ? <span data-testid="desk-builder-problem" style={quiet}>{problem}</span> : base && (
          <>
            {netLabel && response?.expiry?.net_premium != null && (
              <span data-testid="desk-builder-net" className="cp-mono-note">{netLabel} {fmtLevel(Math.abs(response.expiry.net_premium))} for the position (end-of-day closes, before costs)</span>
            )}
            <MarginStrip state={marginQ} />
            <StrategyGraphs
              base={base} response={response} errorText={pay.errorText} pending={pay.isPending} stale={pay.isStale} onRetry={pay.refetch}
              scenario={scn} onScenarioChange={setScn} dataDate={chain.summary.as_of} persona={persona} compact={mobile}
            />
          </>
        )}
        <span style={quiet}>
          Rule-based structures, not forecasts: none has been shown to beat a random choice. Whether a spread beats a future depends on volatility, time decay, cost and your risk limit. Research and hypothetical scenarios only.
        </span>
      </div>
    </div>
  );
}
