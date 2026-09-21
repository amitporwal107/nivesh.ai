/**
 * Resolves the app's CSS custom properties (index.css, scoped under `.research-screen`) to concrete colour strings
 * a <canvas> context can use. `getComputedStyle` only substitutes `var(...)` inside a real CSS property (like
 * `color`), never for a custom property read back directly — so this renders a hidden probe element per token and
 * reads its resolved `color`. Runs once per chart mount; the chart does not currently re-theme on a live light/dark
 * toggle (documented limitation, v1).
 */
export interface ChartTheme {
  bg1: string; bg2: string;
  ink: string; ink3: string; ink4: string;
  mint: string; amber: string; danger: string;
  line: string;
}

const TOKENS: Record<keyof ChartTheme, string> = {
  bg1: "var(--bg-1)", bg2: "var(--bg-2)",
  ink: "var(--c-ink)", ink3: "var(--c-ink-3)", ink4: "var(--c-ink-4)",
  mint: "var(--mint)", amber: "var(--amber)", danger: "var(--danger-hex)",
  line: "var(--c-line)",
};

export function resolveTheme(host: HTMLElement): ChartTheme {
  const probe = document.createElement("span");
  probe.style.position = "absolute";
  probe.style.visibility = "hidden";
  probe.style.pointerEvents = "none";
  host.appendChild(probe);
  const out = {} as ChartTheme;
  for (const key of Object.keys(TOKENS) as Array<keyof ChartTheme>) {
    probe.style.color = TOKENS[key];
    out[key] = getComputedStyle(probe).color || "#888888";
  }
  host.removeChild(probe);
  return out;
}

/** rgba(...) with an overridden alpha, from a computed `rgb(r, g, b)` / `rgba(r, g, b, a)` string. */
export function withAlpha(rgbOrRgba: string, alpha: number): string {
  const m = rgbOrRgba.match(/rgba?\(([^)]+)\)/);
  if (!m) return rgbOrRgba;
  const parts = m[1].split(",").map((s) => s.trim());
  const [r, g, b] = parts;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
