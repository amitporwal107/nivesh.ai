/**
 * Markets → Sector Analysis. One row per sector profile from
 * GET /api/markets/sectors (returns are the average of the sector's stocks, in percent).
 */
import { useSectorAnalyses } from "@/hooks/use-markets";
import type { SectorCard } from "@/services/contracts/markets.contract";
import { DataTable, EmptyBlock, LoadingBlock, Section, fmtNum, fmtPct, type Column } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel, fmtMultiple } from "./format";
import { LoadError, NameCell, ReadCard, Signed } from "./parts";

function pctCell(n: number | null | undefined) {
  return <Signed value={n}>{fmtPct(n, { signed: true, digits: 2 })}</Signed>;
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
  const q = useSectorAnalyses();
  const { ask } = useCopilotShell();

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

  const columns: Column<SectorCard>[] = [
    { key: "sector", header: "Sector", width: "minmax(0,1.7fr)", render: (s) => <NameCell name={s.name} /> },
    { key: "d1", header: "1D", align: "right", num: true, render: (s) => pctCell(s.metrics.avg_return_1d) },
    { key: "d20", header: "20D", align: "right", num: true, render: (s) => pctCell(s.metrics.avg_return_20d) },
    { key: "y1", header: "1Y", align: "right", num: true, render: (s) => pctCell(s.metrics.avg_return_1y) },
    { key: "pe", header: "Median P/E", align: "right", num: true, render: (s) => fmtMultiple(s.metrics.median_pe) },
    {
      key: "ad", header: "Up / down", align: "right", num: true,
      render: (s) => s.metrics.advancing == null && s.metrics.declining == null
        ? "—"
        : `${fmtNum(s.metrics.advancing ?? 0)} / ${fmtNum(s.metrics.declining ?? 0)}`,
    },
  ];

  return (
    <>
      <ReadCard eyebrow="Sector read" testId="markets-sector-read">{sectorLine(ranked)}</ReadCard>
      <Section
        title={`Sectors · ${ranked.length}`}
        note={`Average return of each sector’s stocks${asOf ? ` · as of ${dayLabel(asOf, { year: true })}` : ""}`}
        flush
      >
        <div data-testid="markets-sectors">
          <DataTable
            columns={columns}
            rows={ranked}
            rowKey={(s) => s.slug}
            onRowClick={(s) => ask(`How is the ${s.name} sector doing, and which stocks are leading it?`)}
            minWidth={620}
          />
        </div>
      </Section>
    </>
  );
}
