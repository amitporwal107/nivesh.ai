import React from "react";
import FundCardWidget from "./FundCardWidget";
import MarketBriefWidget from "./MarketBriefWidget";
import CompareTableWidget from "./CompareTableWidget";
import SipPlanWidget from "./SipPlanWidget";
import RebalancePlanWidget from "./RebalancePlanWidget";
import TaxHarvestWidget from "./TaxHarvestWidget";
import StressTestWidget from "./StressTestWidget";
import SectorRotationWidget from "./SectorRotationWidget";
import OverlapRevealWidget from "./OverlapRevealWidget";
import InsightCardWidget from "./InsightCardWidget";
import SkeletonCard from "../shared/SkeletonCard";

/**
 * WidgetRenderer — dispatches a server-produced envelope to the right
 * widget component.
 *
 * Surfaces:
 *   - embedded="chat"  → AI Copilot chat. ALWAYS renders InsightCardWidget
 *                        (legacy per-kind widgets are off in chat).
 *   - embedded="drawer" / "insights" / "dashboard" → legacy per-kind
 *     widgets remain available for surfaces that read native data shapes
 *     directly (e.g. inline JSX on the Insights tabs).
 */
const WidgetRenderer = ({ envelope, onAction, embedded = "chat", testId }) => {
  if (!envelope) return null;
  if (envelope.partial) {
    return <SkeletonCard lines={5} testId={testId ? `${testId}-skeleton` : undefined} />;
  }

  // Chat surface is unified — every envelope routes through the
  // mobile-first InsightCardWidget. The backend NIDP adapter upgrades
  // legacy widget kinds to insight_card; if anything still slips through
  // with a legacy kind, fall back to insight_card with the same data so
  // the user never sees a "not supported" placeholder in chat.
  if (embedded === "chat") {
    return <InsightCardWidget envelope={envelope} onAction={onAction} testId={testId} />;
  }

  const common = { envelope, onAction, embedded, testId };
  switch (envelope.kind) {
    case "fund_card":       return <FundCardWidget       {...common} />;
    case "market_brief":    return <MarketBriefWidget    {...common} />;
    case "compare_table":   return <CompareTableWidget   {...common} />;
    case "sip_plan":        return <SipPlanWidget        {...common} />;
    case "rebalance_plan":  return <RebalancePlanWidget  {...common} />;
    case "tax_harvest":     return <TaxHarvestWidget     {...common} />;
    case "stress_test":     return <StressTestWidget     {...common} />;
    case "sector_rotation": return <SectorRotationWidget {...common} />;
    case "overlap_reveal":  return <OverlapRevealWidget  {...common} />;
    case "insight_card":    return <InsightCardWidget    {...common} />;
    // NIDP-emitted kinds without dedicated frontend handlers — these
    // should have been upgraded to insight_card by the backend adapter,
    // but we map to a "best-fit" widget as a safety net for non-chat
    // surfaces.
    case "fund_comparison":     return <CompareTableWidget   {...common} />;
    case "portfolio_overview":  return <MarketBriefWidget    {...common} />;
    case "goal_tracker":        return <SipPlanWidget        {...common} />;
    case "stock_screener":      return <CompareTableWidget   {...common} />;
    default:
      return (
        <div data-testid={`widget-unknown-${envelope.kind}`} className="text-[11px] text-slate-500 p-2 border border-dashed border-slate-300 rounded">
          Widget kind <code>{envelope.kind}</code> not yet supported in this build.
        </div>
      );
  }
};

export default WidgetRenderer;
