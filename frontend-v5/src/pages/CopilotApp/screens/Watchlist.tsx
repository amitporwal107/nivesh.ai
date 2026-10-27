import { NotConnected, Screen, ScreenHeader } from "../components/ui";
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
 */
export default function WatchlistScreen() {
  return (
    <Screen testId="screen-page-watchlist">
      <ScreenHeader
        eyebrow="Watchlist & alerts"
        title="Stocks you follow, and what you want to be told"
        sub="The AI scanner's daily ideas, your own lists, the research watchlist with live prices, this week's results names, your saved screens as watchlists, the price levels the scanner is watching, and your filing alerts."
      />
      <AiScannerWatchlist />
      <ResultsThisWeek />
      <PersonalLists />
      <ResearchWatchlist />
      <ScreenWatchlists />
      <SetupsToWatch />
      <FilingAlertSettings />
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
    </Screen>
  );
}
