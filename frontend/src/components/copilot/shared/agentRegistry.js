/**
 * agentRegistry.js — single source of truth for backend agent_id → display
 * metadata used in the copilot UI (ribbon, picker, route event).
 *
 * Keep this in sync with backend `nidp/services/copilot_agent/schemas.py`
 * (AgentName enum). When a new agent is added on the backend, add an entry
 * here too, otherwise the ribbon falls back to a title-cased id.
 */

export const AGENT_REGISTRY = {
  market_analyst: { label: "Market Analyst", icon: "compass" },
  stock_analyst: { label: "Stock Analyst", icon: "bar-chart-3" },
  mf_analyst: { label: "MF Analyst", icon: "search" },
  portfolio_analyst: { label: "Portfolio Analyst", icon: "line-chart" },
  risk_analyst: { label: "Risk Analyst", icon: "shield" },
  goal_planner: { label: "Goal Planner", icon: "file-text" },
  recommendation: { label: "Recommendation Engine", icon: "receipt" },
};

/**
 * Resolve any agent reference (id string, AgentName enum value, or
 * partial agent object) to a consistent {id, label, icon, confidence?}
 * shape that the ribbon can render.
 */
export function resolveAgent(input) {
  if (!input) return null;
  const id = typeof input === "string" ? input : input.id || input.agent;
  if (!id) return null;
  const known = AGENT_REGISTRY[id] || {};
  const fallbackLabel = id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return {
    id,
    label: (typeof input === "object" && input.label) || known.label || fallbackLabel,
    icon: (typeof input === "object" && input.icon) || known.icon || "compass",
    ...(typeof input === "object" && input.confidence != null
      ? { confidence: input.confidence }
      : {}),
    ...(typeof input === "object" && input.version ? { version: input.version } : {}),
  };
}
