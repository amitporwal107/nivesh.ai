/**
 * Calibration panel: when the model flags a stock at X%, does it happen X% of the time?
 * One group per probability band: PREDICTED = dashed outline bar, REALISED = solid bar, on ONE shared y-axis.
 * A band with realised == null (too few resolved names to measure) is never drawn as a zero bar: a zero would
 * read as "it never happened". It keeps its predicted outline, an empty realised slot and a "too few" label.
 * Plain SVG, no charting library. Colours come from --mv-* custom properties; the literals are fallbacks.
 */
import type { MoversCalibration } from "@/services/adapters/movers.adapter";

type Props = { data: MoversCalibration | null; error?: string | null; currentP?: number | null; onRetry?: () => void };
type Band = MoversCalibration["bands"][number];
type Extra = MoversCalibration & { scored_as?: string | null; note?: string | null };

const W = 720, PAD_L = 44, PAD_R = 10, PLOT_T = 14, PLOT_H = 170, LABEL_H = 34;
const PRED = "var(--mv-pred, #4c6ef5)", REAL = "var(--mv-real, #2f9e6e)", INK = "var(--mv-ink, #5b6472)";
const GRID = "var(--mv-grid, rgba(128,128,128,0.25))", CUR = "var(--mv-rule, #e1a21b)";

const REASONS: Record<string, string> = {
  NO_FINAL_RUN_IN_WINDOW: "No finished model run falls inside this date window, so there is nothing to compare against what happened.",
  NO_ESTIMATES_FOR_HEAD: "The model produced no estimates for this measure in the window.",
  NO_RESOLVED_OUTCOMES: "No flagged name has finished its horizon yet, so there are no outcomes to score.",
};
const pc = (v: number | null | undefined, d = 1) => (v == null ? "n/a" : `${(v * 100).toFixed(d)}%`);
const label = (b: Band) => (b.hi == null ? `${pc(b.lo, 0)}+` : `${pc(b.lo, 0)}-${pc(b.hi, 0)}`);
const inBand = (b: Band, p: number) => p >= b.lo && (b.hi == null || p < b.hi);

function headline(r: number | null): string {
  if (r == null) return "Over-prediction could not be computed: no band has enough resolved names to measure what actually happened.";
  const x = r.toFixed(2);
  if (r > 1.05) return `Predicts ${x}x what actually happened: it over-states how often this occurs.`;
  if (r < 0.95) return `Predicts ${x}x what actually happened: it under-states how often this occurs.`;
  return `Predicts ${x}x what actually happened: close to calibrated.`;
}

export function MoversCalibration({ data, error, currentP, onRetry }: Props) {
  const retry = onRetry ? <button type="button" className="mv-btn mv-cal-retry" onClick={onRetry}>Retry</button> : null;
  if (error) return <div className="mv-cal mv-cal-error" role="alert" data-testid="mv-cal-error">Calibration could not be loaded: {error} {retry}</div>;
  if (!data) return <div className="mv-cal mv-cal-loading" aria-busy="true" data-testid="mv-cal-loading">Loading calibration...</div>;

  const d = data as Extra;
  const foot = (
    <p className="mv-cal-foot mv-muted" data-testid="mv-cal-foot">
      {d.population} names in the population; {d.pending_excluded} still inside their horizon are excluded from the bands, because scoring them
      as "did not move" would flatter the model.
      {d.scored_as ? <> Scored as: {d.scored_as}.</> : null}{d.note ? <> {d.note}</> : null}
    </p>
  );

  if (!d.available) {
    const why = (d.reason && REASONS[d.reason]) || (d.reason ? `Unavailable (${d.reason}).` : "Calibration is unavailable for this window.");
    return (
      <div className="mv-cal mv-cal-unavailable" data-testid="mv-cal-unavailable">
        <p>{why}</p>
        <p className="mv-muted">Population in window: {d.population}. {d.pending_excluded} pending.</p>
        {retry}
      </div>
    );
  }

  const bands = d.bands;
  const max = Math.max(0.0001, ...bands.flatMap((b) => [b.predicted, b.realised ?? 0]));
  const plotW = W - PAD_L - PAD_R, slot = plotW / Math.max(1, bands.length), bw = Math.min(26, slot * 0.36);
  const y = (v: number) => PLOT_T + PLOT_H - (v / max) * PLOT_H;
  const cur = currentP == null ? null : bands.find((b) => inBand(b, currentP)) ?? null;
  const measured = bands.filter((b) => b.realised != null).length;
  const aria = `Predicted versus realised frequency across ${bands.length} bands; ${measured} have enough names to measure. ${headline(d.over_prediction)}`;
  const ticks = [0, 0.5, 1].map((f) => f * max);

  return (
    <div className="mv-cal" data-testid="mv-cal">
      <p className="mv-cal-over" data-testid="mv-cal-over">{headline(d.over_prediction)}</p>
      {cur ? <p className="mv-cal-curlabel">The selected stock ({pc(currentP)}) is in the {label(cur)} band (outlined in the chart).</p> : null}
      <svg viewBox={`0 0 ${W} ${PLOT_T + PLOT_H + LABEL_H}`} className="mv-cal-svg" role="img" aria-label={aria} style={{ width: "100%", height: "auto" }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD_L} x2={W - PAD_R} y1={y(t)} y2={y(t)} stroke={GRID} />
            <text x={PAD_L - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill={INK}>{pc(t, 0)}</text>
          </g>
        ))}
        {bands.map((b, i) => {
          const cx = PAD_L + (i + 0.5) * slot, px0 = cx - bw - 1, rx0 = cx + 1, isCur = cur === b;
          return (
            <g key={b.lo} data-testid={`mv-cal-band-${b.lo}`}>
              <title>{`${label(b)}: n=${b.n}, predicted ${pc(b.predicted)}, realised ${b.realised == null ? "too few to measure" : pc(b.realised)}`}</title>
              {isCur ? <rect data-testid="mv-cal-current" x={cx - slot / 2 + 1} y={PLOT_T - 6} width={slot - 2} height={PLOT_H + LABEL_H + 6}
                fill="none" stroke={CUR} strokeWidth={2} rx={3} /> : null}
              <rect x={px0} y={y(b.predicted)} width={bw} height={Math.max(1, PLOT_T + PLOT_H - y(b.predicted))}
                fill="none" stroke={PRED} strokeWidth={1.5} strokeDasharray="4 3" />
              {b.realised == null ? (
                <text x={rx0 + bw / 2} y={PLOT_T + PLOT_H - 4} textAnchor="middle" fontSize="9" fill={INK}
                  transform={`rotate(-90 ${rx0 + bw / 2} ${PLOT_T + PLOT_H - 4})`}>too few</text>
              ) : (
                <rect x={rx0} y={y(b.realised)} width={bw} height={Math.max(1, PLOT_T + PLOT_H - y(b.realised))} fill={REAL} />
              )}
              <text x={cx} y={PLOT_T + PLOT_H + 14} textAnchor="middle" fontSize="11" fill={INK}>{label(b)}</text>
              <text x={cx} y={PLOT_T + PLOT_H + 28} textAnchor="middle" fontSize="10" fill={INK}>{`n=${b.n}`}</text>
            </g>
          );
        })}
        <line x1={PAD_L} x2={W - PAD_R} y1={y(0)} y2={y(0)} stroke={INK} />
      </svg>
      <p className="mv-cal-legend mv-muted">
        <span className="mv-cal-key mv-cal-key-pred" style={{ borderBottom: `2px dashed ${PRED}` }}>dashed outline = predicted</span>{" "}
        <span className="mv-cal-key mv-cal-key-real" style={{ borderBottom: `4px solid ${REAL}` }}>solid = realised</span>{" "}
        "too few" = not enough resolved names to measure (not zero).
      </p>
      <table className="mv-cal-table" data-testid="mv-cal-table" style={{ fontSize: 12, width: "100%" }}>
        <caption className="mv-sr-only" style={{ textAlign: "left" }}>Calibration by predicted band</caption>
        <thead><tr><th scope="col">Band</th><th scope="col">n</th><th scope="col">Predicted</th><th scope="col">Realised</th></tr></thead>
        <tbody>
          {bands.map((b) => (
            <tr key={b.lo}>
              <th scope="row">{label(b)}{cur === b ? " (selected stock)" : ""}</th><td>{b.n}</td><td>{pc(b.predicted)}</td>
              <td>{b.realised == null ? "too few to measure" : pc(b.realised)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {foot}
    </div>
  );
}
