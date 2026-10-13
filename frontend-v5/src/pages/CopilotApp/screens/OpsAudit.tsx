/**
 * Audit log.
 * Design: frontend-v5/design/nivesh-copilot/NVOps.dc.html, page === 'audit'.
 *
 * The design shows every analysis run, import and consequential action across
 * the platform, each replayable. The backend has no admin audit route and no
 * run records to replay, so that part is a NotConnected block.
 *
 * What is real: the audit trail of the account in use
 * (GET /api/compliance/audit, useMyAuditTrail). It is labelled with its scope
 * — one account, not the platform.
 */
import { useImpersonationStore } from "@/stores/impersonation.store";
import {
  EmptyBlock, Footnote, LoadingBlock, NotConnected, Pill, Screen, Section,
  humaniseTag, type Tone,
} from "../components/ui";
import { LoadFailed, OpsHeader, OpsTabs } from "./internal/shared";
import { useMyAuditTrail, type AuditRow } from "./internal/use-internal-data";

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

/** "13 Oct, 14:33:08" in the viewer's time zone; "—" for a bad timestamp. */
function stamp(iso?: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso);
  if (!Number.isFinite(t.getTime())) return "—";
  const day = t.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  const time = t.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
  return `${day}, ${time}`;
}

function AuditLine({ row }: { row: AuditRow }) {
  const outcome = (row.outcome ?? "").toLowerCase();
  const meta = [row.audit_id, row.action, row.resource].filter(Boolean).join(" · ");
  return (
    <div data-testid="audit-row" className="flex flex-wrap items-center" style={{ gap: "6px 16px", padding: "13px 16px", borderBottom: "1px solid var(--cp-line)" }}>
      <span data-testid="audit-time" title={row.ts ?? undefined} style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-3)", minWidth: 116 }}>{stamp(row.ts)}</span>
      <div className="flex flex-col min-w-0" style={{ flex: "1 1 240px", gap: 3 }}>
        <span data-testid="audit-action" style={{ fontSize: 14 }}>{ACTION_LABEL[row.action] ?? (humaniseTag(row.action) || row.action)}</span>
        <span data-testid="audit-meta" style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.04em", color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{meta}</span>
      </div>
      {outcome && <span data-testid="audit-outcome"><Pill tone={OUTCOME_TONE[outcome] ?? "ink"}>{outcome}</Pill></span>}
    </div>
  );
}

export default function OpsAuditScreen() {
  const trail = useMyAuditTrail(100);
  const viewingName = useImpersonationStore((s) => s.name);
  const viewing = useImpersonationStore((s) => s.profileId);
  const rows = trail.data ?? [];
  const scope = viewing ? `${viewingName || "The client you are viewing"} · this account only` : "Your account only";

  return (
    <Screen testId="screen-ops-audit">
      <OpsHeader
        title="Audit log"
        sub="Sign-ins, imports, consent changes and other recorded actions. Today this page can only show the trail of the account in use; the platform-wide log is not exposed yet."
      />
      <OpsTabs current="ops/audit" />

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

      <NotConnected
        testId="audit-platform-not-connected"
        title="The platform-wide log is not exposed yet"
        body="Actions are written to the audit trail per account, and the backend has a reader for all accounts (services/audit.py, list_admin), but no admin route calls it. No endpoint returns Copilot analysis runs with their inputs and versions, so runs cannot be listed or replayed from here."
        needs={[
          "An admin route over the audit trail for all accounts, filterable by action and account",
          "A record per Copilot analysis run: run id, tools called, data snapshot and calculation versions",
          "Advisor approvals and statement imports written to the same trail with their run id",
          "A replay endpoint that re-runs a recorded analysis against its saved inputs",
        ]}
      />
    </Screen>
  );
}
