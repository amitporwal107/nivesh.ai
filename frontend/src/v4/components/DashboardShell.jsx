/**
 * Shared chrome for all V4 dashboard screens.
 *
 * Renders the top-bar (brand + user pill + sign-out) and a sticky sub-nav
 * strip linking the 6 main dashboards. Screens wrap their content in this.
 */
import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { resetCurrentUser } from "../api/portfolioIngestion";

const NAV_ITEMS = [
  { label: "Copilot",       path: "/landing" },
  { label: "Concentration", path: "/concentration" },
  { label: "Diversification", path: "/diversification" },
  { label: "Risk",          path: "/risk" },
  { label: "Action Plan",   path: "/plan" },
  { label: "Goals",         path: "/goals" },
];

export function DashboardShell({ children }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();

  const handleSignOut = () => {
    logout().then(() => {
      resetCurrentUser();
      navigate("/", { replace: true });
    });
  };

  return (
    <div style={pageStyle}>
      {/* Top bar */}
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
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {user && (
            <div style={pillStyle}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--v4-moss)" }} />
              {user.email}
            </div>
          )}
          <button onClick={handleSignOut} style={signOutStyle} type="button">
            Sign out
          </button>
        </div>
      </header>

      {/* Sub-nav strip */}
      <nav style={subNavStyle}>
        {NAV_ITEMS.map(({ label, path }) => {
          const active = location.pathname === path || location.pathname.endsWith(path);
          return (
            <button
              key={path}
              type="button"
              onClick={() => navigate(path)}
              style={active ? { ...tabStyle, ...tabActiveStyle } : tabStyle}
            >
              {label}
            </button>
          );
        })}
      </nav>

      {/* Page body */}
      <main style={mainStyle}>{children}</main>
    </div>
  );
}

/* Shared helpers used by all dashboard screens */

export function SectionHeader({ children }) {
  return (
    <div style={sectionHeaderStyle}>
      {children}
      <span style={{ flex: 1, height: 1, background: "var(--v4-line)" }} />
    </div>
  );
}

export function StatTile({ label, value, sub, tone }) {
  return (
    <div style={statTileStyle}>
      <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1.4, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 26, color: tone || "var(--v4-ink)", lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontFamily: "var(--v4-mono)", fontSize: 10, color: "var(--v4-ink-faint)", marginTop: 4 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

export function EmptyState({ icon = "◌", title, sub }) {
  return (
    <div style={emptyStateStyle}>
      <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.3 }}>{icon}</div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 18, color: "var(--v4-ink-dim)", marginBottom: 6 }}>{title}</div>
      {sub && <div style={{ fontSize: 13, color: "var(--v4-ink-faint)", lineHeight: 1.5 }}>{sub}</div>}
    </div>
  );
}

export function Skeleton({ height = 80, radius = "var(--v4-r-md)" }) {
  return (
    <div
      style={{
        height,
        borderRadius: radius,
        background: "linear-gradient(90deg, var(--v4-s1) 0%, var(--v4-s2) 50%, var(--v4-s1) 100%)",
        backgroundSize: "200% 100%",
        animation: "v4-shimmer 1.4s ease infinite",
      }}
    />
  );
}

export function formatInr(n) {
  if (n == null || n === "") return "—";
  const v = typeof n === "number" ? n : Number(String(n).replace(/,/g, ""));
  if (!Number.isFinite(v)) return "—";
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  if (v >= 1e3) return `₹${(v / 1e3).toFixed(1)} K`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
}

/* ─── Styles ─── */

const pageStyle = { minHeight: "100vh", background: "var(--v4-bg)", color: "var(--v4-ink)" };

const navStyle = {
  display: "flex", alignItems: "center", justifyContent: "space-between",
  padding: "18px 32px", borderBottom: "1px solid var(--v4-line)",
  position: "sticky", top: 0, background: "rgba(11,10,8,0.94)",
  backdropFilter: "blur(10px)", zIndex: 20,
};

const brandStyle = { display: "flex", alignItems: "center", gap: 12 };

const markStyle = {
  width: 36, height: 36, borderRadius: 9,
  background: "linear-gradient(150deg, var(--v4-saffron), var(--v4-saffron-lo))",
  display: "grid", placeItems: "center",
  fontFamily: "var(--v4-display)", fontWeight: 600, color: "#2a1605", fontSize: 19,
};

const pillStyle = {
  fontFamily: "var(--v4-mono)", fontSize: 10, letterSpacing: 0.6,
  color: "var(--v4-ink-mute)", background: "var(--v4-s2)",
  border: "1px solid var(--v4-line)", padding: "6px 12px", borderRadius: 999,
  display: "flex", alignItems: "center", gap: 8, textTransform: "uppercase",
};

const signOutStyle = {
  fontFamily: "var(--v4-mono)", fontSize: 10, letterSpacing: 1,
  color: "var(--v4-ink-mute)", background: "transparent",
  border: "1px solid var(--v4-line)", padding: "8px 12px", borderRadius: 8,
  textTransform: "uppercase", cursor: "pointer",
};

const subNavStyle = {
  display: "flex", gap: 0, borderBottom: "1px solid var(--v4-line)",
  position: "sticky", top: 73, background: "rgba(11,10,8,0.94)",
  backdropFilter: "blur(8px)", zIndex: 19,
  padding: "0 32px", overflowX: "auto",
};

const tabStyle = {
  fontFamily: "var(--v4-mono)", fontSize: 10, letterSpacing: 1.2,
  color: "var(--v4-ink-faint)", background: "transparent", border: "none",
  borderBottom: "2px solid transparent", padding: "14px 18px",
  cursor: "pointer", textTransform: "uppercase", whiteSpace: "nowrap",
  transition: "color 0.2s, border-color 0.2s",
};

const tabActiveStyle = {
  color: "var(--v4-saffron)",
  borderBottomColor: "var(--v4-saffron)",
};

export const mainStyle = { maxWidth: 1080, margin: "0 auto", padding: "44px 32px 80px" };

const sectionHeaderStyle = {
  fontFamily: "var(--v4-mono)", fontSize: 10, letterSpacing: 1.6,
  color: "var(--v4-ink-faint)", textTransform: "uppercase",
  marginBottom: 14, display: "flex", alignItems: "center", gap: 10,
};

const statTileStyle = {
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-md)",
  padding: "20px 22px",
};

const emptyStateStyle = {
  textAlign: "center", padding: "60px 24px",
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-xl)",
};
