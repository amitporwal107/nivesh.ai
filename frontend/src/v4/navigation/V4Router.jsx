import React, { Suspense, lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";

/*
 * V4 router — every P0 screen lazy-loaded so the V2/V3 bundle stays slim
 * (V4 only ships its chunks when a user actually visits /v4/*).
 *
 * Build order (per V4_PHASE2_PLAN.md):
 *   M1: Homepage
 *   M2: Onboarding
 *   M3: Copilot Landing + Plan Board
 *   M4: Concentration + Diversification + Risk
 *   M5: Goals
 *   M6: Portfolio Dashboard (pending design spec)
 */

const Homepage = lazy(() => import("../screens/Homepage"));
const Onboarding = lazy(() => import("../screens/onboarding/Onboarding"));
const CasCallback = lazy(() => import("../screens/CasCallback"));
const CopilotLanding = lazy(() => import("../screens/CopilotLanding"));
const Concentration = lazy(() => import("../screens/Concentration"));
const Diversification = lazy(() => import("../screens/Diversification"));
const Risk = lazy(() => import("../screens/Risk"));
const ActionPlan = lazy(() => import("../screens/ActionPlan"));
const Goals = lazy(() => import("../screens/Goals"));

function ScreenSkeleton() {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--v4-bg)",
        display: "grid",
        placeItems: "center",
      }}
    >
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: "50%",
          border: "2px solid var(--v4-line-strong)",
          borderTopColor: "var(--v4-saffron)",
          animation: "v4-spin 0.9s linear infinite",
        }}
      />
      <style>{`@keyframes v4-spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

export default function V4Router() {
  return (
    <Suspense fallback={<ScreenSkeleton />}>
      <Routes>
        <Route index element={<Homepage />} />
        <Route path="home" element={<Homepage />} />
        <Route path="onboarding" element={<Onboarding />} />
        <Route path="cas-callback" element={<CasCallback />} />
        <Route path="landing" element={<CopilotLanding />} />
        <Route path="concentration" element={<Concentration />} />
        <Route path="diversification" element={<Diversification />} />
        <Route path="risk" element={<Risk />} />
        <Route path="plan" element={<ActionPlan />} />
        <Route path="goals" element={<Goals />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
