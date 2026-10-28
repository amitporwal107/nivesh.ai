/**
 * Trade Desk › Strategy Lab (the owner's workbench, PLAN.md "1-REVISED"): Build a trade (the ticket, the F&O builder, the
 * Strategy Builder) and Backtest & validation.
 *
 *   Ticket          ?tp=<plan_id> (from an idea), GET /api/desk/trade-plans/{id}: the decision card and the risk service's
 *                   `account_size` for this account. The size is that number: no slider and no size field (REVIEW_lab_v5
 *                   §(d) 2). POST /api/desk/paper-trades (Idempotency-Key) answers allow / reduce ("Accept N?") / block, a
 *                   duplicate (409) or an impossible fill (422 entry_not_tradable), each in plain words.
 *   Wizard          the owner's four steps (lab/Wizard.tsx): choose template, configure, review & adjust, validate &
 *                   paper-trade, on the catalog, the chain, payoff-v2, the margin calculator and the risk service
 *   Strategy Builder  unchanged (plans, candidates, "Paper trade this"), under "From an idea"
 *   Backtest        GET /api/strategy-builder/strategies, POST …/strategies/{id}/backtest: provenance (universe basis and rule,
 *                   code version, data to, cost model, slippage sweep) and the survivorship warning for an index universe
 *
 * Ideas, not recommendations; paper only, nothing is sent to a broker.
 */
import { Suspense, lazy, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { StrategyWizard } from "./lab/Wizard";
import { SafeWidget } from "@/components/shared/SafeWidget";
import { Btn, LoadingBlock, fmtINR, fmtNum, fmtPct } from "../../../../components/ui";
import { useSavedStrategies } from "../../../workspace/strategies";
import { useStrategyTemplates } from "../../../fnolab/governance-data";
import { fmtDay, fmtPrice } from "../../../trading/parts";
import { DecisionCardView } from "../../decision/DecisionCard";
import { usePlanResponse, usePlanView } from "../../decision/plan-view";
import { ENTRY_RULE_SHORT, riskReduceOf, useSubmitPaperTrade, writeProblem, type EntryRule, type NewPaperTrade } from "../../desk-trading";
import { detailOf, orderReasons, readReasons } from "../../risk-controls";
import { RiskReduceOffer } from "../../RiskReduce";
import { planCashBody } from "../../PlanPaperTrade";
import type { TradePlan } from "../../strategy/trade-plan";
import { survivorshipBiased, useBacktestRun, type BacktestRun } from "./trade-desk-data";
import { PAPER_ONLY, Panel, linkBtn, quiet } from "./parts";

const StrategyBuilder = lazy(() => import("../../strategy/StrategyBuilder"));
const FnoTab = lazy(() => import("../../FnoTab"));

/** A part of the page with its own error boundary and loading state; `desk-panel-<id>` as the shell named them. */
function Part({ id, name, children }: { id: string; name: string; children: ReactNode }) {
  return (
    <div data-testid={`desk-panel-${id}`} className="cp-desk-host flex min-w-0 flex-col">
      <SafeWidget key={id} name={`Trading desk · ${name}`}>
        <Suspense fallback={<LoadingBlock label={`Loading ${name}`} rows={3} />}>{children}</Suspense>
      </SafeWidget>
    </div>
  );
}

// ── the ticket ───────────────────────────────────────────────────────────

/** The answer to a submission, in plain words: what the route said, and what was (not) recorded. */
type Answer =
  | { kind: "allow"; text: string; reasons: string[] }
  | { kind: "reduce"; text: string; reasons: string[] }
  | { kind: "block"; text: string; reasons: string[] }
  | { kind: "duplicate" | "unfillable" | "error"; text: string; reasons: string[] };

function answerOf(error: unknown, symbol: string): Answer {
  const d = detailOf(error);
  const code = typeof d.code === "string" ? d.code : null;
  const message = typeof d.message === "string" ? d.message : null;
  const reasons = orderReasons(readReasons(d.reasons)).map((r) => r.message);
  if (code === "risk_reduce") {
    const r = riskReduceOf(error);
    const from = r?.requestedQty ?? r?.requestedLots;
    const to = r?.approvedQty ?? r?.approvedLots;
    return { kind: "reduce", text: `Reduced ${from ?? "?"} → ${to ?? "?"}${r?.approvedLots != null && r.approvedQty == null ? " lots per leg" : ""}. Nothing was recorded.`, reasons };
  }
  if (code === "risk_blocked") return { kind: "block", text: "Blocked by the risk service. Nothing was recorded.", reasons: reasons.length ? reasons : message ? [message] : [] };
  if (code === "duplicate_open_trade" || code === "duplicate_open_structure") {
    const id = typeof d.existing_trade_id === "string" ? d.existing_trade_id : null;
    return { kind: "duplicate", text: `${symbol} is already open${id ? ` (paper trade ${id})` : ""}: not added twice.`, reasons: message ? [message] : [] };
  }
  const plain = writeProblem(error);
  if (code === "entry_not_tradable" || code === "entry_unverifiable" || /entry_not_tradable|entry_unverifiable/.test(plain)) {
    return { kind: "unfillable", text: `Not recorded: ${message ?? plain}`, reasons: [] };
  }
  return { kind: "error", text: `Not recorded: ${plain}`, reasons: [] };
}

function TicketBody({ tp: rowPlan, source }: { tp: TradePlan; source: NewPaperTrade["source"] }) {
  const v = usePlanView(rowPlan, { recordsShownPlan: true });
  const submit = useSubmitPaperTrade();
  const tp = v?.plan ?? rowPlan;
  const symbol = tp.instrument.symbol ?? "—";
  const segment = tp.strategy.segment ?? tp.instrument.segment ?? null;
  const a = v?.accountSize ?? null;
  const shares = a?.status === "sized" && a.quantity != null && a.quantity >= 1 && (a.unit ?? "shares") === "shares" ? a.quantity : null;
  const body = shares != null && !v?.gate && tp.instrument.symbol ? planCashBody(tp, tp.instrument.symbol, shares, source) : null;
  const rule = (tp.entry.desk_entry_rule ?? "at_once") as EntryRule;

  if (segment && segment !== "cash") {
    return (
      <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
        {v && <DecisionCardView v={v} variant="full" testId="td-ticket-card" />}
        <span data-testid="td-ticket-structure-note" style={quiet}>
          A {segment} plan is recorded with its legs: build it in the Strategy Builder below (“Paper trade this”), where the risk service sizes it in lots per leg. This ticket records share trades.
        </span>
      </div>
    );
  }

  let answer: Answer | null = null;
  if (submit.isError) answer = answerOf(submit.error, symbol);
  else if (submit.isSuccess) {
    const r = submit.data.risk;
    const id = submit.data.tradeId;
    const qty = submit.variables?.quantity;
    answer = submit.data.replayed
      ? { kind: "duplicate", text: `This submission was already recorded${id ? ` (paper trade ${id})` : ""}: not added twice.`, reasons: [] }
      : { kind: "allow", text: `Allowed: ${qty != null ? `${fmtNum(qty)} ` : ""}${symbol} shares recorded as a paper trade${id ? ` (${id})` : ""}.`, reasons: (r?.reasons ?? []).map((x) => x.message) };
  }
  const tone = answer?.kind === "allow" ? "var(--mint)" : answer?.kind === "reduce" || answer?.kind === "duplicate" || answer?.kind === "unfillable" ? "var(--amber)" : "var(--cp-danger)";

  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      {v ? <DecisionCardView v={v} variant="full" testId="td-ticket-card" /> : <LoadingBlock label="Reading the plan" rows={2} />}
      <div data-testid="td-ticket-size" data-qty={shares ?? ""} data-status={a?.status ?? ""} className="flex min-w-0 flex-col" style={{ gap: 4, padding: "12px 14px", borderRadius: 12, border: "1px solid var(--mint-line)", background: "var(--bg-2)" }}>
        <span className="cp-eyebrow">Size for your account</span>
        <span className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.1 }}>
          {v?.store === "pending" ? "…" : shares != null ? `${fmtNum(shares)} shares` : "unavailable"}
        </span>
        <span style={quiet}>
          {shares != null
            ? `The risk service’s own size (account_size) on your paper equity${a?.equityRs != null ? ` of ${fmtINR(a.equityRs)}` : ""}: per-trade budget${a?.perTradeBudgetRs != null ? ` ${fmtINR(a.perTradeBudgetRs)}` : ""}, position and liquidity caps, the stop, costs and a 1% gap. ${a?.portfolioNote ?? "May be reduced by portfolio limits at submission."}`
            : a ? `${a.reason ?? `The risk service did not size this plan (${a.status}).`}` : "The risk service has not sized this plan for your account, so nothing can be recorded from here."}
        </span>
        <span style={quiet}>Your risk profile is the only risk setting; change it on Risk Desk › Controls &amp; profile.</span>
      </div>
      <span style={quiet}>
        At the plan’s levels: <span data-testid="td-ticket-rule" data-rule={rule}>{ENTRY_RULE_SHORT[rule] ?? rule}</span>{tp.entry.price != null ? ` at ${fmtPrice(tp.entry.price)}` : ""}. Plan {tp.plan_id}.
      </span>
      {v?.gate ? (
        <span data-testid="td-ticket-blocked" role="note" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--amber)" }}>Recording is off: {v.gate}</span>
      ) : (
        <span className="flex flex-wrap items-center" style={{ gap: 10 }}>
          <Btn variant="primary" data-testid="td-ticket-submit" disabled={!body || submit.isPending || submit.isSuccess} onClick={() => { if (body) submit.mutate(body); }}>
            {submit.isSuccess ? "Recorded" : submit.isPending ? "Recording…" : shares != null ? `Record paper trade · ${fmtNum(shares)} shares` : "Record paper trade"}
          </Btn>
          <span style={quiet}>{PAPER_ONLY}</span>
        </span>
      )}
      {answer && (
        <div data-testid="td-ticket-answer" data-outcome={answer.kind} role={answer.kind === "allow" ? "status" : "alert"} className="flex min-w-0 flex-col"
          style={{ gap: 6, padding: "10px 12px", borderRadius: 10, border: `1px solid ${tone}`, background: "var(--bg-2)" }}>
          <span data-testid="td-ticket-answer-text" style={{ fontSize: 13, lineHeight: 1.5, color: tone }}>{answer.text}</span>
          {answer.reasons.length > 0 && (
            <ul className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, fontSize: 12.5, color: "var(--cp-ink-2)" }}>
              {answer.reasons.map((r, i) => <li key={i} data-testid="td-ticket-reason">{r}</li>)}
            </ul>
          )}
          {answer.kind === "block" && <span style={quiet}>The risk controls are on Risk Desk › Controls &amp; profile. A kill switch blocks new paper entries only, and only an admin clears it.</span>}
          {answer.kind === "reduce" && submit.variables && (
            <RiskReduceOffer error={submit.error} testId="td-ticket-reduce" label={(n) => `Accept ${fmtNum(n)}?`}
              onAccept={(n) => { const last = submit.variables; if (last) submit.mutate({ ...last, quantity: n }); }} />
          )}
        </div>
      )}
    </div>
  );
}

export function Ticket({ planId, source, onOverview }: { planId: string | null; source: NewPaperTrade["source"] | null; onOverview: () => void }) {
  const q = usePlanResponse(planId);
  let body: ReactNode;
  if (!planId) {
    body = (
      <span data-testid="td-ticket-none" style={{ ...quiet, fontSize: 13, color: "var(--cp-ink-2)" }}>
        No idea open. Open one from <button type="button" data-testid="td-ticket-overview" style={linkBtn} onClick={onOverview}>Market Overview › Top AI ideas</button>: its plan comes here with the risk service’s size for your account. Or build a structure below.
      </span>
    );
  } else if (q.isPending) body = <LoadingBlock label={`Reading trade plan ${planId}`} rows={2} />;
  else if (!q.data) body = <span data-testid="td-ticket-missing" role="alert" style={{ ...quiet, color: "var(--amber)" }}>Trade plan {planId} could not be read{q.error ? ` (${writeProblem(q.error)})` : ""}. Nothing can be recorded from it.</span>;
  else {
    const tp = q.data.plan;
    const setup = (tp as { setup?: { bucket?: unknown; signal_date?: unknown } }).setup ?? {};
    const fallback: NewPaperTrade["source"] = {
      kind: "scanner",
      ...(typeof setup.bucket === "string" && setup.bucket ? { bucket: setup.bucket } : {}),
      ...(typeof setup.signal_date === "string" && setup.signal_date ? { signal_date: setup.signal_date } : {}),
    };
    body = <TicketBody tp={tp} source={source ?? fallback} />;
  }
  return <Panel title="Ticket · from an idea" note="sized by the risk service" testId="td-ticket">{body}</Panel>;
}

// ── backtest ─────────────────────────────────────────────────────────────

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

function Provenance({ r }: { r: BacktestRun }) {
  const p = r.provenance;
  const biased = survivorshipBiased(p.universeBasis);
  const pit = p.universeBasis === "point_in_time";
  const universe = `${p.universeRuleVersion ?? p.universeRef ?? "universe not recorded"}${pit ? " (point-in-time, no survivorship)" : p.universeBasis ? ` (${p.universeBasis.replace(/_/g, " ")})` : ""}`;
  return (
    <div data-testid="td-bt-result" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,120px),1fr))", gap: "8px 12px", fontSize: 12.5 }}>
        {[
          ["Trades", fmtNum(r.tradeCount), "trades"],
          ["Return", fmtPct(r.totalReturnPct, { signed: true, digits: 2 }), "return"],
          ["Win rate", fmtPct(r.winRate, { digits: 1 }), "win"],
          ["Max drawdown", fmtPct(r.maxDrawdownPct, { digits: 2 }), "dd"],
        ].map(([k, v, id]) => (
          <div key={id} className="flex flex-col" style={{ gap: 2 }}><span className="cp-eyebrow" style={{ fontSize: 9 }}>{k}</span><span data-testid={`td-bt-${id}`} className="cp-num">{v}</span></div>
        ))}
      </div>
      <p data-testid="td-bt-provenance" className="m-0 cp-num" style={{ fontSize: 12, lineHeight: 1.6, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
        <span data-testid="td-bt-universe">{universe}</span> · code <span data-testid="td-bt-code">{p.codeVersion ?? "not recorded"}</span> · data to <span data-testid="td-bt-data">{p.dataTo ? fmtDay(p.dataTo) : "not recorded"}</span> · cost model <span data-testid="td-bt-cost">{p.costModel ?? "not recorded"}</span>
        {p.slippagePctPerSide != null ? ` · slippage ${fmtNum(p.slippagePctPerSide, 2)}% a side` : ""}{p.entryTiming ? ` · entry ${p.entryTiming}` : ""}{p.schema ? ` · ${p.schema}` : ""}
      </p>
      {biased && (
        <span data-testid="td-bt-survivorship" role="note" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--amber)", padding: "8px 12px", borderRadius: 8, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
          Survivorship bias: {p.universeWarning ?? "this index was applied with its latest constituents, so stocks that left it are missing from the past."}
        </span>
      )}
      {p.notRecorded.length > 0 && <span data-testid="td-bt-not-recorded" style={quiet}>Not recorded on this run: {p.notRecorded.join(", ")}.</span>}
      {r.sweep && (
        <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Slippage sweep</span>
          <div className="cp-scroll" style={{ maxWidth: "100%", overflowX: "auto" }}>
            <table data-testid="td-bt-sweep" style={{ width: "100%", minWidth: 420, borderCollapse: "collapse", fontSize: 12.5 }}>
              <thead><tr className="cp-mono-note" style={{ textAlign: "left" }}><th style={{ padding: "4px 8px" }}>Slippage a side</th><th style={{ padding: "4px 8px", textAlign: "right" }}>Net P/L</th><th style={{ padding: "4px 8px", textAlign: "right" }}>Per trade</th><th style={{ padding: "4px 8px", textAlign: "right" }}>Return</th></tr></thead>
              <tbody>
                {r.sweep.rows.map((s) => (
                  <tr key={s.bps} data-testid="td-bt-sweep-row" data-bps={s.bps} style={{ borderTop: "1px solid var(--cp-line)" }}>
                    <td className="cp-num" style={{ padding: "4px 8px" }}>{fmtNum(s.bps / 100, 2)}%</td>
                    <td className="cp-num" style={{ padding: "4px 8px", textAlign: "right" }}>{fmtINR(s.netPnlRs, { signed: true })}</td>
                    <td className="cp-num" style={{ padding: "4px 8px", textAlign: "right" }}>{fmtINR(s.expectancyRs, { signed: true })}</td>
                    <td className="cp-num" style={{ padding: "4px 8px", textAlign: "right" }}>{fmtPct(s.totalReturnPct, { signed: true, digits: 2 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {r.sweep.basis && <span style={{ ...quiet, fontSize: 11 }}>{r.sweep.basis}.</span>}
        </div>
      )}
      <span style={{ ...quiet, fontSize: 11 }}>A backtest is history, not a forecast. Run {r.runId ?? "id not returned"}.</span>
    </div>
  );
}

function Backtest() {
  const list = useSavedStrategies();
  const run = useBacktestRun();
  const today = useMemo(() => new Date(), []);
  const [id, setId] = useState("");
  const [from, setFrom] = useState(() => isoDay(new Date(today.getTime() - 365 * 86_400_000)));
  const [to, setTo] = useState(() => isoDay(new Date(today.getTime() - 86_400_000)));
  const strategies = list.data ?? [];
  const picked = id || strategies[0]?.id || "";
  let body: ReactNode;
  if (list.isPending) body = <LoadingBlock label="Reading your saved strategies" rows={1} />;
  else if (list.isError) body = <span data-testid="td-bt-list-error" role="alert" style={{ ...quiet, color: "var(--amber)" }}>Your saved strategies did not load: {writeProblem(list.error)}.</span>;
  else if (!strategies.length) body = <span data-testid="td-bt-none" style={quiet}>No saved strategies yet. Save a screen as a strategy (Market Desk › Screener, ready-made screens) to backtest it here.</span>;
  else {
    body = (
      <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
        <div className="flex flex-wrap items-end" style={{ gap: 10 }}>
          <label className="flex min-w-0 flex-col" style={{ gap: 4, fontSize: 12, color: "var(--cp-ink-3)", flex: "1 1 200px" }}>
            Strategy
            <select data-testid="td-bt-strategy" value={picked} onChange={(e) => { run.reset(); setId(e.target.value); }}
              style={{ height: 34, minWidth: 0, maxWidth: "100%", padding: "0 8px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)" }}>
              {strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          {([["From", from, setFrom, "td-bt-from"], ["To", to, setTo, "td-bt-to"]] as const).map(([k, v, set, tid]) => (
            <label key={tid} className="flex flex-col" style={{ gap: 4, fontSize: 12, color: "var(--cp-ink-3)" }}>
              {k}
              <input data-testid={tid} type="date" value={v} onChange={(e) => { run.reset(); set(e.target.value); }}
                style={{ height: 34, padding: "0 8px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)" }} />
            </label>
          ))}
          <Btn variant="primary" data-testid="td-bt-run" disabled={!picked || run.isPending} onClick={() => run.mutate({ id: picked, from, to })}>{run.isPending ? "Running…" : "Run backtest"}</Btn>
        </div>
        {run.isError && <span data-testid="td-bt-error" role="alert" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>The backtest did not run: {writeProblem(run.error)}</span>}
        {run.isSuccess && <Provenance r={run.data} />}
      </div>
    );
  }
  return <Panel title="Backtest" note="end-of-day history · provenance-v1" testId="td-backtest">{body}</Panel>;
}

// ── the sub-views ────────────────────────────────────────────────────────

/** Strategy Builder URL params (an idea's plan inputs, a saved plan, an auto-build): they open "From an idea" below. */
const BUILDER_PARAMS = ["sym", "plan", "build", "cand", "direction", "instrument", "horizon", "focus", "mode"];

/**
 * Strategy Lab › Build a trade: the owner's four-step wizard (lab/Wizard.tsx). Above it, the ticket when an idea's plan
 * is open (?tp=). Below it, folded unless a link opens them: "From an idea · Strategy Builder" (the plans and candidates
 * an idea or the scanner opens; open with its URL inputs or section=builder) and the F&O lab's structures (rules-based
 * cards, compare, levels; open with section=fno, where the lab's "strategies" link lands). Both existed here before the
 * wizard and have no other home yet.
 */
export function BuildTradeView({ planId, source, onOverview, onBacktest }: { planId: string | null; source: NewPaperTrade["source"] | null; onOverview: () => void; onBacktest: () => void }) {
  const [params] = useSearchParams();
  const section = params.get("section");
  const fromIdea = section === "builder" || BUILDER_PARAMS.some((k) => params.has(k));
  const [open, setOpen] = useState(fromIdea);
  const fnoLink = section === "fno";
  const [fnoOpen, setFnoOpen] = useState(fnoLink);
  const templates = useStrategyTemplates();
  const catalog = templates.isSuccess ? templates.data.templates.map((t) => t.name) : null;
  const sym = (params.get("lab_sym") ?? params.get("sym") ?? "").toUpperCase();
  const initial = /^[A-Z0-9&_-]{1,30}$/.test(sym) ? sym : "NIFTY";
  return (
    <div data-testid="td-view-build" className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      {planId && <Ticket planId={planId} source={source} onOverview={onOverview} />}
      <Part id="wizard" name="Build a trade"><StrategyWizard initialSymbol={initial} onBacktest={onBacktest} /></Part>
      <section aria-label="From an idea" className="flex min-w-0 flex-col" style={{ gap: 12, paddingTop: 16, borderTop: "1px solid var(--cp-line)" }}>
        <button type="button" data-testid="td-from-idea" aria-expanded={open || fromIdea} onClick={() => setOpen((o) => !o)}
          className="flex items-center" style={{ gap: 8, padding: 0, border: 0, background: "none", cursor: "pointer", color: "var(--cp-ink-2)", textAlign: "left" }}>
          <span aria-hidden="true" style={{ display: "inline-block", transform: open || fromIdea ? "rotate(90deg)" : undefined }}>›</span>
          <span className="cp-eyebrow">From an idea · Strategy Builder (plans and candidates)</span>
        </button>
        {(open || fromIdea) ? <Part id="strategy" name="the Strategy Builder"><StrategyBuilder /></Part>
          : (
            <span data-testid="td-from-idea-note" style={quiet}>
              No idea open. An idea from the scanner or <button type="button" data-testid="td-ticket-overview" style={linkBtn} onClick={onOverview}>Market Overview › Top AI ideas</button> opens its plan here, with its candidates and “Paper trade this”, and its ticket above the wizard.
            </span>
          )}
      </section>
      <section aria-label="F&O structures" className="flex min-w-0 flex-col" style={{ gap: 12, paddingTop: 16, borderTop: "1px solid var(--cp-line)" }}>
        <button type="button" data-testid="td-fno-structures" aria-expanded={fnoOpen || fnoLink} onClick={() => setFnoOpen((o) => !o)}
          className="flex items-center" style={{ gap: 8, padding: 0, border: 0, background: "none", cursor: "pointer", color: "var(--cp-ink-2)", textAlign: "left" }}>
          <span aria-hidden="true" style={{ display: "inline-block", transform: fnoOpen || fnoLink ? "rotate(90deg)" : undefined }}>›</span>
          <span className="cp-eyebrow">F&amp;O lab · rules-based structures, compare and levels</span>
        </button>
        {(fnoOpen || fnoLink) ? <Part id="fno" name="the F&O builder"><FnoTab views={["strategies"]} asSection builderCatalog={catalog} /></Part>
          : <span style={quiet}>The F&amp;O lab&rsquo;s rules-based structure cards, the side-by-side compare and the levels card; links from the lab open it here.</span>}
      </section>
    </div>
  );
}

/** Strategy Lab › Backtest & validation. */
export function BacktestView() {
  return <div data-testid="td-view-backtest" className="flex min-w-0 flex-col" style={{ gap: 16 }}><Backtest /></div>;
}
