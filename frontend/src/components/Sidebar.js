import React, { useState } from "react";
import {
  LayoutDashboard, Briefcase, Lightbulb, TrendingUp, Target, Users,
  Sparkles, Menu, X, ArrowLeft, User, Globe2, FlaskConical,
} from "lucide-react";

/**
 * Sidebar — three-mode navigation:
 *
 *   1. RETAIL (workspaceType !== "ADVISORY")
 *      → Dashboard · Plan Board · Portfolio · Insights · Goals
 *
 *   2. ADVISOR (ADVISORY, no client selected)
 *      → Advisor (client list + command center). Nothing else — an MFD
 *        operating on no specific client shouldn't see their personal
 *        retail tabs; those belong inside a client context.
 *
 *   3. CLIENT-CONTEXT (ADVISORY, impersonating a client)
 *      → "Back to clients" pill + client header + client-scoped tabs:
 *        Client 360 · Plan Board · Portfolio · Insights · Goals
 *
 * `Dashboard.js` passes:
 *   - workspaceType: "INDIVIDUAL" | "ADVISORY"
 *   - activeProfileName: string when impersonating, otherwise null
 *   - onExitProfile: () => void — clears impersonation + returns to Advisor
 */

// Retail (non-MFD) primary nav.
const RETAIL_NAV = [
  { id: "overview",         label: "Dashboard",       icon: LayoutDashboard },
  { id: "market",           label: "Market",          icon: Globe2, badge: "NEW" },
  { id: "strategy_builder", label: "Strategy Builder", icon: FlaskConical, badge: "BETA" },
  { id: "plan_board",       label: "Plan Board",      icon: TrendingUp, badge: "V2"  },
  { id: "portfolio",        label: "Portfolio",       icon: Briefcase },
  { id: "insights",         label: "Insights",        icon: Lightbulb },
  { id: "goals",            label: "Goals",           icon: Target },
];

// Tabs shown inside a client context (once the MFD has impersonated).
const CLIENT_NAV = [
  { id: "snapshot",         label: "Client 360",       icon: Sparkles, badge: "NEW" },
  { id: "market",           label: "Market",           icon: Globe2 },
  { id: "strategy_builder", label: "Strategy Builder", icon: FlaskConical, badge: "BETA" },
  { id: "plan_board",       label: "Plan Board",       icon: TrendingUp },
  { id: "portfolio",        label: "Portfolio",        icon: Briefcase },
  { id: "insights",         label: "Insights",         icon: Lightbulb },
  { id: "goals",            label: "Goals",            icon: Target },
];

// Advisor-only nav (no client selected).
const ADVISOR_NAV = [
  { id: "advisor",          label: "Advisor",          icon: Users, badge: "MFD" },
  { id: "market",           label: "Market",           icon: Globe2, badge: "NEW" },
  { id: "strategy_builder", label: "Strategy Builder", icon: FlaskConical, badge: "BETA" },
];

const Sidebar = ({
  activeTab, setActiveTab,
  workspaceType, activeProfileName, onExitProfile,
}) => {
  const [mobileOpen, setMobileOpen] = useState(false);

  const isAdvisor     = workspaceType === "ADVISORY";
  const isImpersonating = Boolean(activeProfileName);

  let navItems;
  let mode; // "retail" | "advisor" | "client"
  if (!isAdvisor) {
    navItems = RETAIL_NAV;
    mode = "retail";
  } else if (isImpersonating) {
    navItems = CLIENT_NAV;
    mode = "client";
  } else {
    navItems = ADVISOR_NAV;
    mode = "advisor";
  }

  const handleNav = (id) => {
    setActiveTab(id);
    setMobileOpen(false);
  };

  const handleExit = () => {
    onExitProfile?.();
    setMobileOpen(false);
  };

  return (
    <>
      <button
        data-testid="mobile-menu-toggle"
        className="fixed top-4 left-4 z-50 md:hidden w-10 h-10 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl flex items-center justify-center shadow-sm"
        onClick={() => setMobileOpen(!mobileOpen)}
      >
        {mobileOpen ? <X className="w-5 h-5 text-slate-700 dark:text-slate-200" /> : <Menu className="w-5 h-5 text-slate-700 dark:text-slate-200" />}
      </button>

      {mobileOpen && (
        <div className="fixed inset-0 bg-black/20 z-30 md:hidden" onClick={() => setMobileOpen(false)} />
      )}

      <aside
        data-testid="sidebar"
        data-sidebar-mode={mode}
        className={`fixed top-0 left-0 h-full w-64 bg-white dark:bg-slate-900 border-r border-slate-100 dark:border-slate-800 z-40 flex flex-col transition-transform duration-300 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        } md:translate-x-0`}
      >
        {/* Logo */}
        <div className="p-6 flex items-center gap-3">
          <div className="w-9 h-9 bg-emerald-600 rounded-xl flex items-center justify-center">
            <TrendingUp className="w-5 h-5 text-white" strokeWidth={2.5} />
          </div>
          <span className="text-lg font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            nivesh.ai
          </span>
        </div>

        {/* Client context header — only in client mode */}
        {mode === "client" && (
          <div className="px-3 pb-2" data-testid="sidebar-client-context">
            <button
              type="button"
              onClick={handleExit}
              data-testid="sidebar-back-to-clients"
              className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium text-indigo-700 dark:text-indigo-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 transition-colors mb-2"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              Back to client list
            </button>
            <div
              className="rounded-xl bg-gradient-to-br from-indigo-50 to-white dark:from-indigo-900/30 dark:to-slate-900 border border-indigo-200 dark:border-indigo-800 p-3 flex items-center gap-2.5"
              data-testid="sidebar-client-header"
            >
              <div className="w-9 h-9 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-900/60 dark:text-indigo-300 flex items-center justify-center text-sm font-bold flex-shrink-0">
                {(activeProfileName || "?").slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0">
                <div className="text-[9px] uppercase tracking-wider font-bold text-indigo-600 dark:text-indigo-400">Viewing</div>
                <div className="text-xs font-semibold text-slate-800 dark:text-slate-100 truncate">
                  {activeProfileName}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Nav label for advisor mode to make the intent explicit */}
        {mode === "advisor" && (
          <div className="px-6 pb-1 text-[9px] uppercase tracking-wider font-bold text-slate-400">
            Advisor workspace
          </div>
        )}
        {mode === "client" && (
          <div className="px-6 pb-1 pt-2 text-[9px] uppercase tracking-wider font-bold text-indigo-500 dark:text-indigo-400">
            Client workspace
          </div>
        )}

        <nav className="flex-1 px-3 mt-1 overflow-y-auto">
          {navItems.map(item => (
            <button
              key={item.id}
              data-testid={`nav-${item.id}`}
              onClick={() => handleNav(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl mb-1 transition-all duration-200 text-left ${
                activeTab === item.id
                  ? "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-medium"
                  : "text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 hover:text-slate-700 dark:hover:text-slate-200"
              }`}
            >
              <item.icon className="w-5 h-5" strokeWidth={1.5} />
              <span className="text-sm flex-1">{item.label}</span>
              {item.badge && (
                <span className="text-[10px] font-bold bg-emerald-600 text-white px-2 py-0.5 rounded-full">
                  {item.badge}
                </span>
              )}
            </button>
          ))}
        </nav>

        {/* Footer hint — swap copy per mode */}
        <div className="p-4 text-[11px] text-slate-400 dark:text-zinc-600">
          {mode === "advisor" && (
            <div className="flex items-start gap-1.5">
              <User className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
              <span>Pick a client from the Advisor page to open their portfolio, insights, goals & plan.</span>
            </div>
          )}
          {mode === "retail" && (
            <span>Use the avatar in the top-right for Family, Risk Profile, Admin &amp; Sign Out.</span>
          )}
          {mode === "client" && (
            <span>All edits apply to this client. Exit above to switch.</span>
          )}
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
