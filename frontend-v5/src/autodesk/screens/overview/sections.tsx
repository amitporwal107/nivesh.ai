/**
 * Sections of the Desk overview below the tiles, copied from TDOverview.dc.html: "Needs you", the P&L card, "Broker &
 * data feeds", "Agents · current task" and "Recent agent activity". Each renders real API data or an honest state.
 */
import type { CSSProperties, KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import type { UseQueryResult } from "@tanstack/react-query";
import { errorText } from "../../api";
import { agentName, dateShort, humanize, num, rs } from "../../format";
import type { IndexQuotes } from "../../hooks";
import { screenById } from "../../nav";
import type { AgentStatus, AgentTaskRow, ApprovalRow, DeskStatus, RiskAssessmentRow, TradePlanDetail } from "../../types";
import { Empty, ErrorBox, Loading, PhaseNote, SectionHead, TableHead, TableRow } from "../../ui";
import {
  ACTIVE_STATES, ACTIVITY_LIMIT, ACTIVITY_ROWS, AGENT_ORDER, premarketOf, refId, taskLabel, taskTime, uniqueAgents,
  useAssessments, usePendingPlans, useRecentApprovals, whenIST,
} from "./data";

const box: CSSProperties = { border: "1px solid var(--line)", borderRadius: 14, background: "var(--bg-1)", overflow: "hidden" };
const onKey = (go: () => void) => (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } };

// ── Needs you · ranked by ₹ at risk ──────────────────────────────────────────────────────────────────────────────────

export function NeedsYou({ pending, mobile, now }: { pending: UseQueryResult<ApprovalRow[]>; mobile: boolean; now: number }) {
  const nav = useNavigate();
  const rows = pending.data ?? [];
  const plans = usePendingPlans(rows);
  const ranked = rows
    .map((a, i) => ({ a, q: plans[i] as UseQueryResult<TradePlanDetail> }))
    .map(({ a, q }) => ({ a, q, loss: num(q.data?.body?.max_loss_rs) }))
    .sort((x, y) => (y.loss ?? -1) - (x.loss ?? -1))
    .slice(0, 3);
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <SectionHead label="Needs you · ranked by ₹ at risk" link="Approval queue" to={screenById("approvals").path} />
      <div data-testid="needs-you" style={{ ...box, boxShadow: "var(--shadow-card)" }}>
        {pending.isLoading && <div style={{ padding: 16 }}><Loading label="Loading pending approvals" rows={2} /></div>}
        {pending.error && <div style={{ padding: 12 }}><ErrorBox error={pending.error} what="pending approvals" onRetry={() => pending.refetch()} /></div>}
        {ranked.map(({ a, q, loss }, i) => {
          const go = () => nav(`${screenById("approvals").path}/${encodeURIComponent(a.approval_id)}`);
          const p = q.data;
          const reasons = Array.isArray(a.body?.reasons) ? a.body.reasons.join("; ") : "";
          const t = p
            ? `${p.instrument} ${humanize(p.strategy_type).toLowerCase()} on paper needs your sign-off`
            : `${a.trade_id} v${a.plan_version} needs your sign-off`;
          const s = [a.approval_id, reasons, a.expires_at ? `expires ${whenIST(a.expires_at, now)}` : null,
            q.error ? `plan could not be loaded: ${errorText(q.error)}` : null].filter(Boolean).join(" · ");
          const c = "var(--amber)";
          return (
            <div key={a.approval_id} data-testid="needs-row" role="button" tabIndex={0} onClick={go} onKeyDown={onKey(go)} className="ad-hover"
              style={{ display: "flex", alignItems: "center", gap: 14, padding: mobile ? "14px 14px" : "16px 20px", borderTop: `1px solid ${i ? "var(--line)" : "transparent"}`, cursor: "pointer", transition: "all .15s ease" }}>
              <span style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1, color: "var(--ink-4)", width: 28, flex: "none" }}>{`0${i + 1}`}</span>
              <span className="nv-dot" style={{ flex: "none", width: 8, height: 8, background: c }} />
              <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 15, fontWeight: 500, lineHeight: 1.35, overflowWrap: "anywhere" }}>{t}</span>
                <span data-testid="needs-sub" style={{ fontSize: 12.5, lineHeight: 1.45, color: q.error ? "var(--danger)" : "var(--ink-3)", overflowWrap: "anywhere" }}>{s}</span>
              </div>
              <div style={{ flex: "none", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
                <span data-testid="needs-value" className="nv-num" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1, color: c }}>
                  {q.isLoading ? "…" : loss == null ? "—" : rs(loss)}
                </span>
                <span className="nv-eyebrow" style={{ fontSize: 9 }}>Max loss</span>
              </div>
            </div>
          );
        })}
        {!pending.isLoading && !pending.error && rows.length === 0 && (
          <div data-testid="needs-none" style={{ padding: "18px 20px", fontSize: 14, color: "var(--ink-3)" }}>Nothing is waiting on you.</div>
        )}
      </div>
    </section>
  );
}

// ── Net P&L card (Phase 2) ───────────────────────────────────────────────────────────────────────────────────────────

export function PnlCard() {
  const nav = useNavigate();
  const go = () => nav(screenById("pnl").path);
  return (
    <div data-testid="pnl-card" role="link" tabIndex={0} onClick={go} onKeyDown={onKey(go)}
      style={{ cursor: "pointer", display: "flex", flexDirection: "column", gap: 14, padding: "20px 22px", borderRadius: 14, border: "1px solid var(--line)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <span className="nv-eyebrow">Net P&amp;L today · after est. charges</span>
        <span style={{ fontSize: 12.5, color: "var(--mint)" }}>Real-time P&amp;L ›</span>
      </div>
      <PhaseNote testId="pnl-phase-note">
        Net P&amp;L after estimated charges, its curve through the session and the split by account come with paper execution
        (Phase 2). Nothing is executed in Phase 1, so there is no P&amp;L to show.
      </PhaseNote>
    </div>
  );
}

// ── Broker & data feeds ──────────────────────────────────────────────────────────────────────────────────────────────

interface FeedRow { id: string; n: string; s: string; c: string; note?: string }

function kiteRow(q: IndexQuotes | undefined, err: unknown, now: number): FeedRow {
  const n = "Kite feed · NSE indices (read-only)";
  if (err) return { id: "kite", n, s: "UNAVAILABLE", c: "var(--danger)", note: errorText(err) };
  if (!q) return { id: "kite", n, s: "…", c: "var(--ink-3)" };
  const age = q.dataAt ? Math.max(0, Math.round((now - new Date(q.dataAt).getTime()) / 1000)) : null;
  switch (q.mode) {
    case "live": return q.stale ? { id: "kite", n, s: "DELAYED", c: "var(--amber)" } : { id: "kite", n, s: age != null ? `LIVE · ${age}s` : "LIVE", c: "var(--mint)" };
    case "delayed": return { id: "kite", n, s: "DELAYED", c: "var(--amber)" };
    case "closed": return { id: "kite", n, s: "MARKET CLOSED", c: "var(--ink-3)" };
    case "expired": return { id: "kite", n, s: "LOGIN NEEDED", c: "var(--amber)" };
    case "not_connected": return { id: "kite", n, s: "NOT CONNECTED", c: "var(--danger)" };
    case "disabled": return { id: "kite", n, s: "OFF", c: "var(--ink-3)" };
    default: return { id: "kite", n, s: "UNKNOWN", c: "var(--ink-3)" };
  }
}

const PM_COLOR: Record<string, string> = { READY: "var(--mint)", DEGRADED: "var(--amber)", BLOCKED: "var(--danger)" };

export function FeedsCard({ st, quotes, quotesError, now }: { st: DeskStatus | undefined; quotes: IndexQuotes | undefined; quotesError: unknown; now: number }) {
  const md = st?.market_data;
  const pm = premarketOf(st);
  const eod = (label: string, id: string, d: string | undefined, withNote: boolean): FeedRow => {
    if (!st) return { id, n: label, s: "—", c: "var(--ink-3)" };
    if (md?.error) return { id, n: label, s: "ERROR", c: "var(--danger)", note: withNote ? md.error : undefined };
    return d ? { id, n: label, s: `SESSION ${dateShort(d).toUpperCase()}`, c: "var(--ink-2)" } : { id, n: label, s: "NO SESSION", c: "var(--amber)" };
  };
  const rows: FeedRow[] = [
    kiteRow(quotes, quotesError, now),
    eod("Desk market data · cash EOD", "cash", md?.latest_cash_session, true),
    eod("Desk market data · F&O EOD", "fno", md?.latest_fno_session, false),
    !st ? { id: "premarket", n: "Pre-market check", s: "—", c: "var(--ink-3)" }
      : pm?.status
        ? { id: "premarket", n: "Pre-market check", s: `${pm.status}${pm.sessionDate ? ` · ${dateShort(pm.sessionDate).toUpperCase()}` : ""}`, c: PM_COLOR[pm.status] ?? "var(--ink-3)", note: pm.reason ?? undefined }
        : { id: "premarket", n: "Pre-market check", s: "NOT RUN YET", c: "var(--ink-3)" },
    { id: "paper", n: "Paper engine", s: "PHASE 2", c: "var(--ink-3)" },
  ];
  return (
    <div data-testid="feeds-card" style={{ display: "flex", flexDirection: "column", gap: 6, padding: "18px 22px", borderRadius: 14, border: "1px solid var(--line)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)", minWidth: 0 }}>
      <div style={{ paddingBottom: 6 }}><SectionHead label="Broker & data feeds" link="Reliability" to={screenById("fleet").path} /></div>
      {rows.map((f) => (
        <div key={f.id} data-testid={`feed-${f.id}`} style={{ display: "flex", flexDirection: "column", gap: 4, padding: "8px 0", borderTop: "1px solid var(--line)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="nv-dot" style={{ flex: "none", background: f.c }} />
            <span style={{ flex: 1, minWidth: 0, fontSize: 13.5 }}>{f.n}</span>
            <span data-testid={`feed-${f.id}-status`} style={{ fontFamily: "var(--mono)", fontSize: 11, color: f.c, textAlign: "right" }}>{f.s}</span>
          </div>
          {f.note && <span data-testid={`feed-${f.id}-note`} style={{ paddingLeft: 16, fontSize: 11.5, lineHeight: 1.45, color: "var(--danger)", overflowWrap: "anywhere" }}>{f.note}</span>}
        </div>
      ))}
      <span data-testid="feeds-broker-note" style={{ paddingTop: 8, borderTop: "1px solid var(--line)", fontSize: 12, lineHeight: 1.5, color: "var(--ink-3)" }}>
        Broker connections are not part of Phase 1: brokers stay read-only and the desk's accounts are paper accounts.
      </span>
    </div>
  );
}

// ── Agents · current task ────────────────────────────────────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  BUSY: "var(--mint)", IDLE: "var(--ink-2)", SCALING: "var(--indigo)", DEGRADED: "var(--amber)", MAINTENANCE: "var(--amber)",
  QUARANTINED: "var(--danger)", OFFLINE: "var(--danger)",
};

function currentTask(q: UseQueryResult<AgentTaskRow[]>, now: number): { text: string; error?: boolean } {
  if (q.isLoading) return { text: "Loading tasks…" };
  if (q.error) return { text: `Could not load tasks: ${errorText(q.error)}`, error: true };
  const all = q.data ?? [];
  const desk = all.filter((t) => !t.simulation_id);
  const t = desk[0];
  if (!t) return { text: all.length ? `No desk task among its last ${ACTIVITY_LIMIT} tasks (the rest are simulation runs).` : "No desk task yet." };
  const state = humanize(t.state).toLowerCase();
  if (ACTIVE_STATES.has(t.state)) return { text: `Working on: ${taskLabel(t)} · ${state} since ${whenIST(t.created_at, now)}` };
  const why = t.error ?? t.result_summary;
  return { text: `Last: ${taskLabel(t)} · ${state} ${whenIST(taskTime(t), now)}${why ? ` · ${why}` : ""}` };
}

export function AgentsNow({ st, activities, now }: { st: DeskStatus | undefined; activities: UseQueryResult<AgentTaskRow[]>[]; now: number }) {
  const nav = useNavigate();
  const go = () => nav(screenById("agents").path);
  const reg = uniqueAgents(st);
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <SectionHead label="Agents · current task" link="Command centre" to={screenById("agents").path} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,200px),1fr))", gap: 10 }}>
        {AGENT_ORDER.map((k, i) => {
          const r = reg.find((a) => a.agent_key === k);
          const status: AgentStatus | null = r?.status ?? null;
          const c = status ? STATUS_COLOR[status] ?? "var(--ink-3)" : "var(--ink-3)";
          const task = currentTask(activities[i], now);
          return (
            <div key={k} data-testid={`agent-card-${k}`} role="link" tabIndex={0} onClick={go} onKeyDown={onKey(go)} className="ad-hover-line"
              style={{ cursor: "pointer", display: "flex", flexDirection: "column", gap: 8, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--line)", background: "var(--bg-1)", minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="nv-dot" style={{ background: c }} />
                <span data-testid="agent-status" style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", color: c }}>{status ?? (st ? "NOT REGISTERED" : "—")}</span>
              </div>
              <span style={{ fontSize: 14, fontWeight: 500, lineHeight: 1.3 }}>{agentName(k)}</span>
              <span data-testid="agent-task" style={{ fontSize: 12, lineHeight: 1.45, color: task.error ? "var(--danger)" : "var(--ink-3)", overflowWrap: "anywhere" }}>{task.text}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ── Recent agent activity ────────────────────────────────────────────────────────────────────────────────────────────

const AGENT_COLOR: Record<string, string> = {
  AI_TRADER: "var(--indigo)", TRADING_ASSISTANT: "var(--mint)", RISK_OPS: "var(--mint)", MIDDLE_OFFICE: "var(--ink-2)", TECH_SUPPORT: "var(--ink-2)",
};
const COLS = "72px 120px minmax(0,1.4fr) minmax(0,1.3fr) 110px minmax(0,0.9fr)";

interface ActRow { key: string; agent: string; t: AgentTaskRow }

export function Activity({ activities, mobile, now }: { activities: UseQueryResult<AgentTaskRow[]>[]; mobile: boolean; now: number }) {
  const rows: ActRow[] = AGENT_ORDER.flatMap((k, i) => (activities[i].data ?? []).filter((t) => !t.simulation_id).map((t) => ({ key: `${k}:${t.task_id}`, agent: k, t })))
    .sort((a, b) => new Date(taskTime(b.t)).getTime() - new Date(taskTime(a.t)).getTime())
    .slice(0, ACTIVITY_ROWS);
  const approvalIds = rows.map((r) => (r.t.task_type === "REVIEW_FOR_APPROVAL" ? refId(r.t.result_ref, "approval") : null));
  const assessmentIds = rows.map((r) => (r.t.task_type === "ASSESS_RISK" ? refId(r.t.result_ref, "assessment") : null));
  const approvals = useRecentApprovals(approvalIds.some(Boolean));
  const aIds = assessmentIds.filter((x): x is string => !!x);
  const assessments = useAssessments(aIds);
  const asmt = (id: string | null) => (id ? (assessments[aIds.indexOf(id)] as UseQueryResult<RiskAssessmentRow> | undefined) : undefined);

  const loading = activities.some((q) => q.isLoading);
  const failed = AGENT_ORDER.filter((_, i) => activities[i].error);
  const lookupErrors = [
    approvals.error ? `approval decisions: ${errorText(approvals.error)}` : null,
    ...aIds.map((id, i) => (assessments[i]?.error ? `${id}: ${errorText(assessments[i].error)}` : null)),
  ].filter(Boolean);

  const cells = (r: ActRow, i: number) => {
    const appr = approvalIds[i] ? approvals.data?.find((a) => a.approval_id === approvalIds[i]) : undefined;
    const ra = asmt(assessmentIds[i])?.data;
    let policy = "—";
    let qty = "—";
    if (appr) {
      const b = appr.body as Record<string, unknown>;
      if (b.policy_id) policy = `${String(b.policy_id)} v${b.policy_version ?? "?"}`;
      const scope = b.scope as Record<string, unknown> | null | undefined;
      if (scope && scope.max_lots != null) qty = `max ${String(scope.max_lots)} lots`;
    } else if (ra) {
      if (ra.policy_id) policy = `${ra.policy_id} v${ra.policy_version ?? "?"}`;
      const s = ra.body?.sizing as Record<string, unknown> | null | undefined;
      if (s && s.proposed_size != null) qty = `allowed ${String(s.allowed_size ?? "—")} of ${String(s.proposed_size)} ${String(s.unit ?? "")}`.trim();
    }
    const state = r.t.state === "COMPLETED" ? "" : ` (${humanize(r.t.state).toLowerCase()})`;
    return {
      t: whenIST(taskTime(r.t), now),
      a: agentName(r.agent),
      c: AGENT_COLOR[r.agent] ?? "var(--ink-2)",
      w: `${taskLabel(r.t)}${state}`,
      y: r.t.error ?? r.t.result_summary ?? "—",
      p: policy,
      q: qty,
    };
  };

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <SectionHead label="Recent agent activity · what, why, which policy, what quantity" link="Audit trail" to={screenById("middle").path} />
      <div data-testid="activity" style={box}>
        {loading && <div style={{ padding: 16 }}><Loading label="Loading agent activity" rows={3} /></div>}
        {!loading && failed.length === AGENT_ORDER.length && (
          <div style={{ padding: 12 }}><ErrorBox error={activities[0].error} what="agent activity" onRetry={() => activities.forEach((q) => q.refetch())} /></div>
        )}
        {!loading && failed.length > 0 && failed.length < AGENT_ORDER.length && (
          <div data-testid="activity-partial-error" style={{ padding: "10px 18px", fontSize: 12.5, color: "var(--danger)" }}>
            Activity of {failed.map(agentName).join(", ")} could not be loaded: {errorText(activities[AGENT_ORDER.indexOf(failed[0])].error)}
          </div>
        )}
        {!loading && failed.length < AGENT_ORDER.length && rows.length === 0 && <Empty testId="activity-empty">No agent activity on the desk yet.</Empty>}
        {!loading && rows.length > 0 && !mobile && (
          <>
            <TableHead cols={COLS} labels={["Time", "Agent", "What happened", "Why", "Policy", "Quantity"]} />
            {rows.map((r, i) => {
              const x = cells(r, i);
              return (
                <TableRow key={r.key} cols={COLS} testId="activity-row">
                  <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)" }}>{x.t}</span>
                  <span style={{ fontSize: 12, color: x.c }}>{x.a}</span>
                  <span style={{ overflowWrap: "anywhere" }}>{x.w}</span>
                  <span style={{ color: "var(--ink-2)", overflowWrap: "anywhere" }}>{x.y}</span>
                  <span title={x.p} style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{x.p}</span>
                  <span style={{ fontSize: 12.5, color: "var(--ink-2)" }}>{x.q}</span>
                </TableRow>
              );
            })}
          </>
        )}
        {!loading && rows.length > 0 && mobile && rows.map((r, i) => {
          const x = cells(r, i);
          return (
            <div key={r.key} data-testid="activity-card" style={{ display: "flex", flexDirection: "column", gap: 5, padding: "13px 16px", borderTop: `1px solid ${i ? "var(--line)" : "transparent"}` }}>
              <div style={{ display: "flex", gap: 10, alignItems: "baseline", minWidth: 0 }}>
                <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)", flex: "none" }}>{x.t}</span>
                <span style={{ fontSize: 12, color: x.c, flex: "none" }}>{x.a}</span>
                <span style={{ flex: 1 }} />
                <span title={x.p} style={{ fontFamily: "var(--mono)", fontSize: 9.5, color: "var(--ink-3)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{x.p}</span>
              </div>
              <span style={{ fontSize: 14, lineHeight: 1.4, overflowWrap: "anywhere" }}>{x.w}</span>
              <span style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--ink-3)", overflowWrap: "anywhere" }}>{x.y} · {x.q}</span>
            </div>
          );
        })}
        {lookupErrors.length > 0 && (
          <div data-testid="activity-lookup-error" style={{ padding: "10px 18px", borderTop: "1px solid var(--line)", fontSize: 12, color: "var(--danger)", overflowWrap: "anywhere" }}>
            Policy and quantity could not be loaded for {lookupErrors.join("; ")}
          </div>
        )}
      </div>
    </section>
  );
}

