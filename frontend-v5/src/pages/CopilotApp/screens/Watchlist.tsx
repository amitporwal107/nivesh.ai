import {
  EmptyBlock, Footnote, LoadingBlock, NotConnected, Pill, Screen, ScreenHeader, TONE_COLOR,
  fmtNum, relTime, type Tone,
} from "../components/ui";
import { useFilingAlerts } from "./markets/hooks";
import { LoadError } from "./markets/parts";

/**
 * Watchlist & alerts. Design: design/nivesh-copilot/NVPages.dc.html
 * (page === "watchlist").
 *
 * The product has no per-user watchlist and no price alerts yet, so this screen
 * says so and shows the one real thing it has: the user's filing-alert
 * preferences (GET /api/filings/alerts), read-only.
 *
 * The dated research list behind the public /watchlist page
 * (GET /api/public/research-watchlist) is NOT shown here on purpose:
 * backend/routes/research_watchlist.py states it is internal research that is
 * not linked from any in-app navigation.
 */
export default function WatchlistScreen() {
  return (
    <Screen testId="screen-page-watchlist">
      <ScreenHeader
        eyebrow="Watchlist & alerts"
        title="Stocks you follow, and what you want to be told"
        sub="A watchlist of your own is not connected yet. Your filing-alert preferences are shown below."
      />

      <NotConnected
        testId="watchlist-personal-nc"
        title="Your own watchlist is not connected yet"
        body="The design lets you add any stock, see Nivesh’s latest read on it and attach the condition you want to be told about. The product has nowhere to store that yet."
        needs={[
          "An endpoint to add, list and remove stocks on a watchlist that belongs to you",
          "A one-line current read for each watched stock",
          "A condition per stock (price, volume, moving average) and a job that checks it",
        ]}
      />

      <FilingAlerts />

      <NotConnected
        testId="watchlist-alerts-nc"
        title="Price and event alerts are not connected yet"
        body="The design lists alerts such as a close above a level on higher volume, a fall below the 200-day average or a change in promoter pledge, each with its channel and when it last fired."
        needs={[
          "Alert rules on price, volume, technical levels, pledge changes and screen matches",
          "A delivery service (in-app and email), and a record of when each alert fired",
          "A way to change filing-alert types and channels from this screen (the save endpoint exists; the app has no mutation hook for it)",
        ]}
      />
    </Screen>
  );
}

function FilingAlerts() {
  const q = useFilingAlerts();

  if (q.isPending) return <LoadingBlock label="Loading your alerts" />;
  if (q.isError) return <LoadError title="Your alert preferences didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const prefs = q.data;
  // true = alerts are being sent, false = saved but nothing is sent, null = the response did not say.
  const sending = prefs.delivery ? prefs.delivery.active : null;
  const channels = Object.entries(prefs.channels).filter(([, on]) => on).map(([c]) => c);
  const onCount = prefs.catalog.filter((c) => prefs.types[c.key]).length;

  if (prefs.catalog.length === 0) {
    return (
      <div className="flex flex-col" style={{ gap: 10 }}>
        <span className="cp-eyebrow">Filing alerts</span>
        <EmptyBlock title="No filing-alert types to show" body="The list of filing types did not come back with your preferences." />
      </div>
    );
  }

  return (
    <div className="flex flex-col" style={{ gap: 10 }}>
      <span className="cp-eyebrow">
        Filing alerts · <span data-testid="watchlist-alerts-on">{fmtNum(onCount)}</span> of {fmtNum(prefs.catalog.length)} types on
      </span>

      {sending === false && (
        <div
          data-testid="watchlist-alerts-delivery"
          style={{ padding: "10px 14px", borderRadius: 12, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}
        >
          {prefs.delivery?.note ?? "Preferences are saved, but scheduled delivery is not switched on yet."}
        </div>
      )}

      {prefs.catalog.map((c) => {
        const on = !!prefs.types[c.key];
        const tone: Tone = !on ? "ink" : sending === true ? "mint" : sending === false ? "amber" : "ink";
        const status = !on ? "Off" : sending === true ? "On" : sending === false ? "Saved · not sending" : "Saved";
        return (
          <div key={c.key} data-testid="watchlist-alert" className="cp-card flex flex-wrap items-center" style={{ gap: "8px 14px", padding: "12px 16px", borderRadius: 12 }}>
            <span className="nv-dot" style={{ background: on ? TONE_COLOR[tone] : "var(--cp-ink-4)" }} aria-hidden />
            <span style={{ flex: "1 1 220px", fontSize: 14 }}>{c.label}</span>
            <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>
              {on ? (channels.length ? channels.join(" · ") : "No channel chosen") : "—"}
            </span>
            <Pill tone={tone}>{status}</Pill>
          </div>
        );
      })}

      {prefs.updatedAt && <Footnote>Preferences saved {relTime(prefs.updatedAt)}</Footnote>}
    </div>
  );
}
