/**
 * Overview — page hero, the 5-step "how the copilot thinks" pipeline,
 * the guided tour stops, and the two-audiences split.
 */
import { Mark } from "../parts";

const PIPELINE = [
  { n: "01 · GROUNDING", t: "NIDP data layer", d: "Live portfolio, Q/H/E/A scores, market context — the facts every answer stands on.", accent: "var(--mint)", border: "rgb(var(--pos) / 0.28)" },
  { n: "02 · REASONING", t: "Specialist agents", d: "Health, Quality, Exit, Add, Tax, Goals, Allocation, Market — each owns a job.", accent: "var(--indigo-hex)" },
  { n: "03 · VERDICT", t: "One synthesis line", d: "A single editorial sentence names the problem in plain language.", accent: "rgb(var(--ink-3))" },
  { n: "04 · PRIORITISE", t: "Ranked by ₹ impact", d: "Actions numbered 01–03, ordered by rupee effect, each with its severity.", accent: "var(--amber)" },
  { n: "05 · SAFETY", t: "Approve · escalate", d: "Nothing executes without consent; a human advisor is always one tap away.", accent: "var(--amber)", border: "rgb(var(--warm) / 0.30)" },
];

const STOPS = [
  { n: "01", tag: "PRINCIPLES", t: "Design paradigms", d: "Why advisory AI needs a workspace, evidence, guided freedom, stage visibility and a human loop — annotated beside a live mockup.", href: "#ct-principles" },
  { n: "02", tag: "6 SCREENS", t: "The advisory page, end to end", d: "Portfolio Health Review in full — Intake → Analysis → Options → Recommendation → Action → Escalation.", href: "#ct-screens" },
  { n: "03", tag: "10 CARDS", t: "Every workflow at a glance", d: "The full catalog of investor jobs — health, fund deep-dive, buy, exit, tax, goals, rebalance, consolidate, SIP, market.", href: "#ct-workflows" },
  { n: "04", tag: "40 PANELS", t: "All flows, start to finish", d: "Every workflow as an Ask → Analyze → Decide → Act filmstrip — the complete journey for each.", href: "#ct-allflows" },
  { n: "05", tag: "ADVISOR", t: "The advisor's book (MFD)", d: "AUM & book health, a “who to call first” monitor, and nine client-driven workflows across 128 clients.", href: "#ct-advisor", indigo: true },
  { n: "06", tag: "iPHONE", t: "On mobile", d: "The same loop in your pocket — ask, read the synthesis, act on the ranked fix, approve.", href: "#ct-mobile" },
];

const INVESTOR = [
  ["Portfolio health review", "H"],
  ["Fund deep-dive", "Q"],
  ["Where to invest new money", "A"],
  ["Should I sell?", "E"],
  ["Tax-loss harvesting", "TAX"],
  ["Goal on track?", "GOAL"],
  ["Rebalance · Consolidate · SIP · Market", "+4"],
];
const ADVISOR: Array<[string, string, string]> = [
  ["AUM & book health", "₹42.8Cr", "rgb(var(--ink-3))"],
  ["At-risk & churn", "7", "var(--danger-hex)"],
  ["Reviews due", "14", "var(--amber)"],
  ["Harvest across the book", "₹3.1L", "var(--mint)"],
  ["Idle cash to deploy", "₹1.2Cr", "var(--mint)"],
  ["Off-mandate · SIP step-ups · Onboarding", "+3", "rgb(var(--ink-3))"],
  ["Suitability & disclosures", "GUARD", "var(--danger-hex)"],
];

export default function Overview() {
  return (
    <section id="ct-overview" style={{ padding: "44px clamp(18px,3vw,56px) 20px" }}>
      {/* hero */}
      <div className="ct-wrap" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 16 }}>
            <Mark />
            <span className="nv-serif" style={{ fontSize: 20 }}>Nivesh Copilot</span>
            <span className="nv-pill nv-pill-mint"><span className="nv-dot" style={{ background: "var(--mint)" }} />GUIDED TOUR</span>
          </div>
          <div className="nv-eyebrow" style={{ marginBottom: 10 }}>THE COMPLETE ADVISORY AI · INVESTOR + ADVISOR · DESKTOP + MOBILE</div>
          <h1 className="nv-serif" style={{ margin: 0, fontSize: "clamp(32px,3.6vw,52px)", lineHeight: 1.03, maxWidth: "18ch" }}>
            One AI that reads your portfolio and tells you the <span style={{ color: "var(--mint)" }}>one thing to fix first</span>.
          </h1>
        </div>
        <p className="nv-prose" style={{ maxWidth: "34ch", margin: 0, fontSize: 14 }}>
          Six deliverables, one system. Start with how the engine works, then walk each surface — every screen links to its own section.
        </p>
      </div>

      <hr className="nv-hr" style={{ maxWidth: 1340, margin: "28px auto 34px" }} />

      <div className="ct-wrap" style={{ display: "flex", flexDirection: "column", gap: 40 }}>
        {/* how the engine works */}
        <div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
            <span className="nv-serif" style={{ fontSize: 24 }}>How the copilot thinks</span>
            <span className="nv-body" style={{ color: "rgb(var(--ink-3))" }}>Grounded data → specialist agents → one synthesis → ranked action → your approval</span>
          </div>
          <div className="nv-card" style={{ padding: 8 }}>
            <div className="ct-pipe">
              {PIPELINE.map((p, i) => (
                <div key={p.t} style={{ display: "contents" }}>
                  <div className="nv-card-2 ct-node" style={{ borderColor: p.border }}>
                    <span className="nv-eyebrow" style={{ fontSize: 8, color: p.accent }}>{p.n}</span>
                    <span className="nv-serif" style={{ fontSize: 17 }}>{p.t}</span>
                    <span className="nv-body" style={{ fontSize: 12 }}>{p.d}</span>
                  </div>
                  {i < PIPELINE.length - 1 && <div className="ct-arw">→</div>}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* guided tour stops */}
        <div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
            <span className="nv-serif" style={{ fontSize: 24 }}>Walk the system</span>
            <span className="nv-body" style={{ color: "rgb(var(--ink-3))" }}>Six stops · each jumps to its section</span>
          </div>
          <div className="ct-cardgrid" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(340px,1fr))" }}>
            {STOPS.map((s) => (
              <a key={s.n} href={s.href} className="nv-card ct-stop" style={s.indigo ? { borderColor: "rgb(var(--indigo) / 0.30)" } : undefined}>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
                  <span className="ct-bignum" style={s.indigo ? { color: "var(--indigo-hex)" } : undefined}>{s.n}</span>
                  <span className={s.indigo ? "nv-pill nv-pill-indigo" : "nv-pill"} style={{ fontSize: 9 }}>{s.tag}</span>
                </div>
                <span className="nv-serif" style={{ fontSize: 20 }}>{s.t}</span>
                <span className="nv-body" style={{ fontSize: 13 }}>{s.d}</span>
                <span className="ct-open" style={s.indigo ? { color: "var(--indigo-hex)" } : undefined}>OPEN ▸</span>
              </a>
            ))}
          </div>
        </div>

        {/* two audiences */}
        <div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
            <span className="nv-serif" style={{ fontSize: 24 }}>Two audiences, one engine</span>
            <span className="nv-body" style={{ color: "rgb(var(--ink-3))" }}>The same NIDP grounding serves the investor and the advisor</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(400px,1fr))", gap: 18 }}>
            <div className="nv-card" style={{ padding: "20px 22px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 12 }}>
                <span className="nv-pill nv-pill-mint" style={{ fontSize: 9 }}>INVESTOR</span>
                <span className="nv-body" style={{ color: "rgb(var(--ink-3))", fontSize: 12 }}>10 workflows · self-serve</span>
              </div>
              {INVESTOR.map(([label, tag]) => (
                <div key={label} className="ct-wl">
                  <span>{label}</span>
                  <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>{tag}</span>
                </div>
              ))}
            </div>
            <div className="nv-card" style={{ padding: "20px 22px", borderColor: "rgb(var(--indigo) / 0.30)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 12 }}>
                <span className="nv-pill nv-pill-indigo" style={{ fontSize: 9 }}>ADVISOR · MFD</span>
                <span className="nv-body" style={{ color: "rgb(var(--ink-3))", fontSize: 12 }}>9 workflows · book-level</span>
              </div>
              {ADVISOR.map(([label, tag, color]) => (
                <div key={label} className="ct-wl">
                  <span>{label}</span>
                  <span className="nv-mono" style={{ fontSize: 10, color }}>{tag}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
