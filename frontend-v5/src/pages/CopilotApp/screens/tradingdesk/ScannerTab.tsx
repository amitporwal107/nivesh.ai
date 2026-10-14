/**
 * Smart trading desk — 02 AI Opportunity scanner: the end-of-day opportunity
 * list (design-spec §4), and the phone's M2 composition (§11).
 *
 *   GET /api/positional/watchlist?limit=30   setup buckets, close, trigger, stop      (useDeskScanner, desk-data.ts)
 *   GET /api/positional/picks?limit=30       scored picks with entry, stop, target    (useDeskScanner)
 *                                            both: spark_closes (last 24 daily closes, end of day) for the row's
 *                                            line and its last change, avg_traded_value_cr_20d for "Liquid only"
 *   GET /api/move-odds/latest?head=p_up5_1d  next-session estimates per stock, events on record, the model's
 *   GET /api/move-odds/latest?head=p_up10_1d own out-of-sample record                  (useDeskOdds)
 *
 * The score is the scanner's rules-based score (final_score × 100), not a
 * probability. "P(+5% next session)" is the move-odds model's estimate that
 * the next session's high reaches the previous close + 5% — one session only;
 * the design's P(+5%) / P(+10%) slots carry these two heads. "Liquid only"
 * keeps the stocks whose average daily traded value (close × volume) over the
 * last 20 sessions is at least ₹10 Cr; a stock the routes sent no traded
 * value for cannot pass, and the tab says how many those are.
 *
 * Shown as "—" because no route publishes it: "Hit rate · n" (a per-setup
 * back-tested record). The design's "Momentum" chip has no scanner bucket; the
 * chips are the scanner's four real buckets.
 */
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { EmptyBlock, ErrorBlock, LoadingBlock, Pill, TONE_COLOR, fmtNum, fmtPct, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { Sparkline } from "../markets/parts";
import { SymbolCell } from "../desk/parts";
import { fmtDay, fmtPrice } from "../trading/parts";
import { STATUS_LABEL, lastMove, oddsLabel, scanDateLabel, setupLabel, type UpHead } from "./chart-data";
import { useDesk } from "./context";
import {
  BUCKET_RULE, LIQUID_MIN_CR, useDeskOdds, useDeskScanner,
  type DeskOdds, type DeskSetup, type SetupBucket, type SetupStatus,
} from "./desk-data";

type RankBy = "score" | "p5" | "p10";
type Group = "all" | SetupBucket;

/** The design's chips (All · Breakouts · Momentum · Pullbacks), as the scanner's real buckets. */
const GROUPS: ReadonlyArray<{ key: Group; label: string }> = [
  { key: "all", label: "All" },
  { key: "breakout_confirmed", label: "Breakouts" },
  { key: "pre_breakout", label: "Near breakout" },
  { key: "trend_continuation", label: "Pullbacks" },
  { key: "true_accumulation", label: "Accumulation" },
];

const PARTIAL_NOTE: Record<"watchlist" | "picks", string> = {
  watchlist: "The setup watchlist (GET /api/positional/watchlist) did not answer, so only the scanner’s picks are listed.",
  picks: "The scanner picks (GET /api/positional/picks) did not answer, so only the setup watchlist is listed and no stock has a target.",
};

interface Row {
  s: DeskSetup;
  /** Move-odds P(+5%) and P(+10%) next session, 0–1; null when the model has no figure for the stock. */
  p5: number | null;
  p10: number | null;
  /** Events on record for the stock in the model's run. */
  events: number | null;
  /** % from the close (else the entry) to the target. */
  toTarget: number | null;
  /** Last close and its change, from the row's daily closes. */
  move: ReturnType<typeof lastMove>;
}

/** Descending, with missing values last. */
function desc(a: number | null, b: number | null): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return b - a;
}

const headOf = (rank: RankBy): UpHead => (rank === "p10" ? "p_up10_1d" : "p_up5_1d");
const pOf = (r: Row, head: UpHead) => (head === "p_up10_1d" ? r.p10 : r.p5);
const eyebrow95: CSSProperties = { fontSize: 9.5 };

// ── controls ─────────────────────────────────────────────────────────────

function RankBySwitch({ value, onChange, ready, plain, small }: { value: RankBy; onChange: (v: RankBy) => void; ready: Record<UpHead, boolean>; plain: boolean; small?: boolean }) {
  const options: Array<{ key: RankBy; label: string; disabled?: boolean; title?: string }> = [
    { key: "score", label: "Score", title: "The scanner’s rules-based score, 0–100" },
    { key: "p5", label: oddsLabel("p_up5_1d", plain), disabled: !ready.p_up5_1d, title: ready.p_up5_1d ? undefined : "Needs the move-odds model’s published estimates" },
    { key: "p10", label: oddsLabel("p_up10_1d", plain), disabled: !ready.p_up10_1d, title: ready.p_up10_1d ? undefined : "Needs the move-odds model’s published estimates" },
  ];
  return (
    <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
      <span className="cp-eyebrow" style={eyebrow95}>Rank by</span>
      <div
        role="group"
        aria-label="Rank by"
        className="inline-flex max-w-full flex-wrap"
        style={{ gap: 2, padding: small ? 2 : 3, borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}
      >
        {options.map((o) => {
          const on = o.key === value;
          return (
            <button
              key={o.key}
              type="button"
              aria-pressed={on}
              disabled={o.disabled}
              title={o.title}
              data-testid={`desk-scan-rank-${o.key}`}
              onClick={() => onChange(o.key)}
              style={{
                padding: small ? "5px 9px" : "6px 12px", borderRadius: 999, border: 0, whiteSpace: "nowrap",
                fontFamily: "var(--mono)", fontSize: small ? 9.5 : 10.5, letterSpacing: "0.08em",
                cursor: o.disabled ? "not-allowed" : "pointer", opacity: o.disabled ? 0.45 : 1,
                background: on ? "var(--bg-4)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
              }}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Filter chip (design-spec §1): 5px 11px, 12px; ON mint-soft, mint text, mint-line border. */
function Chip({ on, onClick, testId, children, title }: { on: boolean; onClick: () => void; testId: string; children: ReactNode; title?: string }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      data-testid={testId}
      title={title}
      onClick={onClick}
      style={{
        flex: "none", padding: "5px 11px", borderRadius: 999, fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)", whiteSpace: "nowrap",
        border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`,
        color: on ? "var(--mint)" : "var(--cp-ink-2)",
        background: on ? "var(--mint-soft)" : "transparent",
      }}
    >
      {children}
    </button>
  );
}

function GroupChips({ value, onChange }: { value: Group; onChange: (g: Group) => void }) {
  return (
    <div role="group" aria-label="Setup group" className="flex flex-wrap" style={{ gap: 6 }}>
      {GROUPS.map((g) => (
        <Chip key={g.key} on={g.key === value} onClick={() => onChange(g.key)} testId={`desk-scan-group-${g.key}`} title={g.key === "all" ? undefined : BUCKET_RULE[g.key]}>
          {g.label}
        </Chip>
      ))}
    </div>
  );
}

const LIQUID_TITLE = `Average daily traded value (close × volume) over the last 20 sessions of at least ₹${LIQUID_MIN_CR} Cr`;

/** The design's toggle switch: track 30 × 18, knob 12 × 12 sliding from 2px to 14px, label beside it. */
function LiquidSwitch({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      data-testid="desk-scan-liquid"
      title={LIQUID_TITLE}
      onClick={() => onChange(!on)}
      className="inline-flex items-center"
      style={{ gap: 8, padding: 0, border: 0, background: "none", cursor: "pointer", fontFamily: "var(--sans)", fontSize: 12, color: "var(--cp-ink-2)" }}
    >
      <span aria-hidden style={{ position: "relative", width: 30, height: 18, flex: "none", borderRadius: 999, border: "1px solid var(--line-2)", background: on ? "var(--mint-soft)" : "var(--bg-3)" }}>
        <span style={{ position: "absolute", top: 2, left: on ? 14 : 2, width: 12, height: 12, borderRadius: 999, background: on ? "var(--mint)" : "var(--cp-ink-3)", transition: "left .15s ease" }} />
      </span>
      <span data-testid="desk-scan-liquid-label">Liquid only · ADV ≥ ₹{LIQUID_MIN_CR} Cr</span>
    </button>
  );
}

// ── cells ────────────────────────────────────────────────────────────────

function ScoreText({ score, size = 23 }: { score: number | null; size?: number }) {
  if (score == null) return <span data-testid="desk-scan-score">—</span>;
  return (
    <span data-testid="desk-scan-score" style={{ fontFamily: "var(--display)", fontSize: size, lineHeight: 1, color: score >= 80 ? "var(--mint)" : "var(--cp-indigo)" }}>
      {fmtNum(score, 0)}
    </span>
  );
}

/** A 5px bar on a bg-3 track and the value in serif on the right; "—" and an empty bar when there is no figure. */
function OddsCell({ p, head }: { p: number | null; head: UpHead }) {
  return (
    <span className="flex w-full items-center" style={{ gap: 8, minWidth: 0 }}>
      <span aria-hidden style={{ position: "relative", flex: "1 1 auto", minWidth: 16, height: 5, borderRadius: 999, background: "var(--bg-3)" }}>
        <span style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${p == null ? 0 : Math.min(100, Math.max(0, p * 100))}%`, borderRadius: 999, background: "var(--mint)" }} />
      </span>
      <span data-testid="desk-scan-odds" data-head={head} style={{ flex: "none", fontFamily: "var(--display)", fontSize: 20, lineHeight: 1, color: p == null ? "var(--cp-ink-3)" : "var(--cp-ink)" }}>
        {p == null ? "—" : fmtPct(p * 100, { digits: 1 })}
      </span>
    </span>
  );
}

/** "+ 3 events · " when the model has filings / news on record for the stock, then the scanner's own reason. */
function PatternCell({ r, plain }: { r: Row; plain: boolean }) {
  const s = r.s;
  const why = s.why ?? s.reasons[0] ?? null;
  return (
    <span className="flex flex-col" style={{ gap: 2, minWidth: 0 }} title={[s.bucket ? BUCKET_RULE[s.bucket] : null, why].filter(Boolean).join(" ")}>
      <span data-testid="desk-scan-setup" style={{ fontSize: 13, fontWeight: 500, color: "var(--cp-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{setupLabel(s, plain)}</span>
      {(why || (r.events != null && r.events > 0)) && (
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {r.events != null && r.events > 0 && (
            <span data-testid="desk-scan-catalyst" style={{ color: "var(--cp-ink-2)" }}>+ {fmtNum(r.events)} {plain ? (r.events === 1 ? "news item" : "news items") : r.events === 1 ? "event" : "events"}{why ? " · " : ""}</span>
          )}
          {why && <span data-testid="desk-scan-why">{why}</span>}
        </span>
      )}
    </span>
  );
}

function StatusPill({ status }: { status: SetupStatus }) {
  return <span data-testid="desk-scan-status" data-status={status}><Pill tone={STATUS_LABEL[status].tone}>{STATUS_LABEL[status].label}</Pill></span>;
}

/** "₹510.00 +0.6%" — the last close and its change, from the row's daily closes; else the scan close or the entry. */
function StockSub({ r }: { r: Row }) {
  const s = r.s;
  if (r.move) {
    return (
      <span className="cp-num">
        {fmtPrice(r.move.close)}{" "}
        <span data-testid="desk-scan-change" style={{ color: TONE_COLOR[r.move.change > 0 ? "mint" : r.move.change < 0 ? "danger" : "ink"] }}>
          {fmtPct(r.move.changePct, { signed: true, digits: 1 })}
        </span>
      </span>
    );
  }
  if (s.close != null) return <span className="cp-num">Close {fmtPrice(s.close)}</span>;
  if (s.entry != null) return <span className="cp-num">Entry {fmtPrice(s.entry)}</span>;
  return <>{s.sector ?? ""}</>;
}

/** "₹12.4 Cr a day" — the 20-session average traded value. */
const tradedText = (cr: number | null) => (cr == null ? "No traded value" : `₹${fmtNum(cr, cr >= 100 ? 0 : 1)} Cr a day`);

function StockCell({ r, size = 24 }: { r: Row; size?: number }) {
  return (
    <span className="block min-w-0" title={`20-session average traded value: ${tradedText(r.s.avgTradedCr)}`}>
      <SymbolCell symbol={r.s.symbol} sub={<StockSub r={r} />} testId="desk-scan-symbol" size={size}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 12.5 }}>{r.s.symbol}</span>
      </SymbolCell>
    </span>
  );
}

/** The last daily closes as a line, coloured by where the last close sits against the first. */
function SparkCell({ s, width, height = 24 }: { s: DeskSetup; width: number; height?: number }) {
  const n = s.spark.length;
  if (n < 2) return <span data-testid="desk-scan-spark-none" className="cp-mono-note">No line</span>;
  const tone: Tone = s.spark[n - 1] > s.spark[0] ? "mint" : s.spark[n - 1] < s.spark[0] ? "danger" : "ink";
  return (
    <span data-testid="desk-scan-spark" data-points={n} data-tone={tone} title={`Last ${n} daily closes${s.sparkEnd ? ` to ${fmtDay(s.sparkEnd)}` : ""} (end of day)`} style={{ display: "block", width, maxWidth: "100%" }}>
      <Sparkline values={s.spark} tone={tone} height={height} />
    </span>
  );
}

const hitCell = <span data-testid="desk-scan-hit" className="cp-num" title="No per-setup back-tested record is published" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>—</span>;
const targetText = (r: Row) => fmtPct(r.toTarget, { signed: true, digits: 1 });

// ── table (wide), cards (narrow box) and the phone list ──────────────────

/** The design's columns: # · Stock · Score · P · Hit rate · n · Pattern / catalyst · To target · 24 sessions · Status. */
const COLS = "28px minmax(0,1.3fr) 56px minmax(0,1.1fr) 90px minmax(0,1.7fr) 60px 84px 108px";
const cellStyle: CSSProperties = { minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };

/** Width the table's columns need; a narrower box (the desk beside the docked Copilot) shows the rows as cards. */
const TABLE_MIN_WIDTH = 900;

/** True while the observed box is narrower than `below` px. Starts from `initial` until the box is measured. */
function useNarrowBox(box: HTMLElement | null, below: number, initial: boolean): boolean {
  const [narrow, setNarrow] = useState(initial);
  useEffect(() => {
    if (!box || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setNarrow(w < below);
    });
    ro.observe(box);
    return () => ro.disconnect();
  }, [box, below]);
  return narrow;
}

function columnHeads(head: UpHead, plain: boolean): Array<[string, string, "left" | "right"]> {
  return [
    ["rank", "#", "left"], ["stock", "Stock", "left"], ["score", "Score", "left"], ["odds", oddsLabel(head, plain), "left"],
    ["hit", plain ? "Past record" : "Hit rate · n", "left"], ["setup", plain ? "Why it shows up" : "Pattern / catalyst", "left"],
    ["target", "To target", "left"], ["spark", "24 sessions", "left"], ["status", "Status", "left"],
  ];
}

const rankText = (i: number) => String(i + 1).padStart(2, "0");

function ScanTable({ rows, selected, onOpen, head, plain }: { rows: Row[]; selected: string | null; onOpen: (sym: string) => void; head: UpHead; plain: boolean }) {
  return (
    <div role="table" aria-label="Scanner setups" data-testid="desk-scan-table">
      <div role="row" className="grid" style={{ gridTemplateColumns: COLS, gap: 12, padding: "10px 18px" }}>
        {columnHeads(head, plain).map(([k, label, align]) => (
          <span key={k} role="columnheader" data-testid={`desk-scan-col-${k}`} style={{ ...cellStyle, textAlign: align, fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>{label}</span>
        ))}
      </div>
      {rows.map((r, i) => {
        const on = r.s.symbol === selected;
        return (
          <div
            key={r.s.symbol}
            role="row"
            tabIndex={0}
            data-testid={`desk-scan-row-${r.s.symbol}`}
            data-selected={on}
            aria-current={on ? "true" : undefined}
            onClick={() => onOpen(r.s.symbol)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(r.s.symbol); } }}
            className="cp-row-link grid items-center"
            style={{ gridTemplateColumns: COLS, gap: 12, padding: "10px 18px", borderTop: "1px solid var(--cp-line)", fontSize: 13, color: "var(--cp-ink-2)", background: on ? "var(--bg-2)" : undefined }}
          >
            <span role="cell" data-testid="desk-scan-rank" className="cp-num" style={{ ...cellStyle, fontSize: 11, color: on ? "var(--mint)" : "var(--cp-ink-3)" }}>{rankText(i)}</span>
            <span role="cell" style={cellStyle}>
              <StockCell r={r} />
              <span className="sr-only" data-testid="desk-scan-traded">{tradedText(r.s.avgTradedCr)}</span>
            </span>
            <span role="cell" style={cellStyle}><ScoreText score={r.s.score} /></span>
            <span role="cell" style={cellStyle}><OddsCell p={pOf(r, head)} head={head} /></span>
            <span role="cell" style={cellStyle}>{hitCell}</span>
            <span role="cell" style={cellStyle}><PatternCell r={r} plain={plain} /></span>
            <span role="cell" data-testid="desk-scan-target" className="cp-num" style={{ ...cellStyle, fontSize: 12, color: r.toTarget == null ? "var(--cp-ink-3)" : TONE_COLOR.mint }}>{targetText(r)}</span>
            <span role="cell" style={cellStyle}><SparkCell s={r.s} width={84} /></span>
            <span role="cell" style={cellStyle}><StatusPill status={r.s.status} /></span>
          </div>
        );
      })}
    </div>
  );
}

/** The same fields, in the design's order, as one card per row — for a box too narrow for the nine columns. */
function ScanCards({ rows, selected, onOpen, head, plain }: { rows: Row[]; selected: string | null; onOpen: (sym: string) => void; head: UpHead; plain: boolean }) {
  const heads = Object.fromEntries(columnHeads(head, plain).map(([k, label]) => [k, label]));
  return (
    <div role="list" aria-label="Scanner setups" className="flex flex-col" data-testid="desk-scan-cards">
      {rows.map((r, i) => {
        const on = r.s.symbol === selected;
        return (
          <div key={r.s.symbol} role="listitem" style={{ borderTop: "1px solid var(--cp-line)" }}>
            <button
              type="button"
              data-testid={`desk-scan-row-${r.s.symbol}`}
              data-selected={on}
              aria-current={on ? "true" : undefined}
              onClick={() => onOpen(r.s.symbol)}
              className="cp-row-link flex w-full flex-col"
              style={{ gap: 10, padding: "12px 18px", border: 0, textAlign: "left", color: "var(--cp-ink-2)", fontFamily: "var(--sans)", fontSize: 13, background: on ? "var(--bg-2)" : "transparent" }}
            >
              <span className="flex w-full items-center" style={{ gap: 12, minWidth: 0 }}>
                <span data-testid="desk-scan-rank" className="cp-num" style={{ flex: "none", width: 20, fontSize: 11, color: on ? "var(--mint)" : "var(--cp-ink-3)" }}>{rankText(i)}</span>
                <span style={{ flex: "1 1 auto", minWidth: 0 }}><StockCell r={r} /></span>
                <span style={{ flex: "none" }}><ScoreText score={r.s.score} /></span>
              </span>
              <span className="flex w-full items-center justify-between" style={{ gap: 10, minWidth: 0 }}>
                <span style={{ minWidth: 0, flex: "1 1 auto" }}><PatternCell r={r} plain={plain} /></span>
                <span style={{ flex: "none" }}><StatusPill status={r.s.status} /></span>
              </span>
              <span className="grid w-full items-end" style={{ gridTemplateColumns: "minmax(0,1.6fr) minmax(0,0.8fr) minmax(0,0.8fr) minmax(0,1fr)", gap: 12 }}>
                <span className="flex min-w-0 flex-col" style={{ gap: 4 }}>
                  <span className="cp-eyebrow" style={{ ...eyebrow95, ...cellStyle }}>{heads.odds}</span>
                  <OddsCell p={pOf(r, head)} head={head} />
                </span>
                <span className="flex min-w-0 flex-col" style={{ gap: 4 }}>
                  <span className="cp-eyebrow" style={{ ...eyebrow95, ...cellStyle }}>{heads.hit}</span>
                  {hitCell}
                </span>
                <span className="flex min-w-0 flex-col" style={{ gap: 4 }}>
                  <span className="cp-eyebrow" style={{ ...eyebrow95, ...cellStyle }}>To target</span>
                  <span data-testid="desk-scan-target" className="cp-num" style={{ fontSize: 12, color: r.toTarget == null ? "var(--cp-ink-3)" : TONE_COLOR.mint }}>{targetText(r)}</span>
                </span>
                <span className="flex min-w-0 flex-col" style={{ gap: 4 }}>
                  <SparkCell s={r.s} width={84} />
                  <span data-testid="desk-scan-traded" className="cp-num" style={{ fontSize: 10, color: "var(--cp-ink-3)", ...cellStyle }}>{tradedText(r.s.avgTradedCr)}</span>
                </span>
              </span>
            </button>
          </div>
        );
      })}
    </div>
  );
}

/** Phone (design-spec §11 M2): # · Stock · Score (with P under it) · Upside · Pattern (with the status under it). */
const PHONE_COLS = "16px minmax(0,1fr) 40px 46px 92px";

function PhoneTable({ rows, selected, onOpen, head, plain }: { rows: Row[]; selected: string | null; onOpen: (sym: string) => void; head: UpHead; plain: boolean }) {
  const headStyle: CSSProperties = { fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--cp-ink-3)", ...cellStyle };
  return (
    <section data-testid="desk-scan-table" data-layout="phone" className="cp-card flex min-w-0 flex-col" role="table" aria-label="Scanner setups">
      <div role="row" className="grid" style={{ gridTemplateColumns: PHONE_COLS, gap: 6, padding: "10px 12px", borderBottom: "1px solid var(--cp-line)" }}>
        {[["rank", "#"], ["stock", "Stock"], ["score", "Score"], ["target", "Upside"], ["setup", "Pattern"]].map(([k, l]) => (
          <span key={k} role="columnheader" data-testid={`desk-scan-col-${k}`} style={headStyle}>{l}</span>
        ))}
      </div>
      {rows.map((r, i) => {
        const on = r.s.symbol === selected;
        const p = pOf(r, head);
        const soft = r.s.score != null && r.s.score >= 80 ? "var(--mint-soft)" : "var(--cp-indigo-soft)";
        return (
          <div
            key={r.s.symbol}
            role="row"
            tabIndex={0}
            data-testid={`desk-scan-row-${r.s.symbol}`}
            data-selected={on}
            aria-current={on ? "true" : undefined}
            onClick={() => onOpen(r.s.symbol)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(r.s.symbol); } }}
            className="cp-row-link grid items-center"
            style={{ gridTemplateColumns: PHONE_COLS, gap: 6, padding: "10px 12px", borderTop: i ? "1px solid var(--cp-line)" : undefined, background: on ? "var(--bg-2)" : undefined }}
          >
            <span role="cell" data-testid="desk-scan-rank" className="cp-num" style={{ fontSize: 10, color: on ? "var(--mint)" : "var(--cp-ink-3)" }}>{i + 1}</span>
            <span role="cell" style={{ minWidth: 0, fontSize: 11 }}>
              <StockCell r={r} size={20} />
              <span className="sr-only" data-testid="desk-scan-traded">{tradedText(r.s.avgTradedCr)}</span>
            </span>
            <span role="cell" className="flex flex-col items-center" style={{ gap: 2 }}>
              <span className="inline-flex items-center justify-center" style={{ width: 34, height: 24, borderRadius: 8, background: soft }}><ScoreText score={r.s.score} size={17} /></span>
              <span className="cp-num" style={{ fontSize: 8.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap" }} title={oddsLabel(head, plain)}>
                P <span data-testid="desk-scan-odds" data-head={head}>{p == null ? "—" : fmtPct(p * 100, { digits: 0 })}</span>
              </span>
            </span>
            <span role="cell" data-testid="desk-scan-target" className="cp-num" style={{ fontSize: 11, color: r.toTarget == null ? "var(--cp-ink-3)" : TONE_COLOR.mint, ...cellStyle }}>{targetText(r)}</span>
            <span role="cell" className="flex min-w-0 flex-col" style={{ gap: 2 }}>
              <span data-testid="desk-scan-setup" style={{ fontSize: 11, color: "var(--cp-ink)", ...cellStyle }}>{setupLabel(r.s, plain)}</span>
              <span data-testid="desk-scan-status" data-status={r.s.status} style={{ fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.1em", textTransform: "uppercase", color: STATUS_LABEL[r.s.status].tone === "ink" ? "var(--cp-ink-3)" : TONE_COLOR[STATUS_LABEL[r.s.status].tone] }}>
                {STATUS_LABEL[r.s.status].label}
              </span>
            </span>
          </div>
        );
      })}
    </section>
  );
}

// ── the model's state ────────────────────────────────────────────────────

const pct1 = (p: number | null | undefined) => (p == null ? "—" : fmtPct(p * 100, { digits: 1 }));

/** Header meta: the model and its out-of-sample window, or why its column is empty. */
function ModelMeta({ odds, isError, onRetry }: { odds: DeskOdds | undefined; isError: boolean; onRetry: () => void }) {
  let tone: Tone | "quiet" = "quiet";
  let body: ReactNode;
  if (isError) {
    tone = "danger";
    body = <>Move-odds didn’t load{" "}<button type="button" data-testid="desk-scan-record-retry" onClick={onRetry} style={{ padding: 0, border: 0, background: "none", font: "inherit", letterSpacing: "inherit", textTransform: "inherit", color: "var(--cp-ink)", cursor: "pointer" }}>Retry ›</button></>;
  } else if (!odds) {
    body = "Move-odds · loading";
  } else if (odds.kind === "final") {
    body = odds.data.record ? `Move-odds ${odds.data.run.model} · out-of-sample ${odds.data.record.window_label}` : `Move-odds ${odds.data.run.model} · no out-of-sample record`;
  } else if (odds.kind === "not_published") {
    tone = "amber";
    body = `Move-odds · not published for ${fmtDay(odds.expectedSession)}`;
  } else if (odds.kind === "withheld") {
    tone = "amber";
    body = "Move-odds · run withheld";
  } else {
    body = "Move-odds · not enabled for this account";
  }
  return (
    <span
      data-testid="desk-scan-record"
      data-state={isError ? "error" : odds?.kind ?? "loading"}
      className="cp-eyebrow"
      style={{ ...eyebrow95, marginLeft: "auto", color: tone === "quiet" ? "var(--cp-ink-4)" : TONE_COLOR[tone] }}
    >
      {body}
    </span>
  );
}

/** One sentence on the model: its record, or why the probability column is empty. */
function modelSentence(odds: DeskOdds | undefined, isError: boolean, head: UpHead, plain: boolean): string {
  const label = oddsLabel(head, plain);
  if (isError) return `The move-odds model didn’t load, so the ${label} column is empty.`;
  if (!odds) return "Loading the move-odds model.";
  if (odds.kind === "final") {
    const { record, run } = odds.data;
    const rec = record
      ? `Out-of-sample ${record.window_label}: top-10 hit rate ${pct1(record.top10_hit_rate)} over ${fmtNum(record.sessions)} sessions vs base rate ${pct1(record.base_rate)}.`
      : "The model has no out-of-sample record for this estimate.";
    return `${rec} Run on data of ${fmtDay(run.data_as_of)}, for the session of ${fmtDay(run.target_session)}.`;
  }
  if (odds.kind === "not_published") return `The model has not published for ${fmtDay(odds.expectedSession)} yet${odds.lastPublishedFor ? ` (last published for ${fmtDay(odds.lastPublishedFor)})` : ""}, so the ${label} column is empty.`;
  if (odds.kind === "withheld") return `The model’s run for the next session was withheld: ${odds.reason}. The ${label} column is empty.`;
  return `Move probabilities are not enabled for this account, so the ${label} column is empty.`;
}

function PartialNote({ which }: { which: "watchlist" | "picks" }) {
  return <span data-testid="desk-scan-partial" role="status" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>{PARTIAL_NOTE[which]}</span>;
}

// ── the tab ──────────────────────────────────────────────────────────────

export default function ScannerTab() {
  const { mobile } = useCopilotShell();
  const { symbol, openChart, persona } = useDesk();
  const plain = persona === "investor";
  const scan = useDeskScanner();
  const odds5Q = useDeskOdds("p_up5_1d");
  const odds10Q = useDeskOdds("p_up10_1d");
  const [rankBy, setRankBy] = useState<RankBy>("score");
  const [group, setGroup] = useState<Group>("all");
  const [liquid, setLiquid] = useState(false);
  const [listBox, setListBox] = useState<HTMLDivElement | null>(null);
  const asCards = useNarrowBox(listBox, TABLE_MIN_WIDTH, true);

  const by5 = odds5Q.data?.kind === "final" ? odds5Q.data.bySymbol : null;
  const by10 = odds10Q.data?.kind === "final" ? odds10Q.data.bySymbol : null;
  const setups = scan.data?.setups;

  const all: Row[] = useMemo(() => (setups ?? []).map((s) => {
    const key = s.symbol.toUpperCase();
    const m5 = by5?.get(key) ?? null;
    const m10 = by10?.get(key) ?? null;
    const base = s.close ?? s.entry;
    const toTarget = s.target != null && base != null && base > 0 ? ((s.target - base) / base) * 100 : null;
    return { s, p5: m5?.p ?? null, p10: m10?.p ?? null, events: m5?.events ?? m10?.events ?? null, toTarget, move: lastMove(s.spark) };
  }), [setups, by5, by10]);

  // Ranking by the model needs its figures; without them the list stays ranked by score.
  const ready: Record<UpHead, boolean> = { p_up5_1d: !!by5, p_up10_1d: !!by10 };
  const rank: RankBy = rankBy !== "score" && !ready[headOf(rankBy)] ? "score" : rankBy;
  const head = headOf(rank);
  const oddsQ = head === "p_up10_1d" ? odds10Q : odds5Q;
  const rows = useMemo(() => {
    const kept = all.filter((r) => (group === "all" || r.s.bucket === group) && (!liquid || (r.s.avgTradedCr != null && r.s.avgTradedCr >= LIQUID_MIN_CR)));
    const byScore = (a: Row, b: Row) => desc(a.s.score, b.s.score);
    return [...kept].sort((a, b) => (rank === "score" ? byScore(a, b) : desc(pOf(a, head), pOf(b, head)) || byScore(a, b)));
  }, [all, group, rank, head, liquid]);

  if (scan.isPending) return <LoadingBlock label="Loading the scanner" rows={5} />;
  if (scan.isError) {
    return (
      <div data-testid="desk-scan-error">
        <ErrorBlock title="The scanner didn’t load: neither the setup watchlist nor the scanner picks answered" error={scan.error} onRetry={() => scan.refetch()} />
      </div>
    );
  }

  const data = scan.data;
  const date = scanDateLabel(data.watchAsOf, data.signalDate);

  if (!all.length) {
    return (
      <div data-testid="desk-scan-empty" className="flex flex-col" style={{ gap: 10 }}>
        <EmptyBlock
          title={date ? `No setups on the ${date} scan` : "No setups on the latest scan"}
          body="The end-of-day scanner found no stock that met its rules for that session. The list fills again after the next close is processed."
        />
        {data.partial.map((p) => <PartialNote key={p} which={p} />)}
      </div>
    );
  }

  // Stocks in the chosen group the routes sent no traded value for: "Liquid only" cannot judge them.
  const inGroup = all.filter((r) => group === "all" || r.s.bucket === group);
  const noTraded = inGroup.filter((r) => r.s.avgTradedCr == null).length;
  const sparkEnd = all.find((r) => r.s.sparkEnd)?.s.sparkEnd ?? null;
  const shown = `${fmtNum(rows.length)} of ${fmtNum(all.length)} shown`;
  const label = oddsLabel(head, plain);

  const notes = (
    <>
      {liquid && (
        <span data-testid="desk-scan-liquid-note" role="status" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          Liquid only: average daily traded value (close × volume) over the last 20 sessions of at least ₹{LIQUID_MIN_CR} Cr.
          {noTraded > 0
            ? ` ${fmtNum(noTraded)} ${noTraded === 1 ? "stock has" : "stocks have"} no traded-value figure and ${noTraded === 1 ? "is" : "are"} not shown while this is on.`
            : " Every stock here has a traded-value figure."}
        </span>
      )}
      {data.partial.map((p) => <PartialNote key={p} which={p} />)}
    </>
  );
  const groupEmpty = (
    <div data-testid="desk-scan-group-empty" style={{ padding: "14px 18px", fontSize: 13, color: "var(--cp-ink-3)", borderTop: "1px solid var(--cp-line)" }}>
      {liquid ? `No setup in this group trades ₹${LIQUID_MIN_CR} Cr or more a day on average.` : "No setup in this group on this scan."}
    </div>
  );
  const footnote = (
    <>
      {plain ? (
        <>
          <span>Score is a rules-based rank from the end-of-day scan, 0–100; it is not a chance of anything. {label}: a model’s estimate that the next trading day’s high gets {head === "p_up10_1d" ? "10" : "5"}% above the last close — one day only.</span>
          <span data-testid="desk-scan-model-note">{modelSentence(oddsQ.data, oddsQ.isError, head, plain)}</span>
          <span>Past record: no track record per idea is published yet, so it shows —. 24 sessions: each stock’s last daily closes{sparkEnd ? ` to ${fmtDay(sparkEnd)}` : ""}, end of day. Liquid only: stocks trading at least ₹{LIQUID_MIN_CR} Cr a day on average over 20 days.</span>
        </>
      ) : (
        <>
          <span>Score: the end-of-day scanner’s rules-based score, 0–100, from its trend, breakout, volume and accumulation checks. It ranks setups; it is not a probability. {label}: the move-odds model’s estimate that the next session’s high reaches the previous close plus {head === "p_up10_1d" ? "10" : "5"}%, one session only.</span>
          <span data-testid="desk-scan-model-note">{modelSentence(oddsQ.data, oddsQ.isError, head, plain)}</span>
          <span>Hit rate · n: no per-setup back-tested record is published, so it shows —. 24 sessions: each stock’s last daily closes{sparkEnd ? ` to ${fmtDay(sparkEnd)}` : ""}, end of day. Liquid only: 20-session average traded value (close × volume) of at least ₹{LIQUID_MIN_CR} Cr a day.</span>
        </>
      )}
      <span>Sources: NSE end-of-day scanner (GET /api/positional/watchlist, /picks) · move-odds model (GET /api/move-odds/latest). Open a row for its chart.</span>
    </>
  );

  // ── phone (design-spec §11 M2) ──
  if (mobile) {
    const confirmed = all.filter((r) => r.s.status === "confirmed").length;
    const awaiting = all.filter((r) => r.s.status === "awaiting").length;
    const best = [...all].filter((r) => r.p5 != null).sort((a, b) => desc(a.p5, b.p5))[0] ?? null;
    const liquidCount = all.filter((r) => r.s.avgTradedCr != null && r.s.avgTradedCr >= LIQUID_MIN_CR).length;
    return (
      <div data-testid="desk-scanner" data-layout="phone" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
        <div role="group" aria-label="Setup group" className="cp-scroll flex overflow-x-auto" style={{ gap: 6, paddingBottom: 2 }}>
          {GROUPS.map((g) => (
            <Chip key={g.key} on={g.key === group} onClick={() => setGroup(g.key)} testId={`desk-scan-group-${g.key}`}>{g.label}</Chip>
          ))}
          <Chip on={liquid} onClick={() => setLiquid(!liquid)} testId="desk-scan-liquid" title={LIQUID_TITLE}>Liquid only</Chip>
        </div>
        <RankBySwitch value={rank} onChange={setRankBy} ready={ready} plain={plain} small />
        {notes}
        <span data-testid="desk-scan-eyebrow" className="cp-eyebrow" style={{ fontSize: 9, color: "var(--cp-ink-4)" }}>
          NSE · end of day{date ? ` ${date}` : ""} · {shown}
        </span>
        {rows.length === 0 ? <div className="cp-card">{groupEmpty}</div> : <PhoneTable rows={rows} selected={symbol} onOpen={openChart} head={head} plain={plain} />}
        <section data-testid="desk-scan-insights" className="cp-card flex flex-col" style={{ gap: 8, padding: 14 }}>
          <span className="cp-eyebrow">Scanner insights</span>
          <p className="m-0" style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
            {plain
              ? <>{fmtNum(all.length)} ideas on the {date ?? "latest"} scan; {fmtNum(confirmed)} {confirmed === 1 ? "has" : "have"} already broken out and {fmtNum(awaiting)} {awaiting === 1 ? "is" : "are"} close.</>
              : <>{fmtNum(all.length)} setups on the {date ?? "latest"} scan: {fmtNum(confirmed)} confirmed, {fmtNum(awaiting)} awaiting a trigger, {fmtNum(all.length - confirmed - awaiting)} forming.</>}
            {" "}{best && best.p5 != null ? <>Highest {oddsLabel("p_up5_1d", plain)}: {best.s.symbol} at {pct1(best.p5)}.</> : null}
            {" "}{fmtNum(liquidCount)} of {fmtNum(all.length)} trade ₹{LIQUID_MIN_CR} Cr or more a day.
          </p>
          <details style={{ fontSize: 11, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            <summary data-testid="desk-scan-footnote-toggle" style={{ cursor: "pointer", color: "var(--cp-ink-2)" }}>How these figures are worked out</summary>
            <span data-testid="desk-scan-footnote" className="flex flex-col" style={{ gap: 4, paddingTop: 6 }}>{footnote}</span>
          </details>
        </section>
      </div>
    );
  }

  // ── desk (design-spec §4) ──
  return (
    <section data-testid="desk-scanner" data-layout="desk" className="cp-card flex min-w-0 flex-col">
      <header className="flex flex-wrap items-center" style={{ gap: "6px 14px", padding: "13px 18px", borderBottom: "1px solid var(--cp-line)", background: "var(--bg-0)", borderRadius: "14px 14px 0 0" }}>
        <span data-testid="desk-scan-title" className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}><span style={{ color: "var(--mint)" }}>02</span> · AI Opportunity scanner</span>
        <span data-testid="desk-scan-eyebrow" className="cp-eyebrow" style={{ ...eyebrow95, color: "var(--cp-ink-4)" }}>
          NSE · end of day{date ? ` ${date}` : ""} · next-session odds · {shown}
        </span>
        <ModelMeta odds={oddsQ.data} isError={oddsQ.isError} onRetry={() => oddsQ.refetch()} />
      </header>

      <div data-testid="desk-scan-controls" className="flex flex-wrap items-center" style={{ gap: 12, padding: "12px 18px", borderBottom: "1px solid var(--cp-line)" }}>
        <RankBySwitch value={rank} onChange={setRankBy} ready={ready} plain={plain} />
        <span aria-hidden style={{ width: 1, height: 20, background: "var(--line-2)" }} />
        <GroupChips value={group} onChange={setGroup} />
        <span style={{ marginLeft: "auto" }}><LiquidSwitch on={liquid} onChange={setLiquid} /></span>
        {(liquid || data.partial.length > 0) && <div className="flex flex-col" style={{ gap: 4, flexBasis: "100%" }}>{notes}</div>}
      </div>

      <div ref={setListBox}>
        {rows.length === 0 ? groupEmpty : asCards
          ? <ScanCards rows={rows} selected={symbol} onOpen={openChart} head={head} plain={plain} />
          : <ScanTable rows={rows} selected={symbol} onOpen={openChart} head={head} plain={plain} />}
      </div>

      <div data-testid="desk-scan-footnote" className="flex flex-col" style={{ gap: 4, padding: "12px 18px", borderTop: "1px solid var(--cp-line)", fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
        {footnote}
      </div>
    </section>
  );
}
