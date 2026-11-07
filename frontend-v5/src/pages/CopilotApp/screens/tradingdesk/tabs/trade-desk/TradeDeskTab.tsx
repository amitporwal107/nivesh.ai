/**
 * Smart trading desk — 02 Trade Desk › Paper Trading (the owner's workbench, docs/desk_redesign_20261027/PLAN.md "1-REVISED").
 *
 * Paper Trading v2 (owner, 5 Nov 2026: "We need to completely replace the current paper trading dashboard";
 * docs/scanner_paper_trading/UI_DESIGN_V2.md): exactly his six views, each under the shell (paper/shell.tsx: the status
 * strip, the account card and the mode chooser):
 *
 *   ?tab=trade&view=paper&sub=overview        01 Overview               paper/Overview.tsx        (builder A)
 *   ?tab=trade&view=paper&sub=opportunities   02 Scanner opportunities  paper/Opportunities.tsx   (builder A)
 *   ?tab=trade&view=paper&sub=allocation      03 Capital allocation     paper/Allocation.tsx      (builder B)
 *   ?tab=trade&view=paper&sub=risk            04 Portfolio risk         paper/Risk.tsx            (builder B)
 *   ?tab=trade&view=paper&sub=pnl             05 Real-time P&L          paper/Pnl.tsx             (builder B)
 *   ?tab=trade&view=paper&sub=analytics       06 Strategy analytics     paper/Analytics.tsx       (builder A)
 *
 * The old sub-views' URLs redirect (desk-nav.ts PAPER_OLD_SUBS: live, journal → pnl; settings → allocation; the Risk Desk's
 * overview / allocation / portfolio → overview / allocation / risk). No code is deleted in this release: the pre-v2 screens
 * (Live desk, Trade journal, P&L dashboard, the SPT Opportunities / Analytics / Settings) stay in the tree, routed nowhere;
 * PaperBookTab below is kept for the same reason.
 *
 * The frame (TradingDesk.tsx) draws the sections, the numbered sub-view chips (with the 02 badge) and the "These are paper
 * trades… My portfolio" line. Nothing is sent to a broker.
 */
import { useSearchParams } from "react-router-dom";
import { LoadingBlock } from "../../../../components/ui";
import { QueryProblem } from "../../../trading/parts";
import { useDesk } from "../../context";
import { usePaperTrades, type PaperBook } from "../../desk-trading";
import { ClosedView, OpenPendingView } from "./BookViews";
import { HeaderStrip } from "./HeaderStrip";
import { JournalPanel, type JournalTrade } from "./Journal";
import { quiet } from "./parts";
import { PaperAllocation } from "./paper/Allocation";
import { PaperAnalytics } from "./paper/Analytics";
import { usePaperAccount } from "./paper/api-a";
import { PaperOpportunities } from "./paper/Opportunities";
import { PaperOverview } from "./paper/Overview";
import { PaperPnl } from "./paper/Pnl";
import { PaperRisk } from "./paper/Risk";
import { PaperShell } from "./paper/shell";

/** The journal's trade: ?trade=<id>, else the newest closed trade, else the newest open one. */
function journalTrade(d: PaperBook, id: string | null): JournalTrade | null {
  const cash = d.trades.find((t) => t.id === id);
  if (cash) return { kind: "cash", t: cash };
  const st = d.strategyTrades.find((t) => t.id === id);
  if (st) return { kind: "strategy", t: st };
  const closed = [...d.trades.filter((t) => t.status === "closed").map((t): JournalTrade => ({ kind: "cash", t })),
    ...d.strategyTrades.filter((t) => t.status === "closed").map((t): JournalTrade => ({ kind: "strategy", t }))]
    .sort((a, b) => String(b.t.closedAt ?? "").localeCompare(String(a.t.closedAt ?? "")));
  if (closed.length) return closed[0];
  const open = d.trades[0] ? { kind: "cash" as const, t: d.trades[0] } : d.strategyTrades[0] ? { kind: "strategy" as const, t: d.strategyTrades[0] } : null;
  return open;
}

/** The six Paper Trading v2 views (desk-nav.ts SUB_VIEWS "trade/paper"); anything else is the default, 01 Overview. */
const V2_SUBS = ["overview", "opportunities", "allocation", "risk", "pnl", "analytics"] as const;
type V2Sub = (typeof V2_SUBS)[number];

export default function TradeDeskTab({ sub }: {
  sub: string | null; onSub: (sub: string, extra?: Record<string, string>) => void;
}) {
  const acct = usePaperAccount();
  const accountId = acct.data?.accountId ?? null;
  const v: V2Sub = (V2_SUBS as readonly string[]).includes(sub ?? "") ? (sub as V2Sub) : "overview";
  return (
    <div data-testid="td-tab" data-section="paper" data-sub={v} className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      <PaperShell acct={acct} />
      {v === "overview" ? <PaperOverview />
        : v === "opportunities" ? <PaperOpportunities mode={acct.data?.config?.mode ?? null} />
        : v === "allocation" ? <PaperAllocation accountId={accountId} />
        : v === "risk" ? <PaperRisk accountId={accountId} />
        : v === "pnl" ? <PaperPnl accountId={accountId} />
        : <PaperAnalytics accountId={accountId} />}
    </div>
  );
}

/** Retained, not routed (Paper Trading v2, owner 5 Nov: no code is deleted in this release). Live desk and Trade journal:
 *  both read the one paper-trades answer. */
export function PaperBookTab({ sub, onSub }: {
  sub: string | null; onSub: (sub: string, extra?: Record<string, string>) => void;
}) {
  const desk = useDesk();
  const [params] = useSearchParams();
  const q = usePaperTrades();
  const openJournal = (j: JournalTrade) => onSub("journal", { trade: j.t.id });

  let body;
  if (q.isPending) body = <LoadingBlock label="Reading your paper trades" rows={4} />;
  else if (q.isError) body = <div data-testid="td-trades-error"><QueryProblem what="Your paper trades" error={q.error} onRetry={() => q.refetch()} /></div>;
  else if (sub === "journal") {
    const item = journalTrade(q.data, params.get("trade"));
    const all = [...q.data.trades.map((t) => ({ id: t.id, label: `${t.symbol} · ${t.status}` })), ...q.data.strategyTrades.map((t) => ({ id: t.id, label: `${t.familyName ?? t.family ?? "Structure"} ${t.underlying} · ${t.status}` }))];
    body = (
      <div data-testid="td-view-journal" className="flex min-w-0 flex-col" style={{ gap: 16 }}>
        {item ? (
          <>
            <label className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 12, color: "var(--cp-ink-3)" }}>
              Trade
              <select data-testid="td-journal-pick" value={item.t.id} onChange={(e) => onSub("journal", { trade: e.target.value })}
                style={{ height: 32, minWidth: 0, maxWidth: "100%", padding: "0 8px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)" }}>
                {all.map((o) => <option key={o.id} value={o.id}>{o.label} · {o.id}</option>)}
              </select>
            </label>
            <JournalPanel key={item.t.id} item={item} onChart={(s) => desk.openChart(s)} />
          </>
        ) : <span data-testid="td-journal-none" style={quiet}>No paper trades yet, so there is no journal to show.</span>}
        <ClosedView d={q.data} onOpen={openJournal} />
      </div>
    );
  } else {
    body = (
      <>
        <OpenPendingView d={q.data} onOpen={openJournal} onChart={(s) => desk.openChart(s)} onNewTrade={() => desk.openStrategyIdeas()} onOverview={() => desk.openTab("overview")} />
        <ClosedView d={q.data} onOpen={openJournal} recent={5} />
      </>
    );
  }

  return (
    <div data-testid="td-tab" data-section="paper" data-sub={sub ?? ""} className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      {sub !== "journal" && <HeaderStrip />}
      {body}
    </div>
  );
}
