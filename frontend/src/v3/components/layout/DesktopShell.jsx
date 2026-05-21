import React from "react";
import Sidebar from "./Sidebar";

/**
 * Desktop shell — sidebar + main column with max-width per spec §3.
 * Tablet uses the same shell but the parent collapses the sidebar to icon rail.
 */
export default function DesktopShell({ children, persona, collapsedSidebar = false }) {
  return (
    <div style={{ display: "flex", minHeight: "100vh", alignItems: "stretch" }}>
      <Sidebar persona={persona} collapsed={collapsedSidebar} />
      <main
        style={{
          flex: 1,
          minWidth: 0,
          padding: "0 var(--v3-desktop-gutter) 24px",
          maxWidth: `calc(var(--v3-main-max-w) + 2 * var(--v3-desktop-gutter))`,
          margin: "0 auto",
          width: "100%",
        }}
      >
        {children}
      </main>
    </div>
  );
}
