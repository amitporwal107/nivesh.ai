import React from "react";
import { ChevronDown } from "lucide-react";

/**
 * Generic pill — spec §2.6 composer meta pill pattern.
 * dotColor maps to status indicators (saffron=auto, indigo=agent, gold=model).
 */
export default function Pill({
  dotColor = "var(--v3-moss)",
  children,
  onClick,
  active = false,
  chevron = true,
  icon = null,
  className = "",
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={className}
      style={{
        background: "var(--v3-bg-2)",
        border: `1px solid ${active ? "var(--v3-line-strong)" : "var(--v3-line)"}`,
        borderRadius: 999,
        padding: "5px 10px 5px 8px",
        fontSize: 11,
        color: "var(--v3-ink-2)",
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        cursor: "pointer",
        transition: "border-color var(--v3-dur) var(--v3-ease), color var(--v3-dur) var(--v3-ease)",
        whiteSpace: "nowrap",
        fontFamily: "var(--v3-font-sans)",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--v3-line-strong)")}
      onMouseLeave={(e) => (e.currentTarget.style.borderColor = active ? "var(--v3-line-strong)" : "var(--v3-line)")}
    >
      {icon ? icon : <span style={{ width: 6, height: 6, borderRadius: 999, background: dotColor }} />}
      <span>{children}</span>
      {chevron && <ChevronDown size={11} strokeWidth={2.5} style={{ color: "var(--v3-ink-3)" }} />}
    </button>
  );
}
