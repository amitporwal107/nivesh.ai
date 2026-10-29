/**
 * Phase 3 decision card — ONE component for every surface that shows a trade idea's plan (criteria 3.1):
 *
 *   row    one line (entry and order type · stop and its method · targets in R · size · rupee risk and % of equity ·
 *          estimated costs · horizon · plan id) with the status, the approval badge, and an expander for the rest:
 *          Top 10 stock and F&O rows, the AI watchlist's cash and F&O rows, the Top-by-regime cards
 *   full   every section open: the lab's focus panel, the Strategy Builder's selected candidate, the paper-trade record
 *
 * Every level is the TradePlan's (plan-view.ts reads it by id); the size, the rupee risk, the costs and the % of equity are
 * the universal risk service's own sizing of the plan for the signed-in account (`account_size`, backend
 * risk_gate/plan_sizing.py), so the size shown is the size a submission is approved at when no portfolio limit binds. A
 * field that is not there says "unavailable" and why, never a guess and never the plan's own input-based size. "Provisional" (no risk decision, amber, dashed) and "Risk-approved" (an actual allow decision of the
 * universal risk service, mint, solid) look different, and the badge says it in words. The scanner's rank and score are
 * not a prediction, a probability or an edge; the card says so. Ideas, not recommendations; nothing places an order.
 */
import { useState, type CSSProperties, type ReactNode } from "react";
import { fmtNum, humaniseTag } from "../../../components/ui";
import { fmtDay, fmtPrice } from "../../trading/parts";
import { costsBreakdownText, readCostsBreakdown } from "../desk-trading";
import { stopMethodText, type TradePlan } from "../strategy/trade-plan";
import { STATUS_TEXT, usePlanResponse, usePlanView, type PlanView, type RiskState } from "./plan-view";
import { WaysForwardLine, WaysForwardSection, waysForward } from "./ways-forward";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const numOr = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const UNAVAILABLE = "unavailable";

export const CARD_CAVEAT = "An idea to review, not a recommendation. The score only puts ideas in order; it does not predict a return. The prices come from fixed rules, and an exit price is not guaranteed: a stock can open past it. Nothing is sent to a broker.";

const bearishPlan = (tp: TradePlan) => str(rec(tp.strategy).direction) === "bearish";

const APPROVAL: Record<RiskState, { label: string; tone: string; border: string; bg: string; dashed: boolean }> = {
  provisional: { label: "Not yet checked against your limits", tone: "var(--amber)", border: "var(--amber)", bg: "transparent", dashed: true },
  approved: { label: "Fits your limits", tone: "var(--mint)", border: "var(--mint-line)", bg: "var(--mint-soft)", dashed: false },
  reduce: { label: "Allowed at a smaller size", tone: "var(--amber)", border: "var(--amber)", bg: "transparent", dashed: false },
  block: { label: "Not allowed by your limits", tone: "var(--cp-danger)", border: "var(--cp-danger)", bg: "transparent", dashed: false },
};
const STATUS_TONE: Record<string, string> = { rejected: "var(--cp-danger)", eligible: "var(--mint)", open: "var(--mint)", triggered: "var(--mint)", watch: "var(--amber)" };

const segOf = (tp: TradePlan) => tp.strategy.segment ?? tp.instrument.segment ?? null;
const isOptions = (tp: TradePlan) => segOf(tp) === "options";

// ── the one line ─────────────────────────────────────────────────────────

/** When to enter, in plain words: "if it rises above ₹4,262.26", "at the close ₹…", "on a dip to ₹…". */
export function entryText(tp: TradePlan): string {
  const bear = bearishPlan(tp);
  if (tp.entry.price != null) {
    const p = fmtPrice(tp.entry.price);
    switch (tp.entry.order_type) {
      case "at_close": return `at the close, ${p}`;
      case "stop_trigger": return bear ? `if it falls below ${p}` : `if it rises above ${p}`;
      case "limit_pullback": return bear ? `on a bounce to ${p}` : `on a dip to ${p}`;
      default: return p;
    }
  }
  const net = numOr((tp.entry as Raw).net_premium_rs);
  return net != null ? `at today's option prices (${fmtPrice(Math.abs(net))} ${net < 0 ? "paid" : "received"})` : UNAVAILABLE;
}

/** Where to get out if the idea is wrong: the price only (the reason is in the full card, in plain words). */
export function stopText(tp: TradePlan): string {
  if (tp.stop.price == null && tp.stop.premium_stop == null) return UNAVAILABLE;
  return tp.stop.price != null ? fmtPrice(tp.stop.price) : `option value ${fmtPrice(tp.stop.premium_stop)}`;
}

/** Why the exit is where it is, in plain words (the method itself, e.g. "1.5×ATR", is in Technical details). */
export function stopWhyText(tp: TradePlan): string {
  const m = tp.stop.method;
  if (m === "atr") return "a normal day's price swing below the entry, so ordinary ups and downs do not trigger it";
  if (m === "structural") return "just below a recent low the price held";
  if (m === "capital") return "where the loss reaches your budget for one trade";
  if (m === "premium") return "on the option's own value";
  if (m === "underlying") return "on the stock or index price";
  if (m === "expected_move") return "at the edge of the move the options market expects";
  return "set by the plan's rules";
}

/** The profit targets: prices only. */
export function targetsText(tp: TradePlan): string {
  const ts = tp.targets.filter((t) => t.price != null);
  return ts.length ? ts.map((t) => fmtPrice(t.price)).join(" · ") : UNAVAILABLE;
}

/** "gain about 2× the amount at risk" for a target's R multiple. */
const gainText = (r: number | null | undefined) => (r == null ? null : `gain about ${fmtNum(r, 1)}× the amount at risk`);

const firstMessage = (rs: Array<{ message: string | null }>) => rs.map((r) => r.message).find(Boolean) ?? null;

/** The account's size: the risk service's sizing (account_size), never the plan's own input-based size. */
export function sizeText(v: PlanView): string {
  const a = v.accountSize;
  if (!a) return v.store === "pending" ? "sizing for your account…" : `${UNAVAILABLE}: the plan was not sized for your account`;
  if (a.status === "unavailable") return `${UNAVAILABLE}: ${a.reason ?? "the sizing could not be worked out"}`;
  if (a.status === "not_sizable") return `${UNAVAILABLE}: your risk limits would not allow it (${firstMessage(a.blocking) ?? "see the full card"})`;
  const n = a.lots != null
    ? `${fmtNum(a.lots)} lot${a.lots === 1 ? "" : "s"}${a.lotSize != null ? ` × ${fmtNum(a.lotSize)}` : ""}`
    : a.quantity != null ? `${fmtNum(a.quantity)} shares` : UNAVAILABLE;
  return a.status === "not_confirmed" ? `${n} (too big for your limits as is)` : n;
}

export function riskText(v: PlanView): string {
  const a = v.accountSize;
  const total = a && (a.status === "sized" || a.status === "not_confirmed") ? a.estimatedRisk?.total ?? null : null;
  if (total == null) return UNAVAILABLE;
  return `${fmtPrice(total)} (${a?.riskPctOfEquity != null ? `${fmtNum(a.riskPctOfEquity, 2)}% of your capital` : "share of your capital unavailable"})`;
}

/** The round-trip costs at the account's size (the risk estimate's), else none. */
function costsTotal(v: PlanView): number | null {
  const a = v.accountSize;
  return a && (a.status === "sized" || a.status === "not_confirmed") ? a.estimatedRisk?.costs ?? null : null;
}

/** The plan's own cost card total (at its own size), for the details only. */
function planCostsTotal(tp: TradePlan): number | null {
  const c = rec(tp.costs);
  return numOr(rec(c.breakdown_at_stop).total) ?? numOr(rec(c.breakdown_round_trip_at_entry).total);
}

function horizonText(tp: TradePlan): string {
  const t = rec(rec(tp.exit_plan).time);
  const max = numOr(t.max_sessions) ?? numOr(rec(tp.timeframe).sessions_max);
  if (max != null) return `up to ${fmtNum(max)} trading days`;
  const h = str(rec(tp.timeframe).horizon);
  return h ?? UNAVAILABLE;
}

/** "open risk ₹5,00,000.00 · exposure ₹8,00,000.00 · Banks ₹10,00,000.00 · 10 more positions": the budgets the risk
 *  service found left on your real book now (account_size.portfolio.remaining, plan_sizing._remaining). */
export function budgetsLeftText(remaining: Record<string, unknown>): string {
  const sector = str(remaining.sector);
  const positions = numOr(remaining.positions);
  return `${fmtPrice(numOr(remaining.open_risk_rs))} more you can risk · ${fmtPrice(numOr(remaining.exposure_rs))} more you can invest`
    + (sector ? ` · ${fmtPrice(numOr(remaining.sector_rs))} more in ${sector}` : "")
    + (positions != null ? ` · ${fmtNum(positions)} more trade${positions === 1 ? "" : "s"}` : "");
}

/** "Price data of 18 Oct, before the last completed session 19 Oct" — the plan's own dates, null when current. */
export function staleText(tp: TradePlan): string | null {
  const d = tp.data_as_of ?? {};
  const out: string[] = [];
  const price = d.price ?? null, ref = d.reference_session ?? null;
  if (price && ref && price < ref) out.push(`price data of ${fmtDay(price)}, before the last completed session ${fmtDay(ref)}`);
  const data = d.chain ?? d.fno ?? price;
  const regime = d.regime ?? null;
  if (regime && data && regime < data) out.push(`market regime measured ${fmtDay(regime)}, older than the data of ${fmtDay(data)}`);
  return out.length ? out.join("; ") : null;
}

// ── pieces ───────────────────────────────────────────────────────────────

function Badge({ state, testId }: { state: RiskState; testId: string }) {
  const a = APPROVAL[state];
  return (
    <span data-testid={testId} data-approval={state} className="cp-pill" title="Only your risk limits approve a trade, when you place a paper trade of this plan."
      style={{ color: a.tone, borderColor: a.border, background: a.bg, borderStyle: a.dashed ? "dashed" : "solid", flex: "none" }}>
      {state === "approved" ? "✓ " : state === "block" ? "✕ " : ""}{a.label}
    </span>
  );
}

function Item({ k, v, testId, title }: { k: string; v: string; testId: string; title?: string }) {
  const na = v.startsWith(UNAVAILABLE);
  return (
    <span data-testid={testId} data-unavailable={na ? "true" : undefined} className="cp-num" title={title} style={{ overflowWrap: "anywhere" }}>
      <span style={{ color: "var(--cp-ink-3)" }}>{k} </span>
      <span style={{ color: na ? "var(--cp-ink-3)" : "var(--cp-ink)", fontStyle: na ? "italic" : undefined }}>{v}</span>
    </span>
  );
}

function Section({ title, testId, children }: { title: string; testId: string; children: ReactNode }) {
  return (
    <section data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 4, paddingTop: 8, borderTop: "1px solid var(--cp-line)" }}>
      <h5 className="cp-eyebrow m-0" style={{ fontWeight: 400, fontSize: 9.5 }}>{title}</h5>
      <div className="flex min-w-0 flex-col" style={{ gap: 3, fontSize: 12.5, lineHeight: 1.5, overflowWrap: "anywhere" }}>{children}</div>
    </section>
  );
}

const NA = ({ why }: { why: string }) => <span style={{ ...quiet, fontStyle: "italic" }}>Unavailable: {why}</span>;

function Row({ k, children, testId }: { k: string; children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-wrap" style={{ gap: "0 8px" }}>
      <span style={{ color: "var(--cp-ink-3)", minWidth: 110 }}>{k}</span>
      <span className="min-w-0" style={{ flex: "1 1 200px" }}>{children}</span>
    </div>
  );
}

function RiskCheck({ v }: { v: PlanView }) {
  const d = v.risk.decision;
  if (!d) {
    return (
      <span data-testid="dc-risk-check" data-state="none">
        Not checked yet: your risk limits are checked when you place a paper trade of this plan, so nothing is approved before that.
      </span>
    );
  }
  const size = d.approvedQty != null ? `${fmtNum(d.approvedQty)} shares` : d.approvedLots != null ? `${fmtNum(d.approvedLots)} lot(s) per leg` : null;
  const asked = d.requestedQty != null ? `${fmtNum(d.requestedQty)} shares` : d.requestedLots != null ? `${fmtNum(d.requestedLots)} lot(s)` : null;
  const word = d.outcome === "allow" ? `Fits your limits${size ? `: ${size}` : ""}` : d.outcome === "reduce" ? `Allowed at a smaller size: at most ${size ?? "—"}${asked ? ` (you asked ${asked})` : ""}` : "Not allowed by your limits";
  const er = d.estimatedRisk;
  return (
    <span data-testid="dc-risk-check" data-state={d.outcome} data-stale={v.risk.staleWhy ? "true" : undefined} className="flex flex-col" style={{ gap: 2 }}>
      <span>
        {word}{er?.total != null ? ` · max loss ${fmtPrice(er.total)}` : ""}
        {d.at ? ` · checked ${new Date(d.at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}
      </span>
      {d.reasons.filter((r) => r.severity !== "info").length > 0 && (
        <span data-testid="dc-risk-reasons" style={{ color: d.outcome === "block" ? "var(--cp-danger)" : "var(--cp-ink-2)" }}>
          {d.reasons.filter((r) => r.severity !== "info").map((r) => r.message).join("; ")}
        </span>
      )}
      {v.risk.staleWhy && <span data-testid="dc-risk-stale" style={{ color: "var(--amber)" }}>This check no longer applies: {v.risk.staleWhy}. It is checked again when you place the trade.</span>}
    </span>
  );
}

/**
 * The row's "may be lowered" line (opt-in, `budgets`): the size above assumes no other open trades, so a trade can still
 * be cut by the ones you hold; this says so, with the room left in your limits now and, when they already bind, the size
 * they allow (the route's account_size.portfolio).
 */
function BudgetsLine({ v }: { v: PlanView }) {
  const a = v.accountSize;
  const pf = a?.portfolio ?? null;
  const left = pf
    ? `room left: ${budgetsLeftText(pf.remaining)}`
    : v.store === "pending" ? "room left: reading…"
      : `room left: ${UNAVAILABLE} (${a?.reason ?? (a ? "your open trades could not be read" : "the plan was not sized for your account")})`;
  return (
    <span data-testid="dc-row-budgets" data-binding={pf && pf.reasons.length ? "true" : undefined} className="flex min-w-0 flex-col" style={{ ...quiet, gap: 2, overflowWrap: "anywhere" }}>
      <span>Your other open trades may lower this size · {left}</span>
      {pf && pf.reasons.length > 0 && (
        <span style={{ color: "var(--amber)" }}>With your open trades now: {pf.sizeNow != null ? `at most ${fmtNum(pf.sizeNow)}` : "—"} ({pf.reasons.map((r) => r.message).join("; ")})</span>
      )}
    </span>
  );
}

// ── the full sections ────────────────────────────────────────────────────

/**
 * The plan builder's evidence and warning text, made readable on the card: long floats to two decimals
 * ("Relative volume 1.2966179010676246x" → "1.30x", "1734.5622804300003 Cr" → "1,734.56 Cr"), no internal module
 * names ("(macro_engine.classify_desk_regime, session …)" → "(session …)") and no routes (", GET /api/risk/profile"). The stored text is unchanged: it is part of
 * the plan's content, and so of its id (audit 2026-10-28).
 */
export function readableText(t: string): string {
  return t
    .replace(/\s*\((?:GET|POST) \/api\/[^\s)]*\)/g, "")
    .replace(/,?\s*(?:GET|POST) \/api\/[^\s),;]*/g, "")
    .replace(/\s*\((?:[a-z_]+\.)+[a-z_]+\)/g, "")
    .replace(/\((?:[a-z_]+\.)+[a-z_]+(?: \([^)]*\))?,\s*/g, "(")
    .replace(/\d+\.\d{3,}/g, (m) => fmtNum(Number(m), 2));
}

/** The plan's own "not sized" notes (candidates.py: payoff for 1 share, the gross-only ratio, "Sizing needs …"): stale
 *  once the risk service has sized the plan for your account. */
function unsizedFlag(f: Raw): boolean {
  const m = str(f.message) ?? "";
  return f.code === "sizing_incomplete" || /^(Sizing is incomplete|Sizing needs |Reward : risk is judged before costs here)/.test(m);
}

const SEGMENT_WORDS: Record<string, string> = { cash: "shares", futures: "futures", options: "options", combination: "shares and options" };
const VIEW_WORDS: Record<string, string> = { bullish: "expects a rise", bearish: "expects a fall", neutral: "expects little movement", vol_expansion: "expects a big move", vol_contraction: "expects a quiet market" };
const EVIDENCE_WORDS: Record<string, string> = { regime: "Market mood", trend: "Price trend", relative_strength: "Strength against the market", momentum: "Momentum", volume: "Buying interest (volume)", structure: "Chart pattern" };
const WARNING_WORDS: Record<string, string> = { event: "Upcoming event", liquidity: "Ease of buying and selling", concentration: "Too much in one place", correlation: "Moves with what you hold" };
function verdictText(direction: string | null): string {
  const d = (direction ?? "").toLowerCase();
  if (/support|for|bull|confirm|positive/.test(d)) return "supports the idea";
  if (/against|conflict|bear|negative|contra/.test(d)) return "works against the idea";
  return "neutral";
}

function Sections({ v }: { v: PlanView }) {
  const tp = v.plan;
  const p = tp as unknown as Raw;
  const ins = rec(tp.instrument), strat = rec(tp.strategy), tf = rec(tp.timeframe), entry = rec(tp.entry), stop = rec(tp.stop);
  const size = rec(tp.size), costs = rec(tp.costs), exit = rec(tp.exit_plan);
  const legs = Array.isArray(ins.legs) ? (ins.legs as Raw[]) : [];
  const evidence = Array.isArray(rec(p.evidence).items) ? (rec(p.evidence).items as Raw[]) : null;
  const warnings = Array.isArray(p.warnings) ? (p.warnings as Raw[]) : null;
  const a = v.accountSize;
  const accountSized = a != null && (a.status === "sized" || a.status === "not_confirmed") && (a.quantity != null || a.lots != null);
  const flags = (Array.isArray(p.risk_flags) ? (p.risk_flags as Raw[]) : []).filter((f) => f.code !== "warning" || str(f.message))
    .filter((f) => !(accountSized && unsizedFlag(f)));
  const bd = readCostsBreakdown(costs.breakdown_at_stop ?? costs.breakdown_round_trip_at_entry);
  const opt = rec(exit.options);
  const trailing = rec(exit.trailing), trend = rec(exit.trend), time = rec(exit.time);
  const dates = Object.entries(tp.data_as_of ?? {}).filter(([, d]) => !!d && /^\d{4}-\d{2}-\d{2}/.test(d));
  const reasons = tp.eligibility.reasons.map((r) => r.message || r.code).filter(Boolean) as string[];
  const seg = segOf(tp);
  const primary = tp.targets.find((x) => x.primary);
  return (
    <div data-testid="dc-sections" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <WaysForwardSection ways={waysForward(v)} />
      <Section title="The idea" testId="dc-sec-setup">
        <Row k="What">{str(ins.symbol) ?? UNAVAILABLE} · {SEGMENT_WORDS[seg ?? ""] ?? humaniseTag(seg ?? "type unavailable")}{numOr(ins.lot_size) && numOr(ins.lot_size)! > 1 ? ` · lot ${fmtNum(numOr(ins.lot_size))}` : ""}{str(ins.expiry) ? ` · expiry ${fmtDay(str(ins.expiry))}` : ""}</Row>
        <Row k="Strategy">{str(strat.label) ?? humaniseTag(str(strat.family) ?? "unavailable")}{str(strat.direction) ? ` · ${VIEW_WORDS[str(strat.direction) as string] ?? str(strat.direction)}` : ""}</Row>
        <Row k="Hold for">{numOr(tf.sessions_max) != null ? `up to ${fmtNum(numOr(tf.sessions_max))} trading days` : horizonText(tp)}</Row>
        <Row k="Status" testId="dc-status-text">{STATUS_TEXT[v.status]}{v.statusFromLifecycle ? " (from your paper trades)" : " (no paper trade of it yet)"}</Row>
        {v.status === "rejected" && (
          <Row k="Why not" testId="dc-rejection">{reasons.length ? reasons.join("; ") : "The plan's rules turned it down; no reason was recorded."}</Row>
        )}
      </Section>
      <Section title="When to enter" testId="dc-sec-entry">
        <Row k="Enter">{entryText(tp)}</Row>
        {numOr(entry.valid_for_sessions) != null && <Row k="Waits">up to {fmtNum(numOr(entry.valid_for_sessions))} trading days for that; after that the idea lapses</Row>}
        <Row k="Last close">{fmtPrice(numOr(entry.reference_close))}</Row>
        {isOptions(tp) && legs.length > 0 && (
          <Row k="Positions">{legs.map((l, i) => <span key={i} style={{ display: "block" }}>{str(l.side) === "sell" ? "Sell" : "Buy"} {fmtNum(numOr(l.lots) ?? 1)} lot{(numOr(l.lots) ?? 1) === 1 ? "" : "s"}{numOr(l.lot_size) != null ? ` (${fmtNum(numOr(l.lot_size))} each)` : ""} of the {numOr(l.strike) != null ? `${fmtNum(numOr(l.strike))} ` : ""}{str(l.option_type) ?? str(l.kind) ?? ""} at {fmtPrice(numOr(l.entry_price))}</span>)}</Row>
        )}
      </Section>
      <Section title="When the idea is wrong" testId="dc-sec-stop">
        <Row k="Exit at">{stopText(tp)}</Row>
        <Row k="Why there">{stopWhyText(tp)}</Row>
        <Row k="Wrong if">{str(stop.invalidation) ? readableText(str(stop.invalidation) as string) : <NA why="the plan does not say" />}</Row>
      </Section>
      <Section title="Targets (where to take profit, not forecasts)" testId="dc-sec-targets">
        {tp.targets.length ? tp.targets.map((t, i) => (
          <Row key={t.name} k={`Target ${i + 1}`}>{fmtPrice(t.price)}{gainText(t.r_multiple) ? ` · ${gainText(t.r_multiple)}` : ""}{t.primary ? " · the one a paper trade aims for" : ""}</Row>
        )) : <NA why="the plan has no profit target" />}
      </Section>
      <Section title="Money at risk (your account)" testId="dc-sec-size">
        <Row k="Size" testId="dc-size-text">{sizeText(v)}</Row>
        <Row k="Max loss">{riskText(v)}{a?.estimatedRisk ? <span style={{ ...quiet, display: "block" }}>loss at the exit {fmtPrice(a.estimatedRisk.gross)} + charges {fmtPrice(a.estimatedRisk.costs)} + an allowance for a price gap {fmtPrice(a.estimatedRisk.gapStress)}</span> : null}</Row>
        <Row k="Your capital" testId="dc-equity">
          {v.equity.rs != null
            ? <>{fmtPrice(v.equity.rs)} (your risk profile){a?.perTradeBudgetRs != null ? ` · up to ${fmtPrice(a.perTradeBudgetRs)} at risk on one trade` : ""}</>
            : <NA why={v.equity.error ?? "your capital could not be read"} />}
        </Row>
        {a && a.binding.length > 0 && <Row k="Size limited by" testId="dc-binding">{a.binding.map((r) => r.message).join("; ")}</Row>}
        {a && a.factors.length > 0 && <Row k="Size cut because" testId="dc-factors"><span style={{ color: "var(--amber)" }}>{a.factors.map((r) => r.message).join("; ")}</span></Row>}
        {a?.status === "not_confirmed" && <Row k="Too big as is" testId="dc-not-confirmed"><span style={{ color: "var(--amber)" }}>At this size your limits would cut it again{a.confirmSize != null ? ` (to ${fmtNum(a.confirmSize)})` : ""}: {a.confirmReasons.map((r) => r.message).join("; ")}.</span></Row>}
        {a?.status === "not_sizable" && <Row k="Not allowed" testId="dc-not-sizable"><span style={{ color: "var(--cp-danger)" }}>{a.blocking.map((r) => r.message).join("; ")}</span></Row>}
        {a?.portfolio && (
          <Row k="Other trades" testId="dc-portfolio">
            <span>Your other open trades may lower this size when you place it.</span>
            {a.portfolio.reasons.length > 0 && <span style={{ display: "block", color: "var(--amber)" }}>With your open trades now: {a.portfolio.sizeNow != null ? `at most ${fmtNum(a.portfolio.sizeNow)}` : "—"} ({a.portfolio.reasons.map((r) => r.message).join("; ")})</span>}
            <span data-testid="dc-budgets-left" style={{ ...quiet, display: "block" }}>Room left in your limits: {budgetsLeftText(a.portfolio.remaining)}</span>
          </Row>
        )}
        <Row k="Limits check"><RiskCheck v={v} /></Row>
      </Section>
      <Section title="Charges" testId="dc-sec-costs">
        <Row k="Charges">{costsTotal(v) != null ? `about ${fmtPrice(costsTotal(v))} at your size (brokerage, taxes and slippage, in and out)` : <NA why="no size for your account" />}</Row>
        <Row k="Price gaps" testId="dc-gap">{str(costs.gap_risk) ? readableText(str(costs.gap_risk) as string) : <NA why="this plan was stored before plans carried it" />}</Row>
      </Section>
      <Section title="Why this idea" testId="dc-sec-evidence">
        {evidence ? evidence.map((e) => (
          <Row key={String(e.key)} k={EVIDENCE_WORDS[String(e.key)] ?? str(e.label) ?? String(e.key)} testId={`dc-ev-${String(e.key)}`}>
            {e.status === "ok" ? verdictText(str(e.direction)) : <span style={{ ...quiet, fontStyle: "italic" }}>not checked</span>}
          </Row>
        )) : <NA why="this plan was stored before plans carried their evidence" />}
      </Section>
      <Section title="Things to watch" testId="dc-sec-warnings">
        {warnings ? warnings.map((w) => (
          <Row key={String(w.key)} k={WARNING_WORDS[String(w.key)] ?? str(w.label) ?? String(w.key)} testId={`dc-warn-${String(w.key)}`}>
            <span data-status={String(w.status)} style={{ color: w.status === "flagged" ? "var(--amber)" : undefined }}>
              {w.status === "flagged" ? `⚠ ${readableText(str(w.text) ?? "")}` : w.status === "clear" ? "nothing found" : w.status === "at_entry" ? "checked when you place the trade" : "not checked"}
            </span>
          </Row>
        )) : <NA why="this plan was stored before plans carried their warnings" />}
      </Section>
      <Section title="How it ends" testId="dc-sec-exit">
        <Row k="If wrong">exit at {stopText(tp)}</Row>
        <Row k="If right">{primary ? `take profit at ${fmtPrice(primary.price)}` : UNAVAILABLE}</Row>
        <Row k="Time limit">{numOr(time.max_sessions) != null ? `close it after ${fmtNum(numOr(time.max_sessions))} trading days` : isOptions(tp) ? "at expiry" : <NA why="no time limit on this plan" />}</Row>
        {trailing.enabled === true && <Row k="Protect gains">the exit price moves up as the price rises</Row>}
        {trend.enabled === true && <Row k="Trend exit">close it if the trend turns down</Row>}
        {isOptions(tp) && (
          <Row k="Option value">{opt.status === "ok"
            ? `exit if it falls to ${fmtPrice(numOr(opt.planned_stop))}; take profit at ${fmtPrice(numOr(opt.target_1))}, then ${fmtPrice(numOr(opt.target_2))}`
            : <NA why="no option exit levels were worked out" />}</Row>
        )}
      </Section>
      <details data-testid="dc-sec-audit" style={{ paddingTop: 8, borderTop: "1px solid var(--cp-line)" }}>
        <summary className="cp-eyebrow" style={{ fontSize: 9.5, cursor: "pointer" }}>Technical details</summary>
        <div className="flex min-w-0 flex-col" style={{ gap: 3, fontSize: 12, lineHeight: 1.5, overflowWrap: "anywhere", paddingTop: 6, color: "var(--cp-ink-2)" }}>
          <Row k="Stop method">{stopMethodText(tp.stop)}{str(stop.rationale) ? ` · ${readableText(str(stop.rationale) as string)}` : ""}</Row>
          {numOr(stop.premium_stop) != null && <Row k="Premium stop">{fmtPrice(numOr(stop.premium_stop))} a unit, on the whole structure</Row>}
          <Row k="Entry order">{str(entry.order_type) ?? "—"}{str(entry.order_text) ? ` · ${str(entry.order_text)}` : ""}{str(entry.logic) ? ` · ${str(entry.logic)}` : ""}</Row>
          <Row k="Targets in R">{tp.targets.length ? tp.targets.map((t) => `${humaniseTag(t.name)} ${fmtPrice(t.price)}${t.r_multiple != null ? ` (${fmtNum(t.r_multiple, 2)}R)` : ""}${t.rule ? ` — ${t.rule}` : ""}`).join(" · ") : "—"}</Row>
          <Row k="R (risk a unit)">{tp.r_per_unit != null ? fmtPrice(tp.r_per_unit) : UNAVAILABLE}</Row>
          {evidence && <Row k="Evidence" testId="dc-ev-raw">{evidence.map((e) => `${str(e.label) ?? String(e.key)}: ${readableText(str(e.text) ?? "—")}${str(e.as_of) ? ` (${fmtDay(str(e.as_of))})` : ""}`).join(" · ")}</Row>}
          {flags.length > 0 && <Row k="Other flags" testId="dc-other-flags">{flags.map((f) => str(f.message) ?? str(f.code)).filter(Boolean).map((t) => readableText(t as string)).join("; ")}</Row>}
          <Row k="Sized by">{a?.basis ?? "—"}{a?.limitsVersion ? ` · limits ${a.limitsVersion}` : ""}{v.equity.basis ? ` · ${v.equity.basis}` : ""}{v.equity.label ? ` · ${v.equity.label}` : ""}</Row>
          {size.status === "complete" && (
            <Row k="The plan's own sizing" testId="dc-own-size">{numOr(size.lots) != null ? `${fmtNum(numOr(size.lots))} lot(s)` : `${fmtNum(numOr(size.quantity))} ${seg === "cash" ? "shares" : "units"}`} at {readableText(str(size.equity_basis) ?? "the plan's inputs")}{numOr(size.risk_rs) != null ? `, risk ${fmtPrice(numOr(size.risk_rs))}` : ""}: a what-if, not what the risk service approves for your account.</Row>
          )}
          {v.risk.decision && <Row k="Risk decision">{v.risk.decision.decisionId.slice(0, 8)} · {v.risk.decision.policyVersion ?? "policy —"} · limits {v.risk.decision.limitsVersion ?? "—"}{v.risk.decision.estimatedRisk ? ` · stop ${fmtPrice(v.risk.decision.estimatedRisk.gross)}, costs ${fmtPrice(v.risk.decision.estimatedRisk.costs)}, gap stress ${fmtPrice(v.risk.decision.estimatedRisk.gapStress)}` : ""}</Row>}
          <Row k="Cost card">{planCostsTotal(tp) != null ? `${fmtPrice(planCostsTotal(tp))} · ${costsBreakdownText(bd, (n) => fmtPrice(n)) ?? ""}` : "—"}{str(costs.basis) ? ` · ${str(costs.basis)} (the plan's own size)` : ""}{str(costs.model) ? ` · ${str(costs.model)}` : ""}{Array.isArray(costs.excluded) && costs.excluded.length ? ` · not included: ${(costs.excluded as unknown[]).map(String).join(", ")}` : ""}</Row>
          <Row k="Exit rules">trailing {trailing.enabled === true ? `${fmtNum(numOr(trailing.atr_multiple), 1)}×ATR` : "off"} · trend {trend.enabled === true ? `close below ${str(trend.ma) ?? "the average"} ${numOr(trend.period) ?? ""}` : "off"}{isOptions(tp) && opt.status === "ok" ? ` · option ${str(opt.kind) ?? ""} ${fmtPrice(numOr(opt.entry))} a unit${str(rec(opt.greek_review).review_when) ? ` · review when ${str(rec(opt.greek_review).review_when)}` : ""}` : ""}</Row>
          <Row k="Data as of" testId="dc-data-asof">{dates.length ? dates.map(([k, d]) => `${k.replace(/_/g, " ")} ${fmtDay(d)}`).join(" · ") : "—"}</Row>
          <Row k="Rule versions">{tp.rules_version || "—"}{str(p.strategy_rules_version) ? ` · ${str(p.strategy_rules_version)}` : ""}{str(p.calculation_version) ? ` · ${str(p.calculation_version)}` : ""}</Row>
          <Row k="Plan" testId="dc-plan-id">{tp.plan_id}{tp.version != null ? ` · version ${tp.version}` : ""}{str(p.created_at) ? ` · stored ${fmtDay(str(p.created_at))}` : ""}</Row>
        </div>
      </details>
    </div>
  );
}

// ── the card ─────────────────────────────────────────────────────────────

export function DecisionCardView({ v, variant, testId = "dc", budgets = false }: { v: PlanView; variant: "row" | "full"; testId?: string; budgets?: boolean }) {
  const [open, setOpen] = useState(false);
  const tp = v.plan;
  const a = APPROVAL[v.risk.state];
  const stale = staleText(tp);
  const shown = variant === "full" || open;
  const costs = costsTotal(v);
  return (
    <div data-testid={testId} data-plan-id={tp.plan_id} data-row-plan-id={v.rowPlan.plan_id} data-variant={variant} data-approval={v.risk.state} data-status={v.status}
      data-store={v.store} data-size-status={v.accountSize?.status ?? "none"}
      className="flex min-w-0 flex-col"
      style={{ gap: 6, padding: "8px 10px", borderRadius: 10, border: `1px ${a.dashed ? "dashed" : "solid"} ${a.border}`, background: "var(--bg-1)" }}>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px" }}>
        <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Trade plan</span>
        <span data-testid="dc-status" data-status={v.status} className="cp-pill" style={{ color: STATUS_TONE[v.status] ?? "var(--cp-ink-2)", flex: "none" }}>{STATUS_TEXT[v.status]}</span>
        <Badge state={v.risk.state} testId="dc-approval" />
        {stale && <span data-testid="dc-stale" className="cp-pill" style={{ color: "var(--amber)", flex: "none" }} title={stale}>Old data</span>}
      </div>
      <div data-testid="dc-line" className="flex min-w-0 flex-wrap" style={{ gap: "2px 12px", fontSize: 12.5, lineHeight: 1.5 }}>
        <Item k="Enter" v={entryText(tp)} testId="dc-entry" />
        <Item k="Exit if wrong" v={stopText(tp)} testId="dc-stop" />
        <Item k="Targets" v={targetsText(tp)} testId="dc-targets" />
        <Item k="Size" v={sizeText(v)} testId="dc-size" title="Sized for your account by your risk limits (assuming no other open trades)" />
        <Item k="Max loss" v={riskText(v)} testId="dc-risk" title="If it hits the exit: the loss, the charges and an allowance for a price gap, at your size" />
        <Item k="Charges" v={costs != null ? `about ${fmtPrice(costs)}` : UNAVAILABLE} testId="dc-costs" />
        <Item k="Hold for" v={horizonText(tp)} testId="dc-horizon" />
      </div>
      {budgets && variant === "row" && <BudgetsLine v={v} />}
      {variant === "row" && !open && <WaysForwardLine ways={waysForward(v)} />}
      {v.changed && (
        <span data-testid="dc-changed" role="note" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>
          Plan changed: version {v.changed.toVersion ?? "?"} replaces version {v.changed.fromVersion ?? "?"} that this list was built with. The figures shown are the newer ones.
        </span>
      )}
      {stale && <span data-testid="dc-stale-text" style={{ ...quiet, color: "var(--amber)" }}>Old data: {stale}.</span>}
      {v.store === "unread" && <span data-testid="dc-store-unread" style={quiet}>The saved plan could not be read just now: the status and the limits check shown are this list's copy.</span>}
      {shown && <Sections v={v} />}
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px" }}>
        {variant === "row" && (
          <button type="button" className="cp-chip" data-testid="dc-toggle" aria-expanded={open} onClick={() => setOpen((x) => !x)} style={{ padding: "2px 10px", fontSize: 11.5 }}>
            {open ? "Hide plan details" : "Plan details"}
          </button>
        )}
        <span data-testid="dc-action" data-enabled={v.gate ? "false" : "true"} style={{ fontSize: 12, lineHeight: 1.5, color: v.gate ? "var(--amber)" : "var(--cp-ink-3)" }}>
          {v.gate ? `Paper trade off: ${v.gate}` : v.risk.state === "reduce" && v.risk.decision ? "Paper trade: your limits allow only the smaller size above." : "Paper trade: available. Your limits are checked when you place it."}
        </span>
      </div>
      <span data-testid="dc-caveat" style={{ ...quiet, fontSize: 11 }}>{CARD_CAVEAT}</span>
    </div>
  );
}

/** The card for a row's plan. `recordsShownPlan`: see usePlanView. `budgets`: a row also says it may be reduced by
 *  portfolio limits at submission, with the budgets left (Market Overview's Top AI ideas). */
export function DecisionCard({ plan, variant, testId, recordsShownPlan = false, budgets = false }: {
  plan: TradePlan; variant: "row" | "full"; testId?: string; recordsShownPlan?: boolean; budgets?: boolean;
}) {
  const v = usePlanView(plan, { recordsShownPlan });
  return v ? <DecisionCardView v={v} variant={variant} testId={testId} budgets={budgets} /> : null;
}

/** "No trade plan" for an idea whose route sent `trade_plan: null`, with the route's reason. */
export function NoPlan({ reason, testId = "dc-none" }: { reason: string | null | undefined; testId?: string }) {
  return (
    <span data-testid={testId} role="note" style={{ ...quiet, padding: "6px 10px", borderRadius: 10, border: "1px dashed var(--line-2)" }}>
      No trade plan for this idea{reason ? `: ${reason}` : " (no entry with a stop on the loss side)"}. Nothing can be paper traded from it.
    </span>
  );
}

/** The full card of the plan a paper trade cites, read by id (the paper-trade record). */
export function DecisionCardById({ planId, testId = "dc-trade", variant = "full", budgets = false }: { planId: string; testId?: string; variant?: "row" | "full"; budgets?: boolean }) {
  const q = usePlanResponse(planId);
  if (q.isPending) return <span data-testid={`${testId}-loading`} style={quiet}>Reading trade plan {planId}…</span>;
  if (!q.data) return <span data-testid={`${testId}-missing`} style={quiet}>Trade plan {planId} could not be read{q.error ? "" : " (the route sent no plan)"}.</span>;
  return <DecisionCard plan={q.data.plan} variant={variant} testId={testId} recordsShownPlan budgets={budgets} />;
}
