import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useLocation } from "react-router-dom";
import { Menu } from "lucide-react";
import { cn } from "@/lib/utils";
const TITLE_MAP = {
    "/dashboard": "Dashboard",
    "/portfolio": "Portfolio",
    "/risk": "Risk analysis",
    "/recommendations": "Recommendations",
    "/chat": "Chat",
    "/settings": "Settings",
};
export function Topbar({ className }) {
    const { pathname } = useLocation();
    const title = TITLE_MAP[pathname] ?? "Nivesh";
    return (_jsxs("header", { className: cn("sticky top-0 z-30 bg-bg/85 backdrop-blur border-b border-hairline", "flex items-center gap-3 px-5 h-14", className), children: [_jsx("button", { type: "button", "aria-label": "Open menu", className: "grid place-items-center h-9 w-9 rounded-md text-ink-2 hover:bg-surface-2", children: _jsx(Menu, { className: "h-5 w-5" }) }), _jsx("span", { className: "font-display text-lg tracking-tightish", children: title }), _jsx("span", { className: "ml-auto grid place-items-center h-8 w-8 rounded-md bg-ink text-on-accent font-display text-base leading-none", children: "\u0928" })] }));
}
