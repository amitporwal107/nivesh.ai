/**
 * Product KPIs — the blocks that have a number an endpoint returns.
 *
 * Rule for this file: a figure is shown only when an endpoint returns it. The
 * few figures that are counted on the page from a list (sign-ins from the user
 * directory, the latest quality row per data set) say so next to the number,
 * with what the list covers.
 */
import { useState } from "react";
import { DataTable, Footnote, Pill, Section, Tiles, fmtDate, fmtNum, fmtPct, humaniseTag, relTime, type Column, type TileItem, type Tone } from "../../components/ui";
import { QueryBlock, StatusPill, asUtc } from "./shared";
import { useQualitySummary, type QualityScore } from "./ops-nidp-data";
import {
  ADMIN_USERS_CAP, useAdminUsers, useDataHealth, useEntrySetupResearch, useOcrStats, usePositionalCalibration, useWorkStats,
  type AdminUser, type CalibrationBucket, type SetupResearch,
} from "./ops-platform-data";

const DAY_MS = 86_400_000;

// ── platform: sign-ins counted from the user directory ───────────────────

function signedInWithin(users: AdminUser[], days: number, now: number): number {
  return users.filter((u) => {
    const t = u.last_login_at ? Date.parse(asUtc(u.last_login_at) ?? "") : NaN;
    return Number.isFinite(t) && now - t <= days * DAY_MS;
  }).length;
}

/**
 * No endpoint reports active users. The user directory does return every
 * account's newest sign-in, so the counts below are made here from that list —
 * on request, because the directory is a slow admin call.
 */
export function SignInCounts() {
  const [asked, setAsked] = useState(false);
  const users = useAdminUsers(asked);
  // Already loaded on the Audit page: show it without asking again.
  if (!asked && !users.data) {
    return (
      <div data-testid="kpi-signins-ask" className="cp-card flex flex-wrap items-center" style={{ gap: "8px 14px", padding: "14px 16px" }}>
        <span style={{ flex: "1 1 280px", fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          Active users are not reported by any endpoint. This page can count recent sign-ins from the user directory, which keeps the newest sign-in of each account.
        </span>
        <button type="button" className="cp-chip" data-testid="kpi-signins-load" onClick={() => setAsked(true)}>Count sign-ins ›</button>
      </div>
    );
  }
  return (
    <QueryBlock
      query={users}
      what="The account list"
      rows={2}
      isEmpty={(rows) => rows.length === 0}
      empty={{ title: "No accounts to count", body: "The user directory is empty." }}
      emptyTestId="kpi-signins-empty"
    >
      {(rows) => {
        const now = Date.now();
        const of = `of ${fmtNum(rows.length)} ${rows.length === 1 ? "account" : "accounts"}`;
        const items: TileItem[] = [
          { k: "Signed in · last 7 days", v: <span data-testid="kpi-signed-in-7d">{fmtNum(signedInWithin(rows, 7, now))}</span>, s: of },
          { k: "Signed in · last 30 days", v: <span data-testid="kpi-signed-in-30d">{fmtNum(signedInWithin(rows, 30, now))}</span>, s: of },
          { k: "Session still valid", v: <span data-testid="kpi-sessions-valid">{fmtNum(rows.filter((u) => u.session_active).length)}</span>, s: "Newest session not expired" },
          { k: "Never signed in", v: <span data-testid="kpi-never-signed-in">{fmtNum(rows.filter((u) => !u.last_login_at).length)}</span>, s: "No session on record" },
        ];
        return (
          <>
            <Tiles items={items} min={170} />
            <Footnote>
              Counted on this page from the user directory, by each account’s newest stored session · not daily or monthly active users
              {rows.length >= ADMIN_USERS_CAP ? ` · the directory returns at most ${ADMIN_USERS_CAP} accounts, so these counts are a floor` : ""}
            </Footnote>
          </>
        );
      }}
    </QueryBlock>
  );
}

// ── data: quality scores from the publish gate ───────────────────────────

const DOMAIN: Record<string, string> = { equity: "Equity", mf: "Mutual funds" };

/** The newest scored day of each data set. */
function latestPerDomain(rows: QualityScore[]): QualityScore[] {
  const by = new Map<string, QualityScore>();
  for (const r of rows) {
    const cur = by.get(r.domain);
    if (!cur || r.target_date > cur.target_date) by.set(r.domain, r);
  }
  return [...by.values()].sort((a, b) => a.domain.localeCompare(b.domain));
}

const score = (n: number | null | undefined) => fmtNum(n, 1);

const QUALITY_COLUMNS: Column<QualityScore>[] = [
  {
    key: "domain", header: "Data set · data for", width: "minmax(130px,1.2fr)",
    render: (q) => (
      <span style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
        <span data-testid="kpi-quality-row" data-domain={q.domain} style={{ color: "var(--cp-ink)" }}>{DOMAIN[q.domain] ?? humaniseTag(q.domain)}</span>
        <span data-testid="kpi-quality-date" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{fmtDate(q.target_date)}</span>
      </span>
    ),
  },
  { key: "overall", header: "Overall", width: "64px", align: "right", num: true, render: (q) => <span data-testid="kpi-quality-overall" style={{ color: "var(--cp-ink)" }}>{score(q.overall_score)}</span> },
  { key: "accuracy", header: "Accuracy", width: "72px", align: "right", num: true, render: (q) => score(q.accuracy) },
  { key: "consistency", header: "Consistency", width: "88px", align: "right", num: true, render: (q) => score(q.consistency) },
  { key: "completeness", header: "Complete", width: "72px", align: "right", num: true, render: (q) => score(q.completeness) },
  { key: "freshness", header: "Freshness", width: "76px", align: "right", num: true, render: (q) => <span data-testid="kpi-quality-freshness">{score(q.freshness)}</span> },
  { key: "audit", header: "Auditable", width: "76px", align: "right", num: true, render: (q) => score(q.auditability) },
  { key: "grade", header: "Grade", width: "82px", render: (q) => <StatusPill status={q.certification} /> },
  { key: "publish", header: "Publish decision", width: "120px", align: "right", render: (q) => <span data-testid="kpi-quality-decision"><StatusPill status={q.publish_decision} /></span> },
];

export function DataQuality() {
  const quality = useQualitySummary();
  return (
    <QueryBlock
      query={quality}
      what="The data-quality scores"
      rows={2}
      isEmpty={(d) => d.quality.length === 0}
      empty={{ title: "No day has been scored yet", body: "The data platform’s quality gate has not scored any day, so there is no quality figure to report." }}
      emptyTestId="kpi-quality-empty"
    >
      {(d) => {
        const rows = latestPerDomain(d.quality);
        const held = d.exceptions?.length ?? 0;
        return (
          <>
            <Section
              flush
              title="Data quality · newest scored day per data set"
              note={<><span data-testid="kpi-quality-held">{held}</span> {held === 1 ? "day" : "days"} held for review</>}
            >
              <DataTable columns={QUALITY_COLUMNS} rows={rows} rowKey={(q) => q.domain} minWidth={900} />
            </Section>
            <Footnote>Scores are 0–100, computed by the data platform’s publish gate after each day’s load · freshness here is that gate’s score for one day, not a 30-day within-SLA rate</Footnote>
          </>
        );
      }}
    </QueryBlock>
  );
}

// ── data: statement-reading corrections ──────────────────────────────────

export function StatementCorrections() {
  const stats = useOcrStats();
  return (
    <QueryBlock query={stats} what="Statement corrections" rows={2}>
      {(s) => {
        const items: TileItem[] = [
          { k: "Statement corrections", v: <span data-testid="kpi-ocr-total">{fmtNum(s.total_corrections)}</span>, s: "Holdings fixed after import, all time" },
          { k: "ISIN fixes", v: <span data-testid="kpi-ocr-isin">{fmtNum(s.isin_corrections)}</span>, s: "Wrong security matched" },
          { k: "Name fixes", v: <span data-testid="kpi-ocr-name">{fmtNum(s.name_corrections)}</span>, s: "Name misread" },
          { k: "Applied automatically", v: <span data-testid="kpi-ocr-auto">{fmtNum(s.auto_applied)}</span>, s: `${fmtNum(s.patterns_learned)} patterns learned` },
        ];
        return (
          <>
            <Tiles items={items} min={170} />
            <Footnote>Corrections made to holdings read from uploaded statements · a count of fixes, not a reconciliation accuracy rate</Footnote>
          </>
        );
      }}
    </QueryBlock>
  );
}

// ── data: the app's own nightly jobs ─────────────────────────────────────

const HEALTH: Record<string, { label: string; tone: Tone }> = {
  ok: { label: "All clear", tone: "mint" },
  warn: { label: "Warning", tone: "amber" },
  error: { label: "Error", tone: "danger" },
};

export function AppJobs() {
  const health = useDataHealth();
  return (
    <QueryBlock query={health} what="The app’s job status" rows={1}>
      {(h) => {
        const state = HEALTH[h.status] ?? { label: h.status, tone: "ink" as Tone };
        const checked = relTime(h.checked_at);
        return (
          <div data-testid="kpi-app-jobs" className="cp-card flex flex-col" style={{ gap: 10, padding: "14px 16px" }}>
            <div className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
              <span className="cp-eyebrow">App jobs</span>
              <span data-testid="kpi-app-jobs-status"><Pill tone={state.tone}>{state.label}</Pill></span>
              <span style={{ flex: "1 1 220px", fontSize: 13, color: "var(--cp-ink-2)" }}>
                <span data-testid="kpi-app-jobs-issues">{h.issues.length}</span> {h.issues.length === 1 ? "problem" : "problems"} reported by the nightly price, fund-score and rating jobs and the upload scanner{checked ? ` · checked ${checked}` : ""}
              </span>
            </div>
            {h.issues.map((i, n) => (
              <div key={`${i.job ?? ""}-${n}`} data-testid="kpi-app-jobs-issue" className="flex flex-wrap items-baseline" style={{ gap: "4px 12px", fontSize: 13, lineHeight: 1.5 }}>
                <span style={{ color: "var(--cp-ink)" }}>{i.label || i.job || "Job"}</span>
                <StatusPill status={i.severity} />
                <span style={{ flex: "1 1 220px", color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{i.message || "No detail given."}</span>
              </div>
            ))}
          </div>
        );
      }}
    </QueryBlock>
  );
}

// ── user experience: the issue tracker ───────────────────────────────────

export function ReportedIssues() {
  const stats = useWorkStats();
  return (
    <QueryBlock
      query={stats}
      what="The issue counts"
      rows={2}
      isEmpty={(s) => s.total === 0}
      empty={{ title: "No issues on record", body: "The issue tracker is empty: nothing has been filed by staff or by the app’s error intake." }}
      emptyTestId="kpi-issues-empty"
    >
      {(s) => {
        const st = (k: string) => s.by_status[k] ?? 0;
        const pr = (k: string) => s.by_priority[k] ?? 0;
        const items: TileItem[] = [
          { k: "Issues on record", v: <span data-testid="kpi-issues-total">{fmtNum(s.total)}</span>, s: <span data-testid="kpi-issues-priority">P1 {fmtNum(pr("P1"))} · P2 {fmtNum(pr("P2"))} · P3 {fmtNum(pr("P3"))}</span> },
          { k: "Open", v: <span data-testid="kpi-issues-open">{fmtNum(st("open"))}</span>, s: "Not started", tone: st("open") > 0 ? "amber" : "ink" },
          { k: "In progress", v: <span data-testid="kpi-issues-in-progress">{fmtNum(st("in_progress"))}</span>, s: `${fmtNum(st("in_review"))} in review · ${fmtNum(st("testing_qa"))} in QA` },
          { k: "Resolved", v: <span data-testid="kpi-issues-resolved">{fmtNum(st("resolved"))}</span>, s: `${fmtNum(st("wont_fix"))} closed as won’t fix`, tone: st("resolved") > 0 ? "mint" : "ink" },
        ];
        return (
          <>
            <Tiles items={items} min={170} />
            <Footnote>The internal issue tracker, all time: issues filed by staff and by the app’s error intake · a workload count, not a measure of how users experience answers</Footnote>
          </>
        );
      }}
    </QueryBlock>
  );
}

// ── decision quality: the entry-setup study ──────────────────────────────

interface SetupRow { key: string; setup: string; label: string; target: string; trades: number; net: number | null; baseline: number | null; validation: string | null }

function setupRows(d: SetupResearch): SetupRow[] {
  return d.setups.flatMap((s) => s.trades.map((t) => ({
    key: `${s.id}-${t.trade}`,
    setup: s.name,
    label: s.status_label ?? "",
    target: t.trade,
    trades: t.trades,
    net: t.mean_net ?? null,
    baseline: t.baseline_mean_net ?? null,
    validation: t.validation ?? null,
  })));
}

/** A per-trade result held as a fraction (−0.0065) shown in percent (−0.65%). */
const perTrade = (f: number | null) => fmtPct(f == null ? null : f * 100, { signed: true, digits: 2 });

const SETUP_COLUMNS: Column<SetupRow>[] = [
  { key: "setup", header: "Entry setup", width: "minmax(150px,1.5fr)", render: (r) => <span data-testid="kpi-setup-row" style={{ color: "var(--cp-ink)" }} title={r.label || undefined}>{r.setup}</span> },
  { key: "target", header: "Profit target", width: "100px", align: "right", num: true, render: (r) => r.target },
  { key: "trades", header: "Trades", width: "80px", align: "right", num: true, render: (r) => fmtNum(r.trades) },
  { key: "net", header: "Avg per trade", width: "110px", align: "right", num: true, render: (r) => <span data-testid="kpi-setup-net" style={{ color: r.net != null && r.net > 0 ? "var(--mint)" : r.net != null && r.net < 0 ? "var(--cp-danger)" : undefined }}>{perTrade(r.net)}</span> },
  { key: "baseline", header: "Baseline", width: "100px", align: "right", num: true, render: (r) => perTrade(r.baseline) },
  { key: "result", header: "Validated", width: "100px", align: "right", render: (r) => <span data-testid="kpi-setup-result"><StatusPill status={r.validation} /></span> },
];

export function EntrySetupStudy() {
  const study = useEntrySetupResearch();
  return (
    <QueryBlock
      query={study}
      what="The entry-setup study"
      rows={3}
      forbidden="This study belongs to the Move odds feature, which is switched on for an allow-list of accounts, and this account is not on it (403)."
    >
      {(d) => {
        const s = d.study;
        const cost = s.cost_round_trip != null ? fmtPct(s.cost_round_trip * 100, { digits: 2 }) : null;
        const period = s.first_signal_day && s.last_signal_day ? `${fmtDate(s.first_signal_day)} – ${fmtDate(s.last_signal_day)}` : null;
        const tile: TileItem[] = [{
          k: "Entry setups that beat the baseline",
          v: <span data-testid="kpi-setups-validated">{fmtNum(s.validated)} of {fmtNum(s.tested)}</span>,
          s: "Setup and profit-target pairs tested, after costs",
          tone: s.validated > 0 ? "mint" : "ink",
        }];
        return (
          <>
            <Tiles items={tile} min={220} />
            <Section
              flush
              title="Entry-setup study · result per setup"
              note={[period, cost ? `after ${cost} round-trip cost` : null, d.decided ? `decided ${fmtDate(d.decided)}` : null].filter(Boolean).join(" · ")}
            >
              <DataTable columns={SETUP_COLUMNS} rows={setupRows(d)} rowKey={(r) => r.key} minWidth={700} empty="The study lists no setups." />
            </Section>
            <Footnote>
              A stored research result behind the Move odds page, not a live measurement of Copilot insights
              {s.baseline ? ` · baseline: ${s.baseline}` : ""}
              {s.rule ? ` · ${s.rule}` : ""}
            </Footnote>
          </>
        );
      }}
    </QueryBlock>
  );
}

// ── decision quality: positional score calibration ───────────────────────

const band = (b: CalibrationBucket) => `${fmtNum(b.bucket_lo, 2)} – ${fmtNum(b.bucket_hi, 2)}`;

const CALIBRATION_COLUMNS: Column<CalibrationBucket>[] = [
  { key: "metric", header: "Score", width: "minmax(0,1.4fr)", render: (b) => <span data-testid="kpi-calibration-row">{humaniseTag(b.metric) || "—"}</span> },
  { key: "band", header: "Score band", width: "120px", align: "right", num: true, render: band },
  { key: "horizon", header: "Days ahead", width: "100px", align: "right", num: true, render: (b) => fmtNum(b.horizon_days) },
  { key: "samples", header: "Cases", width: "90px", align: "right", num: true, render: (b) => fmtNum(b.sample_count) },
  { key: "moves", header: "Moved", width: "90px", align: "right", num: true, render: (b) => fmtNum(b.moves_count) },
  { key: "rate", header: "Hit rate", width: "90px", align: "right", num: true, render: (b) => <span data-testid="kpi-calibration-rate">{fmtPct(b.probability == null ? null : b.probability * 100)}</span> },
];

export function PositionalCalibration() {
  const cal = usePositionalCalibration();
  return (
    <QueryBlock query={cal} what="The calibration table" rows={2}>
      {(d) => (
        d.buckets.length === 0 ? (
          <div data-testid="kpi-calibration-empty" className="cp-card flex flex-col" style={{ gap: 6, padding: "14px 16px" }}>
            <span className="cp-eyebrow">Positional score calibration</span>
            <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 620, overflowWrap: "anywhere" }}>
              {d._reason
                ? `The calibration table could not be read: ${d._reason}`
                : "The table that compares the positional engine’s scores with what followed is empty. An admin job fills it once enough past picks have a known outcome; until then there is no hit rate to show."}
            </span>
          </div>
        ) : (
          <>
            <Section flush title={<>Positional score calibration · <span data-testid="kpi-calibration-count">{d.buckets.length}</span> bands</>} note="Score band → how often the move followed">
              <DataTable columns={CALIBRATION_COLUMNS} rows={d.buckets} rowKey={(b, i) => `${b.metric ?? ""}-${b.horizon_days ?? ""}-${b.bucket_lo ?? ""}-${i}`} minWidth={680} />
            </Section>
            <Footnote>Covers the positional engine’s own scores only · not the confidence stated in Copilot answers</Footnote>
          </>
        )
      )}
    </QueryBlock>
  );
}
