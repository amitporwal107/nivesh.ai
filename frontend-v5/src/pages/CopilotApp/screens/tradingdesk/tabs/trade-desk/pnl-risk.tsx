/**
 * P&L dashboard v2 — the risk monitor (meters: Margin used, Daily loss limit, Exposure, Open positions at risk; the route's
 * alerts) and the "AI Trading Supervisor" card, as drawn. The supervisor is a RULE-BASED reading of the figures on screen (no
 * model call): the position that has used most of its risk budget, its entry, price and stop loss, and what to look at.
 * Wording (25 Oct rule): never recommend / pick / suggested — the design's "Suggested action" is "Points to review".
 */
import type { ReactNode } from "react";
import { fmtINR, fmtPct } from "../../../../components/ui";
import type { AlertSeverity, PnlPosition, PnlSnapshot } from "./pnl-data";
import { timeIST } from "./pnl-parts";
import { MONO, Pill, SERIF, TONES, card, eyebrow, serifTitle } from "./pnl-ui";

export const AT_RISK_PCT = 40;

const px = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const meterColor = (pct: number | null) => (pct == null ? "var(--cp-ink-3)" : pct >= 70 ? "var(--cp-danger)" : pct >= 40 ? "var(--amber)" : "var(--mint)");

function Meter({ k, label, value, pct, color, sub }: { k: string; label: string; value: string; pct: number | null; color: string; sub: ReactNode }) {
  const w = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <div data-testid="pnl-meter" data-key={k} data-pct={pct == null ? "" : String(Math.round(pct * 100) / 100)} className="flex min-w-0 flex-col" style={{ gap: 7 }}>
      <div className="flex justify-between" style={{ ...eyebrow, gap: 8 }}><span>{label}</span><span data-testid="pnl-meter-value" style={{ color }}>{value}</span></div>
      <div style={{ height: 5, borderRadius: 3, background: "var(--bg-3)", overflow: "hidden" }}><div style={{ height: "100%", width: `${w}%`, background: color }} /></div>
      <div style={{ fontSize: 12, color: "var(--cp-ink-3)", lineHeight: 1.4 }}>{sub}</div>
    </div>
  );
}

const SEV: Record<AlertSeverity, "danger" | "amber" | "indigo"> = { CRITICAL: "danger", WARNING: "amber", INFO: "indigo" };
const TYPE_WORDS: Record<string, string> = {
  STOP_LOSS_HIT: "Stop loss hit", NEAR_STOP_LOSS: "Near stop loss", TARGET_REACHED: "Target reached", EXIT_DUE: "Closes at the evening check",
  EXPIRY: "Expiry", STALE_PRICE: "Price not current", FEED: "Feed", RECONCILIATION_MISMATCH: "Ledger check", CAPITAL: "Capital",
};

export function RiskMonitor({ d }: { d: PnlSnapshot }) {
  const r = d.risk;
  const s = d.summary;
  const atRisk = d.positions.filter((p) => p.riskUsedPct != null && p.riskUsedPct >= AT_RISK_PCT).length;
  const exposure = r.exposureRs ?? s.exposureRs;
  const capital = s.allocatedCapital;
  const expPct = exposure != null && capital ? (exposure / capital) * 100 : null;
  return (
    <section data-testid="pnl-risk" className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", padding: "20px 22px", gap: 14 }}>
      <div style={serifTitle}>Risk monitor</div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 14 }}>
        <Meter k="margin" label="Margin used" value={fmtPct(r.margin.usedPct, { digits: 1 })} pct={r.margin.usedPct} color={meterColor(r.margin.usedPct)}
          sub={r.margin.basis ?? (r.capital.basis ? `Paper: ${r.capital.basis}` : "Basis not given")} />
        <Meter k="daily-loss" label="Daily loss limit" value={fmtPct(r.dailyLossUsedPct, { digits: 0 })} pct={r.dailyLossUsedPct} color={meterColor(r.dailyLossUsedPct)}
          sub={r.dailyLossLimitRs != null ? `Used of ${fmtINR(r.dailyLossLimitRs)} (paper risk profile)` : "No daily loss limit set"} />
        <Meter k="exposure" label="Exposure" value={fmtINR(exposure)} pct={expPct} color="var(--cp-indigo)"
          sub={`Notional of open positions${expPct != null ? ` · ${fmtPct(expPct, { digits: 1 })} of capital` : ""}`} />
        <Meter k="at-risk" label="Open positions at risk" value={String(atRisk)} pct={Math.min(100, atRisk * 20)} color="var(--amber)" sub={`Above ${AT_RISK_PCT}% of their risk budget`} />
      </div>
      <div data-testid="pnl-alerts-head" style={{ ...eyebrow, marginTop: 4 }}>Alerts · {r.alerts.length}</div>
      <div data-testid="pnl-alerts" className="flex flex-col" style={{ gap: 8 }}>
        {r.alerts.length ? r.alerts.map((a, i) => {
          const t = TONES[SEV[a.severity]];
          return (
            <div key={`${a.type}-${a.positionId ?? ""}-${i}`} data-testid="pnl-alert" data-severity={a.severity} data-type={a.type} role={a.severity === "CRITICAL" ? "alert" : undefined}
              className="flex items-start" style={{ gap: 12, padding: "10px 12px", borderRadius: 10, background: t.soft, border: `1px solid ${t.line}` }}>
              <span aria-hidden style={{ marginTop: 6, width: 6, height: 6, borderRadius: "50%", background: t.c, flex: "none" }} />
              <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
                <span style={{ fontSize: 13.5, fontWeight: 500, color: "var(--cp-ink)" }}>{TYPE_WORDS[a.type] ?? a.type.replace(/_/g, " ").toLowerCase()}{a.symbol ? ` · ${a.symbol}` : ""}</span>
                <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)", lineHeight: 1.45, overflowWrap: "anywhere" }}>
                  {a.message}
                  {a.observed != null || a.threshold != null ? <span className="cp-num" style={{ color: "var(--cp-ink-3)" }}> ({a.observed != null ? `now ${px(a.observed)}` : ""}{a.observed != null && a.threshold != null ? " · " : ""}{a.threshold != null ? `level ${px(a.threshold)}` : ""})</span> : null}
                </span>
              </div>
            </div>
          );
        }) : (
          <div data-testid="pnl-alerts-none" className="flex items-start" style={{ gap: 12, padding: "10px 12px", borderRadius: 10, background: TONES.mint.soft, border: `1px solid ${TONES.mint.line}` }}>
            <span aria-hidden style={{ marginTop: 6, width: 6, height: 6, borderRadius: "50%", background: TONES.mint.c, flex: "none" }} />
            <div className="flex flex-col" style={{ gap: 2 }}><span style={{ fontSize: 13.5, fontWeight: 500, color: "var(--cp-ink)" }}>No active alerts</span><span style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>No monitored threshold is crossed on these positions.</span></div>
          </div>
        )}
      </div>
      <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)", lineHeight: 1.45 }}>
        Paper alerts use the prices shown here and are for display: the paper ledger still decides each exit on the day's end-of-day bar at the evening check.
      </span>
    </section>
  );
}

/** The position that has used most of its risk budget (a positive figure only), else none. */
export function worstPosition(rows: PnlPosition[]): PnlPosition | null {
  let best: PnlPosition | null = null;
  for (const p of rows) if (p.riskUsedPct != null && p.riskUsedPct > 0 && (!best || p.riskUsedPct > (best.riskUsedPct as number))) best = p;
  return best;
}

export function Supervisor({ d }: { d: PnlSnapshot }) {
  const w = worstPosition(d.positions);
  const stale = d.positions.filter((p) => p.priceStatus === "DELAYED" || p.priceStatus === "MISSING").length;
  const loss = w?.unrealized != null ? Math.max(0, -w.unrealized) : null;
  const dist = w && w.ltp != null && w.stopLoss != null ? Math.abs(w.ltp - w.stopLoss) : null;
  const headline = w
    ? `${w.instrument} ${loss ? `is losing ${fmtINR(loss)} and ` : ""}has used ${Math.round(w.riskUsedPct as number)}% of its risk budget.`
    : d.positions.length ? "No position is losing against its risk budget." : "No open position in this selection.";
  const obs: string[] = w ? [
    `Entry ${px(w.avgPrice)}, price ${px(w.ltp)}, stop loss ${px(w.stopLoss)}.`,
    dist != null ? `Distance to the stop loss: ${px(dist)} per unit${w.distanceToStopPct != null ? ` (${fmtPct(w.distanceToStopPct, { digits: 2 })})` : ""}.` : "No stop loss recorded for this position.",
    `Account: ${w.account ?? "—"} · ${w.mode === "LIVE" ? "live" : "paper"}.`,
  ] : ["Every position is inside its stop loss and target band, or has no risk budget recorded."];
  if (stale) obs.push(`${stale} position${stale === 1 ? " is" : "s are"} priced from a quote that is not current.`);
  const review = w ? "This position's stop loss distance, and its size against your risk limit." : "Nothing stands out against the risk budget.";
  return (
    <section data-testid="pnl-supervisor" className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", padding: "20px 22px", gap: 14, border: "1px solid var(--indigo-line)" }}>
      <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
        <Pill tone="indigo">AI Trading Supervisor</Pill>
        <span data-testid="pnl-supervisor-meta" style={{ fontFamily: MONO, fontSize: 11, color: "var(--cp-ink-3)" }}>Data as of {timeIST(d.asOf) ?? "—"} IST</span>
      </div>
      <div data-testid="pnl-supervisor-headline" data-id={w?.positionId ?? ""} style={{ fontFamily: SERIF, fontSize: 28, lineHeight: 1.2, color: "var(--cp-ink)" }}>{headline}</div>
      <div data-testid="pnl-supervisor-obs" className="flex flex-col" style={{ gap: 6, fontSize: 13.5, color: "var(--cp-ink-2)", lineHeight: 1.5 }}>
        {obs.map((o, i) => <div key={i}>· {o}</div>)}
      </div>
      <div data-testid="pnl-supervisor-review" style={{ fontSize: 13.5, color: "var(--cp-ink)" }}>
        <span style={eyebrow}>Points to review</span><br />{review}
      </div>
      <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--cp-ink-3)", borderTop: "1px solid var(--cp-line)", paddingTop: 12 }}>
        Rule-based reading of the figures above. No order has been placed or modified.
      </div>
    </section>
  );
}

export function PnlFooter() {
  return (
    <div data-testid="pnl-footer" style={{ fontFamily: MONO, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--cp-ink-3)", lineHeight: 1.6 }}>
      Paper and live positions are tracked separately. Estimated charges are not broker-settled values. Live positions are read from your brokers; Nivesh places no live order.
    </div>
  );
}
