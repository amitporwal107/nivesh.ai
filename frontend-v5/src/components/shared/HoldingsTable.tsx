import { useNavigate } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatINR, formatPct } from "@/lib/formatters";
import type { Holding } from "@/types/fund";

interface Props {
  holdings: Holding[];
  className?: string;
}

/**
 * Holdings table — desktop. On mobile this collapses to a stacked list.
 * Click row → /funds/:id.
 */
export function HoldingsTable({ holdings, className }: Props) {
  const navigate = useNavigate();

  return (
    <div className={cn("rounded-lg bg-surface-1 border border-hairline overflow-hidden", className)}>
      {/* desktop */}
      <table className="hidden sm:table w-full text-sm">
        <thead>
          <tr className="border-b border-hairline">
            {["Fund", "Category", "Units", "Market value", "P&L", "1Y", ""].map((h) => (
              <th
                key={h}
                className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 font-normal text-left px-5 py-3"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {holdings.map((h) => (
            <tr
              key={h.id}
              onClick={() => navigate(`/funds/${h.fundId}`)}
              className="border-t border-hairline hover:bg-surface-2 cursor-pointer transition-colors"
            >
              <td className="px-5 py-4 align-top">
                <div className="font-medium text-[14px]">{h.fund.name}</div>
                <div className="font-mono text-[10.5px] text-ink-3 mt-1">{h.fund.amc}</div>
              </td>
              <td className="px-5 py-4 align-top">
                <span className="font-mono text-[11px] uppercase tracking-[.06em] text-ink-2">
                  {h.fund.category.replace("-", " ")}
                </span>
              </td>
              <td className="px-5 py-4 align-top font-mono num text-[13px] text-ink-2">
                {h.units.toFixed(2)}
              </td>
              <td className="px-5 py-4 align-top font-mono num text-[13px]">
                {formatINR(h.marketValue)}
              </td>
              <td className="px-5 py-4 align-top font-mono num text-[13px] text-pos">
                +{formatINR(h.unrealizedPnl, { compact: true })}
                <span className="text-ink-3 text-[11px] ml-1">({formatPct(h.unrealizedPnlPct, { signed: true })})</span>
              </td>
              <td className="px-5 py-4 align-top font-mono num text-[13px] text-pos">
                {formatPct(h.returns.y1, { signed: true })}
              </td>
              <td className="px-5 py-4 align-top text-ink-3">
                <ChevronRight className="h-4 w-4" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* mobile */}
      <ul className="sm:hidden divide-y divide-[rgb(var(--line)/0.10)]">
        {holdings.map((h) => (
          <li
            key={h.id}
            onClick={() => navigate(`/funds/${h.fundId}`)}
            className="px-5 py-4 active:bg-surface-2"
          >
            <div className="flex items-baseline gap-2">
              <span className="font-medium text-[14px]">{h.fund.name}</span>
              <span className="ml-auto font-mono num text-[13px]">{formatINR(h.marketValue, { compact: true })}</span>
            </div>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="font-mono text-[10.5px] uppercase tracking-[.06em] text-ink-3">
                {h.fund.category.replace("-", " ")}
              </span>
              <span className="ml-auto font-mono text-[11px] text-pos">
                {formatPct(h.returns.y1, { signed: true })}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
