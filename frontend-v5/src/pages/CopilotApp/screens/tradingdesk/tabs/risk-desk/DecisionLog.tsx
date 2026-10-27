/**
 * Risk Desk › Decision log (?tab=risk&view=log).
 *
 *   GET  /api/risk/decisions?limit=200      every allow / reduce / block on this account, newest first, with its
 *                                           reasons, the size asked and approved, the risk estimate (loss at the stop,
 *                                           costs, gap stress), the budgets it was judged against, and the policy,
 *                                           limits and estimate versions (fnolab/governance-data.ts useAuditDecisions)
 *   GET  /api/risk/decisions/{id}/lineage   a row's "Lineage & replay" opens its lineage steps (fnolab/Audit.tsx Lineage)
 *   POST /api/risk/decisions/{id}/replay    and a replay on the stored snapshot; it writes nothing
 *
 * Rows use RiskControls DecisionItem (outcome, path, symbol, reasons, correlation id); this view adds the estimate,
 * versions, budgets and the lineage below each.
 */
import { useState } from "react";
import { Btn, EmptyBlock, LoadingBlock, fmtINR, fmtNum, fmtPct } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { QueryProblem } from "../../../trading/parts";
import { Lineage } from "../../../fnolab/Audit";
import { useAuditDecisions, type AuditDecision } from "../../../fnolab/governance-data";
import { KvRows } from "../../../fnolab/parts";
import { Card, DecisionItem } from "../../RiskControls";
import { ViewHead, quiet } from "./parts";

const kind = (o: string | null) => {
  const k = (o ?? "").toLowerCase();
  return k.startsWith("allow") ? "allow" : k.startsWith("reduc") ? "reduce" : k.startsWith("block") || k === "denied" ? "block" : "other";
};

function sizeText(d: AuditDecision): string | null {
  if (d.requestedQty != null) {
    return d.approvedQty != null && d.approvedQty !== d.requestedQty
      ? `${fmtNum(d.requestedQty)} → ${fmtNum(d.approvedQty)} shares`
      : `${fmtNum(d.requestedQty)} shares`;
  }
  if (d.requestedLots != null) {
    return d.approvedLots != null && d.approvedLots !== d.requestedLots
      ? `${fmtNum(d.requestedLots)} → ${fmtNum(d.approvedLots)} lots per leg`
      : `${fmtNum(d.requestedLots)} lots per leg`;
  }
  return null;
}

function estimateText(d: AuditDecision): string {
  const e = d.estimate;
  if (!e || e.total == null) return "Estimate: not sized";
  const parts = [`stop ${fmtINR(e.gross)}`, `costs ${fmtINR(e.costs)}`, `gap ${fmtINR(e.gapStress)}`].join(" + ");
  return `Estimated risk ${fmtINR(e.total)} (${parts})`;
}

/** The budgets the decision recorded, labelled; only those present. */
function budgetRows(d: AuditDecision): Array<{ k: string; v: string }> {
  const b = d.budget;
  const rs = (k: string) => (b[k] == null ? null : fmtINR(b[k]));
  const p = (k: string) => (b[k] == null ? null : fmtPct(b[k], { digits: 2 }));
  const rows: Array<{ k: string; v: string | null }> = [
    { k: "Per-trade budget", v: rs("per_trade_budget_rs") && `${rs("per_trade_budget_rs")}${b.per_trade_pct != null ? ` (${fmtPct(b.per_trade_pct, { digits: 2 })} of equity)` : ""}` },
    { k: "Open risk", v: b.open_risk_cap_rs == null ? null : `${rs("open_risk_before_rs") ?? "unknown"} before → ${rs("open_risk_after_rs") ?? "—"} after, of ${rs("open_risk_cap_rs")}` },
    { k: "Position cap", v: rs("position_cap_rs") },
    { k: "Sector", v: b.sector_cap_rs == null ? null : `${d.sector ?? "sector"} ${rs("sector_before_rs") ?? "unknown"} of ${rs("sector_cap_rs")}` },
    { k: "Open positions", v: b.max_open_positions == null ? null : `${b.open_positions_before ?? "unknown"} of ${b.max_open_positions}` },
    { k: "Reward:risk", v: b.reward_risk == null ? null : `${b.reward_risk.toFixed(2)} after costs` },
    { k: "Day's loss", v: b.day_loss_pct_limit == null ? null : `${p("day_loss_pct") ?? "unknown"} of ${fmtPct(b.day_loss_pct_limit, { digits: 0 })}` },
    { k: "Week's loss", v: b.week_loss_pct_limit == null ? null : `${p("week_loss_pct") ?? "unknown"} of ${fmtPct(b.week_loss_pct_limit, { digits: 0 })}` },
    { k: "Drawdown", v: b.drawdown_pct_limit == null ? null : `${p("drawdown_pct") ?? "unknown"} of ${fmtPct(b.drawdown_pct_limit, { digits: 0 })}` },
    { k: "Paper cash", v: b.funding_rs == null ? null : `${rs("funding_rs")} needed, ${rs("available_rs") ?? "unknown"} available` },
  ];
  return rows.flatMap((r) => (r.v ? [{ k: r.k, v: r.v }] : []));
}

function Row({ d, first, open, onToggle }: { d: AuditDecision; first: boolean; open: boolean; onToggle: () => void }) {
  const size = sizeText(d);
  const budgets = budgetRows(d);
  return (
    <DecisionItem d={d} first={first}>
      <span data-testid="risk-decision-estimate" className="cp-num" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
        {size ? `${size} · ` : ""}{estimateText(d)}
      </span>
      <span data-testid="risk-decision-versions" className="cp-mono-note" style={{ overflowWrap: "anywhere" }}>
        policy {d.policyVersion ?? "not recorded"} · limits {d.limitsVersion ?? "not recorded"}{d.estimateVersion ? ` · ${d.estimateVersion}` : ""}
      </span>
      <span>
        <Btn variant="ghost" data-testid="risk-decision-open" aria-expanded={open} onClick={onToggle} style={{ padding: "4px 10px" }}>
          {open ? "Close" : "Budgets, lineage & replay"}
        </Btn>
      </span>
      {open && (
        <div data-testid="risk-decision-detail" className="flex min-w-0 flex-col" style={{ gap: 12, padding: "12px 0 4px" }}>
          {budgets.length
            ? <KvRows testId="risk-decision-budgets" rows={budgets} />
            : <span data-testid="risk-decision-no-budgets" style={quiet}>No budgets were recorded on this decision (an older row, or it was refused before sizing).</span>}
          <span className="cp-mono-note" style={{ overflowWrap: "anywhere" }}>decision {d.id}</span>
          <Lineage d={d} />
        </div>
      )}
    </DecisionItem>
  );
}

export function DecisionLog() {
  const { mobile } = useCopilotShell();
  const q = useAuditDecisions();
  const [open, setOpen] = useState<string | null>(null);
  const list = q.data ?? [];
  const n = { allow: 0, reduce: 0, block: 0, other: 0 };
  for (const d of list) n[kind(d.outcome)] += 1;
  const title = q.isSuccess
    ? list.length
      ? `Every risk decision is recorded: ${n.allow} allowed, ${n.reduce} reduced and ${n.block} blocked in the last ${list.length}.`
      : "Every risk decision is recorded; none yet on this account."
    : "Every risk decision is recorded.";
  return (
    <div data-testid="rd-log-view" className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
      <ViewHead view="Decision log" title={title} />
      <Card id="decisions" num="01" title="Risk decisions · append only" testId="risk-decisions">
        {q.isPending && <LoadingBlock label="Loading risk decisions" rows={3} />}
        {q.isError && <div data-testid="risk-decisions-error"><QueryProblem what="Risk decisions" error={q.error} onRetry={() => { void q.refetch(); }} /></div>}
        {q.isSuccess && (list.length === 0
          ? <div data-testid="risk-decisions-empty"><EmptyBlock title="No risk decisions yet" body="Each paper write the gate checks is recorded here, allowed or blocked." /></div>
          : (
            <ol data-testid="risk-decisions-list" className="m-0 flex flex-col p-0" style={{ listStyle: "none" }}>
              {list.map((d, i) => (
                <Row key={d.id} d={d} first={i === 0} open={open === d.id} onToggle={() => setOpen((o) => (o === d.id ? null : d.id))} />
              ))}
            </ol>
          ))}
        {q.isSuccess && list.length > 0 && (
          <span data-testid="risk-decisions-note" style={quiet}>
            Each row stores the reasons, the inputs it read and the policy and limits versions in force. Replay re-runs the checks on that record and writes nothing.
          </span>
        )}
      </Card>
    </div>
  );
}
