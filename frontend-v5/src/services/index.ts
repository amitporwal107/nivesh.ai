/**
 * Services factory — single switch between real and mock impls.
 *
 * Hooks import from THIS file only. Adapters and mocks both implement the
 * same interface; the rest of the app is oblivious to the choice.
 *
 *   VITE_USE_MOCK_API=true  → mocks (local dev, Storybook, tests)
 *   VITE_USE_MOCK_API=false → real backend (staging / prod)
 */
import { apiConfig } from "./api/config";
import { realAuthAdapter } from "./adapters/auth.adapter";
import { realPortfolioAdapter } from "./adapters/portfolio.adapter";
import { realPlansAdapter } from "./adapters/plans.adapter";
import { realGoalsAdapter } from "./adapters/goals.adapter";
import { realAnalyticsAdapter } from "./adapters/analytics.adapter";
import { realInsightsAdapter } from "./adapters/insights.adapter";
import { realDashboardsAdapter } from "./adapters/dashboards.adapter";
import { realAdvisorAdapter } from "./adapters/advisor.adapter";
import { realMfdAdapter } from "./adapters/mfd.adapter";
import { realChatAdapter } from "./adapters/chat.adapter";
import { realCasUploadAdapter } from "./adapters/cas-upload.adapter";
import { realScenariosAdapter } from "./adapters/scenarios.adapter";
import { realIntelligenceAdapter } from "./adapters/intelligence.adapter";
import { realPositionalAdapter } from "./adapters/positional.adapter";
import { mockAuthAdapter } from "./mock/auth.mock";
import { mockPortfolioAdapter } from "./mock/portfolio.mock";
import { mockPlansAdapter } from "./mock/plans.mock";
import { mockGoalsAdapter } from "./mock/goals.mock";
import { mockAnalyticsAdapter } from "./mock/analytics.mock";
import { mockInsightsAdapter } from "./mock/insights.mock";
import { mockDashboardsAdapter } from "./mock/dashboards.mock";
import {
  mockAdvisorAdapter,
  mockMfdAdapter,
  mockChatAdapter,
  mockCasUploadAdapter,
} from "./mock/more.mock";
import {
  mockScenariosAdapter,
  mockIntelligenceAdapter,
} from "./mock/scenarios-intelligence.mock";

export const authService       = apiConfig.useMock ? mockAuthAdapter       : realAuthAdapter;
export const portfolioService  = apiConfig.useMock ? mockPortfolioAdapter  : realPortfolioAdapter;
export const plansService      = apiConfig.useMock ? mockPlansAdapter      : realPlansAdapter;
export const goalsService      = apiConfig.useMock ? mockGoalsAdapter      : realGoalsAdapter;
export const analyticsService  = apiConfig.useMock ? mockAnalyticsAdapter  : realAnalyticsAdapter;
export const insightsService   = apiConfig.useMock ? mockInsightsAdapter   : realInsightsAdapter;
export const dashboardsService = apiConfig.useMock ? mockDashboardsAdapter : realDashboardsAdapter;
export const advisorService    = apiConfig.useMock ? mockAdvisorAdapter    : realAdvisorAdapter;
export const mfdService        = apiConfig.useMock ? mockMfdAdapter        : realMfdAdapter;
export const chatService       = apiConfig.useMock ? mockChatAdapter       : realChatAdapter;
export const casUploadService  = apiConfig.useMock ? mockCasUploadAdapter  : realCasUploadAdapter;
export const scenariosService  = apiConfig.useMock ? mockScenariosAdapter  : realScenariosAdapter;
export const intelligenceService = apiConfig.useMock ? mockIntelligenceAdapter : realIntelligenceAdapter;
// Pro Trader has no mock — always uses real backend
export const positionalService = realPositionalAdapter;

// Re-export the adapter interfaces so consumers can import types.
export type { AuthAdapter }        from "./adapters/auth.adapter";
export type { PortfolioAdapter }   from "./adapters/portfolio.adapter";
export type { PlansAdapter }       from "./adapters/plans.adapter";
export type { GoalsAdapter }       from "./adapters/goals.adapter";
export type { AnalyticsAdapter }   from "./adapters/analytics.adapter";
export type { InsightsAdapter }    from "./adapters/insights.adapter";
export type { DashboardsAdapter, DashboardDomain } from "./adapters/dashboards.adapter";
export type { AdvisorAdapter }     from "./adapters/advisor.adapter";
export type { MfdAdapter }         from "./adapters/mfd.adapter";
export type { ChatAdapter }        from "./adapters/chat.adapter";
export type { CasUploadAdapter }   from "./adapters/cas-upload.adapter";
export type { ScenariosAdapter, ScenarioSimulateBody }    from "./adapters/scenarios.adapter";
export type { IntelligenceAdapter } from "./adapters/intelligence.adapter";
export type { PositionalAdapter, BasketParams } from "./adapters/positional.adapter";
