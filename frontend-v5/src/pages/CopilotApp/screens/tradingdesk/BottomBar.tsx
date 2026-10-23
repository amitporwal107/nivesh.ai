/**
 * Smart trading desk — the phone's bottom navigation (PRD §3.1 and §3.3; the user's decision of 2026-10-14):
 * Overview · Scanner · Intel · Chart · Portfolio · More, fixed at the bottom of the screen above the safe area.
 * It replaces the top chip row on phones; the desktop tab row stays. More holds the desk's AI Copilot (the app's
 * own ask box is hidden on desk pages on a phone and lives there instead, index.tsx), the Options & futures lab
 * and the other destinations. Reads nothing.
 *
 * Each item is a real button (keyboard reachable, with an aria label); the current one carries
 * aria-current="page" and says so in words to screen readers, not only by colour.
 */
import type { ReactNode } from "react";

export type BottomKey = "overview" | "scanner" | "intel" | "chart" | "portfolio" | "smartmoney" | "more";

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
  scanner: <Icon><circle cx="8" cy="8" r="5" {...stroke} /><path d="M12 12l3.5 3.5" {...stroke} /><path d="M5.8 8.6l1.6 1.4 2.8-3.4" {...stroke} /></Icon>,
  intel: <Icon><path d="M3 3.5h9.5v11H4.5A1.5 1.5 0 0 1 3 13V3.5z" {...stroke} /><path d="M12.5 6.5H15V13a1.5 1.5 0 0 1-1.5 1.5" {...stroke} /><path d="M5.5 6.5h4.5M5.5 9h4.5M5.5 11.5h3" {...stroke} /></Icon>,
  chart: <Icon><path d="M4.5 3v12M9 2v14M13.5 5v9" {...stroke} /><rect x="3" y="6" width="3" height="5" rx="0.6" {...stroke} /><rect x="7.5" y="4.5" width="3" height="7" rx="0.6" {...stroke} /><rect x="12" y="7" width="3" height="4" rx="0.6" {...stroke} /></Icon>,
  portfolio: <Icon><circle cx="9" cy="9" r="6.2" {...stroke} /><path d="M9 2.8V9l5.4 3" {...stroke} /></Icon>,
  smartmoney: <Icon><ellipse cx="9" cy="4.6" rx="5.5" ry="2.1" {...stroke} /><path d="M3.5 4.6v4.2c0 1.16 2.46 2.1 5.5 2.1s5.5-.94 5.5-2.1V4.6" {...stroke} /><path d="M3.5 8.8v4.2c0 1.16 2.46 2.1 5.5 2.1s5.5-.94 5.5-2.1V8.8" {...stroke} /></Icon>,
  more: <Icon><circle cx="4" cy="9" r="1.3" fill="currentColor" /><circle cx="9" cy="9" r="1.3" fill="currentColor" /><circle cx="14" cy="9" r="1.3" fill="currentColor" /></Icon>,
};

/** The PRD's order (§3.1), with the phone's short names. */
export const BOTTOM_ITEMS: ReadonlyArray<{ key: BottomKey; label: string; aria: string }> = [
  { key: "overview", label: "Overview", aria: "Overview" },
  { key: "scanner", label: "Scanner", aria: "AI Scanner" },
  { key: "intel", label: "Intel", aria: "Market Intelligence" },
  { key: "chart", label: "Chart", aria: "Chart Analysis" },
  { key: "portfolio", label: "Portfolio", aria: "Portfolio and Risk" },
  { key: "smartmoney", label: "Flows", aria: "Smart Money Movement" },
  { key: "more", label: "More", aria: "More: AI Copilot, Options and futures lab, watchlists and settings" },
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
