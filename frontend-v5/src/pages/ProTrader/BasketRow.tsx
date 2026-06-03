import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import type { BasketItem } from "@/services/contracts/positional.contract";

function fmt(n: number | null | undefined, decimals = 2) {
  if (n == null) return "—";
  return n.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
function fmtRs(n: number | null | undefined) {
  if (n == null) return "—";
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

const STAGE_COLORS: Record<string, string> = {
  ACCUMULATION:   "bg-amber-100 text-amber-800",
  EARLY_BREAKOUT: "bg-emerald-100 text-emerald-800",
  BREAKOUT:       "bg-blue-100 text-blue-800",
  EXTENDED:       "bg-orange-100 text-orange-800",
  WEAK:           "bg-gray-100 text-gray-600",
};

const READINESS_COLORS: Record<string, string> = {
  TRIGGERED: "bg-emerald-100 text-emerald-800",
  NEAR:      "bg-blue-100 text-blue-800",
  WAIT:      "bg-amber-100 text-amber-700",
  FAR:       "bg-gray-100 text-gray-500",
  LATE:      "bg-red-100 text-red-700",
  STOPPED:   "bg-red-200 text-red-800",
};

interface Props {
  item: BasketItem;
  index: number;
}

export function BasketRow({ item, index }: Props) {
  const stageColor = STAGE_COLORS[(item.stage ?? "").toUpperCase()] ?? "bg-gray-100 text-gray-600";
  const readinessColor = READINESS_COLORS[(item.readiness ?? "").toUpperCase()] ?? "bg-gray-100 text-gray-500";

  return (
    <tr className="border-b border-hairline last:border-0 hover:bg-surface-1 transition-colors">
      {/* # */}
      <td className="py-3 pl-4 pr-2 text-center font-mono text-[11px] text-ink-4">{index + 1}</td>

      {/* Symbol + stage + readiness */}
      <td className="py-3 pr-4">
        <div className="flex flex-col gap-1">
          <span className="font-semibold text-[13.5px] text-ink">{item.symbol}</span>
          <div className="flex items-center gap-1.5 flex-wrap">
            {item.stage && (
              <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide", stageColor)}>
                {item.stage.replace("_", " ")}
              </span>
            )}
            {item.readiness && (
              <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide", readinessColor)}>
                {item.readiness}
              </span>
            )}
          </div>
        </div>
      </td>

      {/* Live price */}
      <td className="py-3 pr-4 text-right">
        <span className="font-mono text-[12px] text-ink-2">
          {item.live_price != null ? fmtRs(item.live_price) : "—"}
        </span>
      </td>

      {/* Entry */}
      <td className="py-3 pr-3 text-right">
        <span className="font-mono text-[12px] text-ink">{fmtRs(item.entry_price)}</span>
      </td>

      {/* Stop loss */}
      <td className="py-3 pr-3 text-right">
        <span className="font-mono text-[12px] text-red-600">{fmtRs(item.stoploss)}</span>
      </td>

      {/* Target */}
      <td className="py-3 pr-3 text-right">
        <span className="font-mono text-[12px] text-emerald-600">{fmtRs(item.target_price)}</span>
      </td>

      {/* RR */}
      <td className="py-3 pr-3 text-right">
        <span className="font-mono text-[12px] text-ink-2">1:{fmt(item.risk_reward, 1)}</span>
      </td>

      {/* Horizon */}
      <td className="py-3 pr-3 text-right">
        <span className="font-mono text-[11px] text-ink-3">
          {item.horizon_days_min ?? "?"}–{item.horizon_days_max ?? "?"}d
        </span>
      </td>

      {/* Qty */}
      <td className="py-3 pr-3 text-right">
        <span className="font-mono text-[12px] text-ink font-medium">{item.qty}</span>
      </td>

      {/* Capital deployed */}
      <td className="py-3 pr-3 text-right">
        <div className="flex flex-col items-end gap-0.5">
          <span className="font-mono text-[12px] text-ink">{fmtRs(item.allocated_rs)}</span>
          <span className="font-mono text-[10px] text-red-500">Risk {fmtRs(item.risk_rs)}</span>
        </div>
      </td>

      {/* Hedge */}
      <td className="py-3 pl-1 pr-4 text-right">
        {item.hedge ? (
          <div className="flex flex-col items-end gap-0.5">
            <span className="font-mono text-[11px] text-ink-2">{fmtRs(item.hedge.cost_rs)}</span>
            <span className="font-mono text-[10px] text-ink-4">
              {fmt(item.hedge.cost_pct, 1)}% · {item.hedge.hedge_type === "NIFTY_PE_PROXY" ? "Nifty proxy" : `PE @${fmtRs(item.hedge.put_strike)}`}
            </span>
          </div>
        ) : (
          <span className="text-[11px] text-ink-4">No F&O</span>
        )}
      </td>
    </tr>
  );
}
