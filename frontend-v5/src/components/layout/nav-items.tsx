import {
  LayoutDashboard, Sparkles, MessageSquare, Shield,
  Layers, TrendingUp, Target, Receipt, ClipboardList,
  ShieldCheck, Server, Bug, LineChart, Users, Contact, Globe,
  GraduationCap, FileSearch,
} from "lucide-react";

/**
 * Shared primary navigation config.
 *
 * Single source of truth for the section-level destinations rendered by both
 * the desktop {@link Sidebar} and the mobile {@link MobileSectionTabs} strip,
 * so the two never drift apart. Account-level actions (Settings, Sign out) are
 * NOT here — they live in the user/account menu on each surface. The mobile
 * bottom bar carries its own short list of primary tabs (see MobileBottomNav).
 */
export interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  group?: string;
}

/** Full personal-investor nav — shown to individual users, and to an advisor
 *  while they are impersonating a client (the client's own portfolio view). */
export const SECTION_NAV: NavItem[] = [
  { to: "/dashboard",       label: "Overview",        icon: LayoutDashboard, group: "Dashboards" },
  { to: "/markets",         label: "Markets",         icon: LineChart,       group: "Dashboards" },
  { to: "/funds/international", label: "Intl Funds",   icon: Globe,           group: "Dashboards" },
  { to: "/ai-insights",     label: "AI Insights",     icon: Layers,          group: "Dashboards" },
  { to: "/risk",            label: "Risk",            icon: Shield,          group: "Dashboards" },
  { to: "/performance",     label: "Performance",     icon: TrendingUp,      group: "Dashboards" },
  { to: "/goals",           label: "Goals",           icon: Target,          group: "Dashboards" },
  { to: "/tax",             label: "Tax",             icon: Receipt,         group: "Dashboards" },
  { to: "/advisor",         label: "Advisor",         icon: Users,           group: "Workspace"  },
  { to: "/plan",            label: "Plan board",      icon: ClipboardList,   group: "Workspace"  },
  { to: "/chat",            label: "Chat copilot",    icon: MessageSquare,   group: "Workspace"  },
  { to: "/recommendations", label: "Recommendations", icon: Sparkles,        group: "Workspace"  },
  // Pro Trader and Strategy Builder are intentionally hidden from the nav.
  // Their routes/pages remain (reachable by direct URL); only the entry points
  // are removed. Re-add the two NavItems here to restore them.
  { to: "/learn",           label: "Learn",           icon: GraduationCap,   group: "Workspace"  },
];

/** Research (Filings Intelligence) — a standalone surface. Appended to the nav
 *  ONLY for users with the `research`/`research_only` feature (see getSectionNav),
 *  so the `research` feature flag governs its visibility. */
const RESEARCH_NAV_ITEM: NavItem = {
  to: "/research", label: "Research", icon: FileSearch, group: "Workspace",
};

/** Reduced nav for an advisor at the workspace root (NOT impersonating a
 *  client). The personal-investor dashboards are hidden until the advisor opens
 *  a client, at which point SECTION_NAV (the client's full view) is shown. */
export const ADVISOR_NAV: NavItem[] = [
  { to: "/markets",     label: "Markets",          icon: LineChart,     group: "Dashboards" },
  { to: "/advisor",     label: "Advisor Workspace", icon: Users,        group: "Workspace"  },
  { to: "/client-360",  label: "Client 360",       icon: Contact,       group: "Workspace"  },
  { to: "/plan",        label: "Plan board",       icon: ClipboardList, group: "Workspace"  },
  { to: "/chat",        label: "Chat copilot",     icon: MessageSquare, group: "Workspace"  },
  { to: "/learn",       label: "Learn",            icon: GraduationCap, group: "Workspace"  },
];

/** Pick the primary nav for the current user. An advisor at their workspace
 *  root (workspace_type === "ADVISORY" and NOT impersonating) gets the reduced
 *  advisor nav. The moment they open a client (activeProfileId set) — or for any
 *  individual user — the full personal nav is shown. activeProfileId is the
 *  authoritative "am I inside a client?" signal; workspace_type stays "ADVISORY"
 *  for the advisor account either way, so it can't be used alone. */
export function getSectionNav(
  workspaceType: string | null | undefined,
  activeProfileId?: string | null,
  features?: Record<string, boolean>,
): NavItem[] {
  const base = activeProfileId                        // advisor inside a client → personal view
    ? SECTION_NAV
    : (workspaceType || "").toUpperCase() === "ADVISORY" ? ADVISOR_NAV : SECTION_NAV;
  // The Research entry appears only when the user has the `research` (or
  // `research_only`) feature — the flag governs its visibility. Absent features
  // (older backend) → hidden, the safe default.
  const hasResearch = !!(features?.research || features?.research_only);
  return hasResearch ? [...base, RESEARCH_NAV_ITEM] : base;
}

/** Admin destinations. No longer rendered in the primary sidebar — surfaced in
 *  Settings (and the account menu) instead. Exported for those consumers. */
export function getAdminNav(isAdmin: boolean | undefined): NavItem[] {
  if (!isAdmin) return [];
  return [
    { to: "/work",  label: "Issues",        icon: Bug,         group: "Admin" },
    { to: "/admin", label: "Admin Console", icon: ShieldCheck, group: "Admin" },
    { to: "/nidp",  label: "NIDP Console",  icon: Server,      group: "Admin" },
  ];
}

/** Group a flat NavItem list by its `group` field, preserving first-seen order. */
export function groupNav(items: NavItem[]): Array<{ name: string; items: NavItem[] }> {
  const groups: Array<{ name: string; items: NavItem[] }> = [];
  for (const item of items) {
    const g = item.group ?? "Other";
    const existing = groups.find((x) => x.name === g);
    if (existing) existing.items.push(item);
    else groups.push({ name: g, items: [item] });
  }
  return groups;
}
