/**
 * The field guide (design artifact tab 3A, "What every field on the screen means").
 *
 * 3A in the artifact is one table covering all four designed screens. Most of its rows describe 2A
 * (signals, alerts, score components) and 4A (paper trading, cost model, ledger) — screens that do
 * not exist. Documenting those here would describe a product we do not have, so this guide covers
 * ONLY fields the Charts screen actually renders. It is a panel on the existing screen, opened from
 * the toolbar's More menu, not a new screen.
 *
 * Where the artifact's wording and the code disagree, the code wins. The clearest case is level
 * strength: 3A says "touch count, reaction size and volume confirmation", while the engine
 * (research/charting/geometry.py level_strength, docs/charting.md §13.2) combines touch, recency,
 * rejection, volume and time by frozen weights. The engine's definition is the one written below —
 * a dictionary that describes something other than the running system is worse than no dictionary.
 */
import { useMemo, useState } from "react";

export interface FieldGuideProps {
  open: boolean;
  onClose: () => void;
}

interface Row {
  /** The label exactly as the screen shows it. */
  term: string;
  meaning: string;
  /** Where the value comes from — a snapshot field, a spec section, or "derived". */
  source: string;
}
interface Group { name: string; where: string; accent: string; rows: Row[] }

const GROUPS: Group[] = [
  {
    name: "TOP BAR", where: "ABOVE THE CHART", accent: "var(--mint)",
    rows: [
      { term: "RELIANCE · NSE · EQ", meaning: "The symbol being charted and its exchange segment. Click it to search for another.", source: "SNAPSHOT MANIFEST" },
      { term: "2,985.40 · +0.40 (+0.01%)", meaning: "The last close in the frozen snapshot and its change against the previous bar. This is not a live price.", source: "SNAPSHOT BARS" },
      { term: "VALID / PARTIAL / PIT_UNVERIFIED", meaning: "Data-quality and point-in-time status for this symbol's bars. PIT_UNVERIFIED outranks PARTIAL when both apply.", source: "data_quality_status · pit_status" },
      { term: "1D / 1W / 1M", meaning: "Bar interval. Weekly and monthly are resampled from daily bars at export time; pattern detection stays daily-only.", source: "§38.7" },
      { term: "Indicators", meaning: "Opens the preset catalogue. Every preset was computed when the snapshot was built, so parameters cannot be edited here.", source: "§38.5" },
      { term: "Alert · Compare", meaning: "Disabled — there is no alert engine and no compare series yet. Hover either one for the reason.", source: "§38.19.2" },
    ],
  },
  {
    name: "ON THE CHART", where: "CENTRE", accent: "var(--indigo, #8E97FF)",
    rows: [
      { term: "Shaded box / converging lines", meaning: "A detected pattern, drawn automatically. The label carries its type and confirmation state.", source: "PATTERN RECORD" },
      { term: "Crosshair tooltip", meaning: "O/H/L/C, volume and RSI for the bar under the pointer, mirrored into the chart legend.", source: "SNAPSHOT BARS" },
      { term: "S · -3.2%  /  R · -1.5%", meaning: "A support or resistance band and its distance from the last close. Broken levels drop to a dashed hairline so live levels read first.", source: "DERIVED" },
      { term: "Known", meaning: "The earliest date the detector could have known this pattern. Never earlier than any of its pivots' own confirmation dates.", source: "§38.15" },
      { term: "Nearest: Support ₹2942.00", meaning: "The level closest to the last close, in rupees and in ATR. A fact about distance, not a signal to act on.", source: "§38.15" },
    ],
  },
  {
    name: "LEVELS PANEL", where: "RIGHT", accent: "var(--mint)",
    rows: [
      { term: "₹2890.00 SUPPORT", meaning: "A grouped band and its side. Near-duplicate records within 0.35 ATR of each other are shown as one band.", source: "§38.15" },
      { term: "STRENGTH 4/5", meaning: "The engine's level strength — touches, recency, rejection, volume at the touches and time spent near the level, combined by frozen weights into [0,1] and shown here as fifths. Descriptive, never a probability. Hover for the raw score.", source: "§13.2 · SR_LEVEL_STRENGTH" },
      { term: "n touches", meaning: "How many pivots the detector recorded at this level.", source: "PATTERN PIVOTS" },
      { term: "+₹43.40 · +1.5%", meaning: "Distance from the last close, in rupees and percent.", source: "DERIVED" },
      { term: "HOLDING / BROKEN", meaning: "Whether a close through the level has been confirmed on any record in the band.", source: "PATTERN STATUS" },
    ],
  },
  {
    name: "PANES & LEGEND", where: "CENTRE", accent: "var(--amber)",
    rows: [
      { term: "PRICE / VOLUME / RSI rows", meaning: "Open panes, each with its value at the crosshair. Drag the handle to resize one.", source: "UI" },
      { term: "Collapsed strip", meaning: "A collapsed pane, showing its latest value and a sparkline. One click expands it back to a full pane.", source: "UI" },
      { term: "◡ ⚙ i ✕ on a legend row", meaning: "Hide, settings, provenance and remove for that indicator, without opening a panel.", source: "UI" },
      { term: "1D … All · ADJ · Auto · Log · %", meaning: "Visible-range presets and scale controls, placed next to the time axis they act on.", source: "UI" },
    ],
  },
  {
    name: "PROVENANCE", where: "TOP STRIP", accent: "var(--danger-hex)",
    rows: [
      { term: "SYNTHETIC DEVELOPMENT DATA", meaning: "This snapshot is placeholder data for building the page. No number on the screen may be quoted, reported or acted on.", source: "manifest.fixture" },
      { term: "INTERNAL ONLY", meaning: "Kite-derived prices from a frozen research run. Not for redistribution, and not investment advice.", source: "§2.1" },
    ],
  },
];

export default function FieldGuide({ open, onClose }: FieldGuideProps) {
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return GROUPS;
    return GROUPS
      .map((g) => ({ ...g, rows: g.rows.filter((r) => `${r.term} ${r.meaning} ${r.source}`.toLowerCase().includes(q)) }))
      .filter((g) => g.rows.length > 0);
  }, [query]);

  if (!open) return null;

  return (
    <>
      <div onClick={onClose} data-testid="chart-field-guide-backdrop" style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.42)", zIndex: 70 }} />
      <div
        data-testid="chart-field-guide" role="dialog" aria-modal="true" aria-label="Field guide"
        style={{
          position: "fixed", top: "7vh", left: "50%", transform: "translateX(-50%)", width: "min(760px, 94vw)",
          maxHeight: "80vh", background: "var(--bg-1)", border: "1px solid var(--c-line-strong)", borderRadius: 14,
          boxShadow: "var(--shadow-pop)", zIndex: 71, display: "flex", flexDirection: "column", overflow: "hidden",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 16px", borderBottom: "1px solid var(--c-line)" }}>
          <h3 className="nv-serif" style={{ fontSize: 17, margin: 0 }}>What every field means</h3>
          <span className="nv-mono" style={{ fontSize: 9.5, color: "var(--c-ink-4)", letterSpacing: ".1em" }}>LABEL · MEANING · SOURCE</span>
          <button type="button" onClick={onClose} aria-label="Close" data-testid="chart-field-guide-close" className="rail-ico" style={{ marginLeft: "auto", width: 28, height: 28, borderRadius: 999 }}>✕</button>
        </div>

        <div style={{ padding: "10px 16px 6px" }}>
          <input
            autoFocus value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="Search fields…" aria-label="Search fields" data-testid="chart-field-guide-search"
            style={{ width: "100%", padding: "8px 11px", borderRadius: 9, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--c-ink)", fontSize: 13 }}
          />
          <p style={{ margin: "7px 2px 0", fontSize: 10.5, color: "var(--c-ink-4)", lineHeight: 1.5 }}>
            Covers the fields this screen actually shows. Signals, alerts and paper trading are not built.
          </p>
        </div>

        <div style={{ overflowY: "auto", padding: "4px 16px 16px", flex: 1 }}>
          {groups.length === 0 && (
            <p data-testid="chart-field-guide-empty" style={{ fontSize: 12.5, color: "var(--c-ink-3)", padding: "8px 2px" }}>
              Nothing matches "{query}".
            </p>
          )}
          {groups.map((g) => (
            <section key={g.name} data-testid={`chart-field-guide-group-${g.name.toLowerCase().replace(/[^a-z]+/g, "-")}`} style={{ marginTop: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span aria-hidden="true" style={{ width: 3, height: 13, borderRadius: 2, background: g.accent }} />
                <span className="nv-mono" style={{ fontSize: 9.5, letterSpacing: ".14em", color: "var(--c-ink-2)" }}>{g.name}</span>
                <span className="nv-mono" style={{ marginLeft: "auto", fontSize: 8.5, letterSpacing: ".1em", color: "var(--c-ink-4)" }}>{g.where}</span>
              </div>
              <div style={{ display: "grid", gap: 9 }}>
                {g.rows.map((r) => (
                  <div key={r.term} style={{ display: "grid", gap: 3, paddingBottom: 9, borderBottom: "1px solid var(--c-line)" }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                      <span className="nv-mono" style={{ fontSize: 10.5, letterSpacing: ".04em", color: g.accent }}>{r.term}</span>
                      <span className="nv-mono" style={{ marginLeft: "auto", fontSize: 8.5, letterSpacing: ".1em", color: "var(--c-ink-4)", whiteSpace: "nowrap" }}>{r.source}</span>
                    </div>
                    <span style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--c-ink-2)" }}>{r.meaning}</span>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </>
  );
}
