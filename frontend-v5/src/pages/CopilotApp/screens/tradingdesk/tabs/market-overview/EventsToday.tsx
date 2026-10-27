/**
 * Market Overview — events today: results and filings dated today (IST) for the names on today's ideas, at most five.
 *
 *   names    the Top AI ideas' cash symbols and F&O underlyings (POST /api/desk/strategy/ideas and /top) and the newest
 *            stored AI watchlist's (GET /api/desk/ai-watchlist): the same cached answers the ideas panel shows
 *   events   GET /api/filings/feed through Market Intelligence's lists (intel-data.ts useIntelEvents "all" and "results",
 *            the reads the old Overview's Key market events used), so opening Market Intelligence shows them at once
 *
 * The lists are the feed's newest filings and newest results filings of the last week (the route's limit), not every
 * filing of the day: the legend says so, and Market Intelligence has the rest. Each event names its source; nothing here
 * is an AI read or a recommendation.
 */
import { useMemo, type CSSProperties } from "react";
import { StockIcon } from "../../../../components/EntityIcon";
import { LoadingBlock } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { useAiWatchlist } from "../../../workspace/ai-watchlist-data";
import { useDesk } from "../../context";
import { GROUP_COLOR, eventWhen, useIntelEvents, type IntelEvent } from "../../intel-data";
import { mergeFno, useTop10Fno, useTop10Stocks } from "../../top10-data";
import { Widget } from "../../widget";
import { eventsToday, istDayOf } from "./overview-data";

const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };

/** Every name on today's ideas (both boards and the stored list), upper case. */
function useWatchedNames(): Set<string> {
  const stocks = useTop10Stocks().data;
  const fno = useTop10Fno().data;
  const day = useAiWatchlist(null).data;
  return useMemo(() => {
    const out = new Set<string>();
    for (const i of stocks?.ideas ?? []) out.add(i.symbol.toUpperCase());
    for (const r of mergeFno(fno)) out.add(r.idea.underlying.toUpperCase());
    for (const e of day?.cash ?? []) out.add(e.symbol.toUpperCase());
    for (const e of day?.fno ?? []) out.add(e.underlying.toUpperCase());
    return out;
  }, [stocks, fno, day]);
}

function EventRow({ e, onStock }: { e: IntelEvent; onStock: (sym: string) => void }) {
  const when = eventWhen(e.at);
  const src = e.sources[0] ?? null;
  const sym = e.symbol as string;
  return (
    <li data-testid="mo-event" data-id={e.id} data-group={e.group} className="grid" style={{ gridTemplateColumns: "48px minmax(0,1fr)", gap: 10, padding: "10px 0", borderTop: "1px solid var(--cp-line)" }}>
      <span className="cp-num" title={when.full} style={{ fontSize: 10.5, color: "var(--cp-ink-3)", paddingTop: 2 }}>{when.short}</span>
      <div className="flex min-w-0 flex-col" style={{ gap: 3 }}>
        <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "2px 10px" }}>
          <button type="button" data-testid="mo-event-stock" onClick={() => onStock(sym)} aria-label={`${sym}: open its chart`} className="inline-flex items-center"
            style={{ gap: 6, padding: 0, border: 0, background: "none", cursor: "pointer", color: "var(--cp-ink)", fontFamily: "var(--mono)", fontSize: 11.5 }}>
            <StockIcon symbol={sym} name={e.name} size={16} /><span data-testid="mo-event-symbol">{sym}</span>
          </button>
          <span className="cp-num" style={{ fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase", color: GROUP_COLOR[e.group] }}>{e.type}</span>
        </span>
        <span data-testid="mo-event-title" style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.4, overflowWrap: "anywhere" }}>{e.title}</span>
        <span style={{ ...quiet, fontSize: 11.5, overflowWrap: "anywhere" }}>
          Source: {src?.text ?? e.sourceLabel}
          {src?.url && <> · <a href={src.url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--mint)" }}>open ↗</a></>}
        </span>
      </div>
    </li>
  );
}

export function EventsToday() {
  const { mobile } = useCopilotShell();
  const desk = useDesk();
  const names = useWatchedNames();
  const all = useIntelEvents("all");
  const results = useIntelEvents("results");
  const today = istDayOf(new Date().toISOString()) as string;
  const shown = useMemo(() => eventsToday([...results.events, ...all.events], names, today), [results.events, all.events, names, today]);
  const loading = all.status === "loading" && results.status === "loading";
  const failed = all.status === "error" && results.status === "error";
  return (
    <Widget id="overview.events.today" testId="mo-events" title="Events today" meta={<span style={{ fontSize: 9.5 }}>Results and filings · names on today’s ideas</span>} bodyStyle={{ padding: mobile ? 14 : 18 }}>
      <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
        {loading ? (
          <LoadingBlock label="Loading today’s filings" rows={2} />
        ) : failed ? (
          <span data-testid="mo-events-error" style={quiet}>Filings didn’t load. Market Intelligence has the full list.</span>
        ) : shown.length === 0 ? (
          <span data-testid="mo-events-empty" style={{ ...quiet, color: "var(--cp-ink-2)" }}>
            {names.size === 0 ? "No ideas yet, so no names to look for." : `No results or filings today for the ${names.size} names on today’s ideas.`}
          </span>
        ) : (
          <ul data-testid="mo-events-list" className="m-0 flex flex-col p-0" style={{ listStyle: "none" }}>
            {shown.map((e) => <EventRow key={e.id} e={e} onStock={(s) => desk.openChart(s)} />)}
          </ul>
        )}
        <span data-testid="mo-events-legend" style={{ ...quiet, fontSize: 11.5 }}>
          From Market Intelligence’s newest filings and results of the week, dated today (IST).{" "}
          <button type="button" data-testid="mo-events-all" onClick={() => desk.openIntel()} style={{ padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", color: "var(--mint)" }}>Market Intelligence ›</button>
        </span>
      </div>
    </Widget>
  );
}
