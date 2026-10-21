/**
 * Audit log — the two admin lists that exist beside the per-account trail:
 * the newest sign-in of every account (the user directory) and the log of
 * fund-data refreshes. Neither is the platform-wide audit trail; each says
 * what it covers. Both count against the admin request budget, so each is
 * read when its tab is opened.
 */
import { DataTable, Footnote, Pill, Section, fmtDate, fmtNum, relTime, type Column } from "../../components/ui";
import { FundName } from "../../components/EntityIcon";
import { QueryBlock, StatusPill, asUtc, fmtDuration, stamp } from "./shared";
import { ADMIN_USERS_CAP, useAdminUsers, useFundRefreshLog, type AdminUser, type FundRefresh } from "./ops-platform-data";

// ── newest sign-in per account ───────────────────────────────────────────

const twoLine = { display: "flex", flexDirection: "column", gap: 1, minWidth: 0 } as const;
const clip = { overflow: "hidden", textOverflow: "ellipsis" } as const;

const SIGNIN_COLUMNS: Column<AdminUser>[] = [
  {
    key: "account", header: "Account", width: "minmax(200px,2fr)",
    render: (u) => (
      <span data-testid="audit-signin-row" data-user={u.user_id} style={twoLine}>
        <span style={{ ...clip, color: "var(--cp-ink)" }} title={u.name ?? undefined}>{u.name || u.email || u.user_id}</span>
        {u.name && u.email && <span style={{ ...clip, fontSize: 12, color: "var(--cp-ink-3)" }} title={u.email}>{u.email}</span>}
      </span>
    ),
  },
  { key: "role", header: "Role", width: "80px", render: (u) => (u.is_admin ? <Pill tone="danger">Admin</Pill> : <span style={{ color: "var(--cp-ink-3)" }}>User</span>) },
  {
    key: "last", header: "Newest sign-in", width: "170px",
    render: (u) => (
      // Session times come from Mongo, which keeps UTC; some are written without a zone suffix.
      <span data-testid="audit-signin-last" title={asUtc(u.last_login_at) ?? undefined} style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
        {u.last_login_at ? stamp(asUtc(u.last_login_at), { year: true }) : "Never signed in"}
      </span>
    ),
  },
  {
    key: "session", header: "That session", width: "110px",
    render: (u) => (
      <span data-testid="audit-signin-session">
        {u.session_active ? <Pill tone="mint">Still valid</Pill> : <span style={{ color: "var(--cp-ink-3)" }}>{u.last_login_at ? "Expired" : "—"}</span>}
      </span>
    ),
  },
  { key: "holdings", header: "Holdings", width: "90px", align: "right", num: true, render: (u) => fmtNum(u.holdings_count) },
  { key: "created", header: "Account created", width: "130px", render: (u) => (u.created_at ? fmtDate(asUtc(u.created_at)) : "—") },
];

/** Newest sign-in first; accounts that never signed in last. */
function bySignIn(a: AdminUser, b: AdminUser): number {
  return (b.last_login_at ?? "").localeCompare(a.last_login_at ?? "");
}

export function SignInsByAccount() {
  const users = useAdminUsers();
  return (
    <div data-testid="audit-signins" className="flex flex-col" style={{ gap: 10 }}>
      <QueryBlock
        query={users}
        what="The account list"
        rows={4}
        isEmpty={(rows) => rows.length === 0}
        empty={{ title: "No accounts exist", body: "The user directory is empty, so there is no sign-in to list." }}
        emptyTestId="audit-signins-empty"
      >
        {(rows) => {
          const live = rows.filter((u) => u.session_active).length;
          return (
            <>
              <Section
                flush
                title={<>Newest sign-in per account · <span data-testid="audit-signin-count">{rows.length}</span> {rows.length === 1 ? "account" : "accounts"}</>}
                note={<><span data-testid="audit-signin-live">{live}</span> with a session that is still valid</>}
              >
                <DataTable columns={SIGNIN_COLUMNS} rows={[...rows].sort(bySignIn)} rowKey={(u) => u.user_id} minWidth={800} />
              </Section>
              <Footnote>
                One row per account, from the user directory: the newest session only, not every sign-in · a valid session has not expired, which is not the same as being online
                {rows.length >= ADMIN_USERS_CAP ? ` · the directory returns at most ${ADMIN_USERS_CAP} accounts, so this list is cut short` : ""}
              </Footnote>
            </>
          );
        }}
      </QueryBlock>
    </div>
  );
}

// ── fund-data refresh log ────────────────────────────────────────────────

const REFRESH_SOURCE: Record<string, string> = { fresh: "Fetched now", cache: "From cache", "stale-cache": "From an old cache" };

const REFRESH_COLUMNS: Column<FundRefresh>[] = [
  {
    key: "fund", header: "Fund", width: "minmax(240px,2.2fr)",
    render: (r) => (r.instrument_name
      ? <FundName name={r.instrument_name} size={24} testId="audit-fund-row" />
      : <span data-testid="audit-fund-row" style={{ color: "var(--cp-ink-3)" }}>Not named in the log</span>),
  },
  {
    key: "when", header: "When", width: "130px",
    render: (r) => <span data-testid="audit-fund-time" title={asUtc(r.created_at) ?? undefined} style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{stamp(asUtc(r.created_at))}</span>,
  },
  { key: "status", header: "Result", width: "90px", render: (r) => <span data-testid="audit-fund-status"><StatusPill status={r.status} /></span> },
  { key: "holdings", header: "Holdings read", width: "110px", align: "right", num: true, render: (r) => fmtNum(r.holdings_count) },
  { key: "source", header: "Source", width: "130px", render: (r) => (r.source ? REFRESH_SOURCE[r.source] ?? r.source : "—") },
  { key: "took", header: "Took", width: "80px", align: "right", num: true, render: (r) => fmtDuration(r.duration_ms) },
  {
    key: "issues", header: "Problems found", width: "minmax(0,1.6fr)",
    render: (r) => (r.validation_issues
      ? <span title={r.validation_issues} style={{ color: "var(--amber)" }}>{r.validation_issues}</span>
      : <span style={{ color: "var(--cp-ink-4)" }}>—</span>),
  },
];

export function FundRefreshLog() {
  const log = useFundRefreshLog(100);
  return (
    <div data-testid="audit-fund-log" className="flex flex-col" style={{ gap: 10 }}>
      <QueryBlock
        query={log}
        what="The fund-data refresh log"
        rows={4}
        isEmpty={(rows) => rows.length === 0}
        empty={{ title: "No fund-data refresh is on record", body: "Nothing has been written to the refresh log. A row appears each time a fund’s holdings are fetched from the source site." }}
        emptyTestId="audit-fund-empty"
      >
        {(rows) => {
          const failed = rows.filter((r) => r.status === "failed").length;
          const partial = rows.filter((r) => r.status === "partial").length;
          return (
            <>
              <Section
                flush
                title={<>Fund-data refreshes · <span data-testid="audit-fund-count">{rows.length}</span> most recent</>}
                note={<><span data-testid="audit-fund-failed">{failed}</span> failed · <span data-testid="audit-fund-partial">{partial}</span> partial · of the rows shown · newest first</>}
              >
                <DataTable columns={REFRESH_COLUMNS} rows={rows} rowKey={(r) => r.id} minWidth={980} />
              </Section>
              <Footnote>Each row is one fetch of a fund’s holdings by the server, not an action by a person · times are shown in your time zone · the list holds at most the last 100 refreshes{rows[rows.length - 1]?.created_at ? `, back to ${relTime(asUtc(rows[rows.length - 1].created_at))}` : ""}</Footnote>
            </>
          );
        }}
      </QueryBlock>
    </div>
  );
}
