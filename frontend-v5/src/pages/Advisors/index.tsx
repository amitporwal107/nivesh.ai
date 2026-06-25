/**
 * For Advisors — public marketing page for RIAs / MFDs.
 * Content grounded in the advisor dashboard prototype (design/screens-advisor-2.jsx):
 * client roster with health grades, at-risk surfacing (drift / KYC / stale SIP),
 * AUM book and SIP/mandate tracking. Full-bleed, no sidebar.
 */
import { useNavigate } from "react-router-dom";
import MarketingShell from "@/components/marketing/MarketingShell";

const STATS = [
  { v: "87", s: "clients", l: "Under advice on one screen", c: "var(--ink)" },
  { v: "₹64 Cr", s: "AUM", l: "Reconciled and graded daily", c: "var(--ink)" },
  { v: "4", s: "at-risk", l: "Surfaced before the client calls", c: "var(--amber)" },
  { v: "148", s: "SIPs", l: "Mandates and renewals tracked", c: "var(--mint)" },
];

const CAPABILITIES = [
  {
    tag: "ROSTER",
    t: "Every client, graded daily",
    d: "One roster with each client's portfolio health, AUM and return. Sort by what needs attention instead of scrolling through statements.",
  },
  {
    tag: "AT-RISK",
    t: "Problems surface before they're calls",
    d: "Allocation drift, stale or missed SIPs, expiring KYC and concentration breaches are flagged automatically — so you reach out first.",
  },
  {
    tag: "SIP BOOK",
    t: "The whole SIP book in view",
    d: "Volume, top-ups, renewals and failed mandates (NACH bounces, expired mandates) in one place, with tomorrow's schedule ready.",
  },
  {
    tag: "REPORTS",
    t: "Client-ready reviews in one tap",
    d: "Turn the same plain-language analysis your clients trust into a review you can send before every meeting — no spreadsheet assembly.",
  },
];

const WORKFLOW = [
  { n: "01", t: "Bring your book", d: "Clients connect read-only via CAS or broker, or you onboard from statements. Holdings reconcile to the rupee." },
  { n: "02", t: "Let it watch", d: "Nivesh scores every portfolio nightly and flags drift, risk, cost and tax issues across your whole book." },
  { n: "03", t: "Act and advise", d: "Open any client to a ranked action plan, simulate the trade-offs, and send a client-ready review." },
];

export default function AdvisorsPage() {
  const navigate = useNavigate();

  return (
    <MarketingShell active="advisors">
      {/* hero */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "80px 56px 40px", display: "grid", gridTemplateColumns: "1.05fr 1fr", gap: 72, alignItems: "center" }}>
        <div>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 10, padding: "6px 14px 6px 8px", borderRadius: 999, border: "1px solid var(--line-2)", background: "var(--bg-1)", marginBottom: 28 }}>
            <span style={{ background: "var(--indigo-soft)", color: "var(--indigo-hex)", fontSize: 10, fontFamily: "var(--mono)", letterSpacing: ".1em", padding: "3px 8px", borderRadius: 999, textTransform: "uppercase" as const }}>FOR ADVISORS</span>
            <span style={{ fontSize: 13, color: "var(--ink-2)" }}>RIAs &amp; MFDs</span>
          </div>
          <h1 className="nv-serif" style={{ fontSize: 68, lineHeight: 0.98, letterSpacing: "-0.035em", margin: 0 }}>
            Advise more clients,<br />
            <span style={{ fontStyle: "italic" }}>miss</span> nothing<span style={{ color: "var(--mint)" }}>.</span>
          </h1>
          <p style={{ fontSize: 19, lineHeight: 1.55, color: "var(--ink-2)", marginTop: 28, maxWidth: 480 }}>
            Nivesh scores your entire book every night and surfaces the handful of clients
            who need you today — drift, stale SIPs, expiring KYC, concentration — before
            they ever pick up the phone.
          </p>
          <div style={{ display: "flex", gap: 12, marginTop: 40 }}>
            <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
              Book a demo
            </button>
            <button className="nv-btn" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/pricing")}>
              See advisor pricing
            </button>
          </div>
        </div>

        {/* at-risk preview card — mirrors the advisor dashboard prototype */}
        <div className="nv-card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "18px 22px", borderBottom: "1px solid rgb(var(--line) / 0.06)", display: "flex", alignItems: "center", gap: 12 }}>
            <span className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", letterSpacing: ".08em" }}>nivesh.app/advisor</span>
            <span className="nv-pill nv-pill-danger" style={{ marginLeft: "auto" }}>
              <span className="nv-dot" style={{ background: "var(--danger-hex)" }} />
              AT-RISK · 4
            </span>
          </div>
          <div style={{ padding: "22px 24px" }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".16em", color: "var(--ink-3)", textTransform: "uppercase" as const }}>Needs attention today</div>
            <div style={{ marginTop: 14 }}>
              {[
                { n: "D. Rao", a: "₹62 L", w: "Allocation drift · 11pt", sev: "amber" },
                { n: "K. Verma", a: "₹96 L", w: "Stale SIP · 4 missed", sev: "amber" },
                { n: "M. Tandon", a: "₹54 L", w: "Concentration · 41%", sev: "danger" },
                { n: "B. Sen", a: "₹36 L", w: "KYC expiring", sev: "amber" },
              ].map((r, i) => (
                <div key={r.n} style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 2px", borderBottom: i < 3 ? "1px solid rgb(var(--line) / 0.06)" : "none" }}>
                  <span style={{ width: 3, alignSelf: "stretch", background: r.sev === "danger" ? "var(--danger-hex)" : "var(--amber)", borderRadius: 2 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>{r.n}</div>
                    <div className="nv-mono" style={{ fontSize: 10, color: "var(--ink-3)", marginTop: 3, letterSpacing: ".04em" }}>{r.w}</div>
                  </div>
                  <span className="nv-mono" style={{ fontSize: 12, color: "var(--ink-2)" }}>{r.a}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* stat band */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "24px 56px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 1, background: "rgb(var(--line) / 0.06)", border: "1px solid rgb(var(--line) / 0.06)", borderRadius: 18, overflow: "hidden" }}>
          {STATS.map((s) => (
            <div key={s.s} style={{ padding: 28, background: "var(--bg-1)" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                <span className="nv-serif" style={{ fontSize: 40, letterSpacing: "-0.035em", color: s.c }}>{s.v}</span>
                <span className="nv-mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>{s.s}</span>
              </div>
              <p style={{ fontSize: 13, color: "var(--ink-2)", marginTop: 8, lineHeight: 1.5 }}>{s.l}</p>
            </div>
          ))}
        </div>
        <div className="nv-mono" style={{ fontSize: 10, color: "var(--ink-4)", marginTop: 12, letterSpacing: ".06em", textAlign: "center" as const }}>
          Illustrative figures from a sample advisor book.
        </div>
      </div>

      {/* capabilities */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "48px 56px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 16 }}>
          {CAPABILITIES.map((f) => (
            <div key={f.tag} className="nv-card" style={{ padding: 32 }}>
              <span className="nv-pill nv-pill-indigo">{f.tag}</span>
              <div className="nv-serif" style={{ fontSize: 28, letterSpacing: "-0.02em", marginTop: 18 }}>{f.t}</div>
              <p style={{ fontSize: 15, color: "var(--ink-2)", lineHeight: 1.6, marginTop: 12, maxWidth: 440 }}>{f.d}</p>
            </div>
          ))}
        </div>
      </div>

      {/* workflow */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "32px 56px" }}>
        <div style={{ textAlign: "center" as const, marginBottom: 40 }}>
          <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--ink-3)", textTransform: "uppercase" as const }}>How it works</div>
          <h2 className="nv-serif" style={{ fontSize: 42, letterSpacing: "-0.03em", margin: "10px 0 0" }}>From book to action in three steps.</h2>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
          {WORKFLOW.map((w) => (
            <div key={w.n} className="nv-card" style={{ padding: 28 }}>
              <div className="nv-mono" style={{ fontSize: 11, color: "var(--mint)", letterSpacing: ".1em" }}>{w.n}</div>
              <div className="nv-serif" style={{ fontSize: 24, marginTop: 14, letterSpacing: "-0.02em" }}>{w.t}</div>
              <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.55, marginTop: 10 }}>{w.d}</p>
            </div>
          ))}
        </div>
      </div>

      {/* CTA */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "48px 56px 16px" }}>
        <div className="nv-card-2" style={{ padding: "48px 56px", textAlign: "center" as const }}>
          <h2 className="nv-serif" style={{ fontSize: 44, letterSpacing: "-0.03em", margin: 0 }}>Put your whole book on one screen.</h2>
          <p style={{ fontSize: 16, color: "var(--ink-2)", margin: "14px auto 0", maxWidth: 480 }}>
            See a live walkthrough on your own client data. No commitment, read-only access.
          </p>
          <div style={{ display: "flex", gap: 12, marginTop: 32, justifyContent: "center" }}>
            <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
              Book a demo
            </button>
            <button className="nv-btn" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/pricing")}>
              See pricing
            </button>
          </div>
        </div>
      </div>
    </MarketingShell>
  );
}
