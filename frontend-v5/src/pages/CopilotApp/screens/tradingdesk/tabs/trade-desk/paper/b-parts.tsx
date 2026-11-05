/**
 * Paper Trading v2 (builder B) — the private parts of 03 Capital allocation, 04 Portfolio risk and 05 Real-time P&L
 * (docs/scanner_paper_trading/UI_DESIGN_V2.md §2.03–§2.05): bars with a value, the limit-utilization row, the correlation
 * matrix, the position-in-plan marker, the intraday equity curve, the F&O strategy card and the Paper / Live switch.
 * Formatting and geometry only: every figure comes from a route; a null shows "—" (with the reason nearby), never 0.
 */
import { useMemo, type CSSProperties, type ReactNode } from "react";
import { LoadingBlock, fmtINR, fmtNum } from "../../../../../components/ui";
import { QueryProblem } from "../../../../trading/parts";
import { MONO, SERIF } from "../pnl-ui";
import { usePaperAccount } from "./api-a";
import type { Correlation, FnoStructure } from "./api-b";
import { Eyebrow, Note, Pill, Tile, levelOf, mono10, toneColor, type Level, type PillTone } from "./ui";

export const DASH = "—";
export const rs0 = (v: number | null | undefined) => fmtINR(v ?? null);
export const rsC = (v: number | null | undefined) => fmtINR(v ?? null, { compact: v != null && Math.abs(v) >= 1_00_000 });
/** Signed rupees: "+₹1,234" / "−₹40"; "—" when unknown. */
export const rsS = (v: number | null | undefined) => fmtINR(v ?? null, { signed: true });
export const pctTxt = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? DASH : `${fmtNum(v, d)}%`);
export const sgnPct = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? DASH : `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmtNum(Math.abs(v), d)}%`);
export const ofPct = (part: number | null | undefined, whole: number | null | undefined) =>
  part == null || whole == null || !Number.isFinite(part) || !Number.isFinite(whole) || whole <= 0 ? null : (part / whole) * 100;
export const signTone = (v: number | null | undefined): PillTone => (v == null || v === 0 ? "plain" : v > 0 ? "mint" : "danger");
export const px2 = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? DASH : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

// ── no account id yet ────────────────────────────────────────────────────

/** What to show while the view has no account id: still reading (the shell's own read, one cache), failed, or none returned. */
export function AccountMissing({ what }: { what: string }) {
  const acct = usePaperAccount();
  if (acct.isPending) return <LoadingBlock label="Reading your paper account" rows={3} />;
  if (acct.isError) return <div data-testid="pv2-account-error"><QueryProblem what="Your paper account" error={acct.error} onRetry={() => { void acct.refetch(); }} /></div>;
  return <Note testId="pv2-no-account">No paper account was returned for you, so {what}.</Note>;
}

// ── bars ─────────────────────────────────────────────────────────────────

/**
 * A rounded bar of `used` against `limit` with its % on the right. Colour: `base` (indigo for capital) while under the limit; with
 * `levels`, amber over 80 % and danger over 100 % (the design's level rule); without, danger only when over.
 */
export function ValueBar({ used, limit, base, levels = true, testId, label, height = 7, right }: {
  used: number | null | undefined; limit: number | null | undefined; base?: PillTone; levels?: boolean; testId?: string; label: string; height?: number; right?: ReactNode;
}) {
  const lvl = levelOf(used, limit);
  const pct = lvl ? ((used as number) / (limit as number)) * 100 : null;
  const colour = lvl == null ? "var(--cp-ink-3)"
    : lvl === "danger" ? toneColor("danger")
      : lvl === "amber" && levels ? toneColor("amber")
        : base ? toneColor(base) : toneColor(lvl);
  return (
    <div data-testid={testId} data-level={lvl ?? "unknown"} data-pct={pct == null ? "" : pct.toFixed(1)} className="grid min-w-0 items-center"
      style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: 10 }}>
      <div role="img" aria-label={`${label}: ${pct == null ? "unknown" : `${Math.round(pct)}% of the limit`}`}
        style={{ height, borderRadius: 999, background: "var(--bg-3)", overflow: "hidden", minWidth: 0 }}>
        <div style={{ width: `${pct == null ? 0 : Math.max(0, Math.min(100, pct))}%`, height: "100%", borderRadius: 999, background: colour, transition: "width 300ms ease" }} />
      </div>
      <span data-testid={testId ? `${testId}-pct` : undefined} style={{ fontFamily: MONO, fontSize: 11.5, minWidth: 44, textAlign: "right", color: lvl === "danger" ? toneColor("danger") : "var(--cp-ink-2)", fontVariantNumeric: "tabular-nums" }}>
        {right ?? (pct == null ? DASH : `${fmtNum(pct, 0)}%`)}
      </span>
    </div>
  );
}

/** "NEAR LIMIT" (amber, over 80 %) / "BREACH" (danger, over 100 %); nothing otherwise. */
export function LimitFlag({ level, testId }: { level: Level | null; testId?: string }) {
  if (level !== "amber" && level !== "danger") return null;
  return <span data-testid={testId} data-level={level} style={{ ...mono10, color: toneColor(level) }}>{level === "danger" ? "BREACH" : "NEAR LIMIT"}</span>;
}

/** One limit-utilization row: name, its status, "value / limit", the levelled bar; `note` says what a "—" is missing. */
export function LimitRow({ k, name, used, limit, show, note }: {
  k: string; name: string; used: number | null; limit: number | null; show: (v: number | null) => string; note?: string | null;
}) {
  const lvl = levelOf(used, limit);
  return (
    <div data-testid="pv2-limit-row" data-key={k} data-level={lvl ?? "unknown"} className="flex min-w-0 flex-col" style={{ gap: 6, padding: "10px 0", borderTop: "1px solid var(--cp-line)" }}>
      <div className="flex min-w-0 flex-wrap items-baseline justify-between" style={{ gap: "2px 10px" }}>
        <span className="flex min-w-0 items-baseline" style={{ gap: 8 }}>
          <span style={{ fontSize: 13, color: "var(--cp-ink)" }}>{name}</span>
          <LimitFlag level={lvl} testId="pv2-limit-flag" />
        </span>
        <span data-testid="pv2-limit-value" style={{ fontFamily: MONO, fontSize: 12, color: "var(--cp-ink-2)", fontVariantNumeric: "tabular-nums" }}>{show(used)} / {show(limit)}</span>
      </div>
      <ValueBar used={used} limit={limit} label={name} testId="pv2-limit-bar" height={6} />
      {note && <Note testId="pv2-limit-note">{note}</Note>}
    </div>
  );
}

// ── the correlation matrix ───────────────────────────────────────────────

export function CorrMatrix({ c, max = 6 }: { c: Correlation; max?: number }) {
  const n = Math.min(max, c.symbols.length);
  const syms = c.symbols.slice(0, n);
  const th = c.threshold ?? 0.7;
  const cell: CSSProperties = { height: 34, display: "grid", placeItems: "center", borderRadius: 6, fontFamily: MONO, fontSize: 11, fontVariantNumeric: "tabular-nums" };
  const label: CSSProperties = { fontFamily: MONO, fontSize: 10, letterSpacing: "0.04em", color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
  return (
    <div className="min-w-0" style={{ overflowX: "auto" }}>
      <div data-testid="pv2-corr" role="table" aria-label="Correlation of 60-day daily returns" className="grid"
        style={{ gridTemplateColumns: `minmax(64px,auto) repeat(${n}, minmax(44px,1fr))`, gap: 3, minWidth: 64 + n * 47 }}>
        <span role="columnheader" />
        {syms.map((s) => <span key={`h-${s}`} role="columnheader" data-testid="pv2-corr-col" style={{ ...label, textAlign: "center" }} title={s}>{s}</span>)}
        {syms.map((r, i) => (
          <div key={`r-${r}`} role="row" style={{ display: "contents" }}>
            <span role="rowheader" data-testid="pv2-corr-row" style={{ ...label, alignSelf: "center" }} title={r}>{r}</span>
            {syms.map((col, j) => {
              const v = c.matrix[i]?.[j] ?? null;
              const diag = i === j;
              const hot = !diag && v != null && v >= th;
              const a = v == null ? 0 : Math.min(1, Math.abs(v));
              const bg = diag ? "var(--bg-3)" : v == null ? "transparent"
                : hot ? "var(--danger-soft)" : `color-mix(in srgb, var(--cp-indigo) ${Math.round(8 + a * 40)}%, transparent)`;
              return (
                <span key={`${r}-${col}`} role="cell" data-testid="pv2-corr-cell" data-pair={`${r}|${col}`} data-value={v == null ? "" : String(v)}
                  data-hot={hot ? "true" : "false"} data-diag={diag ? "true" : "false"}
                  title={v == null && !diag ? `${r} × ${col}: no figure (see the notes)` : undefined}
                  style={{ ...cell, background: bg, border: v == null && !diag ? "1px dashed var(--line-2)" : "1px solid transparent",
                    color: hot ? toneColor("danger") : diag ? "var(--cp-ink-3)" : "var(--cp-ink)" }}>
                  {diag ? "1.00" : v == null ? DASH : v.toFixed(2)}
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── position in plan ─────────────────────────────────────────────────────

/** Where the price sits between the stop (0) and the target (1); null without both levels or the price. Clamped 0–1. */
export function planPos(ltp: number | null, stop: number | null, target: number | null): number | null {
  if (ltp == null || stop == null || target == null || target === stop) return null;
  const x = (ltp - stop) / (target - stop);
  return Number.isFinite(x) ? Math.max(0, Math.min(1, x)) : null;
}

/** R so far: the move from the entry in units of the entry-to-stop distance (long: up is +; short: down is +). */
export function rMultiple(side: "LONG" | "SHORT" | null, entry: number | null, ltp: number | null, stop: number | null): number | null {
  if (entry == null || ltp == null || stop == null) return null;
  const risk = side === "SHORT" ? stop - entry : entry - stop;
  if (!(risk > 0)) return null;
  const move = side === "SHORT" ? entry - ltp : ltp - entry;
  return move / risk;
}

export function PlanBar({ pos, testId = "pv2-pnl-plan" }: { pos: number | null; testId?: string }) {
  return (
    <div data-testid={testId} data-pos={pos == null ? "" : pos.toFixed(3)} title={pos == null ? "No stop and target on this position" : `${Math.round(pos * 100)}% of the way from the stop to the target`}
      style={{ position: "relative", height: 6, borderRadius: 999, minWidth: 90, background: pos == null ? "var(--bg-3)" : "linear-gradient(90deg, var(--danger-soft), var(--bg-3), var(--mint-soft))" }}>
      {pos != null && (
        <span aria-hidden style={{ position: "absolute", top: -3, left: `calc(${(pos * 100).toFixed(2)}% - 1.5px)`, width: 3, height: 12, borderRadius: 2,
          background: "var(--cp-ink)", transition: "left 400ms ease" }} />
      )}
    </div>
  );
}

// ── the intraday equity curve ────────────────────────────────────────────

const OPEN_MIN = 9 * 60 + 15;
const CLOSE_MIN = 15 * 60 + 30;
const HM = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
const minutesIST = (iso: string) => {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return null;
  const [h, m] = HM.format(new Date(t)).split(":").map(Number);
  return h * 60 + m;
};
export const hmOf = (iso: string | null) => (iso && Number.isFinite(Date.parse(iso)) ? HM.format(new Date(Date.parse(iso))) : null);

/** The session's P&L as an SVG area + line on a 09:15–15:30 IST axis, with a dashed zero line. */
export function EquityCurve({ points, height = 200, live }: { points: Array<{ t: string; v: number }>; height?: number; live: boolean }) {
  const W = 800, H = height;
  const geo = useMemo(() => {
    const pts = points.map((p) => ({ m: minutesIST(p.t), v: p.v })).filter((p): p is { m: number; v: number } => p.m != null);
    if (!pts.length) return null;
    const hi0 = Math.max(0, ...pts.map((p) => p.v)), lo0 = Math.min(0, ...pts.map((p) => p.v));
    const span = hi0 - lo0 || Math.max(1, Math.abs(hi0));
    const lo = lo0 - span * 0.1, hi = hi0 + span * 0.1;
    const X = (m: number) => (Math.max(0, Math.min(CLOSE_MIN - OPEN_MIN, m - OPEN_MIN)) / (CLOSE_MIN - OPEN_MIN)) * W;
    const Y = (v: number) => H - ((v - lo) / (hi - lo)) * H;
    const line = pts.map((p, i) => `${i ? "L" : "M"}${X(p.m).toFixed(1)} ${Y(p.v).toFixed(1)}`).join(" ");
    const zeroY = Y(0);
    const area = pts.length > 1 ? `${line} L${X(pts[pts.length - 1].m).toFixed(1)} ${zeroY.toFixed(1)} L${X(pts[0].m).toFixed(1)} ${zeroY.toFixed(1)} Z` : "";
    const last = pts[pts.length - 1];
    return { line, area, zeroY, endX: X(last.m), endY: Y(last.v), last: last.v };
  }, [points, H]);
  if (!geo) return null;
  const colour = geo.last < 0 ? "var(--cp-danger)" : "var(--mint)";
  const lastT = points.length ? hmOf(points[points.length - 1].t) : null;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <div data-testid="pv2-pnl-curve-plot" data-points={points.length} style={{ position: "relative", height: H }}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Intraday paper equity, net of costs" style={{ width: "100%", height: "100%", display: "block", overflow: "visible" }}>
          <line data-testid="pv2-pnl-curve-zero" x1={0} x2={W} y1={geo.zeroY} y2={geo.zeroY} stroke="var(--line-3)" strokeDasharray="4 5" vectorEffect="non-scaling-stroke" />
          {geo.area && <path d={geo.area} fill={colour} fillOpacity={0.1} />}
          {points.length > 1 && <path d={geo.line} fill="none" stroke={colour} strokeWidth={2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />}
        </svg>
        <span aria-hidden style={{ position: "absolute", left: `calc(${((geo.endX / W) * 100).toFixed(2)}% - 4px)`, top: `calc(${((geo.endY / H) * 100).toFixed(2)}% - 4px)`, width: 8, height: 8, borderRadius: "50%", background: colour }} />
      </div>
      <div data-testid="pv2-pnl-curve-axis" className="flex justify-between" style={{ ...mono10, color: "var(--cp-ink-4, var(--cp-ink-3))" }}>
        <span>09:15</span><span>{lastT ?? "—"} {live ? "NOW" : "LAST"}</span><span>15:30</span>
      </div>
    </div>
  );
}

// ── the Paper / Live switch ──────────────────────────────────────────────

export function ModeSwitch<T extends string>({ value, options, onChange, testId }: { value: T; options: Array<[T, string]>; onChange: (v: T) => void; testId: string }) {
  return (
    <div data-testid={testId} role="group" aria-label="Book" className="flex flex-none" style={{ gap: 2, padding: 3, borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}>
      {options.map(([v, label]) => {
        const on = v === value;
        return (
          <button key={v} type="button" data-testid={`${testId}-${v.toLowerCase()}`} aria-pressed={on} onClick={() => onChange(v)}
            style={{ cursor: "pointer", border: 0, padding: "5px 12px", borderRadius: 999, background: on ? "var(--bg-3)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)", ...mono10 }}>
            {label}
          </button>
        );
      })}
    </div>
  );
}

// ── the F&O strategy card (05 Real-time P&L) ─────────────────────────────

const legCols = "40px minmax(104px,1.6fr) minmax(54px,0.7fr) minmax(54px,0.7fr) 44px minmax(64px,0.9fr)";

export function FnoCard({ s, actions }: { s: FnoStructure; actions?: ReactNode }) {
  const partial = s.status === "partial" || s.legs.some((l) => l.pending);
  const lossUsed = s.pnlRs != null && s.maxLossRs != null && s.maxLossRs > 0 ? Math.max(0, -s.pnlRs) : null;
  const profit = s.pnlRs != null && s.maxProfitRs != null && s.maxProfitRs > 0 ? Math.max(0, s.pnlRs) : null;
  const filled = s.legs.filter((l) => !l.pending && l.qty != null && l.filledQty != null && l.filledQty >= l.qty).length;
  const tile = (label: string, value: ReactNode, tone?: PillTone, id?: string) => (
    <Tile tone={tone} testId={id}>
      <Eyebrow tone={tone}>{label}</Eyebrow>
      <span style={{ fontFamily: MONO, fontSize: 13.5, color: "var(--cp-ink)", fontVariantNumeric: "tabular-nums", overflowWrap: "anywhere" }}>{value}</span>
    </Tile>
  );
  return (
    <section data-testid="pv2-fno-card" data-id={s.id} data-status={partial ? "partial" : "filled"} className="flex min-w-0 flex-col"
      style={{ gap: 14, padding: 16, borderRadius: 14, border: `1px solid ${partial ? "var(--amber-line)" : "var(--cp-line)"}`, background: "var(--bg-1)" }}>
      <div className="flex min-w-0 flex-wrap items-start justify-between" style={{ gap: "8px 14px" }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <span data-testid="pv2-fno-name" style={{ fontSize: 15, fontWeight: 500, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{s.name}</span>
          <span data-testid="pv2-fno-meta" style={{ ...mono10, color: "var(--cp-ink-3)" }}>
            {s.underlying ?? DASH} · EXP {s.expiry ?? DASH} · {s.lots == null ? DASH : `${fmtNum(s.lots)} lot${s.lots === 1 ? "" : "s"}`}
          </span>
        </div>
        <span className="flex flex-wrap items-center" style={{ gap: 10 }}>
          {partial
            ? <Pill tone="amber" testId="pv2-fno-status">Partially filled · unhedged</Pill>
            : <Pill tone="mint" testId="pv2-fno-status">Filled · {s.hedged === false ? "unhedged" : "hedged"}</Pill>}
          <span data-testid="pv2-fno-pnl" style={{ fontFamily: SERIF, fontSize: 30, lineHeight: 1, color: toneColor(signTone(s.pnlRs)), fontVariantNumeric: "tabular-nums" }}>{rsS(s.pnlRs)}</span>
        </span>
      </div>
      <div className="grid min-w-0" style={{ gap: 8, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,120px),1fr))" }}>
        {tile("Max loss", rs0(s.maxLossRs), "danger", "pv2-fno-maxloss")}
        {tile("Max profit", s.maxProfitRs == null ? (s.profitUnbounded ? "Unbounded" : DASH) : rs0(s.maxProfitRs), "mint", "pv2-fno-maxprofit")}
        {tile("Breakeven", s.breakevens.length ? s.breakevens.map(px2).join(" · ") : DASH, undefined, "pv2-fno-breakeven")}
        {tile("Net delta", s.net.delta == null ? DASH : fmtNum(s.net.delta, 2), undefined, "pv2-fno-delta")}
        {tile("Net theta", s.net.thetaRsDay == null ? DASH : `${rsS(s.net.thetaRsDay)} / day`, undefined, "pv2-fno-theta")}
        {tile("Margin", rs0(s.marginRs), "indigo", "pv2-fno-margin")}
      </div>
      <div className="grid min-w-0" style={{ gap: 10, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,220px),1fr))" }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 5 }}>
          <Eyebrow>Loss used of max</Eyebrow>
          <ValueBar used={lossUsed} limit={s.maxLossRs} base="danger" levels={false} label="Loss used of the maximum loss" testId="pv2-fno-lossbar" />
        </div>
        <div className="flex min-w-0 flex-col" style={{ gap: 5 }}>
          <Eyebrow>Profit captured of max</Eyebrow>
          <ValueBar used={profit} limit={s.maxProfitRs} base="mint" levels={false} label="Profit captured of the maximum profit" testId="pv2-fno-profitbar"
            right={s.maxProfitRs == null && s.profitUnbounded ? "no cap" : undefined} />
        </div>
      </div>
      <div className="min-w-0" style={{ overflowX: "auto" }}>
        <div data-testid="pv2-fno-legs" role="table" aria-label={`${s.name} legs`} style={{ minWidth: 410 }}>
          <div role="row" className="grid" style={{ gridTemplateColumns: legCols, gap: 8, padding: "6px 0", borderBottom: "1px solid var(--cp-line)" }}>
            {["Leg", "Contract", "Entry", "LTP", "Filled", "Leg P&L"].map((h, i) => <span key={h} role="columnheader" style={{ ...mono10, color: "var(--cp-ink-3)", textAlign: i >= 2 ? "right" : "left" }}>{h}</span>)}
          </div>
          {s.legs.map((l, i) => {
            const unfilled = l.pending || (l.qty != null && l.filledQty != null && l.filledQty < l.qty);
            const num: CSSProperties = { textAlign: "right", fontFamily: MONO, fontSize: 12, fontVariantNumeric: "tabular-nums" };
            return (
              <div key={`${l.contract}-${i}`} role="row" data-testid="pv2-fno-leg" data-pending={l.pending ? "true" : "false"} className="grid items-center"
                style={{ gridTemplateColumns: legCols, gap: 8, padding: "8px 0", borderBottom: "1px solid var(--cp-line)" }}>
                <span role="cell" data-testid="pv2-fno-leg-side" style={{ ...mono10, color: l.side === "BUY" ? toneColor("mint") : l.side === "SELL" ? "var(--rose, var(--cp-danger))" : "var(--cp-ink-3)" }}>{l.side ?? DASH}</span>
                <span role="cell" style={{ fontSize: 12.5, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{l.contract}</span>
                <span role="cell" style={num}>{px2(l.entry)}</span>
                <span role="cell" style={num}>{px2(l.ltp)}</span>
                <span role="cell" data-testid="pv2-fno-leg-filled" style={{ ...num, color: unfilled ? toneColor("amber") : "var(--cp-ink-2)" }}>
                  {l.filledQty == null ? DASH : fmtNum(l.filledQty)}/{l.qty == null ? DASH : fmtNum(l.qty)}
                </span>
                <span role="cell" data-testid="pv2-fno-leg-pnl" style={{ ...num, color: l.pending ? toneColor("amber") : toneColor(signTone(l.pnlRs)) }}>
                  {l.pending ? "PENDING" : rsS(l.pnlRs)}
                </span>
              </div>
            );
          })}
          {!s.legs.length && <Note>No legs were sent for this structure.</Note>}
        </div>
      </div>
      {partial && (
        <div data-testid="pv2-fno-partial" role="note" style={{ padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink)" }}>
          {filled} of {s.legs.length} legs are filled. Until the hedge leg fills, the filled legs are unhedged: their loss is not bounded by this structure's
          max loss of {rs0(s.maxLossRs)}. {s.note ?? ""}
        </div>
      )}
      {!partial && s.note && <Note>{s.note}</Note>}
      {actions}
    </section>
  );
}
