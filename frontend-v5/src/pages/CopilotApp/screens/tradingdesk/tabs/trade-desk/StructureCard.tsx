/**
 * One recorded F&O structure with EVERY leg (the owner's design: "F&O strategies · every leg shown").
 *
 *   legs, marks, P/L, net premium, state     GET /api/desk/paper-trades (the list the tab already read)
 *   max profit / loss, worst loss after      POST /api/desk/strategy/payoff (payoff-v2) with the trade's STORED legs at their
 *   costs, breakevens                        entry premiums and the underlying's close when recorded: the backend's payoff
 *                                            engine, a pure calculation. At expiry; nothing is estimated in the browser.
 *   Greeks                                   unavailable: the paper-trade record stores no Greeks and no volatility
 *   days to expiry                           calendar days to the leg's stored expiry date
 *
 * The leg table scrolls inside its own box on a phone. Roll is RollAction (GET/POST …/{id}/roll). Simulated only.
 */
import { fmtINR, fmtNum } from "../../../../components/ui";
import { fmtDay, fmtPrice } from "../../../trading/parts";
import type { StrategyLeg, StrategyPaperTrade } from "../../desk-trading";
import { RollAction } from "../../RollAction";
import { calendarDaysTo, structurePayoffRequest, useStructurePayoff } from "./trade-desk-data";
import { Pnl, StatePill, linkBtn, quiet } from "./parts";

const BASIS: Record<string, string> = { settle: "settle", close: "close", expiry_intrinsic: "expiry value", final_settle: "final settle", underlying_close: "share close" };

function contract(l: StrategyLeg): string {
  if (l.kind === "option") return `${l.strike != null ? fmtNum(l.strike, l.strike % 1 ? 2 : 0) : "—"} ${l.optionType === "call" ? "CE" : l.optionType === "put" ? "PE" : ""}`.trim();
  if (l.kind === "future") return "FUT";
  return "Shares";
}

export function LegTable({ t, testId = "td-legs" }: { t: StrategyPaperTrade; testId?: string }) {
  const closed = t.status === "closed";
  const th = { padding: "6px 10px", fontWeight: 500, whiteSpace: "nowrap" as const };
  const td = { padding: "7px 10px", whiteSpace: "nowrap" as const };
  return (
    <div data-testid={testId} className="cp-scroll" style={{ maxWidth: "100%", overflowX: "auto", border: "1px solid var(--cp-line)", borderRadius: 10 }}>
      <table style={{ width: "100%", minWidth: 560, borderCollapse: "collapse", fontSize: 12.5 }}>
        <thead>
          <tr className="cp-mono-note" style={{ textAlign: "left" }}>
            <th style={th}>Leg</th><th style={th}>Contract</th><th style={th}>Expiry</th><th style={{ ...th, textAlign: "right" }}>Lots × size</th>
            <th style={{ ...th, textAlign: "right" }}>Entry</th><th style={{ ...th, textAlign: "right" }}>{closed ? "Exit mark" : "Mark"}</th><th style={{ ...th, textAlign: "right" }}>P/L</th>
          </tr>
        </thead>
        <tbody>
          {t.legs.map((l) => (
            <tr key={l.index} data-testid={`${testId}-row`} data-index={l.index} style={{ borderTop: "1px solid var(--cp-line)" }}>
              <td style={td}>
                <span className="cp-num" style={{ padding: "2px 7px", borderRadius: 5, fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase",
                  color: l.side === "buy" ? "var(--mint)" : "var(--cp-danger)", background: l.side === "buy" ? "var(--mint-soft)" : "var(--cp-danger-soft)" }}>{l.side}</span>
              </td>
              <td data-testid={`${testId}-contract`} className="cp-num" style={td} title={l.label}>{contract(l)}</td>
              <td style={td}>{l.expiry ? fmtDay(l.expiry) : "—"}</td>
              <td className="cp-num" style={{ ...td, textAlign: "right" }}>{fmtNum(l.lots)} × {fmtNum(l.lotSize)}</td>
              <td data-testid={`${testId}-entry`} className="cp-num" style={{ ...td, textAlign: "right" }}>{fmtPrice(l.entry)}</td>
              <td data-testid={`${testId}-mark`} className="cp-num" style={{ ...td, textAlign: "right" }} title={l.markBasisText ?? undefined}>
                {fmtPrice(l.mark)}
                <span style={{ display: "block", fontSize: 10.5, color: "var(--cp-ink-3)" }}>{l.mark == null ? "no mark" : `${l.markBasis ? BASIS[l.markBasis] : "mark"}${l.markDate ? ` · ${fmtDay(l.markDate)}` : ""}`}</span>
              </td>
              <td style={{ ...td, textAlign: "right" }}><Pnl rs={l.pnlRs} testId={`${testId}-pnl`} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Fig({ k, v, testId, tone, sub }: { k: string; v: string; testId: string; tone?: "profit" | "loss"; sub?: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <span className="cp-eyebrow" style={{ fontSize: 9 }}>{k}</span>
      <span data-testid={testId} className="cp-num" style={{ fontSize: 13.5, color: tone === "profit" ? "var(--mint)" : tone === "loss" ? "var(--cp-danger)" : "var(--cp-ink)", overflowWrap: "anywhere" }}>{v}</span>
      {sub && <span style={{ fontSize: 10.5, lineHeight: 1.35, color: "var(--cp-ink-3)" }}>{sub}</span>}
    </div>
  );
}

/** payoff-v2 figures for the stored legs, the Greeks (unavailable) and days to expiry. */
export function StructureFigures({ t }: { t: StrategyPaperTrade }) {
  const q = useStructurePayoff(t);
  const askable = structurePayoffRequest(t) != null;
  const ex = q.data?.valid ? q.data.expiry ?? null : null;
  const expiry = t.legs.find((l) => l.expiry)?.expiry ?? null;
  const dte = calendarDaysTo(expiry);
  let why: string | null = null;
  if (!askable) why = "a leg's price, strike or expiry, or the underlying's reference price, is missing on the record";
  else if (q.isError) why = "the payoff calculation did not answer";
  else if (q.data && !q.data.valid) why = q.data.problems.map((p) => p.message).join("; ") || "the payoff calculation rejected the legs";
  const pending = askable && q.isPending;
  const val = (s: string) => (pending ? "…" : why ? "unavailable" : s);
  const maxProfit = !ex ? "—" : ex.profit_unbounded ? "Unlimited" : rsAbs(ex.max_profit, "+");
  const maxLoss = !ex ? "—" : ex.loss_unbounded ? "Unlimited" : rsAbs(ex.max_loss, "−");
  const worst = q.data?.capital_at_risk != null ? rsAbs(q.data.capital_at_risk, "−") : ex?.loss_unbounded ? "Unlimited" : "—";
  const be = ex ? (ex.breakevens.length ? ex.breakevens.map((b) => fmtNum(b, 2)).join(" · ") : "none in range") : "—";
  return (
    <div data-testid="td-structure-figures" data-state={pending ? "pending" : why ? "unavailable" : "ok"} className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,118px),1fr))", gap: "8px 12px" }}>
        <Fig k="Max profit" testId="td-fig-max-profit" v={val(maxProfit)} tone="profit" sub="at expiry, before costs" />
        <Fig k="Max loss" testId="td-fig-max-loss" v={val(maxLoss)} tone="loss" sub="at expiry, before costs" />
        <Fig k="Worst loss after costs" testId="td-fig-worst" v={val(worst)} tone="loss" sub="statutory costs and slippage" />
        <Fig k="Breakevens" testId="td-fig-breakevens" v={val(be)} sub="at expiry, before costs" />
        <Fig k="Greeks" testId="td-fig-greeks" v="unavailable" sub="not stored on a paper trade" />
        <Fig k="Days to expiry" testId="td-fig-dte" v={dte == null ? "unavailable" : dte < 0 ? "expired" : `${dte}d`} sub={expiry ? `calendar days to ${fmtDay(expiry)}` : "no expiry on the legs"} />
      </div>
      <span data-testid="td-structure-figures-basis" style={{ ...quiet, fontSize: 11 }}>
        {why
          ? `Max profit, max loss and breakevens are unavailable: ${why}.`
          : `From the payoff engine${q.data?.calculation_version ? ` (${q.data.calculation_version})` : ""} on the recorded legs at their entry premiums${t.referencePrice != null ? `, ${t.underlying} at ${fmtPrice(t.referencePrice)}` : ""}.`}
        {" "}Greeks are not on the paper-trade record (no volatility is stored); the F&amp;O builder in New trade shows them for a new structure.
      </span>
    </div>
  );
}

function rsAbs(n: number | null | undefined, sign: "+" | "−"): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${sign}${fmtINR(Math.abs(n))}`;
}

export function StructureCard({ t, onJournal, onChart }: { t: StrategyPaperTrade; onJournal: () => void; onChart: () => void }) {
  return (
    <article data-testid="td-structure" data-id={t.id} data-status={t.status} className="flex min-w-0 flex-col"
      style={{ gap: 12, padding: 14, borderRadius: 14, border: "1px solid var(--line-2)", background: "var(--bg-2)" }}>
      <div className="flex flex-wrap items-start justify-between" style={{ gap: 10 }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <StatePill state={t.state} fallback={t.status === "open" ? "open" : "closed"} testId="td-structure-state" />
            <button type="button" data-testid="td-structure-open" onClick={onJournal}
              style={{ ...linkBtn, color: "var(--cp-ink)", fontFamily: "var(--display)", fontSize: 18, lineHeight: 1.2, textAlign: "left" }}>
              {t.familyName ?? t.family ?? "Structure"} · {t.underlying}
            </button>
          </span>
          <span data-testid="td-structure-summary" style={quiet}>{t.summaryText}{t.tradePlanId ? ` · plan ${t.tradePlanId}` : ""}</span>
        </div>
        <span className="flex flex-col items-end" style={{ gap: 2 }}>
          <Pnl rs={t.netRs} testId="td-structure-net" big />
          <span style={{ ...quiet, fontSize: 10.5 }}>net of costs, before income tax</span>
        </span>
      </div>
      <StructureFigures t={t} />
      <LegTable t={t} />
      <span style={{ ...quiet, fontSize: 11 }}>
        Net premium {t.netPremiumRs != null ? fmtINR(t.netPremiumRs, { signed: true }) : "—"} at entry{t.markPremiumRs != null ? ` · ${fmtINR(t.markPremiumRs, { signed: true })} at the marks` : ""}
        {t.lastMarkDate ? ` · end-of-day bhavcopy marks, ${fmtDay(t.lastMarkDate)}` : t.markError ? ` · no marks (${t.markError})` : ""}.
      </span>
      {t.riskNote && <span style={{ fontSize: 12, color: "var(--amber)" }}>{t.riskNote}</span>}
      <div className="flex flex-wrap items-start" style={{ gap: 8 }}>
        <button type="button" className="cp-chip" data-testid="td-structure-journal" onClick={onJournal} style={{ padding: "4px 12px", fontSize: 12 }}>Trade journal</button>
        <button type="button" className="cp-chip" data-testid="td-structure-chart" onClick={onChart} style={{ padding: "4px 12px", fontSize: 12 }}>Chart · {t.underlying}</button>
        {t.status === "open" && <RollAction t={t} testPrefix="td-roll" />}
      </div>
    </article>
  );
}
