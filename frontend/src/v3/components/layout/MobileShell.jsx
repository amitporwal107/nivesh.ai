import React from "react";
import BottomNav from "./BottomNav";

/**
 * Mobile shell — paddings, sticky composer slot, and BottomNav.
 * Pages render between TopBar (rendered inside page) and the nav.
 */
export default function MobileShell({ children, hideBottomNav = false, footer = null }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        paddingBottom: hideBottomNav ? 0 : `calc(var(--v3-bottom-nav-h) + env(safe-area-inset-bottom, 0px))`,
      }}
    >
      <main style={{ flex: 1, paddingBottom: footer ? 0 : 20 }}>{children}</main>
      {footer}
      {!hideBottomNav && <BottomNav />}
    </div>
  );
}
