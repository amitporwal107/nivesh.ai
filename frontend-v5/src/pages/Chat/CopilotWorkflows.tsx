/**
 * CopilotWorkflows — the copilot chat landing.
 *
 * Replaces the old conversational onboarding. Two modes:
 *   • default    → a persona-aware LIST of workflows (investor 10 / advisor 9)
 *   • guided tour → a Next/Back stepper that opens the full workflow tiles one
 *                   at a time (ASK → ANALYZE → DECIDE → ACT).
 *
 * Persona comes from the caller (workspace_type === "ADVISORY"). Clicking a
 * list row or a tile's "Run" button launches that workflow on the user's real
 * portfolio via onLaunch(prompt) → the page's submitMessage. Tiles show what the
 * workflow does (honest descriptions, not fabricated portfolio numbers); the
 * answer that streams back is live. Rendered as a scoped `.copilot-tour` dark
 * island so the tour styling resolves without leaking into the app.
 */
import { useState, useEffect, useRef } from "react";
import { workflowsFor, type Workflow } from "./workflowCatalog";
import "@/pages/Copilot/copilot.css";

const STAGE_ACCENT: Record<string, string> = {
  ASK: "var(--mint)", ANALYZE: "var(--indigo-hex)", DECIDE: "var(--amber)", ACT: "var(--mint)",
};

function Tile({ wf, onLaunch }: { wf: Workflow; onLaunch: (p: string) => void }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        <span className="nv-mono" style={{ fontSize: 13, color: "var(--mint)" }}>{wf.n}</span>
        <span className="nv-serif" style={{ fontSize: 22 }}>{wf.title}</span>
        <span className="nv-body" style={{ color: "rgb(var(--ink-3))", fontSize: 13 }}>{wf.sub}</span>
      </div>
      {/* Responsive grid — the 4 stages wrap to fit the chat column (the tour's
          fixed 4-wide filmstrip overflows it), so ASK→ANALYZE→DECIDE→ACT are all
          visible without a sideways scroll. */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 12 }}>
        {wf.stages.map((st, i) => (
          <div key={st.label} className="nv-card" style={{ padding: 14, minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span className="nv-mono" style={{ fontSize: 10, letterSpacing: ".12em", color: STAGE_ACCENT[st.label] }}>{st.label}</span>
              <div className="ct-dots">{[0, 1, 2, 3].map((d) => (<span key={d} className={"ct-d4" + (d <= i ? " on" : "")} />))}</div>
            </div>
            <div className="ct-syn" style={{ fontSize: 15 }}>{st.text}</div>
          </div>
        ))}
      </div>
      <button
        onClick={() => onLaunch(wf.prompt)}
        className="nv-btn nv-btn-primary"
        style={{ marginTop: 16, padding: "10px 18px", fontSize: 13, cursor: "pointer", border: "none" }}
      >
        Run this on my portfolio →
      </button>
    </div>
  );
}

export default function CopilotWorkflows({
  isAdvisor = false,
  onLaunch,
}: {
  isAdvisor?: boolean;
  onLaunch: (prompt: string) => void;
}) {
  const workflows = workflowsFor(isAdvisor);
  const [tourOpen, setTourOpen] = useState(false);
  const [step, setStep] = useState(0);
  const headingRef = useRef<HTMLDivElement>(null);

  // Move focus to the active tile heading on step change (a11y).
  useEffect(() => {
    if (tourOpen) headingRef.current?.focus();
  }, [tourOpen, step]);

  const openTour = () => { setStep(0); setTourOpen(true); };
  const prev = () => setStep((s) => Math.max(0, s - 1));
  const next = () => setStep((s) => Math.min(workflows.length - 1, s + 1));

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowLeft") { e.preventDefault(); prev(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); next(); }
    else if (e.key === "Escape") { e.preventDefault(); setTourOpen(false); }
  };

  return (
    <div
      className="copilot-tour"
      data-testid="copilot-workflows"
      data-role={isAdvisor ? "advisor" : "investor"}
      style={{ minHeight: 0, borderRadius: 18, border: "1px solid var(--line-2)", padding: "clamp(16px,3vw,26px)", marginTop: 24, overflowX: "clip" }}
    >
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="nv-eyebrow">{isAdvisor ? "ADVISOR · MFD · YOUR BOOK" : "INVESTOR · YOUR PORTFOLIO"}</div>
          <div className="nv-serif" style={{ fontSize: 24, marginTop: 4 }}>
            {isAdvisor ? "Nine jobs across your book" : "Ten jobs on your portfolio"}
          </div>
        </div>
        {tourOpen ? (
          <button data-testid="tour-close" onClick={() => setTourOpen(false)} className="nv-btn" style={{ padding: "8px 14px", fontSize: 12, cursor: "pointer" }}>
            ✕ Close tour
          </button>
        ) : (
          <button data-testid="guided-tour" onClick={openTour} className="nv-btn nv-btn-primary" style={{ padding: "10px 16px", fontSize: 13, cursor: "pointer", border: "none" }}>
            ▶ Guided tour
          </button>
        )}
      </div>

      <hr className="nv-hr" style={{ margin: "18px 0" }} />

      {!tourOpen ? (
        /* ── default: persona-aware list ── */
        <div data-testid="workflow-list" style={{ display: "flex", flexDirection: "column" }}>
          {workflows.map((wf) => (
            <div
              key={wf.key}
              className="ct-wl"
              data-testid={`wf-row-${wf.key}`}
              role="button"
              tabIndex={0}
              onClick={() => onLaunch(wf.prompt)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onLaunch(wf.prompt); } }}
              style={{ cursor: "pointer" }}
              title={wf.prompt}
            >
              <span style={{ display: "flex", alignItems: "baseline", gap: 10, minWidth: 0 }}>
                <span className="nv-mono" style={{ fontSize: 11, color: "rgb(var(--ink-4))" }}>{wf.n}</span>
                <span style={{ color: "rgb(var(--ink))" }}>{wf.title}</span>
                <span className="nv-body" style={{ fontSize: 12, color: "rgb(var(--ink-3))" }}>· {wf.sub}</span>
              </span>
              <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>{wf.tag}</span>
            </div>
          ))}
        </div>
      ) : (
        /* ── guided tour: one tile per step ── */
        <div role="group" aria-roledescription="Guided tour" onKeyDown={onKey} data-testid="tour-stepper">
          <div ref={headingRef} tabIndex={-1} aria-current="step" style={{ outline: "none" }}>
            <Tile wf={workflows[step]} onLaunch={onLaunch} />
          </div>
          {/* controls */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginTop: 20 }}>
            <button data-testid="tour-prev" onClick={prev} disabled={step === 0} className="nv-btn" style={{ padding: "8px 16px", fontSize: 13, cursor: step === 0 ? "default" : "pointer", opacity: step === 0 ? 0.4 : 1 }}>
              ← Back
            </button>
            <span aria-live="polite" className="nv-mono" style={{ fontSize: 11, color: "rgb(var(--ink-3))", display: "flex", alignItems: "center", gap: 8 }}>
              {`${step + 1} / ${workflows.length}`}
              <span style={{ display: "inline-flex", gap: 4 }}>
                {workflows.map((_, i) => (
                  <span key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: i === step ? "var(--mint)" : "var(--line-3)" }} />
                ))}
              </span>
            </span>
            {step < workflows.length - 1 ? (
              <button data-testid="tour-next" onClick={next} className="nv-btn nv-btn-primary" style={{ padding: "8px 16px", fontSize: 13, cursor: "pointer", border: "none" }}>
                Next →
              </button>
            ) : (
              <button data-testid="tour-finish" onClick={() => setTourOpen(false)} className="nv-btn nv-btn-primary" style={{ padding: "8px 16px", fontSize: 13, cursor: "pointer", border: "none" }}>
                Finish
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
