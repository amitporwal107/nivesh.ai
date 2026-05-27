import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Tax dashboard — placeholder wired to the dashboards service.
 * Shows tax summary data from the backend when available.
 */
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
const TAX_ROWS = [
    { label: "Short-term gains", value: "Connect portfolio", rate: "15%", tax: "—" },
    { label: "Long-term gains", value: "to see your", rate: "10% > 1L", tax: "—" },
    { label: "Dividend income", value: "actual numbers", rate: "slab", tax: "—" },
    { label: "After harvest", value: "here", rate: "net", tax: "—" },
];
function TaxKpiCard({ label, value, sub, tone }) {
    const colorMap = { good: "text-pos", warm: "text-warm", neg: "text-neg", accent: "text-accent" };
    return (_jsxs("div", { className: "rounded-lg bg-surface-1 border border-hairline p-4", children: [_jsx("div", { className: "font-mono text-[10px] uppercase tracking-[.14em] text-ink-3", children: label }), _jsx("div", { className: `font-display text-2xl num mt-1 ${colorMap[tone]}`, children: value }), _jsx("div", { className: "font-mono text-[10px] text-ink-3 mt-0.5", children: sub })] }));
}
export default function TaxPage() {
    const fy = new Date().getFullYear();
    const fyLabel = `FY ${String(fy).slice(2)}–${String(fy + 1).slice(2)}`;
    const daysToMar31 = (() => {
        const mar31 = new Date(fy + 1, 2, 31);
        const today = new Date();
        return Math.max(0, Math.round((mar31.getTime() - today.getTime()) / 86_400_000));
    })();
    return (_jsxs("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full", children: [_jsxs("div", { className: "font-mono text-[11px] uppercase tracking-[.18em] text-ink-3", children: ["Tax \u00B7 ", fyLabel] }), _jsx("h1", { className: "font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5", children: "Your tax picture, plain and simple." }), _jsx("p", { className: "text-[15.5px] text-ink-2 mt-3 max-w-[600px] leading-relaxed", children: "Connect your portfolio to see realised gains, available losses to harvest, and exactly how much you can save before March 31." }), _jsxs("div", { className: "mt-7 grid grid-cols-2 sm:grid-cols-4 gap-3", children: [_jsx(TaxKpiCard, { label: "Net tax owed", value: "\u2014", sub: `${fyLabel} estimate`, tone: "warm" }), _jsx(TaxKpiCard, { label: "Harvest available", value: "\u2014", sub: "unrealised losses", tone: "good" }), _jsx(TaxKpiCard, { label: "Net you save", value: "\u2014", sub: "if you harvest", tone: "good" }), _jsx(TaxKpiCard, { label: "Days to Mar 31", value: String(daysToMar31), sub: "window open", tone: "accent" })] }), _jsxs(Card, { className: "mt-5 p-6", children: [_jsxs(CardLabel, { children: ["Tax breakdown \u00B7 ", fyLabel] }), _jsx("div", { className: "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-4", children: TAX_ROWS.map((row) => (_jsxs("div", { className: "rounded-lg bg-surface-2 border border-hairline p-4", children: [_jsx("div", { className: "font-mono text-[10px] uppercase tracking-[.10em] text-ink-3", children: row.label }), _jsx("div", { className: "font-display text-xl num mt-1", children: row.value }), _jsxs("div", { className: "font-mono text-[10px] text-ink-3 mt-1", children: [row.rate, " \u00B7 ", _jsx("span", { className: "num", children: row.tax })] })] }, row.label))) })] }), _jsxs(Card, { className: "mt-4 p-6", children: [_jsxs("div", { className: "flex items-center mb-4", children: [_jsx(CardLabel, { children: "Harvest plan" }), _jsx(Badge, { tone: "accent", className: "ml-auto", children: "0 lots flagged" })] }), _jsx("div", { className: "py-10 text-center font-mono text-[12px] text-ink-3", children: "No lots flagged yet \u2014 connect your holdings to see harvest opportunities." }), _jsx("button", { className: "mt-2 w-full rounded-lg bg-accent text-white font-medium text-[13px] py-3 hover:bg-accent/90 transition-colors", children: "Import portfolio \u2192" })] }), daysToMar31 < 90 && (_jsxs("div", { className: "mt-4 rounded-lg bg-warm-soft border border-warm/20 p-4 text-[13.5px]", children: [_jsxs("span", { className: "font-medium text-warm", children: [daysToMar31, " days left"] }), " ", "until the FY end harvest window closes. Act before March 31 to lock in your savings."] }))] }));
}
