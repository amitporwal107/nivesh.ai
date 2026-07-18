/**
 * Filings adapter — Design B "Filings Intelligence" (/research) read path.
 *
 * Wraps the endpoints shipped in backend/routes/filings.py (real data only):
 *   GET /api/filings/feed            → { ok, total, facets, rows[] }
 *   GET /api/filings/signals         → { ok, signals[] }
 *   GET /api/filings/{id}/insights   → { ok, one, period, metric, ... } | 404 no_insight_yet
 *
 * `one` / `period` / `metric` / `hasInsights` are null/false for any filing the
 * stage-7 generator has not processed yet — the UI renders the filing row anyway
 * and shows the insight only when it exists (honest degradation, spec §4.2).
 */
import { http } from "@/services/api/http";
import { z } from "zod";

export const FilingRowC = z.object({
  id: z.string(),
  ticker: z.string().nullable().optional(),
  code: z.string().nullable().optional(),
  name: z.string().nullable().optional(),
  date: z.string().nullable().optional(),
  category: z.string().nullable().optional(),
  impact: z.string().nullable().optional(),
  sentiment: z.string().nullable().optional(),
  docLabel: z.string().nullable().optional(),
  url: z.string().nullable().optional(),
  one: z.string().nullable().optional(),
  period: z.string().nullable().optional(),
  metric: z.string().nullable().optional(),
  hasInsights: z.boolean().optional(),
}).passthrough();
export type FilingRow = z.infer<typeof FilingRowC>;

export const FeedRespC = z.object({
  ok: z.boolean().optional(),
  total: z.number().optional(),
  facets: z.record(z.number()).optional(),
  rows: z.array(FilingRowC).default([]),
});
export type FeedResp = z.infer<typeof FeedRespC>;

export const SignalC = z.object({
  rank: z.number().optional(),
  ticker: z.string().nullable().optional(),
  type: z.string().nullable().optional(),
  one: z.string().nullable().optional(),
  metric: z.string().nullable().optional(),
  date: z.string().nullable().optional(),
  sentiment: z.string().nullable().optional(),
}).passthrough();
export type Signal = z.infer<typeof SignalC>;

export const InsightC = z.object({
  ok: z.boolean().optional(),
  id: z.string().optional(),
  one: z.string().nullable().optional(),
  period: z.string().nullable().optional(),
  metric: z.string().nullable().optional(),
  sentiment: z.string().nullable().optional(),
  confidence: z.number().nullable().optional(),
  docType: z.string().nullable().optional(),
  model: z.string().nullable().optional(),
  generatedAt: z.string().nullable().optional(),
  grounded: z.boolean().optional(),
  disclaimer: z.string().optional(),
  reason: z.string().optional(),
}).passthrough();
export type Insight = z.infer<typeof InsightC>;

export interface FeedParams {
  days?: number;
  category?: string;
  impact?: string;
  sentiment?: string;
  q?: string;
  limit?: number;
  offset?: number;
  sort?: "material" | "latest";
}

export const filingsService = {
  async getFeed(p: FeedParams = {}): Promise<FeedResp> {
    const res = await http({ path: "/api/filings/feed", query: { ...p } });
    return FeedRespC.parse(res.data);
  },

  async getSignals(days = 1): Promise<Signal[]> {
    const res = await http({ path: "/api/filings/signals", query: { days } });
    const parsed = z
      .object({ ok: z.boolean().optional(), signals: z.array(SignalC).default([]) })
      .parse(res.data);
    return parsed.signals;
  },

  /** Returns the generated insight, or null when none exists yet (404 no_insight_yet). */
  async getInsight(id: string): Promise<Insight | null> {
    try {
      const res = await http({ path: `/api/filings/${encodeURIComponent(id)}/insights` });
      const parsed = InsightC.parse(res.data);
      return parsed.ok === false ? null : parsed;
    } catch {
      // 404 (no insight generated yet) or a transient error — degrade to "no insight".
      return null;
    }
  },
};
