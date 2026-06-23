/**
 * About — public marketing page. Mission + principles, grounded in the product
 * positioning ("your portfolio, finally legible") and how Nivesh actually works.
 */
import { useNavigate } from "react-router-dom";
import MarketingShell from "@/components/marketing/MarketingShell";

const PRINCIPLES = [
  { t: "Legible, not louder", d: "Most tools throw more numbers at you. We translate your portfolio into plain language and a single grade you can act on." },
  { t: "Read-only by design", d: "We analyse; we never trade or move your money. Access is read-only, and your decisions stay yours." },
  { t: "Grounded, never guessed", d: "Every score traces back to a real holding, and every Copilot answer cites the data it used. No made-up numbers." },
  { t: "Aligned with you", d: "SEBI-aligned analysis tied to your goals and risk profile — not to selling you a product." },
];

const STATS = [
  { v: "20+", l: "health checks per portfolio" },
  { v: "6", l: "scored dimensions, one A–D grade" },
  { v: "4", l: "ways to connect: Gmail, PDF, broker, manual" },
];

export default function AboutPage() {
  const navigate = useNavigate();
  return (
    <MarketingShell>
      {/* hero */}
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "80px 56px 32px", textAlign: "center" as const }}>
        <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--mint)", textTransform: "uppercase" as const }}>About</div>
        <h1 className="nv-serif" style={{ fontSize: 64, lineHeight: 1.0, letterSpacing: "-0.035em", margin: "14px 0 0" }}>
          We make portfolios<br /><span style={{ fontStyle: "italic" }}>legible</span><span style={{ color: "var(--mint)" }}>.</span>
        </h1>
        <p style={{ fontSize: 19, lineHeight: 1.6, color: "var(--ink-2)", margin: "24px auto 0", maxWidth: 600 }}>
          Most investors hold more than they can read — statements across funds, stocks, FDs
          and NPS, scattered and unscored. Nivesh reconciles all of it, grades its health,
          and tells you what to fix and why, in plain language.
        </p>
      </div>

      {/* stat band */}
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "24px 56px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 1, background: "rgb(var(--line) / 0.06)", border: "1px solid rgb(var(--line) / 0.06)", borderRadius: 18, overflow: "hidden" }}>
          {STATS.map((s) => (
            <div key={s.l} style={{ padding: 28, background: "var(--bg-1)", textAlign: "center" as const }}>
              <div className="nv-serif" style={{ fontSize: 44, letterSpacing: "-0.035em" }}>{s.v}</div>
              <p style={{ fontSize: 13, color: "var(--ink-2)", marginTop: 8, lineHeight: 1.5 }}>{s.l}</p>
            </div>
          ))}
        </div>
      </div>

      {/* principles */}
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "48px 56px" }}>
        <div style={{ textAlign: "center" as const, marginBottom: 36 }}>
          <h2 className="nv-serif" style={{ fontSize: 40, letterSpacing: "-0.03em", margin: 0 }}>What we believe</h2>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 16 }}>
          {PRINCIPLES.map((p) => (
            <div key={p.t} className="nv-card" style={{ padding: 28 }}>
              <div className="nv-serif" style={{ fontSize: 24, letterSpacing: "-0.02em" }}>{p.t}</div>
              <p style={{ fontSize: 15, color: "var(--ink-2)", lineHeight: 1.6, marginTop: 10 }}>{p.d}</p>
            </div>
          ))}
        </div>
      </div>

      {/* CTA */}
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "24px 56px 16px", textAlign: "center" as const }}>
        <h2 className="nv-serif" style={{ fontSize: 40, letterSpacing: "-0.03em", margin: 0 }}>Built in India, for Indian portfolios.</h2>
        <p style={{ fontSize: 16, color: "var(--ink-2)", margin: "14px auto 0", maxWidth: 460 }}>
          SEBI-aligned · ARN-128459 · Investments are subject to market risk.
        </p>
        <div style={{ display: "flex", gap: 12, marginTop: 28, justifyContent: "center" }}>
          <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
            Check my portfolio free
          </button>
          <button className="nv-btn" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/contact")}>
            Talk to us
          </button>
        </div>
      </div>
    </MarketingShell>
  );
}
