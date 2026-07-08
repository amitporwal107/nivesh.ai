/**
 * HowWeUseClaudeArticle — long-form body for the blog post
 * "How we build with Claude: an AI engineering team that can't fake 'done'".
 *
 * Public adaptation of docs/HOW_WE_USE_CLAUDE.md — the engineering narrative, with
 * internal file paths / config / status stripped for a public audience. Reuses the
 * blog design tokens; --mint is the accent (engineering / positive).
 */
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";

const PILLARS = [
  { k: "Shared context", d: "One grounding and one source of truth for every session and every agent." },
  { k: "Roles", d: "Per-discipline guardrails and a concrete Definition of Done." },
  { k: "Skills", d: "Project-trained capabilities the agent loads only when relevant." },
  { k: "Subagents", d: "Read-only specialists that run in isolated context." },
  { k: "Commands", d: "Entry points that orchestrate all of the above." },
  { k: "Hooks", d: "Deterministic enforcement of the honesty rules." },
];

// Failure mode → countermeasure.
const MAPS = [
  { p: "Model guesses facts it should look up", s: "Shared context + a golden-source rule: the canonical docs, then the code, win every conflict." },
  { p: "The wrong discipline’s standards get applied", s: "A role-intake step classifies the work and loads the matching guardrails — strictest gate wins." },
  { p: "Re-pasting the same grounding every session", s: "Skills carry their own mandatory pre-reads, pulled in on demand." },
  { p: "Multi-agent context corruption / write races", s: "Read-only specialists + a single orchestrator-writer + a file-based shared workspace." },
  { p: "Silent assumptions on unknowns", s: "A load-bearing unknown pauses the work and asks a human, instead of guessing." },
  { p: "“I wrote the code” disguised as “it works”", s: "A verification gate physically blocks the finish until a real test/build/curl has run." },
];

export default function HowWeUseClaudeArticle() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();

  return (
    <div style={{ padding: isMobile ? "0 4px" : "0" }}>
      <p style={pStyle(isMobile)}>
        Most teams use AI as autocomplete. We don’t. We treat Claude as a <b>team of disciplined engineers</b>
        that boots into the same context every session, classifies the work before touching it, plans through a
        shared workspace, and is <b>deterministically blocked from claiming “done” without showing real
        evidence</b>. The whole system is checked into the repo and versioned like any other code.
      </p>

      {/* THESIS */}
      <div className="nv-card" style={{ padding: isMobile ? "20px 20px" : "24px 28px", margin: "8px 0 26px", borderLeft: "3px solid var(--mint)" }}>
        <div className="nv-serif" style={{ fontSize: isMobile ? 19 : 22, lineHeight: 1.35, letterSpacing: "-0.01em" }}>
          “Changed” is not “verified” — and the machine, not the model’s good intentions,
          <span style={{ color: "var(--mint)" }}> enforces the difference.</span>
        </div>
      </div>

      <p style={pStyle(isMobile)}>Six moving parts make it work:</p>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(3, 1fr)", gap: 12, margin: "6px 0 24px" }}>
        {PILLARS.map((p) => (
          <div key={p.k} className="nv-card" style={{ padding: "16px 18px", borderTop: "3px solid var(--mint)" }}>
            <div className="nv-serif" style={{ fontSize: 17, letterSpacing: "-0.01em" }}>{p.k}</div>
            <div style={{ fontSize: 13, lineHeight: 1.5, color: "var(--ink-3)", marginTop: 6 }}>{p.d}</div>
          </div>
        ))}
      </div>

      <h2 className="nv-serif" style={h2Style}>Context is loaded, not remembered</h2>
      <p style={pStyle(isMobile)}>
        The core problem with AI on a large codebase is drift: the model guesses at facts it should look up, and
        every session re-invents the project. A constitution file loads into <b>every</b> session — the task-intake
        protocol, the honesty rules, a reserved status vocabulary, and the shared quality bar. The documentation is
        the source of truth, with an explicit precedence rule: the summary is a summary; the canonical docs, then
        the code, win every conflict. A cold session and a subagent spawned mid-task ground themselves in the same
        documents with the same precedence.
      </p>

      <h2 className="nv-serif" style={h2Style}>The work tells you which guardrails apply</h2>
      <p style={pStyle(isMobile)}>
        Before doing anything, a session restates the task, classifies the discipline(s) it touches, and loads the
        matching role guide — full-stack, QA, product, design or project. A task can span several; we take the
        <b> union of their guardrails, strictest gate wins</b>. Each role ends in a concrete Definition of Done with
        a per-environment checklist: staging and production have <b>different, stricter</b> gates. “Done” is a
        specific, checkable thing per environment — not a vibe.
      </p>

      <h2 className="nv-serif" style={h2Style}>Isolated specialists, one writer</h2>
      <p style={pStyle(isMobile)}>
        Subagents each run in their <b>own</b> context window and return only a summary — they don’t share live
        memory. So “shared context” across agents is engineered, not automatic: they inherit the same instructions,
        and they pass state as <b>files in a shared workspace on disk</b>. Two constraints prevent the classic
        multi-agent failure modes — the specialists are <b>read-only</b>, and a single orchestrator is the <b>only
        writer</b>. No concurrent-write corruption, no agent stalled on a permission prompt. That file hand-off is
        the shared context in action.
      </p>

      <h2 className="nv-serif" style={h2Style}>The part that isn’t optional</h2>
      <p style={pStyle(isMobile)}>
        Everything above is <em>instructions</em> — and instructions can be ignored under pressure to look done. So
        the honesty rules have a <b>deterministic floor</b>: shell hooks the harness runs regardless of what the
        model intends. The invariant they enforce: <b>you cannot edit code and end the turn without running a real
        verification command</b>. Edit code, and the session is flagged; run a genuine test / build / health-check,
        and the flag clears; try to finish while still flagged, and the stop is <b>physically blocked</b> with a
        message sending the agent back to verify. That is the mechanical enforcement of the rule that
        “done” and “verified” may only be claimed with real command output in the <em>same</em> response.
      </p>

      {/* FAILURE MODE → COUNTERMEASURE */}
      <h2 className="nv-serif" style={{ ...h2Style, color: "var(--mint)" }}>Every piece defeats a specific failure mode</h2>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 12, margin: "10px 0 8px" }}>
        {MAPS.map((m) => (
          <div key={m.p} className="nv-card" style={{ padding: "16px 18px", borderLeft: "3px solid var(--mint)" }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".06em", color: "var(--ink-3)", textTransform: "uppercase" }}>
              Failure mode
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, margin: "5px 0 8px" }}>{m.p}</div>
            <div style={{ color: "var(--mint)", fontWeight: 700, fontSize: 13, marginBottom: 4 }}>→</div>
            <div style={{ fontSize: 14, lineHeight: 1.5, color: "var(--ink-2)" }}>{m.s}</div>
          </div>
        ))}
      </div>

      <p style={{ ...pStyle(isMobile), fontWeight: 500, color: "var(--ink)", marginTop: 24 }}>
        The result is an agent system that is <b>fast where it’s safe to be fast, and unable to lie about being
        done.</b> Context is loaded, not remembered. Roles are matched, not assumed. Verification is enforced,
        not promised.
      </p>

      {/* CTA */}
      <div className="nv-card" style={{ padding: isMobile ? "24px 20px" : "30px 32px", margin: "28px 0 8px", textAlign: "center" }}>
        <h3 className="nv-serif" style={{ fontSize: isMobile ? 26 : 32, letterSpacing: "-0.02em", margin: 0 }}>
          This is the discipline behind Nivesh Copilot
        </h3>
        <p style={{ fontSize: 15, color: "var(--ink-2)", margin: "12px auto 0", maxWidth: 460, lineHeight: 1.6 }}>
          The same honesty and verification rules that govern how we build also govern the advice the product
          gives you — grounded in real data, never guessed.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap", marginTop: 22 }}>
          <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/copilot")}>
            See the Copilot
          </button>
          <button className="nv-btn" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/blog")}>
            More writing
          </button>
        </div>
      </div>
    </div>
  );
}

const h2Style: React.CSSProperties = {
  fontSize: 28,
  letterSpacing: "-0.02em",
  margin: "34px 0 12px",
};

function pStyle(isMobile: boolean): React.CSSProperties {
  return {
    fontSize: isMobile ? 16 : 17,
    lineHeight: 1.7,
    color: "var(--ink-2)",
    margin: "0 0 18px",
  };
}
