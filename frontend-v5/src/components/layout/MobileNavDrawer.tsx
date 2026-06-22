import { useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  LayoutDashboard, PieChart, Sparkles, MessageSquare, Shield,
  Settings, Layers, TrendingUp, Target, Receipt, ClipboardList, Briefcase,
  ShieldCheck, Server, BarChart2, LineChart, X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useMe } from "@/hooks/use-auth";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

const NAV = [
  { to: "/dashboard",       label: "Overview",          icon: LayoutDashboard, group: "Dashboards" },
  { to: "/markets",         label: "Markets",           icon: LineChart,       group: "Dashboards" },
  { to: "/ai-insights",     label: "AI Insights",       icon: Layers,          group: "Dashboards" },
  { to: "/risk",            label: "Risk",              icon: Shield,          group: "Dashboards" },
  { to: "/performance",     label: "Performance",       icon: TrendingUp,      group: "Dashboards" },
  { to: "/goals",           label: "Goals",             icon: Target,          group: "Dashboards" },
  { to: "/tax",             label: "Tax",               icon: Receipt,         group: "Dashboards" },
  { to: "/plan",            label: "Plan board",        icon: ClipboardList,   group: "Workspace"  },
  { to: "/portfolio",       label: "Portfolio Page",    icon: Briefcase,       group: "Workspace"  },
  { to: "/chat",            label: "Chat copilot",      icon: MessageSquare,   group: "Workspace"  },
  { to: "/recommendations", label: "Recommendations",   icon: Sparkles,        group: "Workspace"  },
  { to: "/pro-trader",      label: "Pro Trader",        icon: BarChart2,       group: "Workspace"  },
  { to: "/settings",        label: "Settings",          icon: Settings,        group: "Account"    },
];

interface Props {
  open: boolean;
  onClose: () => void;
}

export function MobileNavDrawer({ open, onClose }: Props) {
  const { data: me } = useMe();
  const { pathname } = useLocation();

  // Close on route change
  useEffect(() => { onClose(); }, [pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  // Lock body scroll while open
  useEffect(() => {
    if (open) document.body.style.overflow = "hidden";
    else document.body.style.overflow = "";
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  const adminNav = me?.is_admin
    ? [
        { to: "/admin", label: "Admin Console", icon: ShieldCheck, group: "Admin" },
        { to: "/nidp",  label: "NIDP Console",  icon: Server,      group: "Admin"  },
      ]
    : [];

  const allNav = [...NAV, ...adminNav];
  const groups: Array<{ name: string; items: typeof allNav }> = [];
  for (const item of allNav) {
    const g = item.group ?? "Other";
    const existing = groups.find((x) => x.name === g);
    if (existing) existing.items.push(item);
    else groups.push({ name: g, items: [item] });
  }

  const initials = me?.name
    ? me.name.split(" ").map((w: string) => w[0]).join("").slice(0, 2).toUpperCase()
    : "?";

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
        aria-hidden="true"
        onClick={onClose}
      />

      {/* Drawer */}
      <div
        className="fixed left-0 top-0 h-full z-50 flex flex-col w-[280px] bg-bg border-r border-hairline overflow-y-auto"
        role="dialog"
        aria-modal="true"
        aria-label="Navigation menu"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-4 border-b border-hairline shrink-0">
          <div className="flex items-center gap-2.5">
            <span className="nv-mark" style={{ width: 28, height: 28, fontSize: 17 }}>न</span>
            <span className="font-display text-[18px] tracking-tightish">Nivesh</span>
          </div>
          <button
            type="button"
            aria-label="Close menu"
            onClick={onClose}
            className="grid place-items-center h-8 w-8 rounded-md text-ink-3 hover:bg-surface-2 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-4 flex flex-col gap-5 overflow-y-auto" aria-label="Primary">
          {groups.map((g) => (
            <div key={g.name} className="flex flex-col gap-0.5">
              <div className="font-mono text-[9.5px] uppercase tracking-[.16em] text-ink-4 px-3.5 pb-1.5">
                {g.name}
              </div>
              {g.items.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 px-3.5 py-2.5 text-[13.5px] rounded-md text-ink-2 hover:bg-surface-2 transition-colors",
                      isActive && "bg-surface-1 text-ink border border-hairline font-medium",
                    )
                  }
                >
                  <Icon className="h-4 w-4" aria-hidden />
                  <span>{label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="shrink-0 px-4 py-4 border-t border-hairline flex items-center gap-3">
          <Avatar className="h-8 w-8 rounded-md">
            <AvatarFallback className="rounded-md text-sm">{initials}</AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <div className="text-[13px] font-medium truncate">{me?.name ?? "—"}</div>
            <div className="text-[10px] font-mono text-ink-3 truncate">{me?.email ?? ""}</div>
          </div>
        </div>
      </div>
    </>
  );
}
