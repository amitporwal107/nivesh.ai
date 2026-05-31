import type { Recommendation } from "@/types/recommendation";

export const mockRecommendations: Recommendation[] = [
  {
    id: "rec-consolidate-largecap",
    action: "CONSOLIDATE",
    title: "Consolidate 3 large-cap funds → keep ICICI Pru Bluechip",
    reason:
      "You hold three large-cap funds with 71% overlap. You're paying 3× the expense ratio for identical exposure. Keep the top-ranked one and exit the rest.",
    suggestedAction: "Exit Axis Bluechip · ₹1.2L",
    severity: "mismatch",
    execution: "redirect",
    magnitude: 120_000,
    expectedEffect: { risk_band_delta: "neutral", score_delta_pct: 4.5, funding_probability_delta: 0 },
  },
  {
    id: "rec-add-debt",
    action: "ADD",
    title: "Add debt · your portfolio is 12% below target",
    reason:
      "Debt allocation is 18% — your Moderate profile targets 40–50%. Point new SIPs to a short-duration debt fund. No realised tax.",
    suggestedAction: "Redirect next SIP to HDFC Corporate Bond",
    severity: "mismatch",
    execution: "redirect",
    magnitude: 46_000,
    expectedEffect: { risk_band_delta: "lower", score_delta_pct: 6.0, funding_probability_delta: 8 },
  },
  {
    id: "rec-trim-smallcap",
    action: "TRIM",
    title: "Trim small-cap by 8% · above your Moderate band",
    reason:
      "Small-cap is 18% of equity — your Moderate cap is 10%. More downside than your plan allows, and this segment returned 0% last year.",
    suggestedAction: "Trim Nippon Small Cap · ₹74,000",
    severity: "severe",
    execution: "stagger",
    magnitude: 74_000,
    taxImpact: { tax_liability: 8200, ltcg: 8200, holding_period_days: 420 },
    requiresConfirmation: true,
    expectedEffect: { risk_band_delta: "lower", score_delta_pct: 8.5, funding_probability_delta: 5 },
  },
  {
    id: "rec-hold-ppfas",
    action: "HOLD",
    title: "Hold Parag Parikh Flexi Cap · top quartile, low overlap",
    reason:
      "Outperformed category by 3.4% over 3 years. 30% international exposure — a useful diversifier. No action needed.",
    suggestedAction: "No change",
    severity: "aligned",
  },
  {
    id: "rec-diversify-gold",
    action: "DIVERSIFY",
    title: "Add a gold ETF · ₹70,000 to reach 8% allocation",
    reason:
      "Gold is currently 2% of your portfolio. Your Conservative profile targets 5–10%. Redirect new money; no realised tax.",
    suggestedAction: "Redirect ₹70,000 to Nippon Gold ETF",
    severity: "minor",
    execution: "redirect",
    magnitude: 70_000,
    expectedEffect: { risk_band_delta: "lower", score_delta_pct: 2.5, funding_probability_delta: 3 },
  },
];
