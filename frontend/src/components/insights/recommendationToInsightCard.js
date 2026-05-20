/**
 * recommendationToInsightCard — map a single Recommendations Center
 * insight object onto the unified `InsightCardData` shape so the
 * Insights page can render through `<InsightCardWidget>` instead of
 * its bespoke per-insight JSX.
 *
 * Insight shape (from backend /api/insights/recommendations):
 *   {
 *     insight_id, title|headline, description|detail, action,
 *     severity ("critical"|"important"|"optimization"|"positive"),
 *     theme ("duplication"|"overlap"|"amc_concentration"|...),
 *     theme_label, theme_order,
 *     type ("alert"|"opportunity"|"warning"|"info"|"success"),
 *     impact ("high"|"medium"|"low"),
 *     benefit: { summary, ... },
 *     completed: bool,
 *   }
 *
 * Output: an envelope dict the WidgetRenderer can dispatch on
 * (kind="insight_card", data=InsightCardData-shape). No backend
 * round-trip — pure client-side transform so existing pages don't
 * need any API changes.
 */

const SEVERITY_MAP = {
  critical:      "critical",
  important:     "high",
  optimization:  "info",
  positive:      "healthy",
};

const THEME_LABEL = {
  duplication: "Duplicate Funds",
  overlap: "Fund Overlap",
  amc_concentration: "AMC Concentration",
  category_concentration: "Category Concentration",
  sector_risk: "Sector Risk",
  drift: "Allocation Drift",
  allocation_gap: "Allocation Gap",
  cost: "Cost Leakage",
  other: "Recommendation",
};

const deriveSeverity = (insight) => {
  // Mirrors the legacy `deriveSeverity` in RecommendationsCenter.jsx
  // so the unified card paints with the same severity intent.
  if (insight.severity && SEVERITY_MAP[insight.severity]) {
    return SEVERITY_MAP[insight.severity];
  }
  const itype = (insight.type || "").toLowerCase();
  const impact = (insight.impact || "").toLowerCase();
  if (itype === "success") return "healthy";
  if (itype === "alert" || (itype === "warning" && impact === "high")) return "critical";
  if (itype === "opportunity" && impact === "high") return "high";
  if (itype === "opportunity" || impact === "low" || itype === "info") return "info";
  return "high";
};

const themeLabel = (insight) =>
  insight.theme_label || THEME_LABEL[insight.theme] || "Recommendation";

const formatRs = (v) => {
  const n = Number(v) || 0;
  if (Math.abs(n) >= 1_00_000) return `₹${(n / 1_00_000).toFixed(2)}L`;
  if (Math.abs(n) >= 1_000)    return `₹${(n / 1_000).toFixed(1)}K`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

/**
 * Convert one insight into the {kind, title, freshness, agent, data}
 * envelope the WidgetRenderer expects. The `data` is InsightCardData-
 * shaped: hero/kpis/findings/recommendation/actions/education.
 *
 * `actionsOverride` lets the caller swap in handlers (mark-as-done,
 * ask-in-chat) so the card's chips wire to the existing functions.
 */
export function recommendationToInsightEnvelope(insight, opts = {}) {
  const severity = deriveSeverity(insight);
  const title    = insight.title || insight.headline || "Recommendation";
  const detail   = insight.description || insight.detail || "";
  const benefit  = insight.benefit || {};
  const completed = !!insight.completed;

  const hero = {
    severity,
    eyebrow: themeLabel(insight),
    headline: title,
    primary_value: null,
    primary_label: null,
    subtitle: completed ? "Marked done" : detail.slice(0, 140) || null,
    trend: completed ? "flat" : null,
  };

  // KPIs: surface the benefit summary + any numeric impact.
  const kpis = [];
  if (benefit.summary) {
    kpis.push({
      label: "Benefit",
      value: benefit.summary.length > 28
        ? benefit.summary.slice(0, 26) + "…"
        : benefit.summary,
      tone: "healthy",
    });
  }
  if (benefit.savings_rs_year) {
    kpis.push({
      label: "Save / year",
      value: formatRs(benefit.savings_rs_year),
      tone: "healthy",
    });
  }
  if (benefit.optimizable_rs) {
    kpis.push({
      label: "Optimizable",
      value: formatRs(benefit.optimizable_rs),
      tone: "info",
    });
  }
  if (insight.impact) {
    kpis.push({
      label: "Impact",
      value: String(insight.impact).toUpperCase(),
      tone: severity,
    });
  }

  // Findings: split the description into discrete points if backend
  // provided an array, else keep it tight.
  const findings = [];
  if (Array.isArray(insight.findings)) {
    insight.findings.slice(0, 4).forEach((f, i) => {
      findings.push({
        priority: severity === "critical" || severity === "high" ? "high" : "medium",
        title: typeof f === "string" ? f : (f.title || `Finding ${i + 1}`),
        detail: typeof f === "string" ? undefined : f.detail,
      });
    });
  } else if (detail && detail.length > 160) {
    // Long descriptions: split on sentence breaks for the findings list.
    const sentences = detail.split(/(?<=\.)\s+/).filter(s => s.trim().length > 0);
    sentences.slice(0, 3).forEach(s => {
      findings.push({
        priority: severity === "critical" || severity === "high" ? "high" : "medium",
        title: s.length > 100 ? s.slice(0, 98) + "…" : s,
      });
    });
  }

  const recommendation = insight.action
    ? { summary: insight.action }
    : (detail && detail.length <= 160 ? { summary: detail } : null);

  // Actions wire back to the caller's onAsk / onMarkDone callbacks via
  // the `action_id` field. RecommendationsCenter's WidgetRenderer
  // onAction handler reads these and routes appropriately.
  const actions = [];
  if (!completed) {
    actions.push({
      label: "Discuss in Chat",
      action_id: "rec_ask",
      style: "primary",
    });
    if (insight.insight_id) {
      actions.push({
        label: "Mark as Done",
        action_id: "rec_mark_done",
        style: "secondary",
      });
    }
  } else if (insight.insight_id) {
    actions.push({
      label: "Reopen",
      action_id: "rec_unmark",
      style: "secondary",
    });
  }

  const data = {
    hero,
    kpis,
    findings,
    recommendation,
    actions,
  };

  return {
    kind: "insight_card",
    title: themeLabel(insight),
    freshness: {
      state: "cached",
      last_updated: insight.generated_at || null,
      source: ["portfolio_intelligence"],
    },
    agent: {
      id: "recommendation",
      label: "Recommendation Engine",
      confidence: insight.confidence_pct != null ? Math.round(insight.confidence_pct) : 85,
    },
    data,
    suggestions: [],
    // attach the original insight so the onAction handler can look up insight_id
    _insight: insight,
  };
}
