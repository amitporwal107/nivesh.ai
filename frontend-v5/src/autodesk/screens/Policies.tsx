/**
 * 12 · Policies & permissions — built to docs/autodesk/design/prototype/TDPolicies.dc.html: header, operating mode by
 * account (+ the locked Autonomous live gate), effective policy table, "What agents may do on their own" + "Who must
 * approve", roles and permissions, emergency controls, version history.
 *
 * Reads GET /policies, /policies/{id}, /accounts, /desk/status, /api/auth/me. Writes (each a request contract in
 * e2e/fixtures/autodesk/requests/policies.json): POST /accounts/{id}/mode, POST /policies/{id}/versions,
 * POST /desk/controls/STOP_NEW_ENTRIES. Live trading is out of scope: its controls are locked and do nothing.
 */
import { useState } from "react";
import { isUnauthorized } from "../api";
import { dateShort } from "../format";
import { useAccounts, useDeskStatus, useIsMobile, useMe } from "../hooks";
import { screenById, screenNo } from "../nav";
import type { Account, OperatingMode, PolicyDetail } from "../types";
import { Empty, ErrorBox, Loading, Pill, ScreenHeader } from "../ui";
import { premarketOf } from "./overview/data";
import { HISTORY_DEPTH, usePolicies, usePolicyDetails, usePolicyHistory } from "./policies/data";
import { EditLimitsDialog, ModeDialog } from "./policies/dialogs";
import {
  AgentsMatrix, Emergency, EffectiveTable, LiveGate, ModeCards, Roles, Versions, WhoApproves, type ModeChange, type VersionEntry,
} from "./policies/sections";
import type { PolicyBodyJson } from "./policies/fields";

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export default function PoliciesScreen() {
  const mobile = useIsMobile();
  const def = screenById("policies");
  const policies = usePolicies();
  const rows = policies.data ?? [];
  const details = usePolicyDetails(rows);
  const history = usePolicyHistory(rows);
  const accountsQ = useAccounts();
  const status = useDeskStatus();
  const me = useMe();
  const [selected, setSelected] = useState<string | null>(null);
  const [ask, setAsk] = useState<{ account: Account; mode: OperatingMode } | null>(null);
  const [changed, setChanged] = useState<ModeChange | null>(null);
  const [editing, setEditing] = useState(false);

  const accounts = (accountsQ.data ?? []).filter((a) => a.kind !== "SIMULATION");
  const account = accounts.find((a) => a.account_id === selected) ?? accounts[0];
  const detailQ = (policyId: string | null | undefined) => (policyId ? details[rows.findIndex((p) => p.policy_id === policyId)] : undefined);
  // The policy the risk engine applies to the selected account; with no account, the tenant default new accounts get.
  const policyId = account ? account.policy_id : rows.find((p) => p.scope_type === "TENANT")?.policy_id ?? rows[0]?.policy_id;
  const polQ = detailQ(policyId);
  const policy: PolicyDetail | undefined = polQ?.data;
  const policyRow = rows.find((p) => p.policy_id === policyId);
  const body = policy?.body as PolicyBodyJson | undefined;
  const others = rows.filter((p) => p.policy_id !== policyId).length;
  const using = policyId ? accounts.filter((a) => a.policy_id === policyId).length : 0;
  const pm = premarketOf(status.data);

  const versionEntries: VersionEntry[] = rows.flatMap((p) => {
    const cur = detailQ(p.policy_id);
    const head: VersionEntry[] = cur ? [{ policy: p, version: p.current_version, q: cur }] : [];
    return [...head, ...history.filter((h) => h.policy_id === p.policy_id).map((h) => ({ policy: p, version: h.version, q: h.q }))];
  });
  const hiddenVersions = rows.filter((p) => p.current_version > HISTORY_DEPTH)
    .map((p) => `${p.name}: versions 1–${p.current_version - HISTORY_DEPTH} are not shown.`);

  const sub = rows.length
    ? `${rows.length === 1 ? "One policy" : `${rows.length} policies`} (${rows.map((p) => `${p.name} v${p.current_version}`).join(", ")}) ` +
      `${rows.length === 1 ? "governs" : "govern"} ${plural(accounts.length, "paper account")}. Every change creates a new version and an audit event; ` +
      "you may tighten any limit, and a limit looser than the default needs an admin."
    : undefined;

  return (
    <div data-testid="screen-policies" style={{ display: "flex", flexDirection: "column", gap: 22, fontFamily: "var(--sans)", color: "var(--ink)", minWidth: 0 }}>
      <ScreenHeader
        mobile={mobile}
        eyebrow={`${screenNo("policies")} · ${def.label}`}
        pills={rows.map((p) => <Pill key={p.policy_id} tone="mint"><span data-testid="policy-pill">{`${p.name} · v${p.current_version} active`}</span></Pill>)}
        title={<span data-testid="headline">The most restrictive rule always wins. <em style={{ color: "var(--mint)" }}>Autonomous live</em> stays locked until the owner decides.</span>}
        sub={sub ? <span data-testid="subline">{sub}</span> : undefined}
      />
      {policies.isLoading && <Loading label="Loading policies" rows={4} />}
      {policies.error && !isUnauthorized(policies.error) && <ErrorBox error={policies.error} what="the policies" onRetry={() => policies.refetch()} />}

      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <span className="nv-eyebrow">Operating mode by account</span>
        {accountsQ.isLoading && <Loading label="Loading accounts" rows={1} />}
        {accountsQ.error && <ErrorBox error={accountsQ.error} what="the accounts" onRetry={() => accountsQ.refetch()} />}
        {accountsQ.data && accounts.length === 0 && (
          <Empty testId="no-accounts">No desk account yet. Create a paper account from the sidebar; it starts in Research mode.</Empty>
        )}
        {accounts.length > 0 && <ModeCards accounts={accounts} policies={rows} changed={changed} onAsk={(a, mode) => setAsk({ account: a, mode })} />}
        <LiveGate />
      </section>

      {!policies.isLoading && !policies.error && (
        <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "baseline" }}>
            <span className="nv-eyebrow" data-testid="effective-eyebrow">
              Effective policy · {account ? `Paper · ${account.name}` : "Default for new accounts"}{policy ? ` · ${policy.name} v${policy.version}` : ""}
            </span>
            <div style={{ display: "flex", gap: 14, alignItems: "baseline" }}>
              <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-3)" }}>● BINDING LEVEL</span>
              {policy && <button type="button" className="ad-link" data-testid="edit-limits" onClick={() => setEditing(true)}>Edit limits ›</button>}
            </div>
          </div>
          {accounts.length > 1 && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {accounts.map((a) => (
                <Pill key={a.account_id} tone={a.account_id === account?.account_id ? "mint" : "ink"} onClick={() => setSelected(a.account_id)}>
                  <span data-testid="effective-account">{a.name}</span>
                </Pill>
              ))}
            </div>
          )}
          {account && !account.policy_id && <Empty testId="no-policy">This account has no policy attached.</Empty>}
          {polQ?.isLoading && <Loading label="Loading the policy" rows={3} />}
          {polQ?.error && <ErrorBox error={polQ.error} what="the policy" onRetry={() => polQ.refetch()} />}
          {policy && <EffectiveTable policy={policy} row={policyRow} />}
          {policy && (
            <span data-testid="effective-note" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--ink-3)" }}>
              Only the {(policyRow?.scope_type ?? policy.scope_type).toLowerCase()} level is set: {policy.name} v{policy.version} is the policy the risk
              engine applies{account ? " to this account" : ""}.{others ? ` ${plural(others, "other policy", "other policies")} ${others === 1 ? "is" : "are"} not attached to it.` : ""}
              {pm?.allowed ? ` The last pre-market check${pm.sessionDate ? ` (${dateShort(pm.sessionDate)})` : ""} narrows the allowed segments for its session to ${pm.allowed.length ? pm.allowed.join(", ").toLowerCase() : "none"}; the narrower list applies.` : ""}
            </span>
          )}
        </section>
      )}

      <div style={{ display: "grid", gridTemplateColumns: mobile ? "minmax(0,1fr)" : "minmax(0,1.2fr) minmax(0,1fr)", gap: 16, alignItems: "start" }}>
        <AgentsMatrix body={body} loading={policies.isLoading || !!polQ?.isLoading} />
        <WhoApproves body={body} loading={policies.isLoading || !!polQ?.isLoading} />
      </div>

      <Roles me={me} />

      <Emergency st={status.data} statusError={status.error} mobile={mobile} />

      {!policies.isLoading && !policies.error && <Versions entries={versionEntries} hidden={hiddenVersions} />}

      {ask && (
        <ModeDialog account={ask.account} mode={ask.mode} onClose={() => setAsk(null)}
          onDone={(a) => { setChanged({ accountId: a.account_id, mode: a.operating_mode, at: a.updated_at ?? null }); setAsk(null); }} />
      )}
      {editing && policy && (
        <EditLimitsDialog policy={policy} accountsUsing={using} onClose={() => setEditing(false)} onDone={() => setEditing(false)} />
      )}
    </div>
  );
}
