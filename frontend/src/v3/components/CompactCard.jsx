import React from "react";
import CategoryBadge from "./CategoryBadge";

/**
 * Spec §2.4 compact card. Top row: category badge + micro-viz. Body: label + meta.
 * Min size: 168×120 mobile, 362×126 desktop — but the grid handles sizing.
 */
export default function CompactCard({ category = "health", label, meta = null, viz = null, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        width: "100%",
        textAlign: "left",
        background: "var(--v3-bg-2)",
        border: "1px solid var(--v3-line)",
        borderRadius: "var(--v3-r-md)",
        padding: 14,
        cursor: "pointer",
        position: "relative",
        overflow: "hidden",
        minHeight: 110,
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        transition: "background var(--v3-dur) var(--v3-ease), border-color var(--v3-dur) var(--v3-ease)",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "var(--v3-bg-3)";
        e.currentTarget.style.borderColor = "var(--v3-line-strong)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "var(--v3-bg-2)";
        e.currentTarget.style.borderColor = "var(--v3-line)";
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <CategoryBadge category={category} size="mini" />
        {viz && <div style={{ flexShrink: 0 }}>{viz}</div>}
      </div>

      <div style={{ marginTop: 10, fontSize: 13.5, fontWeight: 500, color: "var(--v3-ink-1)", lineHeight: 1.35 }}>
        {label}
      </div>

      {meta && (
        <div
          className="v3-eyebrow"
          style={{
            marginTop: 8,
            color: "var(--v3-ink-3)",
            letterSpacing: "0.06em",
            fontSize: 10,
          }}
        >
          {meta}
        </div>
      )}
    </button>
  );
}
