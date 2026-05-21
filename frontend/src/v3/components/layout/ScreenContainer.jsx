import React from "react";

/**
 * Unified container around the content of each screen — abstracts gutters so screen
 * components don't repeat them. Mobile = horizontal gutter from CSS var. Desktop = no
 * extra horizontal gutter (DesktopShell already paddings).
 */
export default function ScreenContainer({ children, variant = "mobile", maxWidth = null, style = {} }) {
  const isMobile = variant === "mobile";
  return (
    <div
      style={{
        padding: isMobile ? "0 var(--v3-mobile-gutter)" : "0",
        maxWidth: maxWidth || (isMobile ? "100%" : "100%"),
        margin: "0 auto",
        width: "100%",
        ...style,
      }}
    >
      {children}
    </div>
  );
}
