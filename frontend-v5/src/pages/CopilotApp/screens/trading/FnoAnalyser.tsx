/**
 * F&O analyser card on the Trader desk. Design: NVIndex.dc.html.
 *
 * Real today, all from GET /api/markets/home (useMarketsHome): the index quote,
 * India VIX, market breadth and the rules-based market read.
 *
 * Everything else in the design needs an option chain, futures prices, index
 * history or constituent weights. No app route serves those, so they are
 * listed as not connected instead of being drawn.
 */
import { useState } from "react";
import { useMarketsHome } from "@/hooks/use-markets";
import { AskChips, Btn, EmptyBlock, LoadingBlock, NotConnected, TONE_COLOR, fmtNum, fmtPct, relTime, signTone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { Choices, Labeled, QueryProblem, fmtSigned } from "./parts";

/** Index names (as /api/markets/home spells them) that have index derivatives in the design. */
export const FNO_INDEX_NAMES = ["Nifty 50", "Nifty Bank"];

const NEEDS = [
  "An option chain per underlying and expiry: strike, call and put price, open interest, change in open interest and IV. The data platform keeps an end-of-day F&O chain (DaaS /v1/fno/{symbol}/chain), but no /api route returns it to the app.",
  "The futures price for the same expiry, for the basis.",
  "Index open, high, low and daily history, for pivots, the previous day’s range, moving averages, RSI and ADX.",
  "Index constituents with weights, for the points each stock added or took away.",
];

export function FnoAnalyser() {
  const { go, mobile } = useCopilotShell();
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
  const vix = d.indices.find((i) => i.is_vix && i.value != null);
  const prevClose = idx.value != null && idx.change != null ? idx.value - idx.change : null;
  const b = d.breadth;
  const tone = TONE_COLOR[signTone(idx.change_pct)];

  const tiles: Array<{ k: string; v: string; s: string; testId?: string }> = [];
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

      {tiles.length > 0 && (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 8 }}>
          {tiles.map((t) => (
            <div key={t.k} className="flex flex-col" style={{ gap: 3, padding: "12px 14px", borderRadius: 10, background: "var(--bg-2)" }}>
              <span className="cp-eyebrow">{t.k}</span>
              <span data-testid={t.testId} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 21 }}>{t.v}</span>
              <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{t.s}</span>
            </div>
          ))}
        </div>
      )}

      <NotConnected
        testId="fno-not-connected"
        title={`Options and futures data for ${idx.name}`}
        body="Futures and basis, put-call ratio, max pain, at-the-money IV, the expected move, open interest by strike, key levels, the stocks that moved the index and daily trend signals belong on this card. Nothing serves them to the app yet, so none of them is shown."
        needs={NEEDS}
        action={<Btn onClick={() => go("tool/optlab")}>Open the options lab</Btn>}
      />

      <AskChips items={asks} />
    </section>
  );
}
