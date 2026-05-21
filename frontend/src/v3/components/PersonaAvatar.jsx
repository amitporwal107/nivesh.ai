import React from "react";
import {
  Sprout,
  BarChart3,
  TrendingUp,
  Gem,
  Clock,
  GraduationCap,
  Calculator,
  Shield,
  Activity,
  Globe,
  Compass,
} from "lucide-react";

const ICONS = {
  sprout: Sprout,
  "bar-chart": BarChart3,
  "trending-up": TrendingUp,
  diamond: Gem,
  clock: Clock,
  graduation: GraduationCap,
  calculator: Calculator,
  shield: Shield,
  activity: Activity,
  globe: Globe,
  compass: Compass,
};

const ACCENT_BG = {
  saffron: "linear-gradient(135deg, var(--v3-saffron), var(--v3-saffron-deep))",
  indigo: "linear-gradient(135deg, var(--v3-indigo), #4a4bc7)",
  moss: "linear-gradient(135deg, var(--v3-moss), #5a7a44)",
  gold: "linear-gradient(135deg, var(--v3-gold), #a88a1d)",
  crimson: "linear-gradient(135deg, var(--v3-crimson), #a73a3a)",
};

const ACCENT_INK = {
  saffron: "var(--v3-saffron-ink)",
  indigo: "#101030",
  moss: "#0c1a06",
  gold: "#1f1602",
  crimson: "#2a0707",
};

const ACCENT_GLOW = {
  saffron: "var(--v3-saffron-soft)",
  indigo: "var(--v3-indigo-soft)",
  moss: "var(--v3-moss-soft)",
  gold: "var(--v3-gold-soft)",
  crimson: "var(--v3-crimson-soft)",
};

export default function PersonaAvatar({ iconKey = "compass", accent = "saffron", size = 44, radius = 12 }) {
  const Icon = ICONS[iconKey] || Compass;
  return (
    <div
      aria-hidden
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        background: ACCENT_BG[accent],
        display: "grid",
        placeItems: "center",
        flexShrink: 0,
        boxShadow: `0 4px 16px -4px ${ACCENT_GLOW[accent]}`,
      }}
    >
      <Icon size={Math.round(size * 0.45)} strokeWidth={2} color={ACCENT_INK[accent]} />
    </div>
  );
}
