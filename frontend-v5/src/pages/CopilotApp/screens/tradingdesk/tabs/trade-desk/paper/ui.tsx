/**
 * Paper Trading v2 — the design's shared primitives (the owner's six-view design of 5 Nov 2026;
 * docs/scanner_paper_trading/UI_DESIGN_V2.md §1 "Visual language"). Every Paper Trading view draws with these:
 *
 *   Card          bg-1 + hairline + radius 14; an optional mono eyebrow title and a right-hand slot
 *   Tile          an inner tile: bg-2, radius 12 (tone: a soft tinted tile, e.g. Stop = danger-soft)
 *   Eyebrow       mono 10px uppercase
 *   Pill          mono 10px uppercase, tinted: mint = good, amber = caution, indigo = info / capital, danger = breach, plain
 *   Kpi           a KPI tile: eyebrow, serif tabular metric, a sub-line
 *   LevelBar      a 6–8px rounded bar on a bg-3 track, coloured by level: mint ≤ 80 % of the limit, amber > 80 %, danger > 100 %
 *   Synthesis     the serif headline sentence with one highlighted span (amber by default)
 *   SectionHeader eyebrow, the h1 or synthesis, an optional prose line, and a right-hand slot
 *   Glyph         ✓ pass (mint) · ! warn (amber) · × fail (danger)
 *   Note          the small ink-3 footnote
 *
 * In the app's tokens (pnl-ui.tsx TONES): --cp-ink*, --cp-line, --cp-danger, --cp-indigo, --mint, --amber, --bg-0..3,
 * --line-2/3 and the *-soft / *-line. The app's dark/light theme applies; there is no separate toggle. Formatting only:
 * nothing here computes a figure.
 */
import type { CSSProperties, ReactNode } from "react";
import { useCopilotShell } from "../../../../../lib/shell-context";
import { MONO, SERIF, TONES } from "../pnl-ui";

export type PillTone = "mint" | "amber" | "indigo" | "danger" | "plain";
export type Level = "mint" | "amber" | "danger";

const toneOf = (t: PillTone) => TONES[t === "plain" ? "ink" : t];
/** The foreground colour of a tone (plain = ink-2). */
export const toneColor = (t: PillTone | "ink" | "ink3"): string =>
  t === "ink3" ? "var(--cp-ink-3)" : t === "plain" || t === "ink" ? "var(--cp-ink-2)" : TONES[t].c;

export const NUM: CSSProperties = { fontVariantNumeric: "tabular-nums" };
export const mono10: CSSProperties = { fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase" };

// ── containers ───────────────────────────────────────────────────────────

export function Card({ title, right, testId, children, style, pad = 18, attrs }: {
  title?: ReactNode; right?: ReactNode; testId?: string; children: ReactNode; style?: CSSProperties; pad?: number; attrs?: Record<string, string>;
}) {
  const { mobile } = useCopilotShell();
  const p = mobile ? Math.min(pad, 14) : pad;
  return (
    <section data-testid={testId} {...attrs} className="flex min-w-0 flex-col"
      style={{ gap: 14, padding: p, borderRadius: 14, border: "1px solid var(--cp-line)", background: "var(--bg-1)", minWidth: 0, ...style }}>
      {(title || right) && (
        <div className="flex min-w-0 flex-wrap items-center justify-between" style={{ gap: "6px 12px" }}>
          {title ? <Eyebrow as="h3">{title}</Eyebrow> : <span />}
          {right && <div className="flex min-w-0 flex-wrap items-center" style={{ gap: 8 }}>{right}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

/** An inner tile: bg-2, radius 12; a tone tints it (Stop = danger-soft, T1 / T2 = mint-soft). */
export function Tile({ tone, children, testId, style, attrs }: { tone?: PillTone; children: ReactNode; testId?: string; style?: CSSProperties; attrs?: Record<string, string> }) {
  const t = tone && tone !== "plain" ? toneOf(tone) : null;
  return (
    <div data-testid={testId} data-tone={tone ?? ""} {...attrs} className="flex min-w-0 flex-col"
      style={{ gap: 4, padding: "10px 12px", borderRadius: 12, background: t ? t.soft : "var(--bg-2)", border: `1px solid ${t ? t.line : "transparent"}`, minWidth: 0, ...style }}>
      {children}
    </div>
  );
}

// ── type ─────────────────────────────────────────────────────────────────

export function Eyebrow({ children, tone, as = "span", testId, style }: { children: ReactNode; tone?: PillTone; as?: "span" | "h3" | "h2"; testId?: string; style?: CSSProperties }) {
  const El = as;
  return (
    <El data-testid={testId} className="m-0" style={{ ...mono10, fontWeight: 400, color: tone ? toneColor(tone) : "var(--cp-ink-3)", ...style }}>
      {children}
    </El>
  );
}

export function Pill({ tone, children, dot, testId, attrs, title, style }: {
  tone: PillTone; children: ReactNode; dot?: boolean; testId?: string; attrs?: Record<string, string>; title?: string; style?: CSSProperties;
}) {
  const t = toneOf(tone);
  const c = toneColor(tone);
  return (
    <span data-testid={testId} data-tone={tone} title={title} {...attrs}
      style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "3px 9px", borderRadius: 999, border: `1px solid ${t.line}`, background: t.soft,
        color: c, ...mono10, whiteSpace: "nowrap", ...style }}>
      {dot && <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: tone === "plain" ? "var(--cp-ink-3)" : c, flex: "none" }} />}
      {children}
    </span>
  );
}

/** The footnote: small, ink-3. */
export function Note({ children, testId, style }: { children: ReactNode; testId?: string; style?: CSSProperties }) {
  return <p data-testid={testId} className="m-0" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere", ...style }}>{children}</p>;
}

/** A KPI tile: eyebrow label, the serif tabular metric (32px; 26px on a phone), a sub-line. */
export function Kpi({ label, value, sub, tone, testId, size }: { label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: PillTone; testId?: string; size?: number }) {
  const { mobile } = useCopilotShell();
  return (
    <Tile testId={testId} attrs={{ "data-tone": tone ?? "" }} style={{ gap: 6, padding: "12px 14px" }}>
      <Eyebrow>{label}</Eyebrow>
      <span data-testid={testId ? `${testId}-value` : undefined}
        style={{ fontFamily: SERIF, fontSize: size ?? (mobile ? 26 : 32), lineHeight: 1.05, color: tone ? toneColor(tone) : "var(--cp-ink)", ...NUM, overflowWrap: "anywhere" }}>
        {value}
      </span>
      {sub != null && <span data-testid={testId ? `${testId}-sub` : undefined} style={{ fontSize: 11.5, lineHeight: 1.4, color: "var(--cp-ink-3)", ...NUM, overflowWrap: "anywhere" }}>{sub}</span>}
    </Tile>
  );
}

/** A grid of KPI tiles that auto-fits at `min` px. */
export function KpiGrid({ min, children, testId }: { min: number; children: ReactNode; testId?: string }) {
  const { mobile } = useCopilotShell();
  return (
    <div data-testid={testId} className="grid min-w-0" style={{ gap: 10, gridTemplateColumns: `repeat(auto-fit,minmax(min(100%,${mobile ? Math.min(min, 150) : min}px),1fr))` }}>
      {children}
    </div>
  );
}

// ── bars ─────────────────────────────────────────────────────────────────

/** The level of a use against its limit: mint ≤ 80 %, amber > 80 %, danger > 100 %; null when either is unknown. */
export function levelOf(used: number | null | undefined, limit: number | null | undefined): Level | null {
  if (used == null || limit == null || !Number.isFinite(used) || !Number.isFinite(limit) || limit <= 0) return null;
  const r = used / limit;
  return r > 1 ? "danger" : r > 0.8 ? "amber" : "mint";
}

/** A rounded bar on a bg-3 track. Width = used / limit (capped at 100 %); colour by level unless `tone` fixes it (indigo = capital). */
export function LevelBar({ used, limit, tone, height = 6, testId, label }: {
  used: number | null | undefined; limit: number | null | undefined; tone?: PillTone; height?: number; testId?: string; label?: string;
}) {
  const lvl = levelOf(used, limit);
  const known = lvl != null;
  const pct = known ? Math.max(0, Math.min(100, ((used as number) / (limit as number)) * 100)) : 0;
  const colour = tone ? (tone === "indigo" && lvl === "danger" ? toneColor("danger") : toneColor(tone)) : lvl ? toneColor(lvl) : "var(--cp-ink-3)";
  return (
    <div data-testid={testId} data-level={lvl ?? "unknown"} data-pct={known ? pct.toFixed(1) : ""} role="img"
      aria-label={label ? `${label}: ${known ? `${Math.round(((used as number) / (limit as number)) * 100)}% of the limit` : "unknown"}` : undefined}
      style={{ height, borderRadius: 999, background: "var(--bg-3)", overflow: "hidden", minWidth: 0 }}>
      <div style={{ width: `${pct}%`, height: "100%", borderRadius: 999, background: colour, transition: "width 300ms ease" }} />
    </div>
  );
}

/** A bar with a fixed width share (0–100) and colour: the pipeline's relative bars. */
export function ShareBar({ pct, colour, height = 8, testId }: { pct: number; colour: string; height?: number; testId?: string }) {
  const w = Math.max(0, Math.min(100, pct));
  return (
    <div data-testid={testId} data-pct={w.toFixed(1)} style={{ height, borderRadius: 999, background: "var(--bg-3)", overflow: "hidden", minWidth: 0 }}>
      <div style={{ width: `${w}%`, height: "100%", borderRadius: 999, background: colour, transition: "width 300ms ease" }} />
    </div>
  );
}

// ── headlines ────────────────────────────────────────────────────────────

export type SynthesisPart = string | { hi: string; tone?: PillTone };

/** The serif synthesis sentence (32px; 24px on a phone), its highlighted span in amber unless a part names a tone. */
export function Synthesis({ parts, testId = "pv2-synthesis" }: { parts: SynthesisPart[]; testId?: string }) {
  const { mobile } = useCopilotShell();
  return (
    <h2 data-testid={testId} className="m-0" style={{ fontFamily: SERIF, fontWeight: 400, fontSize: mobile ? 24 : 32, lineHeight: 1.15, letterSpacing: "-0.01em", color: "var(--cp-ink)", overflowWrap: "anywhere" }}>
      {parts.map((p, i) => typeof p === "string" ? <span key={i}>{p}</span>
        : <span key={i} data-testid={`${testId}-hi`} style={{ color: toneColor(p.tone ?? "amber") }}>{p.hi}</span>)}
    </h2>
  );
}

/** The view header: mono eyebrow, then the h1 (serif 28px) or a Synthesis, an optional prose line, and a right-hand slot. */
export function SectionHeader({ eyebrow, title, synthesis, prose, right, testId }: {
  eyebrow: ReactNode; title?: ReactNode; synthesis?: SynthesisPart[]; prose?: ReactNode; right?: ReactNode; testId?: string;
}) {
  const { mobile } = useCopilotShell();
  return (
    <header data-testid={testId} className="flex min-w-0 flex-wrap items-end justify-between" style={{ gap: "10px 18px" }}>
      <div className="flex min-w-0 flex-col" style={{ gap: 8, flex: "1 1 420px" }}>
        <Eyebrow testId={testId ? `${testId}-eyebrow` : undefined}>{eyebrow}</Eyebrow>
        {synthesis ? <Synthesis parts={synthesis} testId={testId ? `${testId}-synthesis` : undefined} />
          : title ? (
            <h2 data-testid={testId ? `${testId}-title` : undefined} className="m-0"
              style={{ fontFamily: SERIF, fontWeight: 400, fontSize: mobile ? 22 : 28, lineHeight: 1.15, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>
              {title}
            </h2>
          ) : null}
        {prose && <p data-testid={testId ? `${testId}-prose` : undefined} className="m-0" style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 820, overflowWrap: "anywhere" }}>{prose}</p>}
      </div>
      {right && <div className="flex min-w-0 flex-wrap items-center" style={{ gap: 8 }}>{right}</div>}
    </header>
  );
}

// ── marks ────────────────────────────────────────────────────────────────

export type GlyphKind = "pass" | "warn" | "fail" | "not_measured";
const GLYPH: Record<GlyphKind, { g: string; tone: PillTone }> = {
  pass: { g: "✓", tone: "mint" }, warn: { g: "!", tone: "amber" }, fail: { g: "×", tone: "danger" }, not_measured: { g: "!", tone: "amber" },
};

/** ✓ mint pass · ! amber warn (and not measured) · × danger fail. */
export function Glyph({ kind, testId }: { kind: GlyphKind; testId?: string }) {
  const x = GLYPH[kind];
  const t = toneOf(x.tone);
  return (
    <span data-testid={testId} data-kind={kind} aria-label={kind.replace("_", " ")}
      style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", flex: "none", width: 18, height: 18, borderRadius: 6,
        background: t.soft, color: t.c, fontFamily: MONO, fontSize: 11, fontWeight: 600 }}>
      {x.g}
    </span>
  );
}

/** A small coloured dot (the warnings list). */
export function Dot({ tone, size = 8 }: { tone: PillTone; size?: number }) {
  return <span aria-hidden style={{ width: size, height: size, borderRadius: "50%", background: toneColor(tone), flex: "none", marginTop: 5 }} />;
}

/** A two-column grid (the design's 1.3fr / 1fr etc.), one column under 900px of room. */
export function Split({ cols, children, testId, narrow }: { cols: string; children: ReactNode; testId?: string; narrow?: boolean }) {
  return (
    <div data-testid={testId} className="grid min-w-0" style={{ gap: 16, gridTemplateColumns: narrow ? "minmax(0,1fr)" : cols, alignItems: "start" }}>
      {children}
    </div>
  );
}
