/**
 * The "strategy that fits" after its name, on the Overview's idea cards and the AI scanner watchlist: the legs, the size
 * the risk service gives YOUR account (`account_size`), or "1 lot, not sized to your account" with the reason, then max
 * loss and reward : risk, which says when it is under your minimum (audit 2026-10-28, owner rules: sizes from
 * account_size; minimum 1.5 reward : risk). Nothing is computed here: top10-data.fitSize / belowMinimum read the route.
 */
import { belowMinimum, belowMinimumText, fitSize, type FitStrategy } from "./top10-data";
import { ratio, rupeesAbs } from "./strategy/plan-format";

const quiet = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;

export function FitLine({ s, symbol, testId = "desk-top10-fit" }: { s: FitStrategy & { max_loss?: number | null }; symbol: string; testId?: string }) {
  const f = fitSize(s, symbol);
  const below = belowMinimum(s);
  return (
    <>
      {f.legs ? ` · ${f.legs}` : ""}
      {" · "}<span data-testid={`${testId}-size`} data-sized={f.sized} style={f.sized ? undefined : { color: "var(--amber)" }}>{f.size}</span>
      {` · max loss ${rupeesAbs(s.max_loss ?? null)} · reward : risk ${ratio(s.reward_risk_net ?? null)}`}
      {below != null && <span data-testid={`${testId}-below-min`} style={{ color: "var(--amber)" }}>{` (${belowMinimumText(below)})`}</span>}
      {!f.sized && f.why && <span data-testid={`${testId}-why`} style={{ ...quiet, display: "block" }}>Not sized: {f.why}</span>}
    </>
  );
}
