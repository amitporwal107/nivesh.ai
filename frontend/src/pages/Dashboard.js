import React, { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/context/AuthContext";
import { useNavigate, useLocation } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import UserProfileDropdown from "@/components/UserProfileDropdown";
import NiveshCopilotDrawer from "@/components/NiveshCopilotDrawer";
import { Sparkles } from "lucide-react";
import DashboardOverview from "@/components/DashboardOverview";
import PortfolioView from "@/components/PortfolioView";
import ActionablePortfolioView from "@/components/ActionablePortfolioView";
import ChatView from "@/components/ChatView";
import InsightsView from "@/components/InsightsView";
import FamilyView from "@/components/FamilyView";
import AdminView from "@/components/AdminView";
import GoalsView from "@/components/goals/GoalsView";
import OnboardingCopilotView from "@/components/OnboardingCopilotView";
import RiskProfileView from "@/components/RiskProfileView";
import PlanBoardView from "@/components/v2/PlanBoardView";
import ActionPromptModal from "@/components/v2/ActionPromptModal";
import MfdDashboard from "@/components/mfd/MfdDashboard";
import MarketDashboard from "@/components/MarketDashboard";
import StrategyBuilder from "@/pages/StrategyBuilder";
import ClientCasUpload from "@/components/mfd/ClientCasUpload";
import MfdOnboardingWizard from "@/components/mfd/MfdOnboardingWizard";
import ClientSnapshot from "@/components/mfd/ClientSnapshot";
import { toast } from "sonner";
import { DashboardSkeleton } from "@/components/ui/skeleton-loaders";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const Dashboard = () => {
  const { user, loading, checkAuth } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Derive active tab from URL hash (e.g. "#plan_board"), falling back to "overview"
  const tabFromHash = (location.hash || "").replace("#", "") || "overview";
  const [activeTab, setActiveTabState] = useState(tabFromHash);

  // Sync tab changes → URL hash (so the tab is shareable & browser back works)
  const setActiveTab = useCallback((tab) => {
    setActiveTabState(tab);
    navigate(`/dashboard#${tab}`, { replace: false });
  }, [navigate]);

  // Sync URL hash → tab state (handles back/forward navigation)
  useEffect(() => {
    const t = (location.hash || "").replace("#", "");
    if (t && t !== activeTab) setActiveTabState(t);
  }, [location.hash, activeTab]);
  const [holdings, setHoldings] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [insights, setInsights] = useState([]);
  const [portfolios, setPortfolios] = useState([]);
  const [dataLoading, setDataLoading] = useState(true);
  const [userProfile, setUserProfile] = useState(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [showActionPrompt, setShowActionPrompt] = useState(false);

  // MFD workspace state — we fetch on mount so the sidebar knows whether
  // to show the Advisor tab, and the impersonation banner knows whose
  // portfolio we're currently viewing.
  const [workspace, setWorkspace] = useState(null);
  const [activeProfile, setActiveProfile] = useState(null);
  const fetchWorkspace = useCallback(async () => {
    try {
      const ws = await axios.get(`${API}/mfd/workspace`, { withCredentials: true });
      setWorkspace(ws.data);
      if (ws.data?.type === "ADVISORY") {
        // Pull the profile list to resolve active_profile_id → name for the banner
        const pr = await axios.get(`${API}/mfd/profiles`, { withCredentials: true });
        const active = (pr.data?.profiles || []).find((p) => p.profile_id === user?._active_profile_id);
        setActiveProfile(active || null);
      }
    } catch {
      /* non-advisor users — silent */
    }
  }, [user?._active_profile_id]);

  useEffect(() => { if (user) fetchWorkspace(); }, [user, fetchWorkspace]);

  // When an advisor lands on the dashboard with a legacy "#overview" URL
  // (retail-only tab that's hidden in advisor mode), bounce them to the
  // Advisor tab once we know their workspace is ADVISORY. We do this
  // *inline* rather than in a reactive effect to avoid update loops with
  // React Router's location sync.
  useEffect(() => {
    if (workspace?.type === "ADVISORY" && !activeProfile && activeTab === "overview") {
      setActiveTab("advisor");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace?.type]);   // intentionally only triggers on first workspace load

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

  const fetchData = useCallback(async () => {
    setDataLoading(true);
    try {
      const [holdingsRes, analyticsRes, insightsRes, pfRes] = await Promise.all([
        axios.get(`${API}/portfolio/holdings`, { withCredentials: true }),
        axios.get(`${API}/portfolio/analytics`, { withCredentials: true }),
        axios.get(`${API}/insights`, { withCredentials: true }),
        axios.get(`${API}/portfolios`, { withCredentials: true }),
      ]);
      setHoldings(holdingsRes.data);
      setAnalytics(analyticsRes.data);
      setInsights(insightsRes.data);
      setPortfolios(pfRes.data);
    } catch (err) {
      console.error("Error fetching data:", err);
    } finally {
      setDataLoading(false);
    }
  }, []);

  // When MFD opens a client from the Advisor dashboard, we activate the
  // profile on the server (impersonation) and then navigate to Overview so
  // every existing view (portfolio / insights / goals) re-renders against
  // the client's data. A one-line toast tells the user what happened.
  // We also refresh the AuthContext user (`checkAuth`) so the top-bar
  // greeting + avatar reflect the impersonated identity — the backend's
  // `/auth/me` returns the shadow user when active_profile_id is set.
  const enterProfile = useCallback(async (profile, opts) => {
    // Set the destination tab FIRST so the right component mounts before
    // we kick off the retail data fetch. Otherwise MfdDashboard stays
    // mounted during the fetch and can get in the way of the snapshot.
    const destination = opts?.tab || "snapshot";
    setActiveTab(destination);
    setActiveProfile(profile);
    await Promise.all([fetchData(), checkAuth()]);
  }, [setActiveTab, fetchData, checkAuth]);

  // Exit impersonation — returns the MFD to the client list.
  // Also refresh the cached user (`checkAuth`) so the top-bar greeting,
  // avatar and any "Hello, X" copy snap back to the real MFD account.
  const exitProfile = useCallback(async () => {
    try {
      await axios.post(`${API}/mfd/profiles/deactivate`, {}, { withCredentials: true });
      setActiveTab("advisor");
      setActiveProfile(null);
      await Promise.all([fetchData(), checkAuth()]);
      toast.success("Back to advisor view");
    } catch {
      toast.error("Could not exit client view");
    }
  }, [setActiveTab, fetchData, checkAuth]);

  useEffect(() => {
    if (!loading && !user) {
      navigate("/", { replace: true });
      return;
    }
    if (user) {
      fetchProfile();
      fetchData();
    }
  }, [user, loading, navigate, fetchData, fetchProfile]);

  const handleOnboardingComplete = (opts) => {
    fetchProfile();
    fetchWorkspace();
    fetchData();
    // Refresh the cached AuthContext user so the top-bar greeting/avatar
    // snap back to the real MFD identity — onboarding may have created or
    // deactivated an impersonated SELF profile, leaving stale identity.
    checkAuth();
    setActiveTab(opts?.destination || "overview");
  };

  const handleRiskProfileComplete = () => {
    fetchProfile();
    setActiveTab("overview");
  };

  if (loading || profileLoading) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 flex overflow-x-hidden" data-testid="dashboard-loading">
        <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} user={{}} />
        <main className="flex-1 ml-0 md:ml-64 min-h-screen min-w-0">
          <div className="pt-16 md:pt-4 p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
            <DashboardSkeleton />
          </div>
        </main>
      </div>
    );
  }

  if (!user) return null;

  // Show onboarding if not completed
  if (!userProfile?.onboarding_completed) {
    return <OnboardingCopilotView onComplete={handleOnboardingComplete} userProfile={userProfile} />;
  }

  const renderContent = () => {
    // MFD viewing a client with no portfolio yet → show the CAS upload CTA
    // prominently at the top of any content view so it's discoverable
    // regardless of which tab the MFD lands on.
    const showClientUploadCta =
      activeProfile && activeProfile.type === "CLIENT" && (holdings?.length || 0) === 0;

    const withUploadCta = (view) => (
      showClientUploadCta ? (
        <div className="space-y-5">
          <ClientCasUpload
            clientName={activeProfile.name}
            onImported={fetchData}
          />
          {view}
        </div>
      ) : view
    );

    switch (activeTab) {
      case "snapshot":
        if (!activeProfile) return <MfdDashboard onEnterProfile={enterProfile} />;
        return withUploadCta(
          <ClientSnapshot
            activeProfile={activeProfile}
            setActiveTab={setActiveTab}
            onRefresh={fetchData}
          />,
        );
      case "overview":
        return withUploadCta(<DashboardOverview analytics={analytics} insights={insights} holdings={holdings} loading={dataLoading} onRefresh={fetchData} />);
      case "plan_board":
        return withUploadCta(<PlanBoardView />);
      case "family":
        return <FamilyView onRefresh={fetchData} />;
      case "portfolio":
        return withUploadCta(<ActionablePortfolioView />);
      case "portfolio_legacy":
        return withUploadCta(<PortfolioView holdings={holdings} onRefresh={fetchData} portfolios={portfolios} />);
      case "chat":
        return <ChatView onNavigateToPlanBoard={() => setActiveTab("plan_board")} />;
      case "insights":
        return withUploadCta(<InsightsView insights={insights} onRefresh={fetchData} copilotEnabled={userProfile?.copilot_enabled} riskProfile={userProfile?.risk_profile?.category} />);
      case "goals":
        return withUploadCta(<GoalsView />);
      case "risk_profile":
        return <RiskProfileView onComplete={handleRiskProfileComplete} existingProfile={userProfile?.risk_profile} />;
      case "advisor":
        return <MfdDashboard onEnterProfile={enterProfile} />;
      case "market":
        // Market Dashboard — macro regime + sector heatmap + positional ideas.
        // Does not consume per-client data, so it works regardless of
        // workspace mode or impersonation state.
        return <MarketDashboard />;
      case "strategy_builder":
        // Strategy Builder — multi-step wizard (Universe → Strategy → Screen
        // → Backtest → Execute). Phase-1: stock-only, technicals.
        return <StrategyBuilder />;
      case "admin":
        return user?.is_admin ? <AdminView /> : null;
      default:
        return <DashboardOverview analytics={analytics} insights={insights} holdings={holdings} loading={dataLoading} onRefresh={fetchData} />;
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 flex overflow-x-hidden" data-testid="dashboard">
      {/* MFD onboarding wizard — full-screen takeover for ADVISORY workspaces
          that haven't completed the activation flow yet. Completion is
          idempotent: once mfd_onboarding_completed=true the wizard is
          never shown again. */}
      {workspace?.type === "ADVISORY" && workspace?.mfd_onboarding_completed === false && (
        <MfdOnboardingWizard
          onComplete={async (profile) => {
            await fetchWorkspace();
            // Refresh cached identity — wizard may have impersonated a
            // freshly-created profile during the "wow moment" step.
            await checkAuth();
            if (profile) {
              setActiveProfile(profile);
              await fetchData();
              setActiveTab("snapshot");
            } else {
              setActiveTab("advisor");
            }
          }}
        />
      )}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        workspaceType={workspace?.type}
        activeProfileName={activeProfile?.name}
        onExitProfile={exitProfile}
      />
      <main className="flex-1 ml-0 md:ml-64 min-h-screen min-w-0">
        {/* Top bar with user-profile dropdown */}
        <div className="sticky top-0 z-30 flex justify-between items-center gap-3 px-4 sm:px-6 lg:px-8 py-3 bg-[#F8FAFC]/80 dark:bg-slate-950/80 backdrop-blur-sm border-b border-slate-100 dark:border-slate-800">
          {/* Client context pill — compact reminder. Full header with
              avatar + "Back to clients" CTA now lives in the sidebar. */}
          {activeProfile ? (
            <div
              data-testid="impersonation-strip"
              className="flex items-center gap-2 rounded-full bg-indigo-50 dark:bg-indigo-900/30 border border-indigo-200 dark:border-indigo-800 px-3 py-1.5 text-xs"
            >
              <span className="w-5 h-5 rounded-full bg-indigo-100 dark:bg-indigo-900/50 flex items-center justify-center text-indigo-700 dark:text-indigo-300 text-[10px] font-bold">
                {activeProfile.name?.slice(0, 1).toUpperCase()}
              </span>
              <span className="text-indigo-900 dark:text-indigo-200">
                Client context: <strong>{activeProfile.name}</strong>
              </span>
            </div>
          ) : <div />}
          <UserProfileDropdown user={user} activeTab={activeTab} setActiveTab={setActiveTab} />
        </div>
        <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
          {renderContent()}
        </div>
      </main>
      
      {/* Nivesh Copilot floating FAB (bottom-right) + slide-out drawer (from right) */}
      {!copilotOpen && (
        <button
          data-testid="nivesh-copilot-trigger"
          onClick={() => setCopilotOpen(true)}
          aria-label="Open Nivesh Copilot"
          className="fixed bottom-6 right-6 z-40 flex items-center gap-2 pl-4 pr-5 py-3 rounded-full bg-gradient-to-r from-emerald-600 to-emerald-700 hover:from-emerald-700 hover:to-emerald-800 text-white shadow-lg hover:shadow-xl transition-all hover:-translate-y-0.5"
        >
          <Sparkles className="w-5 h-5" />
          <span className="text-sm font-semibold tracking-wide hidden sm:inline">Nivesh Copilot</span>
        </button>
      )}
      <NiveshCopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        onNavigateToPlanBoard={() => { setCopilotOpen(false); setActiveTab("plan_board"); }}
      />

      {/* Action Prompt Modal */}
      <ActionPromptModal 
        open={showActionPrompt}
        onClose={() => setShowActionPrompt(false)}
        onNavigateToPlanBoard={() => setActiveTab("plan_board")}
      />
    </div>
  );
};

export default Dashboard;
