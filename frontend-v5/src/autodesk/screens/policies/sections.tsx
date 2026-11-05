/**
 * Blocks of the Policies & permissions screen, copied from TDPolicies.dc.html. Values come from the policy body, the
 * accounts, desk status and /api/auth/me; rules that are code (Middle Office, who may loosen) are stated as the code
 * has them. Live trading and controls that act on orders or positions are shown locked / not available, with no action.
 */
import { useState, type CSSProperties } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { errorText } from "../../api";
import { dateShort, dateTimeIST, humanize, timeIST } from "../../format";
import { stopEntriesOf, useSetStopEntries } from "../../hooks";
import type { Account, DeskStatus, Me, OperatingMode, PolicyDetail } from "../../types";
import { PhaseNote } from "../../ui";
import { MODE_NOTE, MODE_OPTIONS, type PolicyRow } from "./data";
import { diffBodies, FIELDS, fmtField, type PolicyBodyJson } from "./fields";

const panel: CSSProperties = { display: "flex", flexDirection: "column", padding: "18px 20px", borderRadius: 14, border: "1px solid var(--line)", background: "var(--bg-1)", minWidth: 0 };
const panelTitle: CSSProperties = { fontFamily: "var(--display)", fontSize: 24, paddingBottom: 10 };

// ── Operating mode by account ────────────────────────────────────────────────────────────────────────────────────────

export interface ModeChange { accountId: string; mode: string; at: string | null }

export function ModeCards({ accounts, policies, changed, onAsk }: {
  accounts: Account[]; policies: PolicyRow[]; changed: ModeChange | null; onAsk: (a: Account, mode: OperatingMode) => void;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,320px),1fr))", gap: 12 }}>
      {accounts.map((a) => {
        const pol = policies.find((p) => p.policy_id === a.policy_id);
        const ch = changed && changed.accountId === a.account_id ? changed : null;
        const note = ch
          ? `Mode changed to ${(MODE_OPTIONS.find((o) => o.mode === a.operating_mode)?.label ?? a.operating_mode).toLowerCase()}${ch.at ? ` at ${timeIST(ch.at, { seconds: false })} IST` : ""} and recorded in the audit log.`
          : MODE_NOTE[a.operating_mode] ?? humanize(a.operating_mode);
        return (
          <div key={a.account_id} data-testid="mode-card" style={{ display: "flex", flexDirection: "column", gap: 12, padding: "16px 18px", borderRadius: 14, border: "1px solid var(--line)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)", minWidth: 0 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
              <span style={{ fontFamily: "var(--display)", fontSize: 22, flex: 1 }}>Paper · {a.name}</span>
              <span data-testid="mode-card-policy" style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-3)" }}>
                {pol ? `${pol.name} · v${pol.current_version}` : a.policy_id ? a.policy_id : "No policy"}
              </span>
            </div>
            {a.status !== "ACTIVE" && <span style={{ fontSize: 12, color: "var(--danger)" }}>Account {a.status.toLowerCase()}</span>}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 6 }}>
              {MODE_OPTIONS.map((o) => {
                const on = a.operating_mode === o.mode;
                const ok = o.mode !== "AUTONOMOUS_LIVE";
                return (
                  <button key={o.mode} type="button" data-testid={`mode-opt-${o.mode}`} aria-pressed={on} disabled={!ok}
                    onClick={ok && !on ? () => onAsk(a, o.mode as OperatingMode) : undefined}
                    title={ok ? undefined : "Live trading is not available: owner decision pending"}
                    style={{
                      cursor: ok && !on ? "pointer" : "default", minHeight: 40, padding: "8px 10px", borderRadius: 10,
                      border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`, background: on ? "var(--mint-soft)" : "transparent",
                      color: on ? "var(--mint)" : ok ? "var(--ink-2)" : "var(--ink-4)", fontSize: 12.5, textAlign: "left", fontFamily: "var(--sans)",
                    }}>
                    {ok || on ? o.label : `${o.label} · locked`}
                  </button>
                );
              })}
            </div>
            <span data-testid="mode-note" style={{ fontSize: 12, lineHeight: 1.5, color: ch ? "var(--amber)" : "var(--ink-3)" }}>{note}</span>
          </div>
        );
      })}
    </div>
  );
}

export function LiveGate() {
  const gate = ["Broker permission", "Simulator certification", "Compliance approval", "Kill-switch drill"];
  return (
    <div data-testid="live-gate" style={{ display: "flex", flexDirection: "column", gap: 6, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
      <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", color: "var(--amber)" }}>AUTONOMOUS LIVE · LOCKED</span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 18px", fontSize: 13, color: "var(--ink-2)" }}>
        {gate.map((g) => <span key={g}><span style={{ color: "var(--ink-4)", fontFamily: "var(--mono)" }}>—</span> {g}</span>)}
      </div>
      <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--ink-3)" }}>
        Not available: live trading awaits the owner's decision, and brokers stay read-only. None of these steps exists yet.
      </span>
    </div>
  );
}

// ── Effective policy ─────────────────────────────────────────────────────────────────────────────────────────────────

const SCOPES: [string, string][] = [["TENANT", "Tenant"], ["ACCOUNT", "Account"], ["STRATEGY", "Strategy"], ["SEGMENT", "Segment"]];
const EFF_COLS = "minmax(0,1.5fr) repeat(4,minmax(0,1fr)) minmax(0,1.1fr)";

export function EffectiveTable({ policy, row }: { policy: PolicyDetail; row: PolicyRow | undefined }) {
  const body = policy.body as PolicyBodyJson;
  const scope = row?.scope_type ?? policy.scope_type;
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 14, background: "var(--bg-1)", overflow: "hidden" }}>
      <div data-testid="effective-scroll" style={{ overflowX: "auto" }}>
        <div data-testid="effective-table" style={{ minWidth: 820 }}>
          <div style={{ display: "grid", gridTemplateColumns: EFF_COLS, gap: 12, padding: "10px 18px", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--ink-3)" }}>
            <span>Field</span>
            {SCOPES.map(([k, l]) => <span key={k} data-testid={`eff-head-${k}`}>{k === scope ? `● ${l} · v${policy.version}` : l}</span>)}
            <span>Effective</span>
          </div>
          {FIELDS.map((f) => {
            const v = fmtField(f.kind, body[f.key]);
            return (
              <div key={f.key} data-testid={`eff-row-${f.key}`} style={{ display: "grid", gridTemplateColumns: EFF_COLS, gap: 12, padding: "10px 18px", borderTop: "1px solid var(--line)", fontSize: 13, alignItems: "baseline" }}>
                <span style={{ color: "var(--ink-2)" }}>{f.label}</span>
                {SCOPES.map(([k]) => (
                  <span key={k} className="nv-num" style={{ color: k === scope ? "var(--ink)" : "var(--ink-4)", overflowWrap: "anywhere", fontSize: f.kind === "list" ? 11.5 : undefined }}>
                    {k === scope ? (f.kind === "list" && Array.isArray(body[f.key]) ? `${(body[f.key] as unknown[]).length} allowed` : v) : "—"}
                  </span>
                ))}
                <span data-testid="eff-value" className="nv-num" style={{ fontWeight: 500, color: "var(--mint)", overflowWrap: "anywhere", fontSize: f.kind === "list" ? 11.5 : undefined }}>{v}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── What agents may do on their own · Who must approve ───────────────────────────────────────────────────────────────

type Cell = "AUTO" | "APPROVAL" | "NEVER" | "LOCKED";
const CELL: Record<Cell, string> = { AUTO: "var(--mint)", APPROVAL: "var(--amber)", NEVER: "var(--danger)", LOCKED: "var(--ink-4)" };
const MX = "minmax(0,1.6fr) repeat(3,minmax(0,1fr))";

function NoPolicy({ loading, title, testId }: { loading: boolean; title: string; testId: string }) {
  return (
    <section data-testid={testId} style={panel}>
      <span style={panelTitle}>{title}</span>
      <span style={{ fontSize: 13, color: "var(--ink-3)" }}>{loading ? "Loading the policy…" : "No policy to show: the desk has no policy yet."}</span>
    </section>
  );
}

export function AgentsMatrix({ body, loading }: { body: PolicyBodyJson | undefined; loading: boolean }) {
  if (!body) return <NoPolicy loading={loading} title="What agents may do on their own" testId="agents-matrix" />;
  const auto = body.autonomy?.auto_approve !== false;
  const rows: [string, Cell, Cell][] = [
    ["Scan the market and publish signals", "AUTO", "AUTO"],
    ["Draft a trade plan from a signal", "AUTO", "AUTO"],
    ["Risk-check a plan and size it to the policy", "AUTO", "AUTO"],
    ["Revise a plan the risk check cut down", "AUTO", "AUTO"],
    ["Approve a plan inside the autonomy rules", "APPROVAL", auto ? "AUTO" : "APPROVAL"],
    ["Approve a plan outside the autonomy rules", "APPROVAL", "APPROVAL"],
    ["Approve a plan whose risk check failed", "NEVER", "NEVER"],
    ["Change a policy limit", "NEVER", "NEVER"],
  ];
  return (
    <section data-testid="agents-matrix" style={panel}>
      <span style={panelTitle}>What agents may do on their own</span>
      <div style={{ display: "grid", gridTemplateColumns: MX, gap: 8, paddingBottom: 6, fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--ink-3)" }}>
        <span>Action</span><span>Assisted</span><span>Auto paper</span><span>Auto live</span>
      </div>
      {rows.map(([k, a, p]) => (
        <div key={k} data-testid="matrix-row" style={{ display: "grid", gridTemplateColumns: MX, gap: 8, padding: "8px 0", borderTop: "1px solid var(--line)", fontSize: 12.5, alignItems: "center" }}>
          <span style={{ color: "var(--ink-2)" }}>{k}</span>
          {([a, p, "LOCKED"] as Cell[]).map((v, i) => (
            <span key={i} style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.06em", color: CELL[v] }}>{v}</span>
          ))}
        </div>
      ))}
      <div style={{ paddingTop: 10 }}>
        <PhaseNote testId="matrix-phase-note">
          Position actions (opening, trailing, closing, rolling or resizing a position) come with paper execution (Phase 2).
          Auto live is locked: live trading awaits the owner's decision.
        </PhaseNote>
      </div>
    </section>
  );
}

export function WhoApproves({ body, loading }: { body: PolicyBodyJson | undefined; loading: boolean }) {
  if (!body) return <NoPolicy loading={loading} title="Who must approve" testId="who-approves" />;
  const a = body.autonomy;
  const strategies = (a?.strategies ?? []).map((s) => humanize(s)).join(", ");
  const rows: [string, string][] = [
    ["Every plan on an Assisted account", "You, the account owner"],
    ...(a?.auto_approve === false ? [["Every plan on an Autonomous paper account", "You · automatic approval is switched off in the policy"] as [string, string]] : []),
    [`Plan risk above ${fmtField("pct", a?.max_risk_pct)} of equity`, "You · the Middle Office sends it to you"],
    [`Signal score below ${fmtField("num", a?.min_signal_score)}`, "You · the Middle Office sends it to you"],
    ["Strategy outside the autonomy list", `You · approved automatically only: ${strategies || "none"}`],
    ["Plan whose risk check failed", "Never approved · the Middle Office rejects it"],
    ["Plan the risk check passes only at a smaller size", "Sent back for revision"],
    ["Any plan on a Research account", "Never approved · research only"],
    ["Policy or limit change", "You may tighten any limit; looser than the default needs an admin · versioned and audited"],
    ["Live trading", "Not available · owner decision pending"],
  ];
  return (
    <section data-testid="who-approves" style={panel}>
      <span style={panelTitle}>Who must approve</span>
      {rows.map(([k, v]) => (
        <div key={k} data-testid="approve-row" style={{ display: "flex", flexDirection: "column", gap: 3, padding: "9px 0", borderTop: "1px solid var(--line)" }}>
          <span style={{ fontSize: 13.5 }}>{k}</span>
          <span style={{ fontSize: 12, color: "var(--ink-3)", overflowWrap: "anywhere" }}>{v}</span>
        </div>
      ))}
    </section>
  );
}

// ── Roles and permissions ────────────────────────────────────────────────────────────────────────────────────────────

const PERM_HEAD = ["Approve live", "Approve paper", "Edit limits", "Emergency", "Change mode", "View audit"];
const RC = "minmax(0,1.5fr) repeat(6,minmax(0,1fr))";

export function Roles({ me }: { me: UseQueryResult<Me> }) {
  const admin = (me.data?.role ?? "").toLowerCase() === "admin";
  const rows: { id: string; n: string; p: string[] }[] = [
    { id: "owner", n: "Account owner", p: ["—", "✓", "Tighten", "✓", "✓", "✓"] },
    { id: "admin", n: "Administrator", p: ["—", "✓", "✓", "✓", "✓", "✓"] },
  ];
  const mine = me.data ? (admin ? "admin" : "owner") : null;
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <span className="nv-eyebrow">Roles and permissions</span>
      <div style={{ border: "1px solid var(--line)", borderRadius: 14, background: "var(--bg-1)", overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <div style={{ minWidth: 760 }}>
            <div style={{ display: "grid", gridTemplateColumns: RC, gap: 10, padding: "10px 18px", fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--ink-3)" }}>
              <span>Role</span>{PERM_HEAD.map((h) => <span key={h} style={{ textAlign: "center" }}>{h}</span>)}
            </div>
            {rows.map((r) => (
              <div key={r.id} data-testid={`role-${r.id}`} data-you={mine === r.id ? "true" : undefined}
                style={{ display: "grid", gridTemplateColumns: RC, gap: 10, padding: "9px 18px", borderTop: "1px solid var(--line)", fontSize: 13, alignItems: "center", background: mine === r.id ? "var(--bg-2)" : "transparent" }}>
                <span>{r.n}{mine === r.id ? " · you" : ""}</span>
                {r.p.map((v, i) => (
                  <span key={i} style={{ textAlign: "center", fontFamily: "var(--mono)", fontSize: 12, color: v === "—" ? "var(--ink-4)" : v === "✓" ? "var(--mint)" : "var(--amber)" }}>{v}</span>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
      <span data-testid="roles-note" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--ink-3)" }}>
        {me.error ? `Your role could not be loaded: ${errorText(me.error)}. ` : "Highlighted row: your role. "}
        In Phase 1 each desk belongs to one signed-in person; trader, risk officer, approver, operations and auditor roles are not
        built yet. "Tighten": you may make a limit stricter, and only an admin may set one looser than the default. A decision on an
        approval is refused if the plan changed after you reviewed it (plan hash).
      </span>
    </section>
  );
}

// ── Emergency controls ───────────────────────────────────────────────────────────────────────────────────────────────

export const STOP_REASON = "Stopped from Policies & permissions";
export const LIFT_REASON = "Lifted from Policies & permissions";

const UNAVAILABLE: [string, string, string][] = [
  ["gen", "Suspend strategy generation", "Not a separate control in Phase 1; Stop new entries already holds back new plans."],
  ["mods", "Suspend automated modifications", "Acts on resting orders; comes with paper execution (Phase 2)."],
  ["cancel", "Cancel eligible pending entries", "Acts on unfilled orders; comes with paper execution (Phase 2)."],
  ["strat", "Suspend a strategy", "Not a control in Phase 1; the strategies the desk may use are part of the policy."],
  ["acct", "Suspend an account", "Not available in Phase 1: the API has no call to suspend an account yet."],
  ["exits", "Controlled risk-reducing exits", "Acts on positions; comes with paper execution (Phase 2)."],
  ["broker", "Disable a broker adapter", "There is no broker adapter: brokers are read-only and live trading awaits the owner's decision."],
];

export function Emergency({ st, statusError, mobile }: { st: DeskStatus | undefined; statusError: unknown; mobile: boolean }) {
  const on = stopEntriesOf(st);
  const m = useSetStopEntries();
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const ask = () => { m.reset(); setReason(on ? LIFT_REASON : STOP_REASON); setAsking(true); };
  const confirm = () => {
    const r = reason.trim();
    if (!r) return;
    m.mutate({ active: !on, reason: r.slice(0, 300) }, { onSuccess: () => setAsking(false) });
  };
  return (
    <section data-testid="emergency" style={{ display: "flex", flexDirection: "column", gap: 12, padding: mobile ? "18px 16px" : "20px 22px", borderRadius: 16, border: "1px solid var(--danger-line)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)" }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "baseline" }}>
        <span style={{ fontFamily: "var(--display)", fontSize: 26, flex: 1 }}>Emergency controls</span>
        <span style={{ fontSize: 12.5, color: "var(--ink-3)" }}>Phase 1 has one working control. There are no orders or positions yet, so nothing is cancelled.</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: 10 }}>
        <div data-testid="control-entries" style={{ display: "flex", flexDirection: "column", gap: 8, padding: "13px 15px", borderRadius: 12, border: `1px solid ${on ? "var(--danger-line)" : "var(--line)"}`, background: on ? "var(--danger-soft)" : "var(--bg-1)" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span style={{ flex: 1, fontSize: 14, fontWeight: 500 }}>Stop new entries</span>
            <span data-testid="control-entries-state" style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", color: on ? "var(--danger)" : "var(--ink-3)" }}>
              {!st ? "—" : on ? "ACTIVE" : "OFF"}
            </span>
          </div>
          <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--ink-3)" }}>
            No new plan is proposed or approved on the desk's accounts until it is lifted. Signals are still scanned; simulations of past sessions are not affected.
          </span>
          {on && (
            <span data-testid="control-entries-since" style={{ fontSize: 12, lineHeight: 1.45, color: "var(--ink-2)" }}>
              Active since {on.changed_at ? `${dateShort(on.changed_at)}, ${timeIST(on.changed_at)} IST` : "—"} by {on.changed_by ?? "—"}{on.reason ? ` · ${on.reason}` : ""}
            </span>
          )}
          {!!statusError && !st && <span style={{ fontSize: 12, color: "var(--danger)" }}>State unknown: {errorText(statusError)}</span>}
          {asking ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <input data-testid="control-reason" aria-label="Reason (kept in the audit log)" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)}
                style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 13, fontFamily: "var(--sans)" }} />
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <button type="button" data-testid="control-confirm" onClick={confirm} disabled={m.isPending || !reason.trim()}
                  style={{ cursor: m.isPending ? "default" : "pointer", padding: "8px 14px", borderRadius: 10, border: 0, background: on ? "var(--mint)" : "var(--danger)", color: on ? "#06120B" : "#fff", fontSize: 13, fontWeight: 500, opacity: m.isPending ? 0.6 : 1 }}>
                  {m.isPending ? "Saving…" : on ? "Confirm lift" : "Confirm activate"}
                </button>
                <button type="button" className="ad-link" data-testid="control-cancel" onClick={() => setAsking(false)} style={{ color: "var(--ink-3)" }}>Cancel</button>
              </div>
              {m.error && <span role="alert" data-testid="control-error" style={{ fontSize: 12.5, color: "var(--danger)" }}>{errorText(m.error)}</span>}
            </div>
          ) : st ? (
            <button type="button" className="ad-link" data-testid="control-ask" onClick={ask} style={{ alignSelf: "flex-start", fontSize: 13, color: on ? "var(--mint)" : "var(--danger)" }}>
              {on ? "Lift this control" : "Activate…"}
            </button>
          ) : null}
        </div>
        {UNAVAILABLE.map(([id, t, d]) => (
          <div key={id} data-testid={`control-${id}`} style={{ display: "flex", flexDirection: "column", gap: 8, padding: "13px 15px", borderRadius: 12, border: "1px solid var(--line)", background: "var(--bg-1)" }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span style={{ flex: 1, fontSize: 14, fontWeight: 500, color: "var(--ink-2)" }}>{t}</span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-4)" }}>NOT AVAILABLE</span>
            </div>
            <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--ink-3)" }}>{d}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── Version history ──────────────────────────────────────────────────────────────────────────────────────────────────

export interface VersionEntry { policy: PolicyRow; version: number; q: UseQueryResult<PolicyDetail> | { data: PolicyDetail; error: null; isLoading: false } }

export function Versions({ entries, hidden }: { entries: VersionEntry[]; hidden: string[] }) {
  return (
    <section data-testid="versions" style={panel}>
      <span style={panelTitle}>Version history</span>
      {entries.map((e, i) => {
        const d = e.q.data;
        const active = e.version === e.policy.current_version;
        const prev = entries.find((x) => x.policy.policy_id === e.policy.policy_id && x.version === e.version - 1)?.q.data;
        const next = entries.find((x) => x.policy.policy_id === e.policy.policy_id && x.version === e.version + 1)?.q.data;
        const changes = d ? diffBodies(prev?.body as PolicyBodyJson | undefined, d.body as PolicyBodyJson) : [];
        const when = !d ? "—" : active ? `Since ${dateTimeIST(d.created_at)}` : `${dateTimeIST(d.created_at)} – ${next ? dateTimeIST(next.created_at) : "—"}`;
        const c = active ? "var(--mint)" : "var(--ink-3)";
        const line = active ? "var(--mint-line)" : "var(--line-2)";
        const x = e.q.error
          ? `Could not load this version: ${errorText(e.q.error)}`
          : !d ? "Loading…"
            : [changes.length ? changes.join("; ") : null, d.reason ? `“${d.reason}”` : null, `by ${d.created_by}`].filter(Boolean).join(" · ");
        return (
          <div key={`${e.policy.policy_id}:${e.version}`} data-testid="version-row" style={{ display: "flex", flexDirection: "column", gap: 4, padding: "10px 0", borderTop: `1px solid ${i ? "var(--line)" : "var(--line)"}` }}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <span style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>{e.policy.name} · v{e.version}</span>
              <span className="nv-pill" data-testid="version-state" style={{ padding: "1px 8px", fontSize: 9, color: c, borderColor: line }}>{active ? "ACTIVE" : "RETIRED"}</span>
              <span style={{ flex: 1 }} />
              <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)" }}>{when}</span>
            </div>
            <span data-testid="version-text" style={{ fontSize: 13, lineHeight: 1.5, color: e.q.error ? "var(--danger)" : "var(--ink-2)", overflowWrap: "anywhere" }}>{x}</span>
          </div>
        );
      })}
      {hidden.map((h) => <span key={h} style={{ paddingTop: 8, fontSize: 12, color: "var(--ink-3)" }}>{h}</span>)}
    </section>
  );
}
