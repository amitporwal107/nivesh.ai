/**
 * Trade Desk › Chart Analysis › Live chart — the PAPER ORDER TICKET (PAPER ONLY), the right column of the owner's design.
 *
 *   the plan        ?tp=<plan_id>, else the stored AI watchlist day's plan for the symbol, else a cached ideas board's (the
 *                   caller resolves it in one fast read and never waits on the ~16 s ideas board)
 *                   GET /api/desk/trade-plans/{id}: levels, targets with their R, and `account_size`
 *   QUANTITY        `account_size.quantity`: the risk service's own sizing for this account (plan_sizing.py). Never a browser
 *                   formula, and there is NO risk slider (the owner's decision of 28 Oct): the profile is the only risk
 *                   setting, shown read-only (GET /api/risk/profile per_trade_risk_pct) with the way to Risk Desk › Policy & runtime
 *   risk at stop,   `account_size.estimated_risk` (gross at the stop, costs of the round trip); position value = that
 *   costs           quantity × the plan's entry
 *   Place           POST /api/desk/paper-trades (planCashBody, the body the Strategy Lab ticket sends, Idempotency-Key) → the
 *                   risk service's allow / reduce / block, in words (answerOf, shared with the Strategy Lab ticket)
 *   footer          the live feed's age (useLiveMeta), the day's loss and the open risk against the profile's limits
 *
 * The entry policy chips are the design's three; each is said to be a paper-engine rule or not. The engine has break above,
 * pull back to (a touch of the level) and at once, and fills on end-of-day bars. Paper only; no broker order is sent.
 */
import type { ReactNode } from "react";
import { Btn, LoadingBlock, fmtINR, fmtNum, fmtPct } from "../../../../components/ui";
import { useLiveMeta } from "../../../../lib/useLiveQuotes";
import { fmtPrice } from "../../../trading/parts";
import { usePlanResponse, usePlanView } from "../../decision/plan-view";
import { useSubmitPaperTrade, type NewPaperTrade } from "../../desk-trading";
import { planCashBody } from "../../PlanPaperTrade";
import { RiskReduceOffer } from "../../RiskReduce";
import { useRiskProfile } from "../../risk-profile";
import { answerOf, type Answer } from "./NewTrade";
import { linkBtn, quiet } from "./parts";

const mono = { fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase" as const };

/** The design's entry policies, and the paper engine's rule each one is (null: not an engine rule). */
const POLICIES: Array<{ label: string; rule: string | null; why: string }> = [
  { label: "Retest of range", rule: null, why: "Not a paper-engine rule yet: a retest needs an intraday close back above the trigger, and the engine fills on end-of-day bars." },
  { label: "Range touch", rule: "pullback_to", why: "The engine's pull back to: filled when a session's low reaches the entry." },
  { label: "Next open", rule: null, why: "Not a paper-engine rule yet: the engine has no fill at the next session's open." },
];
const RULE_CHIP: Record<string, string> = { break_above: "Break above", at_once: "At once" };
const RULE_TRIGGER: Record<string, (e: string) => string> = {
  break_above: (e) => `a session's high at or above ${e}`,
  pullback_to: (e) => `a session's low at or below ${e}`,
  at_once: () => "none: filled at once, inside the last session's range",
};

function Row({ k, v, id, sub }: { k: string; v: ReactNode; id: string; sub?: ReactNode }) {
  return (
    <div className="flex min-w-0 items-baseline justify-between" style={{ gap: 10, padding: "6px 0", borderTop: "1px solid var(--cp-line)" }}>
      <span style={{ ...mono, color: "var(--cp-ink-3)", flexShrink: 0 }}>{k}</span>
      <span className="flex min-w-0 flex-col items-end" style={{ gap: 2, textAlign: "right" }}>
        <span data-testid={`lc-ticket-${id}`} className="cp-num" style={{ fontSize: 13, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{v}</span>
        {sub && <span style={{ ...quiet, fontSize: 11 }}>{sub}</span>}
      </span>
    </div>
  );
}

function Shell({ symbol, children, head }: { symbol: string; children: ReactNode; head?: ReactNode }) {
  return (
    <section data-testid="lc-ticket" className="flex min-w-0 flex-col" style={{ gap: 10, padding: "14px 16px", borderRadius: 16, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: 6 }}>
        <h3 className="cp-eyebrow m-0" style={{ color: "var(--cp-ink-2)" }}>Paper order ticket</h3>
        <span data-testid="lc-ticket-paper-only" style={{ ...mono, color: "var(--amber)" }}>Paper only</span>
      </div>
      {head ?? <span className="cp-num" style={{ fontSize: 15, fontWeight: 600 }}>{symbol}</span>}
      {children}
    </section>
  );
}

/** "Feed fresh (0.5s). Daily loss 0.0% of 2.0%. Open risk 1.8% of 3.0%. No broker order is sent." from the real reads. */
export function TicketFooter() {
  const meta = useLiveMeta();
  const prof = useRiskProfile();
  const feed = meta.mode === "live" && !meta.stale
    ? `Feed fresh${meta.ageSeconds != null ? ` (${fmtNum(meta.ageSeconds, meta.ageSeconds < 10 ? 1 : 0)}s)` : ""}.`
    : meta.mode === "live" ? "Feed stale." : meta.mode === "closed" ? "Feed: market closed." : meta.mode === "delayed" ? "Feed delayed." : meta.mode === "expired" ? "Feed: Kite login needed." : "Feed not connected.";
  let daily = "Daily loss unknown.";
  let open = "Open risk unknown.";
  if (prof.data) {
    const lim = prof.data.profile.limits;
    const live = prof.data.live;
    const dayPnl = live?.day.pnlRs ?? null;
    const dayBase = live?.day.startEquityRs ?? null;
    if (dayPnl != null && dayBase != null && dayBase > 0) {
      daily = `Daily loss ${fmtPct(Math.max(0, -dayPnl) / dayBase * 100, { digits: 1 })} of ${fmtPct(lim.daily_loss_pct ?? null, { digits: 1 })}.`;
    }
    const risk = live?.open.riskRs ?? null;
    const eq = live?.equityRs ?? null;
    if (risk != null && eq != null && eq > 0) open = `Open risk ${fmtPct(risk / eq * 100, { digits: 1 })} of ${fmtPct(lim.max_open_risk_pct ?? null, { digits: 1 })}.`;
  } else if (prof.isPending) {
    daily = "Daily loss: reading.";
    open = "Open risk: reading.";
  }
  return (
    <p data-testid="lc-ticket-footer" className="m-0" style={{ ...quiet, fontSize: 11.5 }}>
      {feed} {daily} {open} No broker order is sent.
    </p>
  );
}

export function LiveTicket({ symbol, planId, planPending, noPlanWhy, onIdeas, onRiskPolicy, signalLabel }: {
  symbol: string; planId: string | null; planPending: boolean; noPlanWhy?: string | null; onIdeas: () => void; onRiskPolicy: () => void; signalLabel: string | null;
}) {
  const q = usePlanResponse(planId);
  const prof = useRiskProfile();
  const perTrade = prof.data?.profile.limits.per_trade_risk_pct ?? null;
  const riskRow = (
    <Row k="Risk per trade" id="risk" v={prof.isPending ? "…" : perTrade != null ? fmtPct(perTrade, { digits: 2 }) : "unknown"}
      sub={<>From your risk profile, read only. <button type="button" data-testid="lc-ticket-risk-link" style={linkBtn} onClick={onRiskPolicy}>Risk Desk › Policy &amp; runtime ›</button></>} />
  );
  if (!planId) {
    return (
      <Shell symbol={symbol}>
        {planPending ? <LoadingBlock label="Looking for this stock's plan" rows={2} /> : (
          <span data-testid="lc-ticket-none" style={{ ...quiet, fontSize: 13, color: "var(--cp-ink-2)" }}>
            No plan for {symbol} today, so there is no order to place{noPlanWhy ? ` (${noPlanWhy})` : ""}: a ticket&apos;s quantity is the risk service&apos;s size for an idea&apos;s plan.{" "}
            <button type="button" data-testid="lc-ticket-ideas" style={linkBtn} onClick={onIdeas}>AI Scanner › Ranked candidates ›</button>
          </span>
        )}
        {riskRow}
        <TicketFooter />
      </Shell>
    );
  }
  if (q.isPending) return <Shell symbol={symbol}><LoadingBlock label={`Reading trade plan ${planId}`} rows={3} /></Shell>;
  if (!q.data) {
    return (
      <Shell symbol={symbol}>
        <span data-testid="lc-ticket-missing" role="alert" style={{ ...quiet, color: "var(--amber)" }}>Trade plan {planId} could not be read, so nothing can be placed from it.</span>
        <TicketFooter />
      </Shell>
    );
  }
  return <TicketBody symbol={symbol} resp={q.data} riskRow={riskRow} signalLabel={signalLabel} />;
}

function TicketBody({ symbol, resp, riskRow, signalLabel }: { symbol: string; resp: NonNullable<ReturnType<typeof usePlanResponse>["data"]>; riskRow: ReactNode; signalLabel: string | null }) {
  const v = usePlanView(resp.plan, { recordsShownPlan: true });
  const submit = useSubmitPaperTrade();
  const tp = v?.plan ?? resp.plan;
  const a = v?.accountSize ?? resp.accountSize ?? null;
  const rule = tp.entry.desk_entry_rule ?? "";
  const entry = tp.entry.price ?? null;
  const stop = tp.stop.price ?? null;
  const t1 = tp.targets[0] ?? null;
  const t2 = tp.targets[1] ?? null;
  const shares = a?.status === "sized" && a.quantity != null && a.quantity >= 1 && (a.unit ?? "shares") === "shares" ? a.quantity : null;
  const setup = (tp as { setup?: { bucket?: unknown; signal_date?: unknown } }).setup ?? {};
  const source: NewPaperTrade["source"] = {
    kind: "scanner",
    ...(typeof setup.bucket === "string" && setup.bucket ? { bucket: setup.bucket } : {}),
    ...(typeof setup.signal_date === "string" && setup.signal_date ? { signal_date: setup.signal_date } : {}),
  };
  const body = shares != null && !v?.gate ? planCashBody(tp, symbol, shares, source) : null;
  const segment = tp.strategy.segment ?? tp.instrument.segment ?? "cash";
  const dir = (tp.strategy.direction ?? "").toLowerCase();
  const direction = dir === "bullish" || dir === "long" ? "LONG" : dir === "bearish" || dir === "short" ? "SHORT" : (dir || "direction not recorded").toUpperCase();

  let answer: Answer | null = null;
  if (submit.isError) answer = answerOf(submit.error, symbol);
  else if (submit.isSuccess) {
    const id = submit.data.tradeId;
    const qty = submit.variables?.quantity;
    answer = submit.data.replayed
      ? { kind: "duplicate", text: `This order was already recorded${id ? ` (paper trade ${id})` : ""}: not added twice.`, reasons: [] }
      : { kind: "allow", text: `Allowed: ${qty != null ? `${fmtNum(qty)} ` : ""}${symbol} shares placed as a paper order${id ? ` (${id})` : ""}. It fills only when its entry rule is met on an end-of-day bar.`, reasons: (submit.data.risk?.reasons ?? []).map((x) => x.message) };
  }
  const tone = answer?.kind === "allow" ? "var(--mint)" : answer?.kind === "reduce" || answer?.kind === "duplicate" || answer?.kind === "unfillable" ? "var(--amber)" : "var(--cp-danger)";
  const head = (
    <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
      <span data-testid="lc-ticket-symbol" className="cp-num" style={{ fontSize: 15, fontWeight: 600 }}>{symbol}</span>
      <span data-testid="lc-ticket-direction" style={{ ...mono, padding: "2px 7px", borderRadius: 5, color: "var(--mint)", border: "1px solid var(--mint-line)" }}>{direction}</span>
      <span data-testid="lc-ticket-from" style={{ ...quiet, fontSize: 11.5 }}>from {signalLabel ? `${signalLabel} · ` : ""}plan {tp.plan_id}</span>
    </div>
  );

  if (segment !== "cash") {
    return (
      <Shell symbol={symbol} head={head}>
        <span data-testid="lc-ticket-structure" style={quiet}>A {segment} plan is placed with its legs in Trade Desk › Strategy Lab, where the risk service sizes it in lots per leg. This ticket places share orders.</span>
        {riskRow}
        <TicketFooter />
      </Shell>
    );
  }

  const value = shares != null && entry != null ? shares * entry : null;
  const chips = [...POLICIES, ...(RULE_CHIP[rule] ? [{ label: RULE_CHIP[rule], rule, why: "This plan's entry rule." }] : [])];
  return (
    <Shell symbol={symbol} head={head}>
      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span style={{ ...mono, color: "var(--cp-ink-3)" }}>Entry policy</span>
        <div className="flex flex-wrap" style={{ gap: 6 }} role="group" aria-label="Entry policy (set by the plan)">
          {chips.map((c) => {
            const on = c.rule != null && c.rule === rule;
            return (
              <span key={c.label} data-testid="lc-ticket-policy" data-label={c.label} data-on={on ? "true" : "false"} data-engine={c.rule ? "true" : "false"} title={c.why}
                className="cp-chip" aria-pressed={on}
                style={{ padding: "3px 9px", fontSize: 11.5, opacity: c.rule ? 1 : 0.55, color: on ? "var(--mint)" : undefined, borderColor: on ? "var(--mint-line)" : undefined }}>
                {c.label}
              </span>
            );
          })}
        </div>
        <span style={{ ...quiet, fontSize: 11 }}>Set by the plan. The paper engine has break above, pull back to (a range touch) and at once, on end-of-day bars; a retest or a next-open fill is not an engine rule yet.</span>
      </div>
      {riskRow}
      <Row k="Entry (range)" id="entry" v={fmtPrice(entry)} sub="One level: the plan sets no range." />
      <Row k="Trigger" id="trigger" v={RULE_TRIGGER[rule]?.(fmtPrice(entry)) ?? "not recorded"} sub="Checked on end-of-day bars." />
      <Row k="Stop" id="stop" v={fmtPrice(stop)} />
      <Row k="T1 / T2" id="targets" v={`${fmtPrice(t1?.price ?? null)} / ${t2 ? fmtPrice(t2.price ?? null) : "—"}`} />
      <Row k="Quantity" id="qty" v={<span data-qty={shares ?? ""} data-status={a?.status ?? ""}>{v?.store === "pending" ? "…" : shares != null ? `${fmtNum(shares)} sh` : "unavailable"}</span>}
        sub={shares != null ? `The risk service's size for your account (account_size)${a?.perTradeBudgetRs != null ? `, per-trade budget ${fmtINR(a.perTradeBudgetRs)}` : ""}.` : (a?.reason ?? "The risk service has not sized this plan for your account.")} />
      <Row k="Position value" id="value" v={value != null ? fmtINR(value) : "—"} />
      <Row k="Risk at stop" id="risk-at-stop" v={fmtINR(a?.estimatedRisk?.gross ?? null)} sub={a?.estimatedRisk?.total != null ? `${fmtINR(a.estimatedRisk.total)} with costs and the gap stress` : undefined} />
      <Row k="Planned R:R to T1" id="rr" v={t1?.r_multiple != null ? `${fmtNum(t1.r_multiple, 2)} : 1` : "—"} />
      <Row k="Est. costs" id="costs" v={fmtINR(a?.estimatedRisk?.costs ?? null)} sub="Round trip at the stop (desk cost model)." />
      <p data-testid="lc-ticket-not-a-fill" className="m-0" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
        Entry is not a fill. The order fills only when the entry policy and trigger are met. A stop does not cap loss in a gap.
      </p>
      {v?.gate ? (
        <span data-testid="lc-ticket-blocked" role="note" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--amber)" }}>Placing is off: {v.gate}</span>
      ) : (
        <Btn variant="primary" data-testid="lc-ticket-place" disabled={!body || submit.isPending || submit.isSuccess} onClick={() => { if (body) submit.mutate(body); }}>
          {submit.isSuccess ? "Placed" : submit.isPending ? "Placing…" : "Place paper order"}
        </Btn>
      )}
      {answer && (
        <div data-testid="lc-ticket-answer" data-outcome={answer.kind} role={answer.kind === "allow" ? "status" : "alert"} className="flex min-w-0 flex-col"
          style={{ gap: 6, padding: "10px 12px", borderRadius: 10, border: `1px solid ${tone}`, background: "var(--bg-2)" }}>
          <span data-testid="lc-ticket-answer-text" style={{ fontSize: 13, lineHeight: 1.5, color: tone }}>{answer.text}</span>
          {answer.reasons.length > 0 && (
            <ul className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, fontSize: 12.5, color: "var(--cp-ink-2)" }}>
              {answer.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          )}
          {answer.kind === "reduce" && submit.variables && (
            <RiskReduceOffer error={submit.error} testId="lc-ticket-reduce" label={(n) => `Accept ${fmtNum(n)}?`}
              onAccept={(n) => { const last = submit.variables; if (last) submit.mutate({ ...last, quantity: n }); }} />
          )}
        </div>
      )}
      <TicketFooter />
    </Shell>
  );
}
