/**
 * Smart trading desk — the breadcrumb: the LOCATION, "Trading desk › tab › view" (the redesign of 2026-10-27,
 * docs/desk_redesign_20261027/PLAN.md §1: at most two levels, and the crumbs say where you are, not the clicks that
 * led here). "Trading desk" opens Market Overview; the tab crumb opens the tab's first view; the current place is
 * plain text marked aria-current="page". In the design's mono type (Nivesh Trader Workspace). On a phone the row
 * scrolls sideways and starts scrolled to its end. Reads nothing.
 */
import { useLayoutEffect, useRef, type CSSProperties } from "react";

const sep = <span aria-hidden style={{ color: "var(--cp-ink-4)" }}>›</span>;

const linkStyle: CSSProperties = {
  padding: "2px 0", border: 0, background: "none", cursor: "pointer", font: "inherit", letterSpacing: "inherit", color: "var(--mint)",
};

/**
 * `tab` is the tab's name; `view` the view's, or null for a one-page tab (then the tab is the current place).
 * `onTab` opens the tab's first view; it is only a link when a view follows.
 */
export function DeskTrail({ tab, view, onRoot, onTab }: { tab: string; view: string | null; onRoot: () => void; onTab: () => void }) {
  const box = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const el = box.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [tab, view]);
  const here = view ?? tab;
  return (
    <nav ref={box} aria-label="Breadcrumb" data-testid="desk-trail" data-depth={view ? 2 : 1} className="cp-scroll overflow-x-auto" style={{ minWidth: 0 }}>
      <ol className="m-0 flex items-center p-0" style={{ listStyle: "none", gap: 8, whiteSpace: "nowrap", fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.06em", lineHeight: 1.5 }}>
        <li aria-hidden className="flex items-center" style={{ color: "var(--cp-ink-4)" }}>▸</li>
        <li className="flex items-center">
          <button type="button" data-testid="desk-trail-root" onClick={onRoot} style={linkStyle}>Trading desk</button>
        </li>
        {view && (
          <li className="flex items-center" style={{ gap: 8 }}>
            {sep}
            <button type="button" data-testid="desk-trail-tab" onClick={onTab} style={linkStyle}>{tab}</button>
          </li>
        )}
        <li className="flex items-center" style={{ gap: 8 }}>
          {sep}
          <span data-testid="desk-trail-here" aria-current="page" style={{ color: "var(--cp-ink)", fontWeight: 600 }}>{here}</span>
        </li>
      </ol>
    </nav>
  );
}
