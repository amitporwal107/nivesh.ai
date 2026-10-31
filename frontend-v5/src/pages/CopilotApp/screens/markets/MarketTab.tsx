/**
 * Markets → Market. Everything the market overview returns (GET
 * /api/markets/home): the index tape with its recent closes, sector moves,
 * breadth, the latest institutional cash flows, top movers (+ GET
 * /api/markets/movers?cap= for one cap segment), world indices, commodities and
 * headlines. The 52-week and most-active lists come from GET
 * /api/markets/explore, read when a list is first opened.
 */
import { Flash } from "../../components/LiveBits";
import { closeLabel, useLiveOverlay, flashOf } from "../../lib/useLiveQuotes";
import { useState } from "react";
import type { CapSegment } from "@/services/adapters/markets.adapter";
import type {
  ExploreRow, GlobalQuote, MarketBreadth, MarketIndex, MarketMover, MarketSector, MarketsHome,
} from "@/services/contracts/markets.contract";
import { StockIcon } from "../../components/EntityIcon";
import {
  Btn, DataTable, EmptyBlock, LoadingBlock, Pill, Section, Tiles, TONE_COLOR, fmtNum, fmtPct, signTone,
  type Column, type Tone,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { sentimentTone } from "./ArticlesTab";
import { dayLabel, fmtCr, fmtLevel, fmtPoints, fmtPrice, fmtShares } from "./format";
import { isHeld, useHeldKeys, useMarketLists, useMarketMovers, useMarketOverview, type HeldKeys } from "./hooks";
import {
  AskLink, CompanyCell, FilterChips, LoadError, NameCell, ReadCard, Signed, SourceLine, Sparkline, Stat,
} from "./parts";

type CapFilter = "all" | CapSegment;

const CAPS: { key: CapFilter; label: string }[] = [
  { key: "all", label: "All caps" },
  { key: "large", label: "Large cap" },
  { key: "mid", label: "Mid cap" },
  { key: "small", label: "Small cap" },
];

type ListKey = "high_52w" | "low_52w" | "most_active";

const LISTS: { key: ListKey; label: string }[] = [
  { key: "high_52w", label: "Near 52-week high" },
  { key: "low_52w", label: "Near 52-week low" },
  { key: "most_active", label: "Most active" },
];

/** One sentence about the session, written only from fields the endpoint returned. */
// ── live (Kite) overlays: only while the feed is LIVE; otherwise the end-of-day figures the route sent ──

function LivePriceCell({ symbol, price, eodDay }: { symbol: string; price: number | null; eodDay?: string | null }) {
  const q = useLiveOverlay(symbol, eodDay);
  return q ? <Flash value={flashOf(q)}>{fmtPrice(q.ltp)}</Flash> : <>{fmtPrice(price)}</>;
}

function LiveChgCell({ symbol, pct, testId, eodDay }: { symbol: string; pct: number | null; testId?: string; eodDay?: string | null }) {
  const q = useLiveOverlay(symbol, eodDay);
  const v = q && q.changePct != null ? q.changePct : pct;
  return <Signed value={v} testId={testId}>{fmtPct(v, { signed: true, digits: 2 })}</Signed>;
}

function IndexCard({ ix, eodDay }: { ix: MarketIndex; eodDay?: string | null }) {
  const q = useLiveOverlay(ix.name, ix.as_of?.slice(0, 10) ?? eodDay);          // the tile's own daily-bar day first
  const value = q ? q.ltp : ix.value;
  const change = q ? q.change : ix.change;
  const pct = q ? q.changePct : ix.change_pct;
  // A rising VIX is not a gain, so it stays neutral.
  const tone: Tone = ix.is_vix ? "ink" : signTone(pct);
  return (
    <div className="cp-card flex min-w-0 flex-col" data-live={q ? q.kind : undefined} style={{ gap: 6, padding: "14px 16px" }}>
      <span className="cp-eyebrow">{ix.name}</span>
      {q?.kind === "close" && <span data-testid="markets-index-close" className="cp-mono-note" style={{ fontSize: 9 }}>{closeLabel(q)}</span>}
      <span className="cp-num" style={{ fontSize: 22, color: TONE_COLOR[tone] }} data-testid="markets-index-value" data-index={ix.name}>
        <Flash value={flashOf(q)}>{fmtLevel(value)}</Flash>
      </span>
      <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>
        {!ix.is_vix && change != null && (
          <><span data-testid="markets-index-points" data-index={ix.name}>{fmtPoints(change)}</span>{" · "}</>
        )}
        <span data-testid="markets-index-change" data-index={ix.name}>{fmtPct(pct, { signed: true, digits: 2 })}</span>
      </span>
      <Sparkline values={ix.spark} tone={tone} testId="markets-index-spark" />
    </div>
  );
}

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

interface NamedSector {
  name: string;
  change_pct: number;
}

/** Sectors that carry a name, strongest first. */
function rankSectors(sectors: MarketSector[]): NamedSector[] {
  return sectors
    .flatMap((s) => (s.name ? [{ name: s.name, change_pct: s.change_pct }] : []))
    .sort((a, b) => b.change_pct - a.change_pct);
}

/** The other facts of the session, each from one field of the response. */
function tapeFacts(d: MarketsHome): string[] {
  const facts: string[] = [];
  const vix = d.indices.find((i) => i.is_vix);
  if (vix?.change_pct != null) {
    const trend = (vix.trend ?? "").toUpperCase();
    facts.push(`${vix.name} ${fmtPct(vix.change_pct, { signed: true, digits: 2 })}${trend === "FALLING" ? ", cooling" : trend === "RISING" ? ", rising" : ""}`);
  }
  const fii = d.fii_dii?.fii_net_cr;
  if (fii != null && fii !== 0) {
    facts.push(`FIIs were net ${fii > 0 ? "buyers" : "sellers"} in the cash market${d.fii_dii?.as_of ? ` on ${dayLabel(d.fii_dii.as_of)}` : ""}`);
  }
  const lead = rankSectors(d.sectors)[0];
  if (lead && lead.change_pct > 0) facts.push(`${lead.name} is the strongest sector at ${fmtPct(lead.change_pct, { signed: true, digits: 2 })}`);
  return facts;
}

function quoteValue(q: GlobalQuote): string {
  if (q.value == null) return "—";
  return q.unit && q.unit.includes("%") ? `${q.value.toFixed(2)}%` : fmtLevel(q.value);
}

export function MarketTab({ onOpenFlows }: { onOpenFlows?: () => void }) {
  const home = useMarketOverview();
  const held = useHeldKeys();
  const { mobile } = useCopilotShell();
  const [cap, setCap] = useState<CapFilter>("all");

  if (home.isPending) return <LoadingBlock label="Loading the market" rows={5} />;
  if (home.isError) {
    return <LoadError title="The market dashboard didn’t load" error={home.error} onRetry={() => home.refetch()} />;
  }

  const d = home.data;
  const hasAnything = d.indices.length > 0 || d.gainers.length > 0 || d.losers.length > 0
    || d.sectors.length > 0 || d.breadth.advances != null;
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
  const regions: Array<[string, GlobalQuote[]]> = [
    ["United States", d.global_indices.us],
    ["Europe", d.global_indices.europe],
    ["Asia–Pacific", d.global_indices.asia],
  ];
  const hasWorld = regions.some(([, quotes]) => quotes.length > 0);
  const sectors = rankSectors(d.sectors);

  return (
    <>
      <ReadCard
        testId="markets-read"
        eyebrow="Today’s tape"
        bullets={tapeFacts(d)}
        note={d.verdict_reason
          ? <span data-testid="markets-verdict">Rules-based read{d.verdict ? ` · ${d.verdict.toLowerCase()}` : ""}: {d.verdict_reason}</span>
          : undefined}
      >
        {tapeLine(d)}
      </ReadCard>

      {d.indices.length > 0 && (
        <div className="flex flex-col" style={{ gap: 8 }}>
          <div data-testid="markets-indices" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))", gap: 12 }}>
            {d.indices.map((ix) => <IndexCard key={ix.name} ix={ix} eodDay={d.as_of?.slice(0, 10) ?? null} />)}
          </div>
          <SourceLine
            testId="markets-overview-source"
            asOf={d.fetched_at ?? d.as_of}
            asOfLabel="updated"
            note={d.indices.some((ix) => ix.spark.length > 1) ? "The line in each tile is the recent daily closes" : undefined}
          />
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "minmax(0,1.35fr) minmax(0,1fr)", gap: 12, alignItems: "start" }}>
        <Section title={`Sector moves · ${fmtNum(sectors.length)}`} flush>
          <SectorBars sectors={sectors} />
        </Section>
        <Section
          title="Market breadth"
          note={d.breadth.advances != null && d.breadth.declines != null
            ? <span data-testid="markets-breadth">{fmtNum(d.breadth.advances)} advances · {fmtNum(d.breadth.declines)} declines</span>
            : undefined}
        >
          <Breadth breadth={d.breadth} />
        </Section>
      </div>

      <Section title="Institutional flows · cash market" note={d.fii_dii ? "Net for the latest session" : undefined}>
        {d.fii_dii ? (
          <div className="flex flex-col" style={{ gap: 12 }} data-testid="markets-flows-snapshot">
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 16 }}>
              <Stat label="FII net" tone={signTone(d.fii_dii.fii_net_cr)} value={fmtCr(d.fii_dii.fii_net_cr, { signed: true })} testId="markets-snapshot-fii" />
              <Stat label="DII net" tone={signTone(d.fii_dii.dii_net_cr)} value={fmtCr(d.fii_dii.dii_net_cr, { signed: true })} testId="markets-snapshot-dii" />
            </div>
            <div className="flex flex-wrap items-center justify-between" style={{ gap: "6px 12px" }}>
              <SourceLine testId="markets-snapshot-asof" asOf={d.fii_dii.as_of} quiet />
              {onOpenFlows && (
                <Btn variant="ghost" onClick={onOpenFlows} data-testid="markets-open-flows" style={{ padding: "6px 10px", fontSize: 12 }}>All sessions ›</Btn>
              )}
            </div>
          </div>
        ) : (
          <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }} data-testid="markets-flows-snapshot-empty">
            The latest FII and DII cash figures are not available right now.
          </span>
        )}
      </Section>

      <Section title="Top movers" flush>
        <div style={{ padding: "12px 16px" }}>
          <FilterChips items={CAPS} value={cap} onChange={setCap} label="Market-cap segment" idPrefix="markets-movers-cap" />
        </div>
        {cap === "all"
          ? <MoversTable gainers={d.gainers} losers={d.losers} asOf={d.movers_as_of} held={held.data} />
          : <CapMovers cap={cap} held={held.data} />}
      </Section>

      <MarketLists held={held.data} />

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

      {hasWorld && (
        <div className="flex flex-col" style={{ gap: 14 }} data-testid="markets-world-indices">
          {regions.map(([label, quotes]) => quotes.length > 0 && (
            <div key={label} className="flex flex-col" style={{ gap: 8 }}>
              <span className="cp-eyebrow">World indices · {label}</span>
              <QuoteTiles quotes={quotes} />
            </div>
          ))}
        </div>
      )}

      {d.commodities.length > 0 && (
        <div className="flex flex-col" style={{ gap: 8 }} data-testid="markets-commodities">
          <span className="cp-eyebrow">Commodities and energy</span>
          <QuoteTiles quotes={d.commodities} />
        </div>
      )}

      {d.news.length > 0 && (
        <Section title="Market news" note={`${fmtNum(d.news.length)} recent company announcements`} flush>
          <div data-testid="markets-news">
            {d.news.map((n, i) => (
              <div
                key={`${n.symbol ?? "x"}-${i}`}
                data-testid="markets-news-item"
                className="flex items-start"
                style={{ gap: 12, padding: "12px 16px", borderTop: i ? "1px solid var(--cp-line)" : undefined }}
              >
                {n.symbol && <StockIcon symbol={n.symbol} size={26} />}
                <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
                  <span style={{ fontSize: 13.5, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{n.title}</span>
                  <span className="flex flex-wrap items-center" style={{ gap: "6px 10px" }}>
                    <Pill tone={sentimentTone(n.sentiment)}>{n.category}</Pill>
                    {n.when && <span className="cp-mono-note">{dayLabel(n.when, { year: true })}</span>}
                    <AskLink query={`What does this announcement mean for shareholders? “${n.title}”`}>Ask Copilot about this ›</AskLink>
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}
    </>
  );
}

/** Each sector's change as a bar from a shared centre line; the figure sits beside it. */
function SectorBars({ sectors }: { sectors: NamedSector[] }) {
  const { isAdmin } = useCopilotShell();
  if (sectors.length === 0) {
    return <div style={{ padding: 16, fontSize: 13, color: "var(--cp-ink-3)" }} data-testid="markets-sector-bars-empty">Sector moves are not available right now.</div>;
  }
  const max = Math.max(0.01, ...sectors.map((s) => Math.abs(s.change_pct)));
  return (
    <div data-testid="markets-sector-bars">
      {sectors.map((s, i) => {
        const up = s.change_pct >= 0;
        const width = `${(Math.abs(s.change_pct) / max) * 50}%`;
        return (
          <div
            key={s.name}
            data-testid="markets-sector-bar"
            className="grid items-center"
            style={{ gridTemplateColumns: "minmax(0,1fr) minmax(56px,1.3fr) 64px", gap: 12, padding: "9px 16px", borderTop: i ? "1px solid var(--cp-line)" : undefined, fontSize: 13 }}
          >
            <span style={{ color: "var(--cp-ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>
            <span className="relative" style={{ height: 8, borderRadius: 4, background: "var(--bg-3)" }} aria-hidden>
              <span style={{ position: "absolute", left: "50%", top: -3, bottom: -3, width: 1, background: "var(--line-3)" }} />
              <span style={{ position: "absolute", top: 0, height: "100%", borderRadius: 4, width, background: up ? "var(--mint)" : "var(--cp-danger)", ...(up ? { left: "50%" } : { right: "50%" }) }} />
            </span>
            <span style={{ textAlign: "right" }}>
              <Signed value={s.change_pct}>{fmtPct(s.change_pct, { signed: true, digits: 2 })}</Signed>
            </span>
          </div>
        );
      })}
      {isAdmin && (
        <div className="cp-mono-note" style={{ padding: "10px 16px", borderTop: "1px solid var(--cp-line)" }} title="Shown to admins only" data-testid="markets-sector-bars-period">
          The response does not say which period this change covers
        </div>
      )}
    </div>
  );
}

/** Advances against declines as one bar, then the structural breadth figures. */
function Breadth({ breadth: b }: { breadth: MarketBreadth }) {
  const counted = b.advances != null && b.declines != null;
  const structural = b.pct_above_20ema != null || b.pct_above_50ema != null || b.new_52w_highs != null || b.new_52w_lows != null;
  if (!counted && !structural) {
    return <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }} data-testid="markets-breadth-empty">Breadth figures are not available right now.</span>;
  }
  const adv = b.advances ?? 0;
  const dec = b.declines ?? 0;
  const flat = b.unchanged ?? 0;
  const total = adv + dec + flat || 1;
  // More than half of all stocks above an average is the stronger side.
  const aboveTone = (pct: number | null | undefined): Tone => (pct == null ? "ink" : signTone(pct - 50));
  return (
    <div className="flex flex-col" style={{ gap: 14 }} data-testid="markets-breadth-block">
      {counted && (
        <div className="flex flex-col" style={{ gap: 10 }}>
          <div
            role="img"
            aria-label={`${fmtNum(adv)} advances, ${fmtNum(dec)} declines, ${fmtNum(flat)} unchanged`}
            className="flex overflow-hidden"
            style={{ height: 8, borderRadius: 4, background: "var(--bg-3)" }}
          >
            <span style={{ width: `${(adv / total) * 100}%`, background: "var(--mint)" }} />
            <span style={{ width: `${(flat / total) * 100}%`, background: "var(--line-3)" }} />
            <span style={{ width: `${(dec / total) * 100}%`, background: "var(--cp-danger)" }} />
          </div>
          <div className="grid" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 12 }}>
            <Stat label="Advances" tone="mint" value={fmtNum(b.advances)} />
            <Stat label="Unchanged" value={fmtNum(b.unchanged)} testId="markets-breadth-unchanged" />
            <Stat label="Declines" tone="danger" value={fmtNum(b.declines)} />
          </div>
        </div>
      )}
      {structural && (
        <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 12, paddingTop: counted ? 12 : 0, borderTop: counted ? "1px solid var(--cp-line)" : undefined }}>
          <Stat label="Above their 20-day average" tone={aboveTone(b.pct_above_20ema)} value={fmtPct(b.pct_above_20ema, { digits: 0 })} testId="markets-breadth-above20" />
          <Stat label="Above their 50-day average" tone={aboveTone(b.pct_above_50ema)} value={fmtPct(b.pct_above_50ema, { digits: 0 })} testId="markets-breadth-above50" />
          <Stat label="At a 52-week high" tone="mint" value={fmtNum(b.new_52w_highs)} testId="markets-breadth-highs" />
          <Stat label="At a 52-week low" tone="danger" value={fmtNum(b.new_52w_lows)} testId="markets-breadth-lows" />
        </div>
      )}
      {b.universe != null && <span className="cp-mono-note">Counted across {fmtNum(b.universe)} stocks</span>}
    </div>
  );
}

function QuoteTiles({ quotes }: { quotes: GlobalQuote[] }) {
  return (
    <Tiles
      min={140}
      items={quotes.map((q) => ({
        k: [q.name, q.unit ?? q.sub].filter(Boolean).join(" · "),
        v: quoteValue(q),
        s: <Signed value={q.change_pct}>{fmtPct(q.change_pct, { signed: true, digits: 2 })}</Signed>,
      }))}
    />
  );
}

function CapMovers({ cap, held }: { cap: CapSegment; held: HeldKeys | undefined }) {
  const q = useMarketMovers(cap);
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
      render: (m) => <CompanyCell symbol={m.symbol} name={m.name} held={isHeld(held, m.symbol, m.name)} />,
    },
    { key: "price", header: "Price", align: "right", num: true, render: (m) => <LivePriceCell symbol={m.symbol} price={m.price} eodDay={asOf?.slice(0, 10) ?? null} /> },
    {
      key: "chg", header: "Change", align: "right", num: true,
      render: (m) => <LiveChgCell symbol={m.symbol} pct={m.change_pct} testId="markets-mover-change" eodDay={asOf?.slice(0, 10) ?? null} />,
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
      <SourceLine
        testId="markets-movers-asof"
        asOf={asOf}
        asOfLabel="prices as of"
        note={rows.length > 0 ? "gainers first, then losers" : undefined}
        quiet
        style={{ padding: "10px 16px" }}
      />
    </div>
  );
}

/** Near 52-week high / low and most-active lists. Nothing is requested until a list is opened. */
function MarketLists({ held }: { held: HeldKeys | undefined }) {
  const { ask } = useCopilotShell();
  const [list, setList] = useState<ListKey | "">("");
  const q = useMarketLists(list !== "");

  const detail: Column<ExploreRow> = list === "most_active"
    ? { key: "detail", header: "Shares traded", align: "right", num: true, render: (r) => fmtShares(r.volume) }
    : list === "high_52w"
      ? { key: "detail", header: "From the high", align: "right", num: true, render: (r) => fmtPct(r.from_high_pct, { signed: true }) }
      : { key: "detail", header: "Above the low", align: "right", num: true, render: (r) => fmtPct(r.from_low_pct, { signed: true }) };
  const columns: Column<ExploreRow>[] = [
    {
      key: "stock", header: "Stock", width: "minmax(0,1.7fr)",
      render: (r) => <CompanyCell symbol={r.symbol} name={r.name} held={isHeld(held, r.symbol, r.name)} />,
    },
    { key: "price", header: "Price", align: "right", num: true, render: (r) => <LivePriceCell symbol={r.symbol} price={r.price} /> },
    {
      key: "chg", header: "Change", align: "right", num: true,
      render: (r) => <LiveChgCell symbol={r.symbol} pct={r.change_pct} />,
    },
    detail,
  ];

  return (
    <Section title="Market lists" flush>
      <div style={{ padding: "12px 16px" }}>
        <FilterChips<ListKey | "">
          items={LISTS}
          value={list}
          onChange={(k) => setList(k === list ? "" : k)}
          label="Market list"
          idPrefix="markets-list"
        />
      </div>
      {list === "" ? (
        <div style={{ padding: "0 16px 16px", fontSize: 13, color: "var(--cp-ink-3)" }}>
          Pick a list to see the stocks nearest their 52-week high or low, or the most traded today.
        </div>
      ) : q.isPending ? (
        <div style={{ padding: "0 16px 16px" }}><LoadingBlock label="Loading the list" /></div>
      ) : q.isError ? (
        <div style={{ padding: "0 16px 16px" }}>
          <LoadError title="This list didn’t load" error={q.error} onRetry={() => q.refetch()} />
        </div>
      ) : (
        <div data-testid="markets-list-table">
          <DataTable
            columns={columns}
            rows={q.data[list]}
            rowKey={(r) => r.symbol}
            onRowClick={(r) => ask(`Tell me about ${r.name}`)}
            minWidth={460}
            empty="This list is empty right now."
          />
          <SourceLine
            testId="markets-list-source"
            asOf={q.data.fetched_at}
            asOfLabel="updated"
            note={`Stocks of the ${q.data.universe}`}
            style={{ padding: "10px 16px" }}
          />
        </div>
      )}
    </Section>
  );
}
