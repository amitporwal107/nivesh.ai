/**
 * Strategy Lab › Build a trade, step 3 — Review & adjust (the owner's design, 28 Oct).
 *
 * Left: the leg editor (LEG · SIDE · STRIKE · EXPIRY · LOTS · PRICE · CASH FLOW, a chevron for details), "+ Cash · + Future
 * · + Call · + Put" (Call / Put open the chain picker), "Clear all legs"; the PAYOFF card (the route's at-expiry and today
 * curves, the scenario spot slider — a scenario tool, not a risk setting — and the two P/L tiles read off those curves).
 * Right: STRATEGY SUMMARY, NET GREEKS · NOW, CHECKS (the chain's age, your build limits, the payoff engine's problems and
 * the risk service's own decision for this structure on your account), then on to step 4.
 *
 * Every number is the route's: payoff-v2 (POST /api/desk/strategy/payoff), the chain (strikes, closes, ATM IV), Zerodha's
 * margin calculator (POST /api/fno/margin), the risk service (POST /api/desk/paper-trades/check). Probability of profit is
 * the lognormal read of the route's own curve (wizard-data popOf), labelled "(model)".
 */
import { useState, type CSSProperties, type ReactNode } from "react";
import { Btn } from "../../../../../components/ui";
import type { FnoChain, FnoExpiry, FnoFutures } from "../../../../trading/fno";
import type { PayoffResponse } from "../../../strategy/strategy-contract";
import { ChainPicker, STALE_DAYS, daysBetween, todayIso } from "./ChainPicker";
import { at, fmtStrike, legId, legsSummary, shortDay, type CheckState, type Pop, type WLeg } from "./wizard-data";
import { Card, PayoffPlot, Pill, Stepper, eyebrowS, inr, mono, quietS } from "./ui";

export type MarginView = { kind: "ok"; required: number | null; source: string | null } | { kind: "unavailable"; reason: string } | { kind: "pending" } | { kind: "none" };

export interface Structure {
  problem: string | null;
  pay: { data: PayoffResponse | undefined; errorText: string | null; isPending: boolean; isStale: boolean };
  pop: Pop | null;
  margin: MarginView;
  check: { state: CheckState | undefined; pending: boolean; error: string | null };
  limits: Array<{ ok: boolean; text: string }>;
}

const SIDE_COLOR = { buy: "var(--mint)", sell: "var(--cp-danger)" } as const;
const sel: CSSProperties = { height: 30, padding: "0 6px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink)", fontSize: 12 };
const cell: CSSProperties = { padding: "6px 6px", verticalAlign: "middle" };

/** The leg's cash flow at entry: − for a buy, + for a sell, lots × lot size × price (shares × price for cash). */
export function cashFlow(l: WLeg, lot: number | null): number | null {
  if (l.price == null) return null;
  const units = l.kind === "cash" ? l.lots : lot != null ? l.lots * lot : null;
  return units == null ? null : (l.side === "buy" ? -1 : 1) * units * l.price;
}

export function StepReview({ symbol, chain, expiries, futures, legs, onLegs, getChain, structure, onNext, notice }: {
  symbol: string; chain: FnoChain | null; expiries: FnoExpiry[]; futures: FnoFutures | null; legs: WLeg[];
  onLegs: (next: WLeg[]) => void; getChain: (expiry: string) => Promise<FnoChain | null>; structure: Structure; onNext: () => void; notice?: ReactNode;
}) {
  const [picker, setPicker] = useState<{ focus: "call" | "put" | null; expiry: string | null } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [scnPct, setScnPct] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const lot = chain?.lot_size ?? null;
  const spot = chain?.summary.spot ?? null;
  const listed = expiries.filter((e) => e.days_to_expiry >= 0).slice(0, 3);
  const asOf = chain?.summary.as_of ?? null;
  const age = asOf ? daysBetween(asOf, todayIso()) : null;
  const stale = age != null && age > STALE_DAYS;

  const patch = (id: string, p: Partial<WLeg>) => onLegs(legs.map((l) => (l.id === id ? { ...l, ...p } : l)));
  const futPrice = (expiry: string | null) => {
    const f = futures?.futures.find((x) => x.expiry === expiry) ?? futures?.futures[0];
    return f ? { price: f.close ?? f.settle ?? null, expiry: f.expiry, source: `NSE F&O bhavcopy futures close, ${futures?.as_of}` } : null;
  };
  /** Reprice an option leg from the chain of its (new) expiry at its (new) strike. Not listed → no price, said so. */
  const reprice = async (l: WLeg, p: Partial<WLeg>) => {
    const next = { ...l, ...p };
    if (next.kind !== "option" || !next.expiry) { patch(l.id, p); return; }
    setBusy(l.id);
    try {
      const c = next.expiry === chain?.summary.expiry ? chain : await getChain(next.expiry);
      const strikes = c?.strikes ?? [];
      let strike = next.strike;
      if (strike != null && !strikes.some((r) => r.strike === strike)) {
        // The same strike is not listed on that expiry: the nearest listed one, said in the price source.
        const near = strikes.reduce<number | null>((b, r) => (b == null || Math.abs(r.strike - (strike as number)) < Math.abs(b - (strike as number)) ? r.strike : b), null);
        strike = near;
      }
      const row = strikes.find((r) => r.strike === strike);
      const s = row?.[next.optionType === "put" ? "put" : "call"];
      const px = s ? s.close ?? s.settle ?? null : null;
      patch(l.id, { ...p, strike, price: px, priceSource: c ? `NSE F&O bhavcopy close, ${c.summary.as_of}` : null });
    } finally {
      setBusy(null);
    }
  };
  const stepStrike = (l: WLeg, dir: 1 | -1) => {
    const c = l.expiry === chain?.summary.expiry ? chain : null;
    const strikes = (c ?? chain)?.strikes ?? [];
    const i = strikes.findIndex((r) => r.strike === l.strike);
    const j = i < 0 ? -1 : i + dir;
    if (j < 0 || j >= strikes.length) return;
    void reprice(l, { strike: strikes[j].strike });
  };
  const setType = (l: WLeg, v: string) => {
    if (v === "call" || v === "put") {
      const strike = l.strike ?? chain?.summary.atm_strike ?? null;
      void reprice(l, { kind: "option", optionType: v, strike, expiry: l.expiry ?? chain?.summary.expiry ?? null, lots: l.kind === "cash" ? 1 : l.lots });
    } else if (v === "future") {
      const f = futPrice(l.expiry ?? chain?.summary.expiry ?? null);
      patch(l.id, { kind: "future", optionType: null, strike: null, expiry: f?.expiry ?? l.expiry, price: f?.price ?? null, priceSource: f?.source ?? null, lots: l.kind === "cash" ? 1 : l.lots });
    } else {
      patch(l.id, { kind: "cash", optionType: null, strike: null, expiry: null, price: spot, priceSource: asOf ? `NSE F&O bhavcopy underlying price, ${asOf}` : null, lots: lot ?? 1 });
    }
  };
  const addCash = () => onLegs([...legs, { id: legId(), kind: "cash", side: "buy", optionType: null, strike: null, expiry: null, lots: lot ?? 1, price: spot, priceSource: asOf ? `NSE F&O bhavcopy underlying price, ${asOf}` : null }]);
  const addFuture = () => {
    const f = futPrice(chain?.summary.expiry ?? null);
    onLegs([...legs, { id: legId(), kind: "future", side: "buy", optionType: null, strike: null, expiry: f?.expiry ?? chain?.summary.expiry ?? null, lots: 1, price: f?.price ?? null, priceSource: f?.source ?? null }]);
  };
  const addFromChain = (side: "buy" | "sell", t: "call" | "put", strike: number, expiry: string, price: number, source: string) => {
    const same = legs.find((l) => l.kind === "option" && l.optionType === t && l.strike === strike && l.expiry === expiry && l.side === side);
    if (same) onLegs(legs.map((l) => (l.id === same.id ? { ...l, lots: l.lots + 1 } : l)));
    else onLegs([...legs, { id: legId(), kind: "option", side, optionType: t, strike, expiry, lots: 1, price, priceSource: source }]);
  };

  const r = structure.pay.data;
  const e = r?.valid ? r.expiry : null;
  const pre = r?.valid ? r.pre_expiry : null;
  const grid = e?.grid ?? [];
  const scn = spot != null ? spot * (1 + scnPct / 100) : null;
  const plExp = scn != null && e ? at(grid, e.net, scn) : null;
  const plToday = scn != null && pre?.net && pre.grid ? at(pre.grid, pre.net, scn) : null;
  const fo = legs.filter((l) => l.kind !== "cash");
  const exps = [...new Set(fo.map((l) => l.expiry).filter((x): x is string => !!x))].sort();
  const nearest = exps[0] ?? null;
  const cashCap = legs.filter((l) => l.kind === "cash" && l.price != null).reduce((s, l) => s + l.lots * (l.price as number) * (l.side === "buy" ? 1 : -1), 0);
  const hasCash = legs.some((l) => l.kind === "cash");
  const g = pre?.greeks ?? null;
  const ivs = (pre?.assumptions as { legs?: Array<{ iv_pct?: number | null }> } | undefined)?.legs?.map((x) => x.iv_pct).filter((x): x is number => typeof x === "number") ?? [];
  const np = e?.net_premium ?? null;
  const mp = e ? (e.profit_unbounded ? null : e.max_profit) : null;
  const ml = e ? (e.loss_unbounded ? null : e.max_loss) : null;
  const rr = mp != null && ml != null && ml < 0 && mp > 0 ? mp / Math.abs(ml) : null;
  const costs = r?.valid ? (r.costs as { round_trip?: number | null } | null)?.round_trip ?? null : null;

  return (
    <div data-testid="wz-step-3" className="flex min-w-0 flex-wrap" style={{ gap: 16, alignItems: "flex-start" }}>
      <div className="flex min-w-0 flex-col" style={{ flex: "999 1 560px", gap: 14 }}>
        {notice}
        <Card testId="wz-legs" title="Legs" right={chain ? `${symbol} · lot ${lot ?? "—"}` : symbol}>
          {legs.length === 0 ? <span data-testid="wz-legs-empty" style={quietS}>No legs. Add one below, or open the chain and press B or S on a contract.</span> : (
            <div className="cp-scroll" style={{ maxWidth: "100%", overflowX: "auto" }}>
              <table data-testid="wz-leg-table" style={{ width: "100%", minWidth: 640, borderCollapse: "collapse", fontSize: 12.5 }}>
                <thead>
                  <tr style={{ ...eyebrowS, fontSize: 9.5, textAlign: "left" }}>
                    {["Leg", "Side", "Strike", "Expiry", "Lots", "Price", "Cash flow", ""].map((h) => <th key={h} style={{ ...cell, textAlign: h === "Price" || h === "Cash flow" ? "right" : "left" }}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {legs.map((l) => {
                    const cf = cashFlow(l, lot);
                    const isOpen = open === l.id;
                    const row = l.kind === "option" ? (l.expiry === chain?.summary.expiry ? chain : null)?.strikes.find((x) => x.strike === l.strike)?.[l.optionType === "put" ? "put" : "call"] : null;
                    return [
                      <tr key={l.id} data-testid="wz-leg" data-kind={l.kind} data-side={l.side} data-type={l.optionType ?? ""} data-strike={l.strike ?? ""} data-expiry={l.expiry ?? ""} data-lots={l.lots} aria-busy={busy === l.id}
                        style={{ borderTop: "1px solid var(--cp-line)" }}>
                        <td style={cell}>
                          <select aria-label="Leg type" data-testid="wz-leg-type" value={l.kind === "option" ? l.optionType ?? "call" : l.kind} onChange={(ev) => setType(l, ev.target.value)} style={sel}>
                            <option value="call">CALL</option><option value="put">PUT</option><option value="future">FUT</option><option value="cash">CASH</option>
                          </select>
                        </td>
                        <td style={cell}>
                          <button type="button" data-testid="wz-leg-side" aria-label={`${l.side === "buy" ? "Buy" : "Sell"}: switch`} onClick={() => patch(l.id, { side: l.side === "buy" ? "sell" : "buy" })}
                            style={{ minWidth: 48, height: 28, borderRadius: 8, fontWeight: 700, fontSize: 11.5, cursor: "pointer", border: `1px solid ${SIDE_COLOR[l.side]}`, color: SIDE_COLOR[l.side], background: "transparent" }}>{l.side === "buy" ? "BUY" : "SELL"}</button>
                        </td>
                        <td style={cell}>
                          {l.kind === "option" ? (
                            <span className="inline-flex items-center" style={{ gap: 4 }} data-testid="wz-leg-strike">
                              <button type="button" aria-label="Strike down one listed strike" data-testid="wz-leg-strike-minus" onClick={() => stepStrike(l, -1)} style={miniBtn}>−</button>
                              <span data-testid="wz-leg-strike-value" style={{ ...mono, minWidth: 52, textAlign: "center" }}>{l.strike != null ? fmtStrike(l.strike) : "—"}</span>
                              <button type="button" aria-label="Strike up one listed strike" data-testid="wz-leg-strike-plus" onClick={() => stepStrike(l, 1)} style={miniBtn}>+</button>
                            </span>
                          ) : <span style={quietS}>—</span>}
                        </td>
                        <td style={cell}>
                          {l.kind === "cash" ? <span style={quietS}>—</span> : (
                            <span className="inline-flex flex-wrap" style={{ gap: 4 }} data-testid="wz-leg-expiry">
                              {listed.map((x) => {
                                const on = x.expiry === l.expiry;
                                return (
                                  <button key={x.expiry} type="button" aria-pressed={on} data-testid={`wz-leg-expiry-${x.expiry}`}
                                    onClick={() => (l.kind === "future" ? (() => { const f = futures?.futures.find((y) => y.expiry === x.expiry); patch(l.id, { expiry: x.expiry, price: f ? f.close ?? f.settle ?? null : null, priceSource: f ? `NSE F&O bhavcopy futures close, ${futures?.as_of}` : null }); })() : void reprice(l, { expiry: x.expiry }))}
                                    style={{ padding: "3px 8px", borderRadius: 999, fontSize: 11, cursor: "pointer", border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`, background: on ? "var(--mint-soft)" : "transparent", color: on ? "var(--mint)" : "var(--cp-ink-3)" }}>
                                    {shortDay(x.expiry)}
                                  </button>
                                );
                              })}
                              {l.expiry && !listed.some((x) => x.expiry === l.expiry) && <Pill tone="amber" testId="wz-leg-expiry-other">{shortDay(l.expiry)}</Pill>}
                            </span>
                          )}
                        </td>
                        <td style={cell}><Stepper value={l.lots} min={1} max={l.kind === "cash" ? 1_000_000 : 1000} step={l.kind === "cash" ? lot ?? 1 : 1} label={l.kind === "cash" ? "Shares" : "Lots"} testId="wz-leg-lots" onChange={(n) => patch(l.id, { lots: n })} /></td>
                        <td data-testid="wz-leg-price" style={{ ...cell, ...mono, textAlign: "right" }}>{l.price != null ? fmtStrike(l.price) : <span title="No price in the chain for this contract" style={{ color: "var(--amber)" }}>—</span>}</td>
                        <td data-testid="wz-leg-cashflow" style={{ ...cell, ...mono, textAlign: "right", color: cf == null ? undefined : cf < 0 ? "var(--cp-danger)" : "var(--mint)" }}>{inr(cf, true)}</td>
                        <td style={cell}>
                          <button type="button" aria-expanded={isOpen} aria-label="Leg details" data-testid="wz-leg-more" onClick={() => setOpen(isOpen ? null : l.id)} style={{ ...miniBtn, transform: isOpen ? "rotate(90deg)" : undefined }}>›</button>
                        </td>
                      </tr>,
                      isOpen ? (
                        <tr key={`${l.id}-d`} data-testid="wz-leg-details"><td colSpan={8} style={{ ...cell, paddingTop: 0 }}>
                          <span className="flex flex-wrap items-center" style={{ gap: "4px 14px", ...quietS }}>
                            <span>Price source: {l.priceSource ?? "none"}</span>
                            {row?.delta != null && <span>Chain Δ {row.delta.toFixed(2)}</span>}
                            {row?.iv != null && <span>Chain IV {row.iv.toFixed(1)}%</span>}
                            <button type="button" data-testid="wz-leg-remove" className="cp-btn" data-variant="ghost" onClick={() => onLegs(legs.filter((x) => x.id !== l.id))}>Remove leg</button>
                          </span>
                        </td></tr>
                      ) : null,
                    ];
                  })}
                </tbody>
              </table>
            </div>
          )}
          {legs.length > 0 && <span data-testid="wz-legs-line" style={{ ...mono, fontSize: 11.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{legsSummary(legs)}</span>}
          <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <button type="button" className="cp-btn" data-variant="ghost" data-testid="wz-add-cash" onClick={addCash}>+ Cash</button>
            <button type="button" className="cp-btn" data-variant="ghost" data-testid="wz-add-future" onClick={addFuture}>+ Future</button>
            <button type="button" className="cp-btn" data-variant="ghost" data-testid="wz-add-call" onClick={() => setPicker({ focus: "call", expiry: nearest ?? chain?.summary.expiry ?? null })}>+ Call</button>
            <button type="button" className="cp-btn" data-variant="ghost" data-testid="wz-add-put" onClick={() => setPicker({ focus: "put", expiry: nearest ?? chain?.summary.expiry ?? null })}>+ Put</button>
            <button type="button" className="cp-btn" data-variant="ghost" data-testid="wz-from-chain" onClick={() => setPicker({ focus: null, expiry: nearest ?? chain?.summary.expiry ?? null })}>From chain</button>
            {legs.length > 0 && <button type="button" className="cp-btn" data-variant="ghost" data-testid="wz-clear-legs" onClick={() => onLegs([])} style={{ color: "var(--cp-danger)" }}>Clear all legs</button>}
          </div>
          <span data-testid="wz-legs-note" style={quietS}>
            {lot != null ? `One lot is ${new Intl.NumberFormat("en-IN").format(lot)} shares. ` : ""}
            {asOf ? (stale
              ? `The chain snapshot is the NSE close of ${shortDay(asOf)} (${age} days old), so option prices are estimates, not quotes. `
              : `Option prices are the chain prices: the NSE close of ${shortDay(asOf)}, not live quotes. `) : ""}
            {"“Today” is Black-76 at the volatility solved from each leg's own close. "}
            Legs can be set to different expiries here; the payoff engine and the paper-trade route accept one expiry for now, so a calendar is shown as not supported rather than drawn.
          </span>
        </Card>

        <Card testId="wz-payoff" title={<>Payoff · nearest expiry {nearest ? shortDay(nearest) : "—"} — at expiry ·· today</>} right={spot != null ? <span data-testid="wz-payoff-spot">Spot {fmtStrike(spot)}</span> : undefined}>
          {structure.problem ? <span data-testid="wz-payoff-problem" style={quietS}>{structure.problem}</span>
            : structure.pay.errorText ? <span data-testid="wz-payoff-error" role="alert" style={{ ...quietS, color: "var(--cp-danger)" }}>{structure.pay.errorText}</span>
            : r && !r.valid ? (
              <ul data-testid="wz-payoff-invalid" className="m-0" style={{ paddingLeft: 16, ...quietS, color: "var(--amber)" }}>{r.problems.map((p, i) => <li key={i}>{p.message}</li>)}</ul>
            ) : !e || spot == null ? <span style={quietS}>Working out the payoff…</span> : (
              <>
                <PayoffPlot grid={grid} expiry={e.net} today={pre?.net && pre.grid && pre.grid.length === grid.length ? pre.net : null} spot={spot} scenario={scn ?? spot} breakevens={e.breakevens} stale={structure.pay.isStale} />
                <span className="flex flex-wrap" style={{ gap: "2px 14px", ...quietS, fontSize: 11 }}>
                  <span>— at expiry, net of costs (payoff-v2)</span>
                  <span>- - today, {pre?.model ?? "Black-76"} model{pre?.date ? ` on ${shortDay(pre.date)}` : ""}{!pre?.net ? ": not available" : ""}</span>
                  {e.breakevens.length > 0 && <span>BE {e.breakevens.map((b) => fmtStrike(b)).join(" · ")}</span>}
                </span>
                <label className="flex min-w-0 flex-col" style={{ gap: 6 }}>
                  <span className="flex flex-wrap items-baseline justify-between" style={{ gap: 6 }}>
                    <span style={eyebrowS}>Scenario spot move</span>
                    <span data-testid="wz-scenario-label" style={{ ...mono, fontSize: 12 }}>{scnPct >= 0 ? "+" : "−"}{Math.abs(scnPct).toFixed(1)}% → {scn != null ? fmtStrike(Math.round(scn * 100) / 100) : "—"}</span>
                  </span>
                  <input type="range" data-testid="wz-scenario" aria-label="Scenario spot move (a scenario tool, not a risk setting)" min={-20} max={20} step={0.5} value={scnPct} onChange={(ev) => setScnPct(Number(ev.target.value))} style={{ width: "100%" }} />
                  <span style={{ ...quietS, fontSize: 11 }}>A scenario tool, not a risk setting: it moves the spot on the chart and reads both curves there.</span>
                </label>
                <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,150px),1fr))", gap: 10 }}>
                  <Tile label="P/L at expiry" value={plExp} testId="wz-pl-expiry" />
                  <Tile label="P/L today (model)" value={plToday} testId="wz-pl-today" none={!pre?.net ? "not available" : undefined} />
                </div>
              </>
            )}
        </Card>
      </div>

      <div className="flex min-w-0 flex-col" style={{ flex: "1 1 300px", gap: 14 }}>
        <Card testId="wz-summary" title="Strategy summary">
          <dl className="m-0 grid" style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: "7px 12px", fontSize: 12.5 }}>
            <Row k="Net option premium" id="premium" v={np == null ? "—" : `${np < 0 ? "Debit" : "Credit"} ${inr(Math.abs(np))}`} />
            <Row k="Cash leg capital" id="cash" v={hasCash ? inr(cashCap) : "—"} />
            <Row k="Max profit" id="maxprofit" v={e ? (e.profit_unbounded ? "Unlimited" : inr(e.max_profit)) : "—"} />
            <Row k="Max loss" id="maxloss" v={e ? (e.loss_unbounded ? "Unlimited" : inr(e.max_loss)) : "—"} />
            <Row k="Breakevens" id="be" v={e ? (e.breakevens.length ? e.breakevens.map((b) => fmtStrike(b)).join(" · ") : "none in range") : "—"} />
            <Row k="Probability of profit" id="pop" v={structure.pop ? `${Math.round(structure.pop.value * 100)}% (model)` : "not available"} title={structure.pop?.basis} />
            <Row k="Reward : risk" id="rr" v={rr != null ? `${rr.toFixed(2)} : 1` : "—"} />
            <Row k="Est. costs + slippage" id="costs" v={costs != null ? `${inr(costs)} round trip` : "—"} />
            <Row k="Margin / capital est." id="margin" v={
              structure.margin.kind === "ok" ? `${inr(structure.margin.required)} margin`
                : structure.margin.kind === "pending" ? "asking Kite…"
                : r?.valid && r.capital_at_risk != null ? `${inr(r.capital_at_risk)} capital at risk` : "—"} />
            <Row k="Legs · expiries" id="legs" v={`${legs.length} · ${exps.length ? exps.map(shortDay).join(", ") : "—"}`} />
          </dl>
          <span data-testid="wz-summary-notes" style={{ ...quietS, fontSize: 11 }}>
            Max profit and loss are at expiry before costs (payoff-v2, exact); the costs row is the desk cost card (statutory charges and slippage).
            {structure.margin.kind === "unavailable" ? ` Margin: ${/Kite/.test(structure.margin.reason) ? "Kite login needed. " : ""}${structure.margin.reason} The capital at risk is the payoff's worst net loss.` : structure.margin.kind === "ok" ? ` Margin from ${structure.margin.source ?? "Zerodha's margin calculator"}.` : ""}
            {structure.pop ? ` Probability of profit: ${structure.pop.basis}.` : " Probability of profit needs the chain's ATM IV and one expiry."}
          </span>
        </Card>

        <Card testId="wz-greeks" title="Net Greeks · now">
          {g ? (
            <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 10 }}>
              <Greek k="Delta" id="delta" v={`${g.delta != null && g.delta > 0 ? "+" : g.delta != null && g.delta < 0 ? "−" : ""}${g.delta != null ? new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Math.abs(g.delta)) : "—"} sh`} />
              <Greek k="Theta / day" id="theta" v={inr(g.theta, true)} />
              <Greek k="Vega / 1 vol pt" id="vega" v={inr(g.vega, true)} />
              <Greek k="IV assumption" id="iv" v={ivs.length ? (ivs.length === 1 || Math.max(...ivs) - Math.min(...ivs) < 0.05 ? `${ivs[0].toFixed(1)}% from the close` : `${Math.min(...ivs).toFixed(1)}–${Math.max(...ivs).toFixed(1)}% per leg`) : chain?.summary.atm_iv != null ? `ATM ${chain.summary.atm_iv.toFixed(1)}%` : "—"} />
            </div>
          ) : <span data-testid="wz-greeks-none" style={quietS}>Not available{pre?.unavailable?.length ? `: ${pre.unavailable[0].reason}` : r?.valid ? ": no option leg with time left (or the evaluation day is the expiry)." : " until the payoff is worked out."}</span>}
          <span style={{ ...quietS, fontSize: 11 }}>{pre?.model ?? "Black-76"} on the route, whole position at the spot; each leg's volatility is solved from its own close.</span>
        </Card>

        <ChecksCard structure={structure} asOf={asOf} age={age} stale={stale} />
        <Btn variant="primary" data-testid="wz-to-validate" onClick={onNext} disabled={!e}>Validate &amp; paper-trade →</Btn>
      </div>

      {picker && chain && (
        <ChainPicker symbol={symbol} expiry={picker.expiry} focus={picker.focus} legs={legs} onAdd={addFromChain} onClose={() => setPicker(null)} />
      )}
    </div>
  );
}

const miniBtn: CSSProperties = { width: 24, height: 24, borderRadius: 6, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink)", cursor: "pointer", fontSize: 13, lineHeight: 1 };

function Row({ k, v, id, title }: { k: string; v: ReactNode; id: string; title?: string }) {
  return (
    <>
      <dt style={{ color: "var(--cp-ink-3)" }}>{k}</dt>
      <dd className="m-0" data-testid={`wz-sum-${id}`} title={title} style={{ ...mono, textAlign: "right" }}>{v}</dd>
    </>
  );
}

function Greek({ k, v, id }: { k: string; v: string; id: string }) {
  return (
    <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <span style={{ ...eyebrowS, fontSize: 9.5 }}>{k}</span>
      <span data-testid={`wz-greek-${id}`} style={{ ...mono, fontSize: 15 }}>{v}</span>
    </span>
  );
}

function Tile({ label, value, testId, none }: { label: string; value: number | null; testId: string; none?: string }) {
  return (
    <div data-testid={testId} data-value={value == null ? "" : Math.round(value)} className="flex flex-col" style={{ gap: 4, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)" }}>
      <span style={{ ...eyebrowS, fontSize: 9.5 }}>{label}</span>
      <span style={{ ...mono, fontSize: 18, color: value == null ? "var(--cp-ink-3)" : value < 0 ? "var(--cp-danger)" : "var(--mint)" }}>{value == null ? none ?? "—" : inr(value, true)}</span>
    </div>
  );
}

/** The CHECKS card: the chain's age, your build limits, the payoff engine's problems, the risk service's decision. */
export function ChecksCard({ structure, asOf, age, stale, title = "Checks", testId = "wz-checks" }: { structure: Structure; asOf: string | null; age: number | null; stale: boolean; title?: string; testId?: string }) {
  const items: Array<{ tone: "ok" | "warn" | "bad"; text: ReactNode; id: string }> = [];
  if (asOf) items.push(stale || (age ?? 0) > 0
    ? { tone: "warn", id: "snapshot", text: `Chain snapshot is the NSE close of ${shortDay(asOf)} (${age === 1 ? "1 day" : `${age} days`} old). Premiums are end-of-day closes, not quotes.` }
    : { tone: "ok", id: "snapshot", text: `Chain snapshot is today's close (${shortDay(asOf)}).` });
  structure.limits.forEach((l, i) => items.push({ tone: l.ok ? "ok" : "bad", id: `limit-${i}`, text: l.text }));
  const r = structure.pay.data;
  if (r && !r.valid) r.problems.forEach((p, i) => items.push({ tone: "bad", id: `payoff-${i}`, text: p.message }));
  const c = structure.check;
  if (c.state?.kind === "answer") {
    const a = c.state.a;
    if (a.outcome === "allow") items.push({ tone: "ok", id: "risk", text: "Within your risk limits. Paper only, no broker order is created." });
    else if (a.outcome === "reduce") items.push({ tone: "warn", id: "risk", text: <>Reduced: the risk service allows {a.approvedLots ?? "?"} lot{a.approvedLots === 1 ? "" : "s"} per leg{a.requestedLots != null ? ` (you asked ${a.requestedLots})` : ""}.<Reasons rs={a.reasons} /></> });
    else items.push({ tone: "bad", id: "risk", text: <>Blocked by the risk service.<Reasons rs={a.reasons} /></> });
    if (a.duplicate) items.push({ tone: "warn", id: "dup", text: a.duplicate.message ?? `This structure is already open (paper trade ${a.duplicate.tradeId}).` });
  } else if (c.state?.kind === "refused") items.push({ tone: "bad", id: "risk", text: `Not accepted as a paper trade: ${c.state.message}` });
  else if (c.error) items.push({ tone: "warn", id: "risk", text: `The risk service did not answer: ${c.error}` });
  else if (c.pending) items.push({ tone: "warn", id: "risk", text: "Asking the risk service…" });
  else items.push({ tone: "warn", id: "risk", text: "The risk service is asked once the legs have prices." });
  const outcome = c.state?.kind === "answer" ? c.state.a.outcome : c.state?.kind === "refused" ? "refused" : "";
  return (
    <Card testId={testId} title={title}>
      <ul className="m-0 flex flex-col" data-outcome={outcome} data-testid={`${testId}-list`} style={{ gap: 8, padding: 0, listStyle: "none" }}>
        {items.map((it) => (
          <li key={it.id} data-testid={`${testId}-${it.id}`} data-tone={it.tone} className="flex" style={{ gap: 8, fontSize: 12.5, lineHeight: 1.5 }}>
            <span aria-hidden="true" style={{ color: it.tone === "ok" ? "var(--mint)" : it.tone === "warn" ? "var(--amber)" : "var(--cp-danger)", fontWeight: 700 }}>{it.tone === "ok" ? "✓" : it.tone === "warn" ? "⚠" : "✗"}</span>
            <span className="min-w-0" style={{ color: "var(--cp-ink-2)" }}>{it.text}</span>
          </li>
        ))}
      </ul>
      <span style={{ ...quietS, fontSize: 11 }}>The risk service decides with your profile (the only risk setting, on Risk Desk); this check records nothing and the paper-trade submission decides again.</span>
    </Card>
  );
}

function Reasons({ rs }: { rs: Array<{ message: string }> }) {
  if (!rs.length) return null;
  return <ul className="m-0" data-testid="wz-risk-reasons" style={{ paddingLeft: 16, marginTop: 4 }}>{rs.map((x, i) => <li key={i} data-testid="wz-risk-reason">{x.message}</li>)}</ul>;
}
