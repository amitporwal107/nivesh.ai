import React from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

/**
 * V4 Homepage — public marketing landing. No API calls; auth lives downstream.
 * Faithful to the V4 mockup (nivesh_app.html `s-home` screen).
 *
 * Behaviour:
 *  - Signed-out visitors see "Sign in" / "Check my portfolio free" → /onboarding
 *    (which exposes the Google sign-in card).
 *  - Signed-in visitors see "Open app" / "Open my portfolio" → /onboarding
 *    (which detects the active snapshot and routes to the cockpit, or shows
 *    a refresh prompt if the snapshot is stale).
 */
export default function Homepage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isSignedIn = !!user;

  const primaryCtaLabel = isSignedIn ? "Open my portfolio →" : "Check my portfolio free →";
  const navCtaLabel = isSignedIn ? "Open app" : "Sign in";

  return (
    <div style={pageStyle}>
      <header style={navStyle}>
        <div style={brandStyle}>
          <div style={markStyle}>न</div>
          <div>
            <div style={{ fontFamily: "var(--v4-display)", fontWeight: 600, fontSize: 17, color: "var(--v4-ink)" }}>
              Nivesh
            </div>
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1.4, color: "var(--v4-ink-faint)" }}>
              AI COPILOT
            </div>
          </div>
        </div>
        <nav style={navLinksStyle}>
          <a href="#product" style={navLinkStyle}>Product</a>
          <a href="#advisors" style={navLinkStyle}>For advisors</a>
          <button style={signInBtnStyle} onClick={() => navigate("/onboarding")}>
            {navCtaLabel}
          </button>
        </nav>
      </header>

      <main style={mainStyle}>
        <div style={eyebrowStyle}>BUILT FOR INDIAN INVESTORS</div>
        <h1 style={heroStyle}>
          Know exactly how healthy<br />
          your <em style={{ color: "var(--v4-saffron)", fontStyle: "italic" }}>portfolio</em> is.
        </h1>
        <p style={subheadStyle}>
          Skip the spreadsheets. We read your CAS or Gmail and answer real
          questions about what you own.
        </p>

        <div style={ctaRowStyle}>
          <button style={ctaPrimaryStyle} onClick={() => navigate("/onboarding")}>
            {primaryCtaLabel}
          </button>
          <button style={ctaGhostStyle} onClick={() => document.getElementById("how-it-works")?.scrollIntoView({ behavior: "smooth" })}>
            See how it works
          </button>
        </div>

        <div style={complianceStyle}>
          No card needed · SEBI-aligned · numbers grounded in your data
        </div>

        <section id="how-it-works" style={tilesSectionStyle}>
          <FeatureTile
            icon="📥"
            title="Import in seconds"
            body="Gmail finds your CAS; we read it. No file, no password."
          />
          <FeatureTile
            icon="✓"
            title="A real health score"
            body="Concentration, risk, diversification — scored like a pro."
          />
          <FeatureTile
            icon="→"
            title="Know what to do"
            body="Ranked actions with the impact each one would have."
          />
        </section>

        <SampleScoreTeaser onClick={() => navigate("/onboarding")} />
      </main>

      <footer style={footerStyle}>
        <span>© Nivesh AI</span>
        <span style={{ opacity: 0.6 }}>·</span>
        <a href="/privacy" style={navLinkStyle}>Privacy</a>
      </footer>
    </div>
  );
}

function FeatureTile({ icon, title, body }) {
  return (
    <div style={tileStyle}>
      <div style={tileIconStyle}>{icon}</div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 17, color: "var(--v4-ink)", marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 13, color: "var(--v4-ink-mute)", lineHeight: 1.5 }}>{body}</div>
    </div>
  );
}

function SampleScoreTeaser({ onClick }) {
  return (
    <div style={teaserStyle} onClick={onClick} role="button" tabIndex={0}>
      <div style={teaserGaugeWrap}>
        <svg viewBox="0 0 80 80" style={{ width: 110, height: 110 }}>
          <circle cx="40" cy="40" r="34" stroke="var(--v4-line-strong)" strokeWidth="6" fill="none" />
          <circle
            cx="40"
            cy="40"
            r="34"
            stroke="var(--v4-moss)"
            strokeWidth="6"
            fill="none"
            strokeDasharray={`${(86 / 100) * 213.6} 213.6`}
            strokeLinecap="round"
            transform="rotate(-90 40 40)"
          />
          <text x="40" y="46" textAnchor="middle" fontFamily="var(--v4-display)" fontSize="22" fontWeight="600" fill="var(--v4-ink)">
            86
          </text>
        </svg>
      </div>
      <div>
        <div style={teaserEyebrowStyle}>SAMPLE · PORTFOLIO HEALTH</div>
        <div style={teaserHeadlineStyle}>Grade A — Healthy</div>
        <div style={teaserSubStyle}>
          "Your portfolio is healthy — but financials are over-concentrated."
        </div>
        <div style={teaserCtaStyle}>See your own score →</div>
      </div>
    </div>
  );
}

/* ───────── inline styles (kept here to avoid scattering a tiny stylesheet) ───────── */

const pageStyle = {
  minHeight: "100vh",
  background: "var(--v4-bg)",
  color: "var(--v4-ink)",
  position: "relative",
  overflow: "hidden",
};

const navStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  padding: "18px 32px",
  borderBottom: "1px solid var(--v4-line)",
  position: "sticky",
  top: 0,
  background: "rgba(11,10,8,0.92)",
  backdropFilter: "blur(10px)",
  zIndex: 20,
};

const brandStyle = { display: "flex", alignItems: "center", gap: 12 };

const markStyle = {
  width: 36,
  height: 36,
  borderRadius: 9,
  background: "linear-gradient(150deg, var(--v4-saffron), var(--v4-saffron-lo))",
  display: "grid",
  placeItems: "center",
  fontFamily: "var(--v4-display)",
  fontWeight: 600,
  color: "#2a1605",
  fontSize: 19,
};

const navLinksStyle = { display: "flex", alignItems: "center", gap: 22 };

const navLinkStyle = {
  fontSize: 13,
  color: "var(--v4-ink-dim)",
  cursor: "pointer",
};

const signInBtnStyle = {
  fontSize: 13,
  fontWeight: 500,
  color: "var(--v4-ink)",
  background: "var(--v4-s2)",
  border: "1px solid var(--v4-line)",
  padding: "8px 14px",
  borderRadius: 9,
};

const mainStyle = {
  maxWidth: 920,
  margin: "0 auto",
  padding: "80px 32px 60px",
  textAlign: "center",
};

const eyebrowStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 9,
  letterSpacing: 1.8,
  color: "var(--v4-saffron)",
  textTransform: "uppercase",
  marginBottom: 22,
};

const heroStyle = {
  fontFamily: "var(--v4-display)",
  fontWeight: 500,
  fontSize: "clamp(36px, 6vw, 64px)",
  lineHeight: 1.05,
  letterSpacing: "-0.01em",
  marginBottom: 22,
};

const subheadStyle = {
  fontSize: 17,
  color: "var(--v4-ink-dim)",
  lineHeight: 1.55,
  maxWidth: 560,
  margin: "0 auto 32px",
};

const ctaRowStyle = {
  display: "flex",
  gap: 12,
  justifyContent: "center",
  flexWrap: "wrap",
  marginBottom: 18,
};

const ctaPrimaryStyle = {
  fontSize: 14,
  fontWeight: 600,
  background: "linear-gradient(150deg, var(--v4-saffron), var(--v4-saffron-dk))",
  color: "#2a1605",
  padding: "13px 24px",
  borderRadius: 10,
};

const ctaGhostStyle = {
  fontSize: 14,
  fontWeight: 500,
  background: "var(--v4-s2)",
  color: "var(--v4-ink-dim)",
  border: "1px solid var(--v4-line)",
  padding: "13px 24px",
  borderRadius: 10,
};

const complianceStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 10,
  letterSpacing: 1.2,
  color: "var(--v4-ink-faint)",
  textTransform: "uppercase",
  marginBottom: 80,
};

const tilesSectionStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
  gap: 18,
  marginBottom: 60,
  textAlign: "left",
};

const tileStyle = {
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-lg)",
  padding: "22px 20px",
};

const tileIconStyle = {
  width: 36,
  height: 36,
  borderRadius: 9,
  background: "var(--v4-s3)",
  display: "grid",
  placeItems: "center",
  fontSize: 18,
  marginBottom: 14,
};

const teaserStyle = {
  background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))",
  border: "1px solid var(--v4-line-strong)",
  borderRadius: "var(--v4-r-xl)",
  padding: "26px 26px",
  display: "grid",
  gridTemplateColumns: "auto 1fr",
  gap: 22,
  alignItems: "center",
  textAlign: "left",
  cursor: "pointer",
  transition: "transform .15s var(--v4-ease)",
};

const teaserGaugeWrap = { display: "grid", placeItems: "center" };

const teaserEyebrowStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 9,
  letterSpacing: 1.4,
  color: "var(--v4-ink-faint)",
  marginBottom: 6,
};

const teaserHeadlineStyle = {
  fontFamily: "var(--v4-display)",
  fontSize: 22,
  color: "var(--v4-ink)",
  marginBottom: 8,
};

const teaserSubStyle = {
  fontSize: 13,
  color: "var(--v4-ink-dim)",
  lineHeight: 1.55,
  marginBottom: 12,
};

const teaserCtaStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 10,
  letterSpacing: 1.2,
  color: "var(--v4-saffron)",
  textTransform: "uppercase",
};

const footerStyle = {
  borderTop: "1px solid var(--v4-line)",
  padding: "18px 32px",
  display: "flex",
  gap: 10,
  alignItems: "center",
  justifyContent: "center",
  fontSize: 12,
  color: "var(--v4-ink-mute)",
};
