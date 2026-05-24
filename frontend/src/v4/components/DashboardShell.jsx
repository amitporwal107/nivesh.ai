/**
 * V4 shared shell for all dashboard screens.
 *
 * Layout: fixed left sidebar (240 px) + right content column.
 * Props:  title, badge, badgeTone — rendered in the sticky topnav.
 * Mobile: sidebar hidden; topnav shows ‹ back + ← Chat only.
 */
import React, { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { resetCurrentUser } from "../api/portfolioIngestion";

const NAV_ITEMS = [
  { label: "Concentration",   path: "/concentration" },
  { label: "Diversification", path: "/diversification" },
  { label: "Risk",            path: "/risk" },
  { label: "Action Plan",     path: "/plan" },
  { label: "Goals",           path: "/goals" },
];

const BADGE_TONE = {
  rust:   { bg: "rgba(223,93,93,.12)",   border: "rgba(223,93,93,.3)",   color: "var(--v4-rust)"   },
  gold:   { bg: "rgba(217,182,74,.12)",  border: "rgba(217,182,74,.3)",  color: "var(--v4-gold)"   },
  moss:   { bg: "rgba(136,171,102,.12)", border: "rgba(136,171,102,.3)", color: "var(--v4-moss)"   },
  indigo: { bg: "rgba(125,126,255,.12)", border: "rgba(125,126,255,.3)", color: "var(--v4-indigo)" },
};

export function DashboardShell({ title, badge, badgeTone = "gold", children }) {
  const navigate  = useNavigate();
  const location  = useLocation();
  const { logout } = useAuth();

  const handleSignOut = () => {
    logout().then(() => { resetCurrentUser(); navigate("/", { replace: true }); });
  };

  const bt = BADGE_TONE[badgeTone] || BADGE_TONE.gold;

  return (
    <div style={rootStyle}>
      {/* ── Left sidebar ─────────────────────────────── */}
      <aside style={sidebarStyle}>
        {/* Brand */}
        <div style={sidebarBrandStyle}>
          <div style={markStyle}>न</div>
          <div>
            <div style={{ fontFamily: "var(--v4-display)", fontWeight: 600, fontSize: 15, color: "var(--v4-ink)" }}>Nivesh</div>
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.4, color: "var(--v4-ink-faint)", textTransform: "uppercase" }}>AI Copilot</div>
          </div>
        </div>

        {/* Back to Chat */}
        <button style={chatLinkStyle} onClick={() => navigate("/landing")} type="button">
          <span style={{ fontSize: 12, color: "var(--v4-ink-faint)" }}>←</span>
          <span>Chat · Insights</span>
        </button>

        <div style={sidebarDividerStyle} />

        <div style={{ fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6, color: "var(--v4-ink-faint)", textTransform: "uppercase", padding: "0 18px", marginBottom: 6 }}>
          Dashboards
        </div>

        {/* Nav links */}
        {NAV_ITEMS.map(({ label, path }) => {
          const active = location.pathname === path || location.pathname.endsWith(path);
          return (
            <button
              key={path}
              type="button"
              onClick={() => navigate(path)}
              style={active ? { ...sideNavItemStyle, ...sideNavActiveStyle } : sideNavItemStyle}
            >
              {label}
              {active && <span style={{ marginLeft: "auto", width: 4, height: 4, borderRadius: "50%", background: "var(--v4-saffron)" }} />}
            </button>
          );
        })}

        <div style={{ marginTop: "auto", padding: "18px 18px 24px" }}>
          <button onClick={handleSignOut} style={signOutStyle} type="button">Sign out</button>
        </div>
      </aside>

      {/* ── Right column ─────────────────────────────── */}
      <div style={rightColStyle}>
        {/* Sticky topnav */}
        <header style={topnavStyle}>
          <button style={backBtnStyle} onClick={() => navigate(-1)} type="button">‹</button>
          <span style={{ fontFamily: "var(--v4-display)", fontWeight: 600, fontSize: 17, color: "var(--v4-ink)" }}>
            {title || "Dashboard"}
          </span>
          {badge && (
            <span style={{ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1, padding: "3px 9px", borderRadius: 5, textTransform: "uppercase", background: bt.bg, border: `1px solid ${bt.border}`, color: bt.color }}>
              {badge}
            </span>
          )}
          <button style={chatBackStyle} onClick={() => navigate("/landing")} type="button">
            ← Chat
          </button>
        </header>

        {/* Page body */}
        <main style={mainStyle}>{children}</main>
      </div>
    </div>
  );
}

/* ── Shared helpers ─────────────────────────────────────── */

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
      <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1.4, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 8 }}>{label}</div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 24, color: tone || "var(--v4-ink)", lineHeight: 1.1 }}>{value}</div>
      {sub && <div style={{ fontFamily: "var(--v4-mono)", fontSize: 10, color: "var(--v4-ink-faint)", marginTop: 4 }}>{sub}</div>}
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
    <div style={{ height, borderRadius: radius, background: "linear-gradient(90deg, var(--v4-s1) 0%, var(--v4-s2) 50%, var(--v4-s1) 100%)", backgroundSize: "200% 100%", animation: "v4-shimmer 1.4s ease infinite" }} />
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

/* ── Recommendation section (② pattern) ───────────────── */

const ACTION_META = {
  EXIT:   { tone: "var(--v4-rust)",    label: "Exit"   },
  TRIM:   { tone: "var(--v4-gold)",   label: "Trim"   },
  ADD:    { tone: "var(--v4-moss)",    label: "Add"    },
  HOLD:   { tone: "var(--v4-indigo)", label: "Hold"   },
  REVIEW: { tone: "var(--v4-saffron)", label: "Review" },
};

export function RecommendationCard({ action, accepted, onAccept, onSkip }) {
  const type  = (action.type || "REVIEW").toUpperCase();
  const meta  = ACTION_META[type] || ACTION_META.REVIEW;
  const title = action.asset_name || action.title || "Action";
  const detail = action.reason_text || action.detail;
  const priority = String(action.priority || "").toLowerCase();

  return (
    <div style={recCardStyle(meta.tone, accepted)}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <div style={recTypeBadge(meta.tone)}>
          <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1, color: meta.tone, textTransform: "uppercase" }}>{meta.label}</span>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 3 }}>
            <span style={{ fontFamily: "var(--v4-display)", fontSize: 15, color: "var(--v4-ink)" }}>{title}</span>
            {priority && (
              <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1, color: "var(--v4-ink-faint)", textTransform: "uppercase" }}>
                {priority} priority
              </span>
            )}
          </div>
          {detail && <div style={{ fontSize: 12, color: "var(--v4-ink-dim)", lineHeight: 1.5, marginBottom: 10 }}>{detail}</div>}
          {action.amount > 0 && (
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 10, color: "var(--v4-ink-mute)", marginBottom: 10 }}>
              Amount: <span style={{ color: "var(--v4-ink)" }}>{formatInr(action.amount)}</span>
            </div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" onClick={onAccept}
              style={accepted ? recBtnAcceptedStyle : recBtnAcceptStyle}>
              {accepted ? "✓ Accepted" : "Accept"}
            </button>
            {!accepted && (
              <button type="button" onClick={onSkip} style={recBtnSkipStyle}>Skip</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function ApplyCard({ metricLabel, before, after, unit = "%", acceptedCount, onSend }) {
  const hasMetric = before != null && after != null;
  return (
    <div style={applyCardStyle}>
      <div style={{ fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.2, color: "var(--v4-saffron)", textTransform: "uppercase", marginBottom: 6 }}>③ Apply</div>
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        {hasMetric && (
          <div>
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-faint)", marginBottom: 3, textTransform: "uppercase" }}>{metricLabel}</div>
            <div style={{ fontFamily: "var(--v4-display)", fontSize: 18, color: "var(--v4-moss)" }}>
              {before}{unit} → {after}{unit}
            </div>
          </div>
        )}
        <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-mute)", marginLeft: hasMetric ? "auto" : 0 }}>
          {acceptedCount} accepted
        </div>
        <button type="button" onClick={onSend} style={sendToPlanStyle}>
          Send to Plan board →
        </button>
      </div>
    </div>
  );
}

/**
 * Section-header row: mono caps label with a hairline rule that extends
 * to the right edge. Matches `.hl` in the prototype.
 */
export function HlBar({ children, tone = "var(--v4-ink-faint)" }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 9 }}>
      <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6, color: tone, textTransform: "uppercase" }}>{children}</span>
      <span style={{ flex: 1, height: 1, background: "var(--v4-line)" }} />
    </div>
  );
}

/* ── Styles ──────────────────────────────────────────────── */

const rootStyle = {
  display: "flex",
  minHeight: "100vh",
  background: "var(--v4-bg)",
  color: "var(--v4-ink)",
};

const sidebarStyle = {
  width: 240,
  minWidth: 240,
  borderRight: "1px solid var(--v4-line)",
  background: "var(--v4-s0)",
  display: "flex",
  flexDirection: "column",
  position: "sticky",
  top: 0,
  height: "100vh",
  overflowY: "auto",
};

const sidebarBrandStyle = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "22px 18px 16px",
  borderBottom: "1px solid var(--v4-line)",
};

const markStyle = {
  width: 32, height: 32, borderRadius: 8,
  background: "linear-gradient(150deg, var(--v4-saffron), var(--v4-saffron-lo))",
  display: "grid", placeItems: "center",
  fontFamily: "var(--v4-display)", fontWeight: 600, color: "#2a1605", fontSize: 17, flexShrink: 0,
};

const chatLinkStyle = {
  display: "flex", alignItems: "center", gap: 8,
  fontFamily: "var(--v4-mono)", fontSize: 10, letterSpacing: 1, color: "var(--v4-saffron)",
  textTransform: "uppercase", background: "transparent", border: "none",
  padding: "12px 18px", cursor: "pointer", width: "100%", textAlign: "left",
};

const sidebarDividerStyle = { height: 1, background: "var(--v4-line)", margin: "4px 0 10px" };

const sideNavItemStyle = {
  display: "flex", alignItems: "center",
  fontFamily: "var(--v4-mono)", fontSize: 10, letterSpacing: 0.8, color: "var(--v4-ink-faint)",
  textTransform: "uppercase", background: "transparent", border: "none",
  padding: "11px 18px", cursor: "pointer", width: "100%", textAlign: "left",
  transition: "color .15s, background .15s",
};

const sideNavActiveStyle = {
  color: "var(--v4-saffron)",
  background: "rgba(255,146,72,.07)",
};

const signOutStyle = {
  fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1,
  color: "var(--v4-ink-faint)", background: "transparent",
  border: "1px solid var(--v4-line)", padding: "7px 12px", borderRadius: 7,
  textTransform: "uppercase", cursor: "pointer", width: "100%",
};

const rightColStyle = { flex: 1, display: "flex", flexDirection: "column", minWidth: 0 };

const topnavStyle = {
  display: "flex", alignItems: "center", gap: 12,
  padding: "16px 28px", borderBottom: "1px solid var(--v4-line)",
  position: "sticky", top: 0, background: "rgba(11,10,8,0.96)",
  backdropFilter: "blur(10px)", zIndex: 20,
};

const backBtnStyle = {
  fontSize: 22, color: "var(--v4-ink-dim)", background: "transparent",
  border: "none", cursor: "pointer", lineHeight: 1, padding: "0 4px 0 0",
};

const chatBackStyle = {
  marginLeft: "auto",
  fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1,
  color: "var(--v4-saffron)", background: "transparent", border: "none",
  textTransform: "uppercase", cursor: "pointer",
};

export const mainStyle = { maxWidth: 900, margin: "0 auto", padding: "36px 28px 80px" };

const sectionHeaderStyle = {
  fontFamily: "var(--v4-mono)", fontSize: 10, letterSpacing: 1.6,
  color: "var(--v4-ink-faint)", textTransform: "uppercase",
  marginBottom: 14, display: "flex", alignItems: "center", gap: 10,
};

const statTileStyle = {
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-md)",
  padding: "18px 20px",
};

const emptyStateStyle = {
  textAlign: "center", padding: "60px 24px",
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-xl)",
};

const recCardStyle = (tone, accepted) => ({
  background: accepted
    ? "rgba(136,171,102,.06)"
    : "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: `1px solid ${accepted ? "rgba(136,171,102,.3)" : "var(--v4-line)"}`,
  borderLeft: `3px solid ${accepted ? "var(--v4-moss)" : tone}`,
  borderRadius: "var(--v4-r-md)",
  padding: "14px 16px",
  opacity: accepted ? 0.8 : 1,
});

const recTypeBadge = (tone) => ({
  background: `${tone}18`, border: `1px solid ${tone}40`,
  borderRadius: 6, padding: "3px 8px", flexShrink: 0, marginTop: 2,
});

const recBtnAcceptStyle = {
  fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 0.8,
  color: "var(--v4-moss)", background: "rgba(136,171,102,.1)",
  border: "1px solid rgba(136,171,102,.35)", padding: "6px 13px",
  borderRadius: 7, cursor: "pointer", textTransform: "uppercase",
};

const recBtnAcceptedStyle = {
  ...(() => ({ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 0.8 }))(),
  fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 0.8,
  color: "var(--v4-moss)", background: "rgba(136,171,102,.15)",
  border: "1px solid rgba(136,171,102,.4)", padding: "6px 13px",
  borderRadius: 7, cursor: "default", textTransform: "uppercase",
};

const recBtnSkipStyle = {
  fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 0.8,
  color: "var(--v4-ink-faint)", background: "transparent",
  border: "1px solid var(--v4-line)", padding: "6px 13px",
  borderRadius: 7, cursor: "pointer", textTransform: "uppercase",
};

const applyCardStyle = {
  background: "linear-gradient(168deg, rgba(255,146,72,.08), rgba(255,146,72,.02))",
  border: "1px solid rgba(255,146,72,.25)",
  borderRadius: "var(--v4-r-md)", padding: "16px 18px",
};

const sendToPlanStyle = {
  fontFamily: "var(--v4-sans)", fontSize: 12, fontWeight: 600,
  background: "linear-gradient(150deg, var(--v4-saffron), var(--v4-saffron-dk))",
  color: "#2a1605", padding: "9px 16px", borderRadius: 9,
  border: "none", cursor: "pointer",
};
