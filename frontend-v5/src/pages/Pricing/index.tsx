/**
 * Pricing — public marketing page.
 *
 * NOTE: Nivesh has no published price points yet. The tiers and amounts below
 * are PLACEHOLDER assumptions (INR) chosen to be reasonable and easy to edit —
 * update PLANS / COMPARISON before any public launch. The plan *features* map to
 * real platform capabilities (health score, Copilot, goals, tax, advisor book).
 */
import { useNavigate } from "react-router-dom";
import MarketingShell from "@/components/marketing/MarketingShell";

const PLANS = [
  {
    name: "Free",
    price: "₹0",
    cadence: "forever",
    blurb: "See your portfolio health and your top fixes.",
    cta: "Check my portfolio",
    to: "/login",
    highlight: false,
    features: [
      "Connect 1 portfolio (CAS or broker)",
      "Full A–D health grade",
      "Top 3 ranked actions",
      "Market Pulse daily read",
      "Read-only · no card needed",
    ],
  },
  {
    name: "Pro",
    price: "₹499",
    cadence: "per month",
    blurb: "The full copilot — every action, goal and tax move.",
    cta: "Start Pro",
    to: "/login",
    highlight: true,
    features: [
      "Everything in Free",
      "Unlimited portfolios & holdings",
      "Full ranked action plan + trade simulation",
      "Copilot chat across all lenses",
      "Goal-aware rebalancing",
      "Tax-loss harvesting (FIFO)",
    ],
  },
  {
    name: "Advisor",
    price: "Custom",
    cadence: "per seat",
    blurb: "Your whole client book, scored every night.",
    cta: "Book a demo",
    to: "/for-advisors",
    highlight: false,
    features: [
      "Everything in Pro",
      "Client roster with health grades",
      "At-risk alerts (drift / KYC / SIP)",
      "SIP & mandate tracking",
      "Client-ready reviews",
      "Priority support & onboarding",
    ],
  },
];

const COMPARISON: Array<{ label: string; free: string | boolean; pro: string | boolean; advisor: string | boolean }> = [
  { label: "Portfolios", free: "1", pro: "Unlimited", advisor: "Unlimited" },
  { label: "Health grade (A–D)", free: true, pro: true, advisor: true },
  { label: "Ranked actions", free: "Top 3", pro: "All", advisor: "All" },
  { label: "Trade simulation", free: false, pro: true, advisor: true },
  { label: "Copilot chat", free: "Limited", pro: "Unlimited", advisor: "Unlimited" },
  { label: "Goal-aware rebalancing", free: false, pro: true, advisor: true },
  { label: "Tax-loss harvesting", free: false, pro: true, advisor: true },
  { label: "Client roster & at-risk alerts", free: false, pro: false, advisor: true },
  { label: "SIP & mandate tracking", free: false, pro: false, advisor: true },
  { label: "Client-ready reviews", free: false, pro: false, advisor: true },
];

const FAQ = [
  { q: "Is my data safe?", a: "Access is read-only — we never place trades or move money. Statements are parsed in memory, encrypted in transit, and not warehoused." },
  { q: "Do I need a credit card to start?", a: "No. The Free plan needs no card. You only add payment if you upgrade to Pro." },
  { q: "Can I cancel anytime?", a: "Yes. Pro is month-to-month — cancel whenever and you keep access until the end of the billing period." },
  { q: "How is the Advisor plan priced?", a: "Per advisor seat, based on the size of your book. Book a demo and we'll scope it with you." },
];

function Cell({ v }: { v: string | boolean }) {
  if (v === true) return <span style={{ color: "var(--mint)", fontSize: 16 }}>✓</span>;
  if (v === false) return <span style={{ color: "var(--ink-4)", fontSize: 16 }}>—</span>;
  return <span style={{ fontSize: 13, color: "var(--ink-2)" }}>{v}</span>;
}

export default function PricingPage() {
  const navigate = useNavigate();

  return (
    <MarketingShell active="pricing">
      {/* hero */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "80px 56px 32px", textAlign: "center" as const }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 10, padding: "6px 14px 6px 8px", borderRadius: 999, border: "1px solid var(--line-2)", background: "var(--bg-1)", marginBottom: 28 }}>
          <span style={{ background: "var(--mint-soft)", color: "var(--mint)", fontSize: 10, fontFamily: "var(--mono)", letterSpacing: ".1em", padding: "3px 8px", borderRadius: 999, textTransform: "uppercase" as const }}>PRICING</span>
          <span style={{ fontSize: 13, color: "var(--ink-2)" }}>Start free · upgrade when it pays off</span>
        </div>
        <h1 className="nv-serif" style={{ fontSize: 64, lineHeight: 0.98, letterSpacing: "-0.035em", margin: 0 }}>
          Simple pricing<span style={{ color: "var(--mint)" }}>.</span>
        </h1>
        <p style={{ fontSize: 18, lineHeight: 1.55, color: "var(--ink-2)", margin: "22px auto 0", maxWidth: 520 }}>
          See your portfolio health for free. Upgrade when you want the full plan of
          action — or run your whole client book on Advisor.
        </p>
      </div>

      {/* plan cards */}
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "16px 56px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, alignItems: "stretch" }}>
          {PLANS.map((p) => (
            <div
              key={p.name}
              className="nv-card"
              style={{
                padding: 32,
                display: "flex",
                flexDirection: "column",
                position: "relative" as const,
                border: p.highlight ? "1px solid rgb(var(--pos) / 0.45)" : undefined,
                boxShadow: p.highlight ? "0 1px 0 rgb(255 255 255 / 0.04) inset, 0 24px 48px -24px rgb(0 0 0 / 0.6), 0 0 0 1px rgb(var(--pos) / 0.18)" : undefined,
              }}
            >
              {p.highlight && (
                <span className="nv-pill nv-pill-mint" style={{ position: "absolute" as const, top: -12, left: 32 }}>MOST POPULAR</span>
              )}
              <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--ink-3)", textTransform: "uppercase" as const }}>{p.name}</div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 12 }}>
                <span className="nv-serif" style={{ fontSize: 52, letterSpacing: "-0.04em", lineHeight: 1 }}>{p.price}</span>
                <span className="nv-mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>{p.cadence}</span>
              </div>
              <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.55, marginTop: 14, minHeight: 44 }}>{p.blurb}</p>
              <button
                className={p.highlight ? "nv-btn nv-btn-primary" : "nv-btn"}
                style={{ padding: "12px 18px", fontSize: 14, marginTop: 4, justifyContent: "center" }}
                onClick={() => navigate(p.to)}
              >
                {p.cta}
              </button>
              <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 24, paddingTop: 24, borderTop: "1px solid rgb(var(--line) / 0.06)" }}>
                {p.features.map((f) => (
                  <div key={f} style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                    <span style={{ color: "var(--mint)", fontSize: 14, lineHeight: 1.4 }}>✓</span>
                    <span style={{ fontSize: 13, color: "var(--ink-2)", lineHeight: 1.4 }}>{f}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* comparison table */}
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "48px 56px" }}>
        <div style={{ textAlign: "center" as const, marginBottom: 28 }}>
          <h2 className="nv-serif" style={{ fontSize: 36, letterSpacing: "-0.03em", margin: 0 }}>Compare plans</h2>
        </div>
        <div className="nv-card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr 1fr 1fr", padding: "16px 24px", borderBottom: "1px solid rgb(var(--line) / 0.06)", background: "var(--bg-2)" }}>
            <span className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", letterSpacing: ".1em", textTransform: "uppercase" as const }}>Feature</span>
            {["Free", "Pro", "Advisor"].map((h) => (
              <span key={h} className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", letterSpacing: ".1em", textTransform: "uppercase" as const, textAlign: "center" as const }}>{h}</span>
            ))}
          </div>
          {COMPARISON.map((row, i) => (
            <div key={row.label} style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr 1fr 1fr", padding: "14px 24px", borderBottom: i < COMPARISON.length - 1 ? "1px solid rgb(var(--line) / 0.06)" : "none", alignItems: "center" }}>
              <span style={{ fontSize: 14, color: "var(--ink)" }}>{row.label}</span>
              <span style={{ textAlign: "center" as const }}><Cell v={row.free} /></span>
              <span style={{ textAlign: "center" as const }}><Cell v={row.pro} /></span>
              <span style={{ textAlign: "center" as const }}><Cell v={row.advisor} /></span>
            </div>
          ))}
        </div>
        <div className="nv-mono" style={{ fontSize: 10, color: "var(--ink-4)", marginTop: 12, letterSpacing: ".06em", textAlign: "center" as const }}>
          Indicative pricing — final plans and amounts may change before launch.
        </div>
      </div>

      {/* FAQ */}
      <div style={{ maxWidth: 860, margin: "0 auto", padding: "32px 56px" }}>
        <div style={{ textAlign: "center" as const, marginBottom: 28 }}>
          <h2 className="nv-serif" style={{ fontSize: 36, letterSpacing: "-0.03em", margin: 0 }}>Questions</h2>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {FAQ.map((f) => (
            <div key={f.q} className="nv-card" style={{ padding: 24 }}>
              <div style={{ fontSize: 16, fontWeight: 500 }}>{f.q}</div>
              <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.6, marginTop: 8 }}>{f.a}</p>
            </div>
          ))}
        </div>
      </div>

      {/* CTA */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "24px 56px 16px", textAlign: "center" as const }}>
        <h2 className="nv-serif" style={{ fontSize: 44, letterSpacing: "-0.03em", margin: 0 }}>Start with the free grade.</h2>
        <p style={{ fontSize: 16, color: "var(--ink-2)", margin: "14px auto 0", maxWidth: 440 }}>
          No card. Read-only. Two minutes to your first plan of action.
        </p>
        <div style={{ display: "flex", gap: 12, marginTop: 32, justifyContent: "center" }}>
          <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
            Check my portfolio free
          </button>
        </div>
      </div>
    </MarketingShell>
  );
}
