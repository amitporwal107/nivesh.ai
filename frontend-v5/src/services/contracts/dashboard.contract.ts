/**
 * Dashboards v4 contracts — from the Postman collection's "unified envelope".
 *
 * The OpenAPI doesn't yet expose these paths, but the response shape is the
 * same across all six dashboards. Zod schemas validate at runtime — anything
 * out of spec surfaces as ApiError("contract_drift") in the UI.
 *
 * Endpoints:
 *   GET /api/dashboards/concentration?lens=sector|amc|company|group
 *   GET /api/dashboards/diversification?lens=overlap|stocks|category|asset_mix
 *   GET /api/dashboards/risk
 *   GET /api/dashboards/performance?period=1y|3y|5y
 *   GET /api/dashboards/goals
 *   GET /api/dashboards/tax
 */
import { z } from "zod";

export const StatTileC = z.object({
  label: z.string(),
  value: z.union([z.number(), z.string()]).optional(),
  unit: z.string().optional(),
  sub: z.string().nullish(),
  tone: z.enum(["good", "warm", "neg", "info", "default"]).or(z.string()).optional(),
}).passthrough();

export const RecommendationLiteC = z.object({
  id: z.string(),
  source_domain: z.string().optional(),
  verb: z.string().optional(),
  title: z.string().optional(),
  priority_label: z.string().optional(),
  impact: z.string().optional(),
  effort: z.string().optional(),
  trade_off: z.string().optional(),
  expected_impact: z.string().optional(),
  exclusive: z.boolean().optional(),
}).passthrough();

export const DashboardEnvelopeC = z.object({
  type: z.string(),
  badge: z.union([
    z.string(),
    z.object({ label: z.string(), tone: z.string() }).passthrough(),
  ]).optional(),
  insight: z.union([
    z.string(),
    z.object({ headline: z.string(), subtext: z.string().optional(), hero: z.unknown().optional() }).passthrough(),
  ]).optional(),
  stat_tiles: z.array(StatTileC).default([]),
  breakdown: z.unknown(),                              // shape varies per lens
  recommendations: z.array(RecommendationLiteC).default([]),
  projection: z.unknown().optional(),
  etag: z.string().optional(),
}).passthrough();
export type DashboardEnvelopeC = z.infer<typeof DashboardEnvelopeC>;
