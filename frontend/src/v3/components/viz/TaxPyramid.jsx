import React from "react";

/**
 * Tax pyramid (gains breakdown) — spec §2.4 tax variant.
 */
export default function TaxPyramid({ size = 36, color = "var(--v3-indigo)" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden role="img">
      <path d="M6 30 L18 6 L30 30 Z" fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
      <path d="M11 22 L18 14 L25 22 Z" fill={color} opacity={0.35} />
    </svg>
  );
}
