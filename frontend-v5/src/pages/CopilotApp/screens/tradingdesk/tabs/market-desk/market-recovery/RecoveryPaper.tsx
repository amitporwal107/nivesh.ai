/**
 * Market Desk › Market Recovery — part 6, "Paper trades (live)" (owner, 4 Nov 2026; docs/market_recovery/DESIGN.md §10 E).
 *
 * The top 10 leading-sector candidates, each with the structure the plan chose (the highest reward : risk after costs among the
 * shares plan and the option strategies that passed their checks, at live prices, sized by the user's risk gate), why, and the
 * alternatives on expand; a button that opens them in the PAPER account through the desk's own engine (one POST per stock with
 * the plan's Idempotency-Key, each answer or refusal shown); and the live book: open trades at live marks (polled every 30 s while
 * quotes are live) and the ones closed today, with live closes at the Stop loss / Target 1. Nothing here places an order.
 *
 * Wording: "Buy" / "Sell" appear only as a leg verb before its lot count, and the level words are the page's own exception
 * (Entry zone · Stop loss · Target 1 · Target 2); the entry price is "Opened at", how a trade ended is "How it closed".
 */
import { Fragment, useState, type CSSProperties, type ReactNode } from "react";
import { LoadingBlock, Pill, type Tone } from "../../../../../components/ui";
import { recoveryProblem } from "./market-recovery-data";
import {
  openable, useOpenRecoveryTrades, usePaperLive, usePaperPlan,
  type BodyLeg, type LiveTrade, type Market, type OpenResult, type PaperLive, type PaperPlan, type PlanCandidate, type PlanItem,
} from "./market-recovery-paper";

// ── formatting ───────────────────────────────────────────────────────────────────────────────────────────────────────

const DASH = "—";
const MINUS = "−";
const price = (v: number | null | undefined) => (v == null ? DASH : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const lvl = (v: number | null | undefined) => (v == null ? DASH : v.toLocaleString("en-IN", { maximumFractionDigits: 2 }));
const rs = (v: number | null | undefined, signed = false) =>
  v == null ? DASH : `${signed ? (v < 0 ? MINUS : v > 0 ? "+" : "") : v < 0 ? MINUS : ""}₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const rsWhole = (v: number | null | undefined) => (v == null ? DASH : `₹${Math.round(v).toLocaleString("en-IN")}`);
const pct = (v: number | null | undefined) => (v == null ? DASH : `${v < 0 ? MINUS : v > 0 ? "+" : ""}${Math.abs(v).toFixed(2)}%`);
const tone = (v: number | null | undefined) => (v == null ? "var(--cp-ink-4)" : v > 0 ? "var(--mint)" : v < 0 ? "var(--cp-danger)" : "var(--cp-ink-2)");
function hhmm(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" })} IST`;
}

const note: CSSProperties = { fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const th: CSSProperties = {
  padding: "7px 8px", textAlign: "left", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase",
  color: "var(--cp-ink-4)", fontWeight: 500, borderBottom: "1px solid var(--cp-line)", whiteSpace: "nowrap", verticalAlign: "bottom",
};
const thR: CSSProperties = { ...th, textAlign: "right" };
const td: CSSProperties = {
  padding: "8px 8px", fontSize: 12.5, color: "var(--cp-ink-2)", borderBottom: "1px solid var(--cp-line)", fontFamily: "var(--mono)",
  fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", verticalAlign: "top",
};
const tdR: CSSProperties = { ...td, textAlign: "right" };
const tdText: CSSProperties = { ...td, fontFamily: "var(--sans)", whiteSpace: "normal" };
const sub: CSSProperties = { display: "block", fontSize: 11, lineHeight: 1.45, color: "var(--cp-ink-3)", whiteSpace: "normal" };
const linkBtn: CSSProperties = { padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", color: "var(--mint)", textAlign: "left" };
const btn = (on: boolean): CSSProperties => ({
  padding: "8px 16px", borderRadius: 999, fontSize: 13, cursor: on ? "pointer" : "not-allowed",
  border: `1px solid ${on ? "var(--mint)" : "var(--cp-line)"}`, background: on ? "var(--mint)" : "transparent",
  color: on ? "var(--cp-bg, #071017)" : "var(--cp-ink-4)",
});

/** The market's live state from the plan / live answer: Kite live, Kite login needed, quotes unreadable, or not open. */
function marketState(m: Market): { label: string; tone: Tone; line: string } {
  if (m.live) return { label: "Kite live", tone: "mint", line: `Live Kite quotes${hhmm(m.asOf) ? ` at ${hhmm(m.asOf)}` : ""}: trades open at live prices and close live at the Stop loss or Target 1.` };
  if (m.why === "feed_not_live") return { label: "Kite login needed", tone: "amber", line: "The Kite live feed is not running: the daily Kite login is needed before anything can be opened or closed live." };
  if (m.why === "unreadable") return { label: "Quotes not readable", tone: "danger", line: "The live quotes could not be read just now; nothing can be opened until they are." };
  return { label: "Market not open", tone: "ink", line: "The market is not open, so no live price exists: the plan shows, but nothing can be opened now." };
}

const EXIT_TEXT: Record<string, string> = {
  stop_live: "Stop loss hit (live)",
  target_live: "Target 1 reached (live)",
  stop: "Stop loss hit (end of day)",
  target: "Target 1 reached (end of day)",
  manual: "Closed by you",
  expiry: "Expired",
  time: "Held for the most sessions",
  trailing_stop: "Trailing level hit",
};
const FLAG_TEXT: Record<string, string> = { no_live_quote: "no live quote: P&L not shown" };

// ── pieces ───────────────────────────────────────────────────────────────────────────────────────────────────────────

/** "Buy 1 lot · 2,320 Put @ 64.30" for an option leg (the verb is followed by the lot count, always — the page's wording lint
 *  relies on it); a cash leg reads "425 shares @ 2,323.00". */
function bodyLegText(l: BodyLeg): string {
  if (l.kind === "cash") return `${(l.lots ?? 0).toLocaleString("en-IN")} shares @ ${price(l.entryPrice)}`;
  const verb = l.side === "sell" ? "Sell" : "Buy";
  const what = l.kind === "future" ? "Future" : `${lvl(l.strike)} ${l.optionType === "call" ? "Call" : "Put"}`;
  return `${verb} ${l.lots ?? 1} lot${l.lots === 1 ? "" : "s"} · ${what} @ ${price(l.entryPrice)}`;
}

function ChosenSummary({ c }: { c: PlanCandidate }) {
  if (c.key === "shares") {
    return (
      <span data-testid="mr-paper-legs" className="cp-num" style={{ ...sub, color: "var(--cp-ink-2)" }}>
        {(c.quantity ?? 0).toLocaleString("en-IN")} shares @ {price(c.entryPrice)} · Stop loss {lvl(c.stopPrice)} · Target 1 {lvl(c.targetPrice)}
      </span>
    );
  }
  return (
    <span data-testid="mr-paper-legs" className="flex flex-col" style={{ gap: 1 }}>
      {c.legs.map((l, i) => <span key={i} data-testid="mr-paper-leg" className="cp-num" style={{ ...sub, color: "var(--cp-ink-2)" }}>{bodyLegText(l)}</span>)}
      {(c.stopPrice != null || c.targetPrice != null) && (
        <span className="cp-num" style={sub}>underlying: Stop loss {lvl(c.stopPrice)} · Target 1 {lvl(c.targetPrice)}</span>
      )}
    </span>
  );
}

function sizeText(c: PlanCandidate): string {
  const a = c.approved;
  if (!a) return DASH;
  const n = c.key === "shares" ? a.quantity : a.lots;
  const unit = c.key === "shares" ? (n === 1 ? "share" : "shares") : (n === 1 ? "lot" : "lots");
  return n == null ? DASH : `${n.toLocaleString("en-IN")} ${unit}`;
}

function Alternatives({ item }: { item: PlanItem }) {
  return (
    <div data-testid="mr-paper-detail" data-symbol={item.symbol} className="flex min-w-0 flex-col" style={{ gap: 8, padding: "4px 2px 8px" }}>
      {item.chosen?.approved && (
        <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
          Risk gate: <span className="cp-num">{item.chosen.approved.outcome ?? DASH}</span>
          {item.chosen.approved.estimatedRiskRs != null && <> · estimated risk <span className="cp-num">{rs(item.chosen.approved.estimatedRiskRs)}</span></>}
          {item.chosen.approved.reasons.length > 0 && <> · {item.chosen.approved.reasons.map((r) => r.message ?? r.code).filter(Boolean).join("; ")}</>}
        </span>
      )}
      {item.chosen?.why && <span style={{ fontSize: 12.5, color: "var(--amber)" }}>{item.chosen.why}</span>}
      {item.alternatives.length > 0 ? (
        <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 4 }} data-testid="mr-paper-alts">
          {item.alternatives.map((a, i) => (
            <li key={`${a.key}-${i}`} data-testid="mr-paper-alt" data-key={a.key} data-eligible={a.eligible === null ? "unknown" : String(a.eligible)}
                className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "2px 10px", fontSize: 12.5, color: "var(--cp-ink-2)" }}>
              <span style={{ color: "var(--cp-ink)", minWidth: 150 }}>{a.label}</span>
              {a.rewardRiskNet != null && <span className="cp-num">reward : risk {a.rewardRiskNet.toFixed(2)}</span>}
              {a.maxLossRs != null && <span className="cp-num">max loss {rs(a.maxLossRs)}</span>}
              <span style={{ flex: "1 1 260px", minWidth: 0, color: "var(--cp-ink-3)" }}>
                {a.why ?? (a.eligible ? "Eligible, but a lower reward : risk after costs (or a larger maximum loss on a tie)." : "Not eligible.")}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <span style={note}>No other structure was considered for this stock.</span>
      )}
    </div>
  );
}

function ResultLine({ r }: { r: OpenResult | undefined }) {
  if (!r) return null;
  return (
    <span data-testid="mr-paper-result" data-ok={String(r.ok)} data-status={r.status ?? ""}
          style={{ ...sub, color: r.ok ? "var(--mint)" : "var(--cp-danger)" }}>
      {r.ok ? "✓ " : "✗ "}{r.text}
    </span>
  );
}

function PlanTable({ plan, results }: { plan: PaperPlan; results: Record<string, OpenResult> }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!plan.items.length) return <p className="m-0" data-testid="mr-paper-empty" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>No candidate to plan on this session.</p>;
  return (
    <div className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%", minWidth: 0 }} data-testid="mr-paper-plan-scroll">
      <table className="w-full" style={{ borderCollapse: "collapse", minWidth: 900 }}>
        <thead>
          <tr>
            <th style={th}>#</th><th style={th}>Stock</th><th style={th}>Chosen</th><th style={thR}>Size (risk gate)</th>
            <th style={thR}>Reward : risk after costs</th><th style={thR}>Max gain</th><th style={thR}>Max loss</th><th style={th}>Status</th>
          </tr>
        </thead>
        <tbody>
          {plan.items.map((it) => {
            const c = it.chosen;
            const isOpen = open === it.symbol;
            const state = it.openTrade ? "open" : c ? "ready" : "skipped";
            return (
              <Fragment key={it.symbol}>
                <tr data-testid="mr-paper-row" data-symbol={it.symbol} data-state={state} style={{ opacity: state === "skipped" ? 0.62 : 1 }}>
                  <td style={td}>{it.rank ?? DASH}</td>
                  <td style={tdText}>
                    <button type="button" data-testid="mr-paper-toggle" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : it.symbol)}
                            style={{ ...linkBtn, fontFamily: "var(--mono)", color: "var(--cp-ink)" }}>
                      {isOpen ? "▾" : "▸"} {it.symbol}
                    </button>
                    <span style={sub}>{[it.sector, it.score != null ? `score ${it.score.toFixed(1)}` : null].filter(Boolean).join(" · ")}</span>
                  </td>
                  <td style={tdText}>
                    {c ? (
                      <>
                        <span data-testid="mr-paper-chosen" data-key={c.key} style={{ color: "var(--cp-ink)" }}>{c.label}</span>
                        <ChosenSummary c={c} />
                      </>
                    ) : (
                      <span data-testid="mr-paper-skipped" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>{it.skippedReason ?? "Nothing qualifies."}</span>
                    )}
                  </td>
                  <td style={tdR} data-testid="mr-paper-size">{c ? sizeText(c) : DASH}{c?.approved?.outcome === "reduce" && <span style={sub}>reduced by the gate</span>}</td>
                  <td style={tdR} data-testid="mr-paper-rr">{c?.rewardRiskNet == null ? DASH : `${c.rewardRiskNet.toFixed(2)} : 1`}</td>
                  <td style={{ ...tdR, color: tone(c?.maxGainRs) }}>{c?.maxGainRs == null ? DASH : rs(c.maxGainRs, true)}</td>
                  <td style={{ ...tdR, color: tone(c?.maxLossRs) }}>{c?.maxLossRs == null ? DASH : rs(c.maxLossRs, true)}</td>
                  <td style={tdText}>
                    {it.openTrade ? <Pill tone="indigo">Already open</Pill> : c ? <Pill tone="mint">Ready</Pill> : <Pill tone="ink">Skipped</Pill>}
                    <ResultLine r={results[it.symbol]} />
                  </td>
                </tr>
                {isOpen && (
                  <tr data-testid="mr-paper-detail-row" data-symbol={it.symbol}>
                    <td colSpan={8} style={{ ...tdText, background: "var(--cp-card-2, transparent)" }}><Alternatives item={it} /></td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function liveLegText(t: LiveTrade): string[] {
  return t.legs.map((l) => {
    if (l.instrument === "Shares") return `${(l.lots ?? 0).toLocaleString("en-IN")} shares @ ${price(l.entry)} → ${price(l.live)}`;
    const what = l.instrument === "Future" ? "Future" : `${lvl(l.strike)} ${l.instrument}`;
    return `${l.action} ${l.lots ?? 1} lot${l.lots === 1 ? "" : "s"} · ${what} @ ${price(l.entry)} → ${price(l.live)}`;
  });
}

function LiveBook({ live }: { live: PaperLive }) {
  const t = live.totals;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }} data-testid="mr-paper-live">
      {t && (
        <div data-testid="mr-paper-totals" className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "4px 20px", fontSize: 13, color: "var(--cp-ink-2)" }}>
          <span>Open P&amp;L <span className="cp-num" data-testid="mr-paper-open-pnl" style={{ color: tone(t.openPnlRs) }}>{rs(t.openPnlRs, true)}</span>
            {!t.openPnlComplete && <span style={{ color: "var(--amber)" }}> (partial: a trade has no live quote)</span>}</span>
          <span>Realised today <span className="cp-num" data-testid="mr-paper-realised" style={{ color: tone(t.realisedTodayRs) }}>{rs(t.realisedTodayRs, true)}</span></span>
          <span className="cp-num">{t.openCount ?? 0} open · {t.closedTodayCount ?? 0} closed today</span>
          {live.market.live && <span style={note}>updates every 30 s</span>}
        </div>
      )}
      {live.trades.length ? (
        <div className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%", minWidth: 0 }}>
          <table className="w-full" style={{ borderCollapse: "collapse", minWidth: 980 }}>
            <thead>
              <tr>
                <th style={th}>Stock</th><th style={th}>Structure</th><th style={thR}>Opened at</th><th style={thR}>Live</th>
                <th style={thR}>P&amp;L</th><th style={thR}>P&amp;L % of risk</th><th style={thR}>Stop loss</th><th style={thR}>Target 1</th>
                <th style={th}>Status</th><th style={th}>How it closed</th>
              </tr>
            </thead>
            <tbody>
              {live.trades.map((x) => {
                const closed = x.status !== "open";
                const reason = x.exit?.reason ?? null;
                return (
                  <tr key={x.id} data-testid="mr-live-row" data-id={x.id} data-symbol={x.symbol ?? ""} data-status={x.status ?? ""} data-exit={reason ?? ""}>
                    <td style={td}>{x.symbol ?? DASH}{x.openedAt && <span style={sub}>opened {hhmm(x.openedAt) ?? x.openedAt}</span>}</td>
                    <td style={tdText}>
                      <span style={{ color: "var(--cp-ink)" }}>{x.label ?? x.kind ?? DASH}</span>
                      {x.kind === "shares" && x.quantity != null && <span className="cp-num" style={sub}>{x.quantity.toLocaleString("en-IN")} shares</span>}
                      {liveLegText(x).map((l, i) => <span key={i} data-testid="mr-live-leg" className="cp-num" style={sub}>{l}</span>)}
                      {x.flags.map((f) => <span key={f} style={{ ...sub, color: "var(--amber)" }}>{FLAG_TEXT[f] ?? f.replace(/_/g, " ")}</span>)}
                    </td>
                    <td style={tdR}>{price(x.entry)}</td>
                    <td style={tdR} data-testid="mr-live-price">{closed ? price(x.exit?.price ?? null) : price(x.live)}</td>
                    <td style={{ ...tdR, color: tone(x.pnlRs) }} data-testid="mr-live-pnl">{rs(x.pnlRs, true)}</td>
                    <td style={{ ...tdR, color: tone(x.pnlPct) }}>{pct(x.pnlPct)}</td>
                    <td style={tdR}>{lvl(x.stop)}</td>
                    <td style={tdR}>{lvl(x.target)}</td>
                    <td style={tdText}>{closed ? <Pill tone="ink">Closed</Pill> : <Pill tone="mint">Open</Pill>}</td>
                    <td style={tdText} data-testid="mr-live-exit">
                      {reason ? (
                        <>
                          <span style={{ color: "var(--cp-ink)" }}>{EXIT_TEXT[reason] ?? reason.replace(/_/g, " ")}</span>
                          <span className="cp-num" style={sub}>{x.exit?.price != null ? `at ${price(x.exit.price)}` : ""}{x.exit?.at ? ` · ${hhmm(x.exit.at) ?? x.exit.at}` : ""}</span>
                          {x.exit?.note && <span style={sub}>{x.exit.note}</span>}
                        </>
                      ) : DASH}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="m-0" data-testid="mr-live-empty" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>No Market Recovery paper trade is open, or closed today.</p>
      )}
      {live.notes.length > 0 && <ul className="m-0" style={{ paddingLeft: 18, ...note }}>{live.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
    </div>
  );
}

function Problem({ id, title, error, retry }: { id: string; title: string; error: unknown; retry: () => void }) {
  const p = recoveryProblem(error);
  return (
    <div role="alert" data-testid={id} data-code={p?.code ?? ""} className="flex flex-wrap items-start"
         style={{ gap: "8px 12px", padding: "10px 14px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--cp-danger-soft)" }}>
      <span className="cp-mono-note" style={{ color: "var(--cp-danger)", paddingTop: 2 }}>Error</span>
      <span style={{ flex: "1 1 240px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{title}{p?.message ? ` — ${p.message}` : ""}</span>
      <button type="button" onClick={retry} style={{ fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, cursor: "pointer" }}>Retry ›</button>
    </div>
  );
}

// ── the part ─────────────────────────────────────────────────────────────────────────────────────────────────────────

function PlanBlock({ plan, live }: { plan: PaperPlan; live: PaperLive | undefined }) {
  const opener = useOpenRecoveryTrades();
  const [confirming, setConfirming] = useState(false);
  // The state shown is the freshest read (the live book polls); opening needs the PLAN priced live, so the button reads the plan.
  const market = live?.market ?? plan.market;
  const ms = marketState(market);
  const todo = openable(plan);
  const canOpen = plan.market.live && todo.length > 0 && !opener.running;
  const done = Object.values(opener.results);
  const cap = plan.capital;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      <div className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "6px 14px" }}>
        <span data-testid="mr-paper-market" data-live={String(market.live)} data-why={market.why ?? ""}><Pill tone={ms.tone}>{ms.label}</Pill></span>
        <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)", flex: "1 1 320px", minWidth: 0 }}>{ms.line}</span>
      </div>
      {cap && (
        <div data-testid="mr-paper-capital" className="cp-num flex min-w-0 flex-wrap" style={{ gap: "4px 18px", fontSize: 12.5, color: "var(--cp-ink-2)" }}>
          <span>Paper capital <span style={{ color: "var(--cp-ink)" }}>{rsWhole(cap.startingCapitalRs)}</span></span>
          <span>cash {rsWhole(cap.cashRs)}</span>
          <span>blocked {rsWhole(cap.blockedRs)}</span>
          <span>available <span style={{ color: "var(--cp-ink)" }}>{rsWhole(cap.availableRs)}</span></span>
        </div>
      )}
      {plan.rule && <p className="m-0" data-testid="mr-paper-rule" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{plan.rule}</p>}
      <PlanTable plan={plan} results={opener.results} />
      <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
        {!confirming ? (
          <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "6px 12px" }}>
            <button type="button" data-testid="mr-paper-open" disabled={!canOpen} onClick={() => setConfirming(true)} style={btn(canOpen)}>
              Open paper trades for the top 10
            </button>
            <span style={note} data-testid="mr-paper-open-note">
              {opener.running ? "Opening, one stock at a time…"
                : !plan.market.live ? "Available while live Kite quotes are on."
                : todo.length === 0 ? "Nothing left to open: every candidate is open already or has nothing that qualifies."
                : `${todo.length} ready to open.`}
            </span>
          </div>
        ) : (
          <div role="dialog" aria-label="Confirm paper trades" data-testid="mr-paper-confirm" className="flex min-w-0 flex-col"
               style={{ gap: 10, padding: "12px 14px", borderRadius: 12, border: "1px solid var(--cp-line)", background: "var(--cp-card-2, transparent)" }}>
            <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink)" }}>
              Record {todo.length} paper trade{todo.length === 1 ? "" : "s"} in your paper account at live Kite prices: {todo.map((i) => i.symbol).join(", ")}.
            </span>
            <span style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
              Paper only — no broker order is placed. Each one goes through your risk gate; a refusal is shown and nothing is
              recorded for that stock.
            </span>
            <div className="flex flex-wrap" style={{ gap: 8 }}>
              <button type="button" data-testid="mr-paper-confirm-yes" style={btn(true)}
                      onClick={() => { setConfirming(false); void opener.run(todo); }}>
                Open {todo.length} paper trade{todo.length === 1 ? "" : "s"}
              </button>
              <button type="button" data-testid="mr-paper-confirm-no" onClick={() => setConfirming(false)}
                      style={{ padding: "8px 16px", borderRadius: 999, fontSize: 13, cursor: "pointer", border: "1px solid var(--cp-line)", background: "transparent", color: "var(--cp-ink-2)" }}>
                Cancel
              </button>
            </div>
          </div>
        )}
        {done.length > 0 && (
          <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 3 }} data-testid="mr-paper-results">
            {done.map((r) => (
              <li key={r.symbol} data-testid="mr-paper-result-line" data-symbol={r.symbol} data-ok={String(r.ok)} style={{ fontSize: 12.5, lineHeight: 1.5, color: r.ok ? "var(--cp-ink-2)" : "var(--cp-danger)" }}>
                <span className="cp-num" style={{ color: "var(--cp-ink)" }}>{r.symbol}</span> — {r.ok ? "" : "not opened: "}{r.text}
              </li>
            ))}
          </ul>
        )}
      </div>
      {plan.notes.length > 0 && <ul className="m-0" style={{ paddingLeft: 18, ...note }} data-testid="mr-paper-notes">{plan.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
    </div>
  );
}

export function RecoveryPaper() {
  const plan = usePaperPlan();
  const live = usePaperLive();
  let planBody: ReactNode;
  if (plan.isPending) planBody = <LoadingBlock label="Pricing the top 10 at live quotes and sizing each through your risk gate" rows={4} />;
  else if (plan.isError) planBody = <Problem id="mr-paper-error" title="The paper plan did not load" error={plan.error} retry={() => plan.refetch()} />;
  else planBody = <PlanBlock plan={plan.data} live={live.data} />;
  let liveBody: ReactNode;
  if (live.isPending) liveBody = <LoadingBlock label="Reading your Market Recovery paper trades at live prices" rows={2} />;
  else if (live.isError) liveBody = <Problem id="mr-live-error" title="The live paper book did not load" error={live.error} retry={() => live.refetch()} />;
  else liveBody = <LiveBook live={live.data} />;
  return (
    <section data-testid="mr-paper" aria-label="Paper trades (live)" className="cp-card flex min-w-0 flex-col" style={{ gap: 14, padding: "14px 16px" }}>
      <header className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "4px 12px" }}>
        <h3 className="cp-eyebrow m-0" style={{ flex: "1 1 auto" }}>6 · Paper trades (live)</h3>
        <span style={{ ...note, minWidth: 0 }}>Paper account only · no broker orders</span>
      </header>
      {planBody}
      <div className="flex min-w-0 flex-col" style={{ gap: 8, paddingTop: 10, borderTop: "1px solid var(--cp-line)" }}>
        <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>Live book · open, and closed today</span>
        {liveBody}
      </div>
    </section>
  );
}
