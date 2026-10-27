/**
 * The AI scanner watchlist (the user's requirement of 2026-10-26): every trading day, after the AI scanner run, the Top 10
 * cash ideas and the Top 10 F&O ideas are stored as that day's list (scripts/build_ai_watchlist.py, 20:15 IST), and every
 * day's list is kept. This block shows them by day.
 *
 *   GET  /api/desk/ai-watchlist[?date=]   the day's lists, the dateline, each idea's earlier list days (ai-watchlist-data.ts)
 *   GET  /api/live/stream (useLiveOverlays)   Kite prices for the cash ideas: live while the session is open, the day's
 *                                          Kite close after it; nothing (the list-day close stands) when Kite is not connected
 *   POST /api/live/fno-quotes (useFnoLive)  live option premiums for the F&O ideas' legs, only while the feed is LIVE
 *                                          (Kite's REST budget is rate-limited), every 30 seconds
 *   GET  /api/fno/scan/buildup (useBuildup) each underlying's futures OI build-up, end of day
 *   POST /api/desk/paper-trades           a cash idea at the scanner's levels; an F&O idea as a strategy (IdeaActions)
 *   POST /api/desk/strategy/payoff        an F&O idea's payoff, only once opened (IdeaActions)
 *
 * The dateline is one chip per stored day, newest first, with how many ideas each list holds; a chip loads that day. Each
 * idea says how many list days in a row it has been on. Links open the trading desk: the chart, the plan in the Strategy
 * Builder, the option chain, the futures OI build-up, the F&O lab with the idea in focus, and the paper trades.
 *
 * Every figure is what the routes answered on the list day, kept as it was; only the prices and premiums labelled Live or
 * Close are newer. "Ideas", not recommendations; nothing places an order.
 */
import { useEffect, useId, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { ApiError } from "@/services/api/errors";
import { StockIcon } from "../../components/EntityIcon";
import { Btn, EmptyBlock, LoadingBlock, Pill, Section, TONE_COLOR, fmtINR, fmtNum, fmtPct, signTone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { closeLabel, useLiveMeta, useLiveOverlays, type OverlayQuote } from "../../lib/useLiveQuotes";
import { dayLabel, fmtPrice } from "../markets/format";
import { LoadError } from "../markets/parts";
import { BUCKET_LABEL, type SetupBucket } from "../tradingdesk/desk-data";
import { ENTRY_RULE_SHORT, entryRuleFor, useAddPaperTrade, writeProblem, type NewPaperTrade } from "../tradingdesk/desk-trading";
import { BUILDUP_META, buildupRowFor, indexRowFor, useBuildup } from "../tradingdesk/fno-buildup";
import { StatusPill, ratio, rupeesAbs } from "../tradingdesk/strategy/plan-format";
import type { PlanStatus } from "../tradingdesk/strategy/plan-contract";
import { IdeaActions } from "../tradingdesk/strategy/TopByRegime";
import { StoredIdeaLevels, readStoredLevels } from "../tradingdesk/IdeaLevels";
import { legSlot, legsForBoard, liveNetPremium, useFnoLive, type LiveAnswer } from "../tradingdesk/strategy/top-live";
import {
  deskBuildup, deskChain, deskChart, deskLab, deskPlan, deskTrades, useAiWatchlist, type AiWatchDay, type CashEntry, type FnoEntry,
} from "./ai-watchlist-data";
import { PlanPaperTrade } from "../tradingdesk/PlanPaperTrade";

type Segment = "cash" | "fno";
type BuildupData = ReturnType<typeof useBuildup>["data"];

const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const PLAN_STATUSES = ["plan", "wait", "no_trade", "insufficient_data"];
const LIVE_POLL_MS = 30_000;

const shortDay = (d: string) => new Date(`${d}T12:00:00+05:30`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Kolkata" });

function Chip({ testId, onClick, children, title }: { testId: string; onClick: () => void; children: ReactNode; title?: string }) {
  return <button type="button" className="cp-chip" data-testid={testId} onClick={onClick} title={title}>{children}</button>;
}

function DaysOn({ e, listDate }: { e: { days_on_list: number; earlier_list_dates: string[] }; listDate: string }) {
  const n = e.days_on_list;
  const title = e.earlier_list_dates.length ? `Also on the lists of ${e.earlier_list_dates.slice(0, 6).map(shortDay).join(", ")}` : `First on the list of ${shortDay(listDate)}`;
  return (
    <span data-testid="aiw-days-on" data-days={n} className="cp-pill" data-tone={n > 1 ? "indigo" : "mint"} title={title} style={{ flex: "none" }}>
      {n > 1 ? `${n} days on the list` : "New on this list"}
    </span>
  );
}

/** "Futures OI: Long build-up · price +1.2% · OI +5.3% · EOD 26 Oct" — the underlying's own row in the build-up scan. */
function OiLine({ sym, index, scan }: { sym: string; index: boolean; scan: BuildupData }) {
  const row = scan ? (index ? indexRowFor(scan, sym) : buildupRowFor(scan, sym)) : null;
  if (!row || !row.label) return <span data-testid="aiw-oi" style={quiet}>Futures OI build-up: — (not in the end-of-day scan)</span>;
  const meta = BUILDUP_META[row.label];
  return (
    <span data-testid="aiw-oi" data-label={row.label} style={{ ...quiet, color: "var(--cp-ink-2)" }}>
      Futures OI: <span style={{ color: TONE_COLOR[meta.tone] }}>{meta.label}</span>
      {" · "}price {fmtPct(row.priceChgPct, { signed: true, digits: 1 })} · OI {fmtPct(row.oiChgPct, { signed: true, digits: 1 })}
      {scan?.asOf ? ` · end of day ${shortDay(scan.asOf)}` : ""}
    </span>
  );
}

// ── cash ─────────────────────────────────────────────────────────────────

/** A paper trade at the stored row's TradePlan (Phase 2.1: the plan the job stored that day, cited by id). A day stored
 *  before plans existed has none; only then is the trade recorded at the scanner's levels, as it was. */
function CashPaperTrade({ e, listDate }: { e: CashEntry; listDate: string }) {
  if (e.trade_plan) {
    const bucket = e.scanner.bucket;
    return <PlanPaperTrade tp={e.trade_plan} symbol={e.symbol} sized={e.sized_shares ?? null} testPrefix="aiw-paper"
      source={{ kind: "scanner", ...(bucket ? { bucket } : {}), signal_date: e.scanner.close_date ?? listDate }} />;
  }
  return <ScannerLevelsPaperTrade e={e} listDate={listDate} />;
}

function ScannerLevelsPaperTrade({ e, listDate }: { e: CashEntry; listDate: string }) {
  const paper = useAddPaperTrade();
  const id = useId();
  const [qty, setQty] = useState(e.sized_shares != null ? String(e.sized_shares) : "");
  const { entry, stop, target, bucket } = e.scanner;
  if (entry == null || stop == null || !(entry > stop)) {
    return <span data-testid="aiw-paper-none" style={quiet}>A paper trade needs the scanner’s entry and a stop below it; {e.symbol} has none. Open the plan to record one there.</span>;
  }
  const sendTarget = target != null && target > entry ? target : null;
  const rule = entryRuleFor(entry, e.scanner.close, { bucket });
  const q = Number(qty.trim());
  const ok = /^\d+$/.test(qty.trim()) && q >= 1 && q <= 1_000_000;
  const body: NewPaperTrade | null = ok ? {
    symbol: e.symbol, quantity: q, entry_price: entry, stop_price: stop, target_price: sendTarget,
    source: { kind: "scanner", ...(bucket ? { bucket } : {}), signal_date: e.scanner.close_date ?? listDate },
    entry_rule: rule,
  } : null;
  return (
    <span className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <label htmlFor={id} style={quiet}>Shares</label>
        <input id={id} data-testid="aiw-paper-qty" inputMode="numeric" value={qty} placeholder="Qty" onChange={(ev) => { paper.reset(); setQty(ev.target.value); }}
          style={{ width: 80, height: 30, padding: "0 8px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontSize: 12.5 }} />
        <Btn variant="primary" data-testid="aiw-paper-add" disabled={!body || paper.isPending || paper.isSuccess} onClick={() => { if (body) paper.mutate(body); }} style={{ padding: "5px 12px", fontSize: 12 }}>
          {paper.isSuccess ? "Added" : paper.isPending ? "Adding…" : "Add paper trade"}
        </Btn>
      </span>
      <span style={quiet}>At the scanner’s levels on {shortDay(listDate)}: entry {fmtPrice(entry)} (<span data-testid="aiw-paper-rule" data-rule={rule}>{ENTRY_RULE_SHORT[rule]}</span>), stop {fmtPrice(stop)}{sendTarget != null ? `, target ${fmtPrice(sendTarget)}` : ", no target"}. Simulated; nothing is sent to a broker.</span>
      {paper.isSuccess && <span role="status" data-testid="aiw-paper-done" style={{ fontSize: 12, color: "var(--mint)" }}>Paper trade added: {fmtNum(q)} {e.symbol} at {fmtPrice(entry)}.</span>}
      {paper.isError && <span role="alert" data-testid="aiw-paper-error" style={{ fontSize: 12, color: "var(--cp-danger)" }}>Not added — {writeProblem(paper.error)}</span>}
    </span>
  );
}

function CashRow({ e, listDate, quote, scan }: { e: CashEntry; listDate: string; quote: OverlayQuote | null; scan: BuildupData }) {
  const { go } = useCopilotShell();
  const [paperOpen, setPaperOpen] = useState(false);
  const sc = e.scanner;
  const setup = sc.bucket && sc.bucket in BUCKET_LABEL ? BUCKET_LABEL[sc.bucket as SetupBucket] : "Scanner setup";
  const status = (PLAN_STATUSES.includes(e.plan_status ?? "") ? e.plan_status : "insufficient_data") as PlanStatus;
  const listed = sc.close ?? null;
  const since = quote && listed ? ((quote.ltp - listed) / listed) * 100 : null;
  return (
    <li data-testid={`aiw-cash-${e.symbol}`} className="flex min-w-0 flex-col" style={{ gap: 8, padding: "12px 16px", borderTop: "1px solid var(--cp-line)" }}>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: 10 }}>
        <span className="cp-num" style={{ flex: "none", width: 22, fontSize: 11, color: "var(--cp-ink-3)" }}>{String(e.rank).padStart(2, "0")}</span>
        <StockIcon symbol={e.symbol} name={e.name} size={26} />
        <span className="flex min-w-0 flex-col" style={{ flex: "1 1 160px" }}>
          <span data-testid="aiw-cash-symbol" style={{ fontWeight: 600 }}>{e.symbol}</span>
          <span style={{ ...quiet, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{[e.name, e.sector].filter(Boolean).join(" · ") || "—"}</span>
        </span>
        <DaysOn e={e} listDate={listDate} />
        <span className="cp-num" style={{ fontSize: 12 }} title="The scanner's rules-based score, 0–100. Not a probability.">Score {sc.score != null ? `${fmtNum(sc.score)}/100` : "—"}</span>
        <StatusPill status={status} testId="aiw-cash-status" />
      </div>
      <div className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "4px 14px", paddingLeft: 32 }}>
        <span style={{ ...quiet, color: "var(--cp-ink-2)" }}>{setup}</span>
        <span data-testid="aiw-cash-listed" className="cp-num" style={{ fontSize: 12.5 }}>Close {shortDay(sc.close_date ?? listDate)} {fmtPrice(listed)}</span>
        {quote ? (
          <span data-testid="aiw-cash-latest" data-kind={quote.kind} className="cp-num" style={{ fontSize: 12.5 }}>
            <span style={{ color: quote.kind === "live" ? "var(--mint)" : "var(--cp-ink-3)" }}>{quote.kind === "live" ? "Live · Kite" : closeLabel(quote)}</span>{" "}
            {fmtPrice(quote.ltp)}{" · "}
            <span data-testid="aiw-cash-since" style={{ color: since == null ? undefined : TONE_COLOR[signTone(since)] }}>{fmtPct(since, { signed: true, digits: 2 })} since the list</span>
          </span>
        ) : (
          <span data-testid="aiw-cash-latest" data-kind="none" style={quiet}>Newer price: — (from Kite while the market is open, and its close after)</span>
        )}
      </div>
      <div className="flex min-w-0 flex-col" style={{ gap: 3, paddingLeft: 32 }}>
        <span data-testid="aiw-cash-strategy" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
          <span style={{ color: "var(--cp-ink-3)" }}>Strategy that fits: </span>
          {e.preferred ? (
            <><strong style={{ fontWeight: 500 }}>{e.preferred.label}</strong>{e.preferred.legs_text ? ` · ${e.preferred.legs_text}` : ""}{` · max loss ${rupeesAbs(e.preferred.max_loss)} · reward : risk ${ratio(e.preferred.reward_risk_net)}`}</>
          ) : (
            <span>{e.status_reasons[0] ?? "none passed the plan’s checks that day"}</span>
          )}
        </span>
        {sc.entry != null && sc.stop != null && (
          <span className="cp-num" style={quiet}>Scanner levels: entry {fmtPrice(sc.entry)} · stop {fmtPrice(sc.stop)}{sc.target != null ? ` · target ${fmtPrice(sc.target)}` : ""}</span>
        )}
        {e.fno_eligible && <OiLine sym={e.symbol} index={false} scan={scan} />}
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 6, paddingLeft: 32 }}>
        <Chip testId="aiw-cash-chart" onClick={() => go(deskChart(e.symbol))}>Chart ›</Chip>
        <Chip testId="aiw-cash-plan" onClick={() => go(deskPlan(e, listDate))} title="The plan in the trading desk's Strategy Builder: sizing, costs, evidence, payoff">Strategy ›</Chip>
        {e.fno_eligible && <Chip testId="aiw-cash-chain" onClick={() => go(deskChain(e.symbol))}>Option chain ›</Chip>}
        <button type="button" className="cp-chip" data-testid="aiw-cash-paper" aria-expanded={paperOpen} onClick={() => setPaperOpen((v) => !v)}>{paperOpen ? "Hide paper trade" : "Paper trade"}</button>
        <Chip testId="aiw-cash-trades" onClick={() => go(deskTrades())}>View trades ›</Chip>
      </div>
      {paperOpen && <div style={{ paddingLeft: 32 }}><CashPaperTrade e={e} listDate={listDate} /></div>}
    </li>
  );
}

// ── F&O ──────────────────────────────────────────────────────────────────

function Greeks({ g }: { g: FnoEntry["net_greeks"] }) {
  const cell = (k: string, v: number | null | undefined, d = 2) => (
    <span className="flex flex-col" style={{ gap: 1 }}>
      <span style={{ fontSize: 10.5, letterSpacing: 0.3, textTransform: "uppercase", color: "var(--cp-ink-3)" }}>{k}</span>
      <span className="cp-num" style={{ fontSize: 12.5 }}>{v == null ? "—" : fmtNum(v, d)}</span>
    </span>
  );
  return (
    <div data-testid="aiw-fno-greeks" className="flex flex-wrap" style={{ gap: "6px 18px" }} title="Net Greeks of the whole structure at the list day's chain (Black-76 on end-of-day prices)">
      {cell("Net delta", g?.delta)}{cell("Gamma", g?.gamma, 4)}{cell("Theta / day", g?.theta)}{cell("Vega", g?.vega)}
    </div>
  );
}

function Legs({ e, live, at }: { e: FnoEntry; live: LiveAnswer | undefined; at: Map<string, number> }) {
  const th: CSSProperties = { textAlign: "left", padding: "4px 8px", fontWeight: 500, fontSize: 11, color: "var(--cp-ink-3)", whiteSpace: "nowrap" };
  const td: CSSProperties = { padding: "4px 8px", fontSize: 12, whiteSpace: "nowrap" };
  return (
    <div className="cp-scroll overflow-x-auto" style={{ maxWidth: "100%" }}>
      <table data-testid="aiw-fno-legs" style={{ borderCollapse: "collapse", minWidth: 420 }}>
        <thead><tr><th style={th}>Side</th><th style={th}>Option</th><th style={th}>Expiry</th><th style={th}>Lots × size</th><th style={th}>Premium (list day)</th><th style={th}>Live premium</th></tr></thead>
        <tbody>
          {e.legs.map((l, j) => {
            const idx = at.get(legSlot(e, j));
            const q = live?.available && idx != null ? live.quotes[String(idx)] : undefined;
            return (
              <tr key={j} style={{ borderTop: "1px solid var(--cp-line)" }}>
                <td style={{ ...td, color: l.side === "sell" ? "var(--cp-danger)" : "var(--mint)" }}>{l.side === "sell" ? "Sell" : "Buy"}</td>
                <td style={td} className="cp-num">{l.kind === "option" ? `${fmtNum(l.strike ?? null)} ${(l.option_type ?? "").toUpperCase().startsWith("C") ? "CE" : "PE"}` : l.kind}</td>
                <td style={td}>{l.expiry ? shortDay(l.expiry) : "—"}</td>
                <td style={td} className="cp-num">{l.quantity != null && l.lot_size != null ? `${fmtNum(l.quantity)} × ${fmtNum(l.lot_size)}` : "—"}</td>
                <td style={td} className="cp-num">{l.entry_price != null ? fmtNum(l.entry_price, 2) : "—"}</td>
                <td data-testid="aiw-fno-leg-live" style={{ ...td, color: q ? "var(--mint)" : "var(--cp-ink-4)" }} className="cp-num">{q ? fmtNum(q.last_price, 2) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FnoRow({ e, listDate, rulesVersion, live, at, liveOn, scan }: { e: FnoEntry; listDate: string; rulesVersion: string | null | undefined; live: LiveAnswer | undefined; at: Map<string, number>; liveOn: boolean; scan: BuildupData }) {
  const { go } = useCopilotShell();
  const sym = e.underlying;
  // The levels stored with this day's list, never worked out again on a later day's prices.
  const stored = useMemo(() => readStoredLevels(e.strategy_levels), [e.strategy_levels]);
  const index = e.kind === "index";
  const liveNet = liveNetPremium(e, live, at);
  // Mark against the list day, as if entered at its premiums: (what it cost then) − (what it would cost now), per the listed lots.
  const change = liveNet != null && e.net_premium != null ? Math.round((e.net_premium - liveNet) * 100) / 100 : null;
  return (
    <li data-testid={`aiw-fno-${sym}`} data-kind={e.kind} className="flex min-w-0 flex-col" style={{ gap: 8, padding: "12px 16px", borderTop: "1px solid var(--cp-line)" }}>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: 10 }}>
        <span className="cp-num" style={{ flex: "none", width: 22, fontSize: 11, color: "var(--cp-ink-3)" }}>{String(e.rank).padStart(2, "0")}</span>
        <StockIcon symbol={sym} size={26} />
        <span className="flex min-w-0 flex-col" style={{ flex: "1 1 160px" }}>
          <span data-testid="aiw-fno-symbol" style={{ fontWeight: 600 }}>{sym}</span>
          <span style={quiet}>{index ? "Index options" : "Stock F&O"}</span>
        </span>
        <DaysOn e={e} listDate={listDate} />
        <span data-testid="aiw-fno-fit" className="cp-chip" style={{ flex: "none", fontSize: 11, borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" }}
          title="How well the structure fitted the regime measured that day. Not a probability and not a track record.">fit {fmtNum(e.fit.score, 1)}</span>
      </div>
      <div className="flex min-w-0 flex-col" style={{ gap: 6, paddingLeft: 32 }}>
        <span data-testid="aiw-fno-strategy" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
          <span style={{ color: "var(--cp-ink-3)" }}>Strategy that fits: </span><strong style={{ fontWeight: 500 }}>{e.name}</strong>
          {e.expiry ? ` · exp ${shortDay(e.expiry)}${e.days_to_expiry != null ? ` (${e.days_to_expiry}d then)` : ""}` : ""}
        </span>
        <span className="cp-num" style={{ ...quiet, color: "var(--cp-ink-2)" }}>
          max loss {e.loss_unbounded ? "no lower limit" : fmtINR(e.max_loss)} · max gain {e.profit_unbounded ? "no upper limit" : fmtINR(e.max_profit)} · reward : risk {e.reward_risk == null ? "—" : `${fmtNum(e.reward_risk, 2)} : 1`} · breakeven {e.breakevens.length ? e.breakevens.map((b) => fmtNum(b, 2)).join(", ") : "—"}
        </span>
        <StoredIdeaLevels read={stored} underlying={sym} />
        <Greeks g={e.net_greeks} />
        <Legs e={e} live={live} at={at} />
        <span data-testid="aiw-fno-live" data-state={liveNet != null ? "live" : liveOn ? "partial" : "off"} style={{ ...quiet, color: liveNet != null ? "var(--cp-ink-2)" : undefined }}>
          {liveNet != null ? (
            <>Live net premium {fmtINR(liveNet)} · list day {fmtINR(e.net_premium)} · <span data-testid="aiw-fno-change" style={{ color: change == null ? undefined : TONE_COLOR[signTone(change)] }}>{change == null ? "—" : `${change > 0 ? "+" : ""}${fmtINR(change)}`} since the list</span> (per the listed lots, before costs)</>
          ) : liveOn ? (
            <>Live premiums: not every leg has a live price{live?.reason ? ` (${live.reason})` : ""}.</>
          ) : (
            <>Live premiums show while the market is open and Kite is connected. Premiums above are the list day’s close ({e.price_source ?? "NSE F&O bhavcopy"}).</>
          )}
        </span>
        <OiLine sym={sym} index={index} scan={scan} />
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 6, paddingLeft: 32 }}>
        <Chip testId="aiw-fno-lab" onClick={() => go(deskLab(sym, index))} title={index ? "The lab's NIFTY & BANKNIFTY workspace" : "The lab's Candidates with this stock in focus"}>Open in F&amp;O lab ›</Chip>
        <Chip testId="aiw-fno-chain" onClick={() => go(deskChain(sym))}>Option chain ›</Chip>
        <Chip testId="aiw-fno-buildup" onClick={() => go(deskBuildup(sym, index))}>{index ? "Index futures build-up ›" : "OI build-up ›"}</Chip>
      </div>
      <div style={{ paddingLeft: 32 }}>
        <IdeaActions idea={e} onViewTrades={() => go(deskTrades())} rulesVersion={rulesVersion}
          levels={stored.kind === "ok" ? { data: stored.levels, pending: false } : undefined} />
      </div>
    </li>
  );
}

// ── the block ────────────────────────────────────────────────────────────

function Dateline({ day, onPick }: { day: AiWatchDay; onPick: (d: string | null) => void }) {
  const newest = day.available_dates[0]?.list_date ?? null;
  return (
    <div role="group" aria-label="List days" data-testid="aiw-dateline" className="cp-scroll flex overflow-x-auto" style={{ gap: 6, paddingBottom: 2 }}>
      {day.available_dates.map((d) => {
        const on = d.list_date === day.list_date;
        return (
          <button key={d.list_date} type="button" data-testid={`aiw-day-${d.list_date}`} aria-pressed={on} onClick={() => onPick(d.list_date === newest ? null : d.list_date)}
            className="flex flex-col items-start"
            style={{ flex: "none", gap: 1, padding: "6px 12px", borderRadius: 12, cursor: "pointer", fontFamily: "var(--sans)",
              border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`, background: on ? "var(--mint-soft)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-2)" }}>
            <span style={{ fontSize: 12.5, fontWeight: 500 }}>{shortDay(d.list_date)}{d.list_date === newest ? " · latest" : ""}</span>
            <span className="cp-num" style={{ fontSize: 10.5, color: "var(--cp-ink-3)" }}>{d.cash} cash · {d.fno} F&amp;O</span>
          </button>
        );
      })}
    </div>
  );
}

export function AiScannerWatchlist() {
  const [date, setDate] = useState<string | null>(null);
  const [seg, setSeg] = useState<Segment>("cash");
  const q = useAiWatchlist(date);
  const day = q.data;
  const listDate = day?.list_date ?? null;
  const meta = useLiveMeta();
  const liveOn = meta.mode === "live";
  const scanQ = useBuildup(true);

  const cashSyms = useMemo(() => (day?.cash ?? []).map((e) => e.symbol), [day]);
  const quotes = useLiveOverlays(cashSyms, listDate);
  const fno = useMemo(() => day?.fno ?? [], [day]);
  const { legs, at } = useMemo(() => legsForBoard(fno), [fno]);
  const liveQ = useFnoLive(legs, liveOn && seg === "fno");
  useEffect(() => {
    if (!liveOn || seg !== "fno") return undefined;
    const t = window.setInterval(() => { void liveQ.refetch(); }, LIVE_POLL_MS);
    return () => window.clearInterval(t);
  }, [liveOn, seg, liveQ]);

  const notStored = date !== null && q.error instanceof ApiError && q.error.status === 404;
  let body: ReactNode;
  if (q.isPending) {
    body = <div style={{ padding: 16 }}><LoadingBlock label="Loading the AI scanner watchlist" rows={4} /></div>;
  } else if (notStored) {
    body = <div data-testid="aiw-not-stored" style={{ padding: 16 }}><EmptyBlock title={`No list is stored for ${dayLabel(date, { year: true })}`} action={<Btn onClick={() => setDate(null)}>Show the latest list</Btn>} /></div>;
  } else if (q.isError && !day) {
    body = <div data-testid="aiw-error" style={{ padding: 16 }}><LoadError title="The AI scanner watchlist didn’t load" error={q.error} onRetry={() => q.refetch()} /></div>;
  } else if (!day || !listDate) {
    body = <div data-testid="aiw-empty" style={{ padding: 16 }}><EmptyBlock title="No AI scanner list yet" body={day?.empty_reason ?? "Each weekday's list is stored after the AI scanner run."} /></div>;
  } else {
    const n = day.notes;
    const segs: Array<{ key: Segment; label: string }> = [{ key: "cash", label: `Cash · ${day.cash.length}` }, { key: "fno", label: `F&O · ${day.fno.length}` }];
    body = (
      <div className="flex flex-col">
        <div className="flex flex-col" style={{ gap: 10, padding: "12px 16px", borderBottom: "1px solid var(--cp-line)" }}>
          <Dateline day={day} onPick={setDate} />
          <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
            <div role="group" aria-label="Segment" className="inline-flex" style={{ gap: 2, padding: 3, borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}>
              {segs.map((s) => (
                <button key={s.key} type="button" data-testid={`aiw-seg-${s.key}`} aria-pressed={seg === s.key} onClick={() => setSeg(s.key)}
                  style={{ padding: "5px 12px", borderRadius: 999, border: 0, cursor: "pointer", fontSize: 12.5, fontFamily: "var(--sans)", background: seg === s.key ? "var(--bg-4)" : "transparent", color: seg === s.key ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>
                  {s.label}
                </button>
              ))}
            </div>
            <span data-testid="aiw-price-mode">
              {liveOn ? <Pill tone="mint">Live prices · Kite</Pill> : <Pill tone="amber" title="Live while the NSE session is open and Kite is connected; after the close, the day's Kite close">Prices: list-day close, and Kite when available</Pill>}
            </span>
          </div>
          {q.isPlaceholderData && <span className="cp-mono-note">Loading that day…</span>}
        </div>

        {seg === "cash" ? (
          day.cash.length === 0 ? <div style={{ padding: 16 }}><EmptyBlock title="No cash idea on this list" /></div> : (
            <ol data-testid="aiw-cash-list" className="m-0 p-0" style={{ listStyle: "none" }}>
              {day.cash.map((e) => <CashRow key={e.symbol} e={e} listDate={listDate} quote={quotes.get(e.symbol)} scan={scanQ.data} />)}
            </ol>
          )
        ) : (
          day.fno.length === 0 ? <div style={{ padding: 16 }}><EmptyBlock title="No F&O idea on this list" /></div> : (
            <ol data-testid="aiw-fno-list" className="m-0 p-0" style={{ listStyle: "none" }}>
              {day.fno.map((e) => <FnoRow key={e.underlying} e={e} listDate={listDate} rulesVersion={n.fno_rules_version} live={liveOn ? liveQ.data : undefined} at={at} liveOn={liveOn} scan={scanQ.data} />)}
            </ol>
          )
        )}

        <div className="flex flex-col" style={{ gap: 4, padding: "12px 16px", borderTop: "1px solid var(--cp-line)" }}>
          <span data-testid="aiw-rule" style={quiet}>{seg === "cash" ? day.rules.cash : day.rules.fno}</span>
          <span data-testid="aiw-ranking-note" style={quiet}>{seg === "cash" ? n.cash_ranking : n.fno_ranking}</span>
          {seg === "fno" && n.regime && <span data-testid="aiw-regime" style={quiet}>Regime that day: {n.regime.label ?? "—"}{n.regime.as_of ? ` (measured ${shortDay(n.regime.as_of)})` : ""}{n.regime.india_vix != null ? ` · India VIX ${fmtNum(n.regime.india_vix, 2)}` : ""}{n.fno_staleness ? ` · ${n.fno_staleness}` : ""}</span>}
          <span data-testid="aiw-disclaimer" style={quiet}>
            Ideas the AI scanner ranked that day, kept as they were, for review — not recommendations. Nothing is sent to a broker; paper trades are simulated. 9 out of 10 individual traders in equity F&amp;O incurred net losses (SEBI study).
          </span>
        </div>
      </div>
    );
  }

  return (
    <Section
      title={<span data-testid="aiw-title">AI scanner watchlist{listDate ? ` · ${shortDay(listDate)}` : ""}</span>}
      note={<span data-testid="aiw-note">Top 10 cash and F&amp;O ideas, a new list after each day’s scan, every day kept</span>}
      flush
    >
      <div data-testid="ai-scanner-watchlist">{body}</div>
    </Section>
  );
}
