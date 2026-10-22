/**
 * Audit log.
 * Design: frontend-v5/design/nivesh-copilot/NVOps.dc.html, page === 'audit'.
 *
 * The design shows every analysis run, import and consequential action across
 * the platform, each replayable. The backend writes one audit trail for all
 * accounts but has no admin route that reads it, and keeps no run records to
 * replay, so that part is a NotConnected block.
 *
 * What is real, each labelled with what it covers:
 *   GET /api/compliance/audit    the audit trail of the account in use
 *   GET /api/admin/users         the newest sign-in of every account (user directory)
 *   GET /api/admin/mf/audit-log  the server's log of fund-data refreshes
 */
import { useState } from "react";
import { useImpersonationStore } from "@/stores/impersonation.store";
import {
  EmptyBlock, Footnote, LoadingBlock, NotConnected, Pill, Screen, Section,
  humaniseTag, type Tone,
} from "../components/ui";
import { BrokerIcon } from "../components/EntityIcon";
import { LoadFailed, OpsHeader, OpsTabs, SectionTabs, stamp } from "./internal/shared";
import { useMyAuditTrail, type AuditRow } from "./internal/use-internal-data";
import { FundRefreshLog, SignInsByAccount } from "./internal/ops-audit-sections";

/** Plain wording for the actions the backend records (services/audit.py). */
const ACTION_LABEL: Record<string, string> = {
  login: "Signed in",
  logout: "Signed out",
  login_failed: "Sign-in failed",
  cas_upload: "CAS statement uploaded",
  cas_parse_failed: "CAS statement could not be parsed",
  portfolio_view: "Portfolio viewed",
  portfolio_refresh: "Portfolio refreshed",
  pan_view: "PAN viewed",
  pan_update: "PAN stored",
  pan_delete: "PAN erased",
  plan_generate: "Action plan generated",
  plan_apply: "Plan action applied",
  plan_skip: "Plan action skipped",
  consent_grant: "Consent granted",
  consent_withdraw: "Consent withdrawn",
  data_export: "Data export requested",
  data_delete: "Data deletion requested",
  admin_override: "Admin override",
  admin_impersonate: "Admin viewed an account",
  broker_connect: "Broker connected",
  broker_sync: "Broker holdings synced",
  broker_disconnect: "Broker disconnected",
};

const OUTCOME_TONE: Record<string, Tone> = { success: "mint", denied: "amber", error: "danger" };

/** The broker a broker_* action names (details.broker, e.g. "zerodha"), as a display name. */
function brokerOf(row: AuditRow): string | null {
  if (!row.action.startsWith("broker_")) return null;
  const slug = row.details?.broker;
  return typeof slug === "string" && slug.trim() ? humaniseTag(slug) : null;
}

function AuditLine({ row }: { row: AuditRow }) {
  const outcome = (row.outcome ?? "").toLowerCase();
  const meta = [row.audit_id, row.action, row.resource].filter(Boolean).join(" · ");
  const broker = brokerOf(row);
  return (
    <div data-testid="audit-row" className="flex flex-wrap items-center" style={{ gap: "6px 16px", padding: "13px 16px", borderBottom: "1px solid var(--cp-line)" }}>
      <span data-testid="audit-time" title={row.ts ?? undefined} style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-3)", minWidth: 116 }}>{stamp(row.ts)}</span>
      <div className="flex items-center min-w-0" style={{ flex: "1 1 240px", gap: 10 }}>
        {broker && <BrokerIcon name={broker} size={24} />}
        <div className="flex flex-col min-w-0" style={{ gap: 3 }}>
          <span data-testid="audit-action" style={{ fontSize: 14 }}>
            {ACTION_LABEL[row.action] ?? (humaniseTag(row.action) || row.action)}
            {broker && <span data-testid="audit-broker" style={{ color: "var(--cp-ink-2)" }}> · {broker}</span>}
          </span>
          <span data-testid="audit-meta" style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.04em", color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{meta}</span>
        </div>
      </div>
      {outcome && <span data-testid="audit-outcome"><Pill tone={OUTCOME_TONE[outcome] ?? "ink"}>{outcome}</Pill></span>}
    </div>
  );
}

function AccountTrail() {
  const trail = useMyAuditTrail(100);
  const viewingName = useImpersonationStore((s) => s.name);
  const viewing = useImpersonationStore((s) => s.profileId);
  const rows = trail.data ?? [];
  const scope = viewing ? `${viewingName || "The client you are viewing"} · this account only` : "Your account only";

  return (
    <div className="flex flex-col" style={{ gap: 10 }}>
      {trail.isPending && <LoadingBlock label="Loading the audit trail" rows={4} />}
      {trail.isError && (
        <LoadFailed
          what="The audit trail"
          error={trail.error}
          onRetry={() => trail.refetch()}
          forbidden="The server refused to return this account’s audit trail (403). Sign in again, or use an account that is allowed to read it."
        />
      )}
      {trail.data && rows.length === 0 && (
        <div data-testid="audit-empty">
          <EmptyBlock
            title="No recorded actions for this account"
            body="Nothing has been written to the audit trail for the account in use. Sign-ins, statement uploads, consent changes and broker connections appear here once they happen."
          />
        </div>
      )}
      {rows.length > 0 && (
        <Section
          flush
          title={<>{scope} · <span data-testid="audit-count">{rows.length}</span> most recent</>}
          note="Newest first"
        >
          <div data-testid="audit-list">
            {rows.map((r, i) => <AuditLine key={r.audit_id ?? `${r.ts ?? ""}-${i}`} row={r} />)}
          </div>
        </Section>
      )}
      {rows.length > 0 && <Footnote>Times are shown in your time zone · the list holds at most the last 100 actions</Footnote>}
    </div>
  );
}

type Tab = "account" | "signins" | "funds";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "account", label: "This account" },
  { id: "signins", label: "Sign-ins by account" },
  { id: "funds", label: "Fund-data refreshes" },
];

export default function OpsAuditScreen() {
  const [tab, setTab] = useState<Tab>("account");

  return (
    <Screen testId="screen-ops-audit">
      <OpsHeader
        title="Audit log"
        sub="Recorded actions of the account in use, the newest sign-in of every account, and the server’s log of fund-data refreshes. The audit trail of all accounts together is written by the backend but not exposed to this page yet."
      />
      <OpsTabs current="ops/audit" />

      <div className="flex flex-col" style={{ gap: 14 }}>
        <SectionTabs label="Audit log sections" testId="audit-tabs" tabs={TABS} current={tab} onChange={setTab} />
        {tab === "account" && <AccountTrail />}
        {tab === "signins" && <SignInsByAccount />}
        {tab === "funds" && <FundRefreshLog />}
      </div>

      <NotConnected
        testId="audit-platform-not-connected"
        title="The platform-wide log is not exposed yet"
        body="Every account’s actions — sign-ins, statement uploads, PAN and portfolio views, consent changes, broker connections, admin overrides — are written to one audit trail, and the backend has a reader for all of them (services/audit.py, list_admin), but no admin route calls it. Model calls are not logged at all, and no Copilot analysis run is stored with its inputs and versions, so runs cannot be listed or replayed from here."
        needs={[
          "An admin route over the audit trail for all accounts, filterable by action and account (the reader exists: services/audit.py list_admin)",
          "A record per model call: who asked, which model, tokens in and out, duration, outcome",
          "A record per Copilot analysis run: run id, tools called, data snapshot and calculation versions",
          "Advisor approvals and statement imports written to the same trail with their run id",
          "A replay endpoint that re-runs a recorded analysis against its saved inputs",
          "The infrastructure operator log (restart / run-now actions) readable with an admin session — today it needs a separate service token",
        ]}
      />
    </Screen>
  );
}
