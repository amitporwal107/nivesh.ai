/**
 * The indicators dialog (§38.5): a searchable list of the controlled preset catalogue, grouped as
 * trend / momentum / volatility / volume (§8.1–§8.4).
 *
 * D-3 (2026-09-22): users pick from the catalogue and cannot enter parameters. Every preset was
 * precomputed at export, so adding one here only ever switches on a series the snapshot already
 * carries — this dialog never asks the backend to calculate anything, which is what keeps the Sim
 * Lab rule intact.
 *
 * The same indicator can be added more than once with different presets (SMA 20 and SMA 200), so the
 * list is keyed by preset, not by indicator.
 */
import { useMemo, useState } from "react";
import {
  catalogueEntries, matchesIndicatorSearch, txt,
  type CatalogueIndicator, type CataloguePreset, type IndicatorCatalogue, type Result,
} from "../contract";

export interface IndicatorDialogProps {
  open: boolean;
  onClose: () => void;
  /** null while loading; a non-ok Result renders the reason (§38.5 "the dialog shows the reason"). */
  catalogue: Result<IndicatorCatalogue> | null;
  /** Series ids currently on the chart, so a preset already added reads as added. */
  activeSeriesIds: string[];
  /** seriesId -> how many rows this symbol actually carries for it. A preset the snapshot does not
   *  carry at all, or carries with no rows yet, is offered disabled with the reason — clicking it
   *  would otherwise appear to do nothing, which is the worst of the three outcomes. */
  availableSeries: Record<string, number>;
  onToggle: (seriesId: string) => void;
  /** Opens that series' provenance drawer — the same one the sidebar's info button opens. */
  onShowProvenance: (seriesId: string) => void;
}

const CATEGORY_LABEL: Record<string, string> = {
  trend: "Trend", momentum: "Momentum", volatility: "Volatility", volume: "Volume",
};

export default function IndicatorDialog(props: IndicatorDialogProps) {
  const { open, onClose, catalogue, activeSeriesIds, availableSeries, onToggle, onShowProvenance } = props;
  const [query, setQuery] = useState("");

  const data = catalogue?.kind === "ok" ? catalogue.data : null;
  const entries = useMemo(() => catalogueEntries(data), [data]);
  const matching = useMemo(
    () => entries.filter((e) => matchesIndicatorSearch(e, query)),
    [entries, query],
  );

  const grouped = useMemo(() => {
    const order = data?.categories ?? [];
    const out: Array<{ category: string; items: typeof matching }> = [];
    for (const category of order) {
      const items = matching.filter((e) => e.indicator.category === category);
      if (items.length) out.push({ category, items });
    }
    // Anything whose category is not in the catalogue's own list still shows, rather than vanishing.
    const known = new Set(order);
    const rest = matching.filter((e) => !known.has(e.indicator.category));
    if (rest.length) out.push({ category: "other", items: rest });
    return out;
  }, [matching, data]);

  if (!open) return null;

  return (
    <>
      <div onClick={onClose} data-testid="chart-indicator-dialog-backdrop" style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.42)", zIndex: 70 }} />
      <div
        data-testid="chart-indicator-dialog" role="dialog" aria-modal="true" aria-label="Indicators"
        style={{
          position: "fixed", top: "8vh", left: "50%", transform: "translateX(-50%)", width: "min(560px, 94vw)",
          maxHeight: "78vh", background: "var(--bg-1)", border: "1px solid var(--c-line-strong)", borderRadius: 14,
          boxShadow: "var(--shadow-pop)", zIndex: 71, display: "flex", flexDirection: "column", overflow: "hidden",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 16px", borderBottom: "1px solid var(--c-line)" }}>
          <h3 className="nv-serif" style={{ fontSize: 17, margin: 0, flex: 1 }}>Indicators</h3>
          {data && (
            <span className="nv-mono" data-testid="chart-indicator-dialog-version" title={`Catalogue ${data.version} · ${data.hash}`} style={{ fontSize: 9.5, color: "var(--c-ink-4)" }}>
              CATALOGUE {data.version}
            </span>
          )}
          <button type="button" onClick={onClose} aria-label="Close" data-testid="chart-indicator-dialog-close" className="rail-ico" style={{ width: 28, height: 28, borderRadius: 999 }}>✕</button>
        </div>

        <div style={{ padding: "10px 16px 6px" }}>
          <input
            autoFocus value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="Search indicators…" aria-label="Search indicators" data-testid="chart-indicator-search"
            style={{ width: "100%", padding: "8px 11px", borderRadius: 9, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--c-ink)", fontSize: 13 }}
          />
          <p style={{ margin: "7px 2px 0", fontSize: 10.5, color: "var(--c-ink-4)", lineHeight: 1.5 }}>
            Fixed parameter sets, computed with the snapshot. Parameters cannot be edited here.
          </p>
        </div>

        <div style={{ overflowY: "auto", padding: "4px 10px 12px", flex: 1 }}>
          {catalogue === null && <p data-testid="chart-indicator-dialog-loading" aria-busy="true" style={{ fontSize: 12.5, color: "var(--c-ink-3)", padding: "8px 6px" }}>Loading the catalogue…</p>}

          {catalogue && catalogue.kind !== "ok" && (
            <p role="alert" data-testid="chart-indicator-dialog-error" style={{ fontSize: 12.5, color: "var(--c-ink-2)", padding: "8px 6px", lineHeight: 1.55 }}>
              The indicator catalogue could not be loaded
              {catalogue.kind === "error" ? ` (${catalogue.message})` : catalogue.kind === "unavailable" ? " (the snapshot does not carry one)" : ""}.
            </p>
          )}

          {data && matching.length === 0 && (
            <p data-testid="chart-indicator-dialog-empty" style={{ fontSize: 12.5, color: "var(--c-ink-3)", padding: "8px 6px" }}>
              Nothing matches "{query}".
            </p>
          )}

          {grouped.map(({ category, items }) => (
            <section key={category} data-testid={`chart-indicator-group-${category}`} style={{ marginTop: 8 }}>
              <p className="nv-eyebrow" style={{ margin: "0 0 4px 6px" }}>{CATEGORY_LABEL[category] ?? category}</p>
              <div style={{ display: "grid", gap: 2 }}>
                {items.map(({ indicator, preset }) => (
                  <PresetRow
                    key={preset.preset_id}
                    indicator={indicator}
                    preset={preset}
                    active={activeSeriesIds.includes(preset.series_id)}
                    unavailable={unavailableReason(preset.series_id, availableSeries)}
                    onToggle={() => onToggle(preset.series_id)}
                    onShowProvenance={() => onShowProvenance(preset.series_id)}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </>
  );
}

/** Why a catalogued preset cannot be drawn on this symbol right now, or null when it can. */
function unavailableReason(seriesId: string, available: Record<string, number>): string | null {
  if (!(seriesId in available)) return "not in this snapshot";
  if (available[seriesId] === 0) return "needs more history";
  return null;
}

function PresetRow({ indicator, preset, active, unavailable, onToggle, onShowProvenance }: {
  indicator: CatalogueIndicator; preset: CataloguePreset; active: boolean; unavailable: string | null;
  onToggle: () => void; onShowProvenance: () => void;
}) {
  const params = Object.entries((preset.parameters ?? {}) as Record<string, unknown>)
    .map(([k, v]) => `${k} ${txt(v)}`).join(" · ");
  return (
    <div
      data-testid={`chart-indicator-preset-${preset.preset_id}`}
      style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 8px", borderRadius: 9, background: active ? "var(--bg-2)" : "transparent" }}
    >
      <button
        type="button" onClick={onToggle} aria-pressed={active}
        disabled={!!unavailable} aria-disabled={!!unavailable || undefined}
        data-testid={`chart-indicator-add-${preset.preset_id}`}
        aria-label={unavailable ? `${preset.name} — unavailable, ${unavailable}` : `${active ? "Remove" : "Add"} ${preset.name}`}
        title={unavailable ? `${preset.name} — ${unavailable}` : active ? `Remove ${preset.name} from the chart` : `Add ${preset.name} to the chart`}
        style={{
          flex: 1, minWidth: 0, textAlign: "left", background: "none", border: 0, padding: 0, display: "grid", gap: 1,
          cursor: unavailable ? "not-allowed" : "pointer", opacity: unavailable ? 0.5 : 1,
        }}
      >
        <span style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span style={{ fontSize: 13, color: "var(--c-ink)" }}>{preset.name}</span>
          <span className="nv-mono" style={{ fontSize: 9.5, color: "var(--c-ink-4)" }}>
            {preset.pane === "price" ? "OVERLAY" : "OWN PANE"}
          </span>
          {active && !unavailable && <span className="nv-mono" data-testid={`chart-indicator-added-${preset.preset_id}`} style={{ fontSize: 9.5, color: "var(--mint)" }}>ADDED</span>}
          {unavailable && <span className="nv-mono" data-testid={`chart-indicator-unavailable-${preset.preset_id}`} style={{ fontSize: 9.5, color: "var(--amber)" }}>{unavailable.toUpperCase()}</span>}
        </span>
        <span className="nv-mono" style={{ fontSize: 10.5, color: "var(--c-ink-3)" }}>
          {indicator.name}{params ? ` · ${params}` : ""}
        </span>
      </button>
      <button
        type="button" onClick={onShowProvenance} className="rail-ico"
        data-testid={`chart-indicator-preset-info-${preset.preset_id}`}
        aria-label={`${preset.name} provenance`} title={`Calculation version ${indicator.calculation_version}`}
        style={{ width: 22, height: 22, borderRadius: 999, fontSize: 10, flex: "none" }}
      >
        i
      </button>
    </div>
  );
}
