import React, { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { LayoutDashboard, Briefcase, MessageSquare, Lightbulb, LogOut, TrendingUp, Menu, X, Users, Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

const navItems = [
  { id: "overview", label: "Dashboard", icon: LayoutDashboard },
  { id: "family", label: "Family", icon: Users },
  { id: "portfolio", label: "Portfolio", icon: Briefcase },
  { id: "chat", label: "AI Chat", icon: MessageSquare },
  { id: "insights", label: "Insights", icon: Lightbulb },
];

const Sidebar = ({ activeTab, setActiveTab, user }) => {
  const { logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleNav = (id) => {
    setActiveTab(id);
    setMobileOpen(false);
  };

  const initials = user?.name
    ? user.name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2)
    : "U";

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
              <span className="text-sm">{item.label}</span>
            </button>
          ))}
        </nav>

        {/* Theme Toggle */}
        <div className="px-4 mb-2">
          <button
            data-testid="theme-toggle"
            onClick={toggleTheme}
            className="w-full flex items-center gap-3 px-4 py-2.5 rounded-xl text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 transition-all"
          >
            {theme === "dark" ? <Sun className="w-4 h-4" strokeWidth={1.5} /> : <Moon className="w-4 h-4" strokeWidth={1.5} />}
            <span className="text-sm">{theme === "dark" ? "Light Mode" : "Dark Mode"}</span>
          </button>
        </div>

        <div className="p-4 border-t border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-3 mb-3 px-2">
            <Avatar className="w-9 h-9">
              <AvatarImage src={user?.picture} alt={user?.name} />
              <AvatarFallback className="bg-emerald-100 dark:bg-emerald-900 text-emerald-700 dark:text-emerald-400 text-xs font-semibold">{initials}</AvatarFallback>
            </Avatar>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-slate-900 dark:text-white truncate">{user?.name}</p>
              <p className="text-xs text-slate-400 truncate">{user?.email}</p>
            </div>
          </div>
          <Button
            data-testid="logout-button"
            variant="ghost"
            onClick={logout}
            className="w-full justify-start text-slate-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-xl h-10"
          >
            <LogOut className="w-4 h-4 mr-2" strokeWidth={1.5} />
            <span className="text-sm">Sign Out</span>
          </Button>
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
