import { NotConnected, Screen, ScreenHeader } from "../components/ui";
import { FilingAlertSettings } from "./workspace/FilingAlerts";
import { ResearchWatchlist } from "./workspace/ResearchWatchlist";
import { ScreenWatchlists } from "./workspace/ScreenWatchlists";
import { SetupsToWatch } from "./workspace/SetupsToWatch";

/**
 * Watchlist & alerts. Design: design/nivesh-copilot/NVPages.dc.html
 * (page === "watchlist").
 *
 * Everything the product already has that is a watchlist or an alert, each from
 * the endpoint its original screen uses:
 *   · the research watchlist (the /watchlist page): dated lists, live quotes and
 *     the research behind each stock — workspace/ResearchWatchlist.tsx
 *   · the user's saved screens as watchlists, both kinds: rule screens and
 *     ready-made screens kept from the Screener — workspace/ScreenWatchlists.tsx
 *   · the scanner's price levels to watch (also on the Trader desk) —
 *     workspace/SetupsToWatch.tsx
 *   · filing-alert choices, which can be changed here — workspace/FilingAlerts.tsx
 * A list of hand-picked stocks and alerts on a price have no store in the
 * product, and the last block says so.
 */
export default function WatchlistScreen() {
  return (
    <Screen testId="screen-page-watchlist">
      <ScreenHeader
        eyebrow="Watchlist & alerts"
        title="Stocks you follow, and what you want to be told"
        sub="The research watchlist with live prices, your saved screens as watchlists, the price levels the scanner is watching, and your filing alerts."
      />
      <ResearchWatchlist />
      <ScreenWatchlists />
      <SetupsToWatch />
      <FilingAlertSettings />
      <NotConnected
        testId="watchlist-alerts-nc"
        title="Hand-picked lists and price alerts are not connected yet"
        body="Watchlists here come from the research list, from your saved screens and from the scanner. Adding a single stock by hand, and being told when a price, a volume or a pledge level is crossed, have nowhere to be stored yet."
        needs={[
          "A per-user watchlist store with endpoints to create a list and to add, list and remove a symbol (none exists: GET /api/positional/watchlist is the scanner’s list, GET /api/public/research-watchlist is the published one)",
          "Alert rules on price, volume, technical levels, pledge changes and screen matches, with a job that checks them and a record of when each one fired",
          "A delivery job for filing alerts: the choices above are stored, and routes/filings.py answers delivery.active = false until one exists",
          "A consumer for the notification preferences at GET/PATCH /api/user/preferences (push, email): the routes exist, nothing reads the values, so they are not shown here",
        ]}
      />
    </Screen>
  );
}
