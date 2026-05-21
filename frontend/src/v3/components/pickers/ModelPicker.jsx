import React from "react";
import { Check } from "lucide-react";
import Sheet from "./Sheet";

const TIERS = [
  {
    id: "fast",
    label: "Fast — quick lookups",
    options: [
      { id: "haiku-4.5", name: "Haiku 4.5", tier: "flash", latency: "~0.8s", cost: "₹0.10 per query" },
      { id: "gpt-4o-mini", name: "GPT-4o mini", tier: "flash", latency: "~1.0s", cost: "₹0.12 per query" },
    ],
  },
  {
    id: "balanced",
    label: "Balanced — default",
    options: [
      { id: "gpt-4o", name: "GPT-4o", tier: "balanced", latency: "~2.4s", cost: "₹0.85 per query · recommended" },
      { id: "sonnet-4.6", name: "Sonnet 4.6", tier: "balanced", latency: "~2.8s", cost: "₹0.95 per query" },
    ],
  },
  {
    id: "deep",
    label: "Deep — for big questions",
    options: [
      { id: "opus-4.7", name: "Opus 4.7", tier: "deep", latency: "~6s", cost: "₹4.20 per query · stress tests & planning" },
      { id: "o3", name: "o3", tier: "deep", latency: "~8s", cost: "₹5.10 per query · multi-step reasoning" },
    ],
  },
];

const TIER_BADGE = {
  flash: { bg: "var(--v3-moss-soft)", fg: "var(--v3-moss)", label: "FLASH" },
  balanced: { bg: "var(--v3-gold-soft)", fg: "var(--v3-gold)", label: "BALANCED" },
  deep: { bg: "var(--v3-indigo-soft)", fg: "var(--v3-indigo)", label: "DEEP" },
};

const BAR_HEIGHTS = {
  flash: [4, 8, 5, 5],
  balanced: [6, 11, 14, 8],
  deep: [7, 12, 16, 20],
};

export default function ModelPicker({ open, onClose, value = "gpt-4o", onChange, mode = "sheet", anchorRef }) {
  return (
    <Sheet open={open} onClose={onClose} title="Model picker" subtitle="Opens from Balanced pill" mode={mode} anchorRef={anchorRef}>
      <div>
        {TIERS.map((group) => (
          <div key={group.id} style={{ marginBottom: 12 }}>
            <div
              className="v3-eyebrow"
              style={{ padding: "12px 14px 8px", color: "var(--v3-ink-3)" }}
            >
              {group.label}
            </div>
            {group.options.map((o) => {
              const active = value === o.id;
              const badge = TIER_BADGE[o.tier];
              const bars = BAR_HEIGHTS[o.tier];
              return (
                <button
                  type="button"
                  key={o.id}
                  onClick={() => {
                    onChange && onChange(o.id);
                    onClose && onClose();
                  }}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                    padding: "10px 14px",
                    borderRadius: 10,
                    background: active ? "var(--v3-bg-2)" : "transparent",
                    cursor: "pointer",
                  }}
                >
                  <BarsViz heights={bars} active={active} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 13.5, fontWeight: 600, color: "var(--v3-ink-1)" }}>{o.name}</span>
                      <span
                        style={{
                          fontFamily: "var(--v3-font-mono)",
                          fontSize: 9,
                          padding: "2px 6px",
                          borderRadius: 4,
                          textTransform: "uppercase",
                          letterSpacing: "0.08em",
                          background: badge.bg,
                          color: badge.fg,
                        }}
                      >
                        {badge.label}
                      </span>
                    </div>
                    <div
                      className="v3-eyebrow"
                      style={{ marginTop: 2, color: "var(--v3-ink-3)", letterSpacing: "0.06em" }}
                    >
                      {o.latency} · {o.cost}
                    </div>
                  </div>
                  {active && <Check size={16} style={{ color: "var(--v3-saffron)" }} />}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </Sheet>
  );
}

function BarsViz({ heights, active }) {
  return (
    <div style={{ display: "flex", gap: 3, alignItems: "flex-end", height: 18 }}>
      {heights.map((h, i) => (
        <span
          key={i}
          style={{
            width: 4,
            height: h,
            background: active ? "var(--v3-saffron)" : "var(--v3-ink-4)",
            borderRadius: 1,
            opacity: !active && i >= 2 ? 0.3 : 1,
          }}
        />
      ))}
    </div>
  );
}
