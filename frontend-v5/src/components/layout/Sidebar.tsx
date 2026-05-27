import { NavLink } from "react-router-dom";
import { LayoutDashboard, PieChart, Sparkles, MessageSquare, Shield, Settings, Layers, GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  group?: string;
}

const NAV: NavItem[] = [
  { to: "/dashboard",       label: "Dashboard",        icon: LayoutDashboard, group: "Overview" },
  { to: "/portfolio",       label: "Portfolio",        icon: PieChart,        group: "Overview" },
  { to: "/concentration",   label: "Concentration",    icon: Layers,          group: "Risk" },
  { to: "/diversification", label: "Diversification",  icon: GitBranch,       group: "Risk" },
  { to: "/risk",            label: "Risk analysis",    icon: Shield,          group: "Risk" },
  { to: "/recommendations", label: "Recommendations",  icon: Sparkles,        group: "Act" },
  { to: "/chat",            label: "Chat",             icon: MessageSquare,   group: "Act" },
  { to: "/settings",        label: "Settings",         icon: Settings,        group: "You" },
];

export function Sidebar({ className }: { className?: string }) {
  // group items by their `group` field while preserving order
  const groups: Array<{ name: string; items: NavItem[] }> = [];
  NAV.forEach((item) => {
    const g = item.group ?? "Other";
    const existing = groups.find((x) => x.name === g);
    if (existing) existing.items.push(item);
    else groups.push({ name: g, items: [item] });
  });

  return (
    <aside
      className={cn(
        "w-[224px] shrink-0 flex-col border-r border-hairline bg-bg px-3 py-6 sticky top-0 h-screen",
        className,
      )}
    >
      <div className="flex items-center gap-3 px-3 pb-7">
        <span className="grid place-items-center h-8 w-8 rounded-md bg-ink text-on-accent font-display text-[19px] leading-none">
          न
        </span>
        <span className="font-display text-[19px] tracking-tightish">Nivesh</span>
      </div>

      <nav className="flex flex-col gap-5" aria-label="Primary">
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
                    "flex items-center gap-3 px-3.5 py-2 text-[13.5px] rounded-md text-ink-2 hover:bg-surface-2 transition-colors",
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

      <div className="mt-auto pt-4 border-t border-hairline flex items-center gap-3 px-2">
        <Avatar className="h-8 w-8 rounded-md">
          <AvatarFallback className="rounded-md text-sm">A</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <div className="text-[13px] font-medium truncate">Aarav Kumar</div>
          <div className="text-[10px] font-mono text-ink-3">Free plan</div>
        </div>
      </div>
    </aside>
  );
}
