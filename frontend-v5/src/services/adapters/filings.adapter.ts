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
  docLabel: z.string().nullable().optional(),
  model: z.string().nullable().optional(),
  generatedAt: z.string().nullable().optional(),
  grounded: z.boolean().optional(),
  disclaimer: z.string().optional(),
  reason: z.string().optional(),
  sourceUrl: z.string().nullable().optional(),
  /** Only tabs that actually carry a section — never an empty tab. */
  tabs: z.array(z.object({ key: z.string(), label: z.string() })).default([]),
  /** Grouped under `tab`; `cite` is null when the generator could not point at
   *  a page (an unverifiable page range is dropped server-side, not shown). */
  sections: z.array(
    z.object({
      tab: z.string(),
      h: z.string(),
      items: z.array(z.string()).default([]),
      cite: z.string().nullable().optional(),
      cite_url: z.string().nullable().optional(),
    }),
  ).default([]),
}).passthrough();
export type Insight = z.infer<typeof InsightC>;
export type InsightSection = Insight["sections"][number];

/** Filing-alert preferences (Alerts screen). */
export const AlertsC = z.object({
  ok: z.boolean().optional(),
  types: z.record(z.boolean()).default({}),
  channels: z.record(z.boolean()).default({}),
  catalog: z.array(z.object({ key: z.string(), label: z.string() })).default([]),
  delivery: z.object({
    active: z.boolean().default(false),
    note: z.string().optional(),
  }).optional(),
  updatedAt: z.string().nullable().optional(),
}).passthrough();
export type Alerts = z.infer<typeof AlertsC>;

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

  /** The signed-in user's filing-alert preferences. Never 404s — the backend
   *  returns documented defaults for a user who has not saved any. */
  async getAlerts(): Promise<Alerts> {
    const res = await http({ path: "/api/filings/alerts" });
    return AlertsC.parse(res.data);
  },

  /** Replace the alert preferences; returns the stored state. Errors propagate
   *  so the screen can revert its optimistic toggle rather than lie about a
   *  save that did not happen. */
  async putAlerts(body: { types?: Record<string, boolean>; channels?: Record<string, boolean> }): Promise<Alerts> {
    const res = await http({ path: "/api/filings/alerts", method: "PUT", body });
    return AlertsC.parse(res.data);
  },
};
