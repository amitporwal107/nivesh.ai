import React from "react";

/**
 * Eyebrow + count — spec §3 mobile layout. Used above every section block.
 */
export default function SectionHead({ title, count = null, action = null }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        marginBottom: 10,
        gap: 12,
      }}
    >
      <h3
        style={{
          fontFamily: "var(--v3-font-mono)",
          fontSize: 11,
          fontWeight: 500,
          textTransform: "uppercase",
          letterSpacing: "0.16em",
          color: "var(--v3-ink-3)",
          margin: 0,
        }}
      >
        {title}
      </h3>
      {count != null && (
        <span
          style={{
            fontFamily: "var(--v3-font-mono)",
            fontSize: 10,
            color: "var(--v3-ink-4)",
            letterSpacing: "0.08em",
          }}
        >
          {count}
        </span>
      )}
      {action}
    </div>
  );
}
