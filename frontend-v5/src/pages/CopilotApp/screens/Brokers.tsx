/**
 * Broker connections — where the portfolio comes from.
 * Design: frontend-v5/design/nivesh-copilot/NVBrokers.dc.html.
 *
 * Real: CAS statements (uploaded, or found in Gmail), the broker accounts the
 * server holds for the user with what was read from each (sync, reconnect,
 * disconnect), and the brokers the server lists (./account/brokers). Read-only
 * throughout: nothing here can place an order.
 *
 * A broker sign-in is offered only for a broker the server marks connectable.
 * Today's backend marks none, so today none is offered and the screen says so;
 * the copy that depends on that is chosen from the same field.
 */
import type { UseQueryResult } from "@tanstack/react-query";
import { BrokerIcon } from "../components/EntityIcon";
import { DataTable, EmptyBlock, ErrorBlock, Eyebrow, LoadingBlock, Pill, Screen, ScreenHeader, Section, TONE_COLOR, fmtDate, fmtINR, fmtNum, relTime, type Column, type Tone } from "../components/ui";
import { BrokerAccounts, BrokerConnect, BrokerReturnNotice } from "./account/brokers";
import { GmailSource, StatementUpload } from "./account/parts";
import { saysConnectable, useBrokerAccounts, useBrokerAdapters } from "./account/broker-queries";
import {
  hasStatement,
  useAuditTrail,
  useGmailImportHistory,
  useGmailSourceStatus,
  useOnboardingState,
  type AuditRow,
  type GmailImport,
  type OnboardingState,
} from "./account/queries";

// ── connected: statement on file ─────────────────────────────────────────

function StatementOnFile({ q }: { q: UseQueryResult<OnboardingState> }) {
  if (q.isPending) return <LoadingBlock label="Loading statement status" rows={2} />;
  if (q.isError) return <ErrorBlock title="Statement status didn’t load" error={q.error} onRetry={() => q.refetch()} />;
  const s = q.data;
  if (!hasStatement(s)) {
    return <EmptyBlock title="No statement on file" body="Upload a CAS PDF below, or connect Gmail and Nivesh will look for your latest one." />;
  }
  return (
    <div data-testid="statement-source" className="cp-card-raised flex flex-col" style={{ gap: 12, padding: "16px 18px" }}>
      <div className="flex flex-wrap items-center" style={{ gap: "10px 14px" }}>
        <BrokerIcon name="CAS statement" size={38} />
        <div className="flex flex-col" style={{ flex: "1 1 200px", gap: 2, minWidth: 0 }}>
          <span style={{ fontSize: 15, fontWeight: 500 }}>CAS statement</span>
          <span className="cp-mono-note">
            {s.cas_statement_period ? <>Period <span data-testid="statement-period">{s.cas_statement_period}</span></> : "Period not on the statement"}
            {s.cas_statement_date ? <> · dated <span data-testid="statement-date">{s.cas_statement_date}</span></> : null}
          </span>
        </div>
        <Pill tone="mint">On file</Pill>
      </div>
      <div className="flex flex-wrap items-baseline" style={{ gap: "6px 18px" }}>
        {s.cas_portfolio_value_rs != null && (
          <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>
            Value on the statement <span className="cp-num" data-testid="statement-value" style={{ fontSize: 15, color: "var(--cp-ink)" }}>{fmtINR(s.cas_portfolio_value_rs)}</span>
          </span>
        )}
        <span data-testid="statement-pan" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>
          {s.pan_on_file ? "PAN saved for unlocking statements" : "No PAN saved"}
        </span>
      </div>
    </div>
  );
}

// ── how importing works / what is read ───────────────────────────────────

const IMPORT_STEPS: Array<{ n: string; t: string; d: string }> = [
  { n: "01", t: "Get a CAS", d: "A consolidated account statement from NSDL, CDSL, CAMS or KFintech, as a PDF." },
  { n: "02", t: "Upload it, or connect Gmail", d: "With Gmail connected, Nivesh looks for your latest CAS emails and imports the first one it can read." },
  { n: "03", t: "Unlock it", d: "Usually with your PAN. Some CAMS and KFintech statements use a password you chose." },
  { n: "04", t: "Holdings are replaced", d: "The holdings in the new statement replace what Nivesh had on file." },
];

interface ReadRow { what: string; why: string; access: string; tone: Tone }

const READS: ReadRow[] = [
  { what: "Holdings in your statement", why: "Portfolio value, allocation and risk analysis", access: "Read", tone: "mint" },
  { what: "Mutual fund transactions (NSDL CAS)", why: "Returns over time", access: "Read", tone: "mint" },
  { what: "Month-end values printed on the statement", why: "Your portfolio value trend", access: "Read", tone: "mint" },
  { what: "CAS emails in Gmail", why: "To find and download your latest statement", access: "Read-only", tone: "mint" },
  { what: "Holdings in a connected broker account", why: "Read from the broker each time you press Sync now", access: "Read", tone: "mint" },
];

/** True of today's backend only, so shown only against it (see BrokersScreen). */
const POSITIONS_NOT_READ: ReadRow = { what: "Open positions, funds and margins", why: "Not read yet from any broker account", access: "Not read", tone: "ink" };

const NEVER: ReadRow = { what: "Place, change or cancel orders", why: "Nivesh has no feature that does this, with any source", access: "Never", tone: "danger" };

const READ_COLUMNS: Column<ReadRow>[] = [
  { key: "what", header: "What", render: (r) => <span title={r.what} style={{ fontWeight: 500, color: "var(--cp-ink)" }}>{r.what}</span> },
  { key: "why", header: "Why", width: "minmax(0,1.5fr)", render: (r) => <span title={r.why}>{r.why}</span> },
  { key: "access", header: "Access", width: "96px", align: "right", render: (r) => <span style={{ fontFamily: "var(--mono)", fontSize: 11, textTransform: "uppercase", color: r.tone === "ink" ? "var(--cp-ink-3)" : TONE_COLOR[r.tone] }}>{r.access}</span> },
];

// ── import log ───────────────────────────────────────────────────────────

interface LogRow { id: string; ts: string; event: string; detail: string; failed: boolean }

const BROKER_EVENTS: Record<string, string> = {
  broker_connect: "Broker connect",
  broker_sync: "Broker sync",
  broker_disconnect: "Broker disconnect",
};

function logRows(imports: GmailImport[], audit: AuditRow[]): LogRow[] {
  const rows: LogRow[] = [];
  imports.forEach((m, i) => {
    if (!m.imported_at) return;
    const failed = !!m.status && m.status !== "completed";
    rows.push({
      id: `gmail-${m.message_id ?? i}-${m.imported_at}`,
      ts: m.imported_at,
      event: m.source === "gmail_auto" ? "Gmail automatic import" : "Gmail import",
      detail: [m.filename, m.count != null ? `${fmtNum(m.count)} holdings` : null, failed ? m.status : null].filter(Boolean).join(" · "),
      failed,
    });
  });
  for (const a of audit) {
    const label = BROKER_EVENTS[a.action];
    if (!label) continue;
    const failed = a.outcome !== "success";
    const d = a.details ?? {};
    rows.push({
      id: a.audit_id,
      ts: a.ts,
      event: failed ? `${label} failed` : label,
      detail: [
        typeof d.broker === "string" ? d.broker : null,
        typeof d.count === "number" ? `${fmtNum(d.count)} holdings` : null,
        failed && typeof d.reason === "string" ? d.reason : null,
      ].filter(Boolean).join(" · "),
      failed,
    });
  }
  return rows.sort((x, y) => new Date(y.ts).getTime() - new Date(x.ts).getTime());
}

const LOG_COLUMNS: Column<LogRow>[] = [
  { key: "when", header: "When", width: "92px", render: (r) => <span className="cp-mono-note" title={fmtDate(r.ts)}>{relTime(r.ts)}</span> },
  { key: "event", header: "Event", render: (r) => <span data-testid="import-log-event" style={{ color: r.failed ? "var(--cp-danger)" : "var(--cp-ink)" }}>{r.event}</span> },
  { key: "detail", header: "Detail", width: "minmax(0,1.4fr)", render: (r) => <span data-testid="import-log-detail" title={r.detail}>{r.detail || "—"}</span> },
];

function ImportLog() {
  const imports = useGmailImportHistory();
  const audit = useAuditTrail();

  if (imports.isPending || audit.isPending) {
    return <Section title="Import log"><LoadingBlock label="Loading the import log" rows={3} /></Section>;
  }
  const rows = logRows(imports.data ?? [], audit.data ?? []).slice(0, 12);
  const errors = (
    <>
      {imports.isError && <ErrorBlock title="Gmail imports didn’t load" error={imports.error} onRetry={() => imports.refetch()} />}
      {audit.isError && <ErrorBlock title="Broker events didn’t load" error={audit.error} onRetry={() => audit.refetch()} />}
    </>
  );
  const anyError = imports.isError || audit.isError;

  if (rows.length === 0) {
    return (
      <Section title="Import log">
        <div className="flex flex-col" style={{ gap: 10 }}>
          {errors}
          {!(imports.isError && audit.isError) && (
            <EmptyBlock title="Nothing logged yet" body="Gmail imports and broker events show up here once they happen. Uploaded PDFs are not logged by the server." />
          )}
        </div>
      </Section>
    );
  }
  return (
    <Section title="Import log" note="Gmail imports · broker events" flush>
      {anyError && <div className="flex flex-col" style={{ gap: 10, padding: 16 }}>{errors}</div>}
      <div data-testid="import-log">
        <DataTable columns={LOG_COLUMNS} rows={rows} rowKey={(r) => r.id} minWidth={420} />
      </div>
      <div style={{ padding: "10px 16px" }}>
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>Uploaded PDFs are not in this log: the server keeps no history of them.</span>
      </div>
    </Section>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

export default function BrokersScreen() {
  const accounts = useBrokerAccounts();
  const adapters = useBrokerAdapters();
  const state = useOnboardingState();
  const gmail = useGmailSourceStatus();
  // The planned broker backend says which brokers can be connected; today's does not.
  const connectable = !!adapters.data && saysConnectable(adapters.data);
  const reads = connectable ? [...READS, NEVER] : [...READS, POSITIONS_NOT_READ, NEVER];

  const connectedCount = accounts.data && state.data && gmail.state === "ready"
    ? accounts.data.length + (hasStatement(state.data) ? 1 : 0) + (gmail.data.connected ? 1 : 0)
    : null;

  return (
    <Screen testId="screen-page-brokers">
      <ScreenHeader
        eyebrow="Broker connections"
        pills={<Pill tone="mint">Read-only</Pill>}
        title={<>Where your holdings <em>come from</em>.</>}
        sub={connectable
          ? "Nivesh reads your holdings from a CAS statement that you upload or that it finds in your Gmail, and from a broker account you connect. Whatever the source, Nivesh only reads. It never places an order."
          : "Nivesh reads your holdings from a CAS statement that you upload, or that it finds in your Gmail. Signing in to a broker directly is not available yet. Whatever the source, Nivesh only reads. It never places an order."}
      />

      <BrokerReturnNotice />

      <div className="flex flex-col" style={{ gap: 10 }}>
        <Eyebrow>
          Your sources{connectedCount != null ? <> · <span data-testid="brokers-connected-count">{connectedCount}</span> connected</> : null}
        </Eyebrow>
        <BrokerAccounts q={accounts} />
        <StatementOnFile q={state} />
        <GmailSource />
      </div>

      <div className="flex flex-col" style={{ gap: 10 }}>
        <Eyebrow>Add or replace a statement</Eyebrow>
        <StatementUpload panOnFile={state.data?.pan_on_file ?? false} />
      </div>

      <div className="flex flex-col" style={{ gap: 10 }}>
        <Eyebrow>Connect a broker</Eyebrow>
        <BrokerConnect />
      </div>

      <div className="flex flex-col" style={{ gap: 14, padding: 18, borderRadius: 14, border: "1px solid var(--mint-line)", background: "var(--bg-1)" }}>
        <Eyebrow tone="mint">Importing a statement · 4 steps</Eyebrow>
        <ol className="m-0 grid p-0" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,200px),1fr))", gap: 10, listStyle: "none" }}>
          {IMPORT_STEPS.map((s) => (
            <li key={s.n} className="flex flex-col" style={{ gap: 6, padding: "12px 14px", borderRadius: 12, background: "var(--bg-2)" }}>
              <span aria-hidden style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--mint)" }}>{s.n}</span>
              <span style={{ fontSize: 14, fontWeight: 500 }}>{s.t}</span>
              <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{s.d}</span>
            </li>
          ))}
        </ol>
      </div>

      <Section title="What Nivesh reads, and why" flush>
        <DataTable columns={READ_COLUMNS} rows={reads} rowKey={(r) => r.what} minWidth={760} />
      </Section>

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: 12, alignItems: "start" }}>
        <ImportLog />
        <Section title="Security">
          <ul className="m-0 flex flex-col p-0" style={{ gap: 8, listStyle: "none", fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
            <li>Gmail access is read-only. Nivesh searches only for emails with a PDF attachment from NSDL, CDSL, CAMS or KFintech.</li>
            <li>Disconnecting Gmail here deletes the Google token Nivesh holds. You can also remove Nivesh from your Google account’s third-party access.</li>
            <li>Your PAN, or the statement password when it is different, is kept on your profile so later statements can be opened. Disconnecting Gmail does not remove it.</li>
            <li>A broker sign-in happens on the broker’s own site. Nivesh keeps the access it is given in encrypted form and deletes it when you disconnect the account.</li>
            <li>Each successful Gmail import is recorded with the file name and the number of holdings. You can see it in the import log.</li>
          </ul>
        </Section>
      </div>
    </Screen>
  );
}
