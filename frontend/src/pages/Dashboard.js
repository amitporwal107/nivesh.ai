import React, { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/context/AuthContext";
import { useNavigate, useLocation } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import UserProfileDropdown from "@/components/UserProfileDropdown";
import NiveshCopilotDrawer from "@/components/NiveshCopilotDrawer";
import { Sparkles } from "lucide-react";
import DashboardOverview from "@/components/DashboardOverview";
import PortfolioView from "@/components/PortfolioView";
import ChatView from "@/components/ChatView";
import InsightsView from "@/components/InsightsView";
import FamilyView from "@/components/FamilyView";
import AdminView from "@/components/AdminView";
import OnboardingView from "@/components/OnboardingView";
import RiskProfileView from "@/components/RiskProfileView";
import PlanBoardView from "@/components/v2/PlanBoardView";
import ActionPromptModal from "@/components/v2/ActionPromptModal";
import { DashboardSkeleton } from "@/components/ui/skeleton-loaders";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const Dashboard = () => {
  const { user, loading } = useAuth();
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

  useEffect(() => {
    if (!loading && !user) {
      navigate("/", { replace: true });
      return;
    }
    if (user) {
      fetchProfile();
      fetchData();
      // Show action prompt after 1 second delay
      const timer = setTimeout(() => setShowActionPrompt(true), 1000);
      return () => clearTimeout(timer);
    }
  }, [user, loading, navigate, fetchData, fetchProfile]);

  const handleOnboardingComplete = () => {
    fetchProfile();
    fetchData();
    setActiveTab("overview");
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
    return <OnboardingView onComplete={handleOnboardingComplete} userProfile={userProfile} />;
  }

  const renderContent = () => {
    switch (activeTab) {
      case "overview":
        return <DashboardOverview analytics={analytics} insights={insights} holdings={holdings} loading={dataLoading} onRefresh={fetchData} />;
      case "plan_board":
        return <PlanBoardView />;
      case "family":
        return <FamilyView onRefresh={fetchData} />;
      case "portfolio":
        return <PortfolioView holdings={holdings} onRefresh={fetchData} portfolios={portfolios} />;
      case "chat":
        // Legacy: if someone still lands on #chat, open the drawer instead of rendering inline
        if (!copilotOpen) setCopilotOpen(true);
        return <DashboardOverview analytics={analytics} insights={insights} holdings={holdings} loading={dataLoading} onRefresh={fetchData} />;
      case "insights":
        return <InsightsView insights={insights} onRefresh={fetchData} copilotEnabled={userProfile?.copilot_enabled} riskProfile={userProfile?.risk_profile?.category} />;
      case "risk_profile":
        return <RiskProfileView onComplete={handleRiskProfileComplete} existingProfile={userProfile?.risk_profile} />;
      case "admin":
        return user?.is_admin ? <AdminView /> : null;
      default:
        return <DashboardOverview analytics={analytics} insights={insights} holdings={holdings} loading={dataLoading} onRefresh={fetchData} />;
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 flex overflow-x-hidden" data-testid="dashboard">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
      <main className="flex-1 ml-0 md:ml-64 min-h-screen min-w-0">
        {/* Top bar with Copilot trigger + user-profile dropdown */}
        <div className="sticky top-0 z-30 flex justify-end items-center gap-3 px-4 sm:px-6 lg:px-8 py-3 bg-[#F8FAFC]/80 dark:bg-slate-950/80 backdrop-blur-sm border-b border-slate-100 dark:border-slate-800">
          <button
            data-testid="nivesh-copilot-trigger"
            onClick={() => setCopilotOpen(true)}
            className="flex items-center gap-2 pl-3 pr-4 py-1.5 rounded-full bg-gradient-to-r from-emerald-600 to-emerald-700 hover:from-emerald-700 hover:to-emerald-800 text-white shadow-sm hover:shadow-md transition-all"
            aria-label="Open Nivesh Copilot"
          >
            <Sparkles className="w-4 h-4" />
            <span className="text-sm font-semibold tracking-wide">Nivesh Copilot</span>
          </button>
          <UserProfileDropdown user={user} activeTab={activeTab} setActiveTab={setActiveTab} />
        </div>
        <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
          {renderContent()}
        </div>
      </main>
      
      {/* Nivesh Copilot slide-out drawer */}
      <NiveshCopilotDrawer open={copilotOpen} onClose={() => setCopilotOpen(false)} />

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
