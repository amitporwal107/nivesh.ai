/**
 * Scan dashboard — "Strong signals (score ≥ 70)" (docs/scan_builder/DESIGN.md §11; owner 4 Nov: "process only those signals
 * where signal strength is above 70% … fundamentally and technically good … positional"). Shown when the answer carries
 * `scores_meta` (a backend with signal strength); an older answer keeps the §10 feed (SignalsPanel.tsx).
 *
 * One card per stock whose score reached the threshold today, newest first: its score (when recorded, and now if different),
 * the five parts against their maxima (Quality /30 · Trend /25 · Reason /20 · Size /15 · Participation /10) and the penalties,
 * the reasons as chips, the positional plan frozen when it reached the threshold — in the owner's words for this screen,
 * "Entry · Stop loss · Target 1 · Target 2" and "Trend exit" (his exception to the 3 Nov wording rule, so those blocks are
 * marked data-plan-words; the rest of the page keeps the rule) — the lists it is in, and the price now. The other signalled
 * stocks (below 70, or not scored) are in "Signals by company" under this panel (SignalsByCompany.tsx, §11.1), which replaced
 * the "Below 70" fold that sat here. Browser alerts announce only new strong signals (useStrongAlerts).
 */
import { useMemo, useState, type MouseEvent } from "react";
import type { ListRef, ScoreParts, ScoresMeta, SignalsMeta, StockScore, StockScores, StrongSignal } from "./market-dashboard-data";
import { useStrongAlerts } from "./signal-alerts";
import { AlertsControl, istHm } from "./SignalsPanel";

const fmt2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const n2 = (v: number | null | undefined): string | null => (typeof v === "number" && Number.isFinite(v) ? fmt2.format(v) : null);
const SHOWN = 20;
const PART_KEYS = [
  ["quality", "Quality", 30],
  ["trend", "Trend", 25],
  ["reason", "Reason", 20],
  ["size", "Size", 15],
  ["participation", "Participation", 10],
] as const;

/** "Quality 26/30 · Trend 25/25 · Reason 20/20 · Size 5/15 · Participation 7/10" (+ " · Penalties −5" when any). */
export function partsText(p: ScoreParts | null | undefined, weights: Record<string, number> = {}): string | null {
  if (!p) return null;
  const parts = PART_KEYS.map(([k, label, max]) => `${label} ${Math.round(p[k])}/${weights[k] ?? max}`);
  const pen = Math.abs(p.penalty);                     // the server sends it as a negative part (−5); older fixtures as 5
  if (pen > 0) parts.push(`Penalties −${Math.round(pen)}`);
  return parts.join(" · ");
}

const listText = (lists: ListRef[]): string => lists.map((l) => l.title || l.id).join(" · ");
const scoreText = (v: number | null | undefined): string | null => (typeof v === "number" && Number.isFinite(v) ? `${Math.round(v)}/100` : null);

function SymLink({ sym, chartHref, onOpenSymbol, testId }: { sym: string; chartHref: (s: string) => string; onOpenSymbol: (s: string) => void; testId: string }) {
  return (
    <a data-testid={testId} data-symbol={sym} href={chartHref(sym)} title={`Open ${sym} in Chart Analysis`}
      onClick={(e: MouseEvent<HTMLAnchorElement>) => {
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        onOpenSymbol(sym);
      }}
      style={{ color: "var(--mint)", fontFamily: "var(--mono)", textDecoration: "none" }}>
      {sym} <span aria-hidden>↗</span>
    </a>
  );
}

export function StrongSignals({ strong, scores, meta, signalsMeta, ideaFor, chartHref, onOpenSymbol }: {
  strong: StrongSignal[];
  scores: StockScores;
  meta: ScoresMeta;
  signalsMeta: SignalsMeta | null;
  ideaFor: (sym: string) => { text: string; title: string } | null;
  chartHref: (s: string) => string;
  onOpenSymbol: (s: string) => void;
}) {
  const [all, setAll] = useState(false);
  const day = signalsMeta?.day || strong[0]?.first_strong.slice(0, 10) || "";
  const alerts = useStrongAlerts(strong, day);
  const threshold = meta.threshold;
  const ordered = useMemo(() => [...strong].sort((a, b) => b.first_strong.localeCompare(a.first_strong)), [strong]);
  const strongSyms = useMemo(() => new Set(strong.map((s) => s.symbol)), [strong]);
  // At or above the line without a recorded strong signal (it got there while signals were not being recorded, e.g. after the
  // close: no plan), highest score first. Everything below the line is in "Signals by company".
  const unrecorded = useMemo(() => Object.entries(scores)
    .filter(([sym, sc]) => !strongSyms.has(sym) && typeof sc.score === "number" && sc.score >= threshold)
    .sort(([a, x], [b, y]) => (y.score ?? -1) - (x.score ?? -1) || a.localeCompare(b)), [scores, strongSyms, threshold]);
  const shown = all ? ordered : ordered.slice(0, SHOWN);
  const asOf = Object.entries(meta.as_of).filter(([, v]) => !!v);

  return (
    <section data-testid="sd-strong" aria-label="Strong signals" className="cp-card flex min-w-0 flex-col" style={{ padding: 0, overflow: "hidden" }}>
      <header className="flex min-w-0 flex-wrap items-center" style={{ gap: "6px 10px", padding: "12px 14px 8px" }}>
        <h4 className="m-0" style={{ fontSize: 15, fontWeight: 600, color: "var(--cp-ink)" }}>Strong signals (score ≥ {threshold})</h4>
        <span data-testid="sd-strong-count" className="cp-pill" style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
          {strong.length.toLocaleString("en-IN")} today
        </span>
        <span style={{ flex: "1 1 auto" }} />
        <AlertsControl alerts={alerts} />
      </header>
      {strong.length === 0 ? (
        <p data-testid="sd-strong-empty" className="m-0" style={{ padding: "10px 14px 12px", borderTop: "1px solid var(--cp-line)", fontSize: 13, color: "var(--cp-ink-2)" }}>
          No stock has reached {threshold} today.{signalsMeta && !signalsMeta.recording ? " Strong signals are recorded while the market is open." : ""}
        </p>
      ) : (
        <ul className="m-0 cp-scroll" style={{ listStyle: "none", padding: 0, maxHeight: all ? 720 : undefined, overflow: all ? "auto" : undefined, borderTop: "1px solid var(--cp-line)" }}>
          {shown.map((s) => (
            <StrongCard key={s.symbol} s={s} now={scores[s.symbol] ?? null} weights={meta.weights} idea={ideaFor(s.symbol)} chartHref={chartHref} onOpenSymbol={onOpenSymbol} />
          ))}
        </ul>
      )}
      {unrecorded.length > 0 && (
        <ul data-testid="sd-unrecorded" className="m-0" style={{ listStyle: "none", padding: 0, borderTop: "1px solid var(--cp-line)" }}>
          {unrecorded.map(([sym, sc]) => (
            <li key={sym} data-testid="sd-unrecorded-item" data-symbol={sym} className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px", padding: "7px 14px", fontSize: 12.5, borderBottom: "1px solid var(--cp-line)" }}>
              <SymLink sym={sym} chartHref={chartHref} onOpenSymbol={onOpenSymbol} testId="sd-unrecorded-sym" />
              <span className="cp-pill" style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--mint)" }}>{scoreText(sc.score)}</span>
              <span data-testid="sd-unrecorded-note" style={{ color: "var(--cp-ink-3)" }}>
                At or above {threshold} now, while no signals were being recorded (outside the session), so it carries no plan.
              </span>
            </li>
          ))}
        </ul>
      )}
      {ordered.length > SHOWN && (
        <button type="button" data-testid="sd-strong-toggle" onClick={() => setAll((v) => !v)}
          style={{ alignSelf: "flex-start", border: 0, background: "none", padding: "8px 14px", cursor: "pointer", font: "inherit", fontSize: 12.5, color: "var(--mint)" }}>
          {all ? "Show fewer" : `Show all ${ordered.length.toLocaleString("en-IN")}`}
        </button>
      )}
      {(meta.rules || meta.plan_rules || meta.caveat || asOf.length > 0 || meta.warnings.length > 0) && (
        <div data-testid="sd-strong-foot" style={{ padding: "8px 14px 12px", borderTop: "1px solid var(--cp-line)", fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          {meta.warnings.map((w, i) => <p key={i} data-testid="sd-strong-warning" className="m-0" style={{ color: "var(--amber)" }}>{w}</p>)}
          {meta.rules && <p data-testid="sd-strong-rules" className="m-0">{meta.rules}</p>}
          {meta.plan_rules && <p data-testid="sd-strong-plan-rules" data-plan-words="true" className="m-0">{meta.plan_rules}</p>}
          {meta.caveat && <p data-testid="sd-strong-caveat" data-plan-words="true" className="m-0">{meta.caveat}</p>}
          {asOf.length > 0 && (
            <p data-testid="sd-strong-asof" className="m-0">Data as of: {asOf.map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}</p>
          )}
        </div>
      )}
    </section>
  );
}

function StrongCard({ s, now, weights, idea, chartHref, onOpenSymbol }: {
  s: StrongSignal; now: StockScore | null; weights: Record<string, number>; idea: { text: string; title: string } | null;
  chartHref: (s: string) => string; onOpenSymbol: (s: string) => void;
}) {
  const scoreNow = typeof s.score_now === "number" ? s.score_now : now?.score ?? null;
  const changed = typeof scoreNow === "number" && typeof s.score_at === "number" && Math.round(scoreNow) !== Math.round(s.score_at);
  const parts = partsText(now?.parts ?? s.parts_at, weights);
  const reasons = now?.reasons.length ? now.reasons : s.reasons_at;
  const penalties = now?.penalties ?? [];
  const lists = now?.lists.length ? now.lists : s.lists_at;
  const move = s.move_since_pct;
  const moveTone = typeof move === "number" && Number.isFinite(move) ? (move < 0 ? "var(--cp-danger)" : "var(--mint)") : "var(--cp-ink-3)";
  const rr = [s.rr_1, s.rr_2].filter((v): v is number => typeof v === "number" && Number.isFinite(v)).map((v) => fmt2.format(v).replace(/\.00$/, "")).join(" / ");
  const levels = [
    n2(s.entry) ? `Entry ${n2(s.entry)}` : null,
    n2(s.stop_loss) ? `Stop loss ${n2(s.stop_loss)}` : null,
    n2(s.target_1) ? `Target 1 ${n2(s.target_1)}` : null,
    n2(s.target_2) ? `Target 2 ${n2(s.target_2)}` : null,
  ].filter(Boolean).join(" · ");
  const planTitle = [
    n2(s.atr) ? `ATR(14) ${n2(s.atr)}` : null,
    n2(s.risk_per_share) ? `risk ${n2(s.risk_per_share)} a share` : null,
    s.rules ? `rules ${s.rules}` : null,
  ].filter(Boolean).join(" · ");
  return (
    <li data-testid="sd-strong-item" data-symbol={s.symbol} data-plan={s.plan_ok ? "true" : "false"}
      className="flex min-w-0 flex-col" style={{ gap: 4, padding: "10px 14px", borderBottom: "1px solid var(--cp-line)" }}>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px", fontSize: 13 }}>
        <span data-testid="sd-strong-time" className="cp-mono-note" style={{ color: "var(--cp-ink-2)" }} title="When the score first reached the line today (IST)">
          {istHm(s.first_strong) ?? "–"}
        </span>
        <SymLink sym={s.symbol} chartHref={chartHref} onOpenSymbol={onOpenSymbol} testId="sd-strong-sym" />
        {s.name && <span data-testid="sd-strong-name" style={{ color: "var(--cp-ink-3)", fontSize: 12 }}>{s.name}</span>}
        <span data-testid="sd-strong-score" className="cp-pill" style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--mint)", borderColor: "var(--mint)" }}>
          {scoreText(s.score_at) ?? "–"}
        </span>
        {changed && (
          <span data-testid="sd-strong-score-now" className="cp-mono-note" style={{ color: "var(--cp-ink-2)" }}>
            {Math.round(s.score_at as number)} when recorded · {Math.round(scoreNow as number)} now
          </span>
        )}
        <span style={{ flex: "1 1 auto" }} />
        {n2(s.price_now) && (
          <span data-testid="sd-strong-now" className="cp-num" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
            Now {n2(s.price_now)}
            {typeof move === "number" && Number.isFinite(move) && <span style={{ color: moveTone }}> · {move > 0 ? "+" : ""}{fmt2.format(move)}%</span>}
          </span>
        )}
      </div>
      {parts && <div data-testid="sd-strong-parts" className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>{parts}</div>}
      {reasons.length > 0 && (
        <div className="flex min-w-0 flex-wrap" style={{ gap: 4 }}>
          {reasons.map((r, i) => (
            <span key={i} data-testid="sd-strong-reason" className="cp-pill" style={{ fontSize: 11, color: "var(--cp-ink-2)" }}>{r}</span>
          ))}
        </div>
      )}
      {penalties.length > 0 && (
        <div className="flex min-w-0 flex-wrap" style={{ gap: "2px 10px" }}>
          {penalties.map((p, i) => (
            <span key={i} data-testid="sd-strong-penalty" style={{ fontSize: 11.5, color: "var(--amber)" }}>{p.text} −{Math.round(p.points)}</span>
          ))}
        </div>
      )}
      {s.plan_ok ? (
        <div data-plan-words="true" className="flex min-w-0 flex-col" style={{ gap: 2 }}>
          <div data-testid="sd-strong-plan" title={planTitle || undefined} className="cp-num" style={{ fontSize: 12.5, color: "var(--cp-ink)" }}>
            {levels}{rr ? <span style={{ color: "var(--cp-ink-2)" }}> · R:R {rr}</span> : null}
          </div>
          {s.trend_exit && <div data-testid="sd-strong-exit" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>Trend exit: {s.trend_exit}</div>}
        </div>
      ) : (
        <div data-testid="sd-strong-noplan" data-plan-words="true" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>{s.plan_note || "No plan for this signal."}</div>
      )}
      {lists.length > 0 && (
        <div data-testid="sd-strong-lists" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>In today's lists: {listText(lists)}</div>
      )}
      {idea && (
        <div data-testid="sd-strong-idea" title={idea.title} style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>Strategy idea: {idea.text}</div>
      )}
    </li>
  );
}
