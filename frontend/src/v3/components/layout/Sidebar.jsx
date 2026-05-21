import React from "react";
import { NavLink } from "react-router-dom";
import BrandMark from "../BrandMark";
import { ROUTES } from "../../navigation/routes";

const GROUPS = [
  { id: "workspace", title: "Workspace" },
  { id: "analytics", title: "Analytics" },
  { id: "you", title: "You" },
];

export default function Sidebar({ persona, collapsed = false }) {
  return (
    <aside
      style={{
        position: "sticky",
        top: 0,
        height: "100vh",
        width: collapsed ? 72 : "var(--v3-sidebar-w)",
        flexShrink: 0,
        background: "var(--v3-bg-2)",
        borderRight: "1px solid var(--v3-line)",
        padding: collapsed ? "20px 8px" : "20px 16px",
        overflowY: "auto",
        transition: "width var(--v3-dur) var(--v3-ease)",
        display: "flex",
        flexDirection: "column",
        gap: 24,
      }}
    >
      <div style={{ padding: collapsed ? 0 : "4px 8px" }}>
        <BrandMark withWordmark={!collapsed} size={32} />
      </div>

      {GROUPS.map((g) => {
        const items = ROUTES.filter((r) => r.group === g.id);
        if (items.length === 0) return null;
        return (
          <div key={g.id}>
            {!collapsed && (
              <div
                className="v3-eyebrow"
                style={{ color: "var(--v3-ink-3)", padding: "0 8px", marginBottom: 10 }}
              >
                {g.title}
              </div>
            )}
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 2 }}>
              {items.map((r) => {
                const Icon = r.icon;
                if (!Icon) return null;
                return (
                  <li key={r.path}>
                    <NavLink
                      to={`/${r.path}`}
                      end={r.path === "home"}
                      style={({ isActive }) => ({
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        padding: collapsed ? "10px 0" : "9px 10px",
                        borderRadius: 8,
                        color: isActive ? "var(--v3-ink-1)" : "var(--v3-ink-2)",
                        background: isActive ? "var(--v3-bg-3)" : "transparent",
                        fontSize: 13,
                        textDecoration: "none",
                        transition: "all var(--v3-dur) var(--v3-ease)",
                        justifyContent: collapsed ? "center" : "flex-start",
                      })}
                    >
                      <Icon size={16} strokeWidth={2} />
                      {!collapsed && <span>{r.title}</span>}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}

      <div style={{ marginTop: "auto" }}>
        {!collapsed && (
          <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", padding: "0 8px", marginBottom: 10 }}>
            Persona
          </div>
        )}
        {persona && !collapsed && (
          <NavLink
            to="/profile"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "9px 10px",
              borderRadius: 8,
              background: "var(--v3-bg-3)",
              color: `var(--v3-${persona.accent === "saffron" ? "saffron" : persona.accent})`,
              fontSize: 13,
              fontWeight: 500,
              textDecoration: "none",
            }}
          >
            <span
              aria-hidden
              style={{
                width: 8,
                height: 8,
                borderRadius: 999,
                background: `var(--v3-${persona.accent === "saffron" ? "saffron" : persona.accent})`,
              }}
            />
            {persona.name}
          </NavLink>
        )}
      </div>
    </aside>
  );
}
