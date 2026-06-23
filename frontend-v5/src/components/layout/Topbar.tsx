import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Settings, ShieldCheck, Server, Bug, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useMe, useLogout } from "@/hooks/use-auth";

const TITLE_MAP: Record<string, string> = {
  "/dashboard":       "Dashboard",
  "/markets":         "Markets",
  "/advisor":         "Advisor",
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
  const navigate = useNavigate();
  const { data: me } = useMe();
  const logout = useLogout();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Match on prefix so nested routes (e.g. /settings/profile) still resolve
  const title =
    TITLE_MAP[pathname] ??
    Object.entries(TITLE_MAP).find(([k]) => pathname.startsWith(k + "/"))?.[1] ??
    "Nivesh";

  // Close the account menu on outside click
  useEffect(() => {
    if (!menuOpen) return;
    function handleOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [menuOpen]);

  // Close on route change
  useEffect(() => { setMenuOpen(false); }, [pathname]);

  const initials = me?.name
    ? me.name.split(" ").map((w: string) => w[0]).join("").slice(0, 2).toUpperCase()
    : "?";

  const go = (to: string) => { setMenuOpen(false); navigate(to); };

  return (
    <header
      className={cn(
        "sticky top-0 z-30 bg-bg/85 backdrop-blur border-b border-hairline",
        "flex items-center gap-3 px-5 h-14",
        className,
      )}
    >
      <span className="nv-mark" style={{ width: 28, height: 28, fontSize: 17 }}>न</span>
      <span className="font-display text-lg tracking-tightish">{title}</span>

      {/* Account menu — replaces the old hamburger drawer; keeps Settings,
          admin consoles and Sign out reachable on mobile. */}
      <div className="ml-auto relative" ref={menuRef}>
        <button
          type="button"
          aria-label="Account menu"
          aria-expanded={menuOpen}
          aria-haspopup="menu"
          onClick={() => setMenuOpen((v) => !v)}
          className={cn(
            "grid place-items-center rounded-md transition-colors",
            menuOpen && "bg-surface-1",
          )}
        >
          <Avatar className="h-8 w-8 rounded-md">
            <AvatarFallback className="rounded-md text-sm">{initials}</AvatarFallback>
          </Avatar>
        </button>

        {menuOpen && (
          <div
            role="menu"
            className="absolute right-0 top-full mt-2 w-56 bg-bg border border-hairline rounded-lg shadow-lg overflow-hidden z-50"
          >
            <div className="px-4 py-3 border-b border-hairline">
              <div className="text-[13px] font-medium truncate">{me?.name ?? "—"}</div>
              <div className="text-[11px] text-ink-3 truncate">{me?.email ?? ""}</div>
            </div>

            <div className="py-1">
              <button
                role="menuitem"
                onClick={() => go("/settings")}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-[13px] text-ink-2 hover:bg-surface-2 transition-colors text-left"
              >
                <Settings className="h-3.5 w-3.5" />
                Settings
              </button>

              {me?.is_admin && (
                <>
                  <div className="h-px bg-hairline mx-3 my-1" />
                  <div className="px-4 py-1.5 font-mono text-[9px] uppercase tracking-[.14em] text-ink-4">
                    Admin
                  </div>
                  <button
                    role="menuitem"
                    onClick={() => go("/admin")}
                    className="w-full flex items-center gap-2.5 px-4 py-2.5 text-[13px] text-ink-2 hover:bg-surface-2 transition-colors text-left"
                  >
                    <ShieldCheck className="h-3.5 w-3.5" />
                    Admin Console
                  </button>
                  <button
                    role="menuitem"
                    onClick={() => go("/nidp")}
                    className="w-full flex items-center gap-2.5 px-4 py-2.5 text-[13px] text-ink-2 hover:bg-surface-2 transition-colors text-left"
                  >
                    <Server className="h-3.5 w-3.5" />
                    NIDP Console
                  </button>
                  <button
                    role="menuitem"
                    onClick={() => go("/work")}
                    className="w-full flex items-center gap-2.5 px-4 py-2.5 text-[13px] text-ink-2 hover:bg-surface-2 transition-colors text-left"
                  >
                    <Bug className="h-3.5 w-3.5" />
                    Issues
                  </button>
                </>
              )}

              <div className="h-px bg-hairline mx-3 my-1" />
              <button
                role="menuitem"
                onClick={() => logout.mutate()}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-[13px] text-red-400 hover:bg-surface-2 transition-colors text-left"
              >
                <LogOut className="h-3.5 w-3.5" />
                Sign out
              </button>
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
