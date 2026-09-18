/**
 * Research → Paper. Built to the owner's design docs/Paper Trade Engine standalone (1).html (2026-09-18) and the PRD
 * "Ten-Percent Days — Paper Trade Simulation Engine v1": Today's portfolio · Trade path · Evaluation.
 *
 * Rules this screen keeps:
 *   · Only rendered for accounts with features.move_odds (the API answers 403 to everyone else; a 403 clears the screen).
 *   · Every stored number is shown as the engine stored it: frozen selections, official NSE opens, pre-registered levels,
 *     each exit mode. Sizing, custom baskets and other stop distances are what-ifs computed from the same stored path and
 *     are labelled as such — they never overwrite the record.
 *   · Forward and replay are separate samples and are never pooled. Replay is a retrospective walk-forward of 2025 and is
 *     labelled that way everywhere it appears; forward sessions frozen before the rules were registered are shown but
 *     marked "not counted".
 *   · EOD-1 is the headline read (pre-registered); the other exit modes are shown beside it, never picked after the fact.
 *   · The disclaimer sits above the numbers and never collapses. No NaN/undefined ever reaches the page: missing is "—".
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  MODES, fetchPaperEvaluation, fetchPaperLive, fetchPaperPortfolio, fetchPaperTrade,
  type EvaluationResult, type LiveResult, type PaperMode, type PaperPortfolio, type PaperPortfolioData, type PaperPosition,
  type PaperSample, type PaperUniverseRow, type PortfolioResult, type TradeResult, type PaperExit,
} from "@/services/adapters/paperTrades.adapter";
import { MODE_SESSION, clock, day, dayYear, inr, levels, modeResult, pct, price, prob, sizeBasket, type Path, type Sizing } from "./paperMath";
import "./moveOdds.css";
import "./paperTrades.css";

type View = "today" | "trade" | "eval";
type StopChoice = "prereg" | 3 | 5 | 8;
const LIVE_REFRESH_MS = 60_000;
const MODE_LABEL: Record<PaperMode, { label: string; rule: string }> = {
  "EOD-1": { label: "EOD-1", rule: "close of the entry day · headline" },
  "EOD-3": { label: "EOD-3", rule: "close of day 2" },
  "EOD-5": { label: "EOD-5", rule: "close of day 4" },
  FIXED: { label: "Fixed hold", rule: "close of day 5, no early exit" },
  TARGET_STOP: { label: "Target / stop", rule: "first level touched, else day 5 close" },
};
const BENCH_LABEL: Record<string, string> = {
  A_ALL: "A · every eligible stock", A_RANDOM5: "A · seeded random five", B_MATCHED: "B · matched five", C_MOVEMENT: "C · movement only, no direction",
  D_NIFTY50: "D · Nifty 50",
};
const SIZE_LABEL: Record<string, string> = { L: "Turnover rank 1–100", M: "Turnover rank 101–250", S: "Turnover rank 251+" };
const EXCLUSION_LABEL: Record<string, string> = {
  scored: "not scored", valid_ohlc: "no valid bar on the prediction date", fresh: "stale price", min_price: "close below ₹5",
  min_traded_value: "median traded value below ₹1 crore", ca_validated: "unexplained price jump in 20 sessions", atr_available: "under 15 bars for ATR",
};
const DAY_LABEL = ["Entry day", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5"];

function tone(x: number | null | undefined): string {
  return x == null || !isFinite(x) || Math.abs(x) < 5e-5 ? "" : x > 0 ? "pos" : "neg";
}

export default function PaperTradesScreen() {
  const [sample, setSample] = useState<PaperSample>("forward");
  const [portfolio, setPortfolio] = useState<PaperPortfolio>("P5-NEXT");
  const [date, setDate] = useState<string | null>(null);
  const [view, setView] = useState<View>("today");
  const [res, setRes] = useState<PortfolioResult | null>(null);
  const [reload, setReload] = useState(0);
  const [tradeId, setTradeId] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    setRes(null);
    fetchPaperPortfolio(sample, portfolio, date).then((r) => { if (live) setRes(r); });
    return () => { live = false; };
  }, [sample, portfolio, date, reload]);

  const data = res?.kind === "ok" ? res.data : null;
  useEffect(() => {
    if (!data) return;
    if (tradeId == null || !data.positions.some((p) => p.trade_id === tradeId)) {
      setTradeId((data.positions.find((p) => p.entry_price != null) ?? data.positions[0])?.trade_id ?? null);
    }
  }, [data, tradeId]);

  const pickSample = (s: PaperSample) => { setSample(s); setDate(null); };
  const pickPortfolio = (p: PaperPortfolio) => { setPortfolio(p); setDate(null); };
  const openTrade = (id: number) => { setTradeId(id); setView("trade"); };

  if (res?.kind === "no_access") {
    return (
      <div className="pt" data-testid="paper-screen">
        <div className="mo-state" data-testid="pt-state-no_access"><h3>Paper trades are not enabled for this account</h3>
          <p>This research page is limited to invited accounts.</p></div>
      </div>
    );
  }

  return (
    <div className="pt" data-testid="paper-screen">
      <div className="mo-titlerow">
        <div>
          <div className="pt-eyebrow">Ten-percent days · paper trade simulation engine v1</div>
          <h2 className="mo-title">Paper trades</h2>
          <p className="mo-sub">EOD predictions are frozen after the close, entered at the next session's official open, and tracked for five more sessions. No live execution.</p>
        </div>
        <div className="pt-chips">
          <span className="mo-chip"><span className="mo-dot" />Snapshot immutable</span>
          <span className="mo-chip">Paper only</span>
        </div>
      </div>

      <div className="mo-disc" data-testid="pt-disclaimer" role="note">
        <b>DISCLAIMER</b>Simulated paper trades for research. No orders are placed and no capital is at risk. This analysis is for informational
        purposes only and does not constitute investment advice. Past performance is not indicative of future results. Please consult a
        SEBI-registered investment advisor before making investment decisions.
      </div>

      <div className="pt-controls">
        <div className="pt-seg" role="group" aria-label="Sample">
          <button aria-pressed={sample === "forward"} onClick={() => pickSample("forward")} data-testid="pt-sample-forward">Forward</button>
          <button aria-pressed={sample === "replay"} onClick={() => pickSample("replay")} data-testid="pt-sample-replay">Replay · 2025</button>
        </div>
        <div className="pt-seg" role="group" aria-label="Portfolio">
          {(["P5-NEXT", "P10-NEXT"] as const).map((p) => (
            <button key={p} aria-pressed={portfolio === p} onClick={() => pickPortfolio(p)} data-testid={`pt-portfolio-${p}`}>{p}</button>
          ))}
        </div>
        {data && data.dates.length > 0 && (
          <label className="pt-small pt-datefield">
            Prediction date
            <select className="pt-select" value={data.prediction_date} onChange={(e) => setDate(e.target.value)} data-testid="pt-date">
              {data.dates.map((d) => (
                <option key={d.prediction_date} value={d.prediction_date}>
                  {dayYear(d.prediction_date)} → entry {day(d.entry_session)}{sample === "forward" && !d.counts ? " · not counted" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="mo-tabs" role="tablist">
        {([["today", "Today's portfolio", "frozen selection"], ["trade", "Trade path", "one position, six sessions"], ["eval", "Evaluation", "sample, benchmarks, costs"]] as const).map(([k, l, s]) => (
          <button key={k} role="tab" aria-selected={view === k} className="mo-tab" onClick={() => setView(k)} data-testid={`pt-view-${k}`}>
            <span className="mo-t1">{l}</span><span className="mo-t2">{s}</span>
          </button>
        ))}
      </div>

      {view === "eval" ? (
        <EvalView sample={sample} portfolio={portfolio} />
      ) : res == null ? (
        <div className="mo-tablewrap" data-testid="pt-loading">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="mo-skelrow"><div className="mo-skel" /><div className="mo-skel" /><div className="mo-skel" /></div>)}</div>
      ) : res.kind === "empty" ? (
        <div className="mo-state" data-testid="pt-state-empty"><h3>Nothing recorded yet</h3>
          <p>No {sample} {portfolio} snapshot has been frozen. The engine records each session after the close.</p></div>
      ) : res.kind === "not_found" || res.kind === "error" ? (
        <div className="mo-state" data-testid="pt-state-error"><h3>Could not load the paper portfolio</h3>
          <p>{res.kind === "error" ? res.message : "That session is not recorded."} Nothing older is shown in its place.</p>
          <div><button className="mo-btn" onClick={() => setReload((x) => x + 1)}>Retry</button></div></div>
      ) : data ? (
        <>
          <Provenance data={data} />
          {view === "today" ? <TodayView key={`${data.sample}|${data.portfolio}|${data.prediction_date}`} data={data} onOpen={openTrade} />
                            : <TradeView data={data} tradeId={tradeId} onPick={setTradeId} />}
        </>
      ) : null}
    </div>
  );
}

function Provenance({ data }: { data: PaperPortfolioData }) {
  const p = data.provenance;
  const counts = p.counts_toward_evaluation;
  return (
    <>
      <div className="mo-prov" data-testid="pt-provenance">
        <span>Prediction <b>{day(data.prediction_date)}</b> · frozen <b>{clock(p.prediction_timestamp)}</b></span>
        <span>Entry session <b>{day(p.next_trading_session)}</b> · official open</span>
        <span>Model <b>{p.model_version}</b> · features <b>{p.feature_version}</b></span>
        <span>Rules <b>{p.rules?.rules_id ?? p.rules_id}</b>{p.rules ? <> · <b>{p.rules.git_sha}</b></> : null}</span>
      </div>
      {data.sample === "replay" ? (
        <div className="pt-banner" data-testid="pt-replay-banner">Replay · a retrospective walk-forward of Jan–Aug 2025: each session used only data up to its
          prediction date, but the whole run was produced in 2026. It is evaluated separately from the forward record and never pooled with it.</div>
      ) : !counts ? (
        <div className="pt-banner" data-testid="pt-notcounted-banner">Recorded, not counted: this snapshot was frozen before the paper rules were registered
          ({p.rules ? `${day(p.rules.registered_at)} ${clock(p.rules.registered_at)}` : "registration"}), so it is kept for the record but excluded from the forward evaluation.</div>
      ) : null}
    </>
  );
}

// ── Today's portfolio ────────────────────────────────────────────────────────────────────────────────────────────
interface Leg {
  symbol: string; rank: number; name: string | null; sector: string | null; sizeGroup: string | null; pHead: number; pOther: number | null;
  status: string; reason: string | null; flags: string[]; entry: number | null; refPrice: number | null; atr: number | null; support: number | null;
  stored: { stop: number; target: number; method: string } | null; path: Path; exits: Record<string, PaperExit | null> | null; tradeId: number | null;
}

function pathFromPosition(p: PaperPosition): Path {
  const o = p.observations;
  return { open: o.map((x) => x.open_return), high: o.map((x) => x.high_return), low: o.map((x) => x.low_return), close: o.map((x) => x.return_from_entry),
           observed: p.entry_price != null ? o.length : 0 };
}

function legFromPosition(p: PaperPosition, cfg: PaperPortfolioData["config"]): Leg {
  const target = cfg.target_pct === 5 ? p.target_1_price : p.target_2_price;
  return {
    symbol: p.symbol, rank: p.rank ?? 0, name: p.company_name, sector: p.sector, sizeGroup: p.size_group, pHead: p.movement_probability,
    pOther: p.p_other_threshold, status: p.status, reason: p.status_reason, flags: p.flags, entry: p.entry_price,
    refPrice: p.entry_price ?? p.prediction_close, atr: p.atr_14, support: p.support_level,
    stored: p.stop_loss_price != null && target != null ? { stop: p.stop_loss_price, target, method: p.stop_method ?? "ATR" } : null,
    path: pathFromPosition(p), exits: p.exits, tradeId: p.trade_id,
  };
}

function legFromUniverse(u: PaperUniverseRow): Leg {
  const obs = u.sessions_observed ?? 0;
  return {
    symbol: u.symbol, rank: u.rank, name: u.company_name, sector: u.sector, sizeGroup: u.size_group, pHead: u.movement_probability, pOther: u.p_other_threshold,
    status: u.entry_status ?? "PENDING_ENTRY", reason: u.entry_reason, flags: u.flags ?? [], entry: u.entry_price, refPrice: u.entry_price ?? u.prediction_close,
    atr: u.atr_14, support: null,
    stored: u.stop_loss_price != null && u.target_price != null ? { stop: u.stop_loss_price, target: u.target_price, method: u.stop_method ?? "ATR" } : null,
    path: { open: u.r_open ?? [], high: u.r_high ?? [], low: u.r_low ?? [], close: u.r_close ?? [], observed: u.entry_price != null ? obs : 0 }, exits: null, tradeId: null,
  };
}

function TodayView({ data, onOpen }: { data: PaperPortfolioData; onOpen: (id: number) => void }) {
  const cfg = data.config;
  const target = cfg.target_pct;
  const [basket, setBasket] = useState<"model" | "custom">("model");
  const [chosen, setChosen] = useState<string[]>([]);
  const [picker, setPicker] = useState(false);
  const [capital, setCapital] = useState<number>(cfg.capital_inr);
  const [sizing, setSizing] = useState<Sizing>("equal");
  const [cap] = useState(25);
  const [dayLimit, setDayLimit] = useState(5);
  const [stop, setStop] = useState<StopChoice>("prereg");
  const [mode, setMode] = useState<PaperMode>("EOD-1");
  const isLatestForward = data.sample === "forward" && data.dates[0]?.prediction_date === data.prediction_date;

  const byPos = useMemo(() => new Map(data.positions.map((p) => [p.symbol, legFromPosition(p, cfg)])), [data, cfg]);
  const legs: Leg[] = useMemo(() => {
    if (basket === "model") return data.positions.map((p) => byPos.get(p.symbol) as Leg);
    return data.universe.filter((u) => chosen.includes(u.symbol)).map((u) => byPos.get(u.symbol) ?? legFromUniverse(u)).sort((a, b) => a.rank - b.rank);
  }, [basket, chosen, data, byPos]);

  // indicative levels for a pending entry assume it opens at the prediction-day close; they are labelled that way
  const lv = useCallback((l: Leg) => {
    if (l.stored && l.entry != null) return { ...l.stored, riskPct: (l.entry - l.stored.stop) / l.entry, indicative: false };
    const x = levels(l.entry ?? l.refPrice, l.atr, l.support, cfg.atr_multiplier, target);
    return x ? { stop: x.stop, target: x.target, method: x.method, riskPct: x.riskPct, indicative: l.entry == null } : null;
  }, [cfg.atr_multiplier, target]);
  const stopDist = useCallback((l: Leg) => (stop === "prereg" ? lv(l)?.riskPct ?? null : stop / 100), [stop, lv]);

  const sized = useMemo(() => sizeBasket(legs.map((l) => ({ symbol: l.symbol, atrPct: l.atr != null && l.refPrice ? l.atr / l.refPrice : null, stopDist: stopDist(l) })),
                                         sizing, cap, dayLimit), [legs, sizing, cap, dayLimit, stopDist]);

  const [live, setLive] = useState<LiveResult | null>(null);
  useEffect(() => {
    if (!isLatestForward) { setLive(null); return; }
    let on = true;
    const load = () => fetchPaperLive(data.portfolio).then((r) => { if (on) setLive(r); });
    load();
    const t = window.setInterval(() => { if (document.visibilityState === "visible") load(); }, LIVE_REFRESH_MS);
    return () => { on = false; window.clearInterval(t); };
  }, [isLatestForward, data.portfolio, data.prediction_date]);
  const liveBy = useMemo(() => new Map(live?.kind === "ok" ? live.data.positions.map((p) => [p.symbol, p]) : []), [live]);

  const rows = legs.map((l) => {
    const L = lv(l);
    const sd = stopDist(l);
    const w = sized.w[l.symbol] ?? 0;
    const alloc = capital * w;
    const px = l.entry ?? l.refPrice;
    const units = px ? Math.floor(alloc / px) : 0;
    const value = units * (px ?? 0);
    const fromRecord = stop === "prereg" && l.exits != null;
    let r: { state: string; net: number | null; gross: number | null; mark: number | null; reason: string | null };
    if (l.entry == null) r = { state: "NONE", net: null, gross: null, mark: null, reason: null };
    else if (fromRecord) {
      const e = l.exits?.[mode] ?? null;
      const last = l.path.observed ? l.path.close[l.path.observed - 1] ?? null : null;
      r = { state: e?.state ?? "OPEN", net: e?.net_return ?? null, gross: e?.gross_return ?? null, mark: last == null ? null : last - cfg.cost_pct / 100, reason: e?.exit_reason ?? null };
    } else {
      const stopRet = stop === "prereg" ? (L ? L.stop / (l.entry as number) - 1 : -0.08) : -(stop / 100);
      r = modeResult(l.path, mode, stopRet, target / 100, cfg.cost_pct);
    }
    const shown = r.state === "CLOSED" ? r.net : r.mark;
    const obs = l.path.observed;
    const mfe = obs ? Math.max(...l.path.high.slice(0, obs).map((x) => x ?? -Infinity)) : null;
    const mae = obs ? Math.min(...l.path.low.slice(0, obs).map((x) => x ?? Infinity)) : null;
    return { l, L, sd, w, alloc, units, value, risk: sd != null ? value * sd : null, r, shown, pnl: l.entry != null && shown != null ? value * shown : null,
             mfe: mfe != null && isFinite(mfe) ? mfe : null, mae: mae != null && isFinite(mae) ? mae : null, fromRecord };
  });
  const entered = rows.filter((x) => x.l.entry != null);
  const deployed = entered.reduce((a, x) => a + x.value, 0);
  const indicativeDeployed = rows.filter((x) => x.l.entry == null && x.l.status === "PENDING_ENTRY").reduce((a, x) => a + x.value, 0);
  const pnl = entered.reduce((a, x) => a + (x.pnl ?? 0), 0);
  const atRisk = rows.reduce((a, x) => a + (x.risk ?? 0), 0);
  const allPending = entered.length === 0;
  const sectors = useMemo(() => {
    const m = new Map<string, number>();
    legs.forEach((l) => m.set(l.sector ?? "Unclassified", (m.get(l.sector ?? "Unclassified") ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [legs]);
  const groups = useMemo(() => {
    const m = new Map<string, number>();
    legs.forEach((l) => { if (l.sizeGroup) m.set(l.sizeGroup, (m.get(l.sizeGroup) ?? 0) + 1); });
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [legs]);

  return (
    <div className="pt-grid">
      <div className="pt-main">
        <div className="pt-controls">
          <div className="pt-seg" role="group" aria-label="Basket">
            <button aria-pressed={basket === "model"} onClick={() => setBasket("model")} data-testid="pt-basket-model">Model top 5</button>
            <button aria-pressed={basket === "custom"} onClick={() => { setBasket("custom"); setPicker(true); }} data-testid="pt-basket-custom">Custom basket</button>
          </div>
          {basket === "custom" && (
            <button className="mo-btn" onClick={() => setPicker(!picker)} data-testid="pt-picker-toggle">Choose stocks · {chosen.length} picked {picker ? "▴" : "▾"}</button>
          )}
          <span className="pt-small">Costs {cfg.cost_pct}% round trip · {stop === "prereg" ? "pre-registered levels" : `what-if stop ${stop}%`}</span>
        </div>

        {basket === "custom" && picker && (
          <div className="pt-picker" data-testid="pt-picker">
            <div className="pt-controls" style={{ justifyContent: "space-between", padding: "2px 4px 6px" }}>
              <span className="pt-small">Stored ranked universe · top {data.universe.length} of {data.provenance.eligible}</span>
              <span style={{ display: "inline-flex", gap: 6 }}>
                <button className="mo-btn" onClick={() => setChosen(data.positions.map((p) => p.symbol))}>Start from model top 5</button>
                <button className="mo-btn" onClick={() => setChosen([])}>Clear</button>
              </span>
            </div>
            {data.universe.map((u) => {
              const on = chosen.includes(u.symbol);
              return (
                <button key={u.symbol} className="pt-pick" aria-pressed={on} data-testid={`pt-pick-${u.symbol}`}
                        onClick={() => setChosen((c) => (c.includes(u.symbol) ? c.filter((x) => x !== u.symbol) : [...c, u.symbol]))}>
                  <span className="pt-box">{on ? "✓" : ""}</span>
                  <span className="pt-mono muted">#{u.rank}</span>
                  <span style={{ minWidth: 0 }}><span className="mo-sym">{u.symbol}</span><span className="mo-co">{u.company_name ?? "—"}{u.selection_status === "SELECTED" ? " · in model top 5" : ""}</span></span>
                  <span className="pt-mono" style={{ textAlign: "right" }}>{prob(u.movement_probability)}</span>
                </button>
              );
            })}
            <div className="pt-note" style={{ padding: "6px 4px 2px" }}>Any number of legs · entry stays the next session's official open · a custom basket is a what-if, not the engine's record.</div>
          </div>
        )}

        <div className="mo-panel pt-sizing" data-testid="pt-sizing">
          <div className="pt-field">
            <label htmlFor="pt-capital">Capital to deploy</label>
            <input id="pt-capital" className="pt-input" inputMode="numeric" value={capital.toLocaleString("en-IN")} data-testid="pt-capital"
                   onChange={(e) => { const v = parseInt(e.target.value.replace(/[^\d]/g, ""), 10); setCapital(isNaN(v) ? 0 : v); }} />
            <div className="pt-chips">
              {[100000, 250000, 500000, 1000000].map((c) => (
                <button key={c} className="pt-chipbtn" aria-pressed={capital === c} onClick={() => setCapital(c)} data-testid={`pt-capital-${c}`}>₹{c / 100000}L</button>
              ))}
            </div>
            <span className="pt-hint">The engine's record uses ₹{cfg.capital_inr.toLocaleString("en-IN")}, {100 / cfg.positions}% per position. Everything here is a what-if.</span>
          </div>
          <div className="pt-field">
            <span className="pt-flabel">Allocation rule</span>
            <div className="pt-cards">
              {([["equal", "Equal notional", "same rupees per leg"], ["risk", "Risk weighted", "inverse ATR"], ["capped", "Capped", `equal, no leg above ${cap}%`]] as const).map(([k, l, r]) => (
                <button key={k} className="pt-card-btn" aria-pressed={sizing === k} onClick={() => setSizing(k)} data-testid={`pt-sizing-${k}`}><span>{l}</span><small>{r}</small></button>
              ))}
            </div>
          </div>
          <div className="pt-field">
            <span className="pt-flabel">Most you accept losing if every stop fills</span>
            <div className="pt-chips">
              {[2, 3, 5, 8].map((v) => (
                <button key={v} className="pt-chipbtn amber" aria-pressed={dayLimit === v} onClick={() => setDayLimit(v)} data-testid={`pt-limit-${v}`}>{v}% · {inr(capital * v / 100)}</button>
              ))}
            </div>
            <span className="pt-hint" data-testid="pt-binding">{sized.binding
              ? `This limit binds: each leg is held to the notional that loses ${inr(capital * sized.legBudget)} at its stop; the rest stays in cash.`
              : `Sizing is set by the allocation rule; each leg risks at most ${inr(capital * sized.legBudget)} at its stop.`}</span>
          </div>
          <div className="pt-field">
            <span className="pt-flabel">Stop distance</span>
            <div className="pt-chips">
              <button className="pt-chipbtn danger" aria-pressed={stop === "prereg"} onClick={() => setStop("prereg")} data-testid="pt-stop-prereg">Pre-registered · {cfg.atr_multiplier}× ATR, max 8%</button>
              {([3, 5, 8] as const).map((v) => (
                <button key={v} className="pt-chipbtn danger" aria-pressed={stop === v} onClick={() => setStop(v)} data-testid={`pt-stop-${v}`}>{v}%</button>
              ))}
            </div>
            <span className="pt-hint">Target +{target}% from entry. Levels are fixed before the session and never moved after entry.</span>
          </div>
        </div>

        <div className="pt-stats" data-testid="pt-summary">
          <div className="pt-stat"><span className="pt-stat-l">Capital</span><span className="pt-stat-v">{inr(capital)}</span><span className="pt-stat-s">no leverage</span></div>
          <div className="pt-stat"><span className="pt-stat-l">Deployed</span><span className="pt-stat-v" data-testid="pt-deployed">{inr(allPending ? indicativeDeployed : deployed)}</span>
            <span className="pt-stat-s">{allPending ? "indicative, at the last close" : `${entered.length} legs · whole units`}</span></div>
          <div className="pt-stat"><span className="pt-stat-l">Idle</span><span className="pt-stat-v">{inr(capital - (allPending ? indicativeDeployed : deployed))}</span><span className="pt-stat-s">rounding, limit and no-fills</span></div>
          <div className="pt-stat"><span className="pt-stat-l">At risk</span><span className="pt-stat-v warn" data-testid="pt-atrisk">{inr(atRisk)}</span><span className="pt-stat-s">if every stop fills</span></div>
          <div className="pt-stat"><span className="pt-stat-l">P&amp;L · {MODE_LABEL[mode].label}</span>
            <span className={`pt-stat-v ${allPending ? "" : tone(pnl)}`} data-testid="pt-pnl">{allPending ? "—" : inr(pnl, true)}</span>
            <span className="pt-stat-s">{allPending ? "entry at the next official open" : "after costs · open legs at their last close"}</span></div>
        </div>

        <div className="pt-controls">
          <span className="pt-small">Return shown</span>
          <div className="pt-seg" role="group" aria-label="Exit mode">
            {MODES.map((m) => <button key={m} aria-pressed={mode === m} onClick={() => setMode(m)} data-testid={`pt-mode-${m}`}>{MODE_LABEL[m].label}</button>)}
          </div>
          <span className="pt-small">{MODE_LABEL[mode].rule}</span>
        </div>

        <div className="mo-tablewrap" tabIndex={0}>
          <table className="mo-table pt-table" data-testid="pt-table" style={{ minWidth: 980 }}>
            <caption>{basket === "model" ? `Model top ${data.positions.length} · ${data.portfolio} · as frozen` : `Custom basket · ${legs.length} legs · what-if`}</caption>
            <thead><tr>
              <th scope="col">Rk</th><th scope="col">Stock</th><th scope="col">P(+5%)</th><th scope="col">P(+10%)</th><th scope="col">Allocation</th>
              <th scope="col">Entry · target · stop</th><th scope="col">Return</th><th scope="col">MFE</th><th scope="col">MAE</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Open</span></th>
            </tr></thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={11} className="mo-empty" data-testid="pt-empty-basket">No stocks picked. Open the picker and select any stocks from the stored ranked universe.</td></tr>}
              {rows.map(({ l, L, w, alloc, units, value, risk, r, shown, pnl: legPnl, mfe, mae, fromRecord }) => {
                const lv5 = target === 5 ? l.pHead : l.pOther;
                const lv10 = target === 10 ? l.pHead : l.pOther;
                const lvl = live?.kind === "ok" ? liveBy.get(l.symbol) : undefined;
                return (
                  <tr key={l.symbol} data-testid={`pt-row-${l.symbol}`}>
                    <td className="pt-mono">{l.rank}</td>
                    <th scope="row"><span className="mo-sym">{l.symbol}</span><span className="mo-co">{l.name ?? "—"}</span><span className="pt-small">{l.sector ?? "—"}</span></th>
                    <td className={`pt-mono ${target === 5 ? "" : "muted"}`}>{prob(lv5)}</td>
                    <td className={`pt-mono ${target === 10 ? "" : "muted"}`}>{prob(lv10)}</td>
                    <td><div className="pt-levels"><b data-testid={`pt-alloc-${l.symbol}`}>{inr(alloc)}</b><span>{(w * 100).toFixed(1)}% · {units.toLocaleString("en-IN")} units</span>
                      <span>risk {risk != null ? inr(-risk) : "—"}{l.entry == null && value > 0 ? " · indicative" : ""}</span></div></td>
                    <td><div className="pt-levels">
                      <b data-testid={`pt-entry-${l.symbol}`}>{l.entry != null ? price(l.entry) : l.status === "PENDING_ENTRY" ? `open of ${day(data.provenance.next_trading_session)}` : "no fill"}</b>
                      {L && stop === "prereg" ? <>
                        <span>target {price(L.target)} · stop {price(L.stop)}</span>
                        <span>{L.method === "CAP_8PCT" ? "stop capped at 8%" : L.method === "SUPPORT" ? "stop at 10-day support" : `stop ${cfg.atr_multiplier}× ATR`}{L.indicative ? ` · indicative at close ${price(l.refPrice)}` : ""}</span>
                      </> : l.entry != null ? <span>target {price(l.entry * (1 + target / 100))} · stop {price(l.entry * (1 - (stop as number) / 100))}</span>
                        : <span>last close {price(l.refPrice)}</span>}
                    </div></td>
                    <td data-testid={`pt-ret-${l.symbol}`}>{l.entry == null ? <span className="muted">—</span> : <div className="pt-levels">
                      <b className={tone(shown)}>{pct(shown)}</b>
                      <span>{r.state === "CLOSED" ? `closed · gross ${pct(r.gross)}` : r.state === "NO_BAR" ? "no bar at exit" : `open · mark ${legPnl != null ? inr(legPnl, true) : "—"}`}</span>
                      <span>{fromRecord ? "record" : "what-if"}{r.state === "CLOSED" && legPnl != null ? ` · ${inr(legPnl, true)}` : ""}</span></div>}</td>
                    <td className={`pt-mono ${tone(mfe)}`}>{pct(mfe)}</td>
                    <td className={`pt-mono ${tone(mae)}`}>{pct(mae)}</td>
                    <td>{lvl ? <span className={`pt-pill ${lvl.state === "target" || lvl.state === "exited_target" ? "mint" : lvl.state === "stop" || lvl.state === "exited_stop" ? "danger" : lvl.state === "holding" ? "indigo" : "amber"}`}
                                     title={lvl.note} data-testid={`pt-live-${l.symbol}`}>{lvl.label}</span>
                      : <StatusPill l={l} />}</td>
                    <td>{l.tradeId != null ? <button className="pt-rowbtn" onClick={() => onOpen(l.tradeId as number)} aria-label={`Open the trade path of ${l.symbol}`} data-testid={`pt-open-${l.symbol}`}>›</button> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="pt-note">Return is net of {cfg.cost_pct}% round-trip costs, from the official entry. "Record" is the engine's stored exit; "what-if" is computed from
          the same stored daily path. MFE and MAE are the best and worst intraday moves from entry so far.</p>
      </div>

      <aside className="pt-side">
        {isLatestForward && <LivePanel live={live} />}
        <div className="mo-panel" data-testid="pt-exceptions">
          <h3>Exceptions this session</h3>
          {data.exceptions.length === 0 && Object.keys(data.provenance.excluded).length === 0 ? <p>None recorded.</p> : (
            <ul className="pt-list">
              {data.exceptions.map((e) => (
                <li key={e.symbol}><span className="pt-mono">{e.symbol}</span><span>{[e.status !== "ENTERED" && e.status !== "EVALUATED" && e.status !== "MONITORING" ? (e.reason ?? e.status).replace(/_/g, " ").toLowerCase() : null,
                  ...e.flags.map((f) => f.replace(/_/g, " ").toLowerCase())].filter(Boolean).join(" · ")}</span></li>
              ))}
              {Object.entries(data.provenance.excluded).map(([k, v]) => (
                <li key={k}><span>{EXCLUSION_LABEL[k] ?? k}</span><span className="pt-mono">{v} excluded</span></li>
              ))}
            </ul>
          )}
        </div>
        <div className="mo-panel" data-testid="pt-concentration">
          <h3>Concentration</h3>
          <ul className="pt-list">
            {sectors.map(([k, v]) => (
              <li key={k} style={{ display: "grid", gap: 4 }}><span style={{ display: "flex", justifyContent: "space-between" }}><span>{k}</span>
                <span className="pt-mono">{v} of {legs.length} · {Math.round((v / Math.max(1, legs.length)) * 100)}%</span></span>
                <span className="pt-bar"><span style={{ width: `${(v / Math.max(1, legs.length)) * 100}%` }} /></span></li>
            ))}
            {groups.map(([k, v]) => <li key={k}><span>{SIZE_LABEL[k] ?? k}</span><span className="pt-mono">{v} of {legs.length}</span></li>)}
          </ul>
          <p className="pt-note">No sector cap in v1. Sector is today's classification, not the one on the prediction date.</p>
        </div>
        <div className="mo-panel" data-testid="pt-snapshot">
          <h3>Snapshot provenance</h3>
          <dl className="pt-kv">
            <dt>data cutoff</dt><dd>{day(data.provenance.data_cutoff_timestamp)} {clock(data.provenance.data_cutoff_timestamp)}</dd>
            <dt>frozen</dt><dd>{day(data.provenance.prediction_timestamp)} {clock(data.provenance.prediction_timestamp)}</dd>
            <dt>universe scored</dt><dd>{data.provenance.scored}</dd>
            <dt>eligible, ranked</dt><dd>{data.provenance.eligible}</dd>
            <dt>model</dt><dd>{data.provenance.model_version}</dd>
            <dt>features</dt><dd>{data.provenance.feature_version}</dd>
            <dt>snapshot sha256</dt><dd>{data.provenance.snapshot_sha256.slice(0, 16)}…</dd>
            <dt>rules</dt><dd>{data.provenance.rules ? `${data.provenance.rules.rules_id} · ${data.provenance.rules.rules_sha256.slice(0, 12)}…` : data.provenance.rules_id}</dd>
            <dt>counts</dt><dd>{data.sample === "replay" ? "replay sample" : data.provenance.counts_toward_evaluation ? "yes, forward" : "no (before registration)"}</dd>
          </dl>
          <p className="pt-note">Rankings are not recalculated after the cutoff. A correction would be a new version; the original stays.</p>
        </div>
      </aside>
    </div>
  );
}

function StatusPill({ l }: { l: Leg }) {
  const map: Record<string, [string, string]> = {
    PENDING_ENTRY: ["pending entry", "amber"], ENTERED: ["day 1 · entered", "mint"], MONITORING: [`day ${Math.max(1, l.path.observed - 1)} · monitoring`, "mint"],
    EVALUATED: ["evaluated", "indigo"], ENTRY_UNAVAILABLE: ["no entry", "amber"], SUSPENDED: ["suspended", "amber"], DATA_ERROR: ["data error", "danger"],
    CORPORATE_ACTION_REVIEW: ["corporate action review", "amber"], CANCELLED_BY_RULE: ["cancelled", "amber"],
  };
  const [label, t] = map[l.status] ?? [l.status.toLowerCase(), ""];
  return <span className={`pt-pill ${t}`} title={l.reason ?? undefined}>{label}</span>;
}

function LivePanel({ live }: { live: LiveResult | null }) {
  return (
    <div className="mo-panel" data-testid="pt-live">
      <h3>Live · target / stop experiment</h3>
      {live == null ? <p>Loading live prices…</p> : live.kind === "no_access" ? <p>Not enabled.</p> : live.kind === "empty" ? <p>No forward selection yet.</p>
        : live.kind !== "ok" ? <p data-testid="pt-live-error">Live prices unavailable right now. Official values arrive after tonight's run.</p> : (
        <>
          <div className="pt-stats" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
            <div className="pt-stat"><span className="pt-stat-l">Hold</span><span className="pt-stat-v">{live.data.counts.holding}</span></div>
            <div className="pt-stat"><span className="pt-stat-l">Exit · target</span><span className="pt-stat-v pos">{live.data.counts.target}</span></div>
            <div className="pt-stat"><span className="pt-stat-l">Exit · stop</span><span className="pt-stat-v neg">{live.data.counts.stop}</span></div>
            <div className="pt-stat"><span className="pt-stat-l">Await entry</span><span className="pt-stat-v warn">{live.data.counts.awaiting}</span></div>
          </div>
          <ul className="pt-list">
            {live.data.positions.map((p) => (
              <li key={p.symbol} data-testid={`pt-live-row-${p.symbol}`}><span><span className="pt-mono">{p.symbol}</span> <span className="pt-small">{p.note}</span></span>
                <span className="pt-mono">{p.last != null ? `${price(p.last)} · ${pct(p.return_from_entry)}` : "—"}</span></li>
            ))}
          </ul>
          <p className="pt-note">{live.data.source}, {live.data.delay_note} · as of {clock(live.data.fetched_at)}.
            {live.data.positions.some((p) => p.provisional) ? " Entry is the first 5-minute bar's open until the official open is recorded tonight; levels on it are provisional." : ""} {live.data.official_note}</p>
        </>
      )}
    </div>
  );
}

// ── Trade path ──────────────────────────────────────────────────────────────────────────────────────────────────
function TradeView({ data, tradeId, onPick }: { data: PaperPortfolioData; tradeId: number | null; onPick: (id: number) => void }) {
  const [res, setRes] = useState<TradeResult | null>(null);
  useEffect(() => {
    if (tradeId == null) return;
    let on = true;
    setRes(null);
    fetchPaperTrade(tradeId).then((r) => { if (on) setRes(r); });
    return () => { on = false; };
  }, [tradeId]);
  const cfg = data.config;
  const t = res?.kind === "ok" ? res.data : null;
  const target = t ? (cfg.target_pct === 5 ? t.target_1_price : t.target_2_price) : null;
  const headline = t?.exits["EOD-1"] ?? null;
  const ts = t?.exits["TARGET_STOP"] ?? null;
  return (
    <div className="pt-main" data-testid="pt-trade">
      <div className="pt-controls">
        <span className="pt-small">Position</span>
        <div className="pt-seg" role="group" aria-label="Position">
          {data.positions.map((p) => <button key={p.trade_id} aria-pressed={p.trade_id === tradeId} onClick={() => onPick(p.trade_id)} data-testid={`pt-trade-pick-${p.symbol}`}>{p.symbol}</button>)}
        </div>
      </div>
      {res == null ? <div className="mo-tablewrap"><div className="mo-skelrow"><div className="mo-skel" /><div className="mo-skel" /><div className="mo-skel" /></div></div>
        : res.kind !== "ok" ? <div className="mo-state" data-testid="pt-trade-error"><h3>Could not load this trade</h3><p>{res.kind === "error" ? res.message : "Not found."}</p></div>
        : t && (
        <>
          <div className="pt-trade-head">
            <h3 data-testid="pt-trade-symbol">{t.symbol}</h3>
            <StatusPill l={{ ...legFromPosition(t, cfg) }} />
            <span className="pt-pill">{t.portfolio_type}</span>
            <span className="pt-small">{t.company_name ?? "—"} · predicted {day(t.prediction_date)} · {t.entry_price != null ? `entered ${day(t.entry_date)} at the official open ${price(t.entry_price)}` : `enters at the official open of ${day(t.intended_entry_date)}`}</span>
          </div>
          <div className="pt-stats" data-testid="pt-trade-stats">
            <div className="pt-stat"><span className="pt-stat-l">Net · EOD-1 (headline)</span>
              <span className={`pt-stat-v ${tone(headline?.net_return)}`}>{headline?.state === "CLOSED" ? pct(headline.net_return) : "open"}</span>
              <span className="pt-stat-s">{headline?.state === "CLOSED" ? `gross ${pct(headline.gross_return)}` : "after the entry-day close"}</span></div>
            <div className="pt-stat"><span className="pt-stat-l">MFE</span><span className={`pt-stat-v ${tone(t.observations.at(-1)?.mfe_to_date)}`}>{pct(t.observations.at(-1)?.mfe_to_date)}</span><span className="pt-stat-s">best intraday from entry</span></div>
            <div className="pt-stat"><span className="pt-stat-l">MAE</span><span className={`pt-stat-v ${tone(t.observations.at(-1)?.mae_to_date)}`}>{pct(t.observations.at(-1)?.mae_to_date)}</span><span className="pt-stat-s">worst intraday from entry</span></div>
            <div className="pt-stat"><span className="pt-stat-l">Target / stop</span><span className="pt-stat-v">{ts?.state === "CLOSED" ? (ts.exit_reason ?? "closed") : "open"}</span>
              <span className="pt-stat-s">{ts?.state === "CLOSED" ? `${pct(ts.net_return)} net · ${ts.exit_date ? day(ts.exit_date) : ""}` : "neither level recorded yet"}</span></div>
            <div className="pt-stat"><span className="pt-stat-l">Levels</span><span className="pt-stat-v" style={{ fontSize: 13 }}>{target != null ? `${price(target)} / ${price(t.stop_loss_price)}` : "—"}</span>
              <span className="pt-stat-s">{t.stop_method ? `${t.stop_method === "CAP_8PCT" ? "stop capped at 8%" : t.stop_method === "SUPPORT" ? "stop at support" : `${cfg.atr_multiplier}× ATR14`} · R:R ${t.risk_reward_ratio != null ? t.risk_reward_ratio.toFixed(2) : "—"}` : "set at entry"}</span></div>
          </div>

          <div className="mo-tablewrap" tabIndex={0}>
            <table className="mo-table pt-table" data-testid="pt-path" style={{ minWidth: 760 }}>
              <caption>Path from entry · returns on the entry basis (corporate actions adjusted)</caption>
              <thead><tr><th scope="col">Session</th><th scope="col">Date</th><th scope="col">Open</th><th scope="col">High</th><th scope="col">Low</th><th scope="col">Close</th>
                <th scope="col">Return</th><th scope="col">MFE</th><th scope="col">MAE</th><th scope="col">Levels</th></tr></thead>
              <tbody>
                {t.observations.length === 0 && <tr><td colSpan={10} className="mo-empty">No sessions recorded yet.</td></tr>}
                {t.observations.map((o) => (
                  <tr key={o.session_date} data-testid={`pt-path-${o.days_held}`}>
                    <th scope="row">{DAY_LABEL[o.days_held] ?? `Day ${o.days_held}`}</th><td>{day(o.session_date)}</td>
                    <td className="pt-mono">{price(o.open_price)}</td><td className="pt-mono">{price(o.high_price)}</td><td className="pt-mono">{price(o.low_price)}</td><td className="pt-mono">{price(o.close_price)}</td>
                    <td className={`pt-mono ${tone(o.return_from_entry)}`}>{pct(o.return_from_entry)}</td>
                    <td className={`pt-mono ${tone(o.mfe_to_date)}`}>{pct(o.mfe_to_date)}</td><td className={`pt-mono ${tone(o.mae_to_date)}`}>{pct(o.mae_to_date)}</td>
                    <td>{o.stop_hit ? <span className="pt-pill danger">stop touched</span> : o.target_hit ? <span className="pt-pill mint">target touched</span> : <span className="muted">—</span>}
                      {o.adjustment_factor != null && Math.abs(o.adjustment_factor - 1) > 1e-9 ? <span className="pt-pill amber" style={{ marginLeft: 6 }}>adjusted ×{o.adjustment_factor.toFixed(3)}</span> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pt-grid">
            <div className="mo-tablewrap" tabIndex={0}>
              <table className="mo-table pt-table" data-testid="pt-exits" style={{ minWidth: 600 }}>
                <caption>Exit modes on this trade · all recorded, EOD-1 is the headline</caption>
                <thead><tr><th scope="col">Mode</th><th scope="col">Exit</th><th scope="col">Gross</th><th scope="col">Net 0.25%</th><th scope="col">Net 0.50%</th><th scope="col">Net 1.00%</th></tr></thead>
                <tbody>
                  {MODES.map((m) => {
                    const e = t.exits[m];
                    return (
                      <tr key={m} data-testid={`pt-exit-${m}`}>
                        <th scope="row"><span className="mo-sym">{MODE_LABEL[m].label}</span><span className="pt-small">{MODE_LABEL[m].rule}</span></th>
                        <td className="pt-small">{e?.state === "CLOSED" ? `${e.exit_reason ?? "closed"} · ${day(e.exit_date)}` : e?.state === "NO_BAR_AT_EXIT" ? "no bar at exit" : `open · needs day ${MODE_SESSION[m] - 1 || "0"}`}</td>
                        <td className={`pt-mono ${tone(e?.gross_return)}`}>{e?.state === "CLOSED" ? pct(e.gross_return) : "—"}</td>
                        <td className={`pt-mono ${tone(e?.net_return)}`}>{e?.state === "CLOSED" ? pct(e.net_return) : "—"}</td>
                        <td className={`pt-mono ${tone(e?.net_return_050)}`}>{e?.state === "CLOSED" ? pct(e.net_return_050) : "—"}</td>
                        <td className={`pt-mono ${tone(e?.net_return_100)}`}>{e?.state === "CLOSED" ? pct(e.net_return_100) : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mo-panel" data-testid="pt-log">
              <h3>Lifecycle log</h3>
              <ul className="pt-log">
                {t.events.map((e) => (
                  <li key={e.to_status}><b>{e.to_status.replace(/_/g, " ")}</b><span>{e.note ?? ""}</span><span className="pt-small">{dayYear(e.effective_at)} {clock(e.effective_at)}</span></li>
                ))}
              </ul>
              <p className="pt-note">Every transition is logged. All five exit modes are recorded for every trade; picking the best after the fact would not be a strategy.</p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ── Evaluation ──────────────────────────────────────────────────────────────────────────────────────────────────
function EvalView({ sample, portfolio }: { sample: PaperSample; portfolio: PaperPortfolio }) {
  const [res, setRes] = useState<EvaluationResult | null>(null);
  const [bmode, setBmode] = useState<PaperMode>("EOD-1");
  const [bucketSet, setBucketSet] = useState<"selected" | "universe">("selected");
  useEffect(() => {
    let on = true;
    setRes(null);
    fetchPaperEvaluation(sample, portfolio).then((r) => { if (on) setRes(r); });
    return () => { on = false; };
  }, [sample, portfolio]);
  if (res == null) return <div className="mo-tablewrap" data-testid="pt-eval-loading"><div className="mo-skelrow"><div className="mo-skel" /><div className="mo-skel" /><div className="mo-skel" /></div></div>;
  if (res.kind === "empty") return <div className="mo-state" data-testid="pt-eval-empty"><h3>No evaluation yet</h3><p>The engine stores an evaluation after each run.</p></div>;
  if (res.kind !== "ok") return <div className="mo-state" data-testid="pt-eval-error"><h3>Could not load the evaluation</h3><p>{res.kind === "error" ? res.message : res.kind === "no_access" ? "Not enabled." : "Not found."}</p></div>;
  const ev = res.data;
  const head = ev.modes.find((m) => m.mode === ev.headline_mode) ?? ev.modes[0];
  const aAll = ev.benchmarks.find((b) => b.benchmark === "A_ALL" && b.mode === ev.headline_mode);
  const counted = ev.sessions.counted;
  const bucket = ev.buckets[bucketSet];
  const benchRows = ev.benchmarks.filter((b) => b.mode === bmode);
  const model = ev.modes.find((m) => m.mode === bmode);
  return (
    <div className="pt-main" data-testid="pt-eval">
      <div className={`pt-banner ${ev.statement.established ? "ok" : ""}`} data-testid="pt-statement">
        <b>{ev.sample === "replay" ? "Replay 2025 · " : "Forward · "}{ev.portfolio}</b> — {ev.statement.text}
        {" "}{counted < ev.statement.min_sessions
          ? `${counted} counted session${counted === 1 ? "" : "s"} and ${head?.closed_trades ?? 0} paper trades is too small to conclude anything; the pre-registered minimum is ${ev.statement.min_sessions} sessions.`
          : `${counted} counted sessions, ${head?.closed_trades ?? 0} closed headline trades.`}
        {ev.sample === "forward" && ev.sessions.not_counted.length > 0 ? ` Recorded but not counted: ${ev.sessions.not_counted.map((d) => day(d)).join(", ")}.` : ""}
      </div>

      <div className="pt-stats" data-testid="pt-eval-stats">
        <div className="pt-stat"><span className="pt-stat-l">Sessions counted</span><span className="pt-stat-v">{counted} / {ev.sessions.recorded}</span>
          <span className="pt-stat-s">{ev.sessions.first_counted ? `${dayYear(ev.sessions.first_counted)} – ${dayYear(ev.sessions.last_counted)}` : "none yet"}</span></div>
        <div className="pt-stat"><span className="pt-stat-l">Paper trades · EOD-1</span><span className="pt-stat-v">{head?.closed_trades ?? 0}</span>
          <span className="pt-stat-s">{ev.exceptions.selected} selected · {ev.exceptions.entered} entered</span></div>
        <div className="pt-stat"><span className="pt-stat-l">Net avg · EOD-1</span><span className={`pt-stat-v ${tone(head?.net_mean)}`} data-testid="pt-eval-net">{pct(head?.net_mean)}</span>
          <span className="pt-stat-s">every eligible stock {pct(aAll?.net_mean)}</span></div>
        <div className="pt-stat"><span className="pt-stat-l">+{portfolio === "P5-NEXT" ? 5 : 10}% touched · entry day</span><span className="pt-stat-v">{pct(head?.target_hit_rate, 1, false)}</span>
          <span className="pt-stat-s">every eligible stock {pct(aAll?.hit_rate, 1, false)}</span></div>
        <div className="pt-stat"><span className="pt-stat-l">Edge vs every eligible</span><span className={`pt-stat-v ${tone(head?.edge_vs_a_all?.mean)}`} data-testid="pt-eval-edge">{pct(head?.edge_vs_a_all?.mean)}</span>
          <span className="pt-stat-s">{head?.edge_vs_a_all && head.edge_vs_a_all.lo != null ? `95% CI ${pct(head.edge_vs_a_all.lo)} to ${pct(head.edge_vs_a_all.hi)}` : "needs sessions"}</span></div>
      </div>

      <div className="mo-tablewrap" tabIndex={0}>
        <table className="mo-table pt-table" data-testid="pt-eval-modes" style={{ minWidth: 900 }}>
          <caption>Exit modes and cost sensitivity · pre-registered rules · session-weighted means</caption>
          <thead><tr><th scope="col">Mode</th><th scope="col">Trades</th><th scope="col">Win rate</th><th scope="col">Gross</th><th scope="col">Net 0.25%</th><th scope="col">Net 0.50%</th>
            <th scope="col">Net 1.00%</th><th scope="col">Profit factor</th><th scope="col">vs every eligible</th></tr></thead>
          <tbody>
            {ev.modes.map((m) => (
              <tr key={m.mode} data-testid={`pt-eval-mode-${m.mode}`}>
                <th scope="row"><span className="mo-sym">{MODE_LABEL[m.mode as PaperMode]?.label ?? m.mode}{m.mode === ev.headline_mode ? " · headline" : ""}</span><span className="pt-small">{MODE_LABEL[m.mode as PaperMode]?.rule ?? m.label}</span></th>
                <td className="pt-mono">{m.closed_trades}</td><td className="pt-mono">{pct(m.win_rate, 1, false)}</td>
                <td className={`pt-mono ${tone(m.gross_mean)}`}>{pct(m.gross_mean)}</td><td className={`pt-mono ${tone(m.net_mean)}`}>{pct(m.net_mean)}</td>
                <td className={`pt-mono ${tone(m.net_mean_050)}`}>{pct(m.net_mean_050)}</td><td className={`pt-mono ${tone(m.net_mean_100)}`}>{pct(m.net_mean_100)}</td>
                <td className="pt-mono">{m.profit_factor != null ? m.profit_factor.toFixed(2) : "—"}</td>
                <td className={`pt-mono ${tone(m.edge_vs_a_all?.mean)}`}>{pct(m.edge_vs_a_all?.mean)}{m.edge_vs_a_all?.lo != null ? <span className="pt-small"> [{pct(m.edge_vs_a_all.lo)}, {pct(m.edge_vs_a_all.hi)}]</span> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="pt-grid">
        <div className="pt-main" style={{ gap: 10 }}>
          <div className="pt-controls">
            <span className="pt-small">Against benchmarks · same sessions, same exits, same costs</span>
            <div className="pt-seg" role="group" aria-label="Benchmark mode">
              {MODES.map((m) => <button key={m} aria-pressed={bmode === m} onClick={() => setBmode(m)} data-testid={`pt-bmode-${m}`}>{MODE_LABEL[m].label}</button>)}
            </div>
          </div>
          <div className="mo-tablewrap" tabIndex={0}>
            <table className="mo-table pt-table" data-testid="pt-eval-bench" style={{ minWidth: 560 }}>
              <thead><tr><th scope="col">Basket</th><th scope="col">Net avg</th><th scope="col">+{portfolio === "P5-NEXT" ? 5 : 10}% touched</th><th scope="col">Positive</th><th scope="col">Trades</th></tr></thead>
              <tbody>
                {model && <tr data-testid="pt-bench-MODEL"><th scope="row"><span className="mo-sym">Model top 5</span></th><td className={`pt-mono ${tone(model.net_mean)}`}>{pct(model.net_mean)}</td>
                  <td className="pt-mono">{pct(model.target_hit_rate, 1, false)}</td><td className="pt-mono">{pct(model.win_rate, 1, false)}</td><td className="pt-mono">{model.closed_trades}</td></tr>}
                {benchRows.map((b) => (
                  <tr key={b.benchmark} data-testid={`pt-bench-${b.benchmark}`}>
                    <th scope="row"><span className="mo-sym" style={{ color: "var(--c-ink-2)" }}>{BENCH_LABEL[b.benchmark] ?? b.label}</span></th>
                    <td className={`pt-mono ${tone(b.net_mean)}`}>{pct(b.net_mean)}</td><td className="pt-mono">{b.hit_rate != null ? pct(b.hit_rate, 1, false) : "—"}</td>
                    <td className="pt-mono">{pct(b.positive_rate, 1, false)}</td><td className="pt-mono">{b.trades.toLocaleString("en-IN")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="pt-note">Nifty 50 carries no costs. A: every eligible stock, and five drawn at random with a fixed seed. B: five matched on sector, turnover group,
            volatility, price and liquidity. C: the five with the highest chance of any 5% or 10% move, ignoring direction.</p>

          <div className="pt-controls">
            <span className="pt-small">Calibration by probability bucket</span>
            <div className="pt-seg" role="group" aria-label="Bucket set">
              <button aria-pressed={bucketSet === "selected"} onClick={() => setBucketSet("selected")} data-testid="pt-buckets-selected">Selected trades</button>
              <button aria-pressed={bucketSet === "universe"} onClick={() => setBucketSet("universe")} data-testid="pt-buckets-universe">Every eligible stock</button>
            </div>
          </div>
          <div className="mo-tablewrap" tabIndex={0}>
            <table className="mo-table pt-table" data-testid="pt-eval-buckets" style={{ minWidth: 640 }}>
              <thead><tr><th scope="col">Predicted</th><th scope="col">n</th><th scope="col">Hit rate vs predicted</th><th scope="col">Net avg · EOD-1</th><th scope="col">Avg MAE</th></tr></thead>
              <tbody>
                {bucket.map((b) => (
                  <tr key={b.lo} data-testid={`pt-bucket-${b.lo}`}>
                    <th scope="row" className="pt-mono">{Math.round(b.lo * 100)}–{Math.round(b.hi * 100)}%</th><td className="pt-mono">{b.n.toLocaleString("en-IN")}</td>
                    <td>{b.n > 0 && b.model_label_rate != null ? (
                      <div style={{ display: "grid", gap: 4, minWidth: 180 }}>
                        <span className="pt-mono">{pct(b.model_label_rate, 1, false)} <span className="pt-small">predicted {pct(b.predicted_mean, 1, false)}</span></span>
                        <span className="pt-bar"><span style={{ width: `${Math.min(100, b.model_label_rate * 150)}%` }} /><i style={{ left: `${Math.min(100, (b.predicted_mean ?? 0) * 150)}%` }} /></span>
                      </div>) : <span className="muted">—</span>}</td>
                    <td className={`pt-mono ${tone(b.net_mean)}`}>{b.n > 0 ? pct(b.net_mean) : "—"}</td><td className="pt-mono">{b.n > 0 ? pct(b.mae_mean) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="pt-note">The amber tick is the bucket's average predicted probability; the bar is how often the session high actually reached the level. A high hit rate with a
            negative net average is not a good trade.</p>
        </div>
        <aside className="pt-side">
          {head?.portfolio && (
            <div className="mo-panel" data-testid="pt-eval-portfolio">
              <h3>Daily paper portfolio · EOD-1</h3>
              <dl className="pt-kv">
                <dt>capital base</dt><dd>{inr(head.portfolio.capital_base_inr)}</dd>
                <dt>total P&amp;L</dt><dd className={tone(head.portfolio.total_pnl_inr)}>{inr(head.portfolio.total_pnl_inr, true)}</dd>
                <dt>max drawdown</dt><dd>{inr(head.portfolio.max_drawdown_inr)}</dd>
                <dt>mean daily</dt><dd>{pct(head.portfolio.mean_daily_return)}</dd>
                <dt>daily volatility</dt><dd>{pct(head.portfolio.volatility_daily, 2, false)}</dd>
                <dt>Sharpe-like</dt><dd>{head.portfolio.sharpe_like != null ? head.portfolio.sharpe_like.toFixed(2) : "—"}</dd>
              </dl>
              <p className="pt-note">No compounding: the same capital each session, split across overlapping windows.</p>
            </div>
          )}
          <div className="mo-panel" data-testid="pt-eval-exceptions">
            <h3>Entry exceptions</h3>
            <ul className="pt-list">
              {Object.entries(ev.exceptions.by_reason).map(([k, v]) => <li key={k}><span>{k.replace(/_/g, " ").toLowerCase()}</span><span className="pt-mono">{v}</span></li>)}
              {Object.entries(ev.exceptions.flags).map(([k, v]) => <li key={k}><span>{k.replace(/_/g, " ").toLowerCase()} (flag)</span><span className="pt-mono">{v}</span></li>)}
              {Object.keys(ev.exceptions.by_reason).length + Object.keys(ev.exceptions.flags).length === 0 && <li><span>None</span></li>}
            </ul>
          </div>
          <div className="mo-panel" data-testid="pt-eval-limits">
            <h3>Known limits on this sample</h3>
            <ul className="pt-list" style={{ display: "grid", gap: 6 }}>
              <li>Entries assume a fill at the official open; slippage beyond the flat cost is not modelled.</li>
              <li>Overlapping five-session windows share days; intervals use Newey–West errors.</li>
              <li>Sector and names are today's; stocks that delisted since 2025 are missing from the replay universe.</li>
              {ev.sample === "replay" ? <li>Replay is retrospective: the walk-forward was run in 2026 over 2025 data.</li>
                : <li>Forward results count only for snapshots frozen after the rules were registered.</li>}
            </ul>
          </div>
        </aside>
      </div>
    </div>
  );
}
