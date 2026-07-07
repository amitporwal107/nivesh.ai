/**
 * Copilot — the full interactive product tour (/copilot).
 *
 * Ports the eight-section "Nivesh Copilot — Complete" design reference into a
 * public marketing route:
 *   Overview · Principles · Screens (6-stage flow) · Workflows ·
 *   All flows · Advisor book · Mobile.
 *
 * Rendered outside the app shell (public surface). The whole page is pinned to
 * the DARK palette via the `.copilot-tour` wrapper (the design is dark-first),
 * scoped so nothing leaks into the rest of the app.
 *
 * Note: we render MarketingNav directly rather than MarketingShell so the
 * section sub-nav can be `position: sticky` — MarketingShell wraps children in
 * `.nv-frame` (overflow: hidden), which would trap the sticky element.
 */
import { useNavigate } from "react-router-dom";
import MarketingNav from "@/components/marketing/MarketingNav";
import { useIsMobile } from "@/hooks/use-is-mobile";
import { Mark } from "./parts";
import Overview from "./sections/Overview";
import Principles from "./sections/Principles";
import AdvisoryFlow from "./sections/AdvisoryFlow";
import Workflows from "./sections/Workflows";
import AllFlows from "./sections/AllFlows";
import Advisor from "./sections/Advisor";
import Mobile from "./sections/Mobile";
import "./copilot.css";

const SUBNAV: Array<{ label: string; href: string }> = [
  { label: "Overview", href: "#ct-overview" },
  { label: "Principles", href: "#ct-principles" },
  { label: "Screens", href: "#ct-screens" },
  { label: "Workflows", href: "#ct-workflows" },
  { label: "All flows", href: "#ct-allflows" },
  { label: "Advisor", href: "#ct-advisor" },
  { label: "Mobile", href: "#ct-mobile" },
];

const FOOTER_LINKS: Array<[string, string]> = [
  ["Product", "/product"],
  ["For advisors", "/for-advisors"],
  ["Pricing", "/pricing"],
  ["Sign in", "/login"],
];

export default function CopilotPage() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();

  return (
    <div className="copilot-tour">
      <MarketingNav active="product" />

      {/* sticky section sub-nav */}
      <nav className="ct-subnav" aria-label="Tour sections">
        {SUBNAV.map((s) => (
          <a key={s.href} href={s.href}>
            {s.label}
          </a>
        ))}
      </nav>

      <Overview />
      <Principles />
      <AdvisoryFlow />
      <Workflows />
      <AllFlows />
      <Advisor />
      <Mobile />

      {/* closing CTA */}
      <div style={{ padding: isMobile ? "20px 18px 8px" : "40px 56px 16px", textAlign: "center" }}>
        <div className="nv-eyebrow" style={{ marginBottom: 10 }}>SEE IT ON YOUR OWN PORTFOLIO</div>
        <h2 className="nv-serif" style={{ margin: 0, fontSize: isMobile ? 32 : 46, letterSpacing: "-0.03em", lineHeight: 1.03 }}>
          One AI. Your <span style={{ color: "var(--mint)" }}>whole</span> portfolio.
        </h2>
        <p className="nv-prose" style={{ margin: "14px auto 0", maxWidth: 460 }}>
          Connect once and get the same grounded read on everything you actually hold — the one thing to fix first, ranked by impact.
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 32, justifyContent: "center" }}>
          <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
            Check my portfolio free
          </button>
          <button className="nv-btn" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/product")}>
            Back to product
          </button>
        </div>
      </div>

      {/* footer */}
      <div style={{ borderTop: "1px solid var(--line-2)", marginTop: 48 }}>
        <div style={{ maxWidth: 1280, margin: "0 auto", padding: isMobile ? "28px 20px" : "40px 56px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <Mark size={30} fontSize={18} />
            <div>
              <div className="nv-serif" style={{ fontSize: 20 }}>Nivesh Copilot</div>
              <div className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-4))", letterSpacing: ".06em", marginTop: 2 }}>EDUCATIONAL · NOT INVESTMENT ADVICE · READ-ONLY</div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
            {FOOTER_LINKS.map(([label, to]) => (
              <span key={label} onClick={() => navigate(to)} style={{ fontSize: 13, color: "rgb(var(--ink-2))", cursor: "pointer" }}>{label}</span>
            ))}
          </div>
        </div>
        <div style={{ borderTop: "1px solid var(--line-2)" }}>
          <div style={{ maxWidth: 1280, margin: "0 auto", padding: isMobile ? "16px 20px" : "18px 56px", display: "flex", flexDirection: isMobile ? "column" : "row", alignItems: "center", justifyContent: "space-between", gap: isMobile ? 8 : 0, textAlign: isMobile ? "center" : undefined }}>
            <span className="nv-mono" style={{ fontSize: 11, color: "rgb(var(--ink-4))", letterSpacing: ".06em" }}>© 2026 Nivesh. All rights reserved.</span>
            <span className="nv-mono" style={{ fontSize: 11, color: "rgb(var(--ink-4))", letterSpacing: ".06em" }}>Made in India · Investments are subject to market risk.</span>
          </div>
        </div>
      </div>
    </div>
  );
}
