/**
 * SelfHealingArticle — long-form body for the blog post
 * "Self-healing software: how our systems fix their own bugs — and stop at a pull request".
 *
 * Public adaptation of docs/AUTONOMOUS_DEVELOPMENT_LIFECYCLE.md + phoenix/README.md,
 * with internal file paths / config / uncommitted-status stripped for a public audience.
 * Reuses the blog design tokens; --mint is the accent, --amber marks the human gate.
 */
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";

// The pipeline — each stage a chip; the human gates are amber.
const PIPE = [
  { s: "Detect", human: false },
  { s: "Triage", human: true },
  { s: "RCA", human: false },
  { s: "Fix", human: false },
  { s: "Verify", human: false },
  { s: "PR → merge", human: true },
];

const PHASES = [
  { n: "Detect", d: "Errors become tracked issues automatically — swept from logs, reproduced by users, or reported by the app — and deduplicated by signature so the same bug never files twice. A recurrence of a resolved issue reopens as a regression." },
  { n: "Triage", d: "The human gate. A person marks an issue a real defect before anything auto-fixes; the fix path refuses to run otherwise. Autonomy doesn’t decide what’s worth fixing — a person does." },
  { n: "RCA", d: "The agent writes a root-cause analysis — summary, cause, impact, fix plan, prevention — and is explicitly forbidden from inventing details the evidence doesn’t support." },
  { n: "Fix", d: "All work happens in an isolated, throwaway clone — never the running system. The mandate: the smallest correct change at the root cause, no unrelated refactors, no hardcoded secrets. If it can’t determine a safe fix, it makes none and flags the issue for a human — it never fabricates a diff." },
  { n: "Verify", d: "The same gate, automated: a compile check, then a real test run on staging that produces a document ending in PASS or FAIL. If it’s missing something it needs — a token, a staging environment — it records the gap instead of inventing a result." },
  { n: "Review → Release", d: "It opens a pull request flagged “generated — do not merge without checking”, and stops. From there a human reviews; promotion to production is only ever a human merge." },
];

// Autonomy risk → control.
const GOV = [
  { p: "Fixes something that isn’t a real bug", s: "A human triage gate — the fix path refuses unless a person marked the issue a valid defect." },
  { p: "Corrupts the running system", s: "All work in a throwaway clone / isolated worktree, never the live tree." },
  { p: "Ships unreviewed code", s: "Pull-request only. It never merges, deploys, or writes to production; the PR is flagged for human review." },
  { p: "Touches files it shouldn’t", s: "A “smallest change” mandate, plus a hard path-allowlist that rejects any edit outside the permitted scope." },
  { p: "Claims a fix that doesn’t work", s: "A compile gate and a real staging test with a recorded verdict before anything advances." },
  { p: "Runs in production by mistake", s: "Disabled by default; off in production; missing credentials make it a safe no-op, not a guess." },
];

export default function SelfHealingArticle() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();

  return (
    <div style={{ padding: isMobile ? "0 4px" : "0" }}>
      <p style={pStyle(isMobile)}>
        The discipline we use to build with AI also runs <b>without a human at the keyboard</b>. An error in
        production becomes a triaged work-item, a root-cause analysis, an auto-fix on a branch, and an automated
        test run — and then it <b>stops</b>, at a pull request, for a human to merge. The one rule that makes
        autonomy safe is simple and absolute.
      </p>

      {/* THESIS */}
      <div className="nv-card" style={{ padding: isMobile ? "20px 20px" : "24px 28px", margin: "8px 0 26px", borderLeft: "3px solid var(--amber)" }}>
        <div className="nv-serif" style={{ fontSize: isMobile ? 19 : 22, lineHeight: 1.35, letterSpacing: "-0.01em" }}>
          Autonomy stops at the pull request. A human is the gate on
          <span style={{ color: "var(--amber)" }}> every change that ships.</span>
        </div>
      </div>

      {/* PIPELINE */}
      <div className="nv-card" style={{ padding: isMobile ? "20px 16px" : "22px 24px", margin: "0 0 22px" }}>
        <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".14em", color: "var(--ink-3)", textTransform: "uppercase", marginBottom: 14 }}>
          Error → fix → pull request
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
          {PIPE.map((step, i) => (
            <div key={step.s} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span
                className="nv-mono"
                style={{
                  fontSize: isMobile ? 11 : 12, padding: "7px 12px", borderRadius: 8, whiteSpace: "nowrap",
                  border: `1px solid ${step.human ? "var(--amber)" : "var(--line-2)"}`,
                  color: step.human ? "var(--amber)" : "var(--ink-2)",
                  background: step.human ? "transparent" : "var(--bg-2)",
                  fontWeight: step.human ? 700 : 500,
                }}
              >
                {step.s}{step.human ? " ·human" : ""}
              </span>
              {i < PIPE.length - 1 && <span style={{ color: "var(--ink-4)" }}>→</span>}
            </div>
          ))}
        </div>
        <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 14, letterSpacing: ".03em" }}>
          Two <span style={{ color: "var(--amber)" }}>human gates</span> bracket the autonomy: a person decides what gets fixed, and a person merges what ships.
        </div>
      </div>

      <h2 className="nv-serif" style={h2Style}>The lifecycle, phase by phase</h2>
      <p style={pStyle(isMobile)}>
        Each phase of a normal engineering lifecycle, run by code instead of a person — under the identical honesty
        and verification rules a human session obeys.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, margin: "6px 0 22px" }}>
        {PHASES.map((ph, i) => (
          <div key={ph.n} className="nv-card" style={{ padding: "16px 18px", borderLeft: `3px solid ${i === 1 || i === 5 ? "var(--amber)" : "var(--mint)"}` }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <span className="nv-mono" style={{ fontSize: 11, color: i === 1 || i === 5 ? "var(--amber)" : "var(--mint)", letterSpacing: ".08em" }}>{String(i + 1).padStart(2, "0")}</span>
              <span className="nv-serif" style={{ fontSize: 18, letterSpacing: "-0.01em" }}>{ph.n}</span>
              {(i === 1 || i === 5) && <span className="nv-mono" style={{ fontSize: 10, color: "var(--amber)", border: "1px solid var(--amber)", borderRadius: 6, padding: "1px 6px" }}>HUMAN</span>}
            </div>
            <div style={{ fontSize: 14.5, lineHeight: 1.55, color: "var(--ink-2)", marginTop: 8 }}>{ph.d}</div>
          </div>
        ))}
      </div>

      <h2 className="nv-serif" style={h2Style}>Phoenix — the same rules, made structural</h2>
      <p style={pStyle(isMobile)}>
        Where the in-app pipeline is a <em>feature</em>, <b>Phoenix</b> is a <em>platform</em>: an autonomous-SRE
        control plane where the coding agent is the implementation engine, wrapped in orchestration, governance and
        audit. One thin slice is proven end-to-end: an incident spins up an <b>isolated worktree</b>; the agent
        fixes the code; a hard <b>path-allowlist gate rejects</b> anything outside the permitted scope; a validator
        runs the incident’s real test suite and gates on the actual exit code; a PR is opened and recorded as
        <b> needs-approval</b>; and every step lands in an append-only audit trail. The non-negotiables aren’t
        requests here — they’re structural: it never writes production, the allowlist is a hard gate (not a polite
        ask), validation is real, every decision is audited, and it runs under the same governing rules a human
        session does.
      </p>

      {/* GOVERNANCE */}
      <h2 className="nv-serif" style={{ ...h2Style, color: "var(--mint)" }}>How each autonomy risk is contained</h2>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 12, margin: "10px 0 8px" }}>
        {GOV.map((m) => (
          <div key={m.p} className="nv-card" style={{ padding: "16px 18px", borderLeft: "3px solid var(--mint)" }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".06em", color: "var(--ink-3)", textTransform: "uppercase" }}>Risk</div>
            <div style={{ fontSize: 14, fontWeight: 600, margin: "5px 0 8px" }}>{m.p}</div>
            <div style={{ color: "var(--mint)", fontWeight: 700, fontSize: 13, marginBottom: 4 }}>→</div>
            <div style={{ fontSize: 14, lineHeight: 1.5, color: "var(--ink-2)" }}>{m.s}</div>
          </div>
        ))}
      </div>

      <p style={{ ...pStyle(isMobile), color: "var(--ink-3)", fontSize: isMobile ? 14 : 15, marginTop: 22 }}>
        Today this is an early walking skeleton — proven on a controlled incident. Broader observability ingestion,
        automated staging promotion and a learning loop are on the roadmap. What ships first, and stays fixed, is
        the safety model: a human decides what to fix, and a human merges what goes live.
      </p>

      {/* CTA */}
      <div className="nv-card" style={{ padding: isMobile ? "24px 20px" : "30px 32px", margin: "28px 0 8px", textAlign: "center" }}>
        <h3 className="nv-serif" style={{ fontSize: isMobile ? 26 : 32, letterSpacing: "-0.02em", margin: 0 }}>
          Software that heals itself — safely
        </h3>
        <p style={{ fontSize: 15, color: "var(--ink-2)", margin: "12px auto 0", maxWidth: 460, lineHeight: 1.6 }}>
          The same engineering discipline runs behind Nivesh Copilot — grounded in real evidence, gated by real
          verification, and never claiming “done” without proof.
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
