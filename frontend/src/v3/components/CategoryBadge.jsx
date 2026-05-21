import React from "react";

const LABELS = {
  health: "Health",
  performance: "Performance",
  risk: "Risk",
  tax: "Tax",
  goal: "Goal",
};

/**
 * Pill badge used inside HeroCard / CompactCard headers — spec §2.3 / §2.4.
 * Colors: tinted background + matching text. `size`=mini for compact cards.
 */
export default function CategoryBadge({ category = "health", size = "default", label }) {
  const color = `var(--v3-cat-${category})`;
  const soft = `var(--v3-cat-${category}-soft)`;
  const isMini = size === "mini";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: isMini ? "3px 8px" : "4px 9px",
        borderRadius: 999,
        background: soft,
        color,
        fontFamily: "var(--v3-font-mono)",
        fontSize: isMini ? 9.5 : 10,
        fontWeight: 500,
        textTransform: "uppercase",
        letterSpacing: "0.1em",
        lineHeight: 1.2,
      }}
    >
      <span style={{ width: 5, height: 5, borderRadius: 999, background: color }} aria-hidden />
      {label || LABELS[category] || category}
    </span>
  );
}
