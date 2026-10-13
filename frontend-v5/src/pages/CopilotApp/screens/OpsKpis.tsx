/**
 * Product KPIs.
 * Design: frontend-v5/design/nivesh-copilot/NVOps.dc.html, page === 'kpis'.
 *
 * The design reports sixteen 30-day metrics in four groups. Almost all of them
 * need per-answer telemetry (timings, tool outcomes, evidence links, user
 * follow-through, model cost) that no endpoint reports, so those groups are
 * NotConnected blocks that name what each metric needs.
 *
 * What is measured today and shown as numbers:
 *   GET /api/admin/stats            accounts, portfolios, holdings, invite list (all time)
 *   GET /api/admin/nidp/feeds/live  how many data sources are healthy right now
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
  return (
    <Screen testId="screen-ops-kpis">
      <OpsHeader
        title="Product KPIs"
        sub="What the product measures today. Most of the planned KPIs need a record of each answer — how long it took, which tools ran, whether the user acted on it — and no endpoint reports that yet. Those groups list what is missing instead of showing numbers."
      />
      <OpsTabs current="ops/kpis" />

      <Group title="Platform" note="All time · not a 30-day window">
        <PlatformUsage />
        <Link to="/admin" className="cp-link" style={{ fontSize: 13, alignSelf: "flex-start" }}>Users and the invite list are managed in the admin console ›</Link>
      </Group>

      <Group title="Data and intelligence" note="Right now">
        <FeedFreshness />
        <NotConnected
          testId="kpi-data-not-connected"
          title="Reconciliation, evidence and tool success are not measured"
          body="The one figure above is a live count, not the 30-day freshness-within-SLA rate in the design."
          needs={[
            "Portfolio reconciliation accuracy — a stored comparison of imported holdings against the source statement",
            "Claims with traceable evidence — each answer recorded with its claims and the evidence linked to them",
            "Tool success rate and p95 latency — duration and outcome recorded for every tool call",
            "Feed freshness within SLA — a per-source freshness target and a daily history of whether it was met",
          ]}
        />
      </Group>

      <Group title="User experience">
        <NotConnected
          testId="kpi-ux-not-connected"
          title="Answer speed and task completion are not measured"
          needs={[
            "Time to first useful answer — a timestamp for each question and for the first answer content shown",
            "Answered without manual tool choice — whether the user picked a tool or agent before asking",
            "Task completion — a definition of the key workflows and an event when each one finishes",
            "Saved-workspace use — weekly active users and how many of them open a saved item",
          ]}
        />
      </Group>

      <Group title="Decision quality">
        <NotConnected
          testId="kpi-decision-not-connected"
          title="Follow-through, outcomes and calibration are not measured"
          body="The design reports how often insights are taken forward only next to their outcomes and calibration, so none of the three is shown until all can be."
          needs={[
            "Insights taken forward — an aggregate of what users did with each insight (thumbs up/down is stored per message, but no endpoint reads it back)",
            "Signals beating baseline — out-of-sample results per signal, after costs, against a stated baseline",
            "Paper outcomes, net of cost — a roll-up of paper trades across strategies, with the trade count",
            "Calibration — stated confidence stored with each insight and compared with what happened",
          ]}
        />
      </Group>

      <Group title="Efficiency">
        <NotConnected
          testId="kpi-efficiency-not-connected"
          title="Cost, caching and tool calls per task are not measured"
          needs={[
            "AI cost per completed task — token usage and price recorded for each answer",
            "Cache hit rate — a counter for repeated calculations served from cache",
            "Tool calls per task — the tool calls recorded against each answer",
            "Resolved without model escalation — which model answered, and whether a larger one was needed",
          ]}
        />
      </Group>

      <Footnote>Numbers on this page come from the admin statistics and feed status endpoints · nothing is estimated</Footnote>
    </Screen>
  );
}
