/**
 * The bottom bar (§38.3 item 5, §38.7): range presets, go-to-date, a fixed IST clock, the ADJ toggle and the
 * price-scale mode. Presentational; range button state/reasons come straight from `ranges.ts#RANGE_PRESETS` (the
 * same source `resolveRange` reads), so there is exactly one place that knows 1D/5D are disabled and why.
 */
import { useEffect, useState } from "react";
import { RANGE_PRESETS, type RangePreset } from "./ranges";
import type { ScaleMode } from "./types";

const SCALE_LABEL: Record<ScaleMode, string> = { auto: "Auto", log: "Log", percent: "%" };

export interface BottomBarProps {
  activeRange: RangePreset | null;
  onSelectRange: (preset: RangePreset) => void;

  /** ISO `YYYY-MM-DD`, or "" for no selection yet. */
  goToDateValue: string;
  onGoToDate: (dateISO: string) => void;
  /** Bounds passed straight to the native date input (the series' first/last bar) — keeps a user from picking a
   *  date the snapshot has no bar for. */
  minDate?: string;
  maxDate?: string;

  adjOn: boolean;
  onToggleAdj: () => void;
  /** §38.7: "Kite daily bars are back-adjusted... a raw series has to come from NSE bhavcopy. Until a raw series
   *  is exported, the toggle is disabled with that reason." Always disabled in W1 — the prop exists so the
   *  reason text (and the eventual W4 enable) lives with the caller, not hardcoded here. */
  adjDisabledReason: string;

  scaleMode: ScaleMode;
  onScaleModeChange: (m: ScaleMode) => void;

  className?: string;
}

export default function BottomBar(props: BottomBarProps) {
  const {
    activeRange, onSelectRange, goToDateValue, onGoToDate, minDate, maxDate,
    adjOn, onToggleAdj, adjDisabledReason, scaleMode, onScaleModeChange, className,
  } = props;

  return (
    <div
      data-testid="chart-bottombar"
      className={className}
      style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 10px", borderTop: "1px solid var(--c-line)", background: "var(--bg-1)", flexWrap: "wrap", fontSize: 12 }}
    >
      <div role="toolbar" aria-label="Range presets" data-testid="chart-range-presets" style={{ display: "flex", gap: 3 }}>
        {RANGE_PRESETS.map((r) => (
          <button
            key={r.id}
            type="button"
            data-testid={`chart-range-${r.id}`}
            onClick={() => r.enabled && onSelectRange(r.id)}
            disabled={!r.enabled}
            aria-disabled={!r.enabled || undefined}
            aria-pressed={activeRange === r.id}
            aria-label={r.enabled ? `Show ${r.label} range` : `${r.label} range — disabled, ${r.disabledReason}`}
            title={r.enabled ? `Show ${r.label}` : `${r.label} disabled — ${r.disabledReason}`}
            style={{
              padding: "4px 8px", borderRadius: 7, border: "1px solid transparent", fontSize: 11.5,
              background: activeRange === r.id ? "var(--mint-soft)" : "transparent",
              color: !r.enabled ? "var(--c-ink-4)" : activeRange === r.id ? "var(--mint)" : "var(--c-ink-2)",
              cursor: r.enabled ? "pointer" : "not-allowed",
            }}
          >
            {r.label}
          </button>
        ))}
      </div>

      <div style={{ width: 1, height: 18, background: "var(--c-line)" }} />

      <label style={{ display: "flex", alignItems: "center", gap: 5, color: "var(--c-ink-3)" }}>
        <span className="sr-only">Go to date</span>
        <input
          type="date" data-testid="chart-go-to-date" aria-label="Go to date" title="Go to date"
          value={goToDateValue} min={minDate} max={maxDate}
          onChange={(e) => onGoToDate(e.target.value)}
          style={{ padding: "3px 6px", borderRadius: 6, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--c-ink)", fontSize: 11.5 }}
        />
      </label>

      <span style={{ marginLeft: "auto" }} />

      <IstClock />

      <div style={{ width: 1, height: 18, background: "var(--c-line)" }} />

      <button
        type="button" data-testid="chart-adj-toggle" disabled aria-disabled="true" aria-pressed={adjOn}
        aria-label={`Adjusted / raw prices — disabled, ${adjDisabledReason}`}
        onClick={onToggleAdj} title={`Adjusted / raw — ${adjDisabledReason}`}
        style={{ padding: "4px 8px", borderRadius: 7, border: "1px solid var(--line-2)", fontSize: 11, color: "var(--c-ink-4)", cursor: "not-allowed", opacity: 0.6 }}
      >
        ADJ
      </button>

      <div role="toolbar" aria-label="Price scale mode" data-testid="chart-scale-mode" style={{ display: "flex", gap: 3 }}>
        {(Object.keys(SCALE_LABEL) as ScaleMode[]).map((m) => (
          <button
            key={m} type="button" data-testid={`chart-scale-${m}`} onClick={() => onScaleModeChange(m)}
            aria-pressed={scaleMode === m} aria-label={`${SCALE_LABEL[m]} price scale`} title={`${SCALE_LABEL[m]} price scale`}
            style={{
              padding: "4px 8px", borderRadius: 7, fontSize: 11.5, border: "1px solid transparent",
              background: scaleMode === m ? "var(--mint-soft)" : "transparent",
              color: scaleMode === m ? "var(--mint)" : "var(--c-ink-2)", cursor: "pointer",
            }}
          >
            {SCALE_LABEL[m]}
          </button>
        ))}
      </div>
    </div>
  );
}

/** §38.7: "Clock: IST, fixed and shown. There is no timezone picker." Self-contained — no props, ticks itself. */
function IstClock() {
  const [now, setNow] = useState(() => formatIst(new Date()));
  useEffect(() => {
    const id = window.setInterval(() => setNow(formatIst(new Date())), 1000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <span data-testid="chart-ist-clock" className="nv-mono" title="India Standard Time" style={{ color: "var(--c-ink-3)", fontSize: 11 }}>
      {now} IST
    </span>
  );
}

function formatIst(d: Date): string {
  return new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(d);
}
