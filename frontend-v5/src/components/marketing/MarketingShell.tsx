/**
 * MarketingShell — shared nav + footer for the public marketing pages
 * (Product, For advisors, Pricing). Mirrors the Homepage nav design so the
 * full-bleed landing surface stays consistent across routes.
 */
import { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";

type NavKey = "product" | "advisors" | "pricing";

const NAV: Array<{ key: NavKey; label: string; to: string }> = [
  { key: "product", label: "Product", to: "/product" },
  { key: "advisors", label: "For advisors", to: "/for-advisors" },
  { key: "pricing", label: "Pricing", to: "/pricing" },
];

export default function MarketingShell({
  active,
  children,
}: {
  active?: NavKey;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  const isMobile = useIsMobile();

  return (
    <div className="nv-frame" style={{ width: "100%", minHeight: "100vh" }}>
      {/* nav */}
      <div style={{ display: "flex", alignItems: "center", padding: isMobile ? "14px 18px" : "20px 56px", borderBottom: "1px solid var(--line-2)" }}>
        <div onClick={() => navigate("/")} style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
          <span className="nv-mark" style={{ width: isMobile ? 28 : 32, height: isMobile ? 28 : 32, fontSize: isMobile ? 17 : 19 }}>न</span>
          <span className="nv-serif" style={{ fontSize: isMobile ? 19 : 22 }}>Nivesh</span>
          {!isMobile && (
            <span className="nv-mono" style={{ fontSize: 10, letterSpacing: ".18em", color: "var(--ink-3)", textTransform: "uppercase" as const, marginLeft: 6 }}>COPILOT</span>
          )}
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: isMobile ? 0 : 36 }}>
          {!isMobile && NAV.map((n) => (
            <span
              key={n.key}
              onClick={() => navigate(n.to)}
              style={{
                fontSize: 14,
                color: active === n.key ? "var(--ink)" : "var(--ink-2)",
                fontWeight: active === n.key ? 500 : 400,
                cursor: "pointer",
              }}
            >
              {n.label}
            </span>
          ))}
          {!isMobile && <span onClick={() => navigate("/login")} style={{ fontSize: 14, color: "var(--ink-2)", cursor: "pointer" }}>Sign in</span>}
          <button className="nv-btn nv-btn-primary" style={{ padding: isMobile ? "8px 14px" : "9px 16px", fontSize: 13, whiteSpace: "nowrap" }} onClick={() => navigate("/login")}>
            {isMobile ? "Check free →" : "Check my portfolio →"}
          </button>
        </div>
      </div>

      {children}

      {/* footer */}
      <div style={{ borderTop: "1px solid var(--line-2)", marginTop: 40 }}>
        <div style={{ maxWidth: 1280, margin: "0 auto", padding: isMobile ? "32px 20px" : "44px 56px", display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1.4fr 1fr 1fr 1fr", gap: isMobile ? 28 : 48 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span className="nv-mark" style={{ width: 30, height: 30, fontSize: 18 }}>न</span>
              <span className="nv-serif" style={{ fontSize: 21 }}>Nivesh</span>
            </div>
            <p style={{ fontSize: 13, color: "var(--ink-3)", lineHeight: 1.6, marginTop: 16, maxWidth: 280 }}>
              Your portfolio, finally legible. Read-only, SEBI-aligned analysis that
              tells you what to fix and why.
            </p>
            <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-4)", marginTop: 18, letterSpacing: ".06em" }}>
              ARN-128459 · IPS &amp; risk disclosure
            </div>
          </div>
          {[
            { h: "Product", items: ["Overview", "For advisors", "Pricing", "Sign in"], to: ["/product", "/for-advisors", "/pricing", "/login"] },
            { h: "Company", items: ["About", "Security", "Contact"], to: ["/about", "/security", "/contact"] },
            { h: "Legal", items: ["Privacy", "Terms", "Disclosure"], to: ["/privacy", "/terms", "/disclosure"] },
          ].map((col) => (
            <div key={col.h}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".16em", color: "var(--ink-4)", textTransform: "uppercase" as const }}>{col.h}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 18 }}>
                {col.items.map((it, i) => (
                  <span key={it} onClick={() => navigate(col.to[i])} style={{ fontSize: 13, color: "var(--ink-2)", cursor: "pointer" }}>{it}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div style={{ borderTop: "1px solid var(--line-2)" }}>
          <div style={{ maxWidth: 1280, margin: "0 auto", padding: isMobile ? "16px 20px" : "18px 56px", display: "flex", flexDirection: isMobile ? "column" : "row", alignItems: "center", justifyContent: "space-between", gap: isMobile ? 8 : 0, textAlign: isMobile ? "center" as const : undefined }}>
            <span className="nv-mono" style={{ fontSize: 11, color: "var(--ink-4)", letterSpacing: ".06em" }}>© 2026 Nivesh. All rights reserved.</span>
            <span className="nv-mono" style={{ fontSize: 11, color: "var(--ink-4)", letterSpacing: ".06em" }}>Made in India · Investments are subject to market risk.</span>
          </div>
        </div>
      </div>
    </div>
  );
}
