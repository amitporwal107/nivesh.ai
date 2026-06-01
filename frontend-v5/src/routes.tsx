import { Routes, Route, Navigate } from "react-router-dom";
import AppLayout from "./components/layout/AppLayout";
import { RequireAuth } from "./components/layout/RequireAuth";
import { RequireAdmin } from "./components/layout/RequireAdmin";
import { RouteErrorBoundary } from "./components/shared/RouteErrorBoundary";
import HomepagePage from "./pages/Homepage";
import DashboardPage from "./pages/Dashboard";
import PortfolioPage from "./pages/Portfolio";
import ConcentrationPage from "./pages/Concentration";
import RecommendationsPage from "./pages/Recommendations";
import RiskPage from "./pages/Risk";
import FundDetailsPage from "./pages/FundDetails";
import SettingsPage from "./pages/Settings";
import ChatPage from "./pages/Chat";
import LoginPage from "./pages/Login";
import OnboardingPage from "./pages/Onboarding";
import CasCallbackPage from "./pages/CasCallback";
import GoalsPage from "./pages/Goals";
import TaxPage from "./pages/Tax";
import PlanPage from "./pages/Plan";
import PerformancePage from "./pages/Performance";
import CompositionPage from "./pages/Composition";
import DiagnosticsPage from "./pages/Diagnostics";
import AdminPage from "./pages/Admin";
import NidpConsolePage from "./pages/NidpConsole";

export function AppRoutes() {
  return (
    <Routes>
      {/* Public landing — full-bleed, no sidebar */}
      <Route index element={<HomepagePage />} />

      {/* Auth screens — full-bleed */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/onboarding" element={<OnboardingPage />} />

      {/* CAS Connect widget OAuth popup callback — standalone, no layout */}
      <Route path="/cas-callback" element={<CasCallbackPage />} />

      {/* Diagnostics — standalone, no auth required (reachable even in failure scenarios) */}
      <Route path="/diagnostics" element={<DiagnosticsPage />} />

      {/* Authenticated app — sidebar layout */}
      <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
        <Route path="/dashboard"        element={<RouteErrorBoundary pageName="Dashboard"><DashboardPage /></RouteErrorBoundary>} />
        <Route path="/portfolio"        element={<RouteErrorBoundary pageName="Portfolio"><PortfolioPage /></RouteErrorBoundary>} />
        <Route path="/funds/:id"        element={<RouteErrorBoundary pageName="Fund Details"><FundDetailsPage /></RouteErrorBoundary>} />
        <Route path="/ai-insights"      element={<RouteErrorBoundary pageName="AI Insights"><ConcentrationPage /></RouteErrorBoundary>} />
        <Route path="/concentration"    element={<Navigate to="/ai-insights" replace />} />
        <Route path="/diversification"  element={<Navigate to="/ai-insights" replace />} />
        <Route path="/risk"             element={<RouteErrorBoundary pageName="Risk"><RiskPage /></RouteErrorBoundary>} />
        <Route path="/performance"      element={<RouteErrorBoundary pageName="Performance"><PerformancePage /></RouteErrorBoundary>} />
        <Route path="/composition"      element={<RouteErrorBoundary pageName="Composition"><CompositionPage /></RouteErrorBoundary>} />
        <Route path="/recommendations"  element={<RouteErrorBoundary pageName="Recommendations"><RecommendationsPage /></RouteErrorBoundary>} />
        <Route path="/chat"             element={<RouteErrorBoundary pageName="Chat"><ChatPage /></RouteErrorBoundary>} />
        <Route path="/goals"            element={<RouteErrorBoundary pageName="Goals"><GoalsPage /></RouteErrorBoundary>} />
        <Route path="/tax"              element={<RouteErrorBoundary pageName="Tax"><TaxPage /></RouteErrorBoundary>} />
        <Route path="/plan"             element={<RouteErrorBoundary pageName="Plan"><PlanPage /></RouteErrorBoundary>} />
        <Route path="/settings"         element={<RouteErrorBoundary pageName="Settings"><SettingsPage /></RouteErrorBoundary>} />
        {/* Admin-only routes — RequireAdmin redirects non-admins to /dashboard */}
        <Route path="/admin"            element={<RequireAdmin><RouteErrorBoundary pageName="Admin"><AdminPage /></RouteErrorBoundary></RequireAdmin>} />
        <Route path="/nidp"             element={<RequireAdmin><RouteErrorBoundary pageName="NIDP Console"><NidpConsolePage /></RouteErrorBoundary></RequireAdmin>} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
