/**
 * SIP board — every SIP recorded for the advisor's clients, grouped by what it
 * needs: failed, mandate ending, step-up due, on track.
 *
 * The original v5 app has the client and the hooks for this (useSipBoard,
 * useSipBoardSummary) but no page, so this screen is the shell's own.
 *
 * Data:
 *   tiles     GET /api/advisor/sip-board/summary   (useSipSummary)
 *   queues    GET /api/advisor/sip-board           (useSipQueues)
 *
 * A row opens that client's Client 360. There is no "message the client"
 * button: the endpoint behind it (POST …/sip-nudge) only stores a request that
 * nothing sends.
 */
import type { ReactNode } from "react";
import {
  DataTable, ErrorBlock, Footnote, LoadingBlock, NotConnected, Screen, ScreenHeader, Section, Tiles,
  fmtDate, fmtINR, fmtNum, fmtPct,
  type Column, type TileItem,
} from "../../components/ui";
import { FundName } from "../../components/EntityIcon";
import { useCopilotShell } from "../../lib/shell-context";
import { SIP_QUEUES, cycleLabel, humanise, useSipQueues, useSipSummary, type SipQueue, type SipRow } from "./data";
import { AdvisorOnly, Quiet, client360View, useAdvisorSession } from "./parts";

/** The server sends at most this many of the on-track SIPs. */
const HEALTHY_CAP = 20;

const QUEUE_TITLE: Record<SipQueue, string> = {
  failed: "Failed",
  expiring: "Mandate ending",
  step_up: "Step-up due",
  healthy: "On track",
};

const QUEUE_NOTE: Record<SipQueue, string> = {
  failed: "The last debit did not go through",
  expiring: "The bank mandate ends soon",
  step_up: "An increase has been proposed",
  healthy: "Debiting as planned",
};

const QUEUE_EMPTY: Record<SipQueue, string> = {
  failed: "No SIP has failed this cycle.",
  expiring: "No mandate is close to ending.",
  step_up: "No step-up is waiting.",
  healthy: "No SIP is recorded as on track.",
};

const QUEUE_MIN_WIDTH: Record<SipQueue, number> = { failed: 860, expiring: 760, step_up: 760, healthy: 760 };

/** The columns every queue has, then the ones that say why a SIP is in this queue. */
function columns(queue: SipQueue): Array<Column<SipRow>> {
  const shared: Array<Column<SipRow>> = [
    {
      key: "client", header: "Client", width: "minmax(0,1fr)",
      render: (r) => <span data-testid="sip-client" style={{ fontWeight: 500, color: "var(--cp-ink)" }}>{(r.client_name ?? "").trim() || "—"}</span>,
    },
    {
      key: "fund", header: "Fund", width: "minmax(0,2fr)",
      render: (r) => {
        const name = (r.fund_name ?? "").trim();
        // The server sends a dash when a SIP has no fund name on record.
        return name && name !== "—" ? <FundName testId="sip-fund" name={name} size={24} /> : "—";
      },
    },
    { key: "amount", header: "Amount", width: "90px", align: "right", num: true, render: (r) => <span data-testid="sip-amount">{fmtINR(r.amount_rs)}</span> },
    { key: "cadence", header: "Every", width: "90px", render: (r) => humanise(r.cadence) || "—" },
  ];
  const nextDebit: Column<SipRow> = { key: "next", header: "Next debit", width: "110px", render: (r) => fmtDate(r.next_debit_date) };

  if (queue === "failed") {
    return [
      ...shared,
      { key: "bounced", header: "Bounced on", width: "110px", render: (r) => <span data-testid="sip-bounced">{fmtDate(r.last_bounce_date)}</span> },
      { key: "reason", header: "Reason", width: "minmax(0,1.3fr)", render: (r) => <span data-testid="sip-reason" title={humanise(r.last_bounce_reason) || undefined}>{humanise(r.last_bounce_reason) || "—"}</span> },
      { key: "missed", header: "Missed", width: "70px", align: "right", num: true, render: (r) => <span data-testid="sip-missed">{fmtNum(r.cycles_missed ?? 0)}</span> },
    ];
  }
  if (queue === "step_up") {
    return [
      ...shared, nextDebit,
      { key: "stepup", header: "Proposed increase", width: "140px", align: "right", num: true, render: (r) => <span data-testid="sip-detail">{fmtPct(r.proposed_stepup_pct, { digits: 0 })}</span> },
    ];
  }
  return [
    ...shared, nextDebit,
    { key: "mandate", header: queue === "expiring" ? "Mandate ends" : "Mandate valid until", width: "140px", render: (r) => <span data-testid="sip-detail">{fmtDate(r.mandate_expiry_date)}</span> },
  ];
}

function Board() {
  const { go } = useCopilotShell();
  const summary = useSipSummary();
  const board = useSipQueues();

  const s = summary.data;
  const tile = (testId: string, text: string | undefined) => (
    summary.isPending ? "…" : summary.isError || text === undefined ? "—" : <span data-testid={testId}>{text}</span>
  );
  const tiles: TileItem[] = [
    { k: "SIPs on record", v: tile("sip-tile-count", s && fmtNum(s.active_sips_count)), s: "Across your clients" },
    { k: "Monthly inflow", v: tile("sip-tile-inflow", s && fmtINR(s.monthly_inflow_rs, { compact: true })), s: "From the monthly SIPs" },
    { k: "Failed", v: tile("sip-tile-failed", s && fmtNum(s.failed_count)), s: "Last debit did not go through", tone: s && s.failed_count > 0 ? "danger" : "ink" },
    { k: "Mandates ending", v: tile("sip-tile-mandates", s && fmtNum(s.mandate_at_risk_count)), s: "Within the next 90 days", tone: s && s.mandate_at_risk_count > 0 ? "amber" : "ink" },
  ];

  const cycle = board.data ? cycleLabel(board.data.cycle) : "";

  let body: ReactNode;
  if (board.isPending) {
    body = <LoadingBlock label="Loading the SIP board" rows={5} />;
  } else if (board.isError) {
    body = <ErrorBlock title="The SIP board didn’t load" error={board.error} onRetry={() => board.refetch()} />;
  } else {
    const { queues } = board.data;
    const total = SIP_QUEUES.reduce((n, q) => n + queues[q].length, 0);
    body = total === 0 ? (
      <NotConnected
        testId="sip-empty"
        title="No SIPs on this board yet"
        body="This board lists the SIPs recorded for your clients. None are recorded. SIPs that Nivesh finds in a client’s statement are not added to this board yet, so it stays empty for now."
        needs={[
          "GET /api/advisor/sip-board and /sip-board/summary read a SIP store (db.sips) that nothing in the backend writes",
          "SIPs detected from statements are saved separately (detected_sips) and served per investor by GET /api/portfolio/sips",
          "Feed this board from that store for every client in the workspace, or add the writer the board expects (state, mandate dates, bounce reason)",
        ]}
      />
    ) : SIP_QUEUES.map((queue) => {
      const rows = queues[queue];
      const capped = queue === "healthy" && rows.length >= HEALTHY_CAP;
      return (
        <div key={queue} data-testid={`sip-queue-${queue}`} className="min-w-0">
          <Section
            flush={rows.length > 0}
            title={<>{QUEUE_TITLE[queue]} · <span data-testid={`sip-queue-${queue}-count`}>{fmtNum(rows.length)}</span></>}
            note={capped ? `The first ${HEALTHY_CAP} are listed` : QUEUE_NOTE[queue]}
          >
            {rows.length === 0 ? (
              <Quiet>{QUEUE_EMPTY[queue]}</Quiet>
            ) : (
              <DataTable
                columns={columns(queue)}
                rows={rows}
                rowKey={(r, i) => `${queue}-${r.sip_id ?? ""}-${i}`}
                minWidth={QUEUE_MIN_WIDTH[queue]}
                onRowClick={(r) => { if (r.profile_id) go(client360View(r.profile_id)); }}
              />
            )}
          </Section>
        </div>
      );
    });
  }

  return (
    <>
      <ScreenHeader
        eyebrow="Advisor · SIP board"
        title={<>SIPs across your <em>book</em></>}
        sub={`Every SIP recorded for your clients, grouped by what it needs${cycle ? ` · ${cycle}` : ""}. Select a row to open that client.`}
      />

      <Tiles items={tiles} />
      {summary.isError && <ErrorBlock title="The SIP totals didn’t load" error={summary.error} onRetry={() => summary.refetch()} />}

      {body}

      <Footnote>SIP details are what is on record for each client · amounts are per instalment · this screen does not message a client or change a SIP</Footnote>
    </>
  );
}

export default function SipBoardScreen() {
  const session = useAdvisorSession();
  return (
    <Screen testId="screen-advisor-sip-board" width={1000}>
      <AdvisorOnly session={session}>
        <Board />
      </AdvisorOnly>
    </Screen>
  );
}
