/**
 * Research → Stock: the blocks fed by ./data.
 *
 *   StockPrice     12 months of daily prices, the 52-week range and the 200-day average
 *   StockCard      the Copilot's research card (scores, valuation, technicals, risk, peers)
 *   StockBackdrop  today's market regime and how it leans for the stock's sector
 */
import { ChatWidget, type WidgetAction } from "@/components/chat/ChatWidget";
import { SafeWidget } from "@/components/shared/SafeWidget";
import { EmptyBlock, LoadingBlock, Section, Tiles, fmtPct, signTone } from "../../components/ui";
import { Flash } from "../../components/LiveBits";
import { useCopilotShell } from "../../lib/shell-context";
import { closeLabel, useLiveOverlay, flashOf } from "../../lib/useLiveQuotes";
import { dayLabel, fmtPrice, titleCase } from "../markets/format";
import { LoadError } from "../markets/parts";
import { usePriceHistory, useStockBackdrop, useStockCard } from "./data";
import { Locked, NotAvailable, orNA } from "./parts";
import { PriceChart, fmtShares } from "./PriceChart";

// ── price ────────────────────────────────────────────────────────────────

export function StockPrice({ symbol, name }: { symbol: string; name: string }) {
  const q = usePriceHistory(symbol);
  const live = useLiveOverlay(symbol, q.data?.kind === "ok" ? q.data.series.last.day : null);        // Kite, only while the feed is LIVE; otherwise the last end-of-day close below

  if (q.isPending) return <LoadingBlock label="Loading the price history" rows={5} />;
  if (q.isError) {
    return (
      <div data-testid="research-stock-price-error">
        <LoadError title="The price history didn’t load" error={q.error} onRetry={() => q.refetch()} />
      </div>
    );
  }
  if (q.data.kind === "locked") {
    return (
      <Locked
        testId="research-stock-price-locked"
        title="Price history is not switched on for this account"
        body={`Daily prices for ${name} are held by the data platform, but the price chart is only switched on for some accounts so far.`}
        needs={[
          "GET /api/research/chart-live/{symbol}/ohlcv answered 403: it sits behind the `charting` feature allowlist",
          "Either add the account to that allowlist or serve daily bars to every signed-in user from an open route",
        ]}
      />
    );
  }
  if (q.data.kind === "none") {
    return (
      <div data-testid="research-stock-price-empty">
        <EmptyBlock
          title={`No daily prices for ${symbol} yet`}
          body="The data platform has no trading sessions on record for this symbol, so there is no price, range or chart to show."
        />
      </div>
    );
  }

  const s = q.data.series;
  // "52-week" only when a full year of sessions is on record; otherwise name the first one.
  const since = dayLabel(s.points[0].day, { year: true });
  const highKey = s.fullYear ? "52-week high" : `High since ${since}`;
  const lowKey = s.fullYear ? "52-week low" : `Low since ${since}`;
  // The average needs 200 sessions behind it, so it can start part-way through the chart.
  const averageFrom = s.points.find((p) => p.avg200 != null)?.day;

  return (
    <Section
      title={s.fullYear ? "Price · last 12 months" : `Price · since ${since}`}
      note={`End of day · ${dayLabel(s.last.day, { year: true })} · adjusted for splits and bonuses`}
    >
      <div className="flex flex-col" style={{ gap: 16 }} data-testid="research-stock-price">
        <Tiles
          min={130}
          items={[
            {
              k: live ? (live.kind === "close" ? closeLabel(live) : "Live price") : "Last close",
              v: <span data-testid="research-stock-close" data-live={live ? "true" : undefined}><Flash value={flashOf(live)}>{fmtPrice(live ? live.ltp : s.last.close)}</Flash></span>,
              s: live && live.changePct != null
                ? <span data-testid="research-stock-day-change">{fmtPct(live.changePct, { signed: true, digits: 2 })} on the day · Kite</span>
                : s.dayChangePct != null
                ? <span data-testid="research-stock-day-change">{fmtPct(s.dayChangePct, { signed: true, digits: 2 })} on the day</span>
                : "Only one session on record",
            },
            {
              k: s.fullYear ? "12-month change" : `Change since ${since}`,
              v: <span data-testid="research-stock-year-change">{orNA(s.changePct, (n) => fmtPct(n, { signed: true }))}</span>,
              tone: signTone(s.changePct),
            },
            { k: highKey, v: <span data-testid="research-stock-high">{fmtPrice(s.high)}</span> },
            { k: lowKey, v: <span data-testid="research-stock-low">{fmtPrice(s.low)}</span> },
            {
              k: "200-day average",
              v: <span data-testid="research-stock-avg200">{orNA(s.last.avg200, fmtPrice)}</span>,
              s: s.last.avg200 == null
                ? "Needs 200 trading sessions"
                : s.last.close >= s.last.avg200 ? "Last close is above it" : "Last close is below it",
            },
            { k: "Volume", v: fmtShares(s.last.volume), s: "Shares traded, last session" },
          ]}
        />
        <PriceChart points={s.points} name={name} />
        {averageFrom && averageFrom !== s.points[0].day && (
          <span data-testid="research-stock-avg200-note" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            The 200-day average line starts on {dayLabel(averageFrom, { year: true })}: sessions before that do not have 200 sessions of price history behind them.
          </span>
        )}
        {s.partial && (
          <span data-testid="research-stock-price-partial" style={{ fontSize: 12, color: "var(--amber)" }}>
            Some sessions had incomplete prices and are left out of this chart.
          </span>
        )}
      </div>
    </Section>
  );
}

// ── the Copilot's research card ──────────────────────────────────────────

export function StockCard({ symbol, name }: { symbol: string; name: string }) {
  const { ask } = useCopilotShell();
  const q = useStockCard(symbol);
  const onAction = (a: WidgetAction) => { if (a.query) ask(a.query); };

  if (q.isPending) return <LoadingBlock label="Loading scores and technicals" rows={6} />;
  if (q.isError) {
    return (
      <div data-testid="research-stock-card-error">
        <LoadError title="Scores and technicals didn’t load" error={q.error} onRetry={() => q.refetch()} />
      </div>
    );
  }
  if (q.data.kind === "locked") {
    return (
      <Locked
        testId="research-stock-card-locked"
        title="Scores and technicals are not switched on for this account"
        body={`The Copilot’s research card for ${name} (quality score, valuation against its sector, technicals, risk and peers) is only switched on for some accounts so far. Asking the Copilot about ${name} shows the same card in the thread.`}
        needs={[
          "GET /api/move-odds/stocks/{symbol}/card answered 403: it sits behind the `move_odds` feature allowlist",
          "Either add the account to that allowlist or expose the same card to every signed-in user from an open route",
        ]}
      />
    );
  }
  if (q.data.kind === "none") {
    return (
      <div data-testid="research-stock-card-empty">
        <EmptyBlock
          title={`No scores for ${symbol} yet`}
          body="The data platform has no research on this symbol: no quality score, technicals or peer group to show."
        />
      </div>
    );
  }

  return (
    <div data-testid="research-stock-card" className="min-w-0">
      <SafeWidget name={`Research card · ${symbol}`}>
        <ChatWidget widget={q.data.widget} onAction={onAction} />
      </SafeWidget>
    </div>
  );
}

// ── market backdrop ──────────────────────────────────────────────────────

const BIAS: Record<string, string> = {
  FAVORABLE: "Favourable",
  NEUTRAL: "Neutral",
  UNFAVORABLE: "Unfavourable",
};

export function StockBackdrop({ symbol }: { symbol: string }) {
  const q = useStockBackdrop(symbol);

  if (q.isPending) return <LoadingBlock label="Loading the market backdrop" rows={2} />;
  if (q.isError) {
    return (
      <div data-testid="research-stock-backdrop-error">
        <LoadError title="The market backdrop didn’t load" error={q.error} onRetry={() => q.refetch()} />
      </div>
    );
  }

  const m = q.data.macro_state;
  if (!m.market && !m.inflation && !m.liquidity && !m.risk) {
    return (
      <div data-testid="research-stock-backdrop-empty">
        <EmptyBlock title="No market backdrop yet" body="Today’s market regime has not been computed, so there is nothing to set this stock against." />
      </div>
    );
  }

  const state = (v: string | null | undefined) => (v ? titleCase(v) : <NotAvailable />);
  const bias = q.data.sector_bias ? BIAS[q.data.sector_bias.toUpperCase()] ?? titleCase(q.data.sector_bias) : null;

  return (
    <Section title="Market backdrop" note="Today’s regime · the same for every stock">
      <div className="flex flex-col" style={{ gap: 14 }} data-testid="research-stock-backdrop">
        <Tiles
          min={130}
          items={[
            { k: "Market", v: state(m.market) },
            { k: "Inflation", v: state(m.inflation) },
            { k: "Liquidity", v: state(m.liquidity) },
            { k: "Risk level", v: state(m.risk) },
          ]}
        />
        <span data-testid="research-stock-backdrop-sector" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          {q.data.raw_sector
            ? <>Sector on record for {symbol}: <strong style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{q.data.raw_sector}</strong>. </>
            : <>No sector is on record for {symbol}, so the regime cannot be read for its sector. </>}
          {q.data.raw_sector && (bias
            ? <>How today’s regime leans for it: <strong style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{bias}</strong>{q.data.sector_rationale ? ` (${q.data.sector_rationale})` : ""}.</>
            : <>How today’s regime leans for it is not available.</>)}
        </span>
      </div>
    </Section>
  );
}
