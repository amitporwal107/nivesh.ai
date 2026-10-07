/**
 * Resolves the app's CSS custom properties (index.css, scoped under `.research-screen`) to concrete colour strings
 * a <canvas> context can use. `getComputedStyle` only substitutes `var(...)` inside a real CSS property (like
 * `color`), never for a custom property read back directly — so this renders a hidden probe element per token and
 * reads its resolved `color`.
 *
 * `resolveTheme(host)` itself is a one-shot read, unchanged for existing callers (ChartCanvas.tsx calls it once on
 * mount). D-6 (§38.9, §38.14) requires the chart to re-theme live when the app's light/dark toggle changes, without
 * a reload — `useAppTheme()` below is the new piece that makes that possible: it re-resolves the tokens whenever
 * `data-theme` on <html> changes (App.tsx sets it there, see index.css `:root[data-theme=...]`) and returns the
 * current value, so a consumer effect can push fresh colours into the live chart instance. Wiring `useAppTheme()`
 * into ChartCanvas's `applyOptions` calls is W1b (this module only makes the value available — ChartCanvas.tsx is
 * being edited by another W0/W1b task right now, so it is not touched here).
 */
import { useEffect, useState } from "react";

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

/* ══════════════════════════════════════════════════════════════════════════
   Live theme following (D-6)
   ══════════════════════════════════════════════════════════════════════════ */
export type ThemeName = "light" | "dark";

/**
 * The app's resolved theme name right now: `data-theme` on <html> when App.tsx has set one (it always does once
 * mounted — `useUIStore`'s default is "dark"), else the `prefers-color-scheme` media query, matching what
 * `:root`'s unscoped CSS block would render before the attribute exists.
 */
function resolveThemeName(): ThemeName {
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "light" || attr === "dark") return attr;
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export interface AppTheme {
  /** "light" | "dark" — the resolved theme name, for anything that needs the name itself (e.g. a library option
   *  that takes a theme string rather than colours). */
  theme: ThemeName;
  /** The same token set `resolveTheme` returns, re-read for the current theme. */
  colors: ChartTheme;
}

/**
 * Live-follows the app theme (D-6): watches `data-theme` on <html> with a MutationObserver, and the
 * `prefers-color-scheme` media query as the fallback path used when the attribute is ever absent (defensive —
 * today App.tsx always sets it, but §38.9 specifies the media-query fallback explicitly). Returns the current
 * theme name and its resolved chart colours, recomputed on every change, so a consumer can re-apply them to a
 * live chart instance without remounting it (AC 12: "changing the app theme in Settings re-themes an open chart
 * without a reload").
 */
export function useAppTheme(): AppTheme {
  const [state, setState] = useState<AppTheme>(() => ({
    theme: resolveThemeName(),
    colors: resolveTheme(document.documentElement),
  }));

  useEffect(() => {
    const recompute = () => setState({ theme: resolveThemeName(), colors: resolveTheme(document.documentElement) });

    const observer = new MutationObserver((mutations) => {
      if (mutations.some((m) => m.attributeName === "data-theme")) recompute();
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

    const mq = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    // addEventListener is the modern API; Safari <14 needs the deprecated addListener. Both are no-ops to
    // detach if unsupported, guarded with optional chaining so this never throws in a headless/test DOM.
    mq?.addEventListener?.("change", recompute);

    return () => {
      observer.disconnect();
      mq?.removeEventListener?.("change", recompute);
    };
  }, []);

  return state;
}
