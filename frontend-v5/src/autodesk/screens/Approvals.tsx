/**
 * 05 · Approval queue (docs/autodesk/design/prototype/TDApprovals.dc.html).
 *
 * Left: requests waiting on a person for the desk's accounts (GET /approvals?pending=true, simulation rows left out)
 * and the decisions recorded earlier (GET /approvals?limit=100). Right: one request opened (screens/approvals/Detail).
 * Routes /approvals and /approvals/:approvalId (deep link). On a phone the list and the detail are two steps.
 *
 * Phase 1: a decision ends the plan at APPROVED / REJECTED / NEEDS_REVISION; nothing is executed. While
 * STOP_NEW_ENTRIES is active the API refuses APPROVE (409) and the screen says so; REJECT still works.
 */
import { useMemo, type CSSProperties } from "react";
import { useQueries } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { errorText } from "../api";
import { DASH, humanize, rs, timeIST, todayIST } from "../format";
import { stopEntriesOf, useAccounts, useDeskStatus, useIsMobile, useMe, useNow, usePendingApprovals } from "../hooks";
import { screenById, screenNo } from "../nav";
import type { Account, ApprovalRow, TradePlanDetail, TradePlanRow } from "../types";
import { ErrorBox, Eyebrow, Loading } from "../ui";
import { ApprovalDetail } from "./approvals/Detail";
import { NUMBER_WORDS, TONES, accountLabel, bodyOf, byExpiry, countdown, deciderName, modeOf, planShort, statusText, statusTone } from "./approvals/model";
import { planQuery, usePlanHeads, useRecentApprovals } from "./approvals/queries";

export default function ApprovalsScreen() {
  const mobile = useIsMobile();
  const { approvalId } = useParams();
  const navigate = useNavigate();
  const now = useNow(1000);
  const pendingQ = usePendingApprovals();
  const recentQ = useRecentApprovals();
  const accounts: Account[] = useAccounts().data ?? [];
  const me = useMe().data;
  const halt = stopEntriesOf(useDeskStatus().data);

  const pending = useMemo(() => [...(pendingQ.data ?? [])].sort(byExpiry), [pendingQ.data]);
  const decided = useMemo(
    () => (recentQ.data ?? []).filter((r) => !r.simulation_id && r.status !== "NEEDS_HUMAN_APPROVAL").sort((x, y) => y.created_at.localeCompare(x.created_at)),
    [recentQ.data],
  );
  const today = todayIST(new Date(now));
  const decidedToday = decided.filter((r) => todayIST(new Date(r.created_at)) === today);
  const history = (decidedToday.length ? decidedToday : decided).slice(0, 8);
  const historyLabel = decidedToday.length || !decided.length ? "Decided earlier today" : "Decided recently";

  const planQs = useQueries({ queries: pending.map((a) => planQuery(a.trade_id, a.plan_version)) });
  const headsQ = usePlanHeads(history.length > 0);
  const heads = useMemo(() => new Map((headsQ.data ?? []).map((p: TradePlanRow) => [p.trade_id, p])), [headsQ.data]);

  const selId = approvalId ?? (mobile ? null : pending[0]?.approval_id ?? history[0]?.supersedes_id ?? history[0]?.approval_id ?? null);
  const open = (id: string) => navigate(`/approvals/${encodeURIComponent(id)}`);
  const back = () => navigate("/approvals");

  const n = pending.length;
  const first = pending.find((a) => a.expires_at);
  const lapsed = first ? new Date(first.expires_at!).getTime() <= now : false;
  const loadingQueue = pendingQ.isLoading;
  const headA = loadingQueue ? "Loading the queue." : n ? `${NUMBER_WORDS[n] ?? `${n} decisions`} ${n === 1 ? "needs" : "need"} you.` : "The queue is clear.";
  const headB = loadingQueue || pendingQ.error ? "" : n
    ? first ? `The first ${lapsed ? "lapsed" : "lapses"} at ${timeIST(first.expires_at, { seconds: false })}.` : "Each one binds one plan version."
    : "Agents continue inside policy.";

  const showList = !mobile || !selId;
  const showDetail = !!selId;
  const def = screenById("approvals");

  return (
    <div data-testid="screen-approvals" style={{ display: "flex", flexDirection: "column", gap: 24, fontFamily: "var(--sans)", color: "var(--ink)" }}>
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <Eyebrow>{screenNo("approvals")} · {def.label}</Eyebrow>
          <span className="nv-pill nv-pill-amber" data-testid="pending-pill">{loadingQueue ? "…" : pendingQ.error ? "? pending" : `${n} pending`}</span>
          <span className="nv-pill">Approvals bind to one plan version</span>
        </div>
        <h1 data-testid="approvals-headline" style={{ margin: 0, fontFamily: "var(--display)", fontWeight: 400, fontSize: mobile ? 30 : 44, lineHeight: 1.06, letterSpacing: "-0.02em", textWrap: "pretty", maxWidth: 900 } as CSSProperties}>
          {headA} {headB && <em style={{ color: "var(--amber)" }}>{headB}</em>}
        </h1>
        <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.55, color: "var(--ink-3)", maxWidth: 680 }}>
          Each item has passed Risk &amp; Operations and been routed by the Middle Office. Your decision is recorded against the exact plan version,
          quantity, mode and expiry shown here; a changed plan needs a new approval.
        </p>
      </section>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 20, alignItems: "flex-start" }}>
        {showList && (
          <div data-testid="approval-list" style={{ flex: "1 1 280px", minWidth: 0, display: "flex", flexDirection: "column", gap: 10 }}>
            <span className="nv-eyebrow">Waiting on you</span>
            {loadingQueue && <Loading label="Loading the queue" rows={2} />}
            {pendingQ.error && <ErrorBox error={pendingQ.error} what="the approval queue" onRetry={() => pendingQ.refetch()} />}
            {!loadingQueue && !pendingQ.error && n === 0 && (
              <div data-testid="queue-empty" style={{ padding: "14px 16px", borderRadius: 14, border: "1px dashed var(--line-2)", fontSize: 13.5, lineHeight: 1.5, color: "var(--ink-3)" }}>
                Nothing is waiting on you. Requests appear here when the Middle Office routes a plan to a person.
              </div>
            )}
            {pending.map((a, i) => {
              const q = planQs[i];
              const plan = q?.data as TradePlanDetail | undefined;
              const b = bodyOf(plan);
              const account = accounts.find((x) => x.account_id === a.account_id);
              const mode = modeOf(account, a);
              const mt = TONES[mode.tone];
              const cd = countdown(a.expires_at, now);
              const on = a.approval_id === selId;
              return (
                <div key={a.approval_id} data-testid="approval-item" role="button" tabIndex={0} onClick={() => open(a.approval_id)} onKeyDown={(e) => { if (e.key === "Enter") open(a.approval_id); }}
                  className="ad-hover-line"
                  style={{ cursor: "pointer", display: "flex", flexDirection: "column", gap: 9, padding: "14px 16px", borderRadius: 14, border: `1px solid ${on ? "var(--line-3)" : "var(--line)"}`, background: on ? "var(--bg-2)" : "var(--bg-1)", transition: "all .15s ease" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-2)", overflowWrap: "anywhere", minWidth: 0 }}>{a.approval_id}</span>
                    <span className="nv-pill" style={{ padding: "2px 8px", fontSize: 9, color: mt[0], borderColor: mt[1] }}>{mode.label}</span>
                    <span style={{ flex: 1 }} />
                    <span className="nv-num" data-testid="item-countdown" style={{ fontFamily: "var(--mono)", fontSize: 11, color: cd.c }}>{cd.t}</span>
                  </div>
                  <span data-testid="item-short" style={{ fontSize: 14.5, fontWeight: 500, lineHeight: 1.35 }}>
                    {q?.error ? <span style={{ color: "var(--danger)", fontSize: 12.5, fontWeight: 400 }}>Plan {a.trade_id}: {errorText(q.error)}</span> : planShort(b, a.trade_id)}
                  </span>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
                    <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{accountLabel(account, a)}</span>
                    <span className="nv-num" data-testid="item-risk" title="Max loss" style={{ fontFamily: "var(--display)", fontSize: 20, color: "var(--ink)" }}>{plan ? rs(b.max_loss_rs) : DASH}</span>
                  </div>
                </div>
              );
            })}

            <span className="nv-eyebrow" data-testid="history-label" style={{ paddingTop: 12 }}>{historyLabel}</span>
            <div data-testid="history" style={{ border: "1px solid var(--line)", borderRadius: 14, background: "var(--bg-1)", overflow: "hidden" }}>
              {recentQ.isLoading && <div style={{ padding: 12 }}><Loading rows={1} label="Loading decisions" /></div>}
              {recentQ.error && <div style={{ padding: 12 }}><ErrorBox error={recentQ.error} what="recent decisions" onRetry={() => recentQ.refetch()} /></div>}
              {!recentQ.isLoading && !recentQ.error && history.length === 0 && <div style={{ padding: "12px 16px", fontSize: 13, color: "var(--ink-3)" }}>No decisions recorded yet.</div>}
              {history.map((h: ApprovalRow, i) => {
                const head = heads.get(h.trade_id);
                const scope = (h.body?.scope ?? {}) as Record<string, unknown>;
                const name = head ? `${head.instrument} · ${humanize(head.strategy_type)}` : typeof scope.instrument === "string" ? `${scope.instrument} · ${humanize(scope.strategy_type)}` : h.trade_id;
                const tone = h.decided_by?.startsWith("SYSTEM:") ? "ink" : statusTone(h.status);
                const target = h.supersedes_id ?? h.approval_id;
                return (
                  <div key={h.approval_id} data-testid="history-row" role="button" tabIndex={0} onClick={() => open(target)} onKeyDown={(e) => { if (e.key === "Enter") open(target); }} className="ad-hover"
                    style={{ cursor: "pointer", display: "flex", flexDirection: "column", gap: 5, padding: "12px 16px", borderTop: `1px solid ${i ? "var(--line)" : "transparent"}` }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)", overflowWrap: "anywhere", minWidth: 0 }}>{h.approval_id} · {timeIST(h.created_at)}</span>
                      <span style={{ flex: 1 }} />
                      <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", color: TONES[tone][0] }}>{h.decided_by?.startsWith("SYSTEM:session_close") ? "EXPIRED" : statusText(h.status)}</span>
                    </div>
                    <span style={{ fontSize: 13.5 }}>{name} v{h.plan_version}</span>
                    <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--ink-3)" }}>{deciderName(h.decided_by, me?.user_id)}{(h.body?.reasons ?? []).length ? ` · ${(h.body.reasons ?? []).join("; ")}` : ""}</span>
                  </div>
                );
              })}
              {headsQ.error && <span role="alert" style={{ display: "block", padding: "8px 16px", fontSize: 12, color: "var(--danger)", borderTop: "1px solid var(--line)" }}>Plan names unavailable: {errorText(headsQ.error)}</span>}
            </div>
          </div>
        )}

        {showDetail && (
          <ApprovalDetail id={selId!} mobile={mobile} now={now} halt={halt} accounts={accounts} meId={me?.user_id} meName={me?.name || me?.email} onBack={back}
            onDecided={(id) => { if (approvalId !== id) navigate(`/approvals/${encodeURIComponent(id)}`, { replace: true }); }} />
        )}
      </div>
    </div>
  );
}
