/**
 * F&O lab · 12 Audit & Decision Replay (?screen=audit). Design: the "Audit & Decision Replay" screen of Nivesh F&O Desk,
 * today state.
 *
 *   GET  /api/risk/decisions?limit=200      every recorded risk decision, newest first (governance-data.ts useAuditDecisions)
 *   GET  /api/risk/decisions/{id}/lineage   the PRD's ten steps for the selected decision, each recorded / not recorded /
 *                                           not reached / not applicable, with what was recorded (useDecisionLineage)
 *   POST /api/risk/decisions/{id}/replay    re-runs the gate on the snapshot stored with the decision and compares;
 *                                           writes nothing (useReplayDecision)
 *   GET  /api/risk/audit?limit=             control changes, append only (tradingdesk/risk-controls.ts useRiskAudit)
 *
 * A search box filters by decision id or correlation id. The lineage marks a step recorded only when the server does.
 * Replay works on the gate's own reads (request, controls, exchange reference, open-structure count); no market price
 * snapshot is stored yet (P0.3), so it says nothing about prices. A row without a snapshot shows the server's reason.
 */
import { useState } from "react";
import { Btn, EmptyBlock, LoadingBlock, Pill, Section, fmtINR } from "../../components/ui";
import { INPUT_STYLE, QueryProblem } from "../trading/parts";
import { stampIst } from "../tradingdesk/overview-data";
import { useRiskAudit, type RiskAuditEvent } from "../tradingdesk/risk-controls";
import {
  isBlocked, matchesDecision, useAuditDecisions, useDecisionLineage, useReplayDecision,
  type AuditDecision, type LineageStatus, type LineageStep,
} from "./governance-data";
import { KvRows, SourceCards, quiet, type SourceItem } from "./parts";

const SOURCES: SourceItem[] = [
  { k: "Decision store", sub: "risk_decisions · gate decisions with correlation id", tone: "mint" },
  { k: "Decision snapshot", sub: "The gate's reads, hashed · no market prices · P0.3", tone: "amber" },
  { k: "Kill-switch audit", sub: "risk_control_audit · exists", tone: "mint" },
  { k: "Paper entry hashes", sub: "entry_record_hash · exists", tone: "mint" },
];

const at = (iso: string | null) => stampIst(iso) ?? "time not recorded";

const STATUS_TEXT: Record<LineageStatus, string> = {
  recorded: "Recorded", not_recorded: "Not recorded", not_reached: "Not reached", not_applicable: "Not applicable",
};
const stepTag = (s: LineageStep) => (s.status === "not_recorded" && s.backlog ? `Not recorded · ${s.backlog}` : STATUS_TEXT[s.status]);

function DecisionRow({ d, on, onPick }: { d: AuditDecision; on: boolean; onPick: () => void }) {
  const blocked = isBlocked(d.outcome);
  return (
    <button type="button" data-testid="fnolab-audit-decision" data-id={d.id} aria-pressed={on} onClick={onPick}
      className="flex flex-col" style={{ textAlign: "left", gap: 4, padding: "10px 12px", borderRadius: 10, border: `1px solid ${on ? "var(--mint-line)" : "var(--cp-line)"}`, background: on ? "var(--bg-2)" : "transparent", color: "var(--cp-ink)", cursor: "pointer", minWidth: 0 }}>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Pill tone={blocked ? "danger" : "mint"}>{d.outcome ?? "outcome not recorded"}</Pill>
        <span style={{ fontSize: 13.5, fontWeight: 500 }}>{d.symbol ?? "—"}</span>
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{d.path ?? d.action ?? "path not recorded"}</span>
        <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-3)" }}>{at(d.at)}</span>
      </span>
      <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>
        {d.id} · {d.correlationId ? `corr ${d.correlationId}` : "no correlation id"}
      </span>
    </button>
  );
}

const mono = (v: string) => <span style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>{v}</span>;
const words = (xs: string[]) => (xs.length ? xs.join(", ") : "none");

function ReplayPanel({ d }: { d: AuditDecision }) {
  const m = useReplayDecision();
  const res = m.data;
  const state = m.isPending ? "running" : m.isError ? "error" : !res ? "idle" : !res.replayable ? "not_replayable" : res.match ? "match" : "mismatch";
  return (
    <div data-testid="fnolab-audit-replay" data-state={state} className="flex flex-col" style={{ gap: 10, padding: "12px 14px", borderRadius: 10, border: "1px dashed var(--line-3)" }}>
      <div className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
        <span style={{ flex: "1 1 260px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          Replay re-runs the gate's checks on what it read when it decided, under the code and policy running now, and compares. It writes nothing. No market price snapshot is stored (P0.3), so it says nothing about the prices.
        </span>
        <Btn data-testid="fnolab-audit-replay-run" disabled={m.isPending} onClick={() => m.mutate(d.id)} style={{ padding: "6px 14px" }}>
          {m.isPending ? "Replaying…" : res ? "Replay again" : "Replay from snapshot"}
        </Btn>
      </div>
      {m.isError && <QueryProblem what="The replay" error={m.error} onRetry={() => m.mutate(d.id)} />}
      {res && !res.replayable && (
        <span data-testid="fnolab-audit-replay-reason" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>Not replayable. {res.reason}</span>
      )}
      {res && res.replayable && (
        <div data-testid="fnolab-audit-replay-result" data-match={String(res.match)} className="flex flex-col" style={{ gap: 8 }}>
          <span className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 13.5 }}>
            <Pill tone={res.match ? "mint" : "danger"}>{res.match ? "Match" : "Mismatch"}</Pill>
            {res.match ? "The same inputs reach the same decision under the code and policy running now." : "The replay does not reproduce the recorded decision."}
          </span>
          <KvRows testId="fnolab-audit-replay-rows" rows={[
            { k: "Outcome", v: `${res.outcomeThen ?? "not recorded"} then · ${res.outcomeNow ?? "—"} now` },
            { k: "Reasons", v: `${words(res.reasonsThen)} then · ${words(res.reasonsNow)} now` },
            { k: "Capital at risk", v: `${res.capitalThen == null ? "—" : fmtINR(res.capitalThen)} then · ${res.capitalNow == null ? "—" : fmtINR(res.capitalNow)} now` },
            { k: "Policy", v: `${res.policyThen ?? "not recorded"} then · ${res.policyNow ?? "—"} now` },
            { k: "Inputs hash", v: res.inputsHashMatch ? "matches the stored request" : "does not match the stored request" },
            { k: "Snapshot hash", v: res.snapshotHashMatch ? "matches the stored snapshot" : "does not match the stored snapshot" },
          ]} />
          {res.differences.length > 0 && (
            <ul data-testid="fnolab-audit-replay-diff" style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
              {res.differences.map((x) => <li key={x}>{x}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Lineage({ d }: { d: AuditDecision }) {
  const q = useDecisionLineage(d.id);
  const [node, setNode] = useState("risk_decision");
  const steps = q.data?.steps ?? [];
  const sel = steps.find((s) => s.step === node) ?? steps.find((s) => s.step === "risk_decision") ?? steps[0];
  return (
    <Section title={`Lineage · ${d.id}`} note={q.data ? `${q.data.recorded} of ${steps.length} recorded · ${at(d.at)}` : at(d.at)}>
      <div className="flex flex-col" style={{ gap: 14 }}>
        {q.isPending && <LoadingBlock label="Reading the lineage" rows={2} />}
        {q.isError && <QueryProblem what="The lineage" error={q.error} onRetry={() => void q.refetch()} />}
        {q.data && (
          <div data-testid="fnolab-audit-lineage" className="cp-scroll flex" style={{ gap: 6, overflowX: "auto", paddingBottom: 4 }}>
            {steps.map((n) => {
              const ok = n.status === "recorded";
              const on = n.step === sel?.step;
              return (
                <button key={n.step} type="button" data-testid="fnolab-audit-node" data-node={n.step} data-status={n.status} data-recorded={String(ok)} aria-pressed={on} onClick={() => setNode(n.step)}
                  className="flex flex-col" style={{ flex: "1 0 112px", textAlign: "left", gap: 5, padding: 10, borderRadius: 10, border: `1px solid ${on ? "var(--mint-line)" : "var(--cp-line)"}`, background: on ? "var(--bg-2)" : "transparent", color: "var(--cp-ink)", opacity: ok ? 1 : 0.7, cursor: "pointer" }}>
                  <span className="flex items-center" style={{ gap: 6, fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase", color: ok ? "var(--mint)" : "var(--cp-ink-4)" }}>
                    <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: ok ? "var(--mint)" : "var(--cp-ink-4)" }} />
                    {stepTag(n)}
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.25 }}>{n.label}</span>
                </button>
              );
            })}
          </div>
        )}

        {sel && (
          <div data-testid="fnolab-audit-node-detail" data-node={sel.step} className="flex flex-col" style={{ gap: 10 }}>
            <span className="cp-eyebrow" style={{ color: sel.status === "recorded" ? "var(--mint)" : "var(--cp-ink-3)" }}>{sel.label} · {stepTag(sel)}</span>
            {sel.step === "risk_decision" && (
              <KvRows testId="fnolab-audit-risk" rows={[
                { k: "Outcome", v: d.outcome ?? "not recorded" },
                { k: "Path · mode", v: `${d.path ?? d.action ?? "—"} · ${d.mode ?? "mode not recorded"}` },
                { k: "Reasons", v: d.reasons.length ? d.reasons.map((r) => (r.code ? `${r.message} (${r.code})` : r.message)).join("; ") : "None (allowed)" },
                { k: "Checks", v: d.checks.length ? d.checks.map((c) => `${c.check} ${c.status ?? "?"}`).join(", ") : "Not recorded on this row" },
                { k: "Policy", v: d.policyVersion ?? "not recorded" },
                { k: "Inputs hash", v: mono(d.inputsHash ?? "not recorded") },
                { k: "Correlation id", v: mono(d.correlationId ?? "not recorded") },
                { k: "Capital at risk", v: d.capitalAtRiskRs == null ? "—" : fmtINR(d.capitalAtRiskRs) },
                { k: "Recorded by", v: d.source ?? "source not recorded" },
              ]} />
            )}
            <span data-testid={sel.status === "not_recorded" ? "fnolab-audit-gap" : "fnolab-audit-step-detail"} style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
              {sel.status === "not_recorded" && sel.backlog ? `Not recorded today (${sel.backlog}). ` : ""}{sel.detail}
            </span>
            {sel.ref && <span data-testid="fnolab-audit-step-ref" style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>ref {sel.ref}</span>}
          </div>
        )}
        <ReplayPanel d={d} />
      </div>
    </Section>
  );
}

function ControlChanges() {
  const q = useRiskAudit();
  let body;
  if (q.isPending) body = <LoadingBlock label="Loading control changes" rows={2} />;
  else if (q.isError) body = <QueryProblem what="Control changes" error={q.error} onRetry={() => void q.refetch()} />;
  else if (!q.data.events.length) body = <span style={quiet}>No control has been changed on this account.</span>;
  else {
    body = (
      <div data-testid="fnolab-audit-controls" className="flex flex-col">
        {q.data.events.map((e: RiskAuditEvent) => (
          <div key={e.id} data-testid="fnolab-audit-control" className="grid" style={{ gridTemplateColumns: "minmax(84px,auto) minmax(0,1fr)", gap: 12, padding: "9px 0", borderTop: "1px solid var(--cp-line)" }}>
            <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-3)" }}>{at(e.at)}</span>
            <span className="flex flex-col" style={{ gap: 2, minWidth: 0 }}>
              <span style={{ fontSize: 13 }}>
                {e.field ?? e.action ?? "control"}: {e.before == null ? "?" : e.before ? "on" : "off"} → {e.after == null ? "?" : e.after ? "on" : "off"}
              </span>
              <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>
                {e.actor ?? "actor not recorded"}{e.reason ? ` · “${e.reason}”` : ""}
              </span>
            </span>
          </div>
        ))}
      </div>
    );
  }
  return (
    <Section title="Control changes" note={q.data?.appendOnly ? "Append only" : undefined}>
      {body}
    </Section>
  );
}

export function Audit() {
  const q = useAuditDecisions();
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const list = q.data ?? [];
  const shown = list.filter((d) => matchesDecision(d, search));
  const sel = shown.find((d) => d.id === picked) ?? shown[0] ?? null;

  return (
    <div className="flex flex-col" style={{ gap: 14 }}>
      <SourceCards items={SOURCES} />
      <label className="flex flex-col" style={{ gap: 6, maxWidth: 460 }}>
        <span className="cp-eyebrow">Search by decision id or correlation id</span>
        <input data-testid="fnolab-audit-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="decision id or correlation id" style={{ ...INPUT_STYLE, width: "100%" }} />
      </label>
      {q.isPending && <LoadingBlock label="Loading risk decisions" />}
      {q.isError && <QueryProblem what="Risk decisions" error={q.error} onRetry={() => void q.refetch()} />}
      {q.isSuccess && !list.length && (
        <EmptyBlock title="No risk decisions recorded" body="Decisions appear here when the policy gate checks a paper write on this account, or when a control blocks one." />
      )}
      {q.isSuccess && list.length > 0 && (
        <div className="flex flex-wrap" style={{ gap: 12, alignItems: "flex-start" }}>
          <div style={{ flex: "1 1 320px", minWidth: 0 }}>
            <Section title="Risk decisions" note={`${shown.length} of ${list.length}`}>
              <div data-testid="fnolab-audit-decisions" className="flex flex-col" style={{ gap: 6, minWidth: 0 }}>
                {shown.length
                  ? shown.map((d) => <DecisionRow key={d.id} d={d} on={sel?.id === d.id} onPick={() => setPicked(d.id)} />)
                  : <span data-testid="fnolab-audit-nomatch" style={quiet}>No decision matches “{search.trim()}”.</span>}
              </div>
            </Section>
          </div>
          <div style={{ flex: "1.4 1 420px", minWidth: 0 }}>{sel && <Lineage key={sel.id} d={sel} />}</div>
        </div>
      )}
      <ControlChanges />
    </div>
  );
}
