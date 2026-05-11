import React from "react";
import FundCardWidget from "./FundCardWidget";
import MarketBriefWidget from "./MarketBriefWidget";
import CompareTableWidget from "./CompareTableWidget";
import SipPlanWidget from "./SipPlanWidget";
import SkeletonCard from "../shared/SkeletonCard";

/**
 * WidgetRenderer — dispatches a server-produced envelope to the right
 * widget component. Returns null on unknown kinds so unsupported
 * envelopes don't break the chat bubble.
 *
 * Doc 06 §6.8 — every widget is renderable in Chat OR outside; this
 * component is the single entry point both surfaces use.
 */
const WidgetRenderer = ({ envelope, onAction, embedded = "chat", testId }) => {
  if (!envelope) return null;
  if (envelope.partial) {
    return <SkeletonCard lines={5} testId={testId ? `${testId}-skeleton` : undefined} />;
  }
  const common = { envelope, onAction, embedded, testId };
  switch (envelope.kind) {
    case "fund_card":      return <FundCardWidget    {...common} />;
    case "market_brief":   return <MarketBriefWidget {...common} />;
    case "compare_table":  return <CompareTableWidget {...common} />;
    case "sip_plan":       return <SipPlanWidget     {...common} />;
    default:
      // Unknown kind — render a small "preview" so it isn't silently dropped.
      return (
        <div data-testid={`widget-unknown-${envelope.kind}`} className="text-[11px] text-slate-500 p-2 border border-dashed border-slate-300 rounded">
          Widget kind <code>{envelope.kind}</code> not yet supported in this build.
        </div>
      );
  }
};

export default WidgetRenderer;
