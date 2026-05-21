import React from "react";

/**
 * The inner viz panel used inside HeroCard. Top row of eyebrow + big number, then the chart body below.
 * Used by Home (FundCount) and reusable for any hero that needs the same structure.
 */
export default function HeroVizPanel({ eyebrow, value, unit, children, size = "mobile" }) {
  const isDesktop = size === "desktop";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span className="v3-eyebrow" style={{ color: "var(--v3-ink-3)" }}>
          {eyebrow}
        </span>
        <span
          style={{
            fontFamily: "var(--v3-font-display)",
            fontWeight: 600,
            fontSize: isDesktop ? 32 : 26,
            color: "var(--v3-ink-1)",
            letterSpacing: "-0.02em",
          }}
        >
          {value}
          {unit && (
            <span
              style={{
                fontFamily: "var(--v3-font-sans)",
                fontWeight: 400,
                fontSize: isDesktop ? 14 : 13,
                color: "var(--v3-ink-3)",
                marginLeft: 4,
              }}
            >
              {unit}
            </span>
          )}
        </span>
      </div>
      {children}
    </div>
  );
}
