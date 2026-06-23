import { useEffect, useRef } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useMe } from "@/hooks/use-auth";
import { getSectionNav } from "./nav-items";

/**
 * MobileSectionTabs — the mobile section navigation, rendered as a sticky,
 * horizontally-scrollable strip of tabs under the Topbar (replaces the old
 * left-slide hamburger drawer). Tap a tab to switch sections; the page itself
 * still scrolls vertically. The bottom bar (MobileBottomNav) continues to carry
 * the few primary destinations for thumb reach.
 *
 * Shown only below `lg` — the desktop Sidebar owns navigation at ≥ lg.
 */
export function MobileSectionTabs({ className }: { className?: string }) {
  const { data: me } = useMe();
  const { pathname } = useLocation();
  const scrollerRef = useRef<HTMLDivElement>(null);

  const items = getSectionNav(me?.workspaceType);

  // Keep the active tab visible: scroll it into the centre when the route changes.
  useEffect(() => {
    const active = scrollerRef.current?.querySelector<HTMLElement>('[aria-current="page"]');
    active?.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
  }, [pathname]);

  return (
    <nav
      aria-label="Sections"
      className={cn(
        "sticky top-14 z-20 bg-bg/90 backdrop-blur border-b border-hairline",
        className,
      )}
    >
      <div
        ref={scrollerRef}
        className="no-scrollbar flex items-center gap-1.5 overflow-x-auto px-3 py-2"
      >
        {items.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3.5 py-1.5 text-[13px] transition-colors",
                isActive
                  ? "bg-surface-1 text-ink border border-hairline font-medium"
                  : "text-ink-3 hover:text-ink-2 hover:bg-surface-2",
              )
            }
          >
            <Icon className="h-3.5 w-3.5 shrink-0" />
            <span>{label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
