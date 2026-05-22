import {
  Sparkles,
  LayoutGrid,
  PieChart,
  Shield,
  IndianRupee,
  TrendingUp,
  MessageSquare,
  UserCheck,
  Activity,
  Settings,
  User,
  Compass,
  Target,
  ListChecks,
  Layers,
} from "lucide-react";

/**
 * Single route registry driving:
 *  - <V3Router> route mounts
 *  - mobile BottomNav (first 5 with bottomNav=true)
 *  - desktop Sidebar groups
 *  - breadcrumbs / page titles
 */
export const ROUTES = [
  { path: "home",      title: "Today",         icon: Sparkles,      group: "workspace", bottomNav: true, bottomLabel: "Today" },
  { path: "dashboard", title: "Dashboard",     icon: LayoutGrid,    group: "workspace", bottomNav: true, bottomLabel: "Home" },
  { path: "portfolio", title: "Portfolio",     icon: PieChart,      group: "workspace", bottomNav: true, bottomLabel: "Portfolio" },
  { path: "portfolio/exposure",        title: "Exposure",        icon: Layers,        group: "analytics" },
  { path: "performance", title: "Performance", icon: TrendingUp,    group: "analytics" },
  { path: "risk",        title: "Risk & Stress", icon: Shield,      group: "analytics" },
  { path: "risk/stress", title: "Stress Test", group: "analytics" },
  { path: "tax",         title: "Tax",         icon: IndianRupee,   group: "analytics" },
  { path: "goals",       title: "Goals",       icon: Target,        group: "plan" },
  { path: "plans",       title: "Plan Board",  icon: ListChecks,    group: "plan" },
  { path: "chat",        title: "Copilot",     icon: MessageSquare, group: "workspace", bottomNav: true, bottomLabel: "Ask" },
  { path: "market",      title: "Market",      icon: Activity,      group: "workspace" },
  { path: "advisor",     title: "Advisor",     icon: UserCheck,     group: "workspace" },
  { path: "profile",     title: "Profile",     icon: User,          group: "you", bottomNav: true, bottomLabel: "You" },
  { path: "settings",    title: "Settings",    icon: Settings,      group: "you" },
  { path: "onboarding",  title: "Welcome",     icon: Compass,       group: "hidden" },
];

export function getRoute(path) {
  return ROUTES.find((r) => r.path === path);
}

export const BOTTOM_NAV = ROUTES.filter((r) => r.bottomNav);
