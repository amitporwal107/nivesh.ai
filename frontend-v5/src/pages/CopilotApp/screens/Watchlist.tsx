import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { NotConnected, Screen, ScreenHeader } from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { AiScannerWatchlist } from "./workspace/AiScannerWatchlist";
import { FilingAlertSettings } from "./workspace/FilingAlerts";
import { PersonalLists } from "./workspace/PersonalLists";
import { ResearchWatchlist } from "./workspace/ResearchWatchlist";
import { ResultsThisWeek } from "./workspace/ResultsThisWeek";
import { ScreenWatchlists } from "./workspace/ScreenWatchlists";
import { SetupsToWatch } from "./workspace/SetupsToWatch";

/**
 * Watchlist & alerts. Design: design/nivesh-copilot/NVPages.dc.html
 * (page === "watchlist").
 *
 * Everything the product has that is a watchlist or an alert, each from its own
 * endpoint:
 *   · the AI scanner watchlist: the Top 10 cash and F&O ideas stored after each
 *     day's scan, by day, with Kite prices and links into the trading desk —
 *     workspace/AiScannerWatchlist.tsx (/api/desk/ai-watchlist)
 *   · Results This Week: this week's results names, scored (verdict vs historical
 *     trend, earnings score, ideas order, results booster, F&O before → after),
 *     each opening its results file — workspace/ResultsThisWeek.tsx
 *     (/api/desk/results-week, /api/desk/results-week/stock/{symbol})
 *   · the user's own lists: name a list, add and remove stocks, with a quote on
 *     each — workspace/PersonalLists.tsx (/api/watchlists). A first-time user is
 *     given one example list, a copy of the newest research watchlist.
 *   · the research watchlist (the /watchlist page): dated lists, live quotes and
 *     the research behind each stock — workspace/ResearchWatchlist.tsx
 *   · the user's saved screens as watchlists, both kinds: rule screens and
 *     ready-made screens kept from the Screener — workspace/ScreenWatchlists.tsx
 *   · the scanner's price levels to watch (also on the Trader desk) —
 *     workspace/SetupsToWatch.tsx
 *   · filing-alert choices, which can be changed here — workspace/FilingAlerts.tsx
 * Alerts on a price or a volume, and the sending of any alert, have no store or
 * job in the product, and the last block says so.
 *
 * Layout (owner, 28 Oct): the watchlists are listed in a left panel; the one picked shows in the rest of the screen.
 * The pick lives in the URL (?wl=…; default Results This Week), so a link or the back button opens the same list, and
 * it works the same on this page and on the desk's Trade Desk › Watchlists, which hosts this screen. "All on one page"
 * (?wl=all) shows every block one after another, as the page did before. Phone: the list becomes a row of chips.
 */
type ListId = "results-this-week" | "ai-scanner" | "my-lists" | "research" | "screens" | "setups" | "alerts" | "all";

const LISTS: { id: ListId; label: string; sub: string }[] = [
  { id: "results-this-week", label: "Results This Week", sub: "This week's results names, scored" },
  { id: "ai-scanner", label: "AI scanner watchlist", sub: "Daily Top 10 cash and F&O ideas" },
  { id: "my-lists", label: "My lists", sub: "Your own lists of stocks" },
  { id: "research", label: "Research watchlist", sub: "Dated research lists, live prices" },
  { id: "screens", label: "Saved screens", sub: "Your screener screens as watchlists" },
  { id: "setups", label: "Price levels to watch", sub: "Levels the scanner is watching" },
  { id: "alerts", label: "Filing alerts", sub: "Which filings you want to hear about" },
  { id: "all", label: "All on one page", sub: "Every list, one after another" },
];
const DEFAULT_LIST: ListId = "results-this-week";

function AlertsNotConnected() {
  return (
    <NotConnected
      testId="watchlist-alerts-nc"
      title="Price and volume alerts, and the sending of alerts, are not connected yet"
      body="You can keep your own lists of stocks above. Being told when a price, a volume or a pledge level is crossed has nowhere to be stored yet, and the filing alerts you choose here are saved but not sent."
      needs={[
        "Alert rules on price, volume, technical levels, pledge changes and screen matches, with a job that checks them and a record of when each one fired",
        "A delivery job for filing alerts: the choices above are stored, and routes/filings.py answers delivery.active = false until one exists",
        "A consumer for the notification preferences at GET/PATCH /api/user/preferences (push, email): the routes exist, nothing reads the values, so they are not shown here",
      ]}
    />
  );
}

function ListContent({ id }: { id: ListId }): ReactNode {
  switch (id) {
    case "results-this-week": return <ResultsThisWeek />;
    case "ai-scanner": return <AiScannerWatchlist />;
    case "my-lists": return <PersonalLists />;
    case "research": return <ResearchWatchlist />;
    case "screens": return <ScreenWatchlists />;
    case "setups": return <SetupsToWatch />;
    case "alerts": return <><FilingAlertSettings /><AlertsNotConnected /></>;
    default:
      return (
        <>
          <ResultsThisWeek />
          <AiScannerWatchlist />
          <PersonalLists />
          <ResearchWatchlist />
          <ScreenWatchlists />
          <SetupsToWatch />
          <FilingAlertSettings />
          <AlertsNotConnected />
        </>
      );
  }
}

function ListNav({ current, onPick, phone }: { current: ListId; onPick: (id: ListId) => void; phone: boolean }) {
  if (phone) {
    return (
      <nav aria-label="Watchlists" data-testid="wl-nav" data-layout="chips" className="flex min-w-0" style={{ gap: 6, overflowX: "auto", paddingBottom: 4 }}>
        {LISTS.map((l) => (
          <button key={l.id} type="button" className="cp-chip" data-testid={`wl-nav-${l.id}`} aria-current={l.id === current ? "page" : undefined}
            onClick={() => onPick(l.id)} style={{ flex: "none", whiteSpace: "nowrap", fontSize: 12, padding: "6px 11px",
              borderColor: l.id === current ? "var(--mint-line)" : undefined, color: l.id === current ? "var(--mint)" : undefined }}>
            {l.label}
          </button>
        ))}
      </nav>
    );
  }
  return (
    <nav aria-label="Watchlists" data-testid="wl-nav" data-layout="panel" className="flex flex-col"
      style={{ position: "sticky", top: 12, alignSelf: "start", gap: 2, padding: 6, borderRadius: 12, border: "1px solid var(--cp-line)", background: "var(--bg-1, transparent)" }}>
      <span className="cp-eyebrow" style={{ padding: "6px 10px 8px" }}>Watchlists</span>
      {LISTS.map((l) => {
        const on = l.id === current;
        return (
          <button key={l.id} type="button" data-testid={`wl-nav-${l.id}`} aria-current={on ? "page" : undefined} onClick={() => onPick(l.id)}
            className="flex min-w-0 flex-col" style={{ gap: 2, padding: "8px 10px", borderRadius: 8, border: 0, textAlign: "left", cursor: "pointer",
              background: on ? "var(--mint-bg, rgba(46,204,113,0.10))" : "transparent", color: "inherit",
              boxShadow: on ? "inset 2px 0 0 var(--mint)" : undefined }}>
            <span style={{ fontSize: 13, fontWeight: on ? 600 : 500, color: on ? "var(--mint)" : "var(--cp-ink)" }}>{l.label}</span>
            <span style={{ fontSize: 11, color: "var(--cp-ink-3)", lineHeight: 1.35 }}>{l.sub}</span>
          </button>
        );
      })}
    </nav>
  );
}

export default function WatchlistScreen() {
  const { mobile } = useCopilotShell();
  const [params, setParams] = useSearchParams();
  const asked = params.get("wl") as ListId | null;
  const current: ListId = asked && LISTS.some((l) => l.id === asked) ? asked : DEFAULT_LIST;
  const pick = (id: ListId) => setParams((prev) => {
    const next = new URLSearchParams(prev);
    next.set("wl", id);
    return next;
  });
  const picked = LISTS.find((l) => l.id === current)!;
  return (
    <Screen testId="screen-page-watchlist" width={1360}>   {/* the 220 px panel + room for the Results This Week rows (1080) */}
      <ScreenHeader
        eyebrow="Watchlist & alerts"
        title="Stocks you follow, and what you want to be told"
        sub="Pick a watchlist on the left. This week's results names. The AI scanner's daily ideas, your own lists, the research watchlist with live prices, your saved screens as watchlists, the price levels the scanner is watching, and your filing alerts."
      />
      <div data-testid="wl-layout" className={mobile ? "flex min-w-0 flex-col" : "grid min-w-0"}
        style={mobile ? { gap: 12 } : { gridTemplateColumns: "220px minmax(0,1fr)", gap: 18, alignItems: "start" }}>
        <ListNav current={current} onPick={pick} phone={mobile} />
        <section data-testid="wl-content" data-list={current} aria-label={picked.label} className="flex min-w-0 flex-col" style={{ gap: mobile ? 12 : 16 }}>
          <ListContent id={current} />
        </section>
      </div>
    </Screen>
  );
}
