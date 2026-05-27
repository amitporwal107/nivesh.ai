import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Routes, Route, Navigate } from "react-router-dom";
import AppLayout from "./components/layout/AppLayout";
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
export function AppRoutes() {
    return (_jsxs(Routes, { children: [_jsx(Route, { path: "/login", element: _jsx(LoginPage, {}) }), _jsx(Route, { path: "/onboarding", element: _jsx(OnboardingPage, {}) }), _jsxs(Route, { element: _jsx(AppLayout, {}), children: [_jsx(Route, { index: true, element: _jsx(Navigate, { to: "/dashboard", replace: true }) }), _jsx(Route, { path: "/dashboard", element: _jsx(DashboardPage, {}) }), _jsx(Route, { path: "/portfolio", element: _jsx(PortfolioPage, {}) }), _jsx(Route, { path: "/funds/:id", element: _jsx(FundDetailsPage, {}) }), _jsx(Route, { path: "/concentration", element: _jsx(ConcentrationPage, {}) }), _jsx(Route, { path: "/diversification", element: _jsx(DiversificationPage, {}) }), _jsx(Route, { path: "/risk", element: _jsx(RiskPage, {}) }), _jsx(Route, { path: "/recommendations", element: _jsx(RecommendationsPage, {}) }), _jsx(Route, { path: "/chat", element: _jsx(ChatPage, {}) }), _jsx(Route, { path: "/goals", element: _jsx(GoalsPage, {}) }), _jsx(Route, { path: "/tax", element: _jsx(TaxPage, {}) }), _jsx(Route, { path: "/plan", element: _jsx(PlanPage, {}) }), _jsx(Route, { path: "/settings", element: _jsx(SettingsPage, {}) })] }), _jsx(Route, { path: "*", element: _jsx(Navigate, { to: "/dashboard", replace: true }) })] }));
}
