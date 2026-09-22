/**
 * §20.3 pattern details card + rules (each opening provenance) + event timeline, opened on selecting a pattern
 * (§38.15 "the details card opens with its §20.3 fields, rules and event timeline"). Required fields per §20.3:
 * pattern_type, direction, status, formation_start, formation_end, support, resistance, breakout_level,
 * invalidation_level, ATR, relative_volume, market_alignment, sector_alignment, point_in_time_validated,
 * pattern_version. `status` is shown as the raw §11 state name (e.g. "PRICE_CONFIRMED"), never a research label
 * (§38.2 "Show the §11 status names, not research states").
 *
 * ATR / relative_volume: the snapshot carries no per-pattern-date indicator value, so both use the same "last bar"
 * convention as the nearest-level readout and the S/R grouping tolerance (contract.ts `lastIndicatorValue`) —
 * documented here and in the test report rather than silently implying a point-in-time-at-formation figure.
 * pattern_version: no dedicated field exists; the run's `engine_version` (research/charting/config.py) is shown,
 * since that is what actually versions the detector that produced this record.
 */
import { txt, num, price as fmtPrice, type Pattern } from "./contract";

interface Props {
  pattern: Pattern;
  atr14: number | null;
  relativeVolume: number | null;
  pitStatus: string | null;
  engineVersion: string | null;
  overlapCount: number;
  overlapIndex: number;
  onPrev: () => void;
  onNext: () => void;
  onOpenRule: (ruleId: string) => void;
  onClose: () => void;
}

export default function PatternDetails({ pattern: p, atr14, relativeVolume, pitStatus, engineVersion, overlapCount, overlapIndex, onPrev, onNext, onOpenRule, onClose }: Props) {
  return (
    <div data-testid="chart-pattern-details" style={{ marginTop: 12, borderTop: "1px solid var(--c-line)", paddingTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <p className="nv-eyebrow" style={{ margin: 0, flex: 1 }}>{p.pattern_type} · details</p>
        {overlapCount > 1 && (
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <button type="button" data-testid="chart-pattern-prev" className="rail-ico" style={{ width: 20, height: 20, borderRadius: 999, fontSize: 11 }} onClick={onPrev} aria-label="Previous overlapping pattern">‹</button>
            <span className="nv-mono" style={{ fontSize: 10, color: "var(--c-ink-4)" }}>{overlapIndex + 1}/{overlapCount}</span>
            <button type="button" data-testid="chart-pattern-next" className="rail-ico" style={{ width: 20, height: 20, borderRadius: 999, fontSize: 11 }} onClick={onNext} aria-label="Next overlapping pattern">›</button>
          </span>
        )}
        <button type="button" data-testid="chart-pattern-details-close" onClick={onClose} className="rail-ico" style={{ width: 20, height: 20, borderRadius: 999 }} aria-label="Clear selection">✕</button>
      </div>

      <dl data-testid="chart-pattern-fields" style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 10px", margin: "0 0 12px", fontSize: 12 }}>
        <Field label="pattern_type" value={p.pattern_type} />
        <Field label="direction" value={p.direction} />
        <Field label="status" value={p.status} />
        <Field label="formation_start" value={p.formation_start} />
        <Field label="formation_end" value={p.formation_end} />
        <Field label="support" value={fmtPrice(p.levels?.support)} />
        <Field label="resistance" value={fmtPrice(p.levels?.resistance)} />
        <Field label="breakout_level" value={fmtPrice(p.levels?.breakout_level)} />
        <Field label="invalidation_level" value={fmtPrice(p.levels?.invalidation_level)} />
        <Field label="ATR" value={num(atr14)} />
        <Field label="relative_volume" value={num(relativeVolume)} />
        <Field label="market_alignment" value={txt(p.components?.market)} />
        <Field label="sector_alignment" value={txt(p.components?.sector)} />
        <Field label="point_in_time_validated" value={txt(pitStatus)} />
        <Field label="pattern_version" value={txt(engineVersion)} />
      </dl>

      <p className="nv-eyebrow" style={{ margin: "0 0 8px" }}>Rules</p>
      <ul style={{ listStyle: "none", margin: "0 0 12px", padding: 0, display: "grid", gap: 4 }}>
        {(p.rules ?? []).map((r) => (
          <li key={r.rule_id} data-testid={`chart-pattern-rule-${r.rule_id}`}>
            <button
              type="button" onClick={() => onOpenRule(r.rule_id)}
              style={{ display: "flex", justifyContent: "space-between", width: "100%", background: "none", border: 0, cursor: "pointer", padding: "3px 0", fontSize: 12, color: "var(--c-ink-2)" }}
            >
              <span>{r.rule_id}</span>
              <span className={`nv-mono ${r.result === "PASS" ? "sig-good" : r.result === "FAIL" ? "sig-risk" : "sig-info"}`}>{r.result}</span>
            </button>
          </li>
        ))}
        {(!p.rules || p.rules.length === 0) && <li style={{ fontSize: 12, color: "var(--c-ink-4)" }}>No rules recorded.</li>}
      </ul>

      <p className="nv-eyebrow" style={{ margin: "0 0 8px" }}>Event timeline</p>
      {(!p.events || p.events.length === 0) ? (
        <p data-testid="chart-pattern-events-empty" style={{ margin: "0 0 12px", fontSize: 11.5, color: "var(--c-ink-4)" }}>No events recorded.</p>
      ) : (
        <ul data-testid="chart-pattern-events" style={{ listStyle: "none", margin: "0 0 12px", padding: 0, display: "grid", gap: 3 }}>
          {[...p.events].sort((a, b) => a.date.localeCompare(b.date)).map((e, i) => (
            <li key={`${e.date}-${e.event_type}-${i}`} data-testid="chart-pattern-event-row" style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: "var(--c-ink-2)" }}>
              <span className="nv-mono">{e.date}</span>
              <span>{e.event_type}{e.rule_id ? ` · ${e.rule_id}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="nv-mono" style={{ color: "var(--c-ink-4)", fontSize: 10 }}>{label}</dt>
      <dd style={{ margin: 0, color: "var(--c-ink)", wordBreak: "break-word" }}>{value}</dd>
    </>
  );
}
