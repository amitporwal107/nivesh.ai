/**
 * Top Movers v4 — page shell: top bar, left rail, hero, and the (non-design) window controls strip.
 *
 * Props (all explicit, wiring is mechanical):
 *
 *   MoversTopBar   { asOf: string | null; modelVersion: string | null }
 *       asOf = latest session date we have (ISO). modelVersion = from the API, null renders the chip without a version.
 *
 *   MoversRail     { mode: "MOVERS" | "FLAGGED"; onMode(m)
 *                    rows: RailRow[]            // list.movers, or flagged.rows (they carry exec / model_p)
 *                    moversCount: number | null; flaggedCount: number | null   // numbers on the two mode buttons
 *                    from: string; to: string  // ISO window, for the eyebrow
 *                    flagged: FlaggedSummary | null   // outcomes / total / horizon / cutoff, for the flagged headline
 *                    selected: {symbol, session} | null; onSelect(row)
 *                    filter: string; onFilter(f)       // MOVERS: ALL|UP|DOWN|MISSED; FLAGGED: ALL|NONE|PENDING
 *                    loading?: boolean; error?: string | null; onRetry?(); emptyText?: string | null
 *                    names?: Record<string, string> }  // symbol -> company name (the API has none; falls back to turnover)
 *
 *   MoversHero     { row: RailRow | null; detail: MoverDetail | null; mode; name?: string | null }
 *
 *   MoversControls { from; to; minAbsPct; direction: "both"|"up"|"down"; includeCa: boolean; withheld: number | null;
 *                    onFrom(v); onTo(v); onMinAbsPct(n); onDirection(d); onToggleCa() }
 */
import "./moversV4Shell.css";
import type { CSSProperties } from "react";
import type { MoverCandidateRow, MoverDetail, MoverFlaggedRow, MoverRow } from "@/services/adapters/movers.adapter";

export type RailRow = MoverRow & Partial<Pick<MoverFlaggedRow, "exec" | "model_p" | "model_head">>;
export type MoversMode = "MOVERS" | "FLAGGED" | "CANDIDATES";
export type MoversDirection = "both" | "up" | "down";
export type FlaggedSummary = {
  total: number; cutoff: number | null; horizon: number; available: boolean;
  outcomes: { UP: number; DOWN: number; BOTH: number; NONE: number; PENDING: number };
};

// ── formatting (fixed formats, not toLocale*) ───────────────────────────────────────────────────────────────────────
const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
function parts(iso: string | null | undefined): [string, string, string] | null {
  if (!iso) return null;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return null;
  return [String(d).padStart(2, "0"), MON[m - 1], String(y)];
}
const fd = (iso: string | null | undefined) => { const p = parts(iso); return p ? `${p[0]} ${p[1]}` : "—"; };
const fdy = (iso: string | null | undefined) => { const p = parts(iso); return p ? `${p[0]} ${p[1]} '${p[2].slice(2)}` : "—"; };
const fdyy = (iso: string | null | undefined) => { const p = parts(iso); return p ? `${p[0]} ${p[1]} ${p[2]}` : "—"; };
/** `pct` fields from the API are already in percent. */
function sp(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  const a = Math.abs(v) < 0.05 ? 0 : v;
  return `${a > 0 ? "+" : a < 0 ? "-" : ""}${Math.abs(a).toFixed(1)}%`;
}
const sentDate = (iso: string) => { const p = parts(iso); return p ? `${p[0]} ${p[1][0]}${p[1].slice(1).toLowerCase()} ${p[2]}` : "—"; };
const p0 = (v: number | null | undefined) => (v == null || !isFinite(v) ? "—" : `${(v * 100).toFixed(0)}%`);
const p2 = (v: number | null | undefined) => (v == null || !isFinite(v) ? "—" : v.toFixed(2));
function cr(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  return v >= 1e7 ? `₹${(v / 1e7).toFixed(1)} Cr` : `₹${(v / 1e5).toFixed(1)} L`;
}

type Tone = "mint" | "amber" | "danger" | "indigo" | "none";
const toneStyle = (t: Tone) =>
  t === "none"
    ? { color: "var(--ink-3)", bg: "transparent", line: "var(--line-2)" }
    : { color: `var(--${t})`, bg: `var(--${t}-soft)`, line: `var(--${t}-line)` };

/** CAUGHT / MISSED (scored, below the cut-off) / not covered (no run, or outside the scored universe). */
type Cover = "CAUGHT" | "MISSED" | "NO MODEL RUN" | "NOT SCORED";
function coverOf(r: RailRow): Cover {
  const o = r.odds;
  if (o.state === "CAUGHT") return "CAUGHT";
  if (o.state === "NO_MODEL_RUN") return "NO MODEL RUN";
  return o.reason === "NOT_IN_SCORED_UNIVERSE" ? "NOT SCORED" : "MISSED";
}
const covered = (c: Cover) => c === "CAUGHT" || c === "MISSED";

function badgeOf(r: RailRow, mode: MoversMode, H: number): { state: string; extra: string; tone: Tone; note: string } {
  if (mode === "FLAGGED") {
    const out = r.exec?.out ?? null;
    const state = out == null ? "FLAGGED" : out === "PENDING" ? `PEND ${r.exec?.el ?? 0}/${r.exec?.H ?? H}` : out;
    return { state, extra: `P ${p2(r.model_p ?? r.odds.score)} · `, tone: "amber",
      note: "Flagged by the model; the outcome is the ±5% race from the next open." };
  }
  const c = coverOf(r);
  const score = r.odds.score;
  if (c === "CAUGHT") return { state: c, extra: score != null ? ` · ${p0(score)}` : "", tone: "mint", note: r.odds.note ?? "Flagged before the move." };
  if (c === "MISSED") return { state: c, extra: "", tone: "danger", note: r.odds.note ?? "Scored below the cut-off." };
  return { state: c, extra: "", tone: "none", note: r.odds.note ?? "No estimate exists for this move; this is a coverage gap, not a miss." };
}

const MONO = "var(--mono)";

// ═══ top bar ════════════════════════════════════════════════════════════════════════════════════════════════════════
export function MoversTopBar({ asOf, modelVersion }: { asOf: string | null; modelVersion: string | null }) {
  return (
    <header data-testid="mv-topbar" style={{ display: "flex", alignItems: "center", gap: 16, padding: "14px 24px", borderBottom: "1px solid var(--line)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span aria-hidden="true" style={{ fontFamily: "var(--display)", fontSize: 28, lineHeight: 1, background: "linear-gradient(135deg,var(--mint),var(--indigo))", WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>न</span>
        <span style={{ fontFamily: "var(--display)", fontSize: 22 }}>Nivesh</span>
        <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: ".14em", color: "var(--ink-3)", textTransform: "uppercase" }}>Movers Lab · v4</span>
      </div>
      <div style={{ flex: 1 }} />
      <span data-testid="mv-asof" style={{ fontFamily: MONO, fontSize: 11, letterSpacing: ".12em", color: "var(--ink-3)" }}>
        {asOf ? `EOD · ${fdyy(asOf)} · NSE` : "EOD · NSE"}
      </span>
      <span data-testid="mv-model-chip" style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 999, border: "1px solid var(--mint-line)", background: "var(--mint-soft)", color: "var(--mint)", fontFamily: MONO, fontSize: 11, letterSpacing: ".12em" }}>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--mint)" }} />
        {modelVersion ? `ODDS MODEL ${modelVersion}` : "ODDS MODEL"}
      </span>
    </header>
  );
}

// ═══ left rail ══════════════════════════════════════════════════════════════════════════════════════════════════════
type RailProps = {
  mode: MoversMode; onMode: (m: MoversMode) => void;
  rows: RailRow[]; moversCount: number | null; flaggedCount: number | null;
  candidateRows: MoverCandidateRow[]; candidatesCount: number | null; candSession: string | null;
  from: string; to: string; flagged: FlaggedSummary | null;
  selected: { symbol: string; session: string } | null;
  onSelect: (r: { symbol: string; session: string }) => void;
  filter: string; onFilter: (f: string) => void;
  loading?: boolean; error?: string | null; onRetry?: () => void; emptyText?: string | null;
  names?: Record<string, string>;
};

const eyebrow: CSSProperties = { fontFamily: MONO, fontSize: 11, letterSpacing: ".14em", color: "var(--ink-3)" };
const segWrap: CSSProperties = { display: "flex", gap: 4, padding: 3, border: "1px solid var(--line-2)", background: "var(--bg-1)" };

export function MoversRail(p: RailProps) {
  const isMir = p.mode === "FLAGGED";
  const isCand = p.mode === "CANDIDATES";
  const H = p.flagged?.horizon ?? 3;
  const filters = isCand ? ["ALL", "FILING", "DEAL"] : isMir ? ["ALL", "NONE", "PENDING"] : ["ALL", "UP", "DOWN", "MISSED"];
  const ft = filters.includes(p.filter) ? p.filter : "ALL";
  const shown = p.rows.filter((r) => {
    if (ft === "ALL") return true;
    if (isMir) return (r.exec?.out ?? "") === ft;
    if (ft === "UP") return (r.pct ?? 0) > 0;
    if (ft === "DOWN") return (r.pct ?? 0) < 0;
    return coverOf(r) === "MISSED";
  });
  const shownCandidates = p.candidateRows.filter((c) => {
    if (ft === "ALL") return true;
    const hasFiling = c.signals.some((s) => s.type === "fil");
    const hasDeal = c.signals.some((s) => s.type !== "fil");
    return ft === "FILING" ? hasFiling : ft === "DEAL" ? hasDeal : true;
  });

  // headline, computed from the rows (design wording; honest about coverage)
  const nCaught = p.rows.filter((r) => coverOf(r) === "CAUGHT").length;
  const nCovered = p.rows.filter((r) => covered(coverOf(r))).length;
  const nUncovered = p.rows.length - nCovered;
  let headA = "", headB = "", headC = "", color = "var(--mint)", note = "";
  if (isCand) {
    color = "var(--indigo)";
    if (p.candidateRows.length > 0) {
      headA = "Candidates for the next session"; headB = ""; headC = "";
      note = `${p.candidateRows.length} NAMES · MATERIAL FILINGS & BULK/BLOCK DEALS${p.candSession ? ` · ${fdyy(p.candSession)}` : ""} · NOT A PREDICTION`;
    } else {
      headA = "No candidates"; headC = " for the last session"; color = "var(--ink-3)";
      note = "NO MATERIAL FILING OR BULK/BLOCK DEAL ON RECORD";
    }
  } else if (isMir) {
    const f = p.flagged;
    color = "var(--amber)";
    if (f && f.total > 0) {
      headB = `${f.outcomes.NONE} of ${f.total}`;
      headC = ` flagged names resolved NONE, ${f.outcomes.PENDING} still pending`;
      note = `OF ${f.total} FLAGGED AT OR ABOVE ${p0(f.cutoff)} · UP ${f.outcomes.UP} · DOWN ${f.outcomes.DOWN} · BOTH ${f.outcomes.BOTH} · NONE ${f.outcomes.NONE} · PENDING ${f.outcomes.PENDING} · ±5% / ${H}S`;
    } else {
      headA = "No name was flagged"; headC = " in this window";
      note = f ? `NO NAME REACHED THE ${p0(f.cutoff)} CUT-OFF · ±5% / ${H}S` : "LOADING";
    }
  } else if (nCovered > 0) {
    headA = "Model caught "; headB = `${nCaught} of ${nCovered}`; headC = " before the move";
    note = `${p.rows.length} MOVERS SHOWN · ${nUncovered > 0 ? `${nUncovered} NOT COVERED (NO MODEL RUN) · ` : ""}RECALL ONLY`;
  } else if (p.rows.length > 0) {
    headA = "No model run covered"; headB = ` these ${p.rows.length}`; headC = " moves"; color = "var(--ink-3)";
    note = `${p.rows.length} MOVERS SHOWN · A COVERAGE GAP, NOT A MISS`;
  } else {
    headA = "No movers"; headC = " in this window"; color = "var(--ink-3)"; note = "0 MOVERS SHOWN";
  }
  const foot = isCand
    ? "Material filings (impact = high) and bulk/block deals from the last session, nothing more. Not a prediction: whether a name reacts next session is for the chart and event log to show, not this list."
    : isMir
    ? `Membership is re-derived at the selected horizon: a name that reaches ±5% leaves the list, and one still inside its window shows PENDING.`
    : "Ranked by absolute return in the window. Every row already moved, so this view measures recall. Switch to Flagged · no move for the other side.";
  const modes: [MoversMode, string][] = [
    ["MOVERS", `MOVERS · RECALL${p.moversCount != null ? ` · ${p.moversCount}` : ""}`],
    ["FLAGGED", `FLAGGED · NONE / PENDING${p.flaggedCount != null ? ` · ${p.flaggedCount}` : ""}`],
    ["CANDIDATES", `CANDIDATES${p.candidatesCount != null ? ` · ${p.candidatesCount}` : ""}`],
  ];
  const emptyBox = isCand
    ? !p.loading && !p.error && p.candidateRows.length === 0
    : !p.loading && !p.error && p.rows.length === 0;
  // one line in the 267px rail like the design's "SEPT 2026": the year is shown only when the window crosses a year boundary
  const win = p.from.slice(0, 4) === p.to.slice(0, 4) ? `${fd(p.from)} – ${fd(p.to)}` : `${fdy(p.from)} – ${fdy(p.to)}`;
  const candTone = toneStyle("indigo");

  return (
    <aside data-testid="mv-rail" aria-label="Movers list" style={{ borderRight: "1px solid var(--line)", padding: "20px 16px", display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
      <div role="group" aria-label="Which side of the model" style={{ ...segWrap, flexDirection: "column", borderRadius: 12 }}>
        {modes.map(([k, l]) => {
          const on = p.mode === k;
          return (
            <button key={k} type="button" className="mv4-seg" aria-pressed={on} data-testid={`mv-mode-${k.toLowerCase()}`}
              onClick={() => p.onMode(k)}
              style={{ border: 0, cursor: "pointer", padding: "8px 10px", borderRadius: 9, textAlign: "left", fontFamily: MONO, fontSize: 11, letterSpacing: ".1em", background: on ? "var(--bg-3)" : "transparent", color: on ? "var(--ink)" : "var(--ink-3)", transition: "all .15s ease" }}>{l}</button>
          );
        })}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={eyebrow}>{isCand ? `CANDIDATES · NOT A PREDICTION` : isMir ? `FLAGGED, DIDN'T MOVE · ${win}` : `TOP MOVERS · ${win}`}</span>
        <span data-testid="mv-rail-headline" style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.2 }}>
          {headA}<span style={{ color }}>{headB}</span>{headC}
        </span>
        <span data-testid={isCand ? "mv-cand-meta" : isMir ? "mv-flagged-shares" : "mv-rail-meta"} style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".08em", color: "var(--ink-3)", lineHeight: 1.5 }}>
          {p.loading ? "LOADING…" : note}
        </span>
      </div>
      <div role="group" aria-label="Filter" style={{ ...segWrap, borderRadius: 999 }}>
        {filters.map((k) => {
          const on = ft === k;
          return (
            <button key={k} type="button" className="mv4-seg" aria-pressed={on} data-testid={`mv-filter-${k.toLowerCase()}`} onClick={() => p.onFilter(k)}
              style={{ flex: 1, border: 0, cursor: "pointer", padding: "6px 0", borderRadius: 999, fontFamily: MONO, fontSize: 10.5, letterSpacing: ".1em", background: on ? "var(--bg-3)" : "transparent", color: on ? "var(--ink)" : "var(--ink-3)", transition: "all .15s ease" }}>{k}</button>
          );
        })}
      </div>
      {p.error && (
        <div role="alert" data-testid="mv-rail-error" style={{ padding: 12, borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 12.5, lineHeight: 1.5, color: "var(--ink-2)", display: "flex", flexDirection: "column", gap: 8 }}>
          <span>The {isCand ? "candidates" : "movers"} list could not be loaded ({p.error}).</span>
          {p.onRetry && <button type="button" className="mv4-link" onClick={p.onRetry} style={{ alignSelf: "flex-start" }}>Try again</button>}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {isCand ? shownCandidates.map((c, i) => {
          const on = !!p.selected && p.selected.symbol === c.symbol && p.selected.session === c.session;
          const hasFiling = c.signals.some((s) => s.type === "fil");
          const hasDeal = c.signals.some((s) => s.type !== "fil");
          const badgeText = hasFiling && hasDeal ? "FILING + DEAL"
            : hasFiling ? `FILING${c.signals.length > 1 ? ` ×${c.signals.length}` : ""}`
            : `DEAL${c.signals.length > 1 ? ` ×${c.signals.length}` : ""}`;
          const pctColor = c.pct == null ? "var(--ink-4)" : c.pct >= 0 ? "var(--mint)" : "var(--danger)";
          return (
            <button key={`${c.symbol}:${c.session}`} type="button" className="mv4-row" aria-current={on ? "true" : undefined}
              data-testid={`mv-rail-row-${c.symbol}`} onClick={() => p.onSelect(c)}
              style={{ textAlign: "left", cursor: "pointer", display: "grid", gridTemplateColumns: "22px minmax(0,1fr) auto", gap: "4px 10px", alignItems: "center", padding: "10px 12px", borderRadius: 12, color: "var(--ink)", fontFamily: "var(--sans)", transition: "all .15s ease" }}>
              <span style={{ fontFamily: MONO, fontSize: 11, color: "var(--ink-4)" }}>{String(i + 1).padStart(2, "0")}</span>
              <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                <span style={{ fontFamily: MONO, fontSize: 13, fontWeight: 500 }}>{c.symbol}</span>
                <span style={{ fontSize: 12, color: "var(--ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.name ?? c.signals[0]?.title ?? ""}</span>
              </span>
              <span style={{ fontFamily: MONO, fontSize: 14, fontWeight: 500, color: pctColor, textAlign: "right" }}>{sp(c.pct)}</span>
              <span />
              <span style={{ fontFamily: MONO, fontSize: 10.5, color: "var(--ink-4)", letterSpacing: ".06em" }}>{fd(c.session)}</span>
              <span data-testid="mv-badge" title={c.signals.map((s) => s.title).join(" · ")}
                style={{ justifySelf: "end", padding: "2px 7px", borderRadius: 999, border: `1px solid ${candTone.line}`, background: candTone.bg, color: candTone.color, fontFamily: MONO, fontSize: 10, letterSpacing: ".08em", whiteSpace: "nowrap" }}>
                <b data-testid="mv-badge-state" style={{ fontWeight: "inherit" }}>{badgeText}</b>
              </span>
            </button>
          );
        }) : shown.map((m, i) => {
          const on = !!p.selected && p.selected.symbol === m.symbol && p.selected.session === m.session;
          const b = badgeOf(m, p.mode, H);
          const ts = toneStyle(b.tone);
          const rank = String(p.rows.indexOf(m) + 1).padStart(2, "0");
          const nm = p.names?.[m.symbol];
          const pctColor = isMir ? "var(--ink-2)" : (m.pct ?? 0) >= 0 ? "var(--mint)" : "var(--danger)";
          return (
            <button key={`${m.symbol}:${m.session}:${i}`} type="button" className="mv4-row" aria-current={on ? "true" : undefined}
              data-testid={`mv-rail-row-${m.symbol}`} onClick={() => p.onSelect(m)}
              style={{ textAlign: "left", cursor: "pointer", display: "grid", gridTemplateColumns: "22px minmax(0,1fr) auto", gap: "4px 10px", alignItems: "center", padding: "10px 12px", borderRadius: 12, color: "var(--ink)", fontFamily: "var(--sans)", transition: "all .15s ease" }}>
              <span style={{ fontFamily: MONO, fontSize: 11, color: "var(--ink-4)" }}>{rank}</span>
              <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                <span style={{ fontFamily: MONO, fontSize: 13, fontWeight: 500 }}>{m.symbol}</span>
                <span style={{ fontSize: 12, color: "var(--ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{nm ?? cr(m.turnover)}</span>
              </span>
              <span style={{ fontFamily: MONO, fontSize: 14, fontWeight: 500, color: pctColor, textAlign: "right" }}>{sp(m.pct)}</span>
              <span />
              <span style={{ fontFamily: MONO, fontSize: 10.5, color: "var(--ink-4)", letterSpacing: ".06em" }}>
                T · {isMir ? "TARGET " : ""}{fd(m.session)}{m.ca_suspect ? " · SPLIT?" : ""}
              </span>
              <span data-testid="mv-badge" title={b.note}
                style={{ justifySelf: "end", padding: "2px 7px", borderRadius: 999, border: `1px solid ${ts.line}`, background: ts.bg, color: ts.color, fontFamily: MONO, fontSize: 10, letterSpacing: ".08em", whiteSpace: "nowrap" }}>
                {b.extra && isMir ? b.extra : ""}<b data-testid="mv-badge-state" style={{ fontWeight: "inherit" }}>{b.state}</b>{!isMir ? b.extra : ""}
              </span>
            </button>
          );
        })}
      </div>
      {emptyBox && (
        <div data-testid={isCand ? "mv-cand-empty" : isMir ? "mv-flagged-unavailable" : "mv-rail-empty"} style={{ padding: 12, borderRadius: 12, border: "1px dashed var(--line-3)", fontSize: 12.5, lineHeight: 1.5, color: "var(--ink-2)" }}>
          {p.emptyText ?? (isCand ? "No material filing or bulk/block deal on record for the last session." : isMir ? "No flagged name is still showing no move in this window." : "No stock moved this much in this window on the liquidity floor this view uses.")}
        </div>
      )}
      {!emptyBox && !p.loading && !p.error && (isCand ? shownCandidates.length === 0 : shown.length === 0) && (
        <div data-testid="mv-rail-filter-empty" style={{ padding: 12, borderRadius: 12, border: "1px dashed var(--line-3)", fontSize: 12.5, lineHeight: 1.5, color: "var(--ink-2)" }}>
          No row matches the {ft} filter.
        </div>
      )}
      <div style={{ fontSize: 11.5, color: "var(--ink-4)", lineHeight: 1.5 }}>{foot}</div>
    </aside>
  );
}

// ═══ hero ═══════════════════════════════════════════════════════════════════════════════════════════════════════════
function heroStats(row: RailRow, detail: MoverDetail | null) {
  // move-day volume vs the average of the sessions before it that the chart holds
  let volX = "—", volNote = "Volume history for this move is not loaded.";
  if (detail && detail.bars.length) {
    let i = detail.bars.findIndex((b) => b.t.slice(0, 10) === row.session.slice(0, 10));
    if (i < 0) i = detail.bar_index_of_session;
    const prior = detail.bars.slice(Math.max(0, i - 20), i).map((b) => b.v).filter((v) => v > 0);
    const v = detail.bars[i]?.v;
    if (prior.length >= 5 && v != null) {
      volX = `${(v / (prior.reduce((a, b) => a + b, 0) / prior.length)).toFixed(1)}×`;
      volNote = `Move-day volume against the average of the ${prior.length} sessions before it${prior.length < 20 ? " in view (fewer than 20 available)" : ""}.`;
    } else volNote = "Fewer than 5 earlier sessions are loaded, so no volume multiple is shown.";
  }
  // events within ±7 calendar days of the move day
  let ev = "—", evNote = "Events are not loaded.";
  if (detail) {
    const T = Date.parse(`${row.session.slice(0, 10)}T00:00:00Z`);
    const n = detail.events.filter((e) => Math.abs(Date.parse(`${e.date.slice(0, 10)}T00:00:00Z`) - T) <= 7 * 864e5).length;
    ev = String(n); evNote = "Corporate events and deals dated within 7 days of the move day.";
  }
  return { volX, volNote, ev, evNote };
}

function heroModel(row: RailRow, mode: MoversMode, H: number): { short: string; tone: Tone } {
  if (mode === "FLAGGED") {
    const o = row.exec?.out;
    return { short: o == null ? "Flagged" : o === "NONE" ? "FP · NONE" : o === "PENDING" ? `PENDING ${row.exec?.el ?? 0}/${row.exec?.H ?? H}` : "Moved", tone: "amber" };
  }
  const c = coverOf(row);
  if (c === "CAUGHT") return { short: row.odds.score != null ? `Caught · ${p0(row.odds.score)}` : "Caught", tone: "mint" };
  if (c === "MISSED") return { short: "Missed", tone: "danger" };
  return { short: c === "NOT SCORED" ? "Not scored" : "No run", tone: "none" };
}

function synthesis(row: RailRow, mode: MoversMode, evCount: string): string {
  const mv = `Moved ${sp(row.pct)} on ${sentDate(row.session)}.`;
  const tail = evCount !== "—" ? ` ${evCount} event${evCount === "1" ? "" : "s"} and deals landed inside T±7.` : "";
  const o = row.odds;
  if (mode === "FLAGGED") {
    const out = row.exec?.out;
    return `Flagged by the odds model at P ${p2(row.model_p ?? o.score)} for ${fdy(row.session)}; ${out === "NONE" ? "it resolved NONE: it reached neither +5% nor -5% in the window" : out === "PENDING" ? "the window has not finished, so the outcome is still pending" : `it went on to reach ${out === "BOTH" ? "both +5% and -5%" : out === "UP" ? "+5%" : "-5%"}`}.${tail}`;
  }
  const c = coverOf(row);
  if (c === "CAUGHT") return `${mv} The odds model flagged it ahead of the move: its estimate was ${p0(o.score)} on ${o.run_session ? sentDate(o.run_session) : "—"}${o.cutoff != null ? `, at or above the ${p0(o.cutoff)} cut-off` : ""}.${tail}`;
  if (c === "MISSED") return `${mv} The odds model did not flag it: ${o.score != null ? `its estimate of ${p0(o.score)} stayed below` : "its estimate stayed below"} the ${p0(o.cutoff)} cut-off${tail ? `, although${tail.replace(/^ (\d+)/, " $1")}` : "."}`;
  if (c === "NOT SCORED") return `${mv} The odds model ran in this window but did not score this stock, so there is no estimate to compare. That is a coverage gap, not a miss.${tail}`;
  return `${mv} No odds-model run covered this window, so it can be neither called caught nor missed. That is a coverage gap, not a miss.${tail}`;
}

const tile: CSSProperties = { display: "flex", flexDirection: "column", gap: 4, padding: "10px 14px", borderRadius: 14 };

export function MoversHero({ row, detail, mode, name, candidateRow }: {
  row: RailRow | null; detail: MoverDetail | null; mode: MoversMode; name?: string | null;
  /** only read when mode === "CANDIDATES"; `row` stays null for that mode */
  candidateRow?: MoverCandidateRow | null;
}) {
  if (mode === "CANDIDATES") {
    if (!candidateRow) {
      return (
        <section data-testid="mv-hero" style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: "16px 32px" }}>
          <span style={{ fontSize: 15, color: "var(--ink-2)" }}>Pick a name on the left to see its chart and what was filed or traded around it.</span>
        </section>
      );
    }
    const c = candidateRow;
    const moveColor = c.pct == null ? "var(--ink-3)" : c.pct >= 0 ? "var(--mint)" : "var(--danger)";
    const sector = detail?.sector?.name ? ` · ${detail.sector.name.toUpperCase()}` : "";
    const titles = c.signals.map((s) => s.title);
    const synthesisText = titles.length <= 1
      ? (titles[0] ?? "No disclosure detail available.")
      : `${titles.length} disclosures on ${sentDate(c.session)}: ${titles.slice(0, 2).join("; ")}${titles.length > 2 ? "…" : ""}`;
    return (
      <section data-testid="mv-hero" style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: "16px 32px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1, minWidth: 320 }}>
          <span style={eyebrow}>{c.symbol} · NSE{sector} · {fdy(c.session)}</span>
          <div style={{ display: "flex", alignItems: "baseline", gap: 16, flexWrap: "wrap" }}>
            <span data-testid="mv-hero-name" style={{ fontFamily: "var(--display)", fontSize: 40, lineHeight: 1 }}>{name || c.name || c.symbol}</span>
            <span data-testid="mv-hero-move" style={{ fontFamily: "var(--display)", fontSize: 40, lineHeight: 1, color: moveColor }}>{sp(c.pct)}</span>
          </div>
          <span data-testid="mv-hero-synthesis" style={{ fontSize: 15, color: "var(--ink-2)", textWrap: "pretty", maxWidth: 760 } as CSSProperties}>{synthesisText}</span>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <div style={{ ...tile, background: "var(--bg-1)", border: "1px solid var(--line)", boxShadow: "var(--shadow-card)" }}>
            <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".12em", color: "var(--ink-3)" }}>SIGNALS</span>
            <span data-testid="mv-hero-signals" style={{ fontFamily: "var(--display)", fontSize: 24 }}>{c.signals.length}</span>
          </div>
        </div>
      </section>
    );
  }
  if (!row) {
    return (
      <section data-testid="mv-hero" style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: "16px 32px" }}>
        <span style={{ fontSize: 15, color: "var(--ink-2)" }}>Pick a stock on the left to see its chart and what was on the tape around the move.</span>
      </section>
    );
  }
  const isMir = mode === "FLAGGED";
  const st = heroStats(row, detail);
  const mdl = heroModel(row, mode, row.exec?.H ?? 3);
  const ts = toneStyle(mdl.tone);
  const sector = detail?.sector?.name ? ` · ${detail.sector.name.toUpperCase()}` : "";
  const moveColor = isMir ? "var(--ink-2)" : (row.pct ?? 0) >= 0 ? "var(--mint)" : "var(--danger)";
  return (
    <section data-testid="mv-hero" style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: "16px 32px" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1, minWidth: 320 }}>
        <span style={eyebrow}>{row.symbol} · NSE{sector} · {isMir ? "TARGET DAY" : "MOVE DAY"} {fdy(row.session)}</span>
        <div style={{ display: "flex", alignItems: "baseline", gap: 16, flexWrap: "wrap" }}>
          <span data-testid="mv-hero-name" style={{ fontFamily: "var(--display)", fontSize: 40, lineHeight: 1 }}>{name || row.symbol}</span>
          <span data-testid="mv-hero-move" style={{ fontFamily: "var(--display)", fontSize: 40, lineHeight: 1, color: moveColor }}>{sp(row.pct)}</span>
        </div>
        <span data-testid="mv-hero-synthesis" style={{ fontSize: 15, color: "var(--ink-2)", textWrap: "pretty", maxWidth: 760 } as CSSProperties}>{synthesis(row, mode, st.ev)}</span>
      </div>
      <div style={{ display: "flex", gap: 10 }}>
        <div title={st.volNote} style={{ ...tile, background: "var(--bg-1)", border: "1px solid var(--line)", boxShadow: "var(--shadow-card)" }}>
          <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".12em", color: "var(--ink-3)" }}>MOVE-DAY VOL</span>
          <span data-testid="mv-hero-vol" style={{ fontFamily: "var(--display)", fontSize: 24 }}>{st.volX}</span>
        </div>
        <div title={st.evNote} style={{ ...tile, background: "var(--bg-1)", border: "1px solid var(--line)", boxShadow: "var(--shadow-card)" }}>
          <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".12em", color: "var(--ink-3)" }}>EVENTS T±7D</span>
          <span data-testid="mv-hero-events" style={{ fontFamily: "var(--display)", fontSize: 24 }}>{st.ev}</span>
        </div>
        <div title={row.odds.note ?? undefined} style={{ ...tile, background: ts.bg, border: `1px solid ${ts.line}` }}>
          <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: ".12em", color: ts.color }}>ODDS MODEL</span>
          <span data-testid="mv-hero-model" style={{ fontFamily: "var(--display)", fontSize: 24, color: ts.color }}>{mdl.short}</span>
        </div>
      </div>
    </section>
  );
}

// ═══ window controls (NOT in the design: a deliberate, functionally required addition) ═══════════════════════════════
type ControlsProps = {
  from: string; to: string; minAbsPct: number; direction: MoversDirection; includeCa: boolean; withheld: number | null;
  onFrom: (v: string) => void; onTo: (v: string) => void; onMinAbsPct: (n: number) => void;
  onDirection: (d: MoversDirection) => void; onToggleCa: () => void;
};
const lab: CSSProperties = { display: "flex", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 10, letterSpacing: ".12em", textTransform: "uppercase", color: "var(--ink-3)" };

export function MoversControls(p: ControlsProps) {
  const dirs: [MoversDirection, string][] = [["both", "Both ways"], ["up", "Up only"], ["down", "Down only"]];
  return (
    <div data-testid="mv-controls" style={{ display: "flex", flexDirection: "column", gap: 10, padding: "10px 14px", borderRadius: 14, background: "var(--bg-1)", border: "1px solid var(--line)" }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "10px 20px" }}>
        <label style={lab}>From
          <input className="mv4-ctl" type="date" value={p.from} max={p.to} data-testid="mv-from" onChange={(e) => p.onFrom(e.target.value || p.from)} /></label>
        <label style={lab}>To
          <input className="mv4-ctl" type="date" value={p.to} min={p.from} data-testid="mv-to" onChange={(e) => p.onTo(e.target.value || p.to)} /></label>
        <label style={lab}>Move at least
          <select className="mv4-ctl" value={p.minAbsPct} data-testid="mv-minpct" onChange={(e) => p.onMinAbsPct(Number(e.target.value))}>
            {[3, 5, 7, 10].map((v) => <option key={v} value={v}>{v}%</option>)}
          </select></label>
        <div role="group" aria-label="Direction" style={{ ...segWrap, borderRadius: 999 }}>
          {dirs.map(([d, l]) => {
            const on = p.direction === d;
            return (
              <button key={d} type="button" className="mv4-seg" aria-pressed={on} data-testid={`mv-dir-${d}`} onClick={() => p.onDirection(d)}
                style={{ border: 0, cursor: "pointer", padding: "6px 12px", borderRadius: 999, fontFamily: MONO, fontSize: 10.5, letterSpacing: ".1em", background: on ? "var(--bg-3)" : "transparent", color: on ? "var(--ink)" : "var(--ink-3)", transition: "all .15s ease" }}>{l}</button>
            );
          })}
        </div>
      </div>
      {p.withheld != null && p.withheld > 0 && (
        <p role="note" data-testid="mv-withheld" style={{ margin: 0, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, fontSize: 12, lineHeight: 1.5, color: "var(--ink-2)" }}>
          <span><b style={{ fontFamily: MONO, color: "var(--amber)" }}>{p.withheld}</b> move{p.withheld === 1 ? "" : "s"} held back as a suspected unadjusted split or bonus: the price fell by a round ratio and no corporate action is on record to match it.</span>
          <button type="button" className="mv4-link" data-testid="mv-include-ca" onClick={p.onToggleCa}>{p.includeCa ? "Hide them again" : "Show them anyway"}</button>
        </p>
      )}
    </div>
  );
}
