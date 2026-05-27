/**
 * Mock analytics adapter — all four methods via existing mock fixtures.
 */
import type { AnalyticsAdapter } from "../adapters/analytics.adapter";
import { mockConcentration } from "@/mock-data/concentration";
import { mockCorrelation, mockOverlap } from "@/mock-data/diversification";
import { mockRisk } from "@/mock-data/risk";

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export const mockAnalyticsAdapter: AnalyticsAdapter = {
  async concentration() { await delay(260); return structuredClone(mockConcentration); },
  async correlation()   { await delay(280); return structuredClone(mockCorrelation); },
  async overlap()       { await delay(260); return structuredClone(mockOverlap); },
  async risk()          { await delay(300); return structuredClone(mockRisk); },
};
