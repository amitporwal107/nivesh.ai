/**
 * F&O analyser card on the Trader desk. Design: NVIndex.dc.html.
 *
 * From GET /api/markets/home (useMarketsHome): the index quote, India VIX,
 * market breadth and the rules-based market read.
 *
 * From the end-of-day NSE F&O bhavcopy (trading/fno.ts), each with its own
 * as-of date:
 *   futures price and basis, nearest expiry   GET /api/fno/{symbol}/futures
 *   put-call ratio, max pain, the strikes     GET /api/fno/{symbol}/expiries
 *   with the most call and put open interest, GET /api/fno/{symbol}/chain
 *   open interest by strike
 *
 * Still not connected: at-the-money IV and the expected move (the data has no
 * implied volatility), the stocks that moved the index and daily trend
 * signals. They are listed as not connected instead of being drawn.
 */
import { useState, type ReactNode } from "react";
import { useMarketsHome } from "@/hooks/use-markets";
import { AskChips, Btn, EmptyBlock, LoadingBlock, NotConnected, TONE_COLOR, fmtNum, fmtPct, relTime, signTone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { ChainGate, OiRows } from "./OptionChainViews";
import { fmtLevel } from "./PayoffResult";
import { FNO_INDICES, fnoSymbolForIndex, nearestFuture, useFnoFutures, useOptionChain, type FnoChain } from "./fno";
import { Choices, Labeled, QueryProblem, fmtDay, fmtSigned } from "./parts";

/** Index names (as /api/markets/home spells them) that have index derivatives in the design. */
export const FNO_INDEX_NAMES: string[] = FNO_INDICES.map((i) => i.indexName);

const NEEDS = [
  "Implied volatility per strike, for at-the-money IV. The end-of-day F&O data has closing prices and open interest but no IV; it needs an IV feed, or an agreed and validated model to derive IV from the closing prices.",
  "The expected move to expiry. The design takes it from the at-the-money straddle price, which the end-of-day chain does carry, but it is a model figure and its “two-thirds of expiries” claim has to be validated before it is shown.",
  "Index open, high, low and daily history, for pivots, the previous day’s range, moving averages, RSI and ADX.",
  "Index constituents with weights, for the points each stock added or took away.",
];

interface Tile {
  k: string;
  v: ReactNode;
  s: ReactNode;
  testId?: string;
}

function TileGrid({ tiles }: { tiles: Tile[] }) {
  return (
    <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 8 }}>
      {tiles.map((t) => (
        <div key={t.k} className="flex flex-col" style={{ gap: 3, padding: "12px 14px", borderRadius: 10, background: "var(--bg-2)" }}>
          <span className="cp-eyebrow">{t.k}</span>
          <span data-testid={t.testId} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 21 }}>{t.v}</span>
          <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{t.s}</span>
        </div>
      ))}
    </div>
  );
}

// ── end-of-day futures ───────────────────────────────────────────────────

function FuturesBlock({ symbol }: { symbol: string }) {
  const q = useFnoFutures(symbol);
  let note: ReactNode = "End-of-day data";
  let body: ReactNode;
  if (q.isPending) {
    body = <LoadingBlock label={`Loading ${symbol} futures`} rows={2} />;
  } else if (q.isError) {
    body = <QueryProblem what="Futures data" error={q.error} onRetry={() => q.refetch()} />;
  } else if (q.data.kind === "none") {
    body = <EmptyBlock title={q.data.message} body="The end-of-day F&O file has no contracts for it." />;
  } else {
    const f = q.data.data;
    const near = nearestFuture(f);
    note = <span data-testid="fno-futures-asof">End-of-day data · as of {fmtDay(f.as_of)}</span>;
    if (!near) {
      body = <EmptyBlock title={`No ${symbol} futures in the end-of-day file`} body={`The file for ${fmtDay(f.as_of)} lists no futures contract for it.`} />;
    } else {
      const side = near.basis == null ? null : near.basis > 0 ? "Premium to" : near.basis < 0 ? "Discount to" : "Level with";
      body = (
        <TileGrid
          tiles={[
            { k: `Futures · ${fmtDay(near.expiry)}`, v: near.settle == null ? "—" : fmtNum(near.settle, 2), s: "Settlement price, nearest expiry", testId: "fno-futures-price" },
            {
              k: "Basis",
              v: fmtSigned(near.basis),
              s: side == null ? "Needs a settlement price and a spot" : <>{side} the end-of-day spot of <span data-testid="fno-futures-spot">{fmtNum(f.spot, 2)}</span></>,
              testId: "fno-basis",
            },
          ]}
        />
      );
    }
  }
  return <Labeled testId="fno-futures" title={`${symbol} futures`} note={note}>{body}</Labeled>;
}

// ── end-of-day options ───────────────────────────────────────────────────

function OptionsSummary({ chain }: { chain: FnoChain }) {
  const { go } = useCopilotShell();
  const s = chain.summary;
  const expiry = fmtDay(s.expiry);
  const levels: Array<{ k: string; v: string; at: number; testId: string; spot?: boolean }> = [];
  if (s.max_put_oi) levels.push({ k: "Highest put OI", v: fmtLevel(s.max_put_oi.strike), at: s.max_put_oi.strike, testId: "fno-top-put-oi" });
  if (s.max_pain != null) levels.push({ k: "Max pain", v: fmtLevel(s.max_pain), at: s.max_pain, testId: "fno-level-max-pain" });
  if (s.spot != null) levels.push({ k: "End-of-day spot", v: fmtNum(s.spot, 2), at: s.spot, testId: "fno-eod-spot", spot: true });
  if (s.max_call_oi) levels.push({ k: "Highest call OI", v: fmtLevel(s.max_call_oi.strike), at: s.max_call_oi.strike, testId: "fno-top-call-oi" });
  // Ascending, so the chips read from the lowest level to the highest with the spot in its place.
  levels.sort((a, b) => a.at - b.at);

  return (
    <div className="flex flex-col" style={{ gap: 12 }}>
      <TileGrid
        tiles={[
          { k: "Put-call ratio", v: s.pcr == null ? "—" : fmtNum(s.pcr, 2), s: "Put OI ÷ call OI, all strikes", testId: "fno-pcr" },
          { k: "Max pain", v: s.max_pain == null ? "—" : fmtLevel(s.max_pain), s: `Strike · ${expiry} expiry`, testId: "fno-max-pain" },
        ]}
      />
      {levels.length > 0 && (
        <div data-testid="fno-key-levels" className="flex flex-col" style={{ gap: 6 }}>
          <span className="cp-eyebrow">Open-interest levels · not price targets</span>
          <div className="flex flex-wrap" style={{ gap: 6 }}>
            {levels.map((l) => (
              <span key={l.k} className="cp-num" style={{ padding: "3px 8px", borderRadius: 6, border: "1px solid var(--cp-line)", fontSize: 10, color: "var(--cp-ink-3)", background: l.spot ? "var(--bg-2)" : undefined }}>
                {l.k} <span data-testid={l.testId} style={{ color: "var(--cp-ink)" }}>{l.v}</span>
              </span>
            ))}
          </div>
          <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            Where the most call and put open interest sat at the close, and the max-pain strike. They describe positioning on {fmtDay(s.as_of)}; they are not support, resistance or targets.
          </span>
        </div>
      )}
      <div className="flex flex-col" style={{ gap: 6, padding: "12px 14px", borderRadius: 12, border: "1px solid var(--cp-line)" }}>
        <div className="flex flex-wrap justify-between" style={{ gap: 8 }}>
          <span className="cp-eyebrow">Open interest by strike</span>
          <span className="cp-num flex" style={{ gap: 10, fontSize: 10 }}>
            <span style={{ color: "var(--cp-danger)" }}>● CALLS</span>
            <span style={{ color: "var(--mint)" }}>● PUTS</span>
          </span>
        </div>
        <OiRows chain={chain} each={4} testId="fno-oi-by-strike" />
      </div>
      <div><Btn data-testid="fno-open-optlab" onClick={() => go("tool/optlab")}>Full chain in the options lab</Btn></div>
    </div>
  );
}

function OptionsBlock({ symbol }: { symbol: string }) {
  const { state } = useOptionChain(symbol, null);
  const note = state.status === "ok"
    ? <span data-testid="fno-options-asof">{fmtDay(state.chain.summary.expiry)} expiry · end-of-day data · as of {fmtDay(state.chain.summary.as_of)}</span>
    : "End-of-day data";
  return (
    <Labeled testId="fno-options" title={`${symbol} options`} note={note}>
      <ChainGate state={state} what="Options data" testId="fno-options">
        {(chain) => <OptionsSummary chain={chain} />}
      </ChainGate>
    </Labeled>
  );
}

// ── card ─────────────────────────────────────────────────────────────────

export function FnoAnalyser() {
  const { mobile } = useCopilotShell();
  const home = useMarketsHome();
  const [picked, setPicked] = useState<string | null>(null);

  if (home.isPending) {
    return <Labeled title="F&O analyser"><LoadingBlock label="Loading index quotes" rows={4} /></Labeled>;
  }
  if (home.isError) {
    return <Labeled title="F&O analyser"><QueryProblem what="The index quote" error={home.error} onRetry={() => home.refetch()} /></Labeled>;
  }

  const d = home.data;
  const indices = d.indices.filter((i) => !i.is_vix && i.value != null && FNO_INDEX_NAMES.includes(i.name));
  if (!indices.length) {
    return (
      <Labeled title="F&O analyser">
        <EmptyBlock
          title="No index quote right now"
          body="The markets feed returned no Nifty 50 or Nifty Bank value, so there is nothing to show here yet."
          action={<Btn onClick={() => home.refetch()}>Try again</Btn>}
        />
      </Labeled>
    );
  }

  const idx = indices.find((i) => i.name === picked) ?? indices[0];
  const symbol = fnoSymbolForIndex(idx.name);
  const vix = d.indices.find((i) => i.is_vix && i.value != null);
  const prevClose = idx.value != null && idx.change != null ? idx.value - idx.change : null;
  const b = d.breadth;
  const tone = TONE_COLOR[signTone(idx.change_pct)];

  const tiles: Tile[] = [];
  if (vix?.value != null) {
    tiles.push({ k: "India VIX", v: fmtNum(vix.value, 2), s: vix.change_pct != null ? `${fmtPct(vix.change_pct, { signed: true, digits: 2 })} today` : "Volatility index", testId: "fno-vix" });
  }
  if (b.advances != null && b.declines != null) {
    tiles.push({ k: "Advancing / declining", v: `${fmtNum(b.advances)} / ${fmtNum(b.declines)}`, s: b.universe != null ? `Of ${fmtNum(b.universe)} stocks` : "Stocks", testId: "fno-breadth" });
  }
  if (b.pct_above_20ema != null) {
    tiles.push({ k: "Above 20-day EMA", v: fmtPct(b.pct_above_20ema), s: "Share of stocks · end of day" });
  }
  if (b.new_52w_highs != null && b.new_52w_lows != null) {
    tiles.push({ k: "52-week highs / lows", v: `${fmtNum(b.new_52w_highs)} / ${fmtNum(b.new_52w_lows)}`, s: "End of day" });
  }

  const asks: Array<{ label: string; query: string }> = [
    { label: `How would a ${idx.name} iron condor work?`, query: `How would I structure a ${idx.name} iron condor for the nearest expiry, and what are its risks?` },
    { label: `What would a 2% fall in ${idx.name} do to my positions?`, query: `What would a 2% fall in ${idx.name} do to my positions?` },
  ];
  if (vix?.value != null) {
    asks.splice(1, 0, {
      label: `Backtest ${idx.name} after VIX closes above ${fmtNum(vix.value, 2)}`,
      query: `Backtest ${idx.name} over the next 5 sessions after India VIX closes above ${fmtNum(vix.value, 2)}`,
    });
  }

  return (
    <section data-testid="fno-analyser" className="cp-card-raised flex flex-col min-w-0" style={{ gap: 16, padding: mobile ? 14 : 18, borderColor: "var(--line-2)" }}>
      <div className="flex flex-wrap items-start justify-between" style={{ gap: 12 }}>
        <div className="flex flex-col min-w-0" style={{ gap: 6 }}>
          <span className="cp-eyebrow">
            F&amp;O analyser · Index · {d.market_state === "open" ? "market open" : "market closed"}
            {d.fetched_at && relTime(d.fetched_at) ? ` · quote ${relTime(d.fetched_at)}` : ""}
          </span>
          <div className="flex flex-wrap items-baseline" style={{ gap: "4px 12px" }}>
            <span data-testid="fno-index-name" style={{ fontFamily: "var(--display)", fontSize: mobile ? 24 : 30 }}>{idx.name}</span>
            <span data-testid="fno-spot" className="cp-metric" style={mobile ? { fontSize: 26 } : undefined}>{fmtNum(idx.value, 2)}</span>
            <span data-testid="fno-change" className="cp-num" style={{ fontSize: 12, color: tone }}>
              {fmtSigned(idx.change)} · {fmtPct(idx.change_pct, { signed: true, digits: 2 })}
            </span>
          </div>
          {prevClose != null && (
            <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>Prev close {fmtNum(prevClose, 2)}</span>
          )}
        </div>
        {indices.length > 1 && (
          <Choices label="Index" testId="fno-index" value={idx.name} onChange={setPicked} options={indices.map((i) => ({ value: i.name, label: i.name }))} />
        )}
      </div>

      {d.verdict && d.verdict_reason && (
        <div className="flex flex-col" style={{ gap: 6, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--mint-line)", background: "var(--mint-soft)" }}>
          <span className="cp-eyebrow">Market regime · rules-based, from breadth and macro risk · {d.verdict}</span>
          <span data-testid="fno-read" className="cp-pretty" style={{ fontFamily: "var(--display)", fontSize: 19, lineHeight: 1.3 }}>{d.verdict_reason}</span>
        </div>
      )}

      {tiles.length > 0 && <TileGrid tiles={tiles} />}

      {symbol && (
        <div className="grid items-start" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: 16 }}>
          <FuturesBlock symbol={symbol} />
          <OptionsBlock symbol={symbol} />
        </div>
      )}

      <NotConnected
        testId="fno-not-connected"
        title={`Implied volatility, expected move and index internals for ${idx.name}`}
        body="At-the-money IV, the expected move to expiry, the stocks that moved the index and daily trend signals also belong on this card. The end-of-day F&O data carries no implied volatility, and nothing serves index constituents or index history to the app, so none of them is shown or estimated."
        needs={NEEDS}
      />

      <AskChips items={asks} />
    </section>
  );
}
