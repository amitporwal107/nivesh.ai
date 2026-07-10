/**
 * TeamOfTenArticle — long-form body for the engineering blog post
 * "Shipping like a team of ten: how we automated our dev + support lifecycle
 * with Claude AI". Adapted from the internal webinar deck of the same name.
 *
 * Same visual system as the other posts: app design tokens (--mint = the
 * "control/solution" accent, --danger-hex = the failure/risk accent, --amber =
 * the "staging / caution" state), nv-card / nv-serif / nv-mono, theme-aware.
 * Honesty note: the "scorecard" section deliberately states what is NOT yet in
 * production — that candor is the whole point of the system it describes.
 */
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";

// The surface a lean team has to cover — the reason "AI as autocomplete" wasn't enough.
const SURFACE = [
  { n: "2", l: "independent production systems", s: "the Copilot app + NIDP, our data platform" },
  { n: "41", l: "Indian market-data feeds", s: "ingested into people's financial decisions" },
  { n: "3", l: "databases, one stack", s: "React 19 · FastAPI · Mongo · Postgres · Redis" },
];

// The six building blocks — each a control on a specific failure mode.
const BLOCKS = [
  { n: "1", t: "Shared context", s: "One grounding, one source of truth — loaded into every session, not remembered." },
  { n: "2", t: "Roles", s: "Per-discipline guardrails + a real, per-environment Definition of Done." },
  { n: "3", t: "Skills", s: "Project-trained capabilities that load on demand and compose." },
  { n: "4", t: "Subagents", s: "Read-only specialists in isolated context; one orchestrator writes." },
  { n: "5", t: "Commands", s: "Slash-command entry points that orchestrate everything above." },
  { n: "6", t: "Hooks", s: "The deterministic floor that enforces honesty. Not optional." },
];

// Failure mode → the control that neutralises it.
const CONTROLS = [
  { f: "The model guesses facts it should look up", c: "A constitution file loads every session; the repo docs are the source of truth. Docs, then code, win every conflict." },
  { f: "The wrong discipline's standards get applied", c: "An intake table maps each request to role guides; a task spanning several loads all of them — strictest gate wins." },
  { f: "It says “done” for code it never ran", c: "A shell hook sets an “unverified” flag on every edit and blocks the turn from ending until a real verify command runs." },
  { f: "An autonomous agent ships unreviewed code", c: "Every autonomous path stops at a pull request. Nothing merges, deploys, or writes main without a human." },
];

// The honest scorecard — states what is live vs. not.
const SCORECARD = [
  { tag: "LIVE", color: "var(--mint)", t: "The assisted flow", s: "Real, in daily use — every feature below went through it." },
  { tag: "STAGING", color: "var(--amber)", t: "Several features", s: "Staging-verified, not yet on prod — the V5 frontend is still rolling out." },
  { tag: "NOT YET", color: "var(--ink-4)", t: "The autonomous systems", s: "Build-verified only, OFF in production by default. Not yet proven end-to-end on live production incidents." },
];

export default function TeamOfTenArticle() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const pad = isMobile ? "0 4px" : "0";

  return (
    <div style={{ padding: pad }}>
      {/* SURFACE STAT TILES */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(3, 1fr)", gap: 14, margin: "8px 0 40px" }}>
        {SURFACE.map((t) => (
          <div key={t.l} className="nv-card" style={{ padding: 22, borderLeft: "3px solid var(--mint)" }}>
            <div className="nv-serif" style={{ fontSize: isMobile ? 40 : 46, lineHeight: 1, letterSpacing: "-0.03em", color: "var(--mint)" }}>{t.n}</div>
            <div style={{ fontSize: 14, fontWeight: 500, marginTop: 12 }}>{t.l}</div>
            <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 4, letterSpacing: ".04em" }}>{t.s}</div>
          </div>
        ))}
      </div>

      <p style={pStyle(isMobile)}>
        Most teams use AI as a fancy autocomplete — and hit a wall. It <b>guesses facts it should look up</b>
        (wrong endpoint, stale schema). It applies the <b>wrong standards</b> (a UI change with no
        accessibility, a database change with no migration discipline). And worst of all, it cheerfully says
        <b> "Done ✅"</b> for code it never ran. On a toy project that's a nuisance. On a real product, that
        last one is a <b>liability</b>.
      </p>

      <p style={pStyle(isMobile)}>
        We couldn't afford it. Nivesh.ai is an AI wealth-management copilot for Indian investors, run by a
        lean team across two production systems, 41 market-data feeds, and other people's money. We
        physically cannot review every line the way a fifty-person team might. Either AI makes us genuinely
        faster <i>and</i> safe — or we can't use it for anything that ships. In fintech, <b>"it returned 200"
        is not "the number is right."</b>
      </p>

      <p style={pStyle(isMobile)}>
        So we stopped prompting harder and changed the environment the AI works in. We built a <b>team of
        disciplined AI engineers directly into the repo</b> — and one rule runs through all of it.
      </p>

      {/* THE ONE RULE */}
      <div className="nv-card" style={{ padding: isMobile ? "26px 22px" : "34px 36px", margin: "8px 0 28px", borderLeft: "3px solid var(--mint)" }}>
        <div className="nv-serif" style={{ fontSize: isMobile ? 26 : 32, letterSpacing: "-0.02em", lineHeight: 1.15 }}>
          "Changed" is not "verified."
        </div>
        <p style={{ fontSize: isMobile ? 16 : 18, color: "var(--ink-2)", margin: "14px 0 0", lineHeight: 1.6 }}>
          And the <b>machine</b> — not the model's good intentions — enforces the difference. Don't ask the
          model to be honest. Make honesty the only path the environment allows.
        </p>
      </div>

      <h2 className="nv-serif" style={h2Style}>What it actually buys a founder</h2>
      <p style={pStyle(isMobile)}>
        This isn't about the AI being clever. It's a business trade: <b>leverage</b> — a lean team operates
        like a much larger one, with spec, build, verify and support running in parallel — but{" "}
        <b>speed only where it's safe</b>. Fast and loose on reversible work; strict and evidence-gated on
        anything that touches money or ships to production. The roles, gates and decision logs are{" "}
        <b>files in the repo</b> — an auditable governance surface, not tribal knowledge in someone's head.
        What you're really buying insurance against is a false "done" reaching production. That's a business
        risk, not a dev inconvenience.
      </p>

      <h2 className="nv-serif" style={h2Style}>Six building blocks, one invariant</h2>
      <p style={pStyle(isMobile)}>
        The system has six moving parts. Read each not as a "cool AI feature" but as a <b>control on a
        specific failure mode</b>. This post is the overview; we take the human-driven system apart
        block by block in{" "}
        <span onClick={() => navigate("/blog/how-we-build-with-claude")} style={linkStyle}>How we build with Claude</span>.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 12, margin: "10px 0 20px" }}>
        {BLOCKS.map((b) => (
          <div key={b.n} className="nv-card" style={{ padding: "16px 18px" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <span className="nv-serif" style={{ fontSize: 22, color: "var(--mint)", lineHeight: 1 }}>{b.n}</span>
              <span style={{ fontSize: 15, fontWeight: 600 }}>{b.t}</span>
            </div>
            <div style={{ fontSize: 14, lineHeight: 1.5, color: "var(--ink-2)", marginTop: 8 }}>{b.s}</div>
          </div>
        ))}
      </div>

      <h2 className="nv-serif" style={h2Style}>The hook that can't be argued with</h2>
      <p style={pStyle(isMobile)}>
        Everything above is instructions — and instructions get ignored under pressure to look done. So the
        honesty rule has a deterministic floor: shell hooks the harness runs no matter what the model intends.
        The moment code is edited, an "unverified" flag is set. If the agent tries to end the turn with that
        flag still set, the hook <b>exits 2 and physically blocks it</b>. Only a real verification command
        clears it — and the reserved words (<span className="nv-mono">done · verified · fixed</span>) are only
        allowed with the evidence in the same message.
      </p>

      {/* TERMINAL CARD — the gate in action */}
      <div className="nv-card" style={{ padding: isMobile ? "18px 16px" : "22px 24px", margin: "8px 0 20px", background: "var(--bg-2)" }}>
        <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".14em", color: "var(--ink-4)", textTransform: "uppercase", marginBottom: 12 }}>
          the gate, live
        </div>
        <pre className="nv-mono" style={{ fontSize: isMobile ? 12 : 13, lineHeight: 1.9, color: "var(--ink-2)", margin: 0, whiteSpace: "pre-wrap", overflowX: "auto" }}>
{`$ /work fix WORK-1042
  intake     Full-Stack + QA
  edit       `}<span style={{ color: "var(--amber)" }}>flag: UNVERIFIED</span>{`
  end turn?  `}<span style={{ color: "var(--danger-hex)" }}>exit 2 — BLOCKED</span>{`
  pytest     14 passed in 6.2s
  report     `}<span style={{ color: "var(--mint)" }}>## Verdict: PASS</span></pre>
        <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 14, letterSpacing: ".03em" }}>
          The model doesn't get to decide it's done. The machine decides, based on evidence.
        </div>
      </div>

      <h2 className="nv-serif" style={h2Style}>Every failure mode has a named control</h2>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 12, margin: "10px 0 20px" }}>
        {CONTROLS.map((m) => (
          <div key={m.f} className="nv-card" style={{ padding: "16px 18px", borderLeft: "3px solid var(--mint)" }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".08em", color: "var(--ink-3)", textTransform: "uppercase" }}>
              Failure · <span style={{ color: "var(--danger-hex)" }}>{m.f}</span>
            </div>
            <div style={{ color: "var(--mint)", fontWeight: 700, margin: "7px 0 3px", fontSize: 13 }}>→</div>
            <div style={{ fontSize: 14.5, lineHeight: 1.5 }}>{m.c}</div>
          </div>
        ))}
      </div>

      <h2 className="nv-serif" style={h2Style}>When the same lifecycle drives itself</h2>
      <p style={pStyle(isMobile)}>
        The human-driven flow — intake → plan → build → verify → PR — also runs <b>autonomously</b>, under the
        identical honesty rules and verification gate. In our Error → Fix pipeline, a production error becomes
        a tracked issue, a root-cause analysis, an isolated-clone code change, and a staging test report. Two
        of those six phases are <b>human gates</b>: a person must classify an issue as a real bug before the
        fix agent will run, and a person reviews and merges the pull request it opens. The agent never
        fabricates a diff it can't verify, and never merges its own work. We walk the whole autonomous
        lifecycle — and the Phoenix control plane behind it — in{" "}
        <span onClick={() => navigate("/blog/self-healing-software-autonomous-fixes")} style={linkStyle}>Self-healing software</span>.
      </p>
      <p style={{ ...pStyle(isMobile), fontWeight: 500, color: "var(--ink)" }}>
        The one rule that keeps autonomy safe: <b>it stops at the pull request.</b> No autonomous path merges,
        deploys, or writes <span className="nv-mono">main</span>. A human is the gate on everything that ships.
      </p>

      {/* HONEST SCORECARD */}
      <h2 className="nv-serif" style={h2Style}>The honest scorecard</h2>
      <p style={pStyle(isMobile)}>
        Because the whole point of the system is that we don't overstate — the same rule applies to this post.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(3, 1fr)", gap: 12, margin: "10px 0 20px" }}>
        {SCORECARD.map((c) => (
          <div key={c.t} className="nv-card" style={{ padding: "18px 20px", borderTop: `3px solid ${c.color}` }}>
            <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".12em", color: c.color, fontWeight: 700 }}>{c.tag}</div>
            <div style={{ fontSize: 15, fontWeight: 600, marginTop: 10 }}>{c.t}</div>
            <div style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--ink-2)", marginTop: 6 }}>{c.s}</div>
          </div>
        ))}
      </div>
      <p style={pStyle(isMobile)}>
        A claim of "fully autonomous production self-healing 🎉" would violate the exact rule this system
        teaches. <b>Verified means verified. On staging is not on prod.</b> Being able to tell you precisely
        where that line is — that's the deliverable.
      </p>

      <h2 className="nv-serif" style={h2Style}>Start Monday: buy the discipline before the autonomy</h2>
      <p style={pStyle(isMobile)}>
        You don't need our whole stack to get the biggest win. In week one, write one page of project context
        (what the project is, where the source-of-truth docs live, five honesty rules) and add{" "}
        <b>one enforcement hook</b>: edited code with no verification run means the turn can't end. That single
        control kills the "fake done" risk immediately — it's the highest-ROI thing on the list. Standards and
        roles come next; the multi-agent team after that; and <b>autonomy is the last thing you turn on</b>,
        never the first — stopping at the PR, with a human triage gate, proven in staging before you trust it.
      </p>

      {/* THREE SENTENCES */}
      <div className="nv-card" style={{ padding: isMobile ? "24px 22px" : "30px 34px", margin: "20px 0 8px" }}>
        <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".14em", color: "var(--ink-4)", textTransform: "uppercase", marginBottom: 16 }}>
          the three sentences to remember
        </div>
        {["Context is loaded, not remembered.", "Roles are matched, not assumed.", "Verification is enforced, not promised."].map((s) => (
          <div key={s} className="nv-serif" style={{ fontSize: isMobile ? 20 : 24, letterSpacing: "-0.01em", lineHeight: 1.35, color: "var(--mint)", marginBottom: 6 }}>{s}</div>
        ))}
        <p style={{ fontSize: 14.5, color: "var(--ink-2)", margin: "14px 0 0", lineHeight: 1.6 }}>
          The result: an AI system that is fast where it's safe to be fast — and unable to lie about being done.
        </p>
      </div>

      {/* GO DEEPER — cross-links to the two deep-dive posts */}
      <h2 className="nv-serif" style={h2Style}>Go deeper</h2>
      <p style={pStyle(isMobile)}>
        This piece is the whole story at a glance. Each half has its own deep-dive:
      </p>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 12, margin: "10px 0 8px" }}>
        <div className="nv-card" role="link" tabIndex={0} onClick={() => navigate("/blog/how-we-build-with-claude")}
          style={{ padding: "18px 20px", cursor: "pointer", borderLeft: "3px solid var(--mint)" }}>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".12em", color: "var(--mint)", textTransform: "uppercase" }}>The assisted half</div>
          <div style={{ fontSize: 16, fontWeight: 600, marginTop: 8, lineHeight: 1.2 }}>How we build with Claude</div>
          <p style={{ fontSize: 13.5, color: "var(--ink-2)", lineHeight: 1.5, marginTop: 6 }}>The six-part system, block by block — context, roles, skills, subagents, commands, hooks.</p>
          <div style={{ color: "var(--mint)", fontSize: 13, fontWeight: 500, marginTop: 10 }}>Read the deep-dive →</div>
        </div>
        <div className="nv-card" role="link" tabIndex={0} onClick={() => navigate("/blog/self-healing-software-autonomous-fixes")}
          style={{ padding: "18px 20px", cursor: "pointer", borderLeft: "3px solid var(--mint)" }}>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".12em", color: "var(--mint)", textTransform: "uppercase" }}>The autonomous half</div>
          <div style={{ fontSize: 16, fontWeight: 600, marginTop: 8, lineHeight: 1.2 }}>Self-healing software</div>
          <p style={{ fontSize: 13.5, color: "var(--ink-2)", lineHeight: 1.5, marginTop: 6 }}>Error → triaged issue → RCA → auto-fix → staging test → a PR that waits for a human. Plus Phoenix.</p>
          <div style={{ color: "var(--mint)", fontSize: 13, fontWeight: 500, marginTop: 10 }}>Read the deep-dive →</div>
        </div>
      </div>

      {/* CTA */}
      <div className="nv-card" style={{ padding: isMobile ? "24px 20px" : "30px 32px", margin: "28px 0 8px", textAlign: "center" }}>
        <h3 className="nv-serif" style={{ fontSize: isMobile ? 26 : 32, letterSpacing: "-0.02em", margin: 0 }}>
          See what the system shipped
        </h3>
        <p style={{ fontSize: 15, color: "var(--ink-2)", margin: "12px auto 0", maxWidth: 460, lineHeight: 1.6 }}>
          The strategy workbench, the "what-if" backtest, the Learning Centre — every feature in the Copilot
          went through the lifecycle above. Try it read-only on your own portfolio.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap", marginTop: 22 }}>
          <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
            Try Nivesh Copilot free
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

const linkStyle: React.CSSProperties = {
  color: "var(--mint)",
  cursor: "pointer",
  fontWeight: 600,
};

function pStyle(isMobile: boolean): React.CSSProperties {
  return {
    fontSize: isMobile ? 16 : 17,
    lineHeight: 1.7,
    color: "var(--ink-2)",
    margin: "0 0 18px",
  };
}
