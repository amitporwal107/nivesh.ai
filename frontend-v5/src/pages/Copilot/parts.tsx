/**
 * Shared primitives for the Copilot tour sections.
 */
import { ReactNode } from "react";

/** Circular health-score ring (SVG). `score` 0–100 sets the arc + label. */
export function ScoreRing({
  score,
  size = 76,
  id,
}: {
  score: number;
  size?: number;
  id: string;
}) {
  const circumference = 195; // matches r=31 arc length used in the design
  const offset = Math.round(circumference * (1 - score / 100));
  return (
    <svg width={size} height={size} viewBox="0 0 76 76" style={{ flex: "0 0 auto" }} aria-hidden>
      <defs>
        <linearGradient id={`ring-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--mint)" />
          <stop offset="1" stopColor="var(--mint-2)" />
        </linearGradient>
      </defs>
      <circle cx="38" cy="38" r="31" fill="none" stroke="var(--bg-4)" strokeWidth="7" />
      <circle
        cx="38"
        cy="38"
        r="31"
        fill="none"
        stroke={`url(#ring-${id})`}
        strokeWidth="7"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform="rotate(-90 38 38)"
      />
      <text
        x="38"
        y="41"
        textAnchor="middle"
        className="nv-serif"
        style={{ fontSize: 22, fill: "rgb(var(--ink))" }}
        dominantBaseline="middle"
      >
        {score}
      </text>
    </svg>
  );
}

/** The Devanagari brand mark used throughout the tour. */
export function Mark({ size = 28, fontSize = 17 }: { size?: number; fontSize?: number }) {
  return (
    <span className="nv-mark" style={{ width: size, height: size, fontSize }}>
      न
    </span>
  );
}

/** Section header row: number · title · subtitle. */
export function SectionHead({
  n,
  title,
  sub,
  accent = "var(--mint)",
  extra,
}: {
  n?: string;
  title: ReactNode;
  sub?: ReactNode;
  accent?: string;
  extra?: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 12,
        marginBottom: 14,
        flexWrap: "wrap",
      }}
    >
      {n && (
        <span className="nv-mono" style={{ fontSize: 13, color: accent }}>
          {n}
        </span>
      )}
      <span className="nv-serif" style={{ fontSize: 24 }}>
        {title}
      </span>
      {sub && (
        <span className="nv-body" style={{ color: "rgb(var(--ink-3))" }}>
          {sub}
        </span>
      )}
      {extra}
    </div>
  );
}
