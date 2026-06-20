import { NavLink, useNavigate } from "react-router-dom";
import { useRef, useState, useEffect } from "react";
import {
  LayoutDashboard, Sparkles, MessageSquare, Shield,
  Settings, Layers, TrendingUp, Target, Receipt, ClipboardList, Wrench,
  ShieldCheck, Server, BarChart2, Bug, LogOut, ChevronUp,
  PanelLeftClose, PanelLeftOpen, LineChart,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useMe, useLogout } from "@/hooks/use-auth";
import { usePortfolioSummary } from "@/hooks/use-portfolio";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  group?: string;
}

const NAV: NavItem[] = [
  { to: "/dashboard",       label: "Overview",         icon: LayoutDashboard, group: "Dashboards" },
  { to: "/markets",         label: "Markets",          icon: LineChart,       group: "Dashboards" },
  { to: "/ai-insights",     label: "AI Insights",      icon: Layers,          group: "Dashboards" },
  { to: "/risk",            label: "Risk",             icon: Shield,          group: "Dashboards" },
  { to: "/performance",     label: "Performance",      icon: TrendingUp,      group: "Dashboards" },
  { to: "/goals",           label: "Goals",            icon: Target,          group: "Dashboards" },
  { to: "/tax",             label: "Tax",              icon: Receipt,         group: "Dashboards" },
  { to: "/plan",            label: "Plan board",       icon: ClipboardList,   group: "Workspace" },
  { to: "/portfolio",       label: "Portfolio builder", icon: Wrench,         group: "Workspace" },
  { to: "/chat",            label: "Chat copilot",     icon: MessageSquare,   group: "Workspace" },
  { to: "/recommendations", label: "Recommendations",  icon: Sparkles,        group: "Workspace" },
  { to: "/pro-trader",      label: "Pro Trader",       icon: BarChart2,       group: "Workspace" },
];

export function Sidebar({ className }: { className?: string }) {
  const { data: me } = useMe();
  const { data: summary } = usePortfolioSummary();
  const logout = useLogout();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Icon-only collapse, persisted across sessions.
  const [collapsed, setCollapsed] = useState<boolean>(
    () => localStorage.getItem("nv-sidebar-collapsed") === "1",
  );
  useEffect(() => {
    localStorage.setItem("nv-sidebar-collapsed", collapsed ? "1" : "0");
    if (collapsed) setMenuOpen(false);
  }, [collapsed]);

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

  const adminNav: NavItem[] = me?.is_admin
    ? [
        { to: "/work",  label: "Issues",         icon: Bug,         group: "Admin" },
        { to: "/admin", label: "Admin Console",  icon: ShieldCheck, group: "Admin" },
        { to: "/nidp",  label: "NIDP Console",   icon: Server,      group: "Admin" },
      ]
    : [];

  const allNav = [...NAV, ...adminNav];

  const groups: Array<{ name: string; items: NavItem[] }> = [];
  allNav.forEach((item) => {
    const g = item.group ?? "Other";
    const existing = groups.find((x) => x.name === g);
    if (existing) existing.items.push(item);
    else groups.push({ name: g, items: [item] });
  });

  const initials = me?.name
    ? me.name.split(" ").map((w: string) => w[0]).join("").slice(0, 2).toUpperCase()
    : "?";

  const portfolioLabel = summary?.totalValue
    ? `₹ ${(summary.totalValue / 100 / 1_00_000).toFixed(1)} L · NIDP ✓`
    : "";

  return (
    <aside
      className={cn(
        "shrink-0 flex-col border-r border-hairline bg-bg py-6 sticky top-0 h-screen transition-[width] duration-200",
        collapsed ? "w-[68px] px-2" : "w-[224px] px-3",
        className,
      )}
    >
      <div
        className={cn(
          "flex items-center pb-7",
          collapsed ? "flex-col gap-3 px-0" : "gap-3 px-3",
        )}
      >
        <span className="nv-mark" style={{ width: 32, height: 32, fontSize: 19 }}>
          न
        </span>
        {!collapsed && (
          <span className="font-display text-[19px] tracking-tightish flex-1">Nivesh</span>
        )}
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="p-1.5 rounded-md text-ink-4 hover:text-ink-2 hover:bg-surface-2 transition-colors"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
        </button>
      </div>

      <nav className={cn("flex flex-col", collapsed ? "gap-2" : "gap-5")} aria-label="Primary">
        {groups.map((g, gi) => (
          <div key={g.name} className="flex flex-col gap-0.5">
            {collapsed ? (
              gi > 0 && <div className="h-px bg-hairline mx-2 mb-1.5" />
            ) : (
              <div className="font-mono text-[9.5px] uppercase tracking-[.16em] text-ink-4 px-3.5 pb-1.5">
                {g.name}
              </div>
            )}
            {g.items.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                title={collapsed ? label : undefined}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 py-2 text-[13.5px] rounded-md text-ink-2 hover:bg-surface-2 transition-colors",
                    collapsed ? "justify-center px-0" : "px-3.5",
                    isActive && "bg-surface-1 text-ink border border-hairline font-medium",
                  )
                }
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden />
                {!collapsed && <span>{label}</span>}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* User menu */}
      <div className="mt-auto pt-4 border-t border-hairline relative" ref={menuRef}>
        {/* Dropdown panel — opens above the trigger */}
        {menuOpen && (
          <div className={cn(
            "absolute bottom-full mb-2 bg-bg border border-hairline rounded-lg shadow-lg overflow-hidden z-50",
            collapsed ? "left-0 w-56" : "left-0 right-0",
          )}>
            {/* User info header */}
            <div className="px-4 py-3 border-b border-hairline">
              <div className="text-[13px] font-medium truncate">{me?.name ?? "—"}</div>
              <div className="text-[11px] text-ink-3 truncate">{me?.email ?? ""}</div>
            </div>

            {/* Menu items */}
            <div className="py-1">
              <button
                onClick={() => { setMenuOpen(false); navigate("/settings"); }}
                className="w-full flex items-center gap-2.5 px-4 py-2 text-[13px] text-ink-2 hover:bg-surface-2 transition-colors text-left"
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
                    onClick={() => { setMenuOpen(false); navigate("/admin"); }}
                    className="w-full flex items-center gap-2.5 px-4 py-2 text-[13px] text-ink-2 hover:bg-surface-2 transition-colors text-left"
                  >
                    <ShieldCheck className="h-3.5 w-3.5" />
                    Admin Console
                  </button>
                  <button
                    onClick={() => { setMenuOpen(false); navigate("/nidp"); }}
                    className="w-full flex items-center gap-2.5 px-4 py-2 text-[13px] text-ink-2 hover:bg-surface-2 transition-colors text-left"
                  >
                    <Server className="h-3.5 w-3.5" />
                    NIDP Console
                  </button>
                  <button
                    onClick={() => { setMenuOpen(false); navigate("/work"); }}
                    className="w-full flex items-center gap-2.5 px-4 py-2 text-[13px] text-ink-2 hover:bg-surface-2 transition-colors text-left"
                  >
                    <Bug className="h-3.5 w-3.5" />
                    Issues
                  </button>
                </>
              )}

              <div className="h-px bg-hairline mx-3 my-1" />
              <button
                onClick={() => logout.mutate()}
                className="w-full flex items-center gap-2.5 px-4 py-2 text-[13px] text-red-400 hover:bg-surface-2 transition-colors text-left"
              >
                <LogOut className="h-3.5 w-3.5" />
                Sign out
              </button>
            </div>
          </div>
        )}

        {/* Trigger — click to toggle menu */}
        <button
          onClick={() => setMenuOpen((v) => !v)}
          title={collapsed ? me?.name ?? "Account" : undefined}
          className={cn(
            "w-full flex items-center gap-3 py-1.5 rounded-md hover:bg-surface-2 transition-colors",
            collapsed ? "justify-center px-0" : "px-2",
            menuOpen && "bg-surface-1",
          )}
        >
          <Avatar className="h-8 w-8 rounded-md shrink-0">
            <AvatarFallback className="rounded-md text-sm">{initials}</AvatarFallback>
          </Avatar>
          {!collapsed && (
            <>
              <div className="min-w-0 flex-1 text-left">
                <div className="text-[13px] font-medium truncate">{me?.name ?? "—"}</div>
                <div className="text-[10px] font-mono text-ink-3">{portfolioLabel}</div>
              </div>
              <ChevronUp
                className={cn(
                  "h-3.5 w-3.5 text-ink-4 shrink-0 transition-transform",
                  !menuOpen && "rotate-180",
                )}
              />
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
