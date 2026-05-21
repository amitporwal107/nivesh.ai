import React from "react";

/**
 * 32×32 saffron-gradient mark with the Devanagari "न" — spec §6 guardrail #5.
 * Used in TopBar and Sidebar. Size is fixed per spec; only opacity can vary.
 */
export default function BrandMark({ size = 32, withWordmark = false, className = "" }) {
  return (
    <div className={`v3-brand ${className}`} style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
      <div
        aria-hidden
        style={{
          width: size,
          height: size,
          borderRadius: 10,
          background: "linear-gradient(135deg, var(--v3-saffron), #ffb380)",
          display: "grid",
          placeItems: "center",
          fontFamily: "var(--v3-font-display)",
          fontWeight: 700,
          color: "var(--v3-saffron-ink)",
          fontSize: Math.round(size * 0.5),
          boxShadow: "inset 0 1px 0 rgba(255,255,255,0.25)",
        }}
      >
        न
      </div>
      {withWordmark && (
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontFamily: "var(--v3-font-display)", fontWeight: 600, fontSize: 17, letterSpacing: "-0.01em", color: "var(--v3-ink-1)" }}>
            Nivesh
          </span>
          <span style={{ fontFamily: "var(--v3-font-display)", fontStyle: "italic", fontSize: 14, color: "var(--v3-ink-3)" }}>
            copilot
          </span>
        </div>
      )}
    </div>
  );
}
