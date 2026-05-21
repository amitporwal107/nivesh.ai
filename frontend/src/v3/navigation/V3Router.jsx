import React, { Suspense, lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import ResponsiveLayout from "./ResponsiveLayout";

// First-run guard: send users who haven't seen the 10-second flow to /onboarding.
// Reads localStorage; safe outside a browser (returns true so SSR/tests don't loop).
function hasOnboarded() {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem("v3.onboarded") === "1";
  } catch {
    return true;
  }
}

function HomeOrOnboarding() {
  return hasOnboarded() ? <Navigate to="home" replace /> : <Navigate to="onboarding" replace />;
}

/**
 * Internal auth gate — V3 itself is mounted publicly so unauthenticated users
 * can see the onboarding welcome (which exposes Google sign-in). Once they
 * leave onboarding, this gate kicks them back if they aren't authenticated.
 */
function V3Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div style={{ minHeight: "100vh", background: "var(--v3-bg-0)", display: "grid", placeItems: "center" }}>
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: "50%",
            border: "2px solid var(--v3-line-strong)",
            borderTopColor: "var(--v3-saffron)",
            animation: "v3-spin 0.9s linear infinite",
          }}
        />
        <style>{`@keyframes v3-spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }
  if (!user) return <Navigate to="onboarding" replace />;
  return children;
}

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
          <Route index element={<HomeOrOnboarding />} />
          {/* Onboarding is PUBLIC — exposes Google sign-in inside the flow. */}
          <Route path="onboarding" element={<Onboarding />} />
          {/* Everything else requires auth via the internal V3Protected gate. */}
          <Route path="home" element={<V3Protected><CopilotHome /></V3Protected>} />
          <Route path="chat" element={<V3Protected><CopilotChat /></V3Protected>} />
          <Route path="chat/:threadId" element={<V3Protected><CopilotChat /></V3Protected>} />
          <Route path="dashboard" element={<V3Protected><Dashboard /></V3Protected>} />
          <Route path="portfolio" element={<V3Protected><Portfolio /></V3Protected>} />
          <Route path="portfolio/diversification" element={<V3Protected><Diversification /></V3Protected>} />
          <Route path="portfolio/concentration" element={<V3Protected><Concentration /></V3Protected>} />
          <Route path="risk" element={<V3Protected><RiskAnalysis /></V3Protected>} />
          <Route path="risk/stress" element={<V3Protected><StressTest /></V3Protected>} />
          <Route path="tax" element={<V3Protected><TaxAnalysis /></V3Protected>} />
          <Route path="performance" element={<V3Protected><Performance /></V3Protected>} />
          <Route path="advisor" element={<V3Protected><Advisor /></V3Protected>} />
          <Route path="market" element={<V3Protected><MarketDashboard /></V3Protected>} />
          <Route path="settings" element={<V3Protected><Settings /></V3Protected>} />
          <Route path="profile" element={<V3Protected><Profile /></V3Protected>} />
        </Route>
        <Route path="*" element={<Navigate to="home" replace />} />
      </Routes>
    </Suspense>
  );
}
