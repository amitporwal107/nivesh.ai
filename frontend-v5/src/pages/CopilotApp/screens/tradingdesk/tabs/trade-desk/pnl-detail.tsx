/**
 * P&L dashboard v2 — one position opened (the design's expanded row): P&L breakdown · fills · actions (Modify risk, Simulate
 * exit / Initiate exit), the candle chart (Chart Analysis' AnalysisChart on GET /api/desk/live-chart, 15 min, with the
 * position's TARGET 1 / ENTRY / STOP / LTP lines) beside the trade journal (signals at entry, GET /api/desk/pnl/journal/{id}),
 * and the trade's own P&L curve (GET /api/desk/pnl/timeseries?trade=).
 *
 * Writes: Modify risk (PATCH /api/desk/paper-trades/{id}/levels, paper share trades, in force from the next session) and
 * Simulate exit (the Live desk's own close, POST /api/desk/paper-trades/{id}/close: at the last end-of-day close). A live
 * (broker) position is read-only: nothing here places, modifies or cancels a broker order.
 */
import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { Btn, LoadingBlock, fmtINR, fmtPct } from "../../../../components/ui";
import { QueryProblem } from "../../../trading/parts";
import { useClosePaperTrade, writeProblem } from "../../desk-trading";
import type { DailyBar } from "../../indicators";
import { AnalysisChart, type ChartLevel } from "./analysis/AnalysisChart";
import { useLiveChart } from "./live-chart-data";
import { quiet } from "./parts";
import {
  levelsProblem, newIdempotencyKey, useEditPaperLevels, useTradeCurve, useTradeJournal,
  type JournalParts, type LevelsBody, type LevelsSaved, type PnlPosition, type PnlStrategy,
} from "./pnl-data";
import { Executions, dayIST, hmIST, rs, timeIST } from "./pnl-parts";
import { MONO, NetCurve, Pill, SERIF, card, eyebrow, signColor } from "./pnl-ui";

const px = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const plainRs = (n: number | null) => (n == null || !Number.isFinite(n) ? "—" : `₹${Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);

const btn = (danger?: boolean): CSSProperties => ({
  cursor: "pointer", padding: "7px 13px", borderRadius: 10, fontSize: 13,
  border: `1px solid ${danger ? "var(--danger-line)" : "var(--line-3)"}`, background: danger ? "var(--danger-soft)" : "transparent", color: danger ? "var(--cp-danger)" : "var(--cp-ink)",
});
const fieldStyle: CSSProperties = { width: 120, padding: "6px 10px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink)", fontSize: 13, fontFamily: MONO };

function Line({ k, v, testId }: { k: string; v: ReactNode; testId?: string }) {
  return <div data-testid={testId} style={{ color: "var(--cp-ink-2)", fontSize: 13, lineHeight: 1.5, overflowWrap: "anywhere" }}>{k} · {v}</div>;
}

/** The trade id the paper writes and the journal take; a structure's legs share their structure's id. */
const tradeOf = (p: PnlPosition) => p.tradeId ?? p.positionId;
const isLive = (p: PnlPosition) => p.mode === "LIVE";

// ── P&L breakdown and fills ──────────────────────────────────────────────

function Breakdown({ p, strategy }: { p: PnlPosition; strategy: PnlStrategy | null }) {
  return (
    <div data-testid="pnl-breakdown" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <div style={eyebrow}>P&amp;L breakdown</div>
      <Line k="Invested value" v={fmtINR(p.investedValue)} />
      <Line k="Gross P&L" v={<span style={{ color: signColor(p.gross) }}>{rs(p.gross)}</span>} />
      <Line k="Est. charges" v={<>{plainRs(p.chargesEstimated)} (estimate, not settled)</>} />
      <Line k="Net P&L" v={<span data-testid="pnl-breakdown-net" style={{ color: signColor(p.net) }}>{rs(p.net)}</span>} />
      <Line k="Day P&L" v={rs(p.dayPnl)} />
      {isLive(p) && (
        <Line testId="pnl-broker-pnl" k="Broker's own P&L" v={<>{rs(p.brokerPnl)}{p.brokerReadAt ? ` at ${hmIST(p.brokerReadAt)}` : ""} (includes its realised part)</>} />
      )}
      {strategy && (
        <Line testId="pnl-structure-net" k="Structure" v={<>{strategy.summary ?? strategy.name} · net {rs(strategy.net)} (all legs){strategy.complete === false ? " — a leg has no price, so the total is not given" : ""}</>} />
      )}
    </div>
  );
}

function feedNote(p: PnlPosition, today: string | null): string {
  const problem = p.contractProblem ? `${p.contractProblem} ` : "";
  const read = isLive(p) ? `Read from ${p.account ?? "the broker"}${p.brokerReadAt ? ` at ${hmIST(p.brokerReadAt)}` : ""}. Nivesh places no order.` : "";
  if (p.priceStatus === "MISSING") return `${problem}No price: this position is left out of the totals.${read ? ` ${read}` : ""}`;
  if (p.priceStatus === "DELAYED") {
    const t = timeIST(p.priceAt);
    const other = p.priceDay && today && p.priceDay !== today ? ` on ${dayIST(p.priceDay)}` : "";
    // A live row's source says why it is not current (e.g. "Broker's last price on its read"); a paper row's is on its price badge.
    const source = isLive(p) && p.priceSource ? ` (${p.priceSource})` : "";
    return `${problem}Last known price${t ? ` from ${t}${other}` : ""}${source}: this P&L is not current.${read ? ` ${read}` : ""}`;
  }
  if (read) return `${problem}${read}`;
  return `${problem}Stop loss and target are the paper ledger's, checked on end-of-day bars at the evening check. Not a broker-side order.`;
}

function Fills({ p, today }: { p: PnlPosition; today: string | null }) {
  return (
    <div data-testid="pnl-fills" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <div style={eyebrow}>Fills</div>
      <Executions list={p.executions} empty={p.executionsNote ?? (isLive(p) ? "No fills read from the broker today." : "No fills recorded for this position.")} />
      {p.executions.length > 0 && p.executionsNote && <span style={{ ...quiet, fontSize: 12 }}>{p.executionsNote}</span>}
      <span data-testid="pnl-feed-note" style={{ ...quiet, fontSize: 12 }}>{feedNote(p, today)}</span>
    </div>
  );
}

// ── actions ──────────────────────────────────────────────────────────────

function LevelsForm({ p, onClose }: { p: PnlPosition; onClose: () => void }) {
  const [stop, setStop] = useState(p.stopLoss != null ? String(p.stopLoss) : "");
  const [target, setTarget] = useState(p.target != null ? String(p.target) : "");
  const [note, setNote] = useState("");
  // One idempotency key per request body: a retry of the same body reuses it (a timed-out save is not applied twice); a changed
  // body, e.g. after a refusal, gets a new one, so the server never sees one key with two bodies.
  const [last, setLast] = useState<{ key: string; body: string } | null>(null);
  const [local, setLocal] = useState<string | null>(null);
  const [saved, setSaved] = useState<LevelsSaved | null>(null);
  const edit = useEditPaperLevels();
  const submit = () => {
    setLocal(null);
    const s = stop.trim() ? Number(stop) : null;
    const t = target.trim() ? Number(target) : null;
    if (s == null && t == null) { setLocal("Give a stop loss or a target."); return; }
    if ((s != null && !(s > 0)) || (t != null && !(t > 0))) { setLocal("Levels must be positive prices."); return; }
    if (s != null && t != null && s >= t) { setLocal("The stop loss must be below the target."); return; }
    // Only what changed: an omitted level stays as it is (the screen never removes a target).
    const body: LevelsBody = {};
    if (s != null && s !== p.stopLoss) body.stop_price = s;
    if (t != null && t !== p.target) body.target_price = t;
    if (body.stop_price == null && body.target_price == null) { setLocal("Those are the levels already in force."); return; }
    if (note.trim()) body.note = note.trim();
    const json = JSON.stringify(body);
    const key = last && last.body === json ? last.key : newIdempotencyKey();
    setLast({ key, body: json });
    edit.mutate({ tradeId: tradeOf(p), body, key }, { onSuccess: (r) => { setSaved(r); setLast(null); } });
  };
  return (
    <div data-testid="pnl-levels-form" className="flex min-w-0 flex-col" style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)" }}>
      <div className="flex flex-wrap items-end" style={{ gap: 10 }}>
        <label className="flex flex-col" style={{ gap: 3, fontSize: 11.5, color: "var(--cp-ink-3)" }}>Stop loss
          <input data-testid="pnl-levels-stop" inputMode="decimal" value={stop} onChange={(e) => setStop(e.target.value)} style={fieldStyle} />
        </label>
        <label className="flex flex-col" style={{ gap: 3, fontSize: 11.5, color: "var(--cp-ink-3)" }}>Target
          <input data-testid="pnl-levels-target" inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} style={fieldStyle} />
        </label>
        <label className="flex min-w-0 flex-col" style={{ gap: 3, fontSize: 11.5, color: "var(--cp-ink-3)", flex: "1 1 140px" }}>Note (optional)
          <input data-testid="pnl-levels-note" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} style={{ ...fieldStyle, width: "100%", fontFamily: "inherit" }} />
        </label>
      </div>
      <span data-testid="pnl-levels-rule" style={{ ...quiet, fontSize: 12 }}>
        In force from the next session; today's bar is still checked against the current levels at the evening check. Current: stop loss {px(p.stopLoss)} · target {px(p.target)}.
      </span>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Btn variant="primary" data-testid="pnl-levels-save" disabled={edit.isPending} onClick={submit}>{edit.isPending ? "Saving…" : "Save levels"}</Btn>
        <Btn data-testid="pnl-levels-cancel" onClick={onClose}>{saved ? "Close" : "Cancel"}</Btn>
      </div>
      {(local || edit.isError) && <span data-testid="pnl-levels-error" role="alert" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>{local ?? levelsProblem(edit.error)}</span>}
      {saved && !edit.isError && (
        <span data-testid="pnl-levels-done" role="status" style={{ fontSize: 12.5, color: "var(--mint)" }}>
          {saved.replayed ? "Already saved. " : "Saved. "}The new levels are in force from {saved.pendingLevels?.fromSession ? dayIST(saved.pendingLevels.fromSession) : "the next session"}.
          {saved.levelRule ? <span style={{ color: "var(--cp-ink-3)" }}> {saved.levelRule}</span> : null}
        </span>
      )}
    </div>
  );
}

function ExitConfirm({ p, strategy, onClose }: { p: PnlPosition; strategy: PnlStrategy | null; onClose: () => void }) {
  const close = useClosePaperTrade();
  return (
    <div data-testid="pnl-exit-confirm" role="group" aria-label="Confirm the simulated exit" className="flex min-w-0 flex-col"
      style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
      <span style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--cp-ink)" }}>
        Close this paper trade at the last end-of-day close (the paper ledger's rule for a manual close)?{strategy || p.strategyId ? " This closes the whole structure, all its legs." : ""} Paper simulator only.
      </span>
      <div className="flex flex-wrap" style={{ gap: 8 }}>
        <Btn variant="primary" data-testid="pnl-exit-yes" disabled={close.isPending || close.isSuccess} onClick={() => close.mutate(tradeOf(p))}>
          {close.isSuccess ? "Closed" : close.isPending ? "Working…" : "Close at the last close"}
        </Btn>
        <Btn data-testid="pnl-exit-cancel" onClick={onClose}>{close.isSuccess ? "Done" : "Cancel"}</Btn>
      </div>
      {close.isError && <span data-testid="pnl-exit-error" role="alert" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>{writeProblem(close.error)}</span>}
      {close.isSuccess && <span data-testid="pnl-exit-done" role="status" style={{ fontSize: 12.5, color: "var(--mint)" }}>Closed in the paper ledger. The dashboard shows it with the next update.</span>}
    </div>
  );
}

function Actions({ p, strategy }: { p: PnlPosition; strategy: PnlStrategy | null }) {
  const [panel, setPanel] = useState<"none" | "levels" | "exit">("none");
  const live = isLive(p);
  const canEdit = !live && p.editableLevels;
  const why = live ? "Broker positions are read-only here."
    : p.strategyId ? "Option and futures structures keep their levels in this release."
      : !canEdit ? "This position's levels cannot be changed here." : null;
  return (
    <div data-testid="pnl-actions" className="flex min-w-0 flex-col items-start" style={{ gap: 10 }}>
      <div style={eyebrow}>Actions</div>
      <div className="flex flex-wrap" style={{ gap: 8 }}>
        <button type="button" data-testid="pnl-modify" disabled={!canEdit} aria-expanded={panel === "levels"} title={why ?? undefined}
          onClick={() => setPanel((v) => (v === "levels" ? "none" : "levels"))} style={{ ...btn(), opacity: canEdit ? 1 : 0.5, cursor: canEdit ? "pointer" : "not-allowed" }}>Modify risk</button>
        <button type="button" data-testid="pnl-exit" aria-expanded={panel === "exit"} onClick={() => setPanel((v) => (v === "exit" ? "none" : "exit"))} style={btn(true)}>
          {live ? "Initiate exit" : "Simulate exit"}
        </button>
      </div>
      {why && <span data-testid="pnl-modify-why" style={{ fontSize: 12.5, color: "var(--cp-ink-3)", lineHeight: 1.45 }}>{why}</span>}
      {p.pendingLevels && (
        <span data-testid="pnl-pending-levels" style={{ fontSize: 12.5, color: "var(--amber)", lineHeight: 1.45 }}>
          New levels saved: stop loss {px(p.pendingLevels.stopLoss)} · target {px(p.pendingLevels.target)}, in force from {p.pendingLevels.fromSession ? dayIST(p.pendingLevels.fromSession) : "the next session"}{p.pendingLevels.version != null ? ` (version ${p.pendingLevels.version})` : ""}.
        </span>
      )}
      {panel === "levels" && canEdit && <LevelsForm p={p} onClose={() => setPanel("none")} />}
      {panel === "exit" && (live
        ? <span data-testid="pnl-exit-note" role="status" style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--cp-ink-2)" }}>Nivesh is read-only with brokers: exit this position in your broker's app. No order has been placed.</span>
        : <ExitConfirm p={p} strategy={strategy} onClose={() => setPanel("none")} />)}
      {panel === "none" && <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)", lineHeight: 1.45 }}>{live ? "Read-only: no broker order can be placed from Nivesh." : "Paper simulator only."}</span>}
    </div>
  );
}

// ── the candle chart ─────────────────────────────────────────────────────

const PRICE_PILL: Record<string, { text: string; tone: "mint" | "amber" | "indigo" | "ink" | "danger" }> = {
  LIVE: { text: "LIVE", tone: "mint" }, DELAYED: { text: "STALE", tone: "amber" }, MISSING: { text: "NO PRICE", tone: "danger" },
  CLOSE: { text: "KITE CLOSE", tone: "indigo" }, EOD: { text: "EOD", tone: "ink" },
};

function levelsOf(p: PnlPosition, strategy: PnlStrategy | null): { levels: ChartLevel[]; note: string | null } {
  const lv = (key: string, value: number | null, label: string, color: string): ChartLevel[] => (value != null && Number.isFinite(value) ? [{ key, value, label, color }] : []);
  if (p.strategyId) {
    if (!strategy) return { levels: [], note: "The structure's levels are not in this answer." };
    return {
      levels: [...lv("target", strategy.targetUnderlying, "TARGET 1", "var(--mint)"), ...lv("stop", strategy.stopUnderlying, "STOP", "var(--cp-danger)"), ...lv("ltp", strategy.underlyingLtp, "LTP", "var(--amber)")],
      note: `${strategy.underlying ?? "Underlying"} chart with the structure's levels on the underlying; the leg's own price is a premium, not on this scale.`,
    };
  }
  if (p.segment !== "EQUITY") return { levels: [], note: "Underlying chart; this contract's own price is not on this scale, so no lines are drawn." };
  if (isLive(p)) return { levels: [...lv("entry", p.avgPrice, "ENTRY", "var(--cp-indigo)"), ...lv("ltp", p.ltp, "LTP", "var(--amber)")], note: "Broker positions have no stop loss or target here." };
  return {
    levels: [...lv("target", p.target, "TARGET 1", "var(--mint)"), ...lv("entry", p.avgPrice, "ENTRY", "var(--cp-indigo)"), ...lv("stop", p.stopLoss, "STOP", "var(--cp-danger)"), ...lv("ltp", p.ltp, "LTP", "var(--amber)")],
    note: null,
  };
}

function TradeChart({ p, strategy, sessionOpen, narrow }: { p: PnlPosition; strategy: PnlStrategy | null; sessionOpen: boolean; narrow: boolean }) {
  const sym = p.underlying ?? p.symbol;
  const q = useLiveChart(sym, null, sessionOpen, { interval: "15m", sessions: 2 });
  const [active, setActive] = useState<number | null>(null);
  const d = q.data;
  const bars: DailyBar[] = useMemo(() => (d?.bars ?? []).map(([day, o, h, l, c, v]) => ({ day, open: o, high: h, low: l, close: c, volume: v })), [d]);
  const { levels, note } = levelsOf(p, strategy);
  const pill = PRICE_PILL[p.priceStatus] ?? PRICE_PILL.MISSING;
  const last = bars[bars.length - 1];
  return (
    <div data-testid="pnl-trade-chart" className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", borderColor: "var(--line-2)", padding: "14px 16px", gap: 10 }}>
      <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
        <span style={{ fontFamily: MONO, fontSize: 13, fontWeight: 500, color: "var(--cp-ink)" }}>{sym ?? p.instrument}</span>
        <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>15M · IST</span>
        <Pill tone={pill.tone} testId="pnl-chart-pill" attrs={{ "data-status": p.priceStatus }}>{pill.text}</Pill>
        <div style={{ flex: 1 }} />
        {last && <span data-testid="pnl-chart-ohlc" style={{ fontFamily: MONO, fontSize: 11.5, color: "var(--cp-ink-2)" }}>O {px(last.open)} · H {px(last.high)} · L {px(last.low)} · C {px(last.close)}</span>}
      </div>
      {q.isPending && !!sym ? <LoadingBlock label="Reading the candles" rows={3} />
        : q.isError ? <div data-testid="pnl-trade-chart-error"><QueryProblem what={`The ${sym} chart`} error={q.error} onRetry={() => q.refetch()} /></div>
          : !sym || !bars.length || !d ? <span data-testid="pnl-trade-chart-empty" style={quiet}>No candles for {sym ?? p.instrument} in these sessions.</span>
            : (
              // Price and volume panes only: AnalysisChart also draws futures-OI panes below them, which this card leaves out.
              <div data-testid="pnl-trade-chart-plot" style={{ height: narrow ? 312 : 392, overflow: "hidden", borderRadius: 10, border: "1px solid var(--cp-line)", background: "var(--bg-0)" }}>
                <AnalysisChart bars={bars} intraday ema={d.ema20} marks={[]} confirms={[]} levels={levels} tradeLines={[]} last={d.last.price}
                  fut={null} futEmpty={null} buildups={[]} events={[]} ladder={null} ladderEmpty={null} compact={narrow} active={active} onActive={setActive}
                  viewKey={`pnl-${sym}`} />
              </div>
            )}
      {bars.length > 0 && levels.length > 0 && (
        <span data-testid="pnl-trade-chart-levels" style={{ ...quiet, fontSize: 11.5 }}>
          {levels.map((l, i) => {
            const off = offChart(bars, l.value);
            return <span key={l.key} data-testid="pnl-chart-level" data-key={l.key} data-off={off ? "true" : "false"}>{i ? " · " : ""}{l.label} {px(l.value)}{off ? " (outside these sessions' range, not drawn)" : ""}</span>;
          })}
        </span>
      )}
      {note && <span data-testid="pnl-trade-chart-note" style={{ ...quiet, fontSize: 11.5 }}>{note}</span>}
    </div>
  );
}

/** AnalysisChart's own rule: a level is drawn when it lies within 60% of the candles' span beyond their low / high. */
function offChart(bars: DailyBar[], v: number) {
  let a = Infinity, b = -Infinity;
  for (const c of bars) { a = Math.min(a, c.low); b = Math.max(b, c.high); }
  if (!Number.isFinite(a)) return false;
  const span = Math.max(b - a, b * 0.01);
  return v < a - span * 0.6 || v > b + span * 0.6;
}

// ── the trade journal (signals at entry) ─────────────────────────────────

const PARTS: Array<[keyof JournalParts, string, number]> = [["quality", "Quality", 30], ["trend", "Trend", 25], ["reason", "Reason", 20], ["size", "Size", 15], ["participation", "Participation", 10]];

/** "Quality 24/30 · Trend 16/25 · …" — the Scan dashboard's line; an unknown part shows "—", never 0. */
export function partsLine(p: JournalParts): string {
  const out = PARTS.map(([k, label, max]) => `${label} ${p[k] == null ? "—" : Math.round(p[k] as number)}/${max}`);
  if (p.penalty != null && Math.abs(p.penalty) > 0) out.push(`Penalties −${Math.round(Math.abs(p.penalty))}`);
  return out.join(" · ");
}

function JournalCard({ p }: { p: PnlPosition }) {
  const applicable = !isLive(p) && !p.strategyId && p.segment === "EQUITY";
  const q = useTradeJournal(applicable ? tradeOf(p) : null);
  let body: ReactNode;
  if (!applicable) {
    body = (
      <span data-testid="pnl-journal-none" style={{ fontSize: 13, color: "var(--cp-ink-2)", lineHeight: 1.5 }}>
        No entry signal recorded for this position. {isLive(p) ? "Broker positions record no entry signal." : "Option and futures structures record no scan signal."}
      </span>
    );
  } else if (q.isPending) body = <LoadingBlock label="Reading the signal at entry" rows={2} />;
  else if (q.isError) body = <div data-testid="pnl-journal-error"><QueryProblem what="The signal at entry" error={q.error} onRetry={() => q.refetch()} /></div>;
  else if (q.data.kind === "none") body = <span data-testid="pnl-journal-none" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>{q.data.why}</span>;
  else {
    const j = q.data.data;
    const g = j.signal;
    const own = j.trade;
    const ownLine = [own.entrySession ? `Entered ${dayIST(own.entrySession)}` : null, own.source?.kind ? `Opened from ${own.source.kind}${own.source.bucket ? ` ${own.source.bucket.replace(/_/g, " ")}` : ""}${own.source.signalDate ? ` (${dayIST(own.source.signalDate)})` : ""}` : null, own.rationale, own.note].filter(Boolean).join(" · ");
    if (!j.found || !g) {
      body = (
        <>
          <span data-testid="pnl-journal-why" style={{ fontSize: 13, color: "var(--cp-ink-2)", lineHeight: 1.5 }}>{j.why ?? `No scan signal for ${j.symbol ?? p.instrument} on its entry day.`}</span>
          {ownLine && <span data-testid="pnl-journal-trade" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>{ownLine}</span>}
        </>
      );
    } else {
      const chg = p.ltp != null && g.entry ? ((p.ltp - g.entry) / g.entry) * 100 : null;
      body = (
        <>
          <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
            <span data-testid="pnl-journal-when" style={{ fontFamily: MONO, fontSize: 12, color: "var(--cp-ink-3)" }}>{[dayIST(j.entryDay), g.firstStrong ? hmIST(g.firstStrong) : null].filter(Boolean).join(" ")}</span>
            <span style={{ fontFamily: MONO, fontSize: 14, fontWeight: 500, color: "var(--mint)" }}>{j.symbol ?? p.symbol}</span>
            <span data-testid="pnl-journal-score" style={{ padding: "3px 12px", borderRadius: 999, border: "1px solid var(--mint-line)", color: "var(--mint)", fontFamily: MONO, fontSize: 12 }}>
              {g.score == null ? "—" : Math.round(g.score)}/100
            </span>
            <div style={{ flex: 1 }} />
            <span style={{ fontFamily: MONO, fontSize: 12.5, color: "var(--cp-ink-2)" }}>
              Now {px(p.ltp)}{chg != null ? <> · <span style={{ color: signColor(chg) }}>{fmtPct(chg, { signed: true, digits: 2 })}</span> since the signal</> : null}
            </span>
          </div>
          {g.parts && <div data-testid="pnl-journal-parts" style={{ fontFamily: MONO, fontSize: 12.5, color: "var(--cp-ink-2)", lineHeight: 1.5 }}>{partsLine(g.parts)}</div>}
          {g.reasons.length > 0 && (
            <div className="flex flex-wrap" style={{ gap: 8 }}>
              {g.reasons.map((r, i) => (
                <span key={i} data-testid="pnl-journal-chip" style={{ padding: "6px 13px", borderRadius: 999, border: "1px solid var(--line-2)", color: "var(--cp-ink-2)", fontFamily: MONO, fontSize: 11, letterSpacing: "0.07em", textTransform: "uppercase", lineHeight: 1.35 }}>{r}</span>
              ))}
            </div>
          )}
          {g.kind === "strong" && g.planOk !== false ? (
            <div data-testid="pnl-journal-levels" style={{ fontFamily: MONO, fontSize: 12.5, color: "var(--cp-ink)", lineHeight: 1.6 }}>
              Entry {px(g.entry)} · Stop loss {px(g.stopLoss)} · Target 1 {px(g.target1)} · Target 2 {px(g.target2)}
              {g.rr1 != null || g.rr2 != null ? <span style={{ color: "var(--cp-ink-3)" }}> · R:R {g.rr1 ?? "—"} / {g.rr2 ?? "—"}</span> : null}
            </div>
          ) : (
            <span data-testid="pnl-journal-noplan" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>
              {g.planNote ?? (g.kind === "scored" ? "The day's score only: the stock did not reach 70, so no plan was frozen." : "No plan recorded.")}
            </span>
          )}
          {g.penalties.length > 0 && <div data-testid="pnl-journal-penalties" style={{ fontSize: 12.5, color: "var(--amber)", lineHeight: 1.5 }}>Penalties: {g.penalties.join(" · ")}</div>}
          {g.trendExit && <div data-testid="pnl-journal-exit" style={{ fontSize: 12.5, color: "var(--cp-ink-2)", lineHeight: 1.5 }}>{g.trendExit}</div>}
          {g.lists.length > 0 && <div data-testid="pnl-journal-lists" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>In the day's lists: {g.lists.map((l) => l.title).join(" · ")}</div>}
          {ownLine && <span data-testid="pnl-journal-trade" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>{ownLine}</span>}
        </>
      );
    }
  }
  return (
    <div data-testid="pnl-journal" className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", borderColor: "var(--line-2)", padding: "14px 16px", gap: 12 }}>
      <div className="flex items-center" style={{ gap: 10 }}>
        <span style={{ fontFamily: SERIF, fontSize: 20, color: "var(--cp-ink)" }}>Trade journal</span>
        <span style={eyebrow}>Signals at entry</span>
      </div>
      {body}
    </div>
  );
}

// ── the trade's P&L curve ────────────────────────────────────────────────

function TradeCurveCard({ p, sessionOpen }: { p: PnlPosition; sessionOpen: boolean }) {
  const id = isLive(p) ? p.positionId : tradeOf(p);
  const q = useTradeCurve(id, sessionOpen);
  const c = q.data;
  const net = c ? c.points.filter((x) => x.net != null) : [];
  const useGross = !!c && !net.length;
  const pts = useGross ? (c?.points ?? []).filter((x) => x.gross != null) : net;
  const values = pts.map((x) => (useGross ? x.gross : x.net) as number);
  const now = values.length ? values[values.length - 1] : null;
  const span = c?.sinceEntry === true ? `since entry${c.from ? ` (${dayIST(c.from)})` : ""}` : c?.sinceEntry === false ? `today's session${c.from ? ` (${dayIST(c.from)})` : ""}` : "";
  return (
    <div data-testid="pnl-trade-curve" data-since-entry={c?.sinceEntry == null ? "" : String(c.sinceEntry)} className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", borderColor: "var(--line-2)", padding: "14px 16px", gap: 10, gridColumn: "1/-1" }}>
      <div className="flex flex-wrap items-baseline" style={{ gap: 12 }}>
        <span style={{ fontFamily: SERIF, fontSize: 20, color: "var(--cp-ink)" }}>Trade P&amp;L</span>
        <span data-testid="pnl-trade-curve-span" style={eyebrow}>{useGross ? "Gross" : "Net of est. charges"}{span ? ` · ${span}` : ""}</span>
        <div style={{ flex: 1 }} />
        {values.length > 0 && <span style={{ fontFamily: MONO, fontSize: 11.5, color: "var(--cp-ink-2)" }}>HIGH {rs(Math.max(...values))} · LOW {rs(Math.min(...values))}</span>}
        <span data-testid="pnl-trade-curve-now" className="cp-num" style={{ fontFamily: SERIF, fontSize: 26, color: signColor(now ?? p.net) }}>{rs(now ?? p.net)}</span>
      </div>
      {q.isPending ? <LoadingBlock label="Reading this trade's candles" rows={2} />
        : q.isError ? <div data-testid="pnl-trade-curve-error"><QueryProblem what="This trade's P&L curve" error={q.error} onRetry={() => q.refetch()} /></div>
          : !values.length ? <span data-testid="pnl-trade-curve-empty" style={quiet}>No points for this trade: {c?.missing.map((m) => m.reason).join("; ") || "no candles yet"}.</span>
            : <NetCurve values={values} height={150} testId="pnl-trade-curve-plot" label="This trade's P&L" />}
      {c && c.notes.length > 0 && <span data-testid="pnl-trade-curve-notes" style={{ ...quiet, fontSize: 11 }}>{c.notes.join(" ")}</span>}
      {c?.basis && <span data-testid="pnl-trade-curve-basis" style={{ ...quiet, fontSize: 11 }}>{c.basis}{c.chargesEstimated != null ? ` Est. charges taken off: ₹${c.chargesEstimated.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}.` : ""}</span>}
    </div>
  );
}

// ── the whole detail ─────────────────────────────────────────────────────

export function PositionDetail({ p, strategy, today, sessionOpen, narrow }: {
  p: PnlPosition; strategy: PnlStrategy | null; today: string | null; sessionOpen: boolean; narrow: boolean;
}) {
  return (
    <div data-testid="pnl-row-detail" data-id={p.positionId} className="grid min-w-0"
      style={{ padding: narrow ? "12px 10px 14px" : "16px 22px 20px", background: "var(--bg-2)", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))", gap: 20, fontSize: 13 }}>
      <Breakdown p={p} strategy={strategy} />
      <Fills p={p} today={today} />
      <Actions p={p} strategy={strategy} />
      <div className="grid min-w-0" style={{ gridColumn: "1/-1", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: 16 }}>
        <TradeChart p={p} strategy={strategy} sessionOpen={sessionOpen} narrow={narrow} />
        <JournalCard p={p} />
      </div>
      <TradeCurveCard p={p} sessionOpen={sessionOpen} />
    </div>
  );
}

