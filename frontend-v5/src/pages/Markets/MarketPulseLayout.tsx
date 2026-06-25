import { NavLink, Outlet } from "react-router-dom";
import { cn } from "@/lib/utils";

/**
 * Market Pulse hub — a thin tab strip over the three Phase-1 surfaces. Each tab
 * owns its own header + data fetching; this layout only switches between them.
 *
 *   /markets                     → Market (indices, breadth, movers, sectors)
 *   /markets/fii-dii             → FII / DII flows
 *   /markets/corporate-actions   → Corporate-action calendar
 */
const TABS: { to: string; label: string; end?: boolean }[] = [
  { to: "/markets", label: "Market", end: true },
  { to: "/markets/earnings", label: "Earnings Tracker" },
  { to: "/markets/fii-dii", label: "FII / DII" },
  { to: "/markets/corporate-actions", label: "Corporate Actions" },
  { to: "/markets/articles", label: "Articles" },
  { to: "/markets/daily-brief", label: "Daily Iris Update" },
];

export default function MarketPulseLayout() {
  return (
    <div>
      <div className="border-b border-hairline">
        <div className="mx-auto w-full max-w-[1180px] px-6 lg:px-10">
          <nav className="-mb-px flex gap-6 overflow-x-auto" aria-label="Market Pulse sections">
            {TABS.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.end}
                className={({ isActive }) =>
                  cn(
                    "whitespace-nowrap border-b-2 py-3 text-[13px] font-medium transition-colors",
                    isActive
                      ? "border-ink text-ink"
                      : "border-transparent text-ink-3 hover:text-ink-2",
                  )
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </div>
      <Outlet />
    </div>
  );
}
