/**
 * "If Nifty falls 5%": what that would do to the user's equity-linked holdings, and how it can be hedged. One call to the Quick Hedge
 * route (POST /api/portfolio/quick-hedge, services/quick_hedge), made on mount; every figure is the server's. Shown on the last step
 * of onboarding; the same card can sit anywhere in the app.
 *
 * Behind the `portfolio_hedge` feature flag like the rest of Quick Hedge: with the flag off it renders nothing and asks nothing, and a
 * 403 is read as "not enabled", never as a failure. An estimate only: the holdings are assumed to move with Nifty by their beta. It
 * places no order and stores nothing; the hedge shown is paper-only.
 */
import { useEffect } from "react";
import { useMe } from "@/hooks/use-auth";
import { ApiError } from "@/services/api/errors";
import { useCopilotShell } from "../lib/shell-context";
import { describeStructure, useQuickHedge, HEDGE_MODES, HEDGE_MODE_LABEL, type HedgeMode } from "../screens/tradingdesk/tabs/risk-desk/hedge-data";
import { Btn, LoadingBlock, TONE_COLOR, fmtINR, fmtNum, fmtPct } from "./ui";

const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;
const fearRow = (m: HedgeMode) => m.rows.find((x) => x.isExpectedFall);
const paysAtFear = (m: HedgeMode) => (fearRow(m)?.hedgePnlRs ?? 0) > 0;

export function NiftyFallCard({ fallPct = 5 }: { fallPct?: number }) {
  const me = useMe();
  const enabled = me.data?.features?.portfolio_hedge === true;
  const { go, ask } = useCopilotShell();
  const q = useQuickHedge();
  useEffect(() => {
    if (enabled) q.mutate({ expectedFallPct: fallPct, tenor: "1m", tolerance: { kind: "pct", value: 5 } });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, fallPct]);

  if (!enabled) return null;
  if (q.isPending || (!q.data && !q.isError)) return <div data-testid="nifty-fall-card" data-state="loading"><LoadingBlock label={`Simulating a ${fallPct}% fall in Nifty`} rows={2} /></div>;
  if (q.isError) {
    if (q.error instanceof ApiError && (q.error.kind === "forbidden" || q.error.status === 403)) return null;
    return <p data-testid="nifty-fall-card" data-state="error" role="note" className="m-0" style={quiet}>The {fallPct}% Nifty fall simulation could not be run just now.</p>;
  }
  const r = q.data;
  const p = r.portfolio, ex = r.exposure;
  const empty = r.reasons.some((x) => x.code === "missing_portfolio");
  // A put pays only below its strike. Show the first choice (Balanced, then Maximum, then Lowest cost) that pays at this fall; when
  // none does, show Balanced and say where its protection starts, never "it would cut the loss" (with the hedge = loss + its cost).
  const offered = HEDGE_MODES.map((k) => r.modes.find((m) => m.mode === k && m.available)).filter((m): m is HedgeMode => m != null);
  const pick: HedgeMode | undefined = offered.find(paysAtFear) ?? offered[0];
  const row = pick ? fearRow(pick) : undefined;
  const pays = pick ? paysAtFear(pick) : false;
  const strike = pick?.legs.find((l) => l.side === "buy")?.strike ?? null;
  const startsDown = strike != null && ex?.spot ? ((ex.spot - strike) / ex.spot) * 100 : null;
  const deeper = pick && row && !pays ? pick.rows.find((x) => x.movePct < row.movePct && (x.hedgePnlRs ?? 0) > 0 && x.withoutRs != null && x.withRs != null) : undefined;
  const total = p.valueRs ?? 0;
  const without = row?.withoutRs ?? (ex?.exposureRs != null ? -(ex.exposureRs * fallPct) / 100 : null);   // the table's own formula when no hedge is offered
  const share = without != null && total > 0 ? ` (${fmtPct((Math.abs(without) / total) * 100, { digits: 1 })} of your whole portfolio)` : "";
  const attention = p.sources?.needsAttention === true;

  return (
    <section data-testid="nifty-fall-card" data-state={empty ? "empty" : r.status} className="cp-card-raised flex flex-col" style={{ gap: 10, padding: "16px 18px" }}>
      <span className="cp-eyebrow">If Nifty falls {fallPct}%</span>
      {empty ? (
        <>
          <span style={{ fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>We found no equity-linked holdings to simulate. Connect a broker or upload a CAS statement to see what a {fallPct}% fall would do to your portfolio.</span>
          <div><Btn data-testid="nifty-fall-connect" variant="primary" onClick={() => go("page/brokers")}>Connect a broker or upload a CAS</Btn></div>
        </>
      ) : without == null ? (
        <span data-testid="nifty-fall-reason" style={{ fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{r.reasons[0]?.message ?? "The simulation is not available right now."}</span>
      ) : (
        <>
          <span style={{ fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
            Your equity-linked holdings would lose about{" "}
            <b data-testid="nifty-fall-without" className="cp-num" style={{ color: TONE_COLOR.danger }}>{fmtINR(Math.abs(without))}</b>{share}.
          </span>
          {pick && row && pays ? (
            <span data-testid="nifty-fall-hedge" data-pays="yes" style={{ fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
              <b>How it can be hedged:</b> {describeStructure(pick, ex?.lot ?? null).toLowerCase()} ({HEDGE_MODE_LABEL[pick.mode]}) for about {fmtINR(pick.totalCostRs)} would cut it to about{" "}
              <b data-testid="nifty-fall-with" className="cp-num">{fmtINR(Math.abs(row.withRs ?? 0))}</b>.
            </span>
          ) : pick && row ? (
            <span data-testid="nifty-fall-hedge" data-pays="no" style={{ fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
              <b>How it can be hedged:</b> {describeStructure(pick, ex?.lot ?? null).toLowerCase()} ({HEDGE_MODE_LABEL[pick.mode]}) for about {fmtINR(pick.totalCostRs)}
              {strike != null ? (
                <> starts paying only below Nifty <b data-testid="nifty-fall-starts" className="cp-num">{fmtNum(strike)}</b>{startsDown != null ? ` (${startsDown.toFixed(1)}% down)` : ""}, so at a {fallPct}% fall it pays nothing and only adds its cost.</>
              ) : (
                <> pays nothing at a {fallPct}% fall and only adds its cost.</>
              )}
              {deeper && (
                <> At a {Math.abs(deeper.movePct)}% fall it would cut the loss from {fmtINR(Math.abs(deeper.withoutRs ?? 0))} to{" "}
                  <b data-testid="nifty-fall-deeper" className="cp-num">{fmtINR(Math.abs(deeper.withRs ?? 0))}</b>.</>
              )}{" "}
              To cover a {fallPct}% fall itself, choose a smaller tolerable loss in the hedge.
            </span>
          ) : (
            <span data-testid="nifty-fall-nohedge" style={{ fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
              {r.reasons[0]?.message ?? "No index-option hedge is offered at this size."}
            </span>
          )}
          <div className="flex flex-wrap" style={{ gap: 8 }}>
            {pick && <Btn data-testid="nifty-fall-see-hedge" variant="primary" onClick={() => go("trader/desk?tab=risk&view=hedge")}>See hedge choices</Btn>}
            <Btn data-testid="nifty-fall-ask" onClick={() => ask(`How can I hedge my portfolio against a ${fallPct}% fall?`)}>Ask the Copilot</Btn>
          </div>
        </>
      )}
      {attention && !empty && (
        <span data-testid="nifty-fall-stale" style={{ ...quiet, color: TONE_COLOR.amber }}>
          Some of your holdings sources look out of date, so this may not include recent trades.{" "}
          <Btn data-testid="nifty-fall-update" variant="ghost" onClick={() => go("page/brokers")}>Update holdings</Btn>
        </span>
      )}
      <span data-testid="nifty-fall-note" style={quiet}>
        An estimate: your equity-linked holdings are assumed to move with Nifty by their beta{p.beta != null ? ` (${p.beta.toFixed(2)})` : ""}; hybrid, gold, overseas and debt holdings are not in it.
        Paper only: nothing is placed.
      </span>
    </section>
  );
}
