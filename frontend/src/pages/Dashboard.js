import React, { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/context/AuthContext";
import { useNavigate } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import DashboardOverview from "@/components/DashboardOverview";
import PortfolioView from "@/components/PortfolioView";
import ChatView from "@/components/ChatView";
import InsightsView from "@/components/InsightsView";
import FamilyView from "@/components/FamilyView";
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
    if (user) fetchData();
  }, [user, loading, navigate, fetchData]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F8FAFC] dark:bg-slate-950">
        <div className="w-10 h-10 border-3 border-emerald-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) return null;

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
      default:
        return <DashboardOverview analytics={analytics} insights={insights} holdings={holdings} loading={dataLoading} onRefresh={fetchData} />;
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 flex" data-testid="dashboard">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} user={user} />
      <main className="flex-1 ml-0 md:ml-64 min-h-screen">
        <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
          {renderContent()}
        </div>
      </main>
    </div>
  );
};

export default Dashboard;
