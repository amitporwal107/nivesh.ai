import React, { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/context/AuthContext";
import { useNavigate } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import DashboardOverview from "@/components/DashboardOverview";
import PortfolioView from "@/components/PortfolioView";
import ChatView from "@/components/ChatView";
import InsightsView from "@/components/InsightsView";
import FamilyView from "@/components/FamilyView";
import AdminView from "@/components/AdminView";
import OnboardingView from "@/components/OnboardingView";
import RiskProfileView from "@/components/RiskProfileView";
import { DashboardSkeleton } from "@/components/ui/skeleton-loaders";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const Dashboard = () => {
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("overview");
  const [holdings, setHoldings] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [insights, setInsights] = useState([]);
  const [portfolios, setPortfolios] = useState([]);
  const [dataLoading, setDataLoading] = useState(true);
  const [userProfile, setUserProfile] = useState(null);
  const [profileLoading, setProfileLoading] = useState(true);

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
      case "family":
        return <FamilyView onRefresh={fetchData} />;
      case "portfolio":
        return <PortfolioView holdings={holdings} onRefresh={fetchData} portfolios={portfolios} />;
      case "chat":
        return <ChatView />;
      case "insights":
        return <InsightsView insights={insights} onRefresh={fetchData} />;
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
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} user={user} />
      <main className="flex-1 ml-0 md:ml-64 min-h-screen min-w-0">
        <div className="pt-16 md:pt-4 p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
          {renderContent()}
        </div>
      </main>
    </div>
  );
};

export default Dashboard;
