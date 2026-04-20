import React, { useState, useRef, useEffect } from "react";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  Users, Shield, ShieldCheck, LogOut, Moon, Sun, ChevronDown, ChevronUp,
} from "lucide-react";

/**
 * Compact user-profile dropdown for the top-right of the dashboard.
 *
 * Contents:
 *   • User name + email (header)
 *   • Family  → setActiveTab('family')
 *   • Risk Profile → setActiveTab('risk_profile')
 *   • Admin (admin only) → setActiveTab('admin')
 *   • Light / Dark mode toggle
 *   • Sign Out
 */
const UserProfileDropdown = ({ user, activeTab, setActiveTab }) => {
  const { logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  // Close on outside click or Escape
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const initials = user?.name
    ? user.name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2)
    : "U";

  const go = (id) => {
    setActiveTab(id);
    setOpen(false);
  };

  const menuItems = [
    { id: "family", label: "Family", icon: Users },
    { id: "risk_profile", label: "Risk Profile", icon: Shield },
    ...(user?.is_admin ? [{ id: "admin", label: "Admin", icon: ShieldCheck }] : []),
  ];

  return (
    <div ref={wrapRef} className="relative" data-testid="user-profile-dropdown">
      <button
        data-testid="user-profile-trigger"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 pl-2 pr-3 py-1.5 rounded-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 hover:shadow-sm transition-all"
        aria-label="Open user menu"
      >
        <Avatar className="w-7 h-7">
          <AvatarImage src={user?.picture} alt={user?.name} />
          <AvatarFallback className="bg-emerald-100 dark:bg-emerald-900 text-emerald-700 dark:text-emerald-400 text-[10px] font-semibold">
            {initials}
          </AvatarFallback>
        </Avatar>
        <span className="hidden sm:inline text-sm font-medium text-slate-700 dark:text-slate-200 max-w-[120px] truncate">
          {user?.name?.split(" ")[0] || "User"}
        </span>
        {open ? (
          <ChevronUp className="w-4 h-4 text-slate-500" />
        ) : (
          <ChevronDown className="w-4 h-4 text-slate-500" />
        )}
      </button>

      {open && (
        <div
          data-testid="user-profile-menu"
          className="absolute right-0 top-[calc(100%+6px)] w-64 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 shadow-xl z-50 overflow-hidden"
        >
          {/* Header */}
          <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-800 flex items-center gap-3">
            <Avatar className="w-10 h-10">
              <AvatarImage src={user?.picture} alt={user?.name} />
              <AvatarFallback className="bg-emerald-100 dark:bg-emerald-900 text-emerald-700 dark:text-emerald-400 text-xs font-semibold">
                {initials}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-900 dark:text-white truncate">
                {user?.name || "User"}
              </p>
              <p className="text-xs text-slate-500 dark:text-zinc-400 truncate">
                {user?.email}
              </p>
              {user?.is_admin && (
                <span className="inline-block mt-0.5 px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300">
                  ADMIN
                </span>
              )}
            </div>
          </div>

          {/* Nav items */}
          <div className="py-1.5">
            {menuItems.map((m) => {
              const active = activeTab === m.id;
              const Icon = m.icon;
              return (
                <button
                  key={m.id}
                  data-testid={`user-menu-${m.id}`}
                  onClick={() => go(m.id)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left text-sm transition-colors ${
                    active
                      ? "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 font-medium"
                      : "text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800"
                  }`}
                >
                  <Icon className="w-4 h-4" strokeWidth={1.5} />
                  <span>{m.label}</span>
                </button>
              );
            })}
          </div>

          {/* Theme toggle */}
          <div className="border-t border-slate-100 dark:border-slate-800 py-1.5">
            <button
              data-testid="user-menu-theme-toggle"
              onClick={toggleTheme}
              className="w-full flex items-center gap-3 px-4 py-2.5 text-left text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800"
            >
              {theme === "dark" ? <Sun className="w-4 h-4" strokeWidth={1.5} /> : <Moon className="w-4 h-4" strokeWidth={1.5} />}
              <span>{theme === "dark" ? "Light Mode" : "Dark Mode"}</span>
            </button>
          </div>

          {/* Sign out */}
          <div className="border-t border-slate-100 dark:border-slate-800 py-1.5">
            <button
              data-testid="user-menu-signout"
              onClick={logout}
              className="w-full flex items-center gap-3 px-4 py-2.5 text-left text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
            >
              <LogOut className="w-4 h-4" strokeWidth={1.5} />
              <span>Sign Out</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default UserProfileDropdown;
