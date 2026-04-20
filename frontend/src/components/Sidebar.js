import React, { useState } from "react";
import { LayoutDashboard, Briefcase, Lightbulb, TrendingUp, Menu, X } from "lucide-react";

/**
 * Slim sidebar — primary navigation only.
 * Secondary items (Family, Risk Profile, Admin, Theme, Sign Out) live in
 * `UserProfileDropdown` at the top-right of the page.
 */
const navItems = [
  { id: "overview", label: "Dashboard", icon: LayoutDashboard },
  { id: "plan_board", label: "Plan Board", icon: TrendingUp, badge: "V2" },
  { id: "portfolio", label: "Portfolio", icon: Briefcase },
  { id: "insights", label: "Insights", icon: Lightbulb },
];

const Sidebar = ({ activeTab, setActiveTab }) => {
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleNav = (id) => {
    setActiveTab(id);
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
        className={`fixed top-0 left-0 h-full w-64 bg-white dark:bg-slate-900 border-r border-slate-100 dark:border-slate-800 z-40 flex flex-col transition-transform duration-300 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        } md:translate-x-0`}
      >
        <div className="p-6 flex items-center gap-3">
          <div className="w-9 h-9 bg-emerald-600 rounded-xl flex items-center justify-center">
            <TrendingUp className="w-5 h-5 text-white" strokeWidth={2.5} />
          </div>
          <span className="text-lg font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            nivesh.ai
          </span>
        </div>

        <nav className="flex-1 px-3 mt-2">
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

        <div className="p-4 text-[11px] text-slate-400 dark:text-zinc-600">
          Use the avatar in the top-right for Family, Risk Profile, Admin &amp; Sign Out.
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
