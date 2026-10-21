/**
 * Markets → Daily Iris Update. The stored rules-based brief from GET
 * /api/markets/daily-brief (today, or a past date picked from GET
 * /api/markets/daily-brief/history): headline and bullets, the day's figures,
 * leading sectors, movers and notable announcements. The headline, the bullets
 * and the regime label are the backend's own words, shown as sent.
 */
import { useState } from "react";
import type { MarketMover } from "@/services/contracts/markets.contract";
import { StockIcon } from "../../components/EntityIcon";
import { DataTable, EmptyBlock, LoadingBlock, Pill, Section, Tiles, fmtNum, fmtPct, signTone, type Column } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel, fmtCr, fmtLevel, titleCase } from "./format";
import { isHeld, useHeldKeys, useMarketBrief, useMarketBriefDays } from "./hooks";
import { AskLink, CompanyCell, LoadError, NameCell, ReadCard, SelectField, Signed, SourceLine } from "./parts";

export function BriefTab() {
  const [date, setDate] = useState<string | undefined>(undefined);
  const q = useMarketBrief(date);
  const history = useMarketBriefDays(30);
  const held = useHeldKeys();
  const { ask, mobile } = useCopilotShell();

  if (q.isPending) return <LoadingBlock label="Loading the daily brief" rows={5} />;
  if (q.isError) return <LoadError title="The daily brief didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const b = q.data.brief;
  const days = history.data?.items ?? [];

  const picker = days.length > 0 && (
    <div className="flex">
      <SelectField label="Brief for" value={date ?? b?.date ?? ""} onChange={(v) => setDate(v || undefined)} testId="markets-brief-date">
        {!date && !b && <option value="">Today</option>}
        {days.map((h) => <option key={h.date} value={h.date}>{dayLabel(h.date, { year: true })}</option>)}
      </SelectField>
    </div>
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
  const state = b.market_state === "open" ? " · market open" : b.market_state === "closed" ? " · market closed" : "";
  const movers = [...b.movers.gainers, ...b.movers.losers];
  const sectors = b.top_sectors.flatMap((x) => (x.name ? [{ name: x.name, change_pct: x.change_pct }] : []));

  const moverColumns: Column<MarketMover>[] = [
    {
      key: "stock", header: "Stock", width: "minmax(0,1.7fr)",
      render: (m) => <CompanyCell symbol={m.symbol} name={m.name} held={isHeld(held.data, m.symbol, m.name)} />,
    },
    {
      key: "chg", header: "Change", align: "right", num: true,
      render: (m) => <Signed value={m.change_pct}>{fmtPct(m.change_pct, { signed: true, digits: 2 })}</Signed>,
    },
  ];
  const sectorColumns: Column<{ name: string; change_pct: number }>[] = [
    { key: "sector", header: "Sector", width: "minmax(0,1.7fr)", render: (x) => <NameCell name={x.name} /> },
    {
      key: "chg", header: "Change", align: "right", num: true,
      render: (x) => <Signed value={x.change_pct}>{fmtPct(x.change_pct, { signed: true, digits: 2 })}</Signed>,
    },
  ];

  return (
    <>
      {picker}

      <ReadCard
        testId="markets-brief-read"
        eyebrow={`Iris read · rules-based · ${dayLabel(b.date, { year: true })}${state}`}
        bullets={b.bullets}
        note={s.verdict
          ? <span data-testid="markets-brief-verdict">Rules-based regime label · {s.verdict.toLowerCase()}</span>
          : undefined}
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
            },
            { k: "FII net", v: <span data-testid="markets-brief-fii">{fmtCr(s.fii_net_cr, { signed: true })}</span>, s: "Cash", tone: signTone(s.fii_net_cr) },
            { k: "DII net", v: <span data-testid="markets-brief-dii">{fmtCr(s.dii_net_cr, { signed: true })}</span>, s: "Cash", tone: signTone(s.dii_net_cr) },
          ]}
        />
      </div>

      {(sectors.length > 0 || movers.length > 0) && (
        <div className="grid" style={{ gridTemplateColumns: mobile || sectors.length === 0 || movers.length === 0 ? "minmax(0,1fr)" : "minmax(0,1fr) minmax(0,1fr)", gap: 12, alignItems: "start" }}>
          {sectors.length > 0 && (
            <Section title="Leading sectors" flush>
              <div data-testid="markets-brief-sectors">
                <DataTable columns={sectorColumns} rows={sectors} rowKey={(x) => x.name} minWidth={260} />
              </div>
            </Section>
          )}
          {movers.length > 0 && (
            <Section title="Top movers" note="Gainers first, then losers" flush>
              <div data-testid="markets-brief-movers">
                <DataTable
                  columns={moverColumns}
                  rows={movers}
                  rowKey={(m, i) => `${m.symbol}-${i}`}
                  onRowClick={(m) => ask(`Tell me about ${m.name}`)}
                  minWidth={280}
                />
              </div>
            </Section>
          )}
        </div>
      )}

      {b.news.length > 0 && (
        <Section title="Notable announcements" flush>
          <div data-testid="markets-brief-news">
            {b.news.map((n, i) => (
              <div
                key={`${n.symbol ?? "x"}-${i}`}
                data-testid="markets-brief-news-item"
                className="flex items-start"
                style={{ gap: 12, padding: "12px 16px", borderTop: i ? "1px solid var(--cp-line)" : undefined }}
              >
                {n.symbol && <StockIcon symbol={n.symbol} size={26} />}
                <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
                  <span style={{ fontSize: 13.5, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{n.title}</span>
                  <span className="flex flex-wrap items-center" style={{ gap: "6px 10px" }}>
                    <Pill>{titleCase(n.category)}</Pill>
                    {n.symbol && <span className="cp-mono-note">{n.symbol}</span>}
                    <AskLink
                      query={n.symbol
                        ? `What does this ${n.symbol} announcement mean for shareholders? “${n.title}”`
                        : `Explain this market announcement: “${n.title}”`}
                    >
                      Ask Copilot about this ›
                    </AskLink>
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      <SourceLine
        testId="markets-brief-source"
        source={b.sources}
        asOf={b.generated_at}
        asOfLabel="generated"
        note="A rules-based read of market data, not a forecast"
      />
    </>
  );
}
