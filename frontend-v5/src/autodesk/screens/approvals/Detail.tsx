/**
 * Approval queue — one request opened (right column of TDApprovals.dc.html): header with countdown and thesis, the
 * decision actions with the approval binding / reason step, then Proposed trade + Capital allocation, Risk report,
 * Portfolio impact + Required approvals, Policy checks and Audit history. Layout and inline styles copy the prototype.
 */
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { errorText } from "../../api";
import { DASH, dateShort, fmtNum, humanize, num, pct, rs, rsShort, timeIST } from "../../format";
import type { Account, ApprovalRow, DeskControlRow, RiskAssessmentRow } from "../../types";
import { ErrorBox, Loading, PhaseNote } from "../../ui";
import {
  GLYPH, TONES, accountLabel, bodyOf, checkCounts, checkSummary, checksOf, countdown, deciderName, equityOf,
  impactRows, maxLots, modeOf, notional, planTitle, producerWho, statusText, statusTone, strike, tradeRows, type ToneKey,
} from "./model";
import { useApproval, useAssessment, useDecide, usePlan, usePlanVersions, usePortfolio, useSignal, type Decision } from "./queries";

const REASONS: Record<"reject" | "revise", string[]> = {
  reject: ["Risk too high for today", "Thesis not convincing", "Wrong instrument"],
  revise: ["Smaller size", "Tighter stop", "Different strikes or expiry"],
};

const card: CSSProperties = { display: "flex", flexDirection: "column", padding: "16px 18px", borderRadius: 14, border: "1px solid var(--line)", background: "var(--bg-1)" };
const k10: CSSProperties = { fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--ink-3)" };

function InlineError({ what, error }: { what: string; error: unknown }) {
  return <span role="alert" data-testid="inline-error" style={{ fontSize: 12, lineHeight: 1.45, color: "var(--danger)", padding: "8px 0", borderTop: "1px solid var(--line)" }}>Could not load {what}: {errorText(error)}</span>;
}

export function DetailFrame({ mobile, onBack, children }: { mobile: boolean; onBack: () => void; children: ReactNode }) {
  return (
    <div data-testid="approval-detail" style={{ flex: "999 1 460px", display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
      {mobile && (
        <span role="button" tabIndex={0} data-testid="back-to-list" onClick={onBack} onKeyDown={(e) => { if (e.key === "Enter") onBack(); }}
          style={{ cursor: "pointer", fontSize: 13, color: "var(--mint)", minHeight: 32, display: "flex", alignItems: "center" }}>‹ All approvals</span>
      )}
      {children}
    </div>
  );
}

export function ApprovalDetail({ id, mobile, now, halt, accounts, meId, meName, onBack, onDecided }: {
  id: string; mobile: boolean; now: number; halt: DeskControlRow | null; accounts: Account[]; meId?: string | null; meName?: string | null;
  onBack: () => void; onDecided: (approvalId: string) => void;
}) {
  const aq = useApproval(id);
  const a = aq.data;
  const pq = usePlan(a?.trade_id, a?.plan_version);
  const plan = pq.data;
  const b = bodyOf(plan);
  const rq = useAssessment(a?.risk_assessment_id);
  const risk: RiskAssessmentRow | null | undefined = a?.risk_assessment_id ? rq.data : plan?.latest_risk_assessment;
  const vq = usePlanVersions(a?.trade_id);
  const portq = usePortfolio(a?.account_id);
  const sq = useSignal(plan?.signal_id ?? b.signal_id ?? null);
  const decide = useDecide(a?.approval_id);
  const [step, setStep] = useState<null | "approve" | "reject" | "revise">(null);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => { setStep(null); setReason(""); setNote(""); }, [id]);

  if (aq.isLoading) return <DetailFrame mobile={mobile} onBack={onBack}><Loading label="Loading the approval request" /></DetailFrame>;
  if (aq.error || !a) return <DetailFrame mobile={mobile} onBack={onBack}><ErrorBox error={aq.error ?? new Error("not found")} what="this approval request" onRetry={() => aq.refetch()} /></DetailFrame>;

  const account = accounts.find((x) => x.account_id === a.account_id);
  const mode = modeOf(account, a);
  const mt = TONES[mode.tone];
  const acct = accountLabel(account, a);
  const approvals = plan?.approvals ?? [];
  const mo: ApprovalRow | undefined = a.decided_by?.startsWith("MIDDLE_OFFICE") ? a
    : approvals.find((r) => r.plan_version === a.plan_version && !r.supersedes_id && r.decided_by?.startsWith("MIDDLE_OFFICE"));
  const answer = approvals.find((r) => r.supersedes_id === a.approval_id);
  const decided: ApprovalRow | undefined = a.status !== "NEEDS_HUMAN_APPROVAL" ? a : answer;
  const cd = countdown(a.expires_at, now);
  const expired = !decided && cd.expired;
  const versionChanged = !!plan && plan.current_version !== a.plan_version;
  const open = !decided && !expired && !versionChanged;
  const why = (mo?.body?.reasons ?? a.body?.reasons ?? []).join("; ");
  const checks = checksOf(risk);
  const warnN = checkCounts(checks).warn;
  const equity = equityOf(risk, account);

  // ── decision banner ─────────────────────────────────────────────────────────────────────────────────────────────
  let banner: { tone: ToneKey; t: string; note: string; testId: string } | null = null;
  if (decided) {
    const who = deciderName(decided.decided_by, meId);
    const at = timeIST(decided.created_at);
    const rsn = (decided.body?.reasons ?? []).join("; ");
    const closed = decided.decided_by?.startsWith("SYSTEM:session_close");
    const txt = closed ? `The approval window closed at the session close (${at}).`
      : decided.status === "APPROVED" ? `Approved by ${who} at ${at}. Phase 1 has no execution: the plan ends at APPROVED and nothing is sent to a broker or a paper engine.`
      : decided.status === "REJECTED" ? `Rejected by ${who} at ${at}. This plan version is closed.`
      : decided.status === "NEEDS_REVISION" ? `Sent back for revision by ${who} at ${at}. A new version needs a new approval.`
      : `${statusText(decided.status)} by ${who} at ${at}.`;
    banner = { tone: closed ? "ink" : statusTone(decided.status), t: closed ? "EXPIRED" : statusText(decided.status), note: rsn && !closed ? `${txt} Reason: ${rsn}` : txt, testId: "decided-banner" };
  } else if (expired) {
    banner = { tone: "danger", t: "EXPIRED", note: `The approval window closed at ${timeIST(a.expires_at)} IST. The API refuses a decision after expiry.`, testId: "expired-banner" };
  } else if (versionChanged) {
    banner = { tone: "amber", t: "PLAN CHANGED", note: `The plan is now at v${plan!.current_version}; this request binds v${a.plan_version}. The API refuses a decision on an older version.`, testId: "version-banner" };
  }
  const bt = banner ? TONES[banner.tone] : TONES.ink;

  // ── binding (PRD §10.3) — the same fields the API's approval scope records ─────────────────────────────────────
  const legs = b.legs ?? [];
  const lots = maxLots(legs);
  const qty = legs.length ? Math.max(...legs.map((l) => l.quantity ?? 0)) : null;
  const hash = plan?.plan_hash ?? "";
  const optStr = legs.filter((l) => l.kind === "CE" || l.kind === "PE").map((l) => strike(l.strike)).join("/");
  const bind: { k: string; v: string; title?: string; testId?: string }[] = [
    { k: "Tenant · account", v: `${account?.tenant_id ?? meId ?? DASH} · ${acct}` },
    { k: "Trade · plan", v: `${a.trade_id} · v${a.plan_version} · hash ${hash ? `${hash.slice(0, 4)}…${hash.slice(-4)}` : DASH}`, title: hash, testId: "bind-hash" },
    { k: "Instrument · strategy", v: `${b.instrument ?? DASH}${optStr ? ` ${optStr}` : ""} · ${humanize(b.strategy_type).toLowerCase()}` },
    { k: "Max quantity", v: legs.every((l) => l.kind === "EQ") ? `${qty ?? DASH} shares` : `${lots ?? DASH} lots · ${qty ?? DASH} per leg` },
    { k: "Max notional · risk", v: `${rs(notional(b), { decimals: 2 })} · ${rs(b.max_loss_rs, { decimals: 2 })}` },
    { k: "Mode · actions", v: `${mode.label} · no orders in Phase 1` },
    { k: "Expires", v: `${a.expires_at ? `${timeIST(a.expires_at)} IST · ${dateShort(a.expires_at)}` : DASH} · approver ${meName || "you"}` },
  ];

  const submit = (decision: Decision, text: string) => {
    if (!plan) return;
    decide.mutate({ decision, reason: text, plan_hash: plan.plan_hash }, { onSuccess: () => { setStep(null); setReason(""); setNote(""); onDecided(a.approval_id); } });
  };
  const decisionError = decide.error ? (
    <span role="alert" data-testid="decision-error" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--danger)" }}>{errorText(decide.error)}</span>
  ) : null;
  const pick = (s: "approve" | "reject" | "revise") => { decide.reset(); setReason(""); setStep(s); };

  // ── sections ────────────────────────────────────────────────────────────────────────────────────────────────────
  const trade = tradeRows(b);
  const sizing = (risk?.body?.sizing ?? {}) as Record<string, unknown>;
  const margin = b.margin_estimate ?? {};
  const capital: { k: string; v: ReactNode }[] = [
    { k: "Reservation", v: <span data-testid="reservation-phase" style={{ color: "var(--ink-3)" }}><span className="nv-pill nv-pill-indigo" style={{ padding: "1px 7px", fontSize: 9, marginRight: 8 }}>Phase 2</span>Capital reservations arrive with paper execution.</span> },
    { k: "Capital required", v: `${rs(b.capital_required_rs, { decimals: 2 })}${margin.method ? ` · ${margin.method}` : ""}` },
    { k: "Sizing rule", v: risk ? [typeof sizing.method === "string" ? sizing.method : null, sizing.proposed_size != null ? `${sizing.proposed_size} ${sizing.unit ?? ""} proposed, ${sizing.allowed_size ?? DASH} allowed` : null, sizing.budget_rs ? `budget ${rs(sizing.budget_rs, { decimals: 2 })}` : null].filter(Boolean).join(" · ") || DASH : DASH },
  ];
  const lossN = num(b.max_loss_rs);
  const tiles: { k: string; v: string; s: string; c: string }[] = [
    { k: "Max loss", v: rs(b.max_loss_rs), s: lossN != null && equity ? `${pct((lossN / equity) * 100)} of ${rsShort(equity)}` : DASH, c: "var(--danger)" },
    { k: "Max profit", v: b.max_profit_rs == null ? "Open" : rs(b.max_profit_rs), s: b.max_profit_rs == null ? "No fixed maximum in the plan" : b.expected_payoff?.reward_risk ? `R:R 1 : ${fmtNum(b.expected_payoff.reward_risk)}` : DASH, c: "var(--mint)" },
    { k: "Breakeven", v: (b.breakevens ?? []).length ? (b.breakevens ?? []).map((x) => fmtNum(x)).join(" / ") : DASH, s: legs.some((l) => l.kind === "CE" || l.kind === "PE") ? `${b.instrument ?? ""} at expiry` : `${b.instrument ?? ""} price`, c: "var(--ink)" },
    { k: "Capital required", v: rs(b.capital_required_rs), s: margin.method ?? DASH, c: "var(--ink)" },
  ];
  const impact = impactRows(risk, account?.name ?? acct);
  const book = portq.data?.book;
  const bookRisk = book ? book.pending.reduce((s, p) => s + (num(p.max_loss_rs) ?? 0), 0) : null;
  const chainRows: { who: string; st: string; t: string; tone: ToneKey }[] = [
    { who: "Risk & Operations", st: risk ? `${risk.verdict}${warnN ? ` · ${warnN} WARNING${warnN === 1 ? "" : "S"}` : ""}` : "NO ASSESSMENT", t: risk ? timeIST(risk.created_at) : DASH, tone: statusTone(risk?.verdict) },
    { who: "Middle Office", st: mo ? statusText(mo.status) : DASH, t: mo ? timeIST(mo.created_at) : DASH, tone: statusTone(mo?.status) },
    mo?.status === "NEEDS_HUMAN_APPROVAL" || a.status === "NEEDS_HUMAN_APPROVAL"
      ? answer
        ? { who: "Account owner · you", st: answer.decided_by?.startsWith("SYSTEM:session_close") ? "EXPIRED AT CLOSE" : statusText(answer.status), t: timeIST(answer.created_at), tone: answer.decided_by?.startsWith("SYSTEM:") ? "ink" : statusTone(answer.status) }
        : { who: "Account owner · you", st: expired ? "EXPIRED" : "WAITING", t: DASH, tone: expired ? "danger" : "ink" }
      : { who: "Account owner · you", st: "NOT NEEDED", t: DASH, tone: "ink" },
    { who: "Paper engine", st: "PHASE 2 · NO EXECUTION", t: DASH, tone: "ink" },
  ];

  const audit: { at: string; who: string; x: string; c: string }[] = [];
  const sig = sq.data;
  if (sig) audit.push({ at: sig.created_at, who: "AI Trader", x: `${sig.signal_id} · ${sig.instrument} ${String(sig.direction).toLowerCase()} · ${humanize(sig.category)} · score ${num(sig.signal_score) ?? sig.signal_score}`, c: "var(--mint)" });
  for (const v of vq.data ?? []) {
    audit.push({ at: v.created_at, who: producerWho(v.created_by, meId), x: `${v.trade_id} v${v.version} · ${humanize(v.strategy_type)} · max loss ${rs(v.max_loss_rs, { decimals: 2 })}${v.change_reason ? ` · ${v.change_reason}` : ""}`, c: "var(--mint)" });
  }
  if (risk) audit.push({ at: risk.created_at, who: "Risk & Operations", x: `${risk.assessment_id} ${risk.verdict}${(risk.body?.violations ?? []).length ? ` · ${(risk.body.violations ?? []).join(", ")}` : ""}${warnN ? ` · ${warnN} warning${warnN === 1 ? "" : "s"}` : ""}`, c: "var(--mint)" });
  for (const r of approvals) {
    const who = deciderName(r.decided_by, meId);
    audit.push({ at: r.created_at, who, x: `${r.approval_id} · ${statusText(r.status)}${(r.body?.reasons ?? []).length ? ` · ${(r.body.reasons ?? []).join("; ")}` : ""}`, c: who === "You" ? "var(--amber)" : who === "Middle Office" ? "var(--ink-2)" : "var(--ink-3)" });
  }
  audit.sort((x, y) => x.at.localeCompare(y.at));

  const h2 = mobile ? 24 : 30;
  const tileMin = mobile ? "130px" : "150px";
  const auditCol = mobile ? "86px" : "110px";

  return (
    <DetailFrame mobile={mobile} onBack={onBack}>
      <div data-testid="approval-card" style={{ display: "flex", flexDirection: "column", gap: 16, padding: mobile ? "18px 16px" : "22px 24px", borderRadius: 16, border: "1px solid var(--line-2)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "12px 20px", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, flex: "1 1 300px" }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <span data-testid="detail-id" style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--ink-2)", overflowWrap: "anywhere" }}>{a.approval_id} · {a.trade_id} v{a.plan_version}</span>
              <span className="nv-pill" data-testid="detail-mode" style={{ color: mt[0], borderColor: mt[1] }}>{mode.label}</span>
              <span className="nv-pill" data-testid="detail-account">{acct}</span>
            </div>
            <h2 data-testid="detail-title" style={{ margin: 0, fontFamily: "var(--display)", fontWeight: 400, fontSize: h2, lineHeight: 1.12, letterSpacing: "-0.015em", textWrap: "pretty" } as CSSProperties}>
              {pq.isLoading ? a.trade_id : planTitle(b, a.trade_id)}
            </h2>
            {why && <span data-testid="detail-why" style={{ fontSize: 13, color: "var(--amber)" }}>{why}</span>}
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
            <span className="nv-num" data-testid="detail-countdown" style={{ fontFamily: "var(--display)", fontSize: 40, lineHeight: 1, color: decided ? "var(--ink-3)" : cd.c }}>{decided ? timeIST(decided.created_at) : cd.t}</span>
            <span className="nv-eyebrow" style={{ fontSize: 9 }}>{decided ? "DECIDED · IST" : a.expires_at ? `LEFT · EXPIRES ${timeIST(a.expires_at)} IST` : "NO EXPIRY SET"}</span>
          </div>
        </div>
        {pq.error ? <ErrorBox error={pq.error} what="the trade plan" onRetry={() => pq.refetch()} /> : (
          <>
            {b.thesis && <p data-testid="detail-thesis" style={{ margin: 0, fontSize: 14.5, lineHeight: 1.6, color: "var(--ink-2)", textWrap: "pretty" } as CSSProperties}>{b.thesis}</p>}
            {(b.rationale ?? []).length > 0 && (
              <ul data-testid="detail-rationale" style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 3, fontSize: 13, lineHeight: 1.5, color: "var(--ink-3)" }}>
                {(b.rationale ?? []).map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            )}
          </>
        )}

        {banner && (
          <div data-testid={banner.testId} style={{ display: "flex", flexWrap: "wrap", gap: "8px 14px", alignItems: "center", padding: "12px 14px", borderRadius: 12, border: `1px solid ${bt[1]}`, background: bt[2] }}>
            <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, letterSpacing: "0.1em", color: bt[0] }}>{banner.t}</span>
            <span style={{ fontSize: 13, color: "var(--ink-2)" }}>{banner.note}</span>
          </div>
        )}

        {open && (
          <div data-testid="decision-actions" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {halt && (
              <div data-testid="halted-note" style={{ padding: "11px 14px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" }}>
                New entries are stopped{halt.reason ? ` (${halt.reason})` : ""}. The API refuses approvals until entries resume; Reject and Request revision still work.
              </div>
            )}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
              <button type="button" data-testid="approve-btn" disabled={!!halt || !plan} onClick={() => pick("approve")}
                style={{ cursor: halt || !plan ? "not-allowed" : "pointer", opacity: halt || !plan ? 0.5 : 1, padding: "11px 20px", borderRadius: 12, border: "1px solid transparent", background: "var(--mint)", color: "#06120B", fontSize: 14, fontWeight: 500 }}>Approve…</button>
              <button type="button" data-testid="revise-btn" disabled={!plan} onClick={() => pick("revise")} className="ad-hover-line"
                style={{ cursor: plan ? "pointer" : "not-allowed", padding: "11px 18px", borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 14 }}>Request revision</button>
              <button type="button" data-testid="reject-btn" disabled={!plan} onClick={() => pick("reject")}
                style={{ cursor: plan ? "pointer" : "not-allowed", padding: "11px 18px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "transparent", color: "var(--danger)", fontSize: 14 }}>Reject</button>
            </div>
            {step === "approve" && (
              <div data-testid="bind-panel" style={{ display: "flex", flexDirection: "column", gap: 10, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--mint-line)", background: "var(--mint-soft)" }}>
                <span className="nv-eyebrow" style={{ color: "var(--mint)" }}>Your approval binds exactly this</span>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,230px),1fr))", gap: "8px 18px" }}>
                  {bind.map((x) => (
                    <div key={x.k} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--ink-3)" }}>{x.k}</span>
                      <span data-testid={x.testId} title={x.title} style={{ fontSize: 13, overflowWrap: "anywhere" }}>{x.v}</span>
                    </div>
                  ))}
                </div>
                <input data-testid="approve-note" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="Note for the audit log (optional)"
                  style={{ padding: "9px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--ink)", fontSize: 13, minWidth: 0 }} />
                {decisionError}
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                  <button type="button" data-testid="confirm-approve" disabled={decide.isPending} onClick={() => submit("APPROVE", note.trim())}
                    style={{ cursor: decide.isPending ? "wait" : "pointer", padding: "10px 18px", borderRadius: 12, border: 0, background: "var(--mint)", color: "#06120B", fontSize: 14, fontWeight: 500 }}>{decide.isPending ? "Recording…" : "Confirm approval"}</button>
                  <span role="button" tabIndex={0} onClick={() => setStep(null)} onKeyDown={(e) => { if (e.key === "Enter") setStep(null); }} style={{ cursor: "pointer", fontSize: 13, color: "var(--ink-3)" }}>Cancel</span>
                  <span style={{ fontSize: 12, color: "var(--ink-3)" }}>The API checks the plan hash, the expiry and Stop new entries again when you confirm.</span>
                </div>
              </div>
            )}
            {(step === "reject" || step === "revise") && (
              <div data-testid="reason-panel" style={{ display: "flex", flexDirection: "column", gap: 10, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-2)" }}>
                <span className="nv-eyebrow">{step === "reject" ? "Why are you rejecting it?" : "What should the Trading Assistant change?"}</span>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {REASONS[step].map((t) => {
                    const on = reason === t;
                    return (
                      <span key={t} role="button" tabIndex={0} data-testid="reason-chip" onClick={() => setReason(t)} onKeyDown={(e) => { if (e.key === "Enter") setReason(t); }}
                        style={{ cursor: "pointer", padding: "8px 14px", borderRadius: 999, fontSize: 13, border: `1px solid ${on ? "var(--line-3)" : "var(--line-2)"}`, color: on ? "var(--ink)" : "var(--ink-2)", background: on ? "var(--bg-3)" : "transparent" }}>{t}</span>
                    );
                  })}
                </div>
                <input data-testid="reason-input" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} placeholder="Or write your own reason"
                  style={{ padding: "9px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--ink)", fontSize: 13, minWidth: 0 }} />
                {decisionError}
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <button type="button" data-testid="confirm-reason" disabled={!reason.trim() || decide.isPending} onClick={() => submit(step === "reject" ? "REJECT" : "REQUEST_REVISION", reason.trim())}
                    style={{ cursor: !reason.trim() || decide.isPending ? "not-allowed" : "pointer", opacity: reason.trim() ? 1 : 0.55, padding: "10px 18px", borderRadius: 12, border: "1px solid var(--line-3)", background: "var(--bg-3)", color: "var(--ink)", fontSize: 14 }}>
                    {decide.isPending ? "Recording…" : step === "reject" ? "Reject plan" : "Send for revision"}
                  </button>
                  <span role="button" tabIndex={0} onClick={() => setStep(null)} onKeyDown={(e) => { if (e.key === "Enter") setStep(null); }} style={{ cursor: "pointer", fontSize: 13, color: "var(--ink-3)" }}>Cancel</span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {pq.isLoading && <Loading label="Loading the plan" rows={2} />}
      {plan && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: 14 }}>
            <div data-testid="sec-trade" style={{ ...card, gap: 2 }}>
              <span className="nv-eyebrow" style={{ paddingBottom: 8 }}>Proposed trade</span>
              {trade.map((t, i) => (
                <div key={i} data-testid="trade-row" style={{ display: "grid", gridTemplateColumns: "58px minmax(0,1fr)", gap: 10, padding: "8px 0", borderTop: "1px solid var(--line)", fontSize: 13, lineHeight: 1.45 }}>
                  <span style={{ ...k10, paddingTop: 2 }}>{t.k}</span>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                    <span style={{ overflowWrap: "anywhere" }}>{t.v}</span>
                    {t.n && <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)", overflowWrap: "anywhere" }}>{t.n}</span>}
                  </div>
                </div>
              ))}
            </div>
            <div data-testid="sec-capital" style={{ ...card, gap: 2 }}>
              <span className="nv-eyebrow" style={{ paddingBottom: 8 }}>Capital allocation</span>
              {capital.map((t) => (
                <div key={t.k} style={{ display: "flex", flexDirection: "column", gap: 2, padding: "8px 0", borderTop: "1px solid var(--line)" }}>
                  <span style={k10}>{t.k}</span>
                  <span className="nv-num" style={{ fontSize: 13.5, overflowWrap: "anywhere" }}>{t.v}</span>
                </div>
              ))}
              {rq.error && <InlineError what="the risk assessment" error={rq.error} />}
            </div>
          </div>

          <div data-testid="sec-risk" style={{ ...card, gap: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
              <span className="nv-eyebrow">Risk report</span>
              <span data-testid="risk-id" style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)", overflowWrap: "anywhere" }}>
                {risk ? `${risk.assessment_id} · ${risk.verdict} · RISK & OPERATIONS · ${timeIST(risk.created_at)}` : rq.isLoading ? "…" : "NO ASSESSMENT FOR THIS VERSION"}
              </span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fit,minmax(${tileMin},1fr))`, gap: 10 }}>
              {tiles.map((r) => (
                <div key={r.k} data-testid="risk-tile" style={{ display: "flex", flexDirection: "column", gap: 4, padding: "12px 14px", borderRadius: 12, background: "var(--bg-2)" }}>
                  <span className="nv-eyebrow" style={{ fontSize: 9 }}>{r.k}</span>
                  <span className="nv-num" style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.1, color: r.c }}>{r.v}</span>
                  <span style={{ fontSize: 11, color: "var(--ink-3)" }}>{r.s}</span>
                </div>
              ))}
            </div>
            <PhaseNote testId="stress-phase-note">Stress rows (index moves, an IV change, a session passing) arrive with the Phase 2 risk engine; Phase 1 checks the plan's own maximum loss against the policy.</PhaseNote>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,320px),1fr))", gap: 14 }}>
            <div data-testid="sec-impact" style={card}>
              <span className="nv-eyebrow" style={{ paddingBottom: 10 }}>Portfolio impact</span>
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.4fr) repeat(3,minmax(0,0.8fr))", gap: 8, paddingBottom: 6, fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--ink-3)" }}>
                <span>Measure</span><span style={{ textAlign: "right" }}>Before</span><span style={{ textAlign: "right" }}>After</span><span style={{ textAlign: "right" }}>Limit</span>
              </div>
              {impact.length === 0 && <span style={{ fontSize: 12.5, color: "var(--ink-3)", padding: "8px 0", borderTop: "1px solid var(--line)" }}>{rq.isLoading ? "Loading…" : "No risk assessment for this plan version."}</span>}
              {impact.map((r) => (
                <div key={r.k} data-testid="impact-row" title={r.note} style={{ display: "grid", gridTemplateColumns: "minmax(0,1.4fr) repeat(3,minmax(0,0.8fr))", gap: 8, padding: "8px 0", borderTop: "1px solid var(--line)", fontSize: 12.5, alignItems: "baseline" }}>
                  <span style={{ color: "var(--ink-2)", overflowWrap: "anywhere" }}>{r.k}</span>
                  <ImpactCell v={r.b} equity={equity} color="var(--ink-3)" />
                  <ImpactCell v={r.a} equity={equity} color="var(--ink)" />
                  <ImpactCell v={r.l} equity={equity} color="var(--ink-3)" />
                </div>
              ))}
              <div data-testid="impact-note" style={{ display: "flex", flexDirection: "column", gap: 4, paddingTop: 8, borderTop: "1px solid var(--line)", fontSize: 11.5, lineHeight: 1.45, color: "var(--ink-3)" }}>
                {risk && <span>As assessed at {timeIST(risk.created_at)} against {String((risk.body?.inputs_snapshot as Record<string, unknown> | undefined)?.pending_commitments ?? DASH)} approved plans; % of {rsShort(equity)} equity.</span>}
                {book && <span data-testid="book-now">Book now: {book.pending.length} approved plan{book.pending.length === 1 ? "" : "s"} · committed max loss {rs(bookRisk, { decimals: 2 })}.</span>}
                {portq.data?.note && <span>{portq.data.note}</span>}
                {portq.error && <span role="alert" style={{ color: "var(--danger)" }}>Could not load the account book: {errorText(portq.error)}</span>}
              </div>
            </div>
            <div data-testid="sec-chain" style={{ ...card, gap: 10 }}>
              <span className="nv-eyebrow">Required approvals</span>
              {chainRows.map((c, i) => {
                const t = TONES[c.tone];
                return (
                  <div key={c.who} data-testid="chain-row" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ width: 22, height: 22, flex: "none", borderRadius: "50%", display: "grid", placeItems: "center", fontFamily: "var(--mono)", fontSize: 10, border: `1px solid ${t[1]}`, background: t[2], color: t[0] }}>{i + 1}</span>
                    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 1 }}>
                      <span style={{ fontSize: 13.5 }}>{c.who}</span>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", color: t[0] }}>{c.st}</span>
                    </div>
                    <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)" }}>{c.t}</span>
                  </div>
                );
              })}
            </div>
          </div>

          <div data-testid="sec-checks" style={card}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", paddingBottom: 10 }}>
              <span className="nv-eyebrow">Policy checks</span>
              <span data-testid="check-summary" style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)" }}>{checks.length ? checkSummary(checks) : DASH}</span>
            </div>
            {checks.length === 0 && <span style={{ fontSize: 12.5, color: "var(--ink-3)" }}>{rq.isLoading ? "Loading…" : "No checks: there is no risk assessment for this plan version."}</span>}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: "0 22px" }}>
              {checks.map((c) => {
                const [g, col] = GLYPH[c.outcome] ?? ["?", "var(--ink-3)"];
                return (
                  <div key={c.name} data-testid="check-row" style={{ display: "flex", gap: 10, padding: "8px 0", borderTop: "1px solid var(--line)", alignItems: "baseline" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 12, width: 14, flex: "none", color: col }}>{g}</span>
                    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                      <span style={{ fontSize: 13 }}>{humanize(c.name)}{c.hard === false ? " (soft)" : ""}</span>
                      <span style={{ fontSize: 11.5, color: "var(--ink-3)", overflowWrap: "anywhere" }}>{c.detail || DASH}</span>
                    </div>
                  </div>
                );
              })}
            </div>
            {risk && <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-4)", paddingTop: 8, overflowWrap: "anywhere" }}>POLICY {risk.policy_id ?? DASH} V{risk.policy_version ?? DASH} · {risk.engine_version}</span>}
          </div>

          <div data-testid="sec-audit" style={card}>
            <span className="nv-eyebrow" style={{ paddingBottom: 8 }}>Audit history</span>
            {audit.map((h, i) => (
              <div key={i} data-testid="audit-row" style={{ display: "grid", gridTemplateColumns: `70px ${auditCol} minmax(0,1fr)`, gap: 10, padding: "8px 0", borderTop: "1px solid var(--line)", fontSize: 13, lineHeight: 1.45, alignItems: "baseline" }}>
                <span className="nv-num" title={h.at} style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)" }}>{timeIST(h.at)}</span>
                <span style={{ fontSize: 12, color: h.c }}>{h.who}</span>
                <span style={{ color: "var(--ink-2)", overflowWrap: "anywhere", minWidth: 0 }}>{h.x}</span>
              </div>
            ))}
            {sq.error && <InlineError what="the signal" error={sq.error} />}
            {vq.error && <InlineError what="the plan versions" error={vq.error} />}
          </div>
        </>
      )}
    </DetailFrame>
  );
}

function ImpactCell({ v, equity, color }: { v: number | null; equity: number | null; color: string }) {
  return (
    <span className="nv-num" style={{ textAlign: "right", color, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 1 }}>
      <span>{v == null ? DASH : rsShort(v)}</span>
      {v != null && equity ? <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-3)" }}>{pct((v / equity) * 100)}</span> : null}
    </span>
  );
}
