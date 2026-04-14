import React, { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { LayoutDashboard, Briefcase, MessageSquare, Lightbulb, LogOut, TrendingUp, Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

const navItems = [
  { id: "overview", label: "Dashboard", icon: LayoutDashboard },
  { id: "portfolio", label: "Portfolio", icon: Briefcase },
  { id: "chat", label: "AI Chat", icon: MessageSquare },
  { id: "insights", label: "Insights", icon: Lightbulb },
];

const Sidebar = ({ activeTab, setActiveTab, user }) => {
  const { logout } = useAuth();
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
      {/* Mobile toggle */}
      <button
        data-testid="mobile-menu-toggle"
        className="fixed top-4 left-4 z-50 md:hidden w-10 h-10 bg-white border border-slate-200 rounded-xl flex items-center justify-center shadow-sm"
        onClick={() => setMobileOpen(!mobileOpen)}
      >
        {mobileOpen ? <X className="w-5 h-5 text-slate-700" /> : <Menu className="w-5 h-5 text-slate-700" />}
      </button>

      {/* Overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 bg-black/20 z-30 md:hidden" onClick={() => setMobileOpen(false)} />
      )}

      {/* Sidebar */}
      <aside
        data-testid="sidebar"
        className={`fixed top-0 left-0 h-full w-64 bg-white border-r border-slate-100 z-40 flex flex-col transition-transform duration-300 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        } md:translate-x-0`}
      >
        {/* Logo */}
        <div className="p-6 flex items-center gap-3">
          <div className="w-9 h-9 bg-emerald-600 rounded-xl flex items-center justify-center">
            <TrendingUp className="w-5 h-5 text-white" strokeWidth={2.5} />
          </div>
          <span className="text-lg font-semibold text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
            WealthPilot
          </span>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 mt-4">
          {navItems.map(item => (
            <button
              key={item.id}
              data-testid={`nav-${item.id}`}
              onClick={() => handleNav(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl mb-1 transition-all duration-200 text-left ${
                activeTab === item.id
                  ? "bg-emerald-50 text-emerald-700 font-medium"
                  : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
              }`}
            >
              <item.icon className="w-5 h-5" strokeWidth={1.5} />
              <span className="text-sm">{item.label}</span>
            </button>
          ))}
        </nav>

        {/* User + Logout */}
        <div className="p-4 border-t border-slate-100">
          <div className="flex items-center gap-3 mb-3 px-2">
            <Avatar className="w-9 h-9">
              <AvatarImage src={user?.picture} alt={user?.name} />
              <AvatarFallback className="bg-emerald-100 text-emerald-700 text-xs font-semibold">{initials}</AvatarFallback>
            </Avatar>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-slate-900 truncate">{user?.name}</p>
              <p className="text-xs text-slate-400 truncate">{user?.email}</p>
            </div>
          </div>
          <Button
            data-testid="logout-button"
            variant="ghost"
            onClick={logout}
            className="w-full justify-start text-slate-500 hover:text-red-600 hover:bg-red-50 rounded-xl h-10"
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
