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

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const numOr = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const UNAVAILABLE = "unavailable";

export const CARD_CAVEAT = "An idea for review, not a recommendation. The scanner's rank and score order ideas; they are not a prediction, a probability or an edge. Levels are rule-based and hypothetical; a stop is a level, not a guaranteed price. Nothing is sent to a broker.";

const ORDER_SHORT: Record<string, string> = { at_close: "at the close", stop_trigger: "break above", limit_pullback: "pull back to", at_premium: "at the premiums" };

const APPROVAL: Record<RiskState, { label: string; tone: string; border: string; bg: string; dashed: boolean }> = {
  provisional: { label: "Provisional · no risk decision yet", tone: "var(--amber)", border: "var(--amber)", bg: "transparent", dashed: true },
  approved: { label: "Risk-approved", tone: "var(--mint)", border: "var(--mint-line)", bg: "var(--mint-soft)", dashed: false },
  reduce: { label: "Risk: smaller size only", tone: "var(--amber)", border: "var(--amber)", bg: "transparent", dashed: false },
  block: { label: "Risk: blocked", tone: "var(--cp-danger)", border: "var(--cp-danger)", bg: "transparent", dashed: false },
};
const STATUS_TONE: Record<string, string> = { rejected: "var(--cp-danger)", eligible: "var(--mint)", open: "var(--mint)", triggered: "var(--mint)", watch: "var(--amber)" };

const segOf = (tp: TradePlan) => tp.strategy.segment ?? tp.instrument.segment ?? null;
const isOptions = (tp: TradePlan) => segOf(tp) === "options";

// ── the one line ─────────────────────────────────────────────────────────

export function entryText(tp: TradePlan): string {
  if (tp.entry.price != null) return `${fmtPrice(tp.entry.price)} (${ORDER_SHORT[tp.entry.order_type ?? ""] ?? tp.entry.order_type ?? "order type unavailable"})`;
  const net = numOr((tp.entry as Raw).net_premium_rs);
  return net != null ? `net premium ${fmtPrice(Math.abs(net))} ${net < 0 ? "debit" : "credit"} (${ORDER_SHORT.at_premium})` : UNAVAILABLE;
}

export function stopText(tp: TradePlan): string {
  if (tp.stop.price == null && tp.stop.premium_stop == null) return UNAVAILABLE;
  const where = tp.stop.price != null ? fmtPrice(tp.stop.price) : `premium ${fmtPrice(tp.stop.premium_stop)}`;
  return `${where} (${stopMethodText(tp.stop)})`;
}

export function targetsText(tp: TradePlan): string {
  const ts = tp.targets.filter((t) => t.price != null);
  return ts.length ? ts.map((t) => `${fmtPrice(t.price)}${t.r_multiple != null ? ` (${fmtNum(t.r_multiple, 2)}R)` : ""}`).join(" · ") : UNAVAILABLE;
}

const firstMessage = (rs: Array<{ message: string | null }>) => rs.map((r) => r.message).find(Boolean) ?? null;

/** The account's size: the risk service's sizing (account_size), never the plan's own input-based size. */
export function sizeText(v: PlanView): string {
  const a = v.accountSize;
  if (!a) return v.store === "pending" ? "sizing for your account…" : `${UNAVAILABLE}: the plan was not sized for your account`;
  if (a.status === "unavailable") return `${UNAVAILABLE}: ${a.reason ?? "the sizing could not be worked out"}`;
  if (a.status === "not_sizable") return `${UNAVAILABLE}: the risk service would refuse it (${firstMessage(a.blocking) ?? "see the sizing"})`;
  const n = a.lots != null
    ? `${fmtNum(a.lots)} lot${a.lots === 1 ? "" : "s"}${a.lotSize != null ? ` × ${fmtNum(a.lotSize)}` : ""}`
    : a.quantity != null ? `${fmtNum(a.quantity)} shares` : UNAVAILABLE;
  return a.status === "not_confirmed" ? `${n} (not allowed as is)` : n;
}

export function riskText(v: PlanView): string {
  const a = v.accountSize;
  const total = a && (a.status === "sized" || a.status === "not_confirmed") ? a.estimatedRisk?.total ?? null : null;
  if (total == null) return UNAVAILABLE;
  return `${fmtPrice(total)} (${a?.riskPctOfEquity != null ? `${fmtNum(a.riskPctOfEquity, 2)}% of equity` : "% of equity unavailable"})`;
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
  if (max != null) return `≤ ${fmtNum(max)} sessions`;
  const h = str(rec(tp.timeframe).horizon);
  return h ?? UNAVAILABLE;
}

/** "open risk ₹5,00,000.00 · exposure ₹8,00,000.00 · Banks ₹10,00,000.00 · 10 more positions": the budgets the risk
 *  service found left on your real book now (account_size.portfolio.remaining, plan_sizing._remaining). */
export function budgetsLeftText(remaining: Record<string, unknown>): string {
  const sector = str(remaining.sector);
  const positions = numOr(remaining.positions);
  return `open risk ${fmtPrice(numOr(remaining.open_risk_rs))} · exposure ${fmtPrice(numOr(remaining.exposure_rs))}`
    + (sector ? ` · ${sector} ${fmtPrice(numOr(remaining.sector_rs))}` : "")
    + (positions != null ? ` · ${fmtNum(positions)} more positions` : "");
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
    <span data-testid={testId} data-approval={state} className="cp-pill" title="Approval comes only from the universal risk service's decision on a paper-trade submission of this plan."
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
        Risk check: no decision yet. The account's risk service (universal-risk-v1) decides when a paper trade of this plan is
        submitted; there is no preview, so nothing is approved before that.
      </span>
    );
  }
  const size = d.approvedQty != null ? `${fmtNum(d.approvedQty)} shares` : d.approvedLots != null ? `${fmtNum(d.approvedLots)} lot(s) per leg` : null;
  const asked = d.requestedQty != null ? `${fmtNum(d.requestedQty)} shares` : d.requestedLots != null ? `${fmtNum(d.requestedLots)} lot(s)` : null;
  const word = d.outcome === "allow" ? `Allowed${size ? ` ${size}` : ""}` : d.outcome === "reduce" ? `Smaller size only: at most ${size ?? "—"}${asked ? ` (asked ${asked})` : ""}` : "Blocked";
  const er = d.estimatedRisk;
  return (
    <span data-testid="dc-risk-check" data-state={d.outcome} data-stale={v.risk.staleWhy ? "true" : undefined} className="flex flex-col" style={{ gap: 2 }}>
      <span>
        Risk check: {word}{er?.total != null ? ` · estimated risk ${fmtPrice(er.total)} (stop ${fmtPrice(er.gross)}, costs ${fmtPrice(er.costs)}, gap stress ${fmtPrice(er.gapStress)})` : ""}
        {d.at ? ` · ${new Date(d.at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}
      </span>
      {d.reasons.filter((r) => r.severity !== "info").length > 0 && (
        <span data-testid="dc-risk-reasons" style={{ color: d.outcome === "block" ? "var(--cp-danger)" : "var(--cp-ink-2)" }}>
          {d.reasons.filter((r) => r.severity !== "info").map((r) => r.message).join("; ")}
        </span>
      )}
      {v.risk.staleWhy && <span data-testid="dc-risk-stale" style={{ color: "var(--amber)" }}>No longer decides this plan: {v.risk.staleWhy}. The next submission is decided again.</span>}
      <span style={quiet}>Decision {d.decisionId.slice(0, 8)} · {d.policyVersion ?? "policy —"} · limits {d.limitsVersion ?? "—"}</span>
    </span>
  );
}

/**
 * The row's "may be reduced" line (opt-in, `budgets`): the size above is the risk service's on an EMPTY book, so a
 * submission can still be cut by your open positions; this says so, with the budgets left on your real book now and,
 * when they already bind, the size they allow (the route's account_size.portfolio).
 */
function BudgetsLine({ v }: { v: PlanView }) {
  const a = v.accountSize;
  const pf = a?.portfolio ?? null;
  const left = pf
    ? `left: ${budgetsLeftText(pf.remaining)}`
    : v.store === "pending" ? "budgets left: reading…"
      : `budgets left: ${UNAVAILABLE} (${a?.reason ?? (a ? "the risk service did not read your open book" : "the plan was not sized for your account")})`;
  return (
    <span data-testid="dc-row-budgets" data-binding={pf && pf.reasons.length ? "true" : undefined} className="flex min-w-0 flex-col" style={{ ...quiet, gap: 2, overflowWrap: "anywhere" }}>
      <span>May be reduced by portfolio limits at submission · {left}</span>
      {pf && pf.reasons.length > 0 && (
        <span style={{ color: "var(--amber)" }}>With your open positions now: {pf.sizeNow != null ? `at most ${fmtNum(pf.sizeNow)}` : "—"} ({pf.reasons.map((r) => r.message).join("; ")})</span>
      )}
    </span>
  );
}

// ── the full sections ────────────────────────────────────────────────────

function Sections({ v }: { v: PlanView }) {
  const tp = v.plan;
  const p = tp as unknown as Raw;
  const ins = rec(tp.instrument), strat = rec(tp.strategy), tf = rec(tp.timeframe), entry = rec(tp.entry), stop = rec(tp.stop);
  const size = rec(tp.size), costs = rec(tp.costs), exit = rec(tp.exit_plan);
  const legs = Array.isArray(ins.legs) ? (ins.legs as Raw[]) : [];
  const evidence = Array.isArray(rec(p.evidence).items) ? (rec(p.evidence).items as Raw[]) : null;
  const warnings = Array.isArray(p.warnings) ? (p.warnings as Raw[]) : null;
  const flags = (Array.isArray(p.risk_flags) ? (p.risk_flags as Raw[]) : []).filter((f) => f.code !== "warning" || str(f.message));
  const bd = readCostsBreakdown(costs.breakdown_at_stop ?? costs.breakdown_round_trip_at_entry);
  const a = v.accountSize;
  const opt = rec(exit.options);
  const trailing = rec(exit.trailing), trend = rec(exit.trend), time = rec(exit.time);
  const dates = Object.entries(tp.data_as_of ?? {}).filter(([, d]) => !!d && /^\d{4}-\d{2}-\d{2}/.test(d));
  const reasons = tp.eligibility.reasons.map((r) => r.message || r.code).filter(Boolean) as string[];
  return (
    <div data-testid="dc-sections" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <Section title="Setup" testId="dc-sec-setup">
        <Row k="Instrument">{str(ins.symbol) ?? UNAVAILABLE} · {humaniseTag(segOf(tp) ?? "segment unavailable")}{numOr(ins.lot_size) && numOr(ins.lot_size)! > 1 ? ` · lot ${fmtNum(numOr(ins.lot_size))}` : ""}{str(ins.expiry) ? ` · expiry ${fmtDay(str(ins.expiry))}` : ""}</Row>
        <Row k="Strategy">{str(strat.label) ?? humaniseTag(str(strat.family) ?? "unavailable")} · {str(strat.direction) ?? "direction unavailable"}</Row>
        <Row k="Timeframe">{str(tf.horizon) ?? UNAVAILABLE}{numOr(tf.sessions_max) != null ? ` · up to ${fmtNum(numOr(tf.sessions_max))} sessions` : ""}</Row>
        <Row k="Status" testId="dc-status-text">{STATUS_TEXT[v.status]}{v.statusFromLifecycle ? " (from your paper trades)" : " (the plan's own state; no paper trade cites it)"}</Row>
      </Section>
      <Section title="Entry" testId="dc-sec-entry">
        <Row k="Trigger">{entryText(tp)}</Row>
        <Row k="Order">{str(entry.order_text) ?? UNAVAILABLE}{numOr(entry.valid_for_sessions) != null ? ` · waits up to ${fmtNum(numOr(entry.valid_for_sessions))} sessions` : ""}</Row>
        <Row k="Reference close">{fmtPrice(numOr(entry.reference_close))}</Row>
        {isOptions(tp) && legs.length > 0 && (
          <Row k="Legs">{legs.map((l, i) => <span key={i} style={{ display: "block" }}>{str(l.side) === "sell" ? "Sell" : "Buy"} {fmtNum(numOr(l.lots) ?? 1)} × {fmtNum(numOr(l.lot_size))} {numOr(l.strike) != null ? fmtNum(numOr(l.strike)) : ""} {str(l.option_type) ?? str(l.kind) ?? ""} at {fmtPrice(numOr(l.entry_price))}</span>)}</Row>
        )}
        {str(entry.logic) && <span style={quiet}>{str(entry.logic)}</span>}
      </Section>
      <Section title="Stop and invalidation" testId="dc-sec-stop">
        <Row k="Stop">{stopText(tp)}</Row>
        <Row k="Why there">{str(stop.rationale) ?? <NA why="the plan records no rationale" />}</Row>
        <Row k="Invalidation">{str(stop.invalidation) ?? <NA why="the plan records no invalidation" />}</Row>
        {numOr(stop.premium_stop) != null && <Row k="Premium stop">{fmtPrice(numOr(stop.premium_stop))} a unit, on the whole structure</Row>}
      </Section>
      <Section title="Targets (scenario levels, not forecasts)" testId="dc-sec-targets">
        {tp.targets.length ? tp.targets.map((t) => (
          <Row key={t.name} k={humaniseTag(t.name)}>{fmtPrice(t.price)}{t.r_multiple != null ? ` · ${fmtNum(t.r_multiple, 2)}R` : " · R unavailable"}{t.primary ? " · the target a paper trade records" : ""}{t.rule ? <span style={{ ...quiet, display: "block" }}>{t.rule}</span> : null}</Row>
        )) : <NA why="the plan has no target on the profit side" />}
        <Row k="R (risk a unit)">{tp.r_per_unit != null ? fmtPrice(tp.r_per_unit) : UNAVAILABLE}</Row>
      </Section>
      <Section title="Size and risk (your account)" testId="dc-sec-size">
        <Row k="Size" testId="dc-size-text">{sizeText(v)}</Row>
        <Row k="Sized by">{a?.basis ?? <NA why="the plan route did not size this plan for your account" />}</Row>
        {a?.perTradeBudgetRs != null && <Row k="Per-trade budget">{fmtPrice(a.perTradeBudgetRs)} of {fmtPrice(a.equityRs)} paper equity{a.limitsVersion ? ` · limits ${a.limitsVersion}` : ""}</Row>}
        {a && a.binding.length > 0 && <Row k="Limited by" testId="dc-binding">{a.binding.map((r) => r.message).join("; ")}</Row>}
        {a && a.factors.length > 0 && <Row k="Regime / volatility" testId="dc-factors"><span style={{ color: "var(--amber)" }}>{a.factors.map((r) => r.message).join("; ")}</span></Row>}
        {a?.status === "not_confirmed" && <Row k="Not allowed as is" testId="dc-not-confirmed"><span style={{ color: "var(--amber)" }}>Submitted at this size the risk service cuts it again{a.confirmSize != null ? ` (to ${fmtNum(a.confirmSize)})` : ""}: {a.confirmReasons.map((r) => r.message).join("; ")}.</span></Row>}
        {a?.status === "not_sizable" && <Row k="Refused" testId="dc-not-sizable"><span style={{ color: "var(--cp-danger)" }}>{a.blocking.map((r) => r.message).join("; ")}</span></Row>}
        <Row k="Risk at the stop">{riskText(v)}{a?.estimatedRisk ? <span style={{ ...quiet, display: "block" }}>stop {fmtPrice(a.estimatedRisk.gross)} + costs {fmtPrice(a.estimatedRisk.costs)} + gap stress {fmtPrice(a.estimatedRisk.gapStress)}</span> : null}</Row>
        <Row k="Equity basis" testId="dc-equity">
          {v.equity.rs != null
            ? <>{fmtPrice(v.equity.rs)} paper equity (risk profile{v.equity.effectiveFrom ? `, effective ${fmtDay(v.equity.effectiveFrom.slice(0, 10))}` : ""}){v.equity.label ? ` · ${v.equity.label}` : ""}{v.equity.basis ? <span style={{ ...quiet, display: "block" }}>{v.equity.basis}</span> : null}</>
            : <NA why={v.equity.error ?? "no equity basis"} />}
        </Row>
        {a?.portfolio && (
          <Row k="At submission" testId="dc-portfolio">
            <span>{a.portfolioNote ?? "May be reduced by portfolio limits at submission."}</span>
            {a.portfolio.reasons.length > 0 && <span style={{ display: "block", color: "var(--amber)" }}>With your open positions now: {a.portfolio.sizeNow != null ? `at most ${fmtNum(a.portfolio.sizeNow)}` : "—"} ({a.portfolio.reasons.map((r) => r.message).join("; ")})</span>}
            <span data-testid="dc-budgets-left" style={{ ...quiet, display: "block" }}>
              Left in your risk profile: {budgetsLeftText(a.portfolio.remaining)}
            </span>
          </Row>
        )}
        {size.status === "complete" && (
          <Row k="The plan's own sizing" testId="dc-own-size">
            <span style={quiet}>{numOr(size.lots) != null ? `${fmtNum(numOr(size.lots))} lot(s)` : `${fmtNum(numOr(size.quantity))} ${segOf(tp) === "cash" ? "shares" : "units"}`} at {str(size.equity_basis) ?? "the plan's inputs"}{numOr(size.risk_rs) != null ? `, risk ${fmtPrice(numOr(size.risk_rs))}` : ""}: a what-if, not what the risk service approves for your account.</span>
          </Row>
        )}
        <Row k="Risk check"><RiskCheck v={v} /></Row>
      </Section>
      <Section title="Costs and gap risk" testId="dc-sec-costs">
        <Row k="Estimated costs">{costsTotal(v) != null ? `${fmtPrice(costsTotal(v))} at your size, entry to the stop (the risk estimate's)` : <NA why="no size for your account" />}</Row>
        <Row k="Cost card">{planCostsTotal(tp) != null ? `${fmtPrice(planCostsTotal(tp))} · ${costsBreakdownText(bd, (n) => fmtPrice(n)) ?? ""}` : <NA why="the cost card could not price this plan" />}{str(costs.basis) ? <span style={{ ...quiet, display: "block" }}>{str(costs.basis)} (the plan's own size); {str(costs.model) ?? "cost model —"}</span> : null}</Row>
        <Row k="Not included">{Array.isArray(costs.excluded) && costs.excluded.length ? (costs.excluded as unknown[]).map(String).join(", ") : "—"}</Row>
        <Row k="Gap and slippage" testId="dc-gap">{str(costs.gap_risk) ?? <NA why="this plan was stored before plans carried it" />}</Row>
      </Section>
      <Section title="Evidence" testId="dc-sec-evidence">
        {evidence ? evidence.map((e) => (
          <Row key={String(e.key)} k={str(e.label) ?? String(e.key)} testId={`dc-ev-${String(e.key)}`}>
            {e.status === "ok"
              ? <>{str(e.text) ?? "—"}{str(e.direction) ? <span style={quiet}> · {str(e.direction)}</span> : null}{str(e.as_of) ? <span style={quiet}> · {fmtDay(str(e.as_of))}</span> : null}</>
              : <NA why={str(e.text) ?? "not computed"} />}
          </Row>
        )) : <NA why="this plan was stored before plans carried their evidence" />}
      </Section>
      <Section title="Warnings" testId="dc-sec-warnings">
        {warnings ? warnings.map((w) => (
          <Row key={String(w.key)} k={str(w.label) ?? String(w.key)} testId={`dc-warn-${String(w.key)}`}>
            <span data-status={String(w.status)} style={{ color: w.status === "flagged" ? "var(--amber)" : undefined }}>
              {w.status === "flagged" ? "⚠ " : w.status === "clear" ? "Clear · " : w.status === "at_entry" ? "Checked at entry · " : "Unavailable · "}{str(w.text) ?? ""}
            </span>
          </Row>
        )) : <NA why="this plan was stored before plans carried their warnings" />}
        {flags.length > 0 && <Row k="Other flags">{flags.map((f) => str(f.message) ?? str(f.code)).filter(Boolean).join("; ")}</Row>}
      </Section>
      <Section title="Exit plan" testId="dc-sec-exit">
        <Row k="Stop">{stopText(tp)}</Row>
        <Row k="Target">{(() => { const t = tp.targets.find((x) => x.primary); return t ? `${fmtPrice(t.price)} (${humaniseTag(t.name)})` : UNAVAILABLE; })()}</Row>
        <Row k="Time">{numOr(time.max_sessions) != null ? `closed at the close of session ${fmtNum(numOr(time.max_sessions))} held` : isOptions(tp) ? "at expiry" : <NA why="no time exit on this plan" />}</Row>
        <Row k="Trailing">{trailing.enabled === true ? `on: ${fmtNum(numOr(trailing.atr_multiple), 1)}×ATR` : "off (an opt-in research rule)"}</Row>
        <Row k="Trend">{trend.enabled === true ? `on: close below ${str(trend.ma) ?? "the average"} ${numOr(trend.period) ?? ""}` : "off (an opt-in research rule)"}</Row>
        {isOptions(tp) && (
          <Row k="Premium levels">{opt.status === "ok"
            ? `${str(opt.kind) ?? ""} ${fmtPrice(numOr(opt.entry))} a unit · stop ${fmtPrice(numOr(opt.planned_stop))} · T1 ${fmtPrice(numOr(opt.target_1))} · T2 ${fmtPrice(numOr(opt.target_2))}${str(rec(opt.greek_review).review_when) ? ` · review when ${str(rec(opt.greek_review).review_when)}` : ""}`
            : <NA why={str(opt.reason) ?? "the levels engine gave no answer"} />}</Row>
        )}
      </Section>
      <Section title="Audit" testId="dc-sec-audit">
        <Row k="Data as of" testId="dc-data-asof">{dates.length ? dates.map(([k, d]) => `${k.replace(/_/g, " ")} ${fmtDay(d)}`).join(" · ") : <NA why="no data dates on the plan" />}</Row>
        <Row k="Rule versions">{tp.rules_version || "—"}{str(p.strategy_rules_version) ? ` · ${str(p.strategy_rules_version)}` : ""}{str(p.calculation_version) ? ` · ${str(p.calculation_version)}` : ""}</Row>
        <Row k="Plan">{tp.plan_id}{tp.version != null ? ` · version ${tp.version}` : ""}{str(p.created_at) ? ` · stored ${fmtDay(str(p.created_at))}` : ""}</Row>
        {v.status === "rejected" && (
          <Row k="Why rejected" testId="dc-rejection">{reasons.length ? reasons.join("; ") : "The plan's rules rejected it; no reason was recorded."}</Row>
        )}
      </Section>
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
        {stale && <span data-testid="dc-stale" className="cp-pill" style={{ color: "var(--amber)", flex: "none" }} title={stale}>Stale data</span>}
        <span data-testid="dc-plan-id" className="cp-num" style={{ ...quiet, fontSize: 11 }}>{tp.plan_id}{tp.version != null ? ` · v${tp.version}` : ""}</span>
      </div>
      <div data-testid="dc-line" className="flex min-w-0 flex-wrap" style={{ gap: "2px 12px", fontSize: 12.5, lineHeight: 1.5 }}>
        <Item k="Entry" v={entryText(tp)} testId="dc-entry" />
        <Item k="Stop" v={stopText(tp)} testId="dc-stop" />
        <Item k="Targets" v={targetsText(tp)} testId="dc-targets" />
        <Item k="Size" v={sizeText(v)} testId="dc-size" title="The risk service's sizing for your account: what a submission is approved at when no portfolio limit binds" />
        <Item k="Risk" v={riskText(v)} testId="dc-risk" title="Stop + costs + gap stress at your size (the risk service's estimate), as a % of your paper equity" />
        <Item k="Est. costs" v={costs != null ? fmtPrice(costs) : UNAVAILABLE} testId="dc-costs" />
        <Item k="Horizon" v={horizonText(tp)} testId="dc-horizon" />
      </div>
      {budgets && variant === "row" && <BudgetsLine v={v} />}
      {v.changed && (
        <span data-testid="dc-changed" role="note" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>
          Plan changed: version {v.changed.toVersion ?? "?"} ({v.changed.toId}) replaces version {v.changed.fromVersion ?? "?"} ({v.changed.fromId}) that this row was built with. The figures shown are version {v.changed.toVersion ?? "?"}'s.
        </span>
      )}
      {stale && <span data-testid="dc-stale-text" style={{ ...quiet, color: "var(--amber)" }}>Stale: {stale}.</span>}
      {v.store === "unread" && <span data-testid="dc-store-unread" style={quiet}>The plan store was not read: status and risk decision are this row's copy only.</span>}
      {shown && <Sections v={v} />}
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px" }}>
        {variant === "row" && (
          <button type="button" className="cp-chip" data-testid="dc-toggle" aria-expanded={open} onClick={() => setOpen((x) => !x)} style={{ padding: "2px 10px", fontSize: 11.5 }}>
            {open ? "Hide plan details" : "Plan details"}
          </button>
        )}
        <span data-testid="dc-action" data-enabled={v.gate ? "false" : "true"} style={{ fontSize: 12, lineHeight: 1.5, color: v.gate ? "var(--amber)" : "var(--cp-ink-3)" }}>
          {v.gate ? `Paper trade off: ${v.gate}` : v.risk.state === "reduce" && v.risk.decision ? "Paper trade: the risk service allows only the smaller size above." : "Paper trade: available; the risk service decides on submission."}
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
export function DecisionCardById({ planId, testId = "dc-trade" }: { planId: string; testId?: string }) {
  const q = usePlanResponse(planId);
  if (q.isPending) return <span data-testid={`${testId}-loading`} style={quiet}>Reading trade plan {planId}…</span>;
  if (!q.data) return <span data-testid={`${testId}-missing`} style={quiet}>Trade plan {planId} could not be read{q.error ? "" : " (the route sent no plan)"}.</span>;
  return <DecisionCard plan={q.data.plan} variant="full" testId={testId} recordsShownPlan />;
}
