import React, { useState } from "react";
import { ChevronDown } from "lucide-react";
import TinyChip from "./TinyChip";

/**
 * Container for tiny chips with collapse toggle — spec §2.5.
 */
export default function MoreQuestions({ title = "More questions", items = [], onPick, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          width: "100%",
          padding: "10px 0",
          borderTop: "1px solid var(--v3-line)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          color: "var(--v3-ink-3)",
          fontFamily: "var(--v3-font-mono)",
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.14em",
          cursor: "pointer",
        }}
        aria-expanded={open}
      >
        <span>
          {title} · {items.length}
        </span>
        <ChevronDown
          size={14}
          style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform var(--v3-dur) var(--v3-ease)" }}
        />
      </button>
      {open && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
          {items.map((item, i) => (
            <TinyChip key={i} onClick={() => onPick && onPick(item)}>
              {item.label || item}
            </TinyChip>
          ))}
        </div>
      )}
    </div>
  );
}
