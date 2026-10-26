/**
 * Smart trading desk — the breadcrumb bar: "Trading desk › the steps taken › here" (rules in desk-trail.ts).
 * Every step is a button that returns to that view as it was left; "Trading desk" opens the Overview and starts
 * the trail again; the current view is plain text marked aria-current="page". On a phone the row scrolls
 * sideways and starts scrolled to its end, so the current view is always in sight. Reads nothing.
 */
import { useLayoutEffect, useRef } from "react";
import type { Crumb } from "./desk-trail";

const sep = <span aria-hidden style={{ color: "var(--cp-ink-4)", fontSize: 12 }}>›</span>;

const linkStyle = {
  padding: "2px 0", border: 0, background: "none", cursor: "pointer", font: "inherit", color: "var(--cp-ink-2)",
  textDecoration: "underline", textDecorationColor: "var(--line-2)", textUnderlineOffset: 3,
} as const;

export function DeskTrail({ trail, here, onRoot, onCrumb }: { trail: Crumb[]; here: string; onRoot: () => void; onCrumb: (index: number) => void }) {
  const box = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const el = box.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [trail, here]);
  return (
    <nav ref={box} aria-label="Breadcrumb" data-testid="desk-trail" data-depth={trail.length} className="cp-scroll overflow-x-auto" style={{ minWidth: 0 }}>
      <ol className="m-0 flex items-center p-0" style={{ listStyle: "none", gap: 8, whiteSpace: "nowrap", fontSize: 12.5, lineHeight: 1.4 }}>
        <li className="flex items-center">
          <button type="button" data-testid="desk-trail-root" onClick={onRoot} style={linkStyle}>Trading desk</button>
        </li>
        {trail.map((c, i) => (
          <li key={`${c.key}-${i}`} className="flex items-center" style={{ gap: 8 }}>
            {sep}
            <button type="button" data-testid={`desk-trail-crumb-${i}`} onClick={() => onCrumb(i)} style={linkStyle}>{c.label}</button>
          </li>
        ))}
        <li className="flex items-center" style={{ gap: 8 }}>
          {sep}
          <span data-testid="desk-trail-here" aria-current="page" style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{here}</span>
        </li>
      </ol>
    </nav>
  );
}
