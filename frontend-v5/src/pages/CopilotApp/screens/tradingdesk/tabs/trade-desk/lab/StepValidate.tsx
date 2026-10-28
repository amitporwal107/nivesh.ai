/**
 * Strategy Lab › Build a trade, step 4 — Validate & paper-trade.
 *
 *   Strategy instance   Save version and Clone go to the ONE store, the Strategy Builder's strategy_versions v2 (owner, 28
 *                       Oct; strategy/instance-store.ts, PR #398). The first save creates the strategy (version 1); each
 *                       later save is a new, unchangeable version from the one loaded (another tab's save first → "save on
 *                       top of version N?"), answered with the server's diff and the store's checks. Clone copies the
 *                       saved version into a new strategy you then edit. A server without the store says so (NOT_YET) and
 *                       the legs stay on the page. Adjust legs goes back to step 3.
 *   Backtest            a structure backtest over option history does not exist for multi-leg F&O structures: said so. A
 *                       cash position links to Backtest & validation (end-of-day strategy backtests with provenance).
 *   Paper gates         a valid payoff, your build limits, the risk service's decision (the check). The trade cites the
 *                       template (signal.source_refs strategy_template), and the saved version (`strategy_ref`) when the legs
 *                       are exactly that version.
 *   Start               POST /api/desk/paper-trades with an Idempotency-Key (desk-trading useAddStrategyPaperTrade): the risk
 *                       service answers allow (recorded), reduce ("Accept N lots per leg?", nothing recorded), block (the
 *                       reasons), a duplicate, or the desk's own 422. Paper only; nothing is sent to a broker.
 *   Monitor             the paper trade started here or opened from Existing strategies, from the paper book (EOD marks).
 */
import { useState, type ReactNode } from "react";
import { Btn } from "../../../../../components/ui";
import { detailOf, orderReasons, readReasons } from "../../../risk-controls";
import { riskReduceOf, useAddStrategyPaperTrade, type NewStrategyPaperTrade, type StrategyPaperTrade } from "../../../desk-trading";
import { ChecksCard, type Structure } from "./StepReview";
import { INPUT_WORDS, legsSummary, refusalOf, shortDay } from "./wizard-data";
import type { StoreCheck } from "../../../strategy/instance-store";
import { Card, Pill, eyebrowS, inr, mono, quietS } from "./ui";
import { daysBetween, todayIso } from "./ChainPicker";

/** What the last Save version / Clone answered, shown next to the buttons (Wizard.tsx save / clone). */
export interface StoreMessage {
  kind: "saved" | "stale" | "unavailable" | "error";
  text: string;
  problems: Array<{ field: string; code: string; message: string }>;
  activeVersionId: string | null;
  activeVersionNo: number | null;
  diff: Array<{ path: string; before: unknown; after: unknown }>;
  checks: StoreCheck[];
}

export interface StoreControls {
  saved: { versionNo: number } | null;
  dirty: boolean;
  canSave: boolean;
  busy: boolean;
  message: StoreMessage | null;
  onSave: () => void;
  onSaveOver: (versionId: string) => void;
  onClone: () => void;
}

const shown = (v: unknown): string => v == null ? "—" : typeof v === "object" ? "changed" : String(v);

type Answer = { kind: "allow" | "reduce" | "block" | "duplicate" | "invalid" | "error"; text: string; reasons: string[]; approvedLots?: number | null; requestedLots?: number | null };

function answerOf(e: unknown): Answer {
  const d = detailOf(e);
  const code = typeof d.code === "string" ? d.code : null;
  const reasons = orderReasons(readReasons(d.reasons)).map((r) => r.message);
  if (code === "risk_reduce") {
    const r = riskReduceOf(e);
    return { kind: "reduce", text: `Reduced: the risk service allows ${r?.approvedLots ?? "?"} lot(s) per leg${r?.requestedLots != null ? ` (you asked ${r.requestedLots})` : ""}. Nothing was recorded.`, reasons, approvedLots: r?.approvedLots ?? null, requestedLots: r?.requestedLots ?? null };
  }
  if (code === "risk_blocked") return { kind: "block", text: "Blocked by the risk service. Nothing was recorded.", reasons: reasons.length ? reasons : typeof d.message === "string" ? [d.message] : [] };
  if (code === "duplicate_open_structure" || code === "duplicate_open_trade") return { kind: "duplicate", text: typeof d.message === "string" ? d.message : "This structure is already open: not added twice.", reasons: [] };
  const r = refusalOf(e);
  if (r.code in INPUT_WORDS || /^invalid_|_required$|_not_supported$/.test(r.code)) return { kind: "invalid", text: `Not recorded: ${r.message}`, reasons: [] };
  return { kind: "error", text: `Not recorded: ${r.message}`, reasons: [] };
}

export function StepValidate({ onAdjust, name, onName, structure, body, multiLeg, cashOnly,
  onBacktest, onLiveDesk, trade, onStarted, asOf, onScaleLots, store }: {
  store: StoreControls;
  onAdjust: () => void; name: string; onName: (s: string) => void;
  structure: Structure; body: NewStrategyPaperTrade | null; multiLeg: boolean; cashOnly: boolean;
  onBacktest: () => void; onLiveDesk: () => void; trade: StrategyPaperTrade | null; onStarted: (id: string | null) => void; asOf: string | null;
  onScaleLots: (approved: number, requested: number) => void;
}) {
  const add = useAddStrategyPaperTrade();
  const [answer, setAnswer] = useState<Answer | null>(null);
  const r = structure.pay.data;
  const check = structure.check.state;
  const gates: Array<{ ok: boolean; text: ReactNode; id: string }> = [
    { id: "payoff", ok: !!r?.valid, text: r?.valid ? "Payoff worked out (payoff-v2, net of costs)." : "No valid payoff yet." },
    ...structure.limits.map((l, i) => ({ id: `limit-${i}`, ok: l.ok, text: l.text })),
    { id: "risk", ok: check?.kind === "answer" && check.a.outcome !== "block", text: check?.kind === "answer" ? (check.a.outcome === "allow" ? "The risk service allows it on your account now." : check.a.outcome === "reduce" ? `The risk service would reduce it to ${check.a.approvedLots ?? "?"} lot(s) per leg.` : "The risk service blocks it on your account now.") : check?.kind === "refused" ? `Not accepted: ${check.message}` : "Waiting for the risk service." },
  ];
  const ready = gates.every((x) => x.ok) && !!body && !trade;
  const start = () => {
    if (!body) return;
    setAnswer(null);
    add.mutate(body, {
      onSuccess: (t) => { setAnswer({ kind: "allow", text: `Allowed: simulated trade ${t.id} is open. Nothing was sent to a broker.`, reasons: [] }); onStarted(t.id); },
      onError: (e) => setAnswer(answerOf(e)),
    });
  };
  const tone = answer?.kind === "allow" ? "var(--mint)" : answer?.kind === "reduce" || answer?.kind === "duplicate" ? "var(--amber)" : "var(--cp-danger)";
  const dte = trade ? trade.legs.map((l) => l.expiry).filter((x): x is string => !!x).sort()[0] : null;

  return (
    <div data-testid="wz-step-4" className="flex min-w-0 flex-wrap" style={{ gap: 16, alignItems: "flex-start" }}>
      <div className="flex min-w-0 flex-col" style={{ flex: "999 1 480px", gap: 14 }}>
        <Card testId="wz-instance" title="Strategy instance" right={<span data-testid="wz-instance-state">{store.saved ? `version ${store.saved.versionNo}${store.dirty ? " · unsaved changes" : ""}` : "unsaved"}</span>}>
          <label className="flex min-w-0 flex-col" style={{ gap: 4, fontSize: 12, color: "var(--cp-ink-3)" }}>
            Name
            <input data-testid="wz-instance-name" value={name} maxLength={80} onChange={(e) => onName(e.target.value)}
              style={{ height: 34, padding: "0 10px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink)", minWidth: 0 }} />
          </label>
          {body && <span data-testid="wz-instance-legs" style={{ ...mono, fontSize: 12 }}>{legsSummary(body.legs.map((l) => ({ kind: l.kind, side: l.side, optionType: l.option_type, strike: l.strike, expiry: l.expiry })))}</span>}
          <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <Btn variant="primary" data-testid="wz-save" disabled={!store.canSave || (!!store.saved && !store.dirty)} onClick={store.onSave}
              title={store.saved && !store.dirty ? `Nothing changed since version ${store.saved.versionNo}.` : undefined}>{store.busy ? "Saving…" : "Save version"}</Btn>
            <button type="button" className="cp-btn" data-variant="ghost" data-testid="wz-clone" disabled={!store.saved || store.dirty || store.busy} onClick={store.onClone}
              title={!store.saved ? "Save a version first: Clone copies a saved version." : store.dirty ? "Save your changes first: Clone copies the saved version." : undefined}>Clone</button>
            <button type="button" className="cp-btn" data-variant="ghost" data-testid="wz-adjust" onClick={onAdjust}>Adjust legs</button>
          </div>
          {store.message ? <StoreNote m={store.message} onSaveOver={store.onSaveOver} /> : null}
          <span style={{ ...quietS, fontSize: 11 }}>
            Saved structures go into your strategy store: one version history, each version unchangeable, and each backtest run on one version. A simulated trade of exactly a saved version cites it (PAPER LIVE in Existing strategies); otherwise it records its legs and the template it came from.
          </span>
        </Card>

        <Card testId="wz-backtest" title="Backtest">
          {cashOnly ? (
            <span style={quietS}>
              A cash position is backtested as a saved screen strategy in <button type="button" data-testid="wz-backtest-link" onClick={onBacktest} style={{ padding: 0, border: 0, background: "none", color: "var(--mint)", cursor: "pointer", font: "inherit" }}>Backtest &amp; validation</button> (end-of-day history with its provenance: universe, code version, data, cost model, slippage sweep).
            </span>
          ) : (
            <span data-testid="wz-backtest-none" style={quietS}>
              Not available yet for {multiLeg ? "multi-leg structures" : "option and futures structures"}: there is no backtest of a structure over option-price history. Backtest &amp; validation covers saved screen strategies (cash).{" "}
              <button type="button" data-testid="wz-backtest-link" onClick={onBacktest} style={{ padding: 0, border: 0, background: "none", color: "var(--mint)", cursor: "pointer", font: "inherit" }}>Open Backtest &amp; validation</button>
            </span>
          )}
        </Card>

        {trade && (
          <Card testId="wz-monitor" title="Monitor · simulated trade" right={trade.status === "open" ? "open" : "closed"}>
            <dl className="m-0 grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,130px),1fr))", gap: 10, fontSize: 12.5 }}>
              <Kv k="Trade" v={trade.id} id="id" />
              <Kv k="State" v={trade.state ?? trade.status} id="state" />
              <Kv k="Net P/L" v={<span style={{ color: (trade.netRs ?? 0) < 0 ? "var(--cp-danger)" : "var(--mint)" }}>{inr(trade.netRs, true)}</span>} id="net" />
              <Kv k="Marked" v={trade.lastMarkDate ? `${shortDay(trade.lastMarkDate)} close` : "not yet"} id="mark" />
              <Kv k="Days to expiry" v={dte ? String(daysBetween(todayIso(), dte)) : "—"} id="dte" />
              <Kv k="Held" v={trade.heldSessions != null ? `${trade.heldSessions} sessions` : "—"} id="held" />
            </dl>
            {trade.flags.length > 0 && <ul className="m-0" style={{ paddingLeft: 16, ...quietS }}>{trade.flags.map((f, i) => <li key={i} data-testid="wz-monitor-flag">{f.text}</li>)}</ul>}
            {trade.premiumPlan && <span data-testid="wz-monitor-plan" style={quietS}>Exit conditions on the structure&rsquo;s premium are recorded with the trade; the Live desk shows and applies them at each end-of-day mark.</span>}
            <span style={quietS}>End-of-day marks, not live. Close or roll it on the <button type="button" data-testid="wz-monitor-live" onClick={onLiveDesk} style={{ padding: 0, border: 0, background: "none", color: "var(--mint)", cursor: "pointer", font: "inherit" }}>Live desk</button>.</span>
          </Card>
        )}
      </div>

      <div className="flex min-w-0 flex-col" style={{ flex: "1 1 300px", gap: 14 }}>
        <Card testId="wz-gates" title="Paper gates">
          <ul className="m-0 flex flex-col" style={{ gap: 8, padding: 0, listStyle: "none" }}>
            {gates.map((x) => (
              <li key={x.id} data-testid={`wz-gate-${x.id}`} data-ok={x.ok ? "true" : "false"} className="flex" style={{ gap: 8, fontSize: 12.5, lineHeight: 1.5 }}>
                <span aria-hidden="true" style={{ color: x.ok ? "var(--mint)" : "var(--cp-danger)", fontWeight: 700 }}>{x.ok ? "✓" : "✗"}</span>
                <span style={{ color: "var(--cp-ink-2)" }}>{x.text}</span>
              </li>
            ))}
          </ul>
        </Card>
        <ChecksCard structure={structure} asOf={asOf} age={asOf ? daysBetween(asOf, todayIso()) : null} stale={false} title="Risk check" testId="wz-checks4" />
        <Card testId="wz-paper" title="Simulated paper trade">
          {trade ? (
            <span data-testid="wz-paper-open" style={{ fontSize: 12.5, color: "var(--mint)" }}>Open as paper trade {trade.id}.</span>
          ) : (
            <Btn variant="primary" data-testid="wz-start" disabled={!ready || add.isPending} onClick={start}>{add.isPending ? "Starting…" : "Start simulated trade"}</Btn>
          )}
          {answer && (
            <div data-testid="wz-answer" data-outcome={answer.kind} role={answer.kind === "allow" ? "status" : "alert"} className="flex flex-col" style={{ gap: 6, padding: "10px 12px", borderRadius: 10, border: `1px solid ${tone}` }}>
              <span data-testid="wz-answer-text" style={{ fontSize: 13, lineHeight: 1.5, color: tone }}>{answer.text}</span>
              {answer.reasons.length > 0 && <ul className="m-0" style={{ paddingLeft: 16, fontSize: 12.5, color: "var(--cp-ink-2)" }}>{answer.reasons.map((x, i) => <li key={i} data-testid="wz-answer-reason">{x}</li>)}</ul>}
              {answer.kind === "reduce" && answer.approvedLots != null && answer.requestedLots != null && answer.approvedLots >= 1 && (
                <button type="button" className="cp-btn" data-variant="ghost" data-testid="wz-accept-reduce" onClick={() => { onScaleLots(answer.approvedLots as number, answer.requestedLots as number); setAnswer(null); }}>
                  Accept {answer.approvedLots} lot{answer.approvedLots === 1 ? "" : "s"} per leg? (the legs change; then start again)
                </button>
              )}
              {answer.kind === "block" && <span style={quietS}>Your risk profile is the only risk setting (Risk Desk › Controls &amp; profile). A kill switch blocks new paper entries; only an admin clears it.</span>}
            </div>
          )}
          <span style={{ ...quietS, fontSize: 11 }}>Paper only: a simulated trade at the chain&rsquo;s closes; nothing is sent to a broker. The order path has no AI in it.</span>
          <button type="button" data-testid="wz-live-desk" onClick={onLiveDesk} style={{ padding: 0, border: 0, background: "none", color: "var(--mint)", cursor: "pointer", font: "inherit", fontSize: 12.5, textAlign: "left" }}>Live desk</button>
        </Card>
      </div>
    </div>
  );
}

function StoreNote({ m, onSaveOver }: { m: StoreMessage; onSaveOver: (versionId: string) => void }) {
  const tone = m.kind === "saved" ? "var(--mint)" : m.kind === "error" ? "var(--cp-danger)" : "var(--amber)";
  const flagged = m.checks.filter((c) => c.severity !== "info");
  return (
    <div data-testid="wz-save-note" data-kind={m.kind} role={m.kind === "saved" ? "status" : "alert"} className="flex flex-col" style={{ gap: 6, fontSize: 12.5, lineHeight: 1.5 }}>
      <span data-testid="wz-save-text" style={{ color: tone }}>{m.text}</span>
      {m.problems.length > 0 && <ul className="m-0" style={{ paddingLeft: 16, color: "var(--cp-ink-2)" }}>{m.problems.map((p, i) => <li key={i} data-testid="wz-save-problem">{p.message} <span style={{ ...mono, fontSize: 11 }}>({p.field})</span></li>)}</ul>}
      {m.diff.length > 0 && (
        <ul data-testid="wz-save-diff" className="m-0" style={{ paddingLeft: 16, color: "var(--cp-ink-2)" }}>
          {m.diff.slice(0, 8).map((d, i) => <li key={i} data-testid="wz-save-diff-item" style={{ ...mono, fontSize: 11.5 }}>{d.path}: {shown(d.before)} → {shown(d.after)}</li>)}
          {m.diff.length > 8 && <li style={quietS}>and {m.diff.length - 8} more</li>}
        </ul>
      )}
      {flagged.length > 0 && <ul className="m-0" style={{ paddingLeft: 16 }}>{flagged.map((c) => <li key={c.code} data-testid="wz-save-check" data-severity={c.severity} style={{ color: c.severity === "blocking" ? "var(--amber)" : "var(--cp-ink-2)" }}>{c.message}</li>)}</ul>}
      {m.kind === "stale" && m.activeVersionId && (
        <button type="button" className="cp-btn" data-variant="ghost" data-testid="wz-save-over" onClick={() => onSaveOver(m.activeVersionId as string)}>
          Save these legs on top of version {m.activeVersionNo ?? "?"}
        </button>
      )}
    </div>
  );
}

function Kv({ k, v, id }: { k: string; v: ReactNode; id: string }) {
  return (
    <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <dt style={{ ...eyebrowS, fontSize: 9.5 }}>{k}</dt>
      <dd className="m-0" data-testid={`wz-monitor-${id}`} style={{ ...mono, overflowWrap: "anywhere" }}>{v}</dd>
    </span>
  );
}
