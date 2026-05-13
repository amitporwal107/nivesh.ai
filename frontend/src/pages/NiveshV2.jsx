/**
 * NiveshV2.jsx — Nivesh AI Copilot 2.0
 *
 * Dark, ChatGPT-style shell wrapping the same V1 backend + components.
 * Mirrors Dashboard.js data-fetching and workspace logic exactly.
 * Forces document dark mode while mounted (class-based Tailwind dark mode).
 */

import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import axios from "axios";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";

// V2 shell
import V2Layout, { SCREEN_TO_TAB } from "@/components/v2app/V2Layout";
import V2HomeScreen from "@/components/v2app/screens/V2HomeScreen";
import { detectPersona } from "@/components/v2app/screens/V2CopilotWelcome";

// V1 content components — rendered as-is inside the dark shell
import OnboardingView from "@/components/OnboardingView";
import RiskProfileView from "@/components/RiskProfileView";
import ChatView from "@/components/ChatView";
import ActionablePortfolioView from "@/components/ActionablePortfolioView";
import InsightsView from "@/components/InsightsView";
import GoalsView from "@/components/goals/GoalsView";
import FamilyView from "@/components/FamilyView";
import MarketDashboard from "@/components/MarketDashboard";
import MfdDashboard from "@/components/mfd/MfdDashboard";
import AdminView from "@/components/AdminView";
import PlanBoardView from "@/components/v2/PlanBoardView";
import StrategyBuilder from "@/pages/StrategyBuilder";
import ClientSnapshot from "@/components/mfd/ClientSnapshot";
import ClientCasUpload from "@/components/mfd/ClientCasUpload";
import MfdOnboardingWizard from "@/components/mfd/MfdOnboardingWizard";
import RiskProfileScreen from "@/components/RiskProfileView";
import UserProfileDropdown from "@/components/UserProfileDropdown";
import { DashboardSkeleton } from "@/components/ui/skeleton-loaders";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// ─── Thin dark wrapper for embedded V1 components ────────────────────────────
// V1 components already have dark: variants; the wrapper ensures the `dark`
// selector on html is active (set in NiveshV2 useEffect below).
const DarkContent = ({ children }) => (
  <div className="text-slate-100 min-h-[50vh]">{children}</div>
);

// ─── Profile screen ──────────────────────────────────────────────────────────
function V2ProfileScreen({ user, userProfile, setScreen, onComplete }) {
  return (
    <div className="space-y-6 max-w-2xl mx-auto">
      <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-6">
        <div className="flex items-center gap-4 mb-6">
          <div className="w-16 h-16 rounded-full bg-indigo-600/20 flex items-center justify-center text-2xl font-bold text-indigo-300 border border-indigo-500/20">
            {user?.name?.split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase() || "ME"}
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">{user?.name || user?.email}</h2>
            <p className="text-sm text-white/40">{user?.email}</p>
            <div className="flex gap-2 mt-1">
              <span className="bg-indigo-500/20 text-indigo-300 text-[9px] font-bold px-2 py-0.5 rounded-full uppercase">
                Premium
              </span>
              {user?.is_admin && (
                <span className="bg-rose-500/20 text-rose-300 text-[9px] font-bold px-2 py-0.5 rounded-full uppercase">
                  Admin
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="p-4 bg-white/5 rounded-xl border border-white/5">
            <p className="text-[9px] font-bold text-white/30 uppercase tracking-widest mb-1">Risk Profile</p>
            <p className="text-sm font-bold text-white">{userProfile?.risk_profile?.category || "Not set"}</p>
          </div>
          <div className="p-4 bg-white/5 rounded-xl border border-white/5">
            <p className="text-[9px] font-bold text-white/30 uppercase tracking-widest mb-1">Journey Type</p>
            <p className="text-sm font-bold text-white">{userProfile?.journey_type || "Investor"}</p>
          </div>
        </div>
      </div>
      <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-6">
        <h3 className="text-sm font-bold text-white mb-4 uppercase tracking-widest">Risk Profile Assessment</h3>
        <DarkContent>
          <RiskProfileView onComplete={onComplete} existingProfile={userProfile?.risk_profile} />
        </DarkContent>
      </div>
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────
export default function NiveshV2() {
  const { user, loading, checkAuth } = useAuth();
  const navigate = useNavigate();

  // ── active screen — maps to V1 tab concept
  const [activeScreen, setActiveScreen] = useState("home");

  // ── same data state as Dashboard.js
  const [holdings, setHoldings]       = useState([]);
  const [analytics, setAnalytics]     = useState(null);
  const [insights, setInsights]       = useState([]);
  const [portfolios, setPortfolios]   = useState([]);
  const [dataLoading, setDataLoading] = useState(true);
  const [userProfile, setUserProfile] = useState(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [workspace, setWorkspace]     = useState(null);
  const [activeProfile, setActiveProfile] = useState(null);
  const [recentChats, setRecentChats] = useState([]);

  // ── Force dark mode while V2 is mounted ──────────────────────────────────
  useEffect(() => {
    document.documentElement.classList.add("dark");
    return () => {
      // Only remove if user preference wasn't dark
      const stored = localStorage.getItem("theme");
      if (stored !== "dark") {
        document.documentElement.classList.remove("dark");
      }
    };
  }, []);

  // ── Fetch user profile ───────────────────────────────────────────────────
  const fetchProfile = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/user/profile`, { withCredentials: true });
      setUserProfile(res.data);
    } catch {
      setUserProfile({ journey_type: null, risk_profile: null, onboarding_completed: false });
    } finally {
      setProfileLoading(false);
    }
  }, []);

  // ── Fetch portfolio data ──────────────────────────────────────────────────
  const fetchData = useCallback(async () => {
    setDataLoading(true);
    try {
      const [h, a, i, p] = await Promise.all([
        axios.get(`${API}/portfolio/holdings`,  { withCredentials: true }),
        axios.get(`${API}/portfolio/analytics`, { withCredentials: true }),
        axios.get(`${API}/insights`,            { withCredentials: true }),
        axios.get(`${API}/portfolios`,          { withCredentials: true }),
      ]);
      setHoldings(h.data);
      setAnalytics(a.data);
      setInsights(i.data);
      setPortfolios(p.data);
    } catch (err) {
      console.error("[V2] data fetch error:", err);
    } finally {
      setDataLoading(false);
    }
  }, []);

  // ── Fetch MFD workspace ───────────────────────────────────────────────────
  const fetchWorkspace = useCallback(async () => {
    try {
      const ws = await axios.get(`${API}/mfd/workspace`, { withCredentials: true });
      setWorkspace(ws.data);
      if (ws.data?.type === "ADVISORY") {
        const pr = await axios.get(`${API}/mfd/profiles`, { withCredentials: true });
        const active = (pr.data?.profiles || []).find(
          (p) => p.profile_id === user?._active_profile_id
        );
        setActiveProfile(active || null);
      }
    } catch {
      // non-advisor users — silent
    }
  }, [user?._active_profile_id]);

  // ── Fetch recent chat sessions for sidebar ───────────────────────────────
  const fetchRecentChats = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/copilot/sessions`, { withCredentials: true });
      setRecentChats((res.data?.sessions || res.data || []).slice(0, 5));
    } catch {
      // Chat sessions are optional
    }
  }, []);

  // ── On user load ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!loading && !user) {
      navigate("/", { replace: true });
      return;
    }
    if (user) {
      fetchProfile();
      fetchData();
      fetchWorkspace();
      fetchRecentChats();
    }
  }, [user, loading, navigate, fetchData, fetchProfile, fetchWorkspace, fetchRecentChats]);

  // ── Advisor: bounce to advisor tab on first load ─────────────────────────
  useEffect(() => {
    if (workspace?.type === "ADVISORY" && !activeProfile && activeScreen === "home") {
      setActiveScreen("advisor");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace?.type]);

  // ── Enter client profile (impersonation) ─────────────────────────────────
  const enterProfile = useCallback(async (profile, opts) => {
    const destination = opts?.tab || "snapshot";
    setActiveScreen(destination);
    setActiveProfile(profile);
    await Promise.all([fetchData(), checkAuth()]);
  }, [fetchData, checkAuth]);

  // ── Exit impersonation ────────────────────────────────────────────────────
  const exitProfile = useCallback(async () => {
    try {
      await axios.post(`${API}/mfd/profiles/deactivate`, {}, { withCredentials: true });
      setActiveScreen("advisor");
      setActiveProfile(null);
      await Promise.all([fetchData(), checkAuth()]);
      toast.success("Back to advisor view");
    } catch {
      toast.error("Could not exit client view");
    }
  }, [fetchData, checkAuth]);

  // ── Global AI input handler — routes to copilot with prefilled query ─────
  const handleAISubmit = useCallback((text) => {
    // Store the pending message so ChatView can pick it up
    sessionStorage.setItem("v2_pending_chat_message", text);
    setActiveScreen("copilot");
  }, []);

  // ── Onboarding handlers ───────────────────────────────────────────────────
  const handleOnboardingComplete = (opts) => {
    fetchProfile();
    fetchWorkspace();
    fetchData();
    checkAuth();
    setActiveScreen(opts?.destination || "home");
  };

  const handleRiskProfileComplete = () => {
    fetchProfile();
    setActiveScreen("home");
  };

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (loading || profileLoading) {
    return (
      <div className="min-h-screen bg-[#0f0f0f] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) return null;

  // ── Show onboarding (reuses V1 OnboardingView) ────────────────────────────
  if (!userProfile?.onboarding_completed) {
    return (
      <div className="dark min-h-screen bg-[#0f0f0f]">
        <OnboardingView
          onComplete={handleOnboardingComplete}
          userProfile={userProfile}
        />
      </div>
    );
  }

  // ── MFD onboarding wizard ─────────────────────────────────────────────────
  if (workspace?.type === "ADVISORY" && workspace?.mfd_onboarding_completed === false) {
    return (
      <div className="dark min-h-screen bg-[#0f0f0f]">
        <MfdOnboardingWizard
          onComplete={async (profile) => {
            await fetchWorkspace();
            await checkAuth();
            if (profile) {
              setActiveProfile(profile);
              await fetchData();
              setActiveScreen("snapshot");
            } else {
              setActiveScreen("advisor");
            }
          }}
        />
      </div>
    );
  }

  // ── Render active screen ──────────────────────────────────────────────────
  const isAdvisor      = workspace?.type === "ADVISORY";
  const isImpersonating = Boolean(activeProfile);

  const showClientUploadCta =
    activeProfile && activeProfile.type === "CLIENT" && (holdings?.length || 0) === 0;

  const withUpload = (view) =>
    showClientUploadCta ? (
      <div className="space-y-5">
        <ClientCasUpload clientName={activeProfile.name} onImported={fetchData} />
        {view}
      </div>
    ) : view;

  const renderScreen = () => {
    switch (activeScreen) {
      // ── Home / Overview ─────────────────────────────────────────────────
      case "home":
        if (isAdvisor && !isImpersonating) {
          return (
            <DarkContent>
              <MfdDashboard onEnterProfile={enterProfile} />
            </DarkContent>
          );
        }
        return (
          <V2HomeScreen
            analytics={analytics}
            insights={insights}
            loading={dataLoading}
            setScreen={setActiveScreen}
          />
        );

      // ── Advisor command centre ───────────────────────────────────────────
      case "advisor":
        return (
          <DarkContent>
            <MfdDashboard onEnterProfile={enterProfile} />
          </DarkContent>
        );

      // ── Client 360 (impersonation) ───────────────────────────────────────
      case "snapshot":
        if (!activeProfile) {
          return (
            <DarkContent>
              <MfdDashboard onEnterProfile={enterProfile} />
            </DarkContent>
          );
        }
        return withUpload(
          <DarkContent>
            <ClientSnapshot
              activeProfile={activeProfile}
              setActiveTab={(tab) => setActiveScreen(tab)}
              onRefresh={fetchData}
            />
          </DarkContent>
        );

      // ── AI Copilot Chat ──────────────────────────────────────────────────
      case "copilot":
        return (
          <ChatView
            onNavigateToPlanBoard={() => setActiveScreen("plan_board")}
            v2Mode={true}
            v2PersonaId={
              isImpersonating
                ? detectPersona(null, holdings, activeProfile)
                : detectPersona(workspace, holdings, userProfile)
            }
            v2Analytics={analytics}
            v2Holdings={holdings}
            v2Workspace={workspace}
          />
        );

      // ── Portfolio ────────────────────────────────────────────────────────
      case "portfolio":
        return withUpload(
          <DarkContent>
            <ActionablePortfolioView />
          </DarkContent>
        );

      // ── Insights ─────────────────────────────────────────────────────────
      case "insights":
        return withUpload(
          <DarkContent>
            <InsightsView
              insights={insights}
              onRefresh={fetchData}
              copilotEnabled={userProfile?.copilot_enabled}
              riskProfile={userProfile?.risk_profile?.category}
            />
          </DarkContent>
        );

      // ── Market ───────────────────────────────────────────────────────────
      case "markets":
        return (
          <DarkContent>
            <MarketDashboard />
          </DarkContent>
        );

      // ── Plan Board ───────────────────────────────────────────────────────
      case "plan_board":
        return withUpload(
          <DarkContent>
            <PlanBoardView />
          </DarkContent>
        );

      // ── Strategy Builder ─────────────────────────────────────────────────
      case "strategy":
        return (
          <DarkContent>
            <StrategyBuilder />
          </DarkContent>
        );

      // ── Goals ────────────────────────────────────────────────────────────
      case "goals":
        return withUpload(
          <DarkContent>
            <GoalsView />
          </DarkContent>
        );

      // ── Family ───────────────────────────────────────────────────────────
      case "family":
        return (
          <DarkContent>
            <FamilyView onRefresh={fetchData} />
          </DarkContent>
        );

      // ── Profile / Risk Profile ───────────────────────────────────────────
      case "profile":
        return (
          <V2ProfileScreen
            user={user}
            userProfile={userProfile}
            setScreen={setActiveScreen}
            onComplete={handleRiskProfileComplete}
          />
        );

      // ── Admin ────────────────────────────────────────────────────────────
      case "admin":
        return user?.is_admin ? (
          <DarkContent>
            <AdminView />
          </DarkContent>
        ) : null;

      default:
        return (
          <V2HomeScreen
            analytics={analytics}
            insights={insights}
            loading={dataLoading}
            setScreen={setActiveScreen}
          />
        );
    }
  };

  return (
    <V2Layout
      activeScreen={activeScreen}
      setScreen={setActiveScreen}
      workspaceType={workspace?.type}
      activeProfileName={activeProfile?.name}
      onExitProfile={exitProfile}
      onAISubmit={handleAISubmit}
      user={user}
      recentChats={recentChats}
    >
      <AnimatePresence mode="wait">
        <motion.div
          key={activeScreen}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
          className="w-full min-h-full"
        >
          {renderScreen()}
        </motion.div>
      </AnimatePresence>
    </V2Layout>
  );
}
