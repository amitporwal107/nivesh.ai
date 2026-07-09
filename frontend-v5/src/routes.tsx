import { Routes, Route, Navigate } from "react-router-dom";
import AppLayout from "./components/layout/AppLayout";
import { RequireAuth } from "./components/layout/RequireAuth";
import { RequireAdmin } from "./components/layout/RequireAdmin";
import { RouteErrorBoundary } from "./components/shared/RouteErrorBoundary";
import HomepagePage from "./pages/Homepage";
import ProductPage from "./pages/Product";
import CopilotPage from "./pages/Copilot";
import AdvisorsPage from "./pages/Advisors";
import PricingPage from "./pages/Pricing";
import AboutPage from "./pages/About";
import SecurityPage from "./pages/Security";
import ContactPage from "./pages/Contact";
import PrivacyPage from "./pages/Privacy";
import TermsPage from "./pages/Terms";
import DisclosurePage from "./pages/Disclosure";
import BlogIndexPage from "./pages/Blog";
import BlogArticlePage from "./pages/Blog/Article";
import DashboardPage from "./pages/Dashboard";
import ConcentrationPage from "./pages/Concentration";
import RecommendationsPage from "./pages/Recommendations";
import RiskPage from "./pages/Risk";
import FundDetailsPage from "./pages/FundDetails";
import SettingsPage from "./pages/Settings";
import LogsPage from "./pages/Logs";
import ReleasesPage from "./pages/Releases";
import ReleaseDetailPage from "./pages/Releases/ReleaseDetail";
import ChatPage from "./pages/Chat";
import LoginPage from "./pages/Login";
import OnboardingPage from "./pages/Onboarding";
import CasCallbackPage from "./pages/CasCallback";
import GmailCallbackPage from "./pages/GmailCallback";
import GoalsPage from "./pages/Goals";
import TaxPage from "./pages/Tax";
import PlanPage from "./pages/Plan";
import PerformancePage from "./pages/Performance";
import CompositionPage from "./pages/Composition";
import DiagnosticsPage from "./pages/Diagnostics";
import AdminPage from "./pages/Admin";
import WorkPage from "./pages/Work";
import TestDiagnosticToolPage from "./pages/TestDiagnosticTool";
import NidpConsolePage from "./pages/NidpConsole";
import ProTraderPage from "./pages/ProTrader";
import StrategyBuilderPage from "./pages/StrategyBuilder";
import LearnPage from "./pages/Learn";
import MarketsPage from "./pages/Markets";
import MarketPulseLayout from "./pages/Markets/MarketPulseLayout";
import EarningsPage from "./pages/Markets/Earnings";
import FiiDiiPage from "./pages/Markets/FiiDii";
import CorporateActionsPage from "./pages/Markets/CorporateActions";
import ArticlesPage from "./pages/Markets/Articles";
import DailyBriefPage from "./pages/Markets/DailyBrief";
import SectorAnalysisPage from "./pages/Markets/SectorAnalysis";
import SectorAnalysisDetailPage from "./pages/Markets/SectorAnalysisDetail";
import AdvisorDashboardPage from "./pages/AdvisorDashboard";
import Client360Page from "./pages/Client360";
import DebugLogsPage from "./pages/DebugLogs";

export function AppRoutes() {
  return (
    <Routes>
      {/* Public landing — full-bleed, no sidebar */}
      <Route index element={<HomepagePage />} />

      {/* Public marketing pages — full-bleed, no sidebar */}
      <Route path="/product" element={<ProductPage />} />
      <Route path="/copilot" element={<CopilotPage />} />
      <Route path="/for-advisors" element={<AdvisorsPage />} />
      <Route path="/pricing" element={<PricingPage />} />
      <Route path="/about" element={<AboutPage />} />
      <Route path="/security" element={<SecurityPage />} />
      <Route path="/contact" element={<ContactPage />} />
      <Route path="/privacy" element={<PrivacyPage />} />
      <Route path="/terms" element={<TermsPage />} />
      <Route path="/disclosure" element={<DisclosurePage />} />
      <Route path="/blog" element={<BlogIndexPage />} />
      <Route path="/blog/:slug" element={<BlogArticlePage />} />

      {/* Auth screens — full-bleed */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/onboarding" element={<OnboardingPage />} />

      {/* CAS Connect widget OAuth popup callback — standalone, no layout */}
      <Route path="/cas-callback" element={<CasCallbackPage />} />

      {/* Gmail OAuth popup callback — relays outcome to opener, no layout */}
      <Route path="/gmail-callback" element={<GmailCallbackPage />} />

      {/* Diagnostics — standalone, no auth required (reachable even in failure scenarios) */}
      <Route path="/diagnostics"          element={<DiagnosticsPage />} />
      {/* Self-diagnostic tool test report — no auth, accessible even when app auth is broken */}
      <Route path="/testSelfDiagnosticTool" element={<TestDiagnosticToolPage />} />
      {/* On-device debug log viewer — no auth, for diagnosing native app errors */}
      <Route path="/debug-logs" element={<DebugLogsPage />} />

      {/* Authenticated app — sidebar layout */}
      <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
        <Route path="/dashboard"        element={<RouteErrorBoundary pageName="Dashboard"><DashboardPage /></RouteErrorBoundary>} />
        <Route path="/markets" element={<RouteErrorBoundary pageName="Markets"><MarketPulseLayout /></RouteErrorBoundary>}>
          <Route index element={<MarketsPage />} />
          <Route path="earnings" element={<EarningsPage />} />
          <Route path="fii-dii" element={<FiiDiiPage />} />
          <Route path="corporate-actions" element={<CorporateActionsPage />} />
          <Route path="articles" element={<ArticlesPage />} />
          <Route path="daily-brief" element={<DailyBriefPage />} />
          <Route path="sectors" element={<SectorAnalysisPage />} />
          <Route path="sectors/:slug" element={<SectorAnalysisDetailPage />} />

        </Route>
        <Route path="/advisor"          element={<RouteErrorBoundary pageName="Advisor"><AdvisorDashboardPage /></RouteErrorBoundary>} />
        <Route path="/client-360"       element={<RouteErrorBoundary pageName="Client 360"><Client360Page /></RouteErrorBoundary>} />
        {/* Portfolio view now lives on the Dashboard; keep the path as a redirect for old links. */}
        <Route path="/portfolio"        element={<Navigate to="/dashboard" replace />} />
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
        <Route path="/settings/logs"    element={<RouteErrorBoundary pageName="Session Logs"><LogsPage /></RouteErrorBoundary>} />
        <Route path="/settings/releases"     element={<RequireAdmin><RouteErrorBoundary pageName="Release Management"><ReleasesPage /></RouteErrorBoundary></RequireAdmin>} />
        <Route path="/settings/releases/:id" element={<RequireAdmin><RouteErrorBoundary pageName="Release Document"><ReleaseDetailPage /></RouteErrorBoundary></RequireAdmin>} />
        <Route path="/pro-trader"       element={<RouteErrorBoundary pageName="Pro Trader"><ProTraderPage /></RouteErrorBoundary>} />
        <Route path="/strategy-builder" element={<RouteErrorBoundary pageName="Strategy Builder"><StrategyBuilderPage /></RouteErrorBoundary>} />
        <Route path="/learn"            element={<RouteErrorBoundary pageName="Learn"><LearnPage /></RouteErrorBoundary>} />
        {/* Admin-only routes — RequireAdmin redirects non-admins to /dashboard */}
        <Route path="/admin"            element={<RequireAdmin><RouteErrorBoundary pageName="Admin"><AdminPage /></RouteErrorBoundary></RequireAdmin>} />
        <Route path="/nidp"             element={<RequireAdmin><RouteErrorBoundary pageName="NIDP Console"><NidpConsolePage /></RouteErrorBoundary></RequireAdmin>} />
        <Route path="/work"             element={<RequireAdmin><RouteErrorBoundary pageName="Work"><WorkPage /></RouteErrorBoundary></RequireAdmin>} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
