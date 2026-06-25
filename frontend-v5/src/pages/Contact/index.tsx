/**
 * Contact — public marketing page. Uses real mailto channels rather than a
 * non-functional form (no backend submit endpoint exists), so nothing pretends
 * to send a message it can't.
 */
import { useNavigate } from "react-router-dom";
import MarketingShell from "@/components/marketing/MarketingShell";

const CHANNELS = [
  {
    tag: "SUPPORT",
    t: "General & support",
    d: "Questions about your portfolio, your account, or how Nivesh works.",
    email: "support@niveshcopilot.com",
    subject: "Support",
  },
  {
    tag: "ADVISORS",
    t: "For advisors",
    d: "Book a walkthrough on your own client book, or ask about Advisor pricing.",
    email: "support@niveshcopilot.com",
    subject: "Advisor demo",
  },
  {
    tag: "SECURITY",
    t: "Security",
    d: "Report a vulnerability or ask about how we handle your data.",
    email: "support@niveshcopilot.com",
    subject: "Security report",
  },
];

export default function ContactPage() {
  const navigate = useNavigate();
  return (
    <MarketingShell>
      {/* hero */}
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "80px 56px 32px", textAlign: "center" as const }}>
        <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--mint)", textTransform: "uppercase" as const }}>Contact</div>
        <h1 className="nv-serif" style={{ fontSize: 60, lineHeight: 1.0, letterSpacing: "-0.035em", margin: "14px 0 0" }}>
          Talk to us<span style={{ color: "var(--mint)" }}>.</span>
        </h1>
        <p style={{ fontSize: 19, lineHeight: 1.6, color: "var(--ink-2)", margin: "24px auto 0", maxWidth: 540 }}>
          We're a small team and we read everything. Pick the right channel below and
          we'll get back to you.
        </p>
      </div>

      {/* channel cards */}
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "24px 56px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
          {CHANNELS.map((c) => (
            <a
              key={c.tag}
              href={`mailto:${c.email}?subject=${encodeURIComponent(c.subject)}`}
              className="nv-card"
              style={{ padding: 28, textDecoration: "none", display: "block" }}
            >
              <span className="nv-pill nv-pill-mint">{c.tag}</span>
              <div className="nv-serif" style={{ fontSize: 24, letterSpacing: "-0.02em", marginTop: 16 }}>{c.t}</div>
              <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.6, marginTop: 10, minHeight: 64 }}>{c.d}</p>
              <span className="nv-mono" style={{ fontSize: 13, color: "var(--mint)" }}>{c.email} ›</span>
            </a>
          ))}
        </div>
      </div>

      {/* quick start band */}
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "40px 56px 16px" }}>
        <div className="nv-card-2" style={{ padding: "32px 40px", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" as const, gap: 20 }}>
          <div>
            <div className="nv-serif" style={{ fontSize: 26, letterSpacing: "-0.02em" }}>Just want to try it?</div>
            <p style={{ fontSize: 14, color: "var(--ink-2)", marginTop: 8, maxWidth: 420, lineHeight: 1.55 }}>
              You don't need to email us to get started — check your portfolio health for free.
            </p>
          </div>
          <button className="nv-btn nv-btn-primary" style={{ padding: "12px 18px", fontSize: 14 }} onClick={() => navigate("/login")}>
            Check my portfolio free
          </button>
        </div>
        <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-4)", marginTop: 24, letterSpacing: ".04em", textAlign: "center" as const }}>
          Made in India · SEBI-aligned · ARN-128459
        </div>
      </div>
    </MarketingShell>
  );
}
