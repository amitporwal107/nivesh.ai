/**
 * Simulation studio · Scenario library (docs/autodesk/design/prototype/studio/SimScenarios.dc.html).
 *
 * Phase 1 truth: the desk API cannot run scenarios. SimulationConfig refuses mode SCENARIO with 422 ("SCENARIO
 * simulations are Phase 3 and not available yet"), and there is no scenario catalogue, schedule or injection endpoint.
 * The design's catalogue (ids, severities, PASS / FAIL results, a schedule) is sample content and is not shown. The page
 * keeps the design's structure — header, "Schedule for the next run" on the 09:15 → 15:30 axis, the library by category,
 * the builder — and lists the kinds of shock the PRD plans (./scenarios/planned.ts), labelled as planned for Phase 3.
 * Every control that would schedule or run something is disabled. Nothing is sent.
 */
import { useState, type CSSProperties } from "react";
import { Link, useLocation } from "react-router-dom";
import { useIsMobile } from "../../hooks";
import { PhaseNote } from "../../ui";
import { PLANNED, SESSION_TICKS, tickPct } from "./scenarios/planned";

const mono = (size: number, color = "var(--ink-3)"): CSSProperties => ({ fontFamily: "var(--mono)", fontSize: size, letterSpacing: "0.08em", color });

export default function StudioScenarios() {
  const mobile = useIsMobile();
  const loc = useLocation();
  const sim = new URLSearchParams(loc.search).get("sim");
  const keep = sim ? `?sim=${encodeURIComponent(sim)}` : "";
  const all = PLANNED.flatMap((c) => c.items.map((it) => ({ ...it, cat: c.t })));
  const offsets = PLANNED.map((_, ci) => PLANNED.slice(0, ci).reduce((n, c) => n + c.items.length, 0));
  const [sel, setSel] = useState(0);
  const selIdx = Math.min(sel, all.length - 1);
  const cur = all[selIdx];

  return (
    <div data-testid="studio-scenarios" style={{ display: "flex", flexDirection: "column", gap: 20, fontFamily: "var(--sans)", color: "var(--ink)" }}>
      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <span className="nv-eyebrow">Scenario library</span>
          <span className="nv-pill" data-testid="scen-count-pill">{all.length} planned kinds · {PLANNED.length} categories</span>
          <span className="nv-pill nv-pill-amber" data-testid="scen-sched-pill">Nothing scheduled · Phase 3</span>
        </div>
        <h1 style={{ margin: 0, fontFamily: "var(--display)", fontWeight: 400, fontSize: "clamp(28px,4vw,44px)", lineHeight: 1.06, letterSpacing: "-0.02em", textWrap: "pretty", maxWidth: 900 } as CSSProperties}>
          Each scenario names the shock <em style={{ color: "var(--amber)" }}>and the behaviour it must produce.</em>
        </h1>
        <p data-testid="scen-sub" style={{ margin: 0, fontSize: 14.5, lineHeight: 1.55, color: "var(--ink-3)", maxWidth: 700 }}>
          Scenario runs come in Phase 3. Today the simulator replays past sessions exactly as they happened, and the desk API refuses a scenario
          run. The kinds below are the ones the product requirements plan for the library; none of them can be scheduled or run yet, and nothing
          on this page is sent.
        </p>
      </section>

      <section data-testid="scen-schedule" style={{ display: "flex", flexDirection: "column", gap: 10, padding: "16px 18px", borderRadius: 14, border: "1px solid var(--amber-line)", background: "var(--bg-1)", minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontFamily: "var(--display)", fontSize: 22 }}>Schedule for the next run</span>
          <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>09:15 → 15:30</span>
        </div>
        <div data-testid="scen-axis" style={{ position: "relative", height: 44, margin: "4px 6px" }}>
          <div style={{ position: "absolute", left: 0, right: 0, top: 20, height: 4, borderRadius: 2, background: "var(--bg-3)" }} />
          {SESSION_TICKS.map((t) => (
            <span key={t} data-testid="scen-tick" className="nv-num" style={{ position: "absolute", left: tickPct(t), top: 30, transform: "translateX(-50%)", fontFamily: "var(--mono)", fontSize: 9.5, color: "var(--ink-4)" }}>{t}</span>
          ))}
        </div>
        <div data-testid="scen-schedule-empty" style={{ display: "flex", gap: 12, alignItems: "baseline", padding: "7px 0", borderTop: "1px solid var(--line)", fontSize: 13, color: "var(--ink-3)" }}>
          Nothing is scheduled. A schedule of shocks for a run comes with scenario simulation.
        </div>
        <PhaseNote phase={3} testId="scen-schedule-note">
          Scenario injection and fault simulation are Phase 3 of the desk. Until then a run replays past sessions as they happened, with no shock added.
        </PhaseNote>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: 20, alignItems: "start" }}>
        <div data-testid="scen-library" style={{ display: "flex", flexDirection: "column", gap: 16, gridColumn: mobile ? "1 / -1" : "span 2", minWidth: 0 }}>
          {PLANNED.map((c, ci) => (
            <section key={c.t} data-testid="scen-cat" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <span className="nv-eyebrow">{c.t}</span>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(min(100%,250px),1fr))", gap: 10 }}>
                {c.items.map((it, k) => {
                  const i = offsets[ci] + k;
                  const on = i === selIdx;
                  return (
                    <div key={it.n} role="button" tabIndex={0} aria-pressed={on} data-testid="scen-card" className="ad-hover-line"
                      onClick={() => setSel(i)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(i); } }}
                      style={{ cursor: "pointer", display: "flex", flexDirection: "column", gap: 8, padding: "14px 16px", borderRadius: 14, border: `1px solid ${on ? "var(--amber-line)" : "var(--line)"}`, background: on ? "var(--amber-soft)" : "var(--bg-1)", transition: "all .15s ease", minWidth: 0 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)" }}>{it.src}</span>
                        <span style={{ flex: 1 }} />
                        <span style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.08em", color: "var(--amber)" }}>PHASE 3</span>
                      </div>
                      <span style={{ fontSize: 14.5, fontWeight: 500, lineHeight: 1.3 }}>{it.n}</span>
                      <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--ink-3)" }}>{it.exp}</span>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <span className="nv-pill" style={{ padding: "1px 7px", fontSize: 8.5, color: "var(--ink-2)", borderColor: "var(--line-2)" }}>PLANNED</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>

        <aside data-testid="scen-builder" style={{ position: mobile ? "static" : "sticky", top: 96, display: "flex", flexDirection: "column", gap: 12, padding: "18px 20px", borderRadius: 16, border: "1px solid var(--line-2)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)", minWidth: 0 }}>
          <span className="nv-eyebrow">Builder · Phase 3</span>
          <span data-testid="scen-builder-name" style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.15 }}>{cur.n}</span>
          <span data-testid="scen-builder-exp" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" }}>{cur.exp}</span>
          <span style={{ ...mono(9.5), paddingTop: 4 }}>INJECT AT</span>
          <div data-testid="scen-times" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {SESSION_TICKS.map((t) => (
              <button key={t} type="button" disabled aria-disabled="true" className="nv-num" title="Scenario injection comes in Phase 3"
                style={{ cursor: "not-allowed", opacity: 0.45, padding: "6px 10px", borderRadius: 999, border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", fontFamily: "var(--mono)", fontSize: 11 }}>{t}</button>
            ))}
          </div>
          <span style={{ ...mono(9.5), paddingTop: 4 }}>PARAMETERS</span>
          <span style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--ink-3)" }}>Size, duration and the instruments hit are set with each scenario when scenario runs arrive.</span>
          <span style={{ ...mono(9.5), paddingTop: 4 }}>BEHAVIOUR CHECKED AT THE END</span>
          <span data-testid="scen-builder-check" style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--ink-2)" }}>· {cur.exp}</span>
          <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--ink-3)" }}>Each scenario's pass / fail assertions are written with it in Phase 3.</span>
          <button type="button" data-testid="scen-add" disabled aria-disabled="true" title="The desk API refuses scenario runs until Phase 3"
            style={{ cursor: "not-allowed", opacity: 0.55, marginTop: 4, padding: "11px 16px", borderRadius: 12, border: 0, background: "var(--amber)", color: "#160E02", fontSize: 14, fontWeight: 500 }}>
            Scenario runs come in Phase 3
          </button>
          <span style={{ fontSize: 12.5 }}>
            <Link to={`/studio/new${keep}`} className="ad-link" data-testid="scen-replay-link">Replay a past session instead ›</Link>
          </span>
        </aside>
      </div>
    </div>
  );
}
