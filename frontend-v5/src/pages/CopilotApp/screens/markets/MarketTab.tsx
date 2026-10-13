/**
 * Markets → Market. Index tape, top movers and global cues from
 * GET /api/markets/home (+ GET /api/markets/movers?cap= for one cap segment).
 */
import { useState } from "react";
import { useMarketsHome, useMarketsMovers } from "@/hooks/use-markets";
import type { CapSegment } from "@/services/adapters/markets.adapter";
import type { GlobalQuote, MarketMover, MarketsHome } from "@/services/contracts/markets.contract";
import {
  DataTable, EmptyBlock, LoadingBlock, Section, Tiles, fmtNum, fmtPct, signTone,
  type Column,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel, fmtLevel, fmtPrice } from "./format";
import { isHeld, useHeldKeys, type HeldKeys } from "./hooks";
import { FilterChips, LoadError, NameCell, ReadCard, Signed } from "./parts";

type CapFilter = "all" | CapSegment;

const CAPS: { key: CapFilter; label: string }[] = [
  { key: "all", label: "All caps" },
  { key: "large", label: "Large cap" },
  { key: "mid", label: "Mid cap" },
  { key: "small", label: "Small cap" },
];

/** One sentence about the session, written only from fields the endpoint returned. */
function tapeLine(d: MarketsHome): string {
  // Exact name: a loose match would also pick up "Nifty 500".
  const nifty = d.indices.find((i) => i.name.trim().toLowerCase() === "nifty 50");
  const pct = nifty?.change_pct ?? null;
  const { advances, declines } = d.breadth;
  const tone = d.breadth.tone.toUpperCase();
  const counts = advances != null && declines != null
    ? `${fmtNum(advances)} advances against ${fmtNum(declines)} declines`
    : "";
  if (pct == null) {
    return counts ? `Across the market there were ${counts}.` : "Index levels are below; the day’s direction is not available yet.";
  }
  const direction = pct > 0.15 ? "higher" : pct < -0.15 ? "lower" : "little changed";
  const verb = d.market_state === "open" ? "are trading" : "closed";
  const breadth = tone === "POSITIVE" ? ", with breadth positive" : tone === "NEGATIVE" ? ", with breadth weak" : counts ? ", with breadth mixed" : "";
  const detail = `The Nifty 50 is ${fmtPct(pct, { signed: true, digits: 2 })}${counts ? `, on ${counts}` : ""}.`;
  return `Markets ${verb} ${direction}${breadth}. ${detail}`;
}

function quoteValue(q: GlobalQuote): string {
  if (q.value == null) return "—";
  return q.unit && q.unit.includes("%") ? `${q.value.toFixed(2)}%` : fmtLevel(q.value);
}

export function MarketTab() {
  const home = useMarketsHome();
  const held = useHeldKeys();
  const [cap, setCap] = useState<CapFilter>("all");

  if (home.isPending) return <LoadingBlock label="Loading the market" rows={5} />;
  if (home.isError) {
    return <LoadError title="The market dashboard didn’t load" error={home.error} onRetry={() => home.refetch()} />;
  }

  const d = home.data;
  const hasAnything = d.indices.length > 0 || d.gainers.length > 0 || d.losers.length > 0 || d.breadth.advances != null;
  if (!hasAnything) {
    return (
      <EmptyBlock
        title="Market data is warming up"
        body="Indices, breadth and movers are not available right now. This screen refreshes on its own every minute."
      />
    );
  }

  const cueColumns: Column<GlobalQuote>[] = [
    { key: "name", header: "Market", width: "minmax(0,1.7fr)", render: (q) => <NameCell name={q.name} sub={q.sub ?? undefined} /> },
    { key: "last", header: "Last", align: "right", num: true, render: (q) => quoteValue(q) },
    {
      key: "chg", header: "Change", align: "right", num: true,
      render: (q) => <Signed value={q.change_pct}>{fmtPct(q.change_pct, { signed: true, digits: 2 })}</Signed>,
    },
  ];

  return (
    <>
      <ReadCard
        testId="markets-read"
        eyebrow="Today’s tape"
        note={d.verdict_reason
          ? <span data-testid="markets-verdict">Rules-based read{d.verdict ? ` · ${d.verdict.toLowerCase()}` : ""}: {d.verdict_reason}</span>
          : undefined}
      >
        {tapeLine(d)}
      </ReadCard>

      {d.indices.length > 0 && (
        <div data-testid="markets-indices">
          <Tiles
            min={140}
            items={d.indices.map((ix) => ({
              k: ix.name,
              v: <span data-testid="markets-index-value" data-index={ix.name}>{fmtLevel(ix.value)}</span>,
              s: <span data-testid="markets-index-change" data-index={ix.name}>{fmtPct(ix.change_pct, { signed: true, digits: 2 })}</span>,
              // A rising VIX is not a gain, so it stays neutral.
              tone: ix.is_vix ? "ink" : signTone(ix.change_pct),
            }))}
          />
        </div>
      )}

      <Section
        title="Top movers"
        note={d.breadth.advances != null && d.breadth.declines != null
          ? <span data-testid="markets-breadth">{fmtNum(d.breadth.advances)} advances · {fmtNum(d.breadth.declines)} declines</span>
          : undefined}
        flush
      >
        <div style={{ padding: "12px 16px" }}>
          <FilterChips items={CAPS} value={cap} onChange={setCap} label="Market-cap segment" idPrefix="markets-movers-cap" />
        </div>
        {cap === "all"
          ? <MoversTable gainers={d.gainers} losers={d.losers} asOf={d.movers_as_of} held={held.data} />
          : <CapMovers cap={cap} held={held.data} />}
      </Section>

      <Section title="Global cues" flush>
        <div data-testid="markets-global-cues">
          <DataTable
            columns={cueColumns}
            rows={d.global_cues}
            rowKey={(q) => q.name}
            minWidth={320}
            empty="Global quotes are not available right now."
          />
        </div>
      </Section>
    </>
  );
}

function CapMovers({ cap, held }: { cap: CapSegment; held: HeldKeys | undefined }) {
  const q = useMarketsMovers(cap);
  if (q.isPending) return <div style={{ padding: "0 16px 16px" }}><LoadingBlock label="Loading movers" /></div>;
  if (q.isError) {
    return (
      <div style={{ padding: "0 16px 16px" }}>
        <LoadError title="Movers for this segment didn’t load" error={q.error} onRetry={() => q.refetch()} />
      </div>
    );
  }
  return <MoversTable gainers={q.data.gainers} losers={q.data.losers} asOf={q.data.as_of} held={held} />;
}

function MoversTable({ gainers, losers, asOf, held }: {
  gainers: MarketMover[];
  losers: MarketMover[];
  asOf?: string | null;
  held: HeldKeys | undefined;
}) {
  const { ask } = useCopilotShell();
  const rows = [...gainers, ...losers];
  const columns: Column<MarketMover>[] = [
    {
      key: "stock", header: "Stock", width: "minmax(0,1.7fr)",
      render: (m) => <NameCell name={m.name} sub={m.symbol} held={isHeld(held, m.symbol, m.name)} />,
    },
    { key: "price", header: "Price", align: "right", num: true, render: (m) => fmtPrice(m.price) },
    {
      key: "chg", header: "Change", align: "right", num: true,
      render: (m) => <Signed value={m.change_pct} testId="markets-mover-change">{fmtPct(m.change_pct, { signed: true, digits: 2 })}</Signed>,
    },
  ];
  return (
    <div data-testid="markets-movers">
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(m, i) => `${m.symbol}-${i}`}
        onRowClick={(m) => ask(`Tell me about ${m.name}`)}
        minWidth={340}
        empty="No movers are available for this segment right now."
      />
      {asOf && rows.length > 0 && (
        <div className="cp-mono-note" style={{ padding: "10px 16px" }} data-testid="markets-movers-asof">
          Prices as of {dayLabel(asOf, { year: true })} · gainers first, then losers
        </div>
      )}
    </div>
  );
}
