import React, { useState } from "react";
import { BarChart3, Search, LineChart, Receipt, Shield, FileText, Compass, Sparkles } from "lucide-react";

const ICON_BY_NAME = {
  "compass": Compass,
  "bar-chart-3": BarChart3,
  "search": Search,
  "line-chart": LineChart,
  "receipt": Receipt,
  "shield": Shield,
  "file-text": FileText,
};

/**
 * AgentRibbon — inline strip prefixing AI output.
 * Doc 02 §2.1, Doc 06 §6.2.
 *
 * Props:
 *   agent: { id, label, version?, confidence? } or null
 *   onViewReasoning: callback
 *   compact: boolean
 */
const AgentRibbon = ({ agent, onViewReasoning, compact = false, testId }) => {
  if (!agent) return null;
  const Icon = ICON_BY_NAME[agent.icon] || ICON_BY_NAME["compass"] || Sparkles;
  const conf = agent.confidence;

  return (
    <div
      data-testid={testId || `agent-ribbon-${agent.id}`}
      className={`inline-flex items-center gap-2 ${compact ? "text-[11px]" : "text-xs"} text-slate-600 dark:text-slate-300`}
    >
      <span
        className="inline-flex items-center justify-center w-5 h-5 rounded-md shadow-sm"
        style={{ background: "var(--cp-intelligence-glow)" }}
      >
        <Icon className="w-3 h-3 text-white" strokeWidth={2} />
      </span>
      <span className="font-medium">{agent.label}</span>
      {agent.version && (
        <span className="text-slate-400">· {agent.version}</span>
      )}
      {conf != null && (
        <span className="text-slate-400 cp-num">· {Math.round(conf)}% confidence</span>
      )}
      {onViewReasoning && (
        <button
          type="button"
          data-testid={`agent-ribbon-${agent.id}-reasoning`}
          onClick={onViewReasoning}
          className="ml-1 text-[11px] underline-offset-2 hover:underline text-[color:var(--cp-accent-brand)]"
        >
          View reasoning
        </button>
      )}
    </div>
  );
};

export default AgentRibbon;
