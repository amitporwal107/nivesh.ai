/**
 * Risk Desk (?tab=risk&view=limits|controls|log; before 2026-10-27 More · Risk controls) — the Risk Control Center: the user's kill switch and trading halt, the
 * limits the policy gate applies to paper writes, and the append-only record of every gate decision and control change.
 *
 *   01 Kill switch & halt     state in words, who set it, when and why; turn on with a reason and a confirmation;
 *                             turn off only where the route says can_reset (an admin); data modes; live authorization
 *   02 Policy limits          limit, used and remaining where the route gives usage; "Gate off for your account"
 *   03 Recent risk decisions  allow / block, path, symbol, reasons and correlation id, newest first
 *   04 Control changes        who changed which control, from what to what, and why, newest first
 *   05 Risk profile           the eight limits the universal risk service applies to every paper entry (value, the
 *                             rupee budget now, and each one's definition: how it is measured, when it resets, what a
 *                             breach does); the equity they are measured against (paper equity, peak, drawdown, day and
 *                             week P&L, open risk; the starting capital is a simulation default); the profile's version
 *                             and effective date; its change log; and a form to tighten a limit (only an admin loosens)
 *
 * Reads and writes: risk-controls.ts (GET /api/risk/status, /policy, /audit, /decisions; PUT /api/risk/kill-switch,
 * /api/risk/halt) and risk-profile.ts (GET and PUT /api/risk/profile). The controls block NEW paper positions only: no
 * order is placed anywhere in this system, and open positions are untouched (the route's own `not_in_scope`, shown at
 * the top). An unreadable status is said to be unknown, never shown as "off", and offers no controls; an unreadable
 * figure in the profile reads "unknown", never 0.
 */
import { useId, useState, type CSSProperties, type ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { Btn, EmptyBlock, ErrorBlock, LoadingBlock, Pill, TONE_COLOR, fmtINR, fmtNum, fmtPct, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { INPUT_STYLE, QueryProblem } from "../trading/parts";
import { stampIst } from "./overview-data";
import {
  controlProblem, useRiskAudit, useRiskDecisions, useRiskPolicy, useRiskStatus, useSetHalt, useSetKillSwitch,
  type RiskAuditEvent, type RiskDecision, type RiskPolicy, type RiskStatus,
} from "./risk-controls";
import {
  BUDGET_OF, LOOSEN_ADMIN_ONLY, isLooser, profileProblem, useRiskProfile, useSetRiskProfile,
  type PeriodPnl, type ProfileChange, type RiskProfileView,
} from "./risk-profile";
import { TrustLine } from "./trust";
import { Widget } from "./widget";

const SOURCE = "Risk controls";
const MAX_REASON = 500; // services/risk_controls.py MAX_REASON

const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" };
const mono: CSSProperties = { fontFamily: "var(--mono)", fontSize: 11.5, overflowWrap: "anywhere" };
const th: CSSProperties = { textAlign: "left", padding: "8px 10px", whiteSpace: "nowrap", borderBottom: "1px solid var(--cp-line)", fontWeight: 400 };
const td: CSSProperties = { padding: "10px", verticalAlign: "top", borderBottom: "1px solid var(--cp-line)", fontSize: 12.5 };

const at = (iso: string | null) => stampIst(iso) ?? "time not recorded";

// ── the two controls ─────────────────────────────────────────────────────

type ControlKind = "kill" | "halt";

const CONTROL: Record<ControlKind, {
  name: string; on: string; off: string; onWords: string; offWords: string; turnOn: string; turnOff: string; adminOnly: string;
  confirmOn: (canReset: boolean) => string; confirmOff: string; doneOn: string; doneOff: string;
}> = {
  kill: {
    name: "Kill switch", on: "On", off: "Off",
    onWords: "New paper positions are blocked.", offWords: "The kill switch blocks nothing.",
    turnOn: "Turn kill switch on", turnOff: "Turn kill switch off", adminOnly: "Only an admin can turn the kill switch off",
    confirmOn: (canReset) => `Turn the kill switch on? New paper positions stay blocked until ${canReset ? "you turn it" : "an admin turns it"} off. Open positions are untouched.`,
    confirmOff: "Turn the kill switch off? New paper positions are allowed again unless trading is halted.",
    doneOn: "Kill switch turned on.", doneOff: "Kill switch turned off.",
  },
  halt: {
    name: "Trading halt", on: "Halted", off: "Not halted",
    onWords: "New paper positions are blocked.", offWords: "The halt blocks nothing.",
    turnOn: "Halt trading", turnOff: "Lift the halt", adminOnly: "Only an admin can lift the halt",
    confirmOn: (canReset) => `Halt trading? New paper positions stay blocked until ${canReset ? "you lift" : "an admin lifts"} the halt. Open positions are untouched.`,
    confirmOff: "Lift the halt? New paper positions are allowed again unless the kill switch is on.",
    doneOn: "Trading halted.", doneOff: "Halt lifted.",
  },
};

function ControlRow({ kind, status }: { kind: ControlKind; status: RiskStatus }) {
  const c = CONTROL[kind];
  const tid = `risk-${kind}`;
  const kill = useSetKillSwitch();
  const halt = useSetHalt();
  const m = kind === "kill" ? kill : halt;
  const on = kind === "kill" ? status.killSwitch : status.halted;
  const id = useId();
  const [step, setStep] = useState<"idle" | "reason" | "confirm">("idle");
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);
  const want = !on;
  const start = () => { m.reset(); setReason(""); setMissing(false); setStep("reason"); };
  const cancel = () => { m.reset(); setStep("idle"); };
  const next = () => {
    if (!reason.trim()) { setMissing(true); return; }
    setStep("confirm");
  };
  const yes = () => m.mutate({ enabled: want, reason: reason.trim() }, { onSuccess: () => { setStep("idle"); setReason(""); } });

  return (
    <div data-testid={tid} data-state={on ? "on" : "off"} className="flex min-w-0 flex-col" style={{ gap: 8, padding: "12px 14px", borderRadius: 12, border: `1px solid ${on ? "var(--danger-line)" : "var(--line-2)"}`, background: on ? "var(--cp-danger-soft)" : "var(--bg-1)" }}>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}>{c.name}</span>
        <span data-testid={`${tid}-pill`}><Pill tone={on ? "danger" : "ink"}>{on ? c.on : c.off}</Pill></span>
      </span>
      <span data-testid={`${tid}-words`} style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink)" }}>
        {c.name}: {on ? c.on.toLowerCase() : c.off.toLowerCase()}. {on ? c.onWords : c.offWords}
      </span>

      {step === "idle" && (
        on && !status.canReset
          ? <span data-testid={`${tid}-admin-only`} style={quiet}>{c.adminOnly}.</span>
          : (
            <span>
              <Btn variant={on ? "default" : "primary"} data-testid={`${tid}-${on ? "off" : "on"}`} onClick={start}>{on ? c.turnOff : c.turnOn}</Btn>
            </span>
          )
      )}

      {step === "reason" && (
        <div data-testid={`${tid}-form`} className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <label htmlFor={`${id}-reason`} style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>Reason (required; recorded with the change)</label>
          <textarea
            id={`${id}-reason`}
            data-testid={`${tid}-reason`}
            autoFocus
            rows={2}
            maxLength={MAX_REASON}
            value={reason}
            aria-invalid={missing || undefined}
            aria-describedby={missing ? `${id}-missing` : `${id}-count`}
            onChange={(e) => { setReason(e.target.value); setMissing(false); }}
            style={{ ...INPUT_STYLE, fontFamily: "var(--sans)", resize: "vertical" }}
          />
          <span id={`${id}-count`} className="cp-mono-note">{reason.length} / {MAX_REASON}</span>
          {missing && <span id={`${id}-missing`} data-testid={`${tid}-reason-error`} role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>Give a reason: it is recorded with the change.</span>}
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <Btn variant="primary" data-testid={`${tid}-continue`} onClick={next}>Continue</Btn>
            <Btn variant="ghost" data-testid={`${tid}-cancel`} onClick={cancel}>Cancel</Btn>
          </span>
        </div>
      )}

      {step === "confirm" && (
        <div data-testid={`${tid}-confirm`} role="group" aria-label={`Confirm: ${want ? c.turnOn : c.turnOff}`} className="flex min-w-0 flex-col" style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
          <span style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink)" }}>{want ? c.confirmOn(status.canReset) : c.confirmOff}</span>
          <span data-testid={`${tid}-confirm-reason`} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>Reason: “{reason.trim()}”</span>
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <Btn variant="primary" data-testid={`${tid}-confirm-yes`} disabled={m.isPending} aria-busy={m.isPending} onClick={yes}>{m.isPending ? "Working…" : want ? c.turnOn : c.turnOff}</Btn>
            {/* Focus lands on Cancel, so a held Enter key cannot confirm by accident. */}
            <Btn variant="ghost" data-testid={`${tid}-confirm-no`} autoFocus disabled={m.isPending} onClick={cancel}>Cancel</Btn>
          </span>
          {m.isError && <span data-testid={`${tid}-confirm-error`} role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>{controlProblem(m.error)}</span>}
        </div>
      )}

      {step === "idle" && m.isSuccess && (
        <span data-testid={`${tid}-done`} role="status" style={{ fontSize: 12, color: "var(--mint)" }}>{m.variables?.enabled ? c.doneOn : c.doneOff} The change is recorded below.</span>
      )}
    </div>
  );
}

// ── 01 status ────────────────────────────────────────────────────────────

const MODE_LABEL: Record<string, string> = { paper: "Paper", shadow: "Shadow", assisted: "Assisted", live: "Live" };
const modeLabel = (m: string) => MODE_LABEL[m] ?? m;

function StatusBody({ q }: { q: UseQueryResult<RiskStatus> }) {
  if (q.isPending) return <LoadingBlock label="Loading your risk controls" rows={3} />;
  if (q.isError) {
    return (
      <div data-testid="risk-status-error" className="flex flex-col" style={{ gap: 8 }}>
        <QueryProblem what="Your risk controls" error={q.error} onRetry={() => { void q.refetch(); }} />
        <span style={quiet}>Their state is unknown here. This screen does not assume the kill switch or the halt is off.</span>
      </div>
    );
  }
  const s = q.data;
  if (!s.known) {
    return (
      <div data-testid="risk-status-unknown">
        <ErrorBlock title="The risk status was not in the expected form" error="the kill switch and halt state is unknown, not off" onRetry={() => { void q.refetch(); }} />
      </div>
    );
  }
  const others = s.modes.filter((m) => m !== "paper").map(modeLabel);
  const la = s.liveAuthorization;
  const lastChange = s.reason || s.setBy || s.setAt;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 14 }}>
      <div className="grid" style={{ gap: 12, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,280px),1fr))", alignItems: "start" }}>
        <ControlRow kind="kill" status={s} />
        <ControlRow kind="halt" status={s} />
      </div>

      <div data-testid="risk-last-change" className="flex min-w-0 flex-col" style={{ gap: 4 }}>
        <span className="cp-eyebrow">Last change</span>
        {lastChange ? (
          <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
            {s.reason ? <span data-testid="risk-last-reason">“{s.reason}”</span> : "No reason on record"}
            {" · by "}<span data-testid="risk-last-by" style={mono}>{s.setBy ?? "unknown"}</span>
            {" · "}<span data-testid="risk-last-at">{at(s.setAt)}</span>
          </span>
        ) : (
          <span data-testid="risk-last-none" style={quiet}>No change on record yet.</span>
        )}
      </div>

      <div className="grid" style={{ gap: 12, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))" }}>
        <div data-testid="risk-modes" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <span className="cp-eyebrow">Data mode</span>
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <span data-testid="risk-mode-paper" style={{ fontSize: 13 }}>Paper</span>
            <Pill tone="mint">Active</Pill>
          </span>
          {others.length > 0 && <span data-testid="risk-mode-unavailable" style={quiet}>{others.join(" / ")}: not available</span>}
        </div>
        <div data-testid="risk-live-auth" data-granted={la?.granted ? "true" : "false"} className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <span className="cp-eyebrow">Live authorization</span>
          {la?.granted ? (
            <>
              <span data-testid="risk-live-auth-words" style={{ fontSize: 13, overflowWrap: "anywhere" }}>Authorized by {la.grantedBy ?? "an unnamed admin"}{la.grantedAt ? ` · ${at(la.grantedAt)}` : ""}</span>
              {la.reason && <span style={{ ...quiet, overflowWrap: "anywhere" }}>“{la.reason}”</span>}
              {!s.liveExecutionAvailable && <span style={quiet}>Authorization alone places nothing: live execution is not available.</span>}
            </>
          ) : (
            <span data-testid="risk-live-auth-words" style={{ fontSize: 13 }}>Not authorized</span>
          )}
        </div>
      </div>

      <TrustLine source={SOURCE} method={s.policyVersion} testId="risk-trust-status" />
    </div>
  );
}

// ── 02 policy ────────────────────────────────────────────────────────────

interface LimitRow { key: string; label: string; limit: number | null; used?: number | null; fmt: (n: number | null) => string; text?: string }

function Remaining({ row }: { row: LimitRow }) {
  if (row.used == null || row.limit == null) return <>—</>;
  const left = row.limit - row.used;
  if (left < 0) return <span style={{ color: TONE_COLOR.danger }}>Over by {row.fmt(-left)}</span>;
  return <>{row.fmt(left)}</>;
}

function PolicyBody({ q, gateEnabled }: { q: UseQueryResult<RiskPolicy>; gateEnabled: boolean | null }) {
  const { mobile } = useCopilotShell();
  const gateNote = gateEnabled === false && (
    <span data-testid="risk-gate-off-note" style={quiet}>The policy gate does not check your paper writes, so these limits are not applied to them. The kill switch and the halt still apply.</span>
  );
  if (q.isPending) return <>{gateNote}<LoadingBlock label="Loading the policy limits" rows={3} /></>;
  if (q.isError) return <div data-testid="risk-policy-error" className="flex flex-col" style={{ gap: 8 }}>{gateNote}<QueryProblem what="The policy limits" error={q.error} onRetry={() => { void q.refetch(); }} /></div>;
  const p = q.data;
  const u = p.usage;
  const count = (n: number | null) => fmtNum(n);
  const rupees = (n: number | null) => fmtINR(n);
  const rows: LimitRow[] = [
    { key: "legs", label: "Legs per structure", limit: p.maxLegs, fmt: count },
    { key: "lots", label: "Lots per leg", limit: p.maxLotsPerLeg, fmt: count },
    { key: "structures", label: "Open structures", limit: p.maxOpenStructures, used: u ? u.openStructures : null, fmt: count },
    { key: "capital", label: "Capital at risk", limit: p.maxCapitalAtRiskRs, used: u ? u.capitalAtRiskRs : null, fmt: rupees },
    { key: "defined", label: "Defined risk only", limit: null, fmt: count, text: p.requireDefinedRisk == null ? "—" : p.requireDefinedRisk ? "Yes" : "No" },
  ];
  // On a phone the cells tighten and the label column wraps, so all four columns fit without a sideways scroll.
  const cell = (st: CSSProperties): CSSProperties => (mobile ? { ...st, padding: "8px 5px" } : st);
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      {gateNote}
      <div className="cp-scroll overflow-x-auto">
        <table data-testid="risk-policy-table" aria-label="Policy limits: limit, used and remaining" style={{ width: "100%", minWidth: mobile ? 0 : 380, borderCollapse: "collapse" }}>
          <thead>
            <tr className="cp-mono-note">
              <th scope="col" style={cell(th)}>Limit</th>
              <th scope="col" style={cell({ ...th, textAlign: "right" })}>Allowed</th>
              <th scope="col" style={cell({ ...th, textAlign: "right" })}>Used</th>
              <th scope="col" style={cell({ ...th, textAlign: "right" })}>Remaining</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} data-testid={`risk-limit-${r.key}`}>
                <th scope="row" style={cell({ ...td, textAlign: "left", fontWeight: 400, color: "var(--cp-ink)" })}>{r.label}</th>
                <td data-testid={`risk-limit-${r.key}-limit`} className="cp-num" style={cell({ ...td, textAlign: "right", whiteSpace: "nowrap" })}>{r.text ?? r.fmt(r.limit)}</td>
                <td data-testid={`risk-limit-${r.key}-used`} className="cp-num" style={cell({ ...td, textAlign: "right", whiteSpace: "nowrap" })}>{r.used == null ? "—" : r.fmt(r.used)}</td>
                <td data-testid={`risk-limit-${r.key}-left`} className="cp-num" style={cell({ ...td, textAlign: "right", whiteSpace: "nowrap" })}><Remaining row={r} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!u && <span data-testid="risk-policy-no-usage" style={quiet}>The route sent no usage figures, so used and remaining are not shown.</span>}
      <TrustLine source={SOURCE} method={p.policyVersion} maker="rules" testId="risk-trust-policy" />
    </div>
  );
}

// ── 03 decisions ─────────────────────────────────────────────────────────

/** Outcome in words. "allow" and "block" are the gate's; an older row's other word is shown as given, in a neutral tone. */
function outcomeOf(o: string | null): { label: string; tone: Tone } {
  const k = (o ?? "").toLowerCase();
  if (k === "allow" || k === "allowed") return { label: "Allowed", tone: "mint" };
  if (k === "block" || k === "blocked") return { label: "Blocked", tone: "danger" };
  return { label: o ?? "No outcome recorded", tone: "ink" };
}

function DecisionItem({ d, first }: { d: RiskDecision; first: boolean }) {
  const o = outcomeOf(d.outcome);
  return (
    <li data-testid="risk-decision" data-outcome={d.outcome ?? ""} className="flex min-w-0 flex-col" style={{ gap: 6, padding: first ? "0 0 12px" : "12px 0", borderTop: first ? 0 : "1px solid var(--cp-line)" }}>
      <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px" }}>
        <span data-testid="risk-decision-outcome"><Pill tone={o.tone}>{o.label}</Pill></span>
        <span data-testid="risk-decision-path" style={mono}>{d.path ?? d.action ?? "path not recorded"}</span>
        {d.symbol && <span data-testid="risk-decision-symbol" className="cp-num" style={{ fontSize: 12.5, color: "var(--cp-ink)" }}>{d.symbol}</span>}
        {d.mode && <span style={quiet}>{modeLabel(d.mode)}</span>}
        <span className="cp-mono-note" style={{ marginLeft: "auto" }}>{at(d.at)}</span>
      </span>
      {d.reasons.length > 0 && (
        <ul data-testid="risk-decision-reasons" className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {d.reasons.map((r, i) => (
            <li key={`${r.code ?? ""}-${i}`} style={{ overflowWrap: "anywhere" }}>
              {r.message}{r.code && r.code !== r.message ? <span style={{ ...mono, color: "var(--cp-ink-3)" }}> ({r.code})</span> : null}
            </li>
          ))}
        </ul>
      )}
      {d.correlationId && (
        <span style={quiet}>Correlation id <code data-testid="risk-decision-cid" style={{ ...mono, color: "var(--cp-ink-2)" }}>{d.correlationId}</code></span>
      )}
    </li>
  );
}

// ── 04 control changes ───────────────────────────────────────────────────

const FIELD: Record<string, { name: string; on: string; off: string }> = {
  kill_switch: { name: "Kill switch", on: "on", off: "off" },
  halted: { name: "Trading halt", on: "halted", off: "not halted" },
};

function AuditItem({ e }: { e: RiskAuditEvent }) {
  const f = e.field ? FIELD[e.field] : undefined;
  const word = (v: boolean | null) => (v == null ? "unknown" : f ? (v ? f.on : f.off) : String(v));
  return (
    <li data-testid="risk-audit-event" className="flex min-w-0 flex-col" style={{ gap: 4, padding: "10px 0 10px 14px", borderLeft: "2px solid var(--line-2)" }}>
      <span className="cp-mono-note">{at(e.at)} · <span data-testid="risk-audit-actor">{e.actor ?? "unknown"}</span></span>
      <span data-testid="risk-audit-change" style={{ fontSize: 13, color: "var(--cp-ink)" }}>{f?.name ?? e.field ?? e.action ?? "Change"}: {word(e.before)} → {word(e.after)}</span>
      {e.reason && <span data-testid="risk-audit-reason" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>“{e.reason}”</span>}
      {e.policyVersion && <span className="cp-mono-note">{e.policyVersion}</span>}
    </li>
  );
}

// ── 05 risk profile ──────────────────────────────────────────────────────

const PROFILE_SOURCE = "Risk profile";
const UNKNOWN = "unknown";
const plainNum = (v: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 4 }).format(v);

/** "0.5%", "10%"; "1.5 : 1" for the minimum reward:risk; "unknown" when the route sent no number. */
function limitText(field: string, v: number | null): string {
  if (v == null) return UNKNOWN;
  return field === "min_reward_risk" ? `${plainNum(v)} : 1` : `${plainNum(v)}%`;
}
const labelOf = (view: RiskProfileView, field: string) => view.definitions[field]?.label ?? field;
const rupeesOr = (n: number | null) => (n == null ? UNKNOWN : fmtINR(n));
const unknownWhy = (reasons: string[]) => (reasons.length ? `${UNKNOWN}: ${reasons.join("; ")}` : UNKNOWN);

function ProfileLimits({ view }: { view: RiskProfileView }) {
  const { mobile } = useCopilotShell();
  const cell = (st: CSSProperties): CSSProperties => (mobile ? { ...st, padding: "8px 5px" } : st);
  const budget = (field: string): { text: string; title?: string } => {
    const key = BUDGET_OF[field];
    if (!key) return { text: "—", title: "Judged as a percentage or a ratio; there is no rupee budget for it." };
    if (!view.live) return { text: UNKNOWN, title: "The live figures could not be read." };
    const rs = view.live.budgetsRs[key] ?? null;
    return rs == null ? { text: UNKNOWN, title: "Paper equity is unknown, so the budget is too." } : { text: fmtINR(rs) };
  };
  const defLine = (k: string, v: string | null) => v && <span style={{ display: "block", overflowWrap: "anywhere" }}><span style={{ color: "var(--cp-ink-2)" }}>{k}:</span> {v}</span>;
  return (
    <div className="cp-scroll overflow-x-auto">
      <table data-testid="risk-profile-table" aria-label="Risk profile limits: the value and the rupee budget now" style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr className="cp-mono-note">
            <th scope="col" style={cell(th)}>Limit</th>
            <th scope="col" style={cell({ ...th, textAlign: "right" })}>Set to</th>
            <th scope="col" style={cell({ ...th, textAlign: "right" })}>Budget now</th>
          </tr>
        </thead>
        <tbody>
          {view.fields.map((f) => {
            const def = view.definitions[f];
            const b = budget(f);
            return (
              <tr key={f} data-testid={`risk-profile-limit-${f}`}>
                <th scope="row" style={cell({ ...td, textAlign: "left", fontWeight: 400, color: "var(--cp-ink)" })}>
                  {def && (def.basis || def.reset || def.breach) ? (
                    <details data-testid={`risk-profile-def-${f}`}>
                      <summary data-testid={`risk-profile-limit-${f}-label`} style={{ cursor: "pointer" }}>{def.label}</summary>
                      <span className="flex flex-col" style={{ ...quiet, gap: 4, marginTop: 6 }}>
                        {defLine("Measured as", def.basis)}
                        {defLine("Resets", def.reset)}
                        {defLine("On a breach", def.breach)}
                      </span>
                    </details>
                  ) : <span data-testid={`risk-profile-limit-${f}-label`}>{labelOf(view, f)}</span>}
                </th>
                <td data-testid={`risk-profile-limit-${f}-value`} className="cp-num" style={cell({ ...td, textAlign: "right", whiteSpace: "nowrap" })}>{limitText(f, view.profile.limits[f] ?? null)}</td>
                <td data-testid={`risk-profile-limit-${f}-budget`} className="cp-num" title={b.title} style={cell({ ...td, textAlign: "right", whiteSpace: "nowrap" })}>{b.text}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ k, testId, value, note }: { k: string; testId: string; value: ReactNode; note?: ReactNode }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <span className="cp-eyebrow">{k}</span>
      <span data-testid={`${testId}-value`} className="cp-num" style={{ fontSize: 13.5, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{value}</span>
      {note && <span style={{ ...quiet, overflowWrap: "anywhere" }}>{note}</span>}
    </div>
  );
}

const pnlText = (p: PeriodPnl) => (p.pnlRs == null ? unknownWhy(p.unknownReasons) : fmtINR(p.pnlRs, { signed: true }));

function ProfileEquity({ view }: { view: RiskProfileView }) {
  const p = view.profile;
  const l = view.live;
  const start = p.startingCapitalRs != null ? fmtINR(p.startingCapitalRs) : UNKNOWN;
  return (
    <div data-testid="risk-profile-equity" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <span className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}>Measured against</span>
      {l ? (
        <div className="grid" style={{ gap: 12, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,150px),1fr))" }}>
          <Stat k="Paper equity" testId="risk-profile-equity-now" value={l.equityRs != null ? fmtINR(l.equityRs) : unknownWhy(l.unknownReasons)}
            note={l.marksAsOf ? `Marks as of ${stampIst(l.marksAsOf) ?? l.marksAsOf}` : undefined} />
          <Stat k="Peak" testId="risk-profile-peak" value={rupeesOr(l.peakRs)} />
          <Stat k="Drawdown" testId="risk-profile-drawdown" value={l.drawdownPct == null ? UNKNOWN : `${fmtPct(l.drawdownPct, { digits: 2 })} below the peak`} />
          <Stat k="Today" testId="risk-profile-day" value={pnlText(l.day)} note={l.day.start ? `Since ${at(l.day.start)}` : undefined} />
          <Stat k="This week" testId="risk-profile-week" value={pnlText(l.week)} note={l.week.start ? `Since ${at(l.week.start)}` : undefined} />
          <Stat k="Open risk" testId="risk-profile-open" value={rupeesOr(l.open.riskRs)}
            note={`${l.open.positions == null ? "Open positions unknown" : `${fmtNum(l.open.positions)} open ${l.open.positions === 1 ? "position" : "positions"}`}${l.open.legacyPositions ? ` (${fmtNum(l.open.legacyPositions)} from before the risk profile)` : ""}; exposure ${rupeesOr(l.open.exposureRs)}`} />
        </div>
      ) : (
        <span data-testid="risk-profile-live-error" role="note" style={{ ...quiet, color: "var(--cp-ink-2)" }}>
          The live figures could not be read ({view.liveError ?? "no reason given"}), so paper equity, P&amp;L, open risk and the rupee budgets are unknown here.
        </span>
      )}
      {l && l.open.sectors.length > 0 && (
        <span data-testid="risk-profile-sectors" style={{ ...quiet, overflowWrap: "anywhere" }}>
          Exposure by sector: {l.open.sectors.slice(0, 6).map((s) => `${s.sector} ${fmtINR(s.rs)}`).join(" · ")}
        </span>
      )}
      <span data-testid="risk-profile-starting" style={{ ...quiet, overflowWrap: "anywhere" }}>
        Starting capital {start}, {p.startingCapitalLabel ?? "simulation default"}.
      </span>
      {p.capitalBasisText && <span data-testid="risk-profile-basis" style={{ ...quiet, overflowWrap: "anywhere" }}>Every percentage is of {p.capitalBasisText}.</span>}
    </div>
  );
}

function ProfileChangeItem({ c, view }: { c: ProfileChange; view: RiskProfileView }) {
  return (
    <li data-testid="risk-profile-change" className="flex min-w-0 flex-col" style={{ gap: 4, padding: "10px 0 10px 14px", borderLeft: "2px solid var(--line-2)" }}>
      <span className="cp-mono-note">
        {at(c.at)} · <span data-testid="risk-profile-change-actor">{c.actor ?? "unknown"}</span>{c.actorIsAdmin ? " (admin)" : ""}
      </span>
      {c.fields.length > 0
        ? c.fields.map((f) => (
          <span key={f.field} data-testid="risk-profile-change-field" style={{ fontSize: 13, color: "var(--cp-ink)" }}>
            {labelOf(view, f.field)}: {limitText(f.field, f.before)} → {limitText(f.field, f.after)}{f.loosened ? " (loosened)" : ""}
          </span>
        ))
        : <span style={{ fontSize: 13, color: "var(--cp-ink)" }}>{c.action ?? "Change"}</span>}
      {c.reason && <span data-testid="risk-profile-change-reason" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>“{c.reason}”</span>}
      {c.versionAfter != null && <span className="cp-mono-note">version {c.versionAfter}</span>}
    </li>
  );
}

function ProfileForm({ view }: { view: RiskProfileView }) {
  const m = useSetRiskProfile();
  const id = useId();
  const [field, setField] = useState(view.fields[0] ?? "");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const current = view.profile.limits[field] ?? null;
  const range = view.ranges[field] ?? null;
  const v = value.trim() === "" ? null : Number(value.trim());
  const typed = v != null && Number.isFinite(v) ? v : null;
  const looser = isLooser(field, current, typed);
  const direction = typed == null || current == null ? null
    : typed === current ? "Same as now."
    : looser ? (view.canLoosen ? "Looser than now." : `Looser than now. ${LOOSEN_ADMIN_ONLY}`)
    : "Tighter than now.";
  const edit = () => { m.reset(); setProblem(null); };
  const submit = () => {
    if (typed == null) { setProblem("Enter the new value as a number."); return; }
    if (range && (typed < range[0] || typed > range[1])) { setProblem(`Enter a value from ${plainNum(range[0])} to ${plainNum(range[1])}.`); return; }
    if (!reason.trim()) { setProblem("Give a reason: it is recorded in the change log."); return; }
    setProblem(null);
    m.mutate({ changes: { [field]: typed }, reason: reason.trim() }, { onSuccess: () => { setValue(""); setReason(""); } });
  };
  const sense = field === "min_reward_risk" ? "higher is tighter" : "lower is tighter";
  return (
    <div data-testid="risk-profile-form" className="flex min-w-0 flex-col" style={{ gap: 8, paddingTop: 12, borderTop: "1px solid var(--cp-line)" }}>
      <span className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}>{view.canLoosen ? "Change a limit" : "Tighten a limit"}</span>
      {!view.canLoosen && <span data-testid="risk-profile-admin-note" style={quiet}>{LOOSEN_ADMIN_ONLY}</span>}
      <div className="grid" style={{ gap: 8, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,200px),1fr))", alignItems: "end" }}>
        <span className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <label htmlFor={`${id}-field`} style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>Limit</label>
          <select id={`${id}-field`} data-testid="risk-profile-field" value={field} onChange={(e) => { edit(); setField(e.target.value); }} style={{ ...INPUT_STYLE, fontFamily: "var(--sans)" }}>
            {view.fields.map((f) => <option key={f} value={f}>{labelOf(view, f)} (now {limitText(f, view.profile.limits[f] ?? null)})</option>)}
          </select>
        </span>
        <span className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <label htmlFor={`${id}-value`} style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>New value{field === "min_reward_risk" ? " (reward : 1)" : " (%)"}</label>
          <input id={`${id}-value`} data-testid="risk-profile-value" inputMode="decimal" value={value} aria-describedby={`${id}-hint`}
            onChange={(e) => { edit(); setValue(e.target.value); }} style={INPUT_STYLE} />
        </span>
      </div>
      <span id={`${id}-hint`} data-testid="risk-profile-hint" style={quiet}>
        Now {limitText(field, current)}{range ? `; from ${plainNum(range[0])} to ${plainNum(range[1])}` : ""} ({sense}).{direction ? ` ${direction}` : ""}
      </span>
      <label htmlFor={`${id}-reason`} style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>Why (required; recorded in the change log)</label>
      <textarea id={`${id}-reason`} data-testid="risk-profile-reason" rows={2} maxLength={MAX_REASON} value={reason}
        onChange={(e) => { edit(); setReason(e.target.value); }} style={{ ...INPUT_STYLE, fontFamily: "var(--sans)", resize: "vertical" }} />
      <span>
        <Btn variant="primary" data-testid="risk-profile-submit" disabled={m.isPending} aria-busy={m.isPending} onClick={submit}>{m.isPending ? "Saving…" : "Save the change"}</Btn>
      </span>
      {problem && <span data-testid="risk-profile-form-error" role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>{problem}</span>}
      {m.isError && <span data-testid="risk-profile-save-error" role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>{profileProblem(m.error)}</span>}
      {m.isSuccess && (
        <span data-testid="risk-profile-saved" role="status" style={{ fontSize: 12, color: "var(--mint)" }}>
          Saved{m.data.profile.effectiveFrom ? `, in effect from ${at(m.data.profile.effectiveFrom)}` : ""}. The change is in the log above.
        </span>
      )}
    </div>
  );
}

function ProfileBody({ q }: { q: UseQueryResult<RiskProfileView> }) {
  if (q.isPending) return <LoadingBlock label="Loading your risk profile" rows={4} />;
  if (q.isError) return <div data-testid="risk-profile-error"><QueryProblem what="Your risk profile" error={q.error} onRetry={() => { void q.refetch(); }} /></div>;
  const view = q.data;
  const p = view.profile;
  const namedText = p.name ? view.namedProfiles[p.name] ?? null : null;
  const est = view.estimate;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 14 }}>
      <div data-testid="risk-profile-meta" className="flex min-w-0 flex-col" style={{ gap: 4 }}>
        <span className="flex min-w-0 flex-wrap items-center" style={{ gap: 8 }}>
          <span data-testid="risk-profile-name"><Pill tone={p.name === "custom" ? "indigo" : "ink"}>{p.name ?? "profile not named"}</Pill></span>
          <span data-testid="risk-profile-version" style={mono}>version {p.version != null ? fmtNum(p.version) : UNKNOWN} · {p.limitsVersion ?? "limits version not sent"}</span>
        </span>
        {namedText && <span data-testid="risk-profile-name-text" style={quiet}>{namedText}</span>}
        <span data-testid="risk-profile-effective" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          {p.effectiveFrom ? `In effect since ${at(p.effectiveFrom)}.` : p.stored ? "In effect; the date it took effect was not sent." : "The defaults: no change has been made for this account."}
          {p.setBy && <>{" "}Set by <span data-testid="risk-profile-set-by" style={mono}>{p.setBy}</span>{p.reason ? <>: <span data-testid="risk-profile-set-reason" style={{ overflowWrap: "anywhere" }}>“{p.reason}”</span></> : null}.</>}
        </span>
      </div>

      <ProfileLimits view={view} />
      <ProfileEquity view={view} />

      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}>Change log</span>
        {view.changes.length === 0
          ? <span data-testid="risk-profile-changes-empty" style={quiet}>No change on record yet.</span>
          : (
            <ol data-testid="risk-profile-changes" className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 2 }}>
              {view.changes.map((c, i) => <ProfileChangeItem key={`${c.at ?? ""}-${i}`} c={c} view={view} />)}
            </ol>
          )}
      </div>

      <ProfileForm view={view} />

      {est && (
        <span data-testid="risk-profile-estimate" style={{ ...quiet, overflowWrap: "anywhere" }}>
          A share entry’s estimated risk is its loss at the stop plus round-trip costs{est.costModel ? ` (${est.costModel})` : ""}{est.gapStressText ? ` and ${est.gapStressText}` : est.gapStressPct != null ? ` and a ${plainNum(est.gapStressPct)}% gap stress` : ""}.
        </span>
      )}
      <TrustLine source={PROFILE_SOURCE} mode="eod" maker="rules" method={view.riskPolicyVersion} testId="risk-trust-profile" />
    </div>
  );
}

// ── the view ─────────────────────────────────────────────────────────────

function Card({ id, num, title, testId, actions, children }: { id: string; num: string; title: ReactNode; testId: string; actions?: ReactNode; children: ReactNode }) {
  const { mobile } = useCopilotShell();
  return (
    <Widget id={`risk.${id}${mobile ? ".phone" : ""}`} testId={testId} headTestId={`${testId}-title`} num={num} title={title} actions={actions}
      headPad={mobile ? "12px 14px" : "13px 18px"} bodyStyle={{ gap: 12, padding: mobile ? "14px 14px 16px" : "16px 18px" }}>
      {children}
    </Widget>
  );
}

/** The Risk Control Center's parts, as the desk's Risk Desk splits them into views (TradingDesk.tsx). */
export type RiskSection = "status" | "policy" | "decisions" | "audit" | "profile";

/**
 * `sections` (the desk redesign of 2026-10-27): the parts this Risk Desk view shows. Left out, all five, as before.
 * Each view keeps the header with what the controls cover.
 */
export default function RiskControls({ sections }: { sections?: readonly RiskSection[] } = {}) {
  const { mobile } = useCopilotShell();
  const has = (s: RiskSection) => !sections || sections.includes(s);
  const status = useRiskStatus();
  const policy = useRiskPolicy();
  const audit = useRiskAudit();
  const decisions = useRiskDecisions();
  const profile = useRiskProfile();
  const s = status.data?.known ? status.data : null;
  const gate = s?.gateEnabled ?? null;
  return (
    <div data-testid="risk-controls" className="flex min-w-0 flex-col" style={{ gap: mobile ? 12 : 16 }}>
      <header className="flex flex-col" style={{ gap: 8 }}>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <span className="cp-eyebrow">Risk Desk</span>
          <span className="cp-pill" data-tone="mint">Paper only</span>
        </span>
        <h1 className="cp-display m-0" data-testid="risk-title" style={{ fontSize: mobile ? 28 : 34, lineHeight: 1.1, letterSpacing: "-0.02em" }}>
          Risk <em>controls</em>
        </h1>
        <p className="m-0" style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          Stop new paper positions with the kill switch or a trading halt, see the limits the policy gate applies, and every decision and change on record.
        </p>
        {s?.scope && <p data-testid="risk-scope" className="m-0" style={quiet}>Covers: {s.scope}.</p>}
        {s?.notInScope && <p data-testid="risk-scope-note" role="note" className="m-0" style={quiet}>Not covered: {s.notInScope}.</p>}
      </header>

      {has("status") && <Card id="status" num="01" title="Kill switch & halt" testId="risk-status">
        <StatusBody q={status} />
      </Card>}

      {has("policy") && <Card
        id="policy" num="02" title="Policy limits" testId="risk-policy"
        actions={gate === false
          ? <span data-testid="risk-gate-off"><Pill tone="amber">Gate off for your account</Pill></span>
          : gate === true ? <span data-testid="risk-gate-on"><Pill tone="mint">Gate on</Pill></span> : undefined}
      >
        <PolicyBody q={policy} gateEnabled={gate} />
      </Card>}

      {(has("decisions") || has("audit")) && <div className="grid" style={{ gap: mobile ? 12 : 16, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", alignItems: "start" }}>
        {has("decisions") && <Card id="decisions" num="03" title="Recent risk decisions" testId="risk-decisions">
          {decisions.isPending && <LoadingBlock label="Loading risk decisions" rows={3} />}
          {decisions.isError && <div data-testid="risk-decisions-error"><QueryProblem what="Risk decisions" error={decisions.error} onRetry={() => { void decisions.refetch(); }} /></div>}
          {decisions.isSuccess && (decisions.data.decisions.length === 0
            ? <div data-testid="risk-decisions-empty"><EmptyBlock title="No risk decisions yet" body="Each paper write the gate checks is recorded here, allowed or blocked." /></div>
            : (
              <ol data-testid="risk-decisions-list" className="m-0 flex flex-col p-0" style={{ listStyle: "none" }}>
                {decisions.data.decisions.map((d, i) => <DecisionItem key={d.id} d={d} first={i === 0} />)}
              </ol>
            ))}
          {decisions.isSuccess && <TrustLine source={SOURCE} method={decisions.data.policyVersion} maker="rules" testId="risk-trust-decisions" />}
        </Card>}

        {has("audit") && <Card id="audit" num="04" title="Control changes" testId="risk-audit">
          {audit.isPending && <LoadingBlock label="Loading control changes" rows={3} />}
          {audit.isError && <div data-testid="risk-audit-error"><QueryProblem what="Control changes" error={audit.error} onRetry={() => { void audit.refetch(); }} /></div>}
          {audit.isSuccess && (audit.data.events.length === 0
            ? <div data-testid="risk-audit-empty"><EmptyBlock title="No control changes yet" body="Turning the kill switch or the halt on or off is recorded here with who did it and why." /></div>
            : (
              <ol data-testid="risk-audit-list" className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 2 }}>
                {audit.data.events.map((e) => <AuditItem key={e.id} e={e} />)}
              </ol>
            ))}
          {audit.isSuccess && audit.data.appendOnly && <span data-testid="risk-audit-append-only" style={quiet}>Append only: no change is edited or deleted.</span>}
          {audit.isSuccess && <TrustLine source={SOURCE} method={audit.data.policyVersion} testId="risk-trust-audit" />}
        </Card>}
      </div>}

      {has("profile") && <Card id="profile" num="05" title="Risk profile" testId="risk-profile">
        <ProfileBody q={profile} />
      </Card>}
    </div>
  );
}
