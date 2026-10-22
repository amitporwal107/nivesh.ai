/**
 * Markets → Sector Analysis. One row per sector profile from GET
 * /api/markets/sectors; opening a row reads that sector's detail from GET
 * /api/markets/sectors/{slug} (figures, largest companies, commentary).
 *
 * Units: returns and changes are in percent, market cap in ₹ crore. "Up / down"
 * counts the sector's stocks by their one-year return, as the endpoint defines it.
 */
import { useState, type ReactNode } from "react";
import { Markdown } from "@/components/chat/Markdown";
import type { SectorCard, SectorDetail, SectorTopCompany } from "@/services/contracts/markets.contract";
import {
  Btn, DataTable, EmptyBlock, LoadingBlock, Section, Tiles, fmtNum, fmtPct, signTone,
  type Column,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { fmtCrCompact, fmtMultiple } from "./format";
import { isHeld, useHeldKeys, useSectorDetail, useSectorList } from "./hooks";
import { AskLink, CompanyCell, LoadError, NameCell, ReadCard, Signed, SourceLine } from "./parts";

function pctCell(n: number | null | undefined, digits = 2) {
  return <Signed value={n}>{fmtPct(n, { signed: true, digits })}</Signed>;
}

function upDown(advancing: number | null | undefined, declining: number | null | undefined): string {
  return advancing == null && declining == null ? "—" : `${fmtNum(advancing ?? 0)} / ${fmtNum(declining ?? 0)}`;
}

/** Leader and laggard by one-year average return, from the rows on screen. */
function sectorLine(ranked: SectorCard[]): string {
  const withYear = ranked.filter((s) => s.metrics.avg_return_1y != null);
  if (withYear.length < 2) {
    return `${ranked.length} ${ranked.length === 1 ? "sector" : "sectors"} tracked. One-year returns are not available for a comparison yet.`;
  }
  const top = withYear[0];
  const bottom = withYear[withYear.length - 1];
  return `${top.name} leads over the year with an average stock return of ${fmtPct(top.metrics.avg_return_1y, { signed: true })}; `
    + `${bottom.name} is weakest at ${fmtPct(bottom.metrics.avg_return_1y, { signed: true })}.`;
}

export function SectorsTab() {
  const q = useSectorList();
  const [open, setOpen] = useState<string | null>(null);

  if (q.isPending) return <LoadingBlock label="Loading sectors" rows={5} />;
  if (q.isError) return <LoadError title="Sectors didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const sectors = q.data.sectors;
  if (q.data.ok === false || sectors.length === 0) {
    return (
      <EmptyBlock
        title="Sector figures are being prepared"
        body="They appear once the latest market data has loaded on the data platform."
      />
    );
  }

  // Highest one-year average return first; sectors without one go last.
  const ranked = [...sectors].sort((a, b) => {
    const x = a.metrics.avg_return_1y;
    const y = b.metrics.avg_return_1y;
    if (x == null && y == null) return a.name.localeCompare(b.name);
    if (x == null) return 1;
    if (y == null) return -1;
    return y - x;
  });
  const asOf = ranked.find((s) => s.as_of_date)?.as_of_date;
  const selected = ranked.find((s) => s.slug === open);

  const columns: Column<SectorCard>[] = [
    { key: "sector", header: "Sector", width: "minmax(0,2fr)", render: (s) => <NameCell name={s.name} sub={s.blurb ?? undefined} /> },
    { key: "n", header: "Stocks", align: "right", num: true, render: (s) => fmtNum(s.metrics.stock_count) },
    { key: "ad", header: "Up / down · 1Y", align: "right", num: true, render: (s) => upDown(s.metrics.advancing, s.metrics.declining) },
    { key: "y1", header: "Avg return · 1Y", align: "right", num: true, render: (s) => pctCell(s.metrics.avg_return_1y) },
    { key: "mcap", header: "Market cap", align: "right", num: true, render: (s) => fmtCrCompact(s.metrics.market_cap_cr) },
    { key: "pe", header: "Median P/E", align: "right", num: true, render: (s) => fmtMultiple(s.metrics.median_pe) },
    {
      key: "idx", header: "Benchmark today", align: "right", num: true,
      render: (s) => <span title={s.benchmark_index ?? undefined}>{pctCell(s.metrics.index_pct_change)}</span>,
    },
  ];

  return (
    <>
      <ReadCard eyebrow="Sector read" testId="markets-sector-read">{sectorLine(ranked)}</ReadCard>

      {selected && <SectorPanel card={selected} onClose={() => setOpen(null)} />}

      <Section title={`Sectors · ${ranked.length}`} note="Open a row for the sector’s companies and commentary" flush>
        <div data-testid="markets-sectors">
          <DataTable
            columns={columns}
            rows={ranked}
            rowKey={(s) => s.slug}
            onRowClick={(s) => setOpen(s.slug === open ? null : s.slug)}
            minWidth={820}
          />
          <SourceLine
            testId="markets-sectors-source"
            asOf={asOf}
            note="Average return and up / down are over one year, across each sector’s stocks"
            style={{ padding: "10px 16px" }}
          />
        </div>
      </Section>
    </>
  );
}

/** One sector opened: its figures, largest companies and the commentary, as the endpoint returns them. */
function SectorPanel({ card, onClose }: { card: SectorCard; onClose: () => void }) {
  const q = useSectorDetail(card.slug);
  const held = useHeldKeys();

  const header = (
    <div className="flex flex-wrap items-start justify-between" style={{ gap: 12 }}>
      <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
        <span className="cp-eyebrow">Sector detail</span>
        <span style={{ fontFamily: "var(--display)", fontSize: 26, lineHeight: 1.15 }} data-testid="markets-sector-detail-name">{card.name}</span>
        {card.blurb && <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>{card.blurb}</span>}
      </div>
      <Btn variant="ghost" onClick={onClose} data-testid="markets-sector-detail-close" style={{ padding: "6px 10px", fontSize: 12 }}>Close ✕</Btn>
    </div>
  );

  let body: ReactNode;
  if (q.isPending) {
    body = <LoadingBlock label="Loading the sector" rows={4} />;
  } else if (q.isError) {
    body = <LoadError title="This sector didn’t load" error={q.error} onRetry={() => q.refetch()} />;
  } else if (!q.data.sector) {
    body = <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }} data-testid="markets-sector-detail-empty">This sector’s detail is not available yet.</span>;
  } else {
    body = <SectorBody sector={q.data.sector} heldFor={(c) => isHeld(held.data, c.symbol, c.name)} />;
  }

  return (
    <section className="cp-card flex min-w-0 flex-col" style={{ gap: 16, padding: "18px 18px" }} data-testid="markets-sector-detail">
      {header}
      {body}
      <AskLink query={`How is the ${card.name} sector doing, and which stocks are leading it?`} testId="markets-sector-ask">
        Ask Copilot about this sector ›
      </AskLink>
    </section>
  );
}

function SectorBody({ sector: s, heldFor }: { sector: SectorDetail; heldFor: (c: SectorTopCompany) => boolean }) {
  const { ask } = useCopilotShell();
  const m = s.metrics;
  const benchmark = s.benchmark_index ?? "Benchmark";

  const columns: Column<SectorTopCompany>[] = [
    {
      key: "company", header: "Company", width: "minmax(0,1.9fr)",
      render: (c) => <CompanyCell symbol={c.symbol} name={c.name} held={heldFor(c)} />,
    },
    { key: "mcap", header: "Market cap", align: "right", num: true, render: (c) => fmtCrCompact(c.market_cap_cr) },
    { key: "y1", header: "Return · 1Y", align: "right", num: true, render: (c) => pctCell(c.return_1y_pct) },
    { key: "pe", header: "P/E", align: "right", num: true, render: (c) => fmtMultiple(c.pe_ttm) },
  ];

  return (
    <>
      {s.headline && <span style={{ fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }} data-testid="markets-sector-detail-headline">{s.headline}</span>}

      <div data-testid="markets-sector-detail-tiles">
        <Tiles
          min={140}
          items={[
            { k: "Market cap", v: fmtCrCompact(m.market_cap_cr) },
            { k: "Median P/E", v: fmtMultiple(m.median_pe) },
            { k: "Median ROE", v: fmtPct(m.median_roe) },
            { k: "Stocks", v: fmtNum(m.stock_count), s: m.advancing == null && m.declining == null ? undefined : `${upDown(m.advancing, m.declining)} up / down over 1Y` },
            { k: "Avg return · 1Y", v: fmtPct(m.avg_return_1y, { signed: true, digits: 2 }), tone: signTone(m.avg_return_1y) },
            {
              k: `${benchmark} today`,
              v: fmtPct(m.index_pct_change, { signed: true, digits: 2 }),
              s: m.index_pe == null ? undefined : `${fmtMultiple(m.index_pe)} P/E`,
              tone: signTone(m.index_pct_change),
            },
          ]}
        />
      </div>

      <Section title="Largest companies by market cap" flush>
        <div data-testid="markets-sector-companies">
          <DataTable
            columns={columns}
            rows={s.top_companies}
            rowKey={(c) => c.symbol}
            onRowClick={(c) => ask(`Tell me about ${c.name}`)}
            minWidth={480}
            empty="The largest companies are not available for this sector right now."
          />
        </div>
      </Section>

      <Section title="Analyst read · AI commentary">
        {s.commentary_md ? (
          <div className="flex flex-col" style={{ gap: 12 }} data-testid="markets-sector-commentary">
            <div className="cp-prose min-w-0" style={{ fontSize: 14 }}><Markdown>{s.commentary_md}</Markdown></div>
            {s.commentary_disclaimer && <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{s.commentary_disclaimer}</span>}
          </div>
        ) : (
          <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-3)" }} data-testid="markets-sector-commentary-empty">
            {s.commentary_error === "llm_not_configured"
              ? "AI commentary is not switched on in this environment. The figures above are unaffected."
              : "AI commentary could not be written right now. The figures above are unaffected."}
          </span>
        )}
      </Section>

      <SourceLine testId="markets-sector-detail-source" source={s.sources} asOf={s.as_of_date} />
    </>
  );
}
