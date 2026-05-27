import { NavLink } from "react-router-dom";
import { LayoutDashboard, PieChart, Sparkles, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

const TABS = [
  { to: "/dashboard",       label: "Home",     icon: LayoutDashboard },
  { to: "/portfolio",       label: "Portfolio", icon: PieChart },
  { to: "/recommendations", label: "Tips",     icon: Sparkles },
  { to: "/chat",            label: "Chat",     icon: MessageSquare },
];

export function MobileBottomNav({ className }: { className?: string }) {
  return (
    <nav
      aria-label="Primary"
      className={cn(
        "fixed bottom-0 inset-x-0 z-30 bg-bg/95 backdrop-blur border-t border-hairline",
        "flex justify-around items-stretch h-16 pb-2 pt-2",
        className,
      )}
    >
      {TABS.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            cn(
              "flex flex-1 flex-col items-center justify-center gap-1 text-[11px]",
              isActive ? "text-accent" : "text-ink-3",
            )
          }
        >
          <Icon className="h-5 w-5" aria-hidden />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
