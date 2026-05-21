import React, { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useBreakpoint } from "../hooks/useBreakpoint";
import { usePersona } from "../adapters";
import MobileShell from "../components/layout/MobileShell";
import DesktopShell from "../components/layout/DesktopShell";

/**
 * Picks Mobile vs Desktop shell from the current breakpoint and provides persona context.
 * Hides bottom-nav on screens that need full-bleed (onboarding).
 */
export default function ResponsiveLayout() {
  const { isMobile, isTablet } = useBreakpoint();
  const { persona } = usePersona();
  const location = useLocation();

  // Scroll to top on route change
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);

  const hideBottomNav = location.pathname.includes("/onboarding");
  const collapsedSidebar = isTablet;

  if (isMobile) {
    return (
      <MobileShell hideBottomNav={hideBottomNav}>
        <Outlet context={{ persona, viewport: "mobile" }} />
      </MobileShell>
    );
  }

  return (
    <DesktopShell persona={persona} collapsedSidebar={collapsedSidebar}>
      <Outlet context={{ persona, viewport: "desktop" }} />
    </DesktopShell>
  );
}
