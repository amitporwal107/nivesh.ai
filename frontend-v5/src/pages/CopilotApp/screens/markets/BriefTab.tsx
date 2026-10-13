/**
 * Markets → Daily Iris Update. The persisted rules-based brief from
 * GET /api/markets/daily-brief (today, or a past date picked from
 * GET /api/markets/daily-brief/history).
 */
import { useState } from "react";
import { useBriefHistory, useDailyBrief } from "@/hooks/use-markets";
import { EmptyBlock, Footnote, LoadingBlock, Tiles, fmtNum, fmtPct, relTime, signTone } from "../../components/ui";
import { dayLabel, fmtCr, fmtLevel, titleCase } from "./format";
import { LoadError, ReadCard, StoryCard } from "./parts";

export function BriefTab() {
  const [date, setDate] = useState<string | undefined>(undefined);
  const q = useDailyBrief(date);
  const history = useBriefHistory(30);

  if (q.isPending) return <LoadingBlock label="Loading the daily brief" rows={5} />;
  if (q.isError) return <LoadError title="The daily brief didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const b = q.data.brief;
  const days = history.data?.items ?? [];

  const picker = days.length > 0 && (
    <label className="flex flex-col self-start" style={{ gap: 4 }}>
      <span className="cp-mono-note">Brief for</span>
      <select
        value={date ?? b?.date ?? ""}
        onChange={(e) => setDate(e.target.value || undefined)}
        data-testid="markets-brief-date"
        style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13 }}
      >
        {!date && !b && <option value="">Today</option>}
        {days.map((h) => <option key={h.date} value={h.date}>{dayLabel(h.date, { year: true })}</option>)}
      </select>
    </label>
  );

  if (!b) {
    return (
      <>
        {picker}
        <EmptyBlock
          title="No brief for this day yet"
          body="The Daily Iris Update is written after the market data refreshes. Pick an earlier day, or check back shortly."
        />
      </>
    );
  }

  const s = b.stats;
  return (
    <>
      {picker}

      <ReadCard
        testId="markets-brief-read"
        eyebrow={`Iris read · rules-based · ${dayLabel(b.date, { year: true })}`}
        bullets={b.bullets}
      >
        <span data-testid="markets-brief-headline">{b.headline}</span>
      </ReadCard>

      <div data-testid="markets-brief-tiles">
        <Tiles
          items={[
            {
              k: "Nifty 50",
              v: <span data-testid="markets-brief-nifty">{fmtLevel(s.nifty_close)}</span>,
              s: fmtPct(s.nifty_change_pct, { signed: true, digits: 2 }),
              tone: signTone(s.nifty_change_pct),
            },
            { k: "India VIX", v: fmtLevel(s.vix), s: fmtPct(s.vix_change_pct, { signed: true, digits: 2 }) },
            {
              k: "Advances / declines",
              v: s.advances == null || s.declines == null ? "—" : `${fmtNum(s.advances)} / ${fmtNum(s.declines)}`,
              s: "NSE",
            },
            { k: "FII net", v: <span data-testid="markets-brief-fii">{fmtCr(s.fii_net_cr, { signed: true })}</span>, s: "Cash", tone: signTone(s.fii_net_cr) },
            { k: "DII net", v: <span data-testid="markets-brief-dii">{fmtCr(s.dii_net_cr, { signed: true })}</span>, s: "Cash", tone: signTone(s.dii_net_cr) },
          ]}
        />
      </div>

      {b.news.length > 0 && (
        <div className="flex flex-col" style={{ gap: 10 }} data-testid="markets-brief-news">
          {b.news.map((n, i) => (
            <StoryCard
              key={`${n.symbol ?? "x"}-${i}`}
              tag={titleCase(n.category)}
              title={n.title}
              meta={n.symbol ?? undefined}
              askQuery={n.symbol
                ? `What does this ${n.symbol} announcement mean for shareholders? “${n.title}”`
                : `Explain this market announcement: “${n.title}”`}
            />
          ))}
        </div>
      )}

      <Footnote>
        {b.generated_at ? `Generated ${relTime(b.generated_at)}` : "Generated"}
        {b.sources.length > 0 ? ` from ${b.sources.join(" · ")}` : ""} · a rules-based read of market data, not a forecast
      </Footnote>
    </>
  );
}
