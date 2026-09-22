/**
 * The in-chart legend (§38.4, §38.19.2 1A design): symbol/timeframe/exchange/status, O H L C + change vs the
 * previous close, volume, and one row per visible indicator with hide/settings/remove/provenance controls.
 *
 * Crosshair resolution ("the bar under the crosshair... off the chart, it shows the last bar", §38.4) is a
 * ChartCanvas/lightweight-charts concern (W1b): this component only renders whichever `bar` it is given. Likewise
 * `previousClose` is passed in rather than derived, since the caller already has the full bar series and index
 * arithmetic belongs with it, not with a presentational legend.
 */
import { useState } from "react";
import { price as fmtPrice, vol as fmtVol, txt, DASH, type Bar } from "../contract";

export interface LegendIndicatorRow {
  id: string;
  /** e.g. "RSI" */
  name: string;
  /** e.g. "14 close" — combined with `name` as "RSI 14 close" (§38.4: "its name and parameters"). */
  params?: string;
  /** One or more output values at the crosshair bar (e.g. MACD: macd/signal/hist). */
  values: Array<{ label?: string; value: string }>;
  /** Swatch colour matching the series' plotted colour, for visual association with the chart. */
  color?: string;
}

export interface LegendProps {
  symbol: string;
  /** Display label, e.g. "1D". */
  timeframe: string;
  exchange: string;
  /** The existing status chip (PIT_UNVERIFIED etc.) — rendered as-is; Legend does not know its internals. */
  statusBadge?: React.ReactNode;

  /** The bar to show O/H/L/C/volume/change for — the crosshair bar, or the last bar when the pointer is off the
   *  chart or nothing has been hovered yet. Null renders dashes. */
  bar: Bar | null;
  /** The immediately preceding bar's close, for the change calculation — null when `bar` is the series' first bar
   *  (no previous close to compare against) or the series itself is unavailable. */
  previousClose: number | null;
  /** True when `bar` is a not-yet-complete period (current week/month, or an intraday bar) — §38.4: "visibly
   *  marked and never feeds confirmation". */
  incomplete?: boolean;

  indicators: LegendIndicatorRow[];
  onHideIndicator: (id: string) => void;
  onOpenIndicatorSettings: (id: string) => void;
  onRemoveIndicator: (id: string) => void;
  onOpenIndicatorProvenance: (id: string) => void;

  collapsed: boolean;
  onToggleCollapsed: () => void;

  className?: string;
}

export default function Legend(props: LegendProps) {
  const {
    symbol, timeframe, exchange, statusBadge, bar, previousClose, incomplete,
    indicators, onHideIndicator, onOpenIndicatorSettings, onRemoveIndicator, onOpenIndicatorProvenance,
    collapsed, onToggleCollapsed, className,
  } = props;

  const close = bar ? bar[4] : null;
  const change = close != null && previousClose != null ? close - previousClose : null;
  const changePct = change != null && previousClose ? (change / previousClose) * 100 : null;
  const up = change != null ? change >= 0 : null;
  const changeColor = up == null ? "var(--c-ink-3)" : up ? "var(--mint)" : "var(--danger-hex)";

  return (
    <div
      data-testid="chart-legend"
      className={className}
      style={{
        position: "absolute", top: 8, left: 8, zIndex: 5, maxWidth: "calc(100% - 16px)",
        background: "var(--bg-glass)", border: "1px solid var(--c-line)", borderRadius: 10,
        padding: collapsed ? "4px 8px" : "8px 10px", backdropFilter: "blur(6px)", fontSize: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span className="nv-mono" data-testid="chart-legend-symbol" style={{ fontWeight: 700, color: "var(--c-ink)" }}>{symbol || DASH}</span>
        <span className="nv-mono" data-testid="chart-legend-timeframe" style={{ color: "var(--c-ink-3)", fontSize: 10.5 }}>{timeframe}</span>
        <span className="nv-mono" data-testid="chart-legend-exchange" style={{ color: "var(--c-ink-3)", fontSize: 10.5 }}>{exchange || DASH}</span>
        {statusBadge}
        {incomplete && (
          <span data-testid="chart-legend-incomplete" className="nv-mono" title="This bar is not complete yet" style={{ fontSize: 9.5, color: "var(--amber)", border: "1px solid var(--amber-line)", borderRadius: 999, padding: "1px 6px" }}>
            forming
          </span>
        )}
        <button
          type="button" data-testid="chart-legend-collapse" onClick={onToggleCollapsed}
          aria-label={collapsed ? "Expand legend" : "Collapse legend"} aria-pressed={collapsed}
          title={collapsed ? "Expand legend" : "Collapse legend"} className="rail-ico"
          style={{ width: 20, height: 20, borderRadius: 999, marginLeft: "auto", fontSize: 10 }}
        >
          {collapsed ? "▾" : "▴"}
        </button>
      </div>

      {!collapsed && (
        <>
          <div data-testid="chart-legend-ohlc" style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 6, fontFamily: "var(--mono)", fontSize: 11.5 }}>
            <OhlcField label="O" value={bar ? fmtPrice(bar[1]) : DASH} color={changeColor} />
            <OhlcField label="H" value={bar ? fmtPrice(bar[2]) : DASH} color={changeColor} />
            <OhlcField label="L" value={bar ? fmtPrice(bar[3]) : DASH} color={changeColor} />
            <OhlcField label="C" value={bar ? fmtPrice(bar[4]) : DASH} color={changeColor} />
            <span data-testid="chart-legend-change" style={{ color: changeColor }}>
              {change != null ? `${change >= 0 ? "+" : ""}${fmtPrice(change)}` : DASH}
              {" "}
              {changePct != null ? `(${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%)` : ""}
            </span>
          </div>
          <div data-testid="chart-legend-volume" style={{ marginTop: 3, fontFamily: "var(--mono)", fontSize: 11, color: "var(--c-ink-3)" }}>
            Vol {bar ? fmtVol(bar[5]) : DASH}
          </div>

          {indicators.length > 0 && (
            <div data-testid="chart-legend-indicators" style={{ marginTop: 6, display: "grid", gap: 2, borderTop: "1px solid var(--c-line)", paddingTop: 6 }}>
              {indicators.map((ind) => (
                <LegendIndicatorRowView
                  key={ind.id} row={ind}
                  onHide={() => onHideIndicator(ind.id)} onSettings={() => onOpenIndicatorSettings(ind.id)}
                  onRemove={() => onRemoveIndicator(ind.id)} onProvenance={() => onOpenIndicatorProvenance(ind.id)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function OhlcField({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <span>
      <span style={{ color: "var(--c-ink-4)" }}>{label} </span>
      <span style={{ color }}>{value}</span>
    </span>
  );
}

function LegendIndicatorRowView({ row, onHide, onSettings, onRemove, onProvenance }: {
  row: LegendIndicatorRow; onHide: () => void; onSettings: () => void; onRemove: () => void; onProvenance: () => void;
}) {
  const [hover, setHover] = useState(false);
  return (
    <div
      data-testid={`chart-legend-indicator-${row.id}`}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ display: "flex", alignItems: "center", gap: 6, fontFamily: "var(--mono)", fontSize: 11 }}
    >
      {row.color && <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2, background: row.color, flex: "none" }} />}
      <span style={{ color: "var(--c-ink-2)", whiteSpace: "nowrap" }}>
        {row.name}{row.params ? ` ${row.params}` : ""}
      </span>
      <span style={{ color: "var(--c-ink-3)", display: "flex", gap: 8 }}>
        {row.values.map((v, i) => (
          <span key={i}>{v.label ? `${v.label} ` : ""}{txt(v.value)}</span>
        ))}
      </span>
      {hover && (
        <span style={{ display: "flex", gap: 3, marginLeft: "auto" }}>
          <IndicatorIconButton testId={`chart-legend-indicator-${row.id}-hide`} label={`Hide ${row.name}`} icon="◡" onClick={onHide} />
          <IndicatorIconButton testId={`chart-legend-indicator-${row.id}-settings`} label={`${row.name} settings`} icon="⚙" onClick={onSettings} />
          <IndicatorIconButton testId={`chart-legend-indicator-${row.id}-provenance`} label={`${row.name} provenance`} icon="i" onClick={onProvenance} />
          <IndicatorIconButton testId={`chart-legend-indicator-${row.id}-remove`} label={`Remove ${row.name}`} icon="✕" onClick={onRemove} />
        </span>
      )}
    </div>
  );
}

function IndicatorIconButton({ testId, label, icon, onClick }: { testId: string; label: string; icon: string; onClick: () => void }) {
  return (
    <button
      type="button" data-testid={testId} aria-label={label} title={label} onClick={onClick}
      className="rail-ico" style={{ width: 16, height: 16, borderRadius: 4, fontSize: 9 }}
    >
      {icon}
    </button>
  );
}
