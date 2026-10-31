/**
 * Risk Desk › Controls & profile (?tab=risk&view=controls).
 *
 *   Kill switch & halt     RiskControls StatusBody: on with a reason and a confirmation; they block NEW paper entries
 *                          only; open positions are untouched and nothing is cancelled; only an admin switches them off
 *                          (GET /api/risk/status, PUT /api/risk/kill-switch, PUT /api/risk/halt)
 *   Control changes        every switch on or off, who and why, append only (GET /api/risk/audit)
 *   Risk profile           RiskControls ProfileBody: the eight limits, the equity they are measured against, the change
 *                          log and the change form (a reason is required; tightening applies now; loosening needs an
 *                          admin) (GET / PUT /api/risk/profile)
 *   Live trading           not available, with the readiness conditions (GET /api/risk/live-readiness)
 *
 * The owner's decision (2026-10-27, 16:40): the kill switch works as the backend does. No slider: the profile is the only
 * risk setting.
 */
import { EmptyBlock, LoadingBlock, Pill } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { QueryProblem } from "../../../trading/parts";
import { useLiveReadiness } from "../../../fnolab/governance-data";
import { Mark } from "../../../fnolab/parts";
import { AuditItem, Card, ProfileBody, StatusBody } from "../../RiskControls";
import { useRiskAudit, useRiskStatus } from "../../risk-controls";
import { useRiskProfile } from "../../risk-profile";
import { ViewHead, quiet } from "./parts";

export const CONTROL_RULE =
  "Anyone can switch the kill switch or the halt on, with a reason. Either one blocks new paper entries only: open positions are untouched and nothing is cancelled. Only an admin can switch them off.";
export const PROFILE_RULE = "A reason is required for every change. Tightening a limit applies now; loosening one needs an admin.";

function LiveTrading() {
  const r = useLiveReadiness();
  const ready = r.data;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <span data-testid="rd-live-headline" data-live={String(ready?.liveExecutionAvailable === true)} style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.2 }}>
        {ready?.liveExecutionAvailable
          ? <>The server reports live execution available, but this build has <span style={{ color: "var(--amber)" }}>no order path</span>.</>
          : <>Live trading: <span style={{ color: "var(--amber)" }}>not available</span>.</>}
      </span>
      <span style={{ ...quiet, color: "var(--cp-ink-2)" }}>
        Every trade on this desk is a paper trade; nothing is sent to a broker. Live orders need each condition below to pass, and none can be waived.
      </span>
      {r.isPending && <LoadingBlock label="Reading the live readiness conditions" rows={3} />}
      {r.isError && <div data-testid="rd-live-error"><QueryProblem what="The live readiness conditions" error={r.error} onRetry={() => { void r.refetch(); }} /></div>}
      {ready && (
        <>
          <span data-testid="rd-live-count"><Pill tone={ready.enforceable === ready.count && ready.count > 0 ? "mint" : "amber"}>{ready.enforceable} of {ready.count} conditions pass</Pill></span>
          <ol data-testid="rd-live-rows" className="m-0 flex flex-col p-0" style={{ listStyle: "none" }}>
            {ready.conditions.map((c) => (
              <li key={c.id} data-testid="rd-live-row" data-id={c.id} data-status={c.status} className="grid" style={{ gridTemplateColumns: "22px minmax(0,1fr)", gap: 10, padding: "9px 0", borderTop: "1px solid var(--cp-line)", alignItems: "start" }}>
                <Mark kind={c.status === "pass" ? "ok" : "fail"} />
                <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
                  <span style={{ fontSize: 13 }}>{c.label}{c.backlog ? <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--amber)", marginLeft: 8 }}>{c.backlog}</span> : null}</span>
                  <span style={{ ...quiet, overflowWrap: "anywhere" }}>{c.evidence}</span>
                </span>
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}

export function ControlsView() {
  const { mobile } = useCopilotShell();
  const status = useRiskStatus();
  const audit = useRiskAudit();
  const profile = useRiskProfile();
  const s = status.data?.known ? status.data : null;
  const title = !s
    ? "Kill switch, halt and your risk profile."
    : s.killSwitch
      ? "The kill switch is on: new paper entries are blocked."
      : s.halted
        ? "Trading is halted: new paper entries are blocked."
        : "Kill switch and halt are off; your risk profile sets every limit.";
  return (
    <div data-testid="rd-controls-view" className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
      <ViewHead view="Policy & runtime" title={title} />

      <div className="grid" style={{ gap: mobile ? 14 : 18, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", alignItems: "start" }}>
        <Card id="status" num="01" title="Kill switch & halt" testId="risk-status">
          <span data-testid="rd-control-rule" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{CONTROL_RULE}</span>
          <StatusBody q={status} />
        </Card>

        <Card id="audit" num="02" title="Control changes" testId="risk-audit">
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
        </Card>
      </div>

      <Card id="profile" num="03" title="Risk profile" testId="risk-profile">
        <span data-testid="rd-profile-rule" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          {PROFILE_RULE} Your profile is the only risk setting: there are no sliders.
        </span>
        <ProfileBody q={profile} />
      </Card>

      <Card id="rd-live" num="04" title="Live trading" testId="rd-live">
        <LiveTrading />
      </Card>
    </div>
  );
}
