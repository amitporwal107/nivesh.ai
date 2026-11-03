/**
 * Market Overview — the owner's design's KPI row and Paper trades panel (PLAN.md 1-REVISED, 27 Oct 19:40 IST). Both are
 * READ-ONLY: this tab never calls GET /api/desk/paper-trades or GET /api/desk/alerts, because listing either applies exits
 * or fires alerts as it reads.
 *
 *   Paper equity     GET /api/risk/profile `live.equity.equity_rs` (paper cash + net unrealised P&L at the end-of-day
 *                    marks, the risk service's own figure), against the starting capital of GET /api/desk/paper-account
 *   Day net P/L      GET /api/risk/profile `live.day.pnl_rs` (net of estimated costs, before income tax)
 *   Open risk        GET /api/risk/profile `live.open.risk_rs` ÷ equity, against the profile's max_open_risk_pct
 *   Candidates       the Top AI candidates' two boards (the cached POST /api/desk/strategy/ideas and /top answers)
 *   Feed             the Kite live feed's state as the app's live store holds it (useLiveMeta)
 *   Paper trades     GET /api/risk/profile `live.open`: the open positions the risk service counts, the share symbols held,
 *                    exposure and open risk; each row and the panel link to Trade Desk, where every trade's P/L lives
 *
 * A figure that is not there says so with the route's reason, never 0. Nothing here places an order.
 */
import type { CSSProperties, ReactNode } from "react";
import { StockIcon } from "../../../../components/EntityIcon";
import { TONE_COLOR, fmtINR, fmtNum, signTone, type Tone } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { useLiveMeta, type LiveMode } from "../../../../lib/useLiveQuotes";
import { dayLabel } from "../../../markets/format";
import { useRiskProfile } from "../../risk-profile";
import { mergeFno, useTop10Fno, useTop10Stocks } from "../../top10-data";
import { Widget } from "../../widget";
import { pctText, tradeDeskLine, usePaperAccount } from "./overview-data";

const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const link: CSSProperties = { padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", color: "var(--mint)" };
const toneColor = (t: Tone) => (t === "ink" ? "var(--cp-ink)" : TONE_COLOR[t]);

function Kpi({ testId, label, value, sub, tone = "ink" }: { testId: string; label: string; value: string; sub: ReactNode; tone?: Tone }) {
  return (
    <div data-testid={testId} className="cp-card flex min-w-0 flex-col" style={{ gap: 6, padding: "14px 16px" }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5, letterSpacing: "0.14em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{label}</span>
      <span data-testid={`${testId}-value`} style={{ fontFamily: "var(--display)", fontSize: 26, lineHeight: 1.1, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: toneColor(tone) }}>{value}</span>
      <span data-testid={`${testId}-sub`} className="cp-num" style={{ fontSize: 10.5, lineHeight: 1.45, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{sub}</span>
    </div>
  );
}

const FEED_WORD: Record<LiveMode, { label: string; tone: Tone }> = {
  live: { label: "Live", tone: "mint" }, delayed: { label: "Delayed", tone: "amber" }, closed: { label: "Closed", tone: "ink" },
  expired: { label: "Closed", tone: "ink" }, not_connected: { label: "Not connected", tone: "amber" }, disabled: { label: "Off", tone: "ink" },
  unknown: { label: "Unknown", tone: "ink" },
};

export function OverviewKpis() {
  const { mobile } = useCopilotShell();
  const rp = useRiskProfile();
  const acct = usePaperAccount();
  const stocks = useTop10Stocks();
  const fno = useTop10Fno();
  const feed = useLiveMeta();
  const live = rp.data?.live ?? null;
  const why = rp.isPending ? "reading the risk profile" : rp.isError ? "the risk profile didn’t load" : rp.data?.liveError ?? null;

  const equity = live?.equityRs ?? null;
  const start = acct.data?.startingRs ?? rp.data?.profile.startingCapitalRs ?? null;
  const growth = equity != null && start ? ((equity - start) / start) * 100 : null;
  const day = live?.day.pnlRs ?? null;
  const line = rp.data ? tradeDeskLine(rp.data) : null;
  const cash = stocks.data ? Math.min(stocks.data.ideas.length, 10) : null;
  const fnoN = fno.data ? mergeFno(fno.data).length : null;
  const scan = stocks.data?.selection.scan_date ?? null;
  const f = FEED_WORD[feed.mode] ?? FEED_WORD.unknown;

  return (
    <div data-testid="mo-kpis" className="grid" style={{ gridTemplateColumns: mobile ? "repeat(2,minmax(0,1fr))" : "repeat(auto-fit,minmax(170px,1fr))", gap: mobile ? 8 : 12 }}>
      <Kpi testId="mo-kpi-equity" label="Paper equity" value={fmtINR(equity)}
        sub={equity == null ? `unknown: ${live?.unknownReasons[0] ?? why ?? "not sent"}` : `start ${fmtINR(start)}${growth != null ? ` · ${growth >= 0 ? "+" : "−"}${fmtNum(Math.abs(growth), 1)}%` : ""}`} />
      <Kpi testId="mo-kpi-day" label="Day net P/L" value={fmtINR(day, { signed: true })} tone={signTone(day)}
        sub={day == null ? `unknown: ${live?.day.unknownReasons[0] ?? why ?? "not sent"}` : "net of costs, before income tax"} />
      <Kpi testId="mo-kpi-risk" label="Open risk" value={line?.openRiskPct != null ? pctText(line.openRiskPct) : "—"}
        tone={line?.openRiskPct != null && line.limitPct != null && line.openRiskPct >= line.limitPct ? "danger" : line?.openRiskPct ? "amber" : "ink"}
        sub={line ? (line.limitPct != null ? `limit ${pctText(line.limitPct)}` : "limit not sent") : why ?? "—"} />
      <Kpi testId="mo-kpi-candidates" label="Candidates" value={cash == null && fnoN == null ? "—" : fmtNum((cash ?? 0) + (fnoN ?? 0))}
        sub={`${cash ?? "—"} cash · ${fnoN ?? "—"} F&O${scan ? ` · scan ${dayLabel(scan)}` : ""}`} />
      <Kpi testId="mo-kpi-feed" label="Feed" value={f.label} tone={f.tone}
        sub={`Kite${feed.ageSeconds != null && feed.mode === "live" ? ` · data ${fmtNum(feed.ageSeconds)}s old` : ""}${feed.session ? ` · session ${feed.session}` : ""}`} />
    </div>
  );
}

/** The open book, read-only: what the risk service counts. Every trade's levels and P/L are on Trade Desk. */
export function PaperTradesPanel({ onOpen }: { onOpen: () => void }) {
  const { mobile } = useCopilotShell();
  const rp = useRiskProfile();
  const live = rp.data?.live ?? null;
  const open = live?.open ?? null;
  const held = open?.heldSymbols ?? [];
  const more = open?.positions != null ? Math.max(0, open.positions - held.length) : 0;
  return (
    <Widget id="overview.paper" testId="mo-paper" title="Paper trades" meta={<span style={{ fontSize: 9.5 }}>Read-only · the risk service’s book</span>}
      actions={<button type="button" data-testid="mo-paper-all" onClick={onOpen} className="cp-chip">Paper Trading ›</button>} bodyStyle={{ padding: mobile ? 14 : 18 }}>
      <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
        {rp.isPending ? <span style={quiet}>Reading your open positions…</span> : !live ? (
          <span data-testid="mo-paper-error" style={quiet}>Open positions didn’t load{rp.data?.liveError ? `: ${rp.data.liveError}` : ""}.</span>
        ) : (
          <>
            <span data-testid="mo-paper-summary" className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>
              {open?.positions == null ? "Open positions unknown" : open.positions === 0 ? "No open positions" : `${open.positions} open position${open.positions === 1 ? "" : "s"}`}
              {open?.exposureRs ? ` · exposure ${fmtINR(open.exposureRs)}` : ""}{open?.riskRs ? ` · open risk ${fmtINR(open.riskRs)}` : ""}
            </span>
            {held.length > 0 && (
              <ul data-testid="mo-paper-list" className="m-0 p-0" style={{ listStyle: "none" }}>
                {held.map((s) => (
                  <li key={s} style={{ borderTop: "1px solid var(--cp-line)" }}>
                    <button type="button" data-testid="mo-paper-row" data-symbol={s} onClick={onOpen} className="flex w-full items-center"
                      style={{ gap: 10, padding: "9px 0", border: 0, background: "none", cursor: "pointer", color: "var(--cp-ink)", textAlign: "left" }}>
                      <StockIcon symbol={s} size={18} />
                      <span className="cp-num" style={{ fontSize: 12.5, flex: 1 }}>{s}</span>
                      <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>Shares</span>
                      <span style={{ fontSize: 12, color: "var(--mint)" }}>Trade Desk ›</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {more > 0 && <span data-testid="mo-paper-more" style={quiet}>{more} more (F&amp;O structures or repeat holdings) on Trade Desk.</span>}
            <span style={{ ...quiet, fontSize: 11.5 }}>
              Each trade’s entry, stop, P/L and exits are on Trade Desk ·{" "}
              <button type="button" data-testid="mo-paper-link" onClick={onOpen} style={link}>Paper Trading ›</button>
            </span>
          </>
        )}
      </div>
    </Widget>
  );
}
