import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { MobileBottomNav } from "./MobileBottomNav";
/**
 * AppLayout — chrome around all authenticated pages.
 *
 * Responsive contract:
 *   ≥ lg: persistent Sidebar (224px) + content
 *   < lg: Topbar + MobileBottomNav
 */
export default function AppLayout() {
    return (_jsxs("div", { className: "min-h-screen bg-bg text-ink flex", children: [_jsx(Sidebar, { className: "hidden lg:flex" }), _jsxs("div", { className: "flex-1 flex flex-col min-w-0", children: [_jsx(Topbar, { className: "lg:hidden" }), _jsx("main", { className: "flex-1 min-w-0 pb-20 lg:pb-0", children: _jsx(Outlet, {}) }), _jsx(MobileBottomNav, { className: "lg:hidden" })] })] }));
}
