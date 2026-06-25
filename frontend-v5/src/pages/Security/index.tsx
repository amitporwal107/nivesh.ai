/**
 * Security — public marketing page. User-facing security commitments only,
 * grounded in how the product works (read-only access, scoped Gmail, encryption,
 * no statement warehousing). Does not expose internal infrastructure details.
 */
import { useNavigate } from "react-router-dom";
import MarketingShell from "@/components/marketing/MarketingShell";

const COMMITMENTS = [
  { t: "Read-only access", d: "Nivesh can read your portfolio to analyse it — never trade, transfer, or move money. There is no write path to your accounts." },
  { t: "Scoped Gmail permission", d: "If you connect Gmail, access is read-only and limited to finding CAS statements. We never send mail or read anything else in your inbox." },
  { t: "Encrypted in transit", d: "All connections use TLS. Statements are parsed and encrypted in transit, not left exposed." },
  { t: "No statement warehousing", d: "We extract the holdings we need and don't hoard your raw statement files beyond what's required to process them." },
  { t: "You stay in control", d: "Revoke any connected account or delete your data at any time, from the app or your Google account." },
  { t: "Least-privilege infrastructure", d: "Access to systems is restricted and audited; we follow least-privilege principles for the people and services that run Nivesh." },
];

export default function SecurityPage() {
  const navigate = useNavigate();
  return (
    <MarketingShell>
      {/* hero */}
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "80px 56px 32px", textAlign: "center" as const }}>
        <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--mint)", textTransform: "uppercase" as const }}>Security</div>
        <h1 className="nv-serif" style={{ fontSize: 60, lineHeight: 1.0, letterSpacing: "-0.035em", margin: "14px 0 0" }}>
          Read-only by design<span style={{ color: "var(--mint)" }}>.</span>
        </h1>
        <p style={{ fontSize: 19, lineHeight: 1.6, color: "var(--ink-2)", margin: "24px auto 0", maxWidth: 580 }}>
          Nivesh is built to understand your portfolio without ever being able to touch it.
          Here's how we keep your data safe and in your control.
        </p>
      </div>

      {/* commitments grid */}
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 56px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
          {COMMITMENTS.map((c) => (
            <div key={c.t} className="nv-card" style={{ padding: 26 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--mint)" }} />
                <span className="nv-serif" style={{ fontSize: 20, letterSpacing: "-0.02em" }}>{c.t}</span>
              </div>
              <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.6, marginTop: 12 }}>{c.d}</p>
            </div>
          ))}
        </div>
      </div>

      {/* report band */}
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "40px 56px 16px" }}>
        <div className="nv-card-2" style={{ padding: "32px 40px", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" as const, gap: 20 }}>
          <div>
            <div className="nv-serif" style={{ fontSize: 26, letterSpacing: "-0.02em" }}>Found something?</div>
            <p style={{ fontSize: 14, color: "var(--ink-2)", marginTop: 8, maxWidth: 460, lineHeight: 1.55 }}>
              We take security reports seriously. If you believe you've found a vulnerability,
              please disclose it responsibly and we'll respond quickly.
            </p>
          </div>
          <a href="mailto:support@niveshcopilot.com?subject=Security%20report" className="nv-btn nv-btn-primary" style={{ padding: "12px 18px", fontSize: 14, textDecoration: "none" }}>
            Report a vulnerability
          </a>
        </div>
        <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-4)", marginTop: 24, letterSpacing: ".04em", textAlign: "center" as const }}>
          Read-only · Encrypted · SEBI-aligned · ARN-128459 ·{" "}
          <span onClick={() => navigate("/privacy")} style={{ color: "var(--mint)", cursor: "pointer" }}>Privacy</span>
        </div>
      </div>
    </MarketingShell>
  );
}
