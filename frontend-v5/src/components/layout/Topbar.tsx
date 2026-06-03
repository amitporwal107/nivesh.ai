import { useState } from "react";
import { useLocation } from "react-router-dom";
import { Menu } from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileNavDrawer } from "./MobileNavDrawer";

const TITLE_MAP: Record<string, string> = {
  "/dashboard":       "Dashboard",
  "/ai-insights":     "AI Insights",
  "/risk":            "Risk",
  "/performance":     "Performance",
  "/goals":           "Goals",
  "/tax":             "Tax",
  "/plan":            "Plan board",
  "/portfolio":       "Portfolio",
  "/chat":            "Chat",
  "/recommendations": "Recommendations",
  "/pro-trader":      "Pro Trader",
  "/settings":        "Settings",
  "/onboarding":      "Onboarding",
  "/admin":           "Admin",
  "/nidp":            "NIDP",
  "/diagnostics":     "Diagnostics",
};

export function Topbar({ className }: { className?: string }) {
  const { pathname } = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Match on prefix so nested routes (e.g. /settings/profile) still resolve
  const title =
    TITLE_MAP[pathname] ??
    Object.entries(TITLE_MAP).find(([k]) => pathname.startsWith(k + "/"))?.[1] ??
    "Nivesh";

  return (
    <>
      <header
        className={cn(
          "sticky top-0 z-30 bg-bg/85 backdrop-blur border-b border-hairline",
          "flex items-center gap-3 px-5 h-14",
          className,
        )}
      >
        <button
          type="button"
          aria-label="Open menu"
          aria-expanded={drawerOpen}
          aria-controls="mobile-nav-drawer"
          onClick={() => setDrawerOpen(true)}
          className="grid place-items-center h-9 w-9 rounded-md text-ink-2 hover:bg-surface-2 transition-colors"
        >
          <Menu className="h-5 w-5" />
        </button>
        <span className="font-display text-lg tracking-tightish">{title}</span>
        <span className="ml-auto grid place-items-center h-8 w-8 rounded-md bg-ink text-on-accent font-display text-base leading-none">
          न
        </span>
      </header>

      <MobileNavDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </>
  );
}
