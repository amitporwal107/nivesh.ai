import { ArrowUpRight } from "lucide-react";
import { CardLabel } from "@/components/ui/card";
import { SparkArea } from "@/components/charts/SparkArea";
import { formatINR, formatPct } from "@/lib/formatters";
import { useCountUp } from "@/hooks/use-animate";
import type { NavPoint } from "@/types/portfolio";
import type { Paise } from "@/types/common";

interface Props {
  value: Paise;
  yearChangePct: number;
  navHistory: NavPoint[];
}

export function PortfolioValueCard({ value, yearChangePct, navHistory }: Props) {
  const shownValue = useCountUp(value, 1300, 100) as Paise;
  return (
    <div className="md:pr-7">
      <CardLabel>Portfolio value</CardLabel>
      <div className="font-display num text-[44px] sm:text-[52px] leading-none tracking-tightish mt-2">
        {formatINR(Math.round(shownValue) as Paise)}
      </div>
      <div className="flex items-center gap-1.5 mt-2 text-[12px] text-pos">
        <ArrowUpRight className="h-3.5 w-3.5" />
        <span>{formatPct(yearChangePct, { signed: true })} over the last year</span>
      </div>
      <div className="mt-3 -mx-2">
        <SparkArea data={navHistory} height={56} animate />
      </div>
    </div>
  );
}
