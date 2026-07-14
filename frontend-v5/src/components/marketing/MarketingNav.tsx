/**
 * MarketingNav — shared top nav for the public marketing surface (Homepage +
 * MarketingShell pages). On desktop it shows the full link row; on mobile it
 * collapses to a logo + CTA with a hamburger that opens the links in a panel,
 * so Product / For advisors / Pricing / Sign in stay reachable on a phone.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { useIsMobile } from "@/hooks/use-is-mobile";

type NavKey = "product" | "advisors" | "pricing";

const NAV: Array<{ key: NavKey; label: string; to: string }> = [
  { key: "product", label: "Product", to: "/product" },
  { key: "advisors", label: "For advisors", to: "/for-advisors" },
  { key: "pricing", label: "Pricing", to: "/pricing" },
];

export default function MarketingNav({ active }: { active?: NavKey }) {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [open, setOpen] = useState(false);

  const go = (to: string) => { setOpen(false); navigate(to); };

  return (
    <div style={{ borderBottom: "1px solid var(--line-2)" }}>
      <div style={{ display: "flex", alignItems: "center", padding: isMobile ? "14px 18px" : "20px 56px" }}>
        <div onClick={() => navigate("/")} style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
          <span className="nv-mark" style={{ width: isMobile ? 28 : 32, height: isMobile ? 28 : 32, fontSize: isMobile ? 17 : 19 }}>न</span>
          <span className="nv-serif" style={{ fontSize: isMobile ? 19 : 22 }}>Nivesh</span>
          {/* App name is "Nivesh Copilot" (matches the OAuth consent screen +
              niveshcopilot.com). Show the "Copilot" wordmark on every viewport
              — it used to be hidden on mobile, which read as just "Nivesh". */}
          <span className="nv-mono" style={{ fontSize: isMobile ? 9 : 10, letterSpacing: ".18em", color: "var(--ink-3)", textTransform: "uppercase" as const, marginLeft: 6 }}>COPILOT</span>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: isMobile ? 8 : 36 }}>
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
          {isMobile && (
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              aria-label={open ? "Close menu" : "Open menu"}
              aria-expanded={open}
              style={{ display: "grid", placeItems: "center", width: 36, height: 36, borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--ink-2)", cursor: "pointer", flexShrink: 0 }}
            >
              {open ? <X size={18} /> : <Menu size={18} />}
            </button>
          )}
        </div>
      </div>

      {/* mobile dropdown — in-flow so it never gets hidden behind the hero */}
      {isMobile && open && (
        <div style={{ borderTop: "1px solid var(--line-2)", background: "var(--bg-1)", padding: "6px 12px 12px", display: "flex", flexDirection: "column" }}>
          {NAV.map((n) => (
            <span
              key={n.key}
              onClick={() => go(n.to)}
              style={{
                padding: "13px 8px",
                fontSize: 15,
                color: active === n.key ? "var(--ink)" : "var(--ink-2)",
                fontWeight: active === n.key ? 500 : 400,
                cursor: "pointer",
                borderBottom: "1px solid var(--line-2)",
              }}
            >
              {n.label}
            </span>
          ))}
          <span onClick={() => go("/login")} style={{ padding: "13px 8px", fontSize: 15, color: "var(--ink-2)", cursor: "pointer" }}>Sign in</span>
        </div>
      )}
    </div>
  );
}
