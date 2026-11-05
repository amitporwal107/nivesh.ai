/**
 * "The day, agent by agent" — the design's lane track (08:00 → 18:30 IST) on the run's real clock steps. A dot marks a
 * lane that produced events in a reached phase of the shown day (one dot per lane and phase: the replay's clock moves by
 * phase, so all of a phase's events share its time). Faint dots in the Orchestrator lane are the phases still scheduled.
 * Clicking the track jumps to the nearest reached phase: the event feed is filtered to it.
 */
import type { CSSProperties } from "react";
import type { ClockEventRow, Tone } from "../../../screens/simulator/model";
import { BANDS, D0, D1, LANES, PHASES, PHASE_INFO, frac, ist, pctOf, plural, secOf, type DayView, type Phase } from "./model";

const DOT: Record<Tone, string> = { mint: "var(--mint)", amber: "var(--amber)", danger: "var(--danger)", indigo: "var(--indigo)", ink: "var(--ink-2)" };
const GLOW: Record<Tone, string> = { mint: "var(--indigo-soft)", amber: "var(--amber-soft)", danger: "var(--danger-soft)", indigo: "var(--indigo-soft)", ink: "var(--indigo-soft)" };

export function DayTrack({ day, clockHere, clockIso, current, selected, onJump }: {
  day: DayView;
  /** The run's clock is on the shown day (draw the cursor). */
  clockHere: boolean;
  clockIso: string | null;
  /** The phase the run's clock is at, when on the shown day (its dots glow). */
  current: Phase | null;
  selected: Phase | null;
  onJump: (p: Phase) => void;
}) {
  const reached = Array.from(day.reached.entries()) as [Phase, ClockEventRow][];
  const now = clockHere ? ist(clockIso) : null;
  const nowSec = now?.sec ?? null;
  const seek = (ev: React.MouseEvent<HTMLDivElement>) => {
    if (!reached.length) return;
    const r = ev.currentTarget.getBoundingClientRect();
    const x0 = r.left + 142;
    const w = r.width - 142;
    const s = D0 + Math.max(0, Math.min(1, (ev.clientX - x0) / w)) * (D1 - D0);
    const best = reached.reduce((a, b) => (Math.abs(secOf(PHASE_INFO[b[0]].at) - s) < Math.abs(secOf(PHASE_INFO[a[0]].at) - s) ? b : a));
    onJump(best[0]);
  };
  const scheduled = PHASES.filter((p) => !day.reached.has(p));
  return (
    <div style={{ overflowX: "auto" }} data-testid="day-track-scroll">
      <div style={{ minWidth: 760, display: "flex", flexDirection: "column", gap: 0 }}>
        <div style={{ display: "grid", gridTemplateColumns: "132px minmax(0,1fr)", gap: 10, alignItems: "end", paddingBottom: 6 }}>
          <span />
          <div style={{ position: "relative", height: 30 }}>
            {BANDS.map((b) => {
              const on = nowSec != null && nowSec >= secOf(b.a) && nowSec < secOf(b.b);
              return (
                <div key={b.t} data-testid="day-band" style={{ position: "absolute", left: pctOf(secOf(b.a)), width: `${((frac(secOf(b.b)) - frac(secOf(b.a))) * 100).toFixed(2)}%`, top: 0, bottom: 0, borderLeft: "1px solid var(--line-2)", padding: "0 5px", display: "flex", flexDirection: "column", justifyContent: "flex-end", overflow: "hidden" }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.06em", color: on ? "var(--ink)" : b.c, whiteSpace: "nowrap" }}>{b.t}</span>
                  <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-4)" }}>{b.a}</span>
                </div>
              );
            })}
          </div>
        </div>
        <div onClick={seek} data-testid="day-track" style={{ position: "relative", cursor: reached.length ? "crosshair" : "default" }}>
          {LANES.map((ln, i) => {
            const dots = day.lanes.filter((d) => d.lane === ln.id);
            return (
              <div key={ln.id} data-testid="day-lane" data-lane={ln.id} style={{ display: "grid", gridTemplateColumns: "132px minmax(0,1fr)", gap: 10, alignItems: "center", height: 30, borderTop: "1px solid var(--line)" }}>
                <span style={{ fontSize: 12, color: ln.phase ? "var(--ink-3)" : "var(--ink-2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{ln.n}</span>
                <div style={{ position: "relative", height: 30, background: i % 2 ? "transparent" : "var(--bg-2)" }}>
                  {ln.note && (
                    <span data-testid="day-lane-note" style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.06em", color: "var(--ink-4)", whiteSpace: "nowrap" }}>{ln.note}</span>
                  )}
                  {dots.map((d) => {
                    const glow = clockHere && current === d.phase;
                    const s: CSSProperties = { position: "absolute", left: pctOf(secOf(PHASE_INFO[d.phase].at)), top: "50%", width: 8, height: 8, margin: "-4px 0 0 -4px", borderRadius: "50%", background: DOT[d.tone], opacity: 1, boxShadow: glow ? `0 0 0 4px ${GLOW[d.tone]}` : "none" };
                    return <span key={d.phase} data-testid="day-dot" data-lane={ln.id} data-phase={d.phase} data-tone={d.tone} title={`${PHASE_INFO[d.phase].at} · ${PHASE_INFO[d.phase].n} · ${plural(d.n, "event")}`} style={s} />;
                  })}
                  {ln.id === "orch" && scheduled.map((p) => (
                    <span key={p} data-testid="day-dot-scheduled" data-phase={p} title={`${PHASE_INFO[p].at} · ${PHASE_INFO[p].n} · scheduled, not yet reached`}
                      style={{ position: "absolute", left: pctOf(secOf(PHASE_INFO[p].at)), top: "50%", width: 8, height: 8, margin: "-4px 0 0 -4px", borderRadius: "50%", background: "var(--indigo)", opacity: 0.35 }} />
                  ))}
                </div>
              </div>
            );
          })}
          {selected && (
            <div data-testid="day-track-selected" style={{ position: "absolute", top: 0, bottom: 0, left: `calc(142px + (100% - 142px) * ${frac(secOf(PHASE_INFO[selected].at)).toFixed(4)})`, borderLeft: "1px dashed var(--indigo-line)", pointerEvents: "none" }} />
          )}
          {nowSec != null && (
            <div data-testid="day-cursor" style={{ position: "absolute", top: 0, bottom: 0, left: `calc(142px + (100% - 142px) * ${frac(nowSec).toFixed(4)})`, borderLeft: "2px solid var(--indigo)", pointerEvents: "none" }}>
              <span className="nv-num" style={{ position: "absolute", top: -2, left: 4, padding: "1px 5px", borderRadius: 5, background: "var(--indigo)", color: "#0A0E1A", fontFamily: "var(--mono)", fontSize: 9.5 }}>{now!.hhmm}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
