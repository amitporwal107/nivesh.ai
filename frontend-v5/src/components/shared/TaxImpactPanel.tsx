import React, { useId } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatINRCompact } from "@/lib/formatters";
import type { TaxImpact } from "@/types/recommendation";

export type { TaxImpact };

interface TaxImpactPanelProps {
  taxImpact?: TaxImpact | null;
  className?: string;
  defaultOpen?: boolean;
}

export function TaxImpactPanel({ taxImpact, className, defaultOpen = false }: TaxImpactPanelProps) {
  const [open, setOpen] = React.useState(defaultOpen);
  const bodyId = useId();

  const hasData =
    taxImpact &&
    (taxImpact.tax_liability != null ||
      taxImpact.stcg != null ||
      taxImpact.ltcg != null ||
      taxImpact.exit_load_rs != null);

  if (!hasData) {
    return (
      <div className={cn("text-[12px] text-ink-3 italic", className)}>
        Tax impact not yet calculated
      </div>
    );
  }

  const ti = taxImpact!;
  const total = ti.tax_liability ?? (ti.stcg ?? 0) + (ti.ltcg ?? 0);
  const isLongTerm = (ti.holding_period_days ?? 0) >= 365;

  return (
    <div className={cn("border border-hairline rounded-md overflow-hidden", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={bodyId}
        className="w-full flex items-center justify-between gap-2 px-4 py-2.5 bg-surface-2 text-left text-[13px] font-medium hover:bg-surface-3 transition-colors"
      >
        <span>
          Tax impact{" "}
          <span className="font-mono text-neg">
            −{formatINRCompact(total)}
          </span>
          {ti.lock_in && (
            <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-warm/10 text-warm">
              Locked
            </span>
          )}
        </span>
        <ChevronDown
          className={cn("h-4 w-4 text-ink-3 transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>

      <div
        id={bodyId}
        hidden={!open}
        className="px-4 py-3 bg-surface-1 grid grid-cols-2 gap-x-6 gap-y-2 text-[12.5px]"
      >
        {ti.stcg != null && ti.stcg > 0 && (
          <Row label="STCG" value={`−${formatINRCompact(ti.stcg)}`} tone="neg" />
        )}
        {ti.ltcg != null && ti.ltcg > 0 && (
          <Row label="LTCG" value={`−${formatINRCompact(ti.ltcg)}`} tone="neg" />
        )}
        {ti.exit_load_rs != null && ti.exit_load_rs > 0 && (
          <Row label="Exit load" value={`−${formatINRCompact(ti.exit_load_rs)}`} tone="neg" />
        )}
        {ti.holding_period_days != null && (
          <Row
            label="Holding period"
            value={`${ti.holding_period_days}d (${isLongTerm ? "LT" : "ST"})`}
          />
        )}
        {ti.lock_in && (
          <Row label="Lock-in" value="ELSS — not redeemable" tone="warm" />
        )}
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "neg" | "warm";
}) {
  return (
    <>
      <span className="text-ink-3">{label}</span>
      <span
        className={cn(
          "font-mono text-right",
          tone === "neg" && "text-neg",
          tone === "warm" && "text-warm",
        )}
      >
        {value}
      </span>
    </>
  );
}
