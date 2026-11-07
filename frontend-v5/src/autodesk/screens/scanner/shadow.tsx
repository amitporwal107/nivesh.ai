/**
 * Shadow scores on the desk screens (package 5 part B). A signal's stored body may carry `shadow_scores` — scores from
 * scoring versions that are NOT the active one (backend/autodesk/scoring/registry.py). They are shown for comparison only and
 * never change ranking, selection or any plan: every use carries the label "shadow — not used for selection".
 */
import { DASH, num } from "../../format";
import type { SignalRow } from "../../types";

export const SHADOW_LABEL = "shadow — not used for selection";

export interface ShadowComponent { dimension: string; weight: number | string; points: number | string; available?: boolean; detail?: string | null }
export interface ShadowScore {
  version: string;
  score?: number | string | null;
  band?: string | null;
  tier?: string | null;
  primary_signal?: string | null;
  signals?: string[];
  context_signals?: string[];
  warnings?: string[];
  components?: ShadowComponent[];
  reasons?: string[];
}

/** "v2-positional" → "v2", "v21-positional" → "v2.1" (the registry keys are the source of truth, this is only a label). */
export function versionTag(version: string): string {
  const v = version.split("-")[0];
  return v === "v21" ? "v2.1" : v;
}

export function shadowScoresOf(sig: SignalRow): ShadowScore[] {
  const raw = (sig.body as Record<string, unknown> | undefined)?.shadow_scores;
  return Array.isArray(raw) ? (raw as ShadowScore[]) : [];
}

const words = (s: string) => s.replace(/_/g, " ").toLowerCase();

/** `v2 77.5 · Strong` — or `v2 not scored` when the version could not score this stock. */
export function chipText(s: ShadowScore): string {
  const n = num(s.score);
  return n == null ? `${versionTag(s.version)} not scored` : `${versionTag(s.version)} ${n.toFixed(1)} · ${s.band ?? DASH}`;
}

/** One small chip per shadow version, for a signal row. Renders nothing when the signal has no shadow scores. */
export function ShadowChips({ sig }: { sig: SignalRow }) {
  const list = shadowScoresOf(sig);
  if (!list.length) return null;
  return (
    <span data-testid="shadow-chips" title={SHADOW_LABEL} style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
      {list.map((s) => (
        <span key={s.version} className="nv-pill" data-testid="shadow-chip" data-version={s.version} style={{ padding: "1px 6px", fontSize: 8.5, textTransform: "none", color: "var(--ink-3)" }}>{chipText(s)}</span>
      ))}
    </span>
  );
}

/** The expanded-row section: per version the score, tier, signals and the attributed components. */
export function ShadowBreakdown({ sig, compact }: { sig: SignalRow; compact?: boolean }) {
  const list = shadowScoresOf(sig);
  return (
    <div data-testid="shadow-section" style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
      <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>Shadow scoring — not used for selection</span>
      {list.length === 0 && <span data-testid="shadow-none" style={{ fontSize: 12, color: "var(--ink-3)" }}>No shadow score stored with this signal.</span>}
      {list.map((s) => {
        const n = num(s.score);
        return (
          <div key={s.version} data-testid="shadow-version" data-version={s.version} style={{ display: "flex", flexDirection: "column", gap: 5, fontSize: compact ? 11.5 : 12 }}>
            <span style={{ color: "var(--ink)" }}>
              <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)" }}>{s.version}</span>{" "}
              <span data-testid="shadow-score" className="nv-num">{n == null ? "not scored" : `${n.toFixed(1)} · ${s.band ?? DASH}`}</span>
              {s.tier && <span style={{ color: "var(--ink-3)" }}> · {s.tier}</span>}
            </span>
            {n == null && (s.reasons ?? []).map((r) => <span key={r} data-testid="shadow-reason" style={{ color: "var(--ink-3)" }}>{r}</span>)}
            {s.primary_signal && <span style={{ color: "var(--ink-2)" }}>Primary signal: {words(s.primary_signal)}</span>}
            {(s.signals?.length ?? 0) > 0 && <span style={{ color: "var(--ink-2)" }}>Signals: {s.signals!.map(words).join(", ")}</span>}
            {(s.context_signals?.length ?? 0) > 0 && <span style={{ color: "var(--ink-2)" }}>Context only: {s.context_signals!.map(words).join(", ")}</span>}
            {(s.warnings?.length ?? 0) > 0 && <span data-testid="shadow-warnings" style={{ color: "var(--ink-2)" }}>Warnings: {s.warnings!.map(words).join(", ")}</span>}
            {(s.components ?? []).map((c) => (
              <div key={c.dimension} data-testid={`shadow-dim-${c.dimension}`} title={c.detail || undefined} style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 54px", gap: 8, alignItems: "baseline" }}>
                <span style={{ color: c.available === false ? "var(--ink-4)" : "var(--ink-2)", overflowWrap: "anywhere" }}>{words(c.dimension)}{c.detail ? ` — ${c.detail}` : ""}</span>
                <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 10.5, textAlign: "right", color: "var(--ink-3)" }}>{num(c.points)} / {num(c.weight)}</span>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
