import React, { Suspense, lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import ResponsiveLayout from "./ResponsiveLayout";

// Lazy-load every screen — production-quality code-split.
const CopilotHome = lazy(() => import("../screens/home/CopilotHome"));
const CopilotChat = lazy(() => import("../screens/chat/CopilotChat"));
const Onboarding = lazy(() => import("../screens/onboarding/Onboarding"));
const Dashboard = lazy(() => import("../screens/dashboard/Dashboard"));
const Portfolio = lazy(() => import("../screens/portfolio/Portfolio"));
const Diversification = lazy(() => import("../screens/portfolio/Diversification"));
const Concentration = lazy(() => import("../screens/portfolio/Concentration"));
const RiskAnalysis = lazy(() => import("../screens/risk/RiskAnalysis"));
const StressTest = lazy(() => import("../screens/risk/StressTest"));
const TaxAnalysis = lazy(() => import("../screens/tax/TaxAnalysis"));
const Performance = lazy(() => import("../screens/performance/Performance"));
const Advisor = lazy(() => import("../screens/advisor/Advisor"));
const MarketDashboard = lazy(() => import("../screens/market/MarketDashboard"));
const Settings = lazy(() => import("../screens/settings/Settings"));
const Profile = lazy(() => import("../screens/profile/Profile"));

function ScreenSkeleton() {
  return (
    <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ height: 110, background: "var(--v3-bg-2)", borderRadius: 20, animation: "v3-skel 1.4s ease-in-out infinite" }} />
      <div style={{ height: 266, background: "var(--v3-bg-2)", borderRadius: 20, animation: "v3-skel 1.4s ease-in-out infinite" }} />
      <div style={{ height: 120, background: "var(--v3-bg-2)", borderRadius: 14, animation: "v3-skel 1.4s ease-in-out infinite" }} />
      <style>{`@keyframes v3-skel { 50% { opacity: 0.5; } }`}</style>
    </div>
  );
}

export default function V3Router() {
  return (
    <Suspense fallback={<ScreenSkeleton />}>
      <Routes>
        <Route element={<ResponsiveLayout />}>
          <Route index element={<Navigate to="home" replace />} />
          <Route path="home" element={<CopilotHome />} />
          <Route path="chat" element={<CopilotChat />} />
          <Route path="chat/:threadId" element={<CopilotChat />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="portfolio" element={<Portfolio />} />
          <Route path="portfolio/diversification" element={<Diversification />} />
          <Route path="portfolio/concentration" element={<Concentration />} />
          <Route path="risk" element={<RiskAnalysis />} />
          <Route path="risk/stress" element={<StressTest />} />
          <Route path="tax" element={<TaxAnalysis />} />
          <Route path="performance" element={<Performance />} />
          <Route path="advisor" element={<Advisor />} />
          <Route path="market" element={<MarketDashboard />} />
          <Route path="settings" element={<Settings />} />
          <Route path="profile" element={<Profile />} />
          <Route path="onboarding" element={<Onboarding />} />
        </Route>
        <Route path="*" element={<Navigate to="home" replace />} />
      </Routes>
    </Suspense>
  );
}
