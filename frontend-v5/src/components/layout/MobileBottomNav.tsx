import { NavLink } from "react-router-dom";
import { LayoutDashboard, PieChart, Sparkles, MessageSquare, Users, Contact } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMe } from "@/hooks/use-auth";
import { useImpersonationStore } from "@/stores/impersonation.store";

const PERSONAL_TABS = [
  { to: "/dashboard",       label: "Home",     icon: LayoutDashboard },
  { to: "/portfolio",       label: "Portfolio", icon: PieChart },
  { to: "/recommendations", label: "Tips",     icon: Sparkles },
  { to: "/chat",            label: "Chat",     icon: MessageSquare },
];

// Advisor-root primary tabs — mirrors the reduced sidebar nav so thumb-reach
// destinations match what the advisor can actually see.
const ADVISOR_TABS = [
  { to: "/advisor",    label: "Clients",  icon: Users },
  { to: "/client-360", label: "360",      icon: Contact },
  { to: "/plan",       label: "Plan",     icon: PieChart },
  { to: "/chat",       label: "Chat",     icon: MessageSquare },
];

export function MobileBottomNav({ className }: { className?: string }) {
  const { data: me } = useMe();
  const activeProfileId = useImpersonationStore((s) => s.profileId);
  const TABS = (me?.workspaceType || "").toUpperCase() === "ADVISORY" && !activeProfileId ? ADVISOR_TABS : PERSONAL_TABS;
  return (
    <nav
      aria-label="Primary"
      className={cn(
        "fixed bottom-0 inset-x-0 z-30 bg-bg/95 backdrop-blur border-t border-hairline pb-safe",
        className,
      )}
    >
      {/* Fixed-height tap row; the outer nav carries the safe-area inset below it
          so the gesture bar / home indicator never overlaps the tabs. */}
      <div className="flex justify-around items-stretch h-16 pt-2 pb-2">
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
      </div>
    </nav>
  );
}
