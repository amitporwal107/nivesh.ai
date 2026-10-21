/**
 * Product KPIs.
 * Design: frontend-v5/design/nivesh-copilot/NVOps.dc.html, page === 'kpis'.
 *
 * The design reports sixteen 30-day metrics in four groups. Most of them need
 * per-answer telemetry (timings, tool outcomes, evidence links, user
 * follow-through, model cost) that the backend does not record, so each group
 * keeps a NotConnected block naming what is still missing.
 *
 * A number is on this page only if an endpoint returns it:
 *   Platform    GET /api/admin/stats                  accounts, portfolios, holdings, invite list (all time)
 *               GET /api/admin/users                  sign-ins counted from the directory, on request
 *   Data        GET /api/admin/nidp/feeds/live        data sources healthy right now
 *               GET /api/admin/nidp/quality/summary   quality scores from the publish gate
 *               GET /api/admin/ocr-correction/stats   corrections to imported statements
 *               GET /api/data-health/summary          the app's nightly jobs
 *   Experience  GET /api/work/stats                   the issue tracker
 *   Decisions   GET /api/move-odds/diagnostics        entry setups vs baseline (a stored study)
 *               GET /api/positional/backtest/calibration  score band → hit rate
 *   Efficiency  GET /api/admin/ai/circuit             whether the insight writer calls a model
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  EmptyBlock, Eyebrow, Footnote, LoadingBlock, NotConnected, Screen, Tiles,
  fmtNum, fmtPct, relTime, type TileItem,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { LoadFailed, OpsHeader, OpsTabs } from "./internal/shared";
import { useAdminStats, useFeedsLive } from "./internal/use-internal-data";
import { AppJobs, DataQuality, EntrySetupStudy, PositionalCalibration, ReportedIssues, SignInCounts, StatementCorrections } from "./internal/ops-kpi-sections";
import { InsightWriterSwitch } from "./internal/ops-tools-sections";

function Group({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col" style={{ gap: 10 }}>
      <span className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 12px" }}>
        <Eyebrow>{title}</Eyebrow>
        {note && <span className="cp-mono-note">{note}</span>}
      </span>
      {children}
    </section>
  );
}

function PlatformUsage() {
  const stats = useAdminStats();
  if (stats.isPending) return <LoadingBlock label="Loading platform counts" rows={2} />;
  if (stats.isError) return <LoadFailed what="Platform counts" error={stats.error} onRetry={() => stats.refetch()} />;
  const { usage, whitelist } = stats.data;
  if (usage.total_users === 0 && whitelist.total === 0) {
    return (
      <div data-testid="kpi-platform-empty">
        <EmptyBlock title="No accounts yet" body="No one is on the invite list and no account has been created, so there is nothing to count." />
      </div>
    );
  }
  const items: TileItem[] = [
    { k: "Accounts", v: <span data-testid="kpi-users">{fmtNum(usage.total_users)}</span>, s: "User records, all time" },
    { k: "Portfolios", v: <span data-testid="kpi-portfolios">{fmtNum(usage.total_portfolios)}</span>, s: "Portfolio records" },
    { k: "Holdings", v: <span data-testid="kpi-holdings">{fmtNum(usage.total_holdings)}</span>, s: "Holding rows, all accounts" },
    {
      k: "Invite list",
      v: <span data-testid="kpi-whitelist-total">{fmtNum(whitelist.total)}</span>,
      s: <span data-testid="kpi-whitelist-split">{fmtNum(whitelist.active)} active · {fmtNum(whitelist.pending)} invited · {fmtNum(whitelist.blocked)} blocked</span>,
    },
    {
      k: "Invites activated",
      v: <span data-testid="kpi-conversion">{fmtPct(whitelist.conversion_rate)}</span>,
      s: "Active ÷ invite list",
      tone: whitelist.total > 0 ? "mint" : "ink",
    },
  ];
  return <Tiles items={items} min={170} />;
}

function FeedFreshness() {
  const { go } = useCopilotShell();
  const feeds = useFeedsLive();
  if (feeds.isPending) return <LoadingBlock label="Loading feed status" rows={2} />;
  if (feeds.isError) return <LoadFailed what="Feed status" error={feeds.error} onRetry={() => feeds.refetch()} />;
  const s = feeds.data.summary;
  if (s.total === 0) {
    return (
      <div data-testid="kpi-feeds-empty">
        <EmptyBlock
          title="No data sources to measure"
          body={feeds.data.db_error
            ? `The NIDP query service could not be read: ${feeds.data.db_error}`
            : "The NIDP source registry returned no ingesters."}
          action={<button type="button" className="cp-chip" onClick={() => go("ops/feeds")}>Open feed health ›</button>}
        />
      </div>
    );
  }
  const pct = (s.healthy / s.total) * 100;
  const checked = relTime(feeds.data.generated_at);
  const items: TileItem[] = [
    {
      k: "Sources healthy now",
      v: <span data-testid="kpi-feeds-healthy">{fmtNum(s.healthy)} of {fmtNum(s.total)}</span>,
      s: <span data-testid="kpi-feeds-healthy-pct">{fmtPct(pct)}{checked ? ` · checked ${checked}` : ""}</span>,
      tone: s.healthy === s.total ? "mint" : "ink",
    },
    { k: "Failing", v: <span data-testid="kpi-feeds-failing">{fmtNum(s.failing)}</span>, s: "Last run failed", tone: s.failing > 0 ? "danger" : "ink" },
    { k: "Stale", v: <span data-testid="kpi-feeds-stale">{fmtNum(s.stale)}</span>, s: "Missed the last trading day", tone: s.stale > 0 ? "amber" : "ink" },
  ];
  return (
    <>
      <Tiles items={items} min={170} />
      <button type="button" className="cp-chip" style={{ alignSelf: "flex-start" }} onClick={() => go("ops/feeds")}>Open feed health ›</button>
    </>
  );
}

export default function OpsKpisScreen() {
  const { go } = useCopilotShell();
  return (
    <Screen testId="screen-ops-kpis">
      <OpsHeader
        title="Product KPIs"
        sub="What the product measures today. Every number here is returned by an endpoint; where one is counted on this page from a list, it says so. Most of the planned KPIs need a record of each answer — how long it took, which tools ran, what it cost, whether the user acted on it — and nothing records that yet, so those are listed as missing instead of shown as numbers."
      />
      <OpsTabs current="ops/kpis" />

      <Group title="Platform" note="All time · not a 30-day window">
        <PlatformUsage />
        <SignInCounts />
        <Link to="/admin" className="cp-link" style={{ fontSize: 13, alignSelf: "flex-start" }}>Users and the invite list are managed in the admin console ›</Link>
      </Group>

      <Group title="Data and intelligence" note="Right now · newest run">
        <FeedFreshness />
        <DataQuality />
        <StatementCorrections />
        <AppJobs />
        <NotConnected
          testId="kpi-data-not-connected"
          title="Reconciliation accuracy, evidence and tool success are not measured"
          body="The figures above are live counts and one-day scores. None of them is the 30-day rate the design asks for, and nothing compares imported holdings with the source statement or links an answer’s claims to its evidence."
          needs={[
            "Portfolio reconciliation accuracy — a stored comparison of imported holdings against the source statement, per import",
            "Claims with traceable evidence — each answer recorded with its claims and the evidence linked to them",
            "Tool success rate and p95 latency — duration and outcome recorded for every tool call",
            "Feed freshness within SLA — a per-source freshness target and a daily history of whether it was met (the quality gate scores one day at a time)",
          ]}
        />
      </Group>

      <Group title="User experience">
        <ReportedIssues />
        <NotConnected
          testId="kpi-ux-not-connected"
          title="Chat volume, answer speed and task completion are not measured"
          body="Chats are stored per account, but no endpoint counts them across accounts, and no timing is kept for an answer."
          needs={[
            "Chat volume — questions and conversations per day across all accounts (chat_sessions and chat_messages hold the rows; no admin route counts them)",
            "Time to first useful answer — a timestamp for each question and for the first answer content shown",
            "Answered without manual tool choice — whether the user picked a tool or agent before asking",
            "Task completion — a definition of the key workflows and an event when each one finishes",
            "Saved-workspace use — weekly active users and how many of them open a saved item",
          ]}
        />
      </Group>

      <Group title="Decision quality">
        <EntrySetupStudy />
        <PositionalCalibration />
        <NotConnected
          testId="kpi-decision-not-connected"
          title="Follow-through, outcomes and calibration of Copilot insights are not measured"
          body="The two blocks above are research results for the Move odds and positional models. Nothing yet measures what users did with a Copilot insight, or whether its stated confidence held."
          needs={[
            "Insights taken forward — an aggregate of what users did with each insight (thumbs up/down is stored per message in copilot_feedback, but no endpoint reads it back)",
            "Paper outcomes, net of cost — one roll-up across strategies with the trade count (an evaluation exists per Move odds paper portfolio and is shown on the Paper trades page)",
            "Signals beating baseline, live — out-of-sample results per signal as they accrue, not a one-off study",
            "Calibration — stated confidence stored with each insight and compared with what happened",
          ]}
          action={<button type="button" className="cp-chip" onClick={() => go("page/paper")}>Open paper trades ›</button>}
        />
      </Group>

      <Group title="Efficiency">
        <InsightWriterSwitch />
        <NotConnected
          testId="kpi-efficiency-not-connected"
          title="Cost, caching and tool calls per task are not measured"
          body="Model calls are made without recording their tokens or price, so there is no cost figure to show. The switch above is the only model-usage fact the backend reports."
          needs={[
            "AI cost per completed task — token usage and price recorded for each model call",
            "Cache hit rate — hit and miss counters on the caches (the datastore status reports how many keys are cached, not how often they are used)",
            "Tool calls per task — the tool calls recorded against each answer",
            "Resolved without model escalation — which model answered, and whether a larger one was needed",
          ]}
        />
      </Group>

      <Footnote>Nothing on this page is estimated · figures counted here from a list say what the list covers</Footnote>
    </Screen>
  );
}
