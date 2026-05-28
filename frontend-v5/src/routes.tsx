import { Routes, Route, Navigate } from "react-router-dom";
import AppLayout from "./components/layout/AppLayout";
import HomepagePage from "./pages/Homepage";
import DashboardPage from "./pages/Dashboard";
import PortfolioPage from "./pages/Portfolio";
import ConcentrationPage from "./pages/Concentration";
import DiversificationPage from "./pages/Diversification";
import RecommendationsPage from "./pages/Recommendations";
import RiskPage from "./pages/Risk";
import FundDetailsPage from "./pages/FundDetails";
import SettingsPage from "./pages/Settings";
import ChatPage from "./pages/Chat";
import LoginPage from "./pages/Login";
import OnboardingPage from "./pages/Onboarding";
import GoalsPage from "./pages/Goals";
import TaxPage from "./pages/Tax";
import PlanPage from "./pages/Plan";
import PerformancePage from "./pages/Performance";

export function AppRoutes() {
  return (
    <Routes>
      {/* Public landing — full-bleed, no sidebar */}
      <Route index element={<HomepagePage />} />

      {/* Auth screens — full-bleed */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/onboarding" element={<OnboardingPage />} />

      {/* Authenticated app — sidebar layout */}
      <Route element={<AppLayout />}>
        <Route path="/dashboard"        element={<DashboardPage />} />
        <Route path="/portfolio"        element={<PortfolioPage />} />
        <Route path="/funds/:id"        element={<FundDetailsPage />} />
        <Route path="/concentration"    element={<ConcentrationPage />} />
        <Route path="/diversification"  element={<DiversificationPage />} />
        <Route path="/risk"             element={<RiskPage />} />
        <Route path="/performance"      element={<PerformancePage />} />
        <Route path="/recommendations"  element={<RecommendationsPage />} />
        <Route path="/chat"             element={<ChatPage />} />
        <Route path="/goals"            element={<GoalsPage />} />
        <Route path="/tax"              element={<TaxPage />} />
        <Route path="/plan"             element={<PlanPage />} />
        <Route path="/settings"         element={<SettingsPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
