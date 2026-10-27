/**
 * Trade Desk header strip, on every view (REVIEW_workspace_vs_phases.md §A "2 Trade Desk", P0):
 *
 *   the paper account   cash · capital at risk (blocked) · equity        GET /api/desk/paper-account (cash, blocked, start)
 *                                                                         GET /api/risk/profile live.equity (paper equity: the
 *                                                                         risk service's basis; /paper-account has no equity)
 *   one chip            "Open risk x% of 3%"                              GET /api/risk/profile: live.open.risk_rs ÷
 *                                                                         live.equity.equity_rs, against max_open_risk_pct
 *   the exit-job line   "Exits checked after the 26 Oct close" / missed   GET /api/desk/exit-job-status
 *
 * The risk numbers live on the Risk Desk; this chip is the one the plan keeps here. Unknown is said with its reason, never 0.
 */
import type { ReactNode } from "react";
import { fmtINR, fmtNum, fmtPct } from "../../../../components/ui";
import { useRiskProfile } from "../../risk-profile";
import { usePaperAccount, useExitJobStatus, type ExitJob } from "./trade-desk-data";
import { quiet } from "./parts";

const dayShort = (iso: string) => {
  const d = new Date(`${iso}T12:00:00+05:30`);
  return Number.isFinite(d.getTime()) ? d.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" }) : iso;
};

function Tile({ k, v, sub, testId }: { k: string; v: ReactNode; sub?: ReactNode; testId: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 4, padding: "12px 14px", borderRadius: 14, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{k}</span>
      <span data-testid={testId} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.1, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{v}</span>
      {sub && <span style={{ ...quiet, fontSize: 11 }}>{sub}</span>}
    </div>
  );
}

/** "Exits checked after the 26 Oct close", or the missed / late / running state in the route's words. */
export function exitJobText(j: ExitJob): { text: string; tone: "ok" | "warn" | "bad" } {
  if (j.status === "ok") return { text: j.lastSession ? `Exits checked after the ${dayShort(j.lastSession)} close` : (j.message ?? "The evening exit check is up to date."), tone: "ok" };
  if (j.status === "running") return { text: "The evening exit check is running now", tone: "warn" };
  if (j.status === "late") return { text: `Exit check late: ${j.message ?? "not recorded yet"}`, tone: "warn" };
  const last = j.lastSession ? ` Last checked after the ${dayShort(j.lastSession)} close.` : "";
  return { text: `Exit check missed: ${j.message ?? "the evening exit check did not run."}${last}`, tone: "bad" };
}

function ExitJobLine() {
  const q = useExitJobStatus();
  let body: ReactNode;
  let status = "loading";
  let color = "var(--cp-ink-3)";
  if (q.isPending) body = "Reading when exits were last checked…";
  else if (q.isError) {
    status = "error";
    body = "When exits were last checked is unavailable right now (the exit-check status did not load).";
    color = "var(--amber)";
  } else {
    status = q.data.status;
    const t = exitJobText(q.data);
    body = t.text;
    color = t.tone === "ok" ? "var(--cp-ink-2)" : t.tone === "warn" ? "var(--amber)" : "var(--cp-danger)";
  }
  return (
    <span data-testid="td-exit-job" data-status={status} role="status" className="flex items-center" style={{ gap: 8, fontSize: 12.5, lineHeight: 1.5, color, minWidth: 0 }}>
      <span aria-hidden className="nv-dot" style={{ flex: "none", width: 7, height: 7, borderRadius: "50%", background: color }} />
      <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>
        {body}
        {!q.isPending && !q.isError && q.data.schedule ? <span style={{ color: "var(--cp-ink-3)" }}> · evening job, {q.data.schedule}</span> : null}
      </span>
    </span>
  );
}

function OpenRiskChip() {
  const q = useRiskProfile();
  let text: string;
  let pct: string = "";
  let tone: "mint" | "amber" | "danger" | "ink" = "ink";
  let title: string | undefined;
  if (q.isPending) text = "Open risk: reading";
  else if (q.isError) text = "Open risk unavailable (the risk profile did not load)";
  else {
    const limit = q.data.profile.limits.max_open_risk_pct ?? null;
    const l = q.data.live;
    const limitText = limit != null ? `${fmtNum(limit, limit % 1 ? 1 : 0)}%` : "an unknown limit";
    if (!l || l.equityRs == null || l.equityRs <= 0 || l.open.riskRs == null) {
      const why = !l ? q.data.liveError : l.unknownReasons.join("; ");
      text = `Open risk unknown of ${limitText}${why ? ` (${why})` : ""}`;
      tone = "amber";
    } else {
      const p = (l.open.riskRs / l.equityRs) * 100;
      pct = p.toFixed(2);
      text = `Open risk ${fmtPct(p, { digits: 1 })} of ${limitText}`;
      tone = limit != null && p >= limit ? "danger" : limit != null && p >= limit * 0.8 ? "amber" : "mint";
      title = `${fmtINR(l.open.riskRs)} reserved at entry against paper equity ${fmtINR(l.equityRs)}${l.budgetsRs.open_risk != null ? `; budget ${fmtINR(l.budgetsRs.open_risk)}` : ""}. The limits are on the Risk Desk.`;
    }
  }
  return (
    <span data-testid="td-open-risk" data-pct={pct} className="cp-pill" data-tone={tone === "danger" ? "danger" : tone} title={title}
      style={{ flex: "none", maxWidth: "100%", whiteSpace: "normal", background: tone === "mint" ? "var(--mint-soft)" : undefined }}>
      {text}
    </span>
  );
}

export function HeaderStrip() {
  const acct = usePaperAccount();
  const risk = useRiskProfile();
  const a = acct.data;
  const live = risk.data?.live ?? null;
  const equity: ReactNode = risk.isPending ? "…" : live?.equityRs != null ? fmtINR(live.equityRs) : "Unknown";
  const equitySub = risk.isError
    ? "the risk profile did not load"
    : live && live.equityRs == null
      ? `unknown: ${live.unknownReasons.join("; ") || "an open position cannot be marked"}`
      : !live && risk.data
        ? `unknown: ${risk.data.liveError ?? "no live figures"}`
        : "cash + net unrealised P&L at end-of-day marks";
  const start = a?.startingCapitalRs ?? risk.data?.profile.startingCapitalRs ?? null;
  return (
    <section data-testid="td-header" aria-label="Paper account" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      {acct.isError ? (
        <span data-testid="td-acct-error" role="alert" style={{ ...quiet, color: "var(--amber)" }}>The paper account did not load, so cash and capital at risk are unknown here.</span>
      ) : null}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,150px),1fr))", gap: 10 }}>
        <Tile k="Cash" testId="td-acct-cash" v={acct.isPending ? "…" : fmtINR(a?.cashRs ?? null)} sub={a?.availableRs != null ? `${fmtINR(a.availableRs)} free after capital at risk` : undefined} />
        <Tile k="Capital at risk (blocked)" testId="td-acct-blocked" v={acct.isPending ? "…" : fmtINR(a?.blockedRs ?? null)} sub="reserved against open positions; not exchange margin" />
        <Tile k="Equity" testId="td-acct-equity" v={equity} sub={equitySub} />
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: "8px 14px" }}>
        <OpenRiskChip />
        <ExitJobLine />
      </div>
      <span data-testid="td-acct-start" style={{ ...quiet, fontSize: 11.5 }}>
        Starting capital {fmtINR(start)}, a simulation default, not a real account’s capital.{a && !a.stored ? " No paper trade has moved the account yet." : ""}
        {a?.blockedBasis ? ` Capital at risk: ${a.blockedBasis}.` : ""}
      </span>
    </section>
  );
}
