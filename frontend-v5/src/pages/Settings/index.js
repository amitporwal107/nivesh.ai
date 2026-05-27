import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Card, CardLabel } from "@/components/ui/card";
import { useUIStore } from "@/stores/ui.store";
import { useMe, useLogout } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";
export default function SettingsPage() {
    const { theme, setTheme } = useUIStore();
    const { data: me } = useMe();
    const logout = useLogout();
    const email = me?.email ?? "—";
    return (_jsxs("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[820px] mx-auto w-full", children: [_jsx("div", { className: "font-mono text-[11px] uppercase tracking-[.18em] text-ink-3", children: "Settings" }), _jsx("h1", { className: "font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5", children: "Make it yours." }), _jsx("p", { className: "text-[15.5px] text-ink-2 mt-3 max-w-[560px] leading-relaxed", children: "Pick a look, control your notifications, manage your data. Changes save automatically." }), _jsxs(Card, { className: "mt-7 p-6", children: [_jsx(CardLabel, { children: "Theme" }), _jsx("div", { className: "grid grid-cols-2 gap-3 mt-4", children: [
                            { v: "light", l: "Light", sw: ["#FAFAF7", "#0F172A", "#4338CA"] },
                            { v: "dark", l: "Dark", sw: ["#0B0E14", "#ECEEF3", "#8177E8"] },
                        ].map((t) => {
                            const on = theme === t.v;
                            return (_jsxs("button", { type: "button", onClick: () => setTheme(t.v), "aria-pressed": on, className: cn("rounded-md p-4 text-left transition-colors border", on ? "bg-accent-soft border-accent/30" : "bg-surface-1 border-hairline hover:bg-surface-2"), children: [_jsx("div", { className: "flex gap-1.5 mb-3", children: t.sw.map((c, i) => _jsx("span", { className: "flex-1 h-7 rounded-sm border border-black/5", style: { background: c } }, i)) }), _jsx("div", { className: "text-[13px] font-medium", children: t.l })] }, t.v));
                        }) })] }), _jsxs(Card, { className: "mt-4 p-6", children: [_jsx(CardLabel, { children: "Notifications" }), _jsx("ul", { className: "mt-3 divide-y divide-[rgb(var(--line)/0.10)]", children: [
                            { l: "A goal needs a top-up", on: true },
                            { l: "Tax-saving window opens", on: true },
                            { l: "My SIP runs each month", on: false },
                            { l: "Daily money update", on: false },
                        ].map((s) => (_jsxs("li", { className: "flex items-center py-3", children: [_jsx("span", { className: "text-[14px]", children: s.l }), _jsx("span", { className: cn("ml-auto h-6 w-10 rounded-full relative transition-colors", s.on ? "bg-accent" : "bg-surface-3"), children: _jsx("span", { className: cn("absolute top-0.5 h-5 w-5 rounded-full bg-surface-1 transition-all shadow", s.on ? "left-[18px]" : "left-0.5") }) })] }, s.l))) })] }), _jsxs(Card, { className: "mt-4 p-6", children: [_jsx(CardLabel, { children: "Account" }), _jsxs("div", { className: "mt-3 text-[14px]", children: [_jsx("div", { children: email }), _jsx("div", { className: "font-mono text-[11px] text-ink-3 mt-1", children: "Connected \u00B7 Gmail OAuth" })] }), _jsxs("div", { className: "mt-5 flex gap-2", children: [_jsx("button", { className: "text-[13px] text-ink-2 hover:text-ink underline-offset-4 hover:underline", children: "Export my data" }), _jsx("span", { className: "text-ink-4", children: "\u00B7" }), _jsx("button", { className: "text-[13px] text-neg hover:underline underline-offset-4", onClick: () => logout.mutate(), children: "Sign out" })] })] })] }));
}
