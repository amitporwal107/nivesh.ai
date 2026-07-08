/**
 * MarketingShell — shared nav + footer for the public marketing pages
 * (Product, For advisors, Pricing). Mirrors the Homepage nav design so the
 * full-bleed landing surface stays consistent across routes.
 */
import { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";
import MarketingNav from "./MarketingNav";

type NavKey = "product" | "advisors" | "pricing";

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
      <MarketingNav active={active} />

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
            { h: "Company", items: ["About", "Blog", "Security", "Contact"], to: ["/about", "/blog", "/security", "/contact"] },
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
