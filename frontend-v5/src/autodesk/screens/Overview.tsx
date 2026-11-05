/**
 * 01 · Desk overview — built to docs/autodesk/design/prototype/TDOverview.dc.html: headline + sub line, "Needs you ·
 * ranked by ₹ at risk", metric tiles, the P&L card + "Broker & data feeds", "Agents · current task" and "Recent agent
 * activity" (table on desktop, cards on a phone).
 *
 * Phase 1 truth: agents scan, draft plans, assess risk and approvals happen; there are no orders, fills, positions or
 * P&L. Blocks that need those keep their place and say "Phase 2" — the prototype's sample figures are never shown, and
 * every sentence of the headline is computed from the API.
 */
import { useNavigate } from "react-router-dom";
import { isUnauthorized } from "../api";
import { agentName, dateLong, dateShort, rsShort, todayIST } from "../format";
import { stopEntriesOf, useDeskStatus, useIndexQuotes, useIsMobile, useNow, usePendingApprovals, type IndexQuotes } from "../hooks";
import { screenById, screenNo, type ScreenId } from "../nav";
import type { ApprovalRow, DeskStatus } from "../types";
import { ErrorBox, Loading, Pill, ScreenHeader, Tile, TileGrid, type Tone } from "../ui";
import { agentCounts, countWord, firstExpiry, MODE_WORD, premarketOf, uniqueAgents, useAgentActivities, whenIST } from "./overview/data";
import { Activity, AgentsNow, FeedsCard, NeedsYou, PnlCard } from "./overview/sections";

const MODE_TONE: Record<string, Tone> = { AUTONOMOUS_PAPER: "mint", ASSISTED: "indigo", RESEARCH: "ink" };
const PM_TONE: Record<string, Tone> = { READY: "mint", DEGRADED: "amber", BLOCKED: "danger" };

function deskAccounts(st: DeskStatus | undefined) {
  return (st?.accounts ?? []).filter((a) => a.kind !== "SIMULATION");
}

/** First sentence of the headline: entries on hold, no account, or agent health — whichever is true. */
function leadSentence(st: DeskStatus | undefined): string {
  if (!st) return "";
  if (stopEntriesOf(st)) return "New plans are on hold.";
  if (deskAccounts(st).length === 0) return "No desk account yet.";
  const c = agentCounts(st);
  if (c.total === 0) return "No agent is registered.";
  if (c.healthy === c.total) return `All ${c.total} agents are healthy.`;
  return `${c.total - c.healthy} of ${c.total} agents need attention.`;
}

function approvalsClause(pending: ApprovalRow[] | undefined, failed: boolean, now: number): { accent: string; tail: string } {
  if (failed) return { accent: "", tail: "Pending approvals could not be loaded." };
  if (!pending) return { accent: "", tail: "" };
  const n = pending.length;
  if (!n) return { accent: countWord(0), tail: "are waiting on you." };
  const first = firstExpiry(pending);
  const verb = n === 1 ? "is" : "are";
  if (!first) return { accent: countWord(n), tail: `${verb} waiting on you.` };
  const past = new Date(first).getTime() < now;
  return { accent: countWord(n), tail: `${verb} waiting on you; the first ${past ? "expired" : "expires"} at ${whenIST(first, now)}.` };
}

function subLine(st: DeskStatus): string {
  const parts = ["There is no P&L yet: orders and fills come with paper execution (Phase 2)."];
  const pm = premarketOf(st);
  if (pm?.status) {
    const segs = pm.allowed && pm.allowed.length ? `, with ${pm.allowed.join(", ").toLowerCase()} allowed` : pm.allowed ? ", with no segment allowed" : "";
    parts.push(`The last pre-market check${pm.sessionDate ? `, for ${dateShort(pm.sessionDate)}` : ""}, was ${pm.status.toLowerCase()}${segs}.`);
  } else {
    parts.push("No pre-market check has run on the desk yet.");
  }
  const bad = uniqueAgents(st).filter((a) => a.status !== "IDLE" && a.status !== "BUSY");
  if (bad.length) parts.push(bad.map((a) => `${agentName(a.agent_key)} is ${a.status.toLowerCase()}`).join("; ") + ".");
  return parts.join(" ");
}

function sessionTile(q: IndexQuotes | undefined, err: unknown, now: number): { v: string; s: string } {
  if (err) return { v: "—", s: "Session unknown: the Kite feed did not answer" };
  if (!q) return { v: "—", s: "Loading…" };
  if (!q.session) return { v: "—", s: "Session unknown" };
  const hours = "NSE · 09:15–15:30 IST";
  if (q.session === "open") {
    const close = new Date(`${todayIST(new Date(now))}T15:30:00+05:30`).getTime();
    const mins = Math.floor((close - now) / 60000);
    return { v: "Open", s: mins > 0 ? `${hours} · closes in ${Math.floor(mins / 60)}h ${mins % 60}m` : hours };
  }
  if (q.session === "pre_open") return { v: "Pre-open", s: hours };
  return { v: "Closed", s: hours };
}

const cap = (s: string) => s.charAt(0) + s.slice(1).toLowerCase();

export default function OverviewScreen() {
  const nav = useNavigate();
  const mobile = useIsMobile();
  const now = useNow(5000);
  const status = useDeskStatus();
  const pending = usePendingApprovals();
  const quotes = useIndexQuotes();
  const activities = useAgentActivities();
  const def = screenById("overview");
  const st = status.data;
  const known = !!st;
  const accounts = deskAccounts(st);
  const go = (id: ScreenId) => () => nav(screenById(id).path);

  const lead = leadSentence(st);
  const { accent, tail } = approvalsClause(pending.data, !!pending.error, now);
  const counts = agentCounts(st);
  const pm = premarketOf(st);
  const first = pending.data ? firstExpiry(pending.data) : null;
  const sess = sessionTile(quotes.data, quotes.error, now);
  const capital = accounts.reduce((s, a) => s + (Number(a.starting_capital_rs) || 0), 0);
  const modeOf = (m: string) => MODE_WORD[m] ?? m;

  const tiles: { id: string; k: string; v: string; s: string; tone: Tone; to?: ScreenId }[] = [
    {
      id: "mode", k: "Operating mode", to: "policies",
      v: accounts[0] ? modeOf(accounts[0].operating_mode) : "—",
      s: !known ? "—" : accounts.length
        ? accounts.map((a, i) => (i === 0 ? a.name : `${a.name} ${modeOf(a.operating_mode).toLowerCase()}`)).join(" · ")
        : "No desk account yet",
      tone: accounts[0]?.operating_mode === "AUTONOMOUS_PAPER" ? "mint" : "ink",
    },
    { id: "session", k: "Market session", v: sess.v, s: sess.s, tone: "ink" },
    {
      id: "agents", k: "Agents", to: "agents",
      v: known ? `${counts.healthy} · ${counts.degraded} · ${counts.offline}` : "—", s: "Healthy · degraded · offline",
      tone: !known ? "ink" : counts.offline ? "danger" : counts.degraded ? "amber" : "mint",
    },
    { id: "trades", k: "Active trades", v: "—", s: "Phase 2 · needs paper execution", tone: "ink", to: "trades" },
    {
      id: "pending", k: "Pending approvals", to: "approvals",
      v: pending.data ? String(pending.data.length) : "—",
      s: pending.error ? "Could not be loaded" : !pending.data ? "Loading…" : pending.data.length
        ? (first ? `First expires ${whenIST(first, now)} IST` : "No expiry set") : "Queue is clear",
      tone: pending.data?.length ? "amber" : pending.data ? "mint" : "ink",
    },
    { id: "orders", k: "Open orders", v: "—", s: "Phase 2 · no orders in Phase 1", tone: "ink", to: "trades" },
    {
      id: "capital", k: "Capital deployed", v: "—", tone: "ink", to: "risk",
      s: accounts.length ? `Phase 2 · starting capital ${rsShort(capital)}` : "Phase 2 · needs paper execution",
    },
    { id: "risk", k: "Open risk · margin", v: "—", s: "Phase 2 · needs positions", tone: "ink", to: "risk" },
    { id: "pnl", k: "Realized · unrealized", v: "—", s: "Phase 2 · needs fills", tone: "ink", to: "pnl" },
    { id: "exceptions", k: "Critical exceptions", v: "—", s: "Phase 2 · reconciliation needs fills", tone: "ink", to: "middle" },
    {
      id: "premarket", k: "Last pre-market check", to: "agents",
      v: pm?.status ? cap(pm.status) : "—",
      s: !known ? "—" : pm?.status
        ? `Session ${pm.sessionDate ? dateShort(pm.sessionDate) : "—"} · ${pm.allowed?.length ? pm.allowed.join(", ").toLowerCase() : "no new risk"}`
        : "Not run yet",
      tone: pm?.status ? PM_TONE[pm.status] ?? "ink" : "ink",
    },
    {
      id: "workflows", k: "Open workflows", to: "agents",
      v: st ? String(st.open_workflows) : "—", s: "Desk workflows created, running or waiting on you", tone: "ink",
    },
  ];

  return (
    <div data-testid="screen-overview" style={{ display: "flex", flexDirection: "column", gap: 28, fontFamily: "var(--sans)", color: "var(--ink)", minWidth: 0 }}>
      <ScreenHeader
        mobile={mobile}
        eyebrow={`${screenNo("overview")} · ${def.label}${st ? ` · ${dateLong(st.as_of)}` : ""}`}
        pills={accounts.map((a) => (
          <Pill key={a.account_id} tone={a.status !== "ACTIVE" ? "danger" : MODE_TONE[a.operating_mode] ?? "ink"} dot={a.operating_mode === "AUTONOMOUS_PAPER" && a.status === "ACTIVE"}>
            <span data-testid="mode-pill">{`${a.status !== "ACTIVE" ? a.status.toLowerCase() : modeOf(a.operating_mode)} · ${a.name}`}</span>
          </Pill>
        ))}
        title={
          status.isLoading ? <span style={{ color: "var(--ink-3)" }}>Loading the desk…</span> : (
            <span data-testid="headline">
              {lead}{lead && (accent || tail) ? " " : ""}
              {accent && <em style={{ color: "var(--amber)" }}>{accent}</em>}{accent ? " " : ""}{tail}
            </span>
          )
        }
        sub={st ? <span data-testid="subline">{subLine(st)}</span> : undefined}
      />
      {status.error && !isUnauthorized(status.error) && <ErrorBox error={status.error} what="the desk status" onRetry={() => status.refetch()} />}

      <NeedsYou pending={pending} mobile={mobile} now={now} />

      {status.isLoading ? <Loading label="Loading desk tiles" rows={2} /> : (
        <TileGrid min={mobile ? "150px" : "200px"}>
          {tiles.map((t) => (
            <Tile key={t.id} testId={`tile-${t.id}`} k={t.k} v={t.v} s={t.s} tone={t.tone} onClick={t.to ? go(t.to) : undefined} />
          ))}
        </TileGrid>
      )}

      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,380px),1fr))", gap: 14 }}>
        <PnlCard />
        <FeedsCard st={st} quotes={quotes.data} quotesError={quotes.error} now={now} />
      </section>

      <AgentsNow st={st} activities={activities} now={now} />

      <Activity activities={activities} mobile={mobile} now={now} />
    </div>
  );
}
