import React from "react";
import { NavLink } from "react-router-dom";
import { BOTTOM_NAV } from "../../navigation/routes";

/**
 * Mobile bottom navigation. Active state uses saffron icon on bg-3 pill.
 */
export default function BottomNav() {
  return (
    <nav
      aria-label="Primary"
      style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 30,
        background: "var(--v3-bg-1)",
        borderTop: "1px solid var(--v3-line)",
        paddingBottom: "env(safe-area-inset-bottom, 8px)",
      }}
    >
      <ul
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${BOTTOM_NAV.length}, 1fr)`,
          margin: 0,
          padding: "6px 4px",
          listStyle: "none",
          gap: 4,
        }}
      >
        {BOTTOM_NAV.map((r) => {
          const Icon = r.icon;
          return (
            <li key={r.path}>
              <NavLink
                to={`/${r.path}`}
                style={({ isActive }) => ({
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 2,
                  padding: "8px 0 6px",
                  borderRadius: 12,
                  background: isActive ? "var(--v3-bg-3)" : "transparent",
                  color: isActive ? "var(--v3-saffron)" : "var(--v3-ink-3)",
                  textDecoration: "none",
                  transition: "all var(--v3-dur) var(--v3-ease)",
                })}
              >
                <Icon size={20} strokeWidth={2} />
                <span
                  style={{
                    fontFamily: "var(--v3-font-mono)",
                    fontSize: 10,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    fontWeight: 500,
                  }}
                >
                  {r.bottomLabel}
                </span>
              </NavLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
