/**
 * Smart trading desk — the phone's bottom navigation (the user's decision of 2026-10-14: a persistent bar on phones),
 * with the four numbered tabs of the redesign of 2026-10-27 (docs/desk_redesign_20261027/PLAN.md): 01 Overview ·
 * 02 Trade · 03 Market · 04 Risk, then the desk's AI Copilot (on a phone the app's own ask box is hidden on desk pages
 * and lives there instead, index.tsx). Fixed at the bottom of the screen above the safe area. My portfolio is in the
 * phone header. Reads nothing.
 *
 * Each item is a real button (keyboard reachable, with an aria label); the current one carries
 * aria-current="page" and says so in words to screen readers, not only by colour.
 */
import type { ReactNode } from "react";

export type BottomKey = "overview" | "trade" | "market" | "risk" | "copilot";

/** The bar's own height without the safe area; the page leaves this much room under its content. */
export const BOTTOM_BAR_HEIGHT = 58;

/**
 * The CSS length the desk pads its content with, and the phone Copilot's ask box sits above: the bar, its 1px top
 * border and an 8px gap, plus the safe area.
 */
export const BOTTOM_BAR_SPACE = `calc(${BOTTOM_BAR_HEIGHT + 1 + 8}px + env(safe-area-inset-bottom))`;

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round" } as const;

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden focusable="false">
      {children}
    </svg>
  );
}

const ICONS: Record<BottomKey, ReactNode> = {
  overview: <Icon><rect x="2.5" y="2.5" width="5.5" height="5.5" rx="1.2" {...stroke} /><rect x="10" y="2.5" width="5.5" height="5.5" rx="1.2" {...stroke} /><rect x="2.5" y="10" width="5.5" height="5.5" rx="1.2" {...stroke} /><rect x="10" y="10" width="5.5" height="5.5" rx="1.2" {...stroke} /></Icon>,
  trade: <Icon><path d="M3 12.5l4-4 3 3 5-6" {...stroke} /><path d="M11.5 5.5H15V9" {...stroke} /></Icon>,
  market: <Icon><path d="M3 3.5h9.5v11H4.5A1.5 1.5 0 0 1 3 13V3.5z" {...stroke} /><path d="M12.5 6.5H15V13a1.5 1.5 0 0 1-1.5 1.5" {...stroke} /><path d="M5.5 6.5h4.5M5.5 9h4.5M5.5 11.5h3" {...stroke} /></Icon>,
  risk: <Icon><path d="M9 2.5l5.5 2v4.2c0 3.2-2.3 5.6-5.5 6.8-3.2-1.2-5.5-3.6-5.5-6.8V4.5L9 2.5z" {...stroke} /><path d="M6.6 8.9l1.7 1.6 3.1-3.4" {...stroke} /></Icon>,
  copilot: <Icon><path d="M3 4.5A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5v6A1.5 1.5 0 0 1 13.5 12H8l-3.5 3v-3h0A1.5 1.5 0 0 1 3 10.5v-6z" {...stroke} /></Icon>,
};

/** The four numbered tabs, short names, then the Copilot. */
export const BOTTOM_ITEMS: ReadonlyArray<{ key: BottomKey; label: string; aria: string; num?: string }> = [
  { key: "overview", label: "Overview", aria: "01 Market Overview", num: "01" },
  { key: "trade", label: "Trade", aria: "02 Trade Desk", num: "02" },
  { key: "market", label: "Market", aria: "03 Market Desk", num: "03" },
  { key: "risk", label: "Risk", aria: "04 Risk Desk", num: "04" },
  { key: "copilot", label: "Copilot", aria: "AI Copilot" },
];

export function DeskBottomBar({ active, onPick }: { active: BottomKey; onPick: (key: BottomKey) => void }) {
  return (
    <nav
      aria-label="Desk sections"
      data-testid="desk-bottom-bar"
      style={{
        position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 25,
        paddingBottom: "env(safe-area-inset-bottom)",
        background: "var(--bg-glass)", WebkitBackdropFilter: "blur(14px)", backdropFilter: "blur(14px)",
        borderTop: "1px solid var(--cp-line)",
      }}
    >
      <ul className="m-0 grid p-0" style={{ listStyle: "none", gridTemplateColumns: `repeat(${BOTTOM_ITEMS.length},minmax(0,1fr))`, height: BOTTOM_BAR_HEIGHT }}>
        {BOTTOM_ITEMS.map((it) => {
          const on = it.key === active;
          return (
            <li key={it.key} className="flex min-w-0">
              <button
                type="button"
                data-testid={`desk-bottom-${it.key}`}
                aria-label={on ? `${it.aria} (current)` : it.aria}
                aria-current={on ? "page" : undefined}
                onClick={() => onPick(it.key)}
                className="flex min-w-0 flex-1 flex-col items-center justify-center"
                style={{
                  gap: 3, padding: "6px 2px", border: 0, background: "transparent", cursor: "pointer",
                  color: on ? "var(--mint)" : "var(--cp-ink-3)", fontFamily: "var(--sans)",
                }}
              >
                <span
                  className="grid place-items-center"
                  style={{ width: 34, height: 24, borderRadius: 999, background: on ? "var(--mint-soft)" : "transparent" }}
                >
                  {ICONS[it.key]}
                </span>
                <span style={{ fontSize: 10.5, lineHeight: 1, fontWeight: on ? 600 : 500, whiteSpace: "nowrap", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>{it.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
