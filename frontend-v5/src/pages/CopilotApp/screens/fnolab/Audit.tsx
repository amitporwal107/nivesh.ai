/**
 * F&O lab · 12 Audit & Decision Replay (?screen=audit). Design: the "Audit & Decision Replay" screen of Nivesh F&O Desk,
 * today state.
 *
 *   GET /api/risk/decisions?limit=200   every recorded risk decision, newest first (governance-data.ts useAuditDecisions):
 *                                       outcome, path, symbol, time, correlation id, policy version, inputs hash, checks
 *   GET /api/risk/audit?limit=          control changes, append only (tradingdesk/risk-controls.ts useRiskAudit)
 *
 * A search box filters by decision id or correlation id. Selecting a decision shows the PRD's ten-step lineage: today
 * only the risk decision is recorded (its risk_decisions row, which is also the audit record); every other step reads
 * "Not recorded" with the backlog item that records it. There is no replay: it needs the snapshot store (P0.3).
 */
import { useState } from "react";
import { EmptyBlock, LoadingBlock, Pill, Section, fmtINR } from "../../components/ui";
import { INPUT_STYLE, QueryProblem } from "../trading/parts";
import { stampIst } from "../tradingdesk/overview-data";
import { useRiskAudit, type RiskAuditEvent } from "../tradingdesk/risk-controls";
import { isBlocked, matchesDecision, useAuditDecisions, type AuditDecision } from "./governance-data";
import { KvRows, SourceCards, quiet, type SourceItem } from "./parts";

const SOURCES: SourceItem[] = [
  { k: "Decision store", sub: "risk_decisions · gate decisions with correlation id · P0.3 for the rest", tone: "amber" },
  { k: "Kill-switch audit", sub: "risk_control_audit · exists", tone: "mint" },
  { k: "Paper entry hashes", sub: "entry_record_hash · exists", tone: "mint" },
  { k: "Snapshot linkage", sub: "Missing · P0.3", tone: "danger" },
];

const at = (iso: string | null) => stampIst(iso) ?? "time not recorded";

type NodeId = "snapshot" | "instrument" | "regime" | "proposal" | "schema" | "pricing" | "risk" | "cert" | "oms" | "audit";

const NODES: Array<{ id: NodeId; k: string; tag: string | null; why: string }> = [
  { id: "snapshot", k: "Market snapshot", tag: "P0.3", why: "No market data snapshot is stored with a decision, so the prices it saw cannot be recovered." },
  { id: "instrument", k: "Instrument master", tag: "P0.3", why: "No versioned instrument master is linked; the gate reads the day's exchange lot size but stores no reference to it." },
  { id: "regime", k: "Regime", tag: "P0.3", why: "No regime snapshot is stored with a decision." },
  { id: "proposal", k: "Agent proposal", tag: "P0.3", why: "There is no F&O agent, so no proposal exists to record." },
  { id: "schema", k: "Schema check", tag: "P0.3", why: "No separate strategy-schema validator exists; the payoff engine's own validation is not recorded with the decision." },
  { id: "pricing", k: "Pricing & margin", tag: "P0.3", why: "No pricing result is stored; the decision keeps only the capital at risk the gate worked out." },
  { id: "risk", k: "Risk decision", tag: null, why: "" },
  { id: "cert", k: "Certification", tag: "P3.1", why: "No certification record exists to match against." },
  { id: "oms", k: "OMS", tag: "P3.2", why: "The OMS paper store is not linked to gate decisions, and there is no broker order." },
  { id: "audit", k: "Audit record", tag: null, why: "" },
];

const recorded = (id: NodeId) => id === "risk" || id === "audit";

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

function Lineage({ d }: { d: AuditDecision }) {
  const [node, setNode] = useState<NodeId>("risk");
  const sel = NODES.find((n) => n.id === node) ?? NODES[6];
  return (
    <Section title={`Lineage · ${d.id}`} note={at(d.at)}>
      <div className="flex flex-col" style={{ gap: 14 }}>
        <div data-testid="fnolab-audit-lineage" className="cp-scroll flex" style={{ gap: 6, overflowX: "auto", paddingBottom: 4 }}>
          {NODES.map((n) => {
            const ok = recorded(n.id);
            const on = n.id === node;
            return (
              <button key={n.id} type="button" data-testid="fnolab-audit-node" data-node={n.id} data-recorded={String(ok)} aria-pressed={on} onClick={() => setNode(n.id)}
                className="flex flex-col" style={{ flex: "1 0 112px", textAlign: "left", gap: 5, padding: 10, borderRadius: 10, border: `1px solid ${on ? "var(--mint-line)" : "var(--cp-line)"}`, background: on ? "var(--bg-2)" : "transparent", color: "var(--cp-ink)", opacity: ok ? 1 : 0.7, cursor: "pointer" }}>
                <span className="flex items-center" style={{ gap: 6, fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase", color: ok ? "var(--mint)" : "var(--cp-ink-4)" }}>
                  <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: ok ? "var(--mint)" : "var(--cp-ink-4)" }} />
                  {ok ? "Recorded" : `Not recorded · ${n.tag}`}
                </span>
                <span style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.25 }}>{n.k}</span>
              </button>
            );
          })}
        </div>

        <div data-testid="fnolab-audit-node-detail" data-node={sel.id} className="flex flex-col" style={{ gap: 10 }}>
          <span className="cp-eyebrow" style={{ color: recorded(sel.id) ? "var(--mint)" : "var(--cp-ink-3)" }}>{sel.k}</span>
          {sel.id === "risk" && (
            <KvRows testId="fnolab-audit-risk" rows={[
              { k: "Outcome", v: d.outcome ?? "not recorded" },
              { k: "Path · mode", v: `${d.path ?? d.action ?? "—"} · ${d.mode ?? "mode not recorded"}` },
              { k: "Reasons", v: d.reasons.length ? d.reasons.map((r) => (r.code ? `${r.message} (${r.code})` : r.message)).join("; ") : "None (allowed)" },
              { k: "Checks", v: d.checks.length ? d.checks.map((c) => `${c.check} ${c.status ?? "?"}`).join(", ") : "Not recorded on this row" },
              { k: "Policy", v: d.policyVersion ?? "not recorded" },
              { k: "Inputs hash", v: <span style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>{d.inputsHash ?? "not recorded"}</span> },
              { k: "Correlation id", v: <span style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>{d.correlationId ?? "not recorded"}</span> },
              { k: "Capital at risk", v: d.capitalAtRiskRs == null ? "—" : fmtINR(d.capitalAtRiskRs) },
              { k: "Recorded by", v: d.source ?? "source not recorded" },
            ]} />
          )}
          {sel.id === "audit" && (
            <span style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
              The decision's own row in risk_decisions is its audit record. It is append-only by convention: the code only inserts, and nothing in the database enforces it.
            </span>
          )}
          {!recorded(sel.id) && (
            <span data-testid="fnolab-audit-gap" style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
              Not recorded today ({sel.tag}). {sel.why}
            </span>
          )}
          <span data-testid="fnolab-audit-replay" style={{ padding: "10px 12px", borderRadius: 10, border: "1px dashed var(--line-3)", fontSize: 13, color: "var(--cp-ink-3)" }}>
            Replay needs the snapshot store (P0.3). Without the market snapshot and versions, the decision cannot be re-run.
          </span>
        </div>
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
