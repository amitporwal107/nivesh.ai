import React, { useState } from "react";
import { motion } from "framer-motion";
import {
  Plus, LayoutDashboard, MessageSquare, Briefcase, BarChart3,
  Target, Users, User, Settings, Zap, ChevronRight, Sparkles,
  Bell, ArrowRight, History, Lightbulb, TrendingUp, Globe2,
  FlaskConical, Terminal, LogOut, RefreshCw, Bot, ArrowLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

// Maps V2 screen IDs to V1 tab IDs
export const SCREEN_TO_TAB = {
  home:           "overview",
  copilot:        "chat",
  portfolio:      "portfolio",
  insights:       "insights",
  markets:        "market",
  plan_board:     "plan_board",
  goals:          "goals",
  family:         "family",
  profile:        "risk_profile",
  advisor:        "advisor",
  snapshot:       "snapshot",
  strategy:       "strategy_builder",
  admin:          "admin",
};

// Retail nav
const RETAIL_NAV = [
  { id: "home",        label: "Dashboard",        icon: LayoutDashboard },
  { id: "markets",     label: "Market Dashboard", icon: Globe2 },
  { id: "portfolio",   label: "Portfolio",        icon: Briefcase },
  { id: "insights",    label: "Insights",         icon: Lightbulb },
  { id: "plan_board",  label: "Plan Board",       icon: TrendingUp },
  { id: "goals",       label: "Goals",            icon: Target },
  { id: "strategy",    label: "Strategy Builder", icon: FlaskConical,   badge: "BETA" },
  { id: "copilot",     label: "Nivesh Copilot",   icon: Bot },
];

// Advisor nav — no Strategy Builder for advisors/PF managers
const ADVISOR_NAV = [
  { id: "advisor",   label: "Advisor",           icon: Users,  badge: "MFD" },
  { id: "markets",   label: "Market Dashboard",  icon: Globe2 },
  { id: "copilot",   label: "Nivesh Copilot",    icon: Bot },
];

// Client context nav (impersonation) — Strategy Builder available for client traders
const CLIENT_NAV = [
  { id: "snapshot",    label: "Client 360",       icon: Sparkles,    badge: "NEW" },
  { id: "markets",     label: "Market Dashboard", icon: Globe2 },
  { id: "portfolio",   label: "Portfolio",        icon: Briefcase },
  { id: "insights",    label: "Insights",         icon: Lightbulb },
  { id: "plan_board",  label: "Plan Board",       icon: TrendingUp },
  { id: "goals",       label: "Goals",            icon: Target },
  { id: "strategy",    label: "Strategy Builder", icon: FlaskConical, badge: "BETA" },
  { id: "copilot",     label: "Nivesh Copilot",   icon: Bot },
];

// Smart suggestions per workspace mode
const NAV_SUGGESTIONS = {
  retail:  ["Is my portfolio risk-aligned?", "How can I save ₹1.5L in taxes?", "Portfolio health check"],
  advisor: ["Show clients with >10% drift", "Draft quarterly review", "Tax-loss harvesting for my book"],
  client:  ["Analyze this client portfolio", "Generate rebalance proposal", "Show goal progress"],
};

export default function V2Layout({
  children,
  activeScreen,
  setScreen,
  workspaceType,
  activeProfileName,
  onExitProfile,
  onAISubmit,
  user,
  recentChats = [],
}) {
  const [globalInput, setGlobalInput] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const navigate = useNavigate();
  const { logout } = useAuth();

  const isAdvisor      = workspaceType === "ADVISORY";
  const isImpersonating = Boolean(activeProfileName);

  // Auto-collapse sidebar when entering a sub-screen; expand on home/advisor
  const homeScreens = ["home", "advisor"];
  React.useEffect(() => {
    setSidebarCollapsed(!homeScreens.includes(activeScreen));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeScreen]);

  let navItems, mode, suggestions;
  if (!isAdvisor) {
    navItems    = RETAIL_NAV;
    mode        = "retail";
    suggestions = NAV_SUGGESTIONS.retail;
  } else if (isImpersonating) {
    navItems    = CLIENT_NAV;
    mode        = "client";
    suggestions = NAV_SUGGESTIONS.client;
  } else {
    navItems    = ADVISOR_NAV;
    mode        = "advisor";
    suggestions = NAV_SUGGESTIONS.advisor;
  }

  const handleGlobalSubmit = () => {
    if (!globalInput.trim()) return;
    onAISubmit?.(globalInput);
    setGlobalInput("");
  };

  const userInitials = user?.name
    ? user.name.split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase()
    : user?.email?.slice(0, 2).toUpperCase() || "ME";

  const screenLabel = navItems.find((n) => n.id === activeScreen)?.label
    || activeScreen?.toUpperCase()?.replace("_", " ")
    || "DASHBOARD";

  return (
    <div className="flex h-screen bg-[#212121] text-[#ECECF1] overflow-hidden font-sans">
      {/* ─── Left Sidebar ─── */}
      <motion.aside
        animate={{ width: sidebarCollapsed ? 64 : 260 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="bg-[#171717] flex flex-col shrink-0 border-r border-white/5 overflow-hidden"
      >
        <div className={cn("p-3 flex-1 overflow-y-auto overflow-x-hidden", sidebarCollapsed && "flex flex-col items-center")}>

          {/* New Insight button — icon only when collapsed */}
          <button
            onClick={() => setScreen("copilot")}
            title="New Insight"
            className={cn(
              "h-11 flex items-center rounded-lg border border-white/20 hover:bg-white/5 transition-colors group mb-5",
              sidebarCollapsed ? "w-10 justify-center px-0" : "w-full gap-3 px-3"
            )}
          >
            <div className="p-1 bg-white/10 rounded-md shrink-0">
              <Plus className="w-4 h-4 text-white" />
            </div>
            {!sidebarCollapsed && (
              <>
                <span className="text-sm font-medium">New Insight</span>
                <div className="ml-auto hidden group-hover:block border border-white/20 px-1 py-0.5 rounded text-[10px] text-white/50">⌘N</div>
              </>
            )}
          </button>

          {/* Client context banner — hidden when collapsed */}
          {!sidebarCollapsed && mode === "client" && (
            <div className="mb-4">
              <button
                onClick={onExitProfile}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium text-indigo-300 hover:bg-white/5 transition-colors mb-2"
              >
                <ChevronRight className="w-3.5 h-3.5 rotate-180" />
                Back to client list
              </button>
              <div className="px-3 py-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20">
                <p className="text-[9px] font-bold text-indigo-400 uppercase tracking-widest">Viewing</p>
                <p className="text-xs font-semibold text-white truncate">{activeProfileName}</p>
              </div>
            </div>
          )}

          {/* Workspace label — hidden when collapsed */}
          {!sidebarCollapsed && mode === "advisor" && (
            <p className="px-3 text-[10px] font-bold text-white/30 uppercase tracking-widest mb-1.5">
              Advisor Workspace
            </p>
          )}

          <div className={cn("space-y-4", sidebarCollapsed && "w-full")}>
            {/* Workspaces nav */}
            <div>
              {!sidebarCollapsed && (
                <p className="px-3 text-[10px] font-bold text-white/40 uppercase tracking-widest mb-1">
                  {mode === "client" ? "Client Workspace" : "Workspaces"}
                </p>
              )}
              <div className={cn("space-y-0.5", sidebarCollapsed && "flex flex-col items-center")}>
                {navItems.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => setScreen(item.id)}
                    title={sidebarCollapsed ? item.label : undefined}
                    className={cn(
                      "h-10 flex items-center rounded-lg text-sm font-medium transition-colors relative",
                      sidebarCollapsed ? "w-10 justify-center px-0" : "w-full gap-3 px-3",
                      activeScreen === item.id
                        ? "bg-[#212121] text-white"
                        : "text-[#ECECF1]/70 hover:bg-[#212121]"
                    )}
                  >
                    <item.icon className={cn("w-4 h-4 shrink-0", activeScreen === item.id ? "text-indigo-400" : "text-white/40")} />
                    {!sidebarCollapsed && (
                      <>
                        <span className="flex-1 text-left truncate">{item.label}</span>
                        {item.badge && (
                          <span className="text-[8px] font-bold bg-emerald-600 text-white px-1.5 py-0.5 rounded-full">{item.badge}</span>
                        )}
                      </>
                    )}
                    {activeScreen === item.id && !sidebarCollapsed && (
                      <motion.div layoutId="v2-active-pill" className="absolute right-2 w-1 h-4 bg-indigo-500 rounded-full" />
                    )}
                    {activeScreen === item.id && sidebarCollapsed && (
                      <span className="absolute right-0.5 w-0.5 h-4 bg-indigo-500 rounded-full" />
                    )}
                  </button>
                ))}

                {user?.is_admin && (
                  <button
                    onClick={() => setScreen("admin")}
                    title={sidebarCollapsed ? "Admin" : undefined}
                    className={cn(
                      "h-10 flex items-center rounded-lg text-sm font-medium transition-colors relative",
                      sidebarCollapsed ? "w-10 justify-center px-0" : "w-full gap-3 px-3",
                      activeScreen === "admin" ? "bg-[#212121] text-white" : "text-[#ECECF1]/70 hover:bg-[#212121]"
                    )}
                  >
                    <Terminal className={cn("w-4 h-4 shrink-0", activeScreen === "admin" ? "text-indigo-400" : "text-white/40")} />
                    {!sidebarCollapsed && <span className="flex-1 text-left">Admin</span>}
                  </button>
                )}
              </div>
            </div>

            {/* Recent chats — hidden when collapsed */}
            {!sidebarCollapsed && recentChats.length > 0 && (
              <div>
                <p className="px-3 text-[10px] font-bold text-white/40 uppercase tracking-widest mb-1">Recent Queries</p>
                <div className="space-y-0.5 opacity-60">
                  {recentChats.slice(0, 5).map((chat) => (
                    <button
                      key={chat.id}
                      onClick={() => setScreen("copilot")}
                      className="w-full h-9 flex items-center gap-3 px-3 rounded-lg text-[13px] text-white/70 hover:bg-[#212121] truncate transition-colors"
                    >
                      <History className="w-4 h-4 text-white/20 shrink-0" />
                      <span className="truncate">{chat.title || chat.first_message || "Chat session"}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Sidebar footer */}
        <div className={cn("p-3 border-t border-white/5 space-y-1", sidebarCollapsed && "flex flex-col items-center px-2")}>
          {sidebarCollapsed ? (
            /* Collapsed footer — just avatar + expand toggle */
            <>
              <button
                onClick={() => setSidebarCollapsed(false)}
                title="Expand sidebar"
                className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-white/5 text-white/30 hover:text-white transition-all mb-1"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
              <div className="w-7 h-7 rounded-lg bg-indigo-600/20 flex items-center justify-center text-indigo-400 border border-indigo-500/20 text-xs font-bold">
                {userInitials}
              </div>
            </>
          ) : (
            /* Expanded footer */
            <>
              <div className="flex items-center justify-between px-2 py-1 mb-1">
                <div className="flex items-center gap-2 px-2 py-1 bg-emerald-500/10 border border-emerald-500/20 rounded-md">
                  <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
                  <span className="text-[9px] font-bold text-emerald-500 uppercase tracking-widest">Live</span>
                </div>
                <button
                  onClick={() => navigate("/dashboard")}
                  className="flex items-center gap-1.5 text-[9px] font-bold text-white/30 hover:text-white/60 transition-colors uppercase tracking-widest"
                  title="Switch to Nivesh Classic"
                >
                  <RefreshCw className="w-3 h-3" />
                  V1 Classic
                </button>
              </div>
              <div className="flex items-center justify-between px-1">
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 rounded-lg bg-indigo-600/20 flex items-center justify-center text-indigo-400 border border-indigo-500/20 text-xs font-bold">
                    {userInitials}
                  </div>
                  <div className="text-left">
                    <p className="text-xs font-semibold text-white leading-none truncate max-w-[110px]">{user?.name || user?.email || "User"}</p>
                    <p className="text-[9px] text-white/30 font-bold uppercase tracking-tight leading-none mt-0.5">
                      {mode === "advisor" ? "Advisor" : mode === "client" ? "Client View" : "Investor"}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button onClick={() => setSidebarCollapsed(true)} title="Collapse sidebar" className="p-1.5 hover:bg-white/5 rounded-lg text-white/30 hover:text-white transition-all">
                    <ChevronRight className="w-3.5 h-3.5 rotate-180" />
                  </button>
                  <button onClick={() => setScreen("profile")} className="p-1.5 hover:bg-white/5 rounded-lg text-white/30 hover:text-white transition-all" title="Profile">
                    <User className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={logout} className="p-1.5 hover:bg-white/5 rounded-lg text-white/30 hover:text-rose-400 transition-all" title="Sign out">
                    <LogOut className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </motion.aside>

      {/* ─── Main Content Area ─── */}
      <main className="flex-1 bg-[#0f0f0f] flex flex-col h-screen overflow-hidden relative">
        {/* Minimal top header */}
        <header className="h-14 flex items-center justify-between px-6 bg-[#0f0f0f]/80 backdrop-blur-xl border-b border-white/5 shrink-0 z-50">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 px-2.5 py-1 bg-white/5 rounded-full border border-white/10">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-[9px] font-bold uppercase tracking-wider text-white/40 leading-none">
                System Live
              </span>
            </div>
            <div className="h-4 w-px bg-white/10" />
            <h2 className="text-xs font-bold text-white/70 tracking-widest uppercase">
              {screenLabel}
            </h2>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden md:flex items-center gap-2 px-2.5 py-1 bg-indigo-500/10 border border-indigo-500/20 rounded-lg">
              <Sparkles className="w-3 h-3 text-indigo-400" />
              <span className="text-[9px] font-black uppercase tracking-tighter text-indigo-300">Neural Alpha</span>
            </div>
            <button
              onClick={() => setScreen("copilot")}
              className="text-white/40 hover:text-white transition-colors relative p-2"
              title="Open AI Copilot"
            >
              <Bell className="w-4 h-4" />
            </button>
            <div className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center text-[9px] font-bold border border-white/10">
              {userInitials}
            </div>
            {/* Back to Dashboard — right corner, visible on any non-home screen */}
            {activeScreen !== "home" && activeScreen !== "advisor" && (
              <button
                onClick={() => setScreen(workspaceType === "ADVISORY" ? "advisor" : "home")}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/25 text-white/50 hover:text-white transition-all group ml-1"
                title="Back to Dashboard"
              >
                <ArrowLeft className="w-3.5 h-3.5 group-hover:-translate-x-0.5 transition-transform" />
                <span className="text-[10px] font-semibold tracking-wide hidden sm:inline">Dashboard</span>
              </button>
            )}
          </div>
        </header>

        {/* Scrollable content — copilot screen fills height and owns its own scroll */}
        <div className={cn(
          "flex-1 min-h-0",
          activeScreen === "copilot"
            ? "flex flex-col overflow-hidden"
            : "overflow-y-auto"
        )} style={activeScreen !== "copilot" ? { scrollbarWidth: "thin", scrollbarColor: "rgba(255,255,255,0.1) transparent" } : {}}>
          <div
            className={cn(
              "mx-auto",
              activeScreen === "copilot"
                ? "max-w-4xl w-full px-6 flex flex-col flex-1 min-h-0 pb-4 pt-4"
                : "p-6 md:p-8 max-w-6xl"
            )}
          >
            {children}
          </div>
          {/* Buffer for floating input — only on non-copilot screens */}
          {activeScreen !== "copilot" && <div className="h-36" />}
        </div>

        {/* Floating AI input bar — hidden on copilot (ChatView owns the input there) */}
        <div className={cn(
          "absolute bottom-0 left-0 right-0 p-6 bg-gradient-to-t from-[#0f0f0f] via-[#0f0f0f]/90 to-transparent z-40 pointer-events-none",
          activeScreen === "copilot" && "hidden"
        )}>
          <div className="max-w-3xl mx-auto pointer-events-auto">
            <div className="relative group">
              <div className="absolute -inset-1 bg-gradient-to-r from-indigo-500/20 to-purple-600/20 rounded-[2rem] blur-xl opacity-0 group-focus-within:opacity-100 transition-opacity duration-700" />
              <div className="relative bg-[#1A1A1A] border border-white/10 rounded-[1.6rem] shadow-2xl p-2 pr-14 focus-within:border-white/20 transition-all ring-1 ring-white/5">
                <input
                  type="text"
                  value={globalInput}
                  onChange={(e) => setGlobalInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleGlobalSubmit()}
                  placeholder="Ask Nivesh Copilot to analyze, trade or rebalance…"
                  className="w-full bg-transparent px-5 py-3 text-sm text-white font-medium outline-none placeholder:text-white/20"
                />
                <button
                  onClick={handleGlobalSubmit}
                  disabled={!globalInput.trim()}
                  className={cn(
                    "absolute right-2 top-1/2 -translate-y-1/2 w-10 h-10 rounded-[1.2rem] flex items-center justify-center transition-all shadow-xl active:scale-95",
                    globalInput.trim()
                      ? "bg-indigo-600 text-white hover:bg-indigo-500"
                      : "bg-white/5 text-white/20 cursor-not-allowed"
                  )}
                >
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </div>
            {/* Suggestion chips */}
            <div className="mt-3 flex items-center justify-center gap-3 flex-wrap">
              {suggestions.slice(0, 3).map((s) => (
                <button
                  key={s}
                  onClick={() => setGlobalInput(s)}
                  className="text-[9px] font-bold text-white/25 uppercase tracking-widest hover:text-indigo-400 hover:bg-white/5 px-2.5 py-1 rounded-lg border border-transparent hover:border-white/5 transition-all"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
