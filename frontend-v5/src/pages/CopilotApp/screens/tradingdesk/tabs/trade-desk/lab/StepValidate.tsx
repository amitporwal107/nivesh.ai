/**
 * Strategy Lab › Build a trade, step 4 — Validate & paper-trade.
 *
 *   Strategy instance   POST /api/desk/strategy/instances (save v1), …/{id}/versions (save as vN+1), …/{id}/clone; Adjust
 *                       legs goes back to step 3. Versions are immutable.
 *   Backtest            a structure backtest over option history does not exist for multi-leg F&O structures: said so. A
 *                       cash position links to Backtest & validation (end-of-day strategy backtests with provenance).
 *   Paper gates         saved as a version, a valid payoff, your build limits, the risk service's decision (the check).
 *   Start               POST /api/desk/paper-trades with an Idempotency-Key (desk-trading useAddStrategyPaperTrade): the risk
 *                       service answers allow (recorded), reduce ("Accept N lots per leg?", nothing recorded), block (the
 *                       reasons), a duplicate, or the desk's own 422. Paper only; nothing is sent to a broker.
 *   Monitor             the open paper trade that cites this instance, from the paper book (read once per load; EOD marks).
 */
import { useState, type ReactNode } from "react";
import { Btn } from "../../../../../components/ui";
import { detailOf, orderReasons, readReasons } from "../../../risk-controls";
import { riskReduceOf, useAddStrategyPaperTrade, type NewStrategyPaperTrade, type StrategyPaperTrade } from "../../../desk-trading";
import { ChecksCard, type Structure } from "./StepReview";
import { INPUT_WORDS, refusalOf, shortDay, type Instance } from "./wizard-data";
import { Card, Pill, eyebrowS, inr, mono, quietS } from "./ui";
import { daysBetween, todayIso } from "./ChainPicker";

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

export function StepValidate({ instance, version, edited, saving, saveError, onSave, onSaveVersion, onClone, onAdjust, name, onName, structure, body, multiLeg, cashOnly,
  onBacktest, onLiveDesk, trade, onStarted, asOf, onScaleLots }: {
  instance: Instance | null; version: number | null; edited: boolean; saving: boolean; saveError: string | null;
  onSave: () => void; onSaveVersion: () => void; onClone: () => void; onAdjust: () => void; name: string; onName: (s: string) => void;
  structure: Structure; body: NewStrategyPaperTrade | null; multiLeg: boolean; cashOnly: boolean;
  onBacktest: () => void; onLiveDesk: () => void; trade: StrategyPaperTrade | null; onStarted: (id: string | null) => void; asOf: string | null;
  onScaleLots: (approved: number, requested: number) => void;
}) {
  const add = useAddStrategyPaperTrade();
  const [answer, setAnswer] = useState<Answer | null>(null);
  const saved = !!instance && version != null;
  const r = structure.pay.data;
  const check = structure.check.state;
  const gates: Array<{ ok: boolean; text: ReactNode; id: string }> = [
    { id: "saved", ok: saved && !edited, text: saved ? (edited ? "Edited since the last saved version: save a new version first, so the paper trade cites what it holds." : `Saved as v${version}: the paper trade cites ${instance?.id.slice(0, 8)}@v${version}.`) : "Save the strategy instance first, so the paper trade cites a version." },
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
        <Card testId="wz-instance" title="Strategy instance" right={saved ? `${instance?.id.slice(0, 8).toUpperCase()} · v${version}${edited ? " · edited" : ""}` : "unsaved"}>
          {!saved && (
            <label className="flex min-w-0 flex-col" style={{ gap: 4, fontSize: 12, color: "var(--cp-ink-3)" }}>
              Name
              <input data-testid="wz-instance-name" value={name} maxLength={80} onChange={(e) => onName(e.target.value)}
                style={{ height: 34, padding: "0 10px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink)", minWidth: 0 }} />
            </label>
          )}
          {saved && instance && (
            <ul data-testid="wz-versions" className="m-0 flex flex-col" style={{ gap: 4, padding: 0, listStyle: "none" }}>
              {[...instance.versions].reverse().map((v) => (
                <li key={v.version} data-testid="wz-version" data-version={v.version} className="flex flex-wrap items-baseline" style={{ gap: 8, fontSize: 12.5 }}>
                  <Pill tone={v.version === version ? "mint" : "grey"}>v{v.version}</Pill>
                  <span style={mono}>{v.savedAt ? v.savedAt.slice(0, 16).replace("T", " ") : ""}</span>
                  <span style={quietS}>{v.legs.length} leg{v.legs.length === 1 ? "" : "s"}{v.note ? ` · ${v.note}` : ""}</span>
                </li>
              ))}
            </ul>
          )}
          {instance?.clonedFrom && <span style={quietS}>Cloned from {instance.clonedFrom.id?.slice(0, 8).toUpperCase()} v{instance.clonedFrom.version}.</span>}
          <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
            {!saved ? <Btn variant="primary" data-testid="wz-save" disabled={saving || !r?.valid} onClick={onSave}>{saving ? "Saving…" : "Save version"}</Btn>
              : <Btn variant="primary" data-testid="wz-save-version" disabled={saving || !edited || !r?.valid} onClick={onSaveVersion}>{saving ? "Saving…" : `Save as v${(instance?.latestVersion ?? 0) + 1}`}</Btn>}
            <button type="button" className="cp-btn" data-variant="ghost" data-testid="wz-clone" disabled={!saved || saving} onClick={onClone}>Clone</button>
            <button type="button" className="cp-btn" data-variant="ghost" data-testid="wz-adjust" onClick={onAdjust}>Adjust legs</button>
          </div>
          {saveError && <span data-testid="wz-save-error" role="alert" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>Not saved: {saveError}</span>}
          <span style={{ ...quietS, fontSize: 11 }}>Each version is kept as saved and never edited; a change is a new version.</span>
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
                  Accept {answer.approvedLots} lot{answer.approvedLots === 1 ? "" : "s"} per leg? (a new version to save, then start)
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

function Kv({ k, v, id }: { k: string; v: ReactNode; id: string }) {
  return (
    <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <dt style={{ ...eyebrowS, fontSize: 9.5 }}>{k}</dt>
      <dd className="m-0" data-testid={`wz-monitor-${id}`} style={{ ...mono, overflowWrap: "anywhere" }}>{v}</dd>
    </span>
  );
}
