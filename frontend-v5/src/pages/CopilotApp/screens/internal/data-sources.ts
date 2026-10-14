/**
 * Tool builder — the data source pool.
 *
 * One list of every data source a Copilot tool can draw on. A tool definition
 * picks its "Data it needs" rows from here (screens/internal/tool-templates.ts
 * does so for every tool that exists today).
 *
 * Every entry was checked against this codebase before it was listed: each
 * endpoint is a route in backend/routes/*.py, and each is read by a screen, a
 * hook, an adapter or the chat pipeline (the file is named beside each entry).
 * Notes that start with "Staging," are what the data held on that date; they
 * are a dated reading, not something this page measures.
 *
 * `status` is a fact about the data connection and nothing else:
 *   connected  an app route serves it and a tool reads it today
 *   partial    it is served, but part of the data or of the flow is missing
 *   planned    no app route serves it yet
 */
import type { Tone } from "../../components/ui";

export type SourceStatus = "connected" | "partial" | "planned";

export interface DataSource {
  id: string;
  name: string;
  /** Where the data comes from. */
  provider: string;
  /** One plain sentence: what the data is. */
  what: string;
  /** The app routes that serve it. Empty when no app route does. */
  endpoints: readonly string[];
  /** How fresh the data is, in plain words. Also the default for a new data row. */
  freshness: string;
  status: SourceStatus;
  note?: string;
}

const POOL = [
  // ── the user's portfolio ───────────────────────────────────────────────
  {
    // backend/routes/portfolio.py, onboarding_gmail.py · hooks/use-portfolio.ts, lib/use-cas-state.ts
    id: "cas-holdings",
    name: "Holdings from the CAS statement",
    provider: "The user's CAS statement, uploaded or found in Gmail",
    what: "Every fund and stock the user holds, with units, cost, current value and gain.",
    endpoints: ["GET /api/portfolio/holdings-enriched", "GET /api/onboarding/state", "GET /api/portfolio/holdings/export"],
    freshness: "When a statement is imported",
    status: "connected",
    note: "A statement arrives by CAS upload or by Gmail sync, which imports the latest one. /api/onboarding/state says which statement is on file; the export route gives the holdings as a CSV or Excel file.",
  },
  {
    // backend/routes/onboarding_gmail.py, gmail.py · hooks/use-cas-upload.ts, hooks/use-gmail.ts, screens/account/queries.ts
    id: "statement-imports",
    name: "Statement imports (CAS upload and Gmail)",
    provider: "The user's own upload, or their Gmail inbox once connected",
    what: "The import of a CAS statement, the state of the Gmail connection and the list of statements Gmail sync has brought in.",
    endpoints: ["POST /api/onboarding/upload-cas", "GET /api/gmail/status", "GET /api/gmail/history"],
    freshness: "When the user uploads a statement or runs a Gmail sync",
    status: "connected",
  },
  {
    // backend/routes/cas_snapshots.py, cas_transactions.py, portfolio.py · screens/portfolio/LedgerSections.tsx, LedgerHoldings.tsx
    id: "statement-records",
    name: "Statements, transactions and SIPs on record",
    provider: "The user's imported statements",
    what: "The statements a user has imported, the transactions in them, the SIPs detected from those transactions, and the stored record of each holding.",
    endpoints: [
      "GET /api/portfolio/cas-snapshots",
      "GET /api/portfolio/transactions",
      "GET /api/portfolio/sips",
      "GET /api/portfolio/holdings",
      "PUT /api/portfolio/holdings/{holding_id}",
    ],
    freshness: "When a statement is imported, or the user corrects a holding",
    status: "connected",
    note: "A correction is saved to the holdings on record; a newer statement replaces the holdings, corrections included, and no log of corrections is kept.",
  },
  {
    // backend/routes/portfolio_exposure.py, portfolio_composition.py · hooks/use-analytics.ts, hooks/use-composition.ts
    id: "exposure",
    name: "Look-through exposure, overlap and remediation",
    provider: "Nivesh portfolio engine, from the holdings and each fund's disclosed portfolio",
    what: "What the portfolio is really exposed to by sector, company, fund house, group and asset class, how much the funds overlap, and what to fix first.",
    endpoints: [
      "GET /api/portfolio/exposure/concentration",
      "GET /api/portfolio/exposure/fund-overlap/matrix",
      "GET /api/portfolio/exposure/remediation",
      "GET /api/portfolio/composition",
    ],
    freshness: "Worked out from the current holdings on each request",
    status: "connected",
    note: "Overlap covers the funds whose stock holdings are on file; the response says what share of the fund money that is.",
  },
  {
    // backend/routes/dashboards.py, analytics.py · hooks/use-dashboards.ts, screens/portfolio/performance-data.ts
    id: "performance",
    name: "Performance and value history",
    provider: "Nivesh portfolio engine, from the values printed on the statement",
    what: "Returns for a chosen period, the month-by-month portfolio value, each fund against its benchmark, and the gain or loss on each holding.",
    endpoints: [
      "GET /api/dashboards/performance",
      "GET /api/portfolio/value-history",
      "GET /api/portfolio/fund-performance",
      "GET /api/portfolio/analytics",
    ],
    freshness: "When a statement is imported; fund ratings are kept for two hours",
    status: "connected",
    note: "Figures are based on statement values. XIRR and alpha can read as still being calculated.",
  },
  {
    // backend/routes/portfolio_snapshots.py, services/portfolio_snapshot.py · services/adapters/portfolio.adapter.ts, screens/portfolio/data.ts
    id: "portfolio-snapshots",
    name: "Portfolio snapshots",
    provider: "Nivesh snapshot engine",
    what: "A dated copy of the portfolio's value, mix and health, used for month-end value and for what changed between two dates.",
    endpoints: ["GET /api/portfolio/trend", "GET /api/portfolio/compare"],
    freshness: "One snapshot a day, and one when a statement is imported",
    status: "connected",
  },
  {
    // backend/routes/insights.py · hooks/use-insights.ts
    id: "health-signals",
    name: "Health score and signals",
    provider: "Nivesh insights engine",
    what: "The portfolio's health score out of 100 with its parts, and the list of things worth the user's attention.",
    endpoints: ["GET /api/insights/analysis", "GET /api/insights"],
    freshness: "As last analysed; the stored analysis is read on each request",
    status: "connected",
  },
  {
    // backend/routes/plans.py, analytics.py · hooks/use-active-plan.ts, hooks/use-recommendations.ts, screens/portfolio/data.ts
    id: "plan-engine",
    name: "Plan engine",
    provider: "Nivesh plan engine, from the holdings, goals and risk profile",
    what: "The active action plan and its steps, the record of past decisions, what the plan would change, and the top recommendations for each asset class.",
    endpoints: [
      "GET /api/plans/active",
      "GET /api/plans/history",
      "GET /api/plans/active/health-projection",
      "POST /api/plans/refresh",
      "PATCH /api/plans/{plan_id}/actions/{action_id}",
      "GET /api/portfolio/recommendations/v5",
    ],
    freshness: "Built when the user asks for a plan or rebuilds it; a step changes when the user marks it",
    status: "connected",
  },
  {
    // backend/routes/goals.py, user.py, dashboards.py · hooks/use-goals.ts, hooks/use-risk-profile.ts
    id: "goals-risk-profile",
    name: "Goals and risk profile",
    provider: "Entered by the user",
    what: "The user's goals with their targets and dates, and the risk profile from the assessment they answered.",
    endpoints: [
      "GET /api/goals",
      "POST /api/goals",
      "GET /api/user/risk-profile",
      "POST /api/user/risk-profile",
      "GET /api/dashboards/goals",
      "POST /api/goals/{goal_id}/what-if",
    ],
    freshness: "As the user last saved them",
    status: "connected",
  },
  {
    // backend/routes/dashboards.py (reads the risk engine's nightly results) · services/adapters/analytics.adapter.ts
    id: "risk-metrics",
    name: "Portfolio risk metrics",
    provider: "Nivesh portfolio risk engine on the data platform",
    what: "Value at risk, volatility, maximum drawdown and beta for the user's portfolio, with stress scenarios.",
    endpoints: ["GET /api/dashboards/risk"],
    freshness: "From the risk engine's nightly run",
    status: "connected",
    note: "The response says when there is no run for the user, or none today, and the page shows that as a warning.",
  },
  {
    // backend/routes/dashboards.py, portfolio_tax.py · hooks/use-dashboards.ts, screens/portfolio/data.ts
    id: "tax",
    name: "Capital gains and tax",
    provider: "Nivesh tax engine, from the holdings and the statement's transactions",
    what: "Realised short-term and long-term gains for the financial year, the tax they lead to, and loss-making lots that could be sold to offset gains.",
    endpoints: ["GET /api/dashboards/tax", "GET /api/portfolio/capital-gains-statement"],
    freshness: "When a statement is imported",
    status: "connected",
  },
  {
    // backend/routes/analytics.py (proxies the data platform's category ranking) · screens/portfolio/performance-data.ts
    id: "mf-rankings",
    name: "Mutual fund category rankings",
    provider: "Nivesh data platform (mutual fund analytics)",
    what: "The top-ranked funds in one SEBI fund category.",
    endpoints: ["GET /api/mf/category-top"],
    freshness: "Re-ranked on weekday evenings",
    status: "connected",
  },

  // ── markets and research ───────────────────────────────────────────────
  {
    // backend/routes/markets.py · hooks/use-markets.ts, services/adapters/markets.adapter.ts
    id: "market-pulse",
    name: "Market pulse",
    provider: "NSE and BSE through the Nivesh data platform; global quotes from Yahoo Finance",
    what: "Index levels and breadth, top movers, sector cards, the earnings season, FII and DII flows, corporate actions, news articles and the daily brief.",
    endpoints: [
      "GET /api/markets/home",
      "GET /api/markets/movers",
      "GET /api/markets/explore",
      "GET /api/markets/sectors",
      "GET /api/markets/sectors/{slug}",
      "GET /api/markets/earnings",
      "GET /api/markets/earnings/companies",
      "GET /api/markets/fii-dii",
      "GET /api/markets/institutional-positioning",
      "GET /api/markets/corporate-actions",
      "GET /api/markets/articles",
      "GET /api/markets/daily-brief",
      "GET /api/markets/daily-brief/history",
    ],
    freshness: "Index quotes within 30 seconds while the market is open, 5 minutes when it is closed; movers and flows are end of day; the brief is written once a day",
    status: "connected",
  },
  {
    // backend/routes/filings.py · services/adapters/filings.adapter.ts, screens/markets/hooks.ts
    // schedule: deploy/cloudpe/nidp/nidp-staging.cron
    id: "filings",
    name: "Exchange filings and announcements",
    provider: "NSE and BSE announcement feeds, classified on the Nivesh data platform",
    what: "Company announcements sorted by type and importance, the most material ones of the day, and the user's filing-alert preferences.",
    endpoints: [
      "GET /api/filings/feed",
      "GET /api/filings/signals",
      "GET /api/filings/alerts",
      "PUT /api/filings/alerts",
      "GET /api/filings/portfolio-held",
    ],
    freshness: "NSE announcements are read every 10 minutes on weekdays and every 30 at weekends; the feed goes back 30 days",
    status: "partial",
    note: "The BSE announcements job is switched off in the staging schedule because BSE refuses that server's requests, so new filings arrive from NSE only. Alert choices are saved; the route reports whether anything is being delivered.",
  },
  {
    // backend/routes/copilot_widgets.py, services/copilot_tools/company_financials.py · screens/markets/hooks.ts
    id: "company-financials",
    name: "Company financials and shareholding",
    provider: "Company results and shareholding filings on the Nivesh data platform",
    what: "A company's reported quarterly results, its shareholding pattern and its latest valuation figures.",
    endpoints: ["POST /api/copilot/widgets/company_financials"],
    freshness: "As companies file; results and shareholding are loaded every night",
    status: "connected",
    note: "Quarterly rows come from the same table the Trendlyne fundamentals fill.",
  },
  {
    // backend/routes/move_odds.py (stock_card) · screens/research/data.ts
    id: "stock-research-card",
    name: "Stock research card",
    provider: "Nivesh data platform (the Copilot's own stock card)",
    what: "Scores, technicals, risk and peers for one stock, as the Copilot's stock analyst attaches them to an answer.",
    endpoints: ["GET /api/move-odds/stocks/{symbol}/card"],
    freshness: "Built when asked, from the data platform's latest figures",
    status: "connected",
    note: "Switched on per account (the move-odds research feature); other accounts get a 403 and see the block as locked.",
  },
  {
    // backend/routes/research_chart_live.py (nidp.prices_eod_adjusted) · screens/research/data.ts, services/adapters/paperTrades.adapter.ts
    id: "adjusted-prices",
    name: "Adjusted daily prices",
    provider: "Nivesh data platform (nidp.prices_eod_adjusted)",
    what: "Daily price bars for an NSE stock, adjusted for splits and bonuses.",
    endpoints: ["GET /api/research/chart-live/{symbol}/ohlcv"],
    freshness: "End of day; adjusted on weekday nights",
    status: "connected",
    note: "Switched on per account (the charts research feature); other accounts get a 403 and see the block as locked.",
  },
  {
    // backend/routes/macro.py (stock_why) · screens/research/data.ts
    id: "macro-backdrop",
    name: "Market backdrop for a stock",
    provider: "Nivesh macro engine",
    what: "The macro state right now, how it tilts the stock's sector, and the position-size factor that follows from it.",
    endpoints: ["GET /api/stock/{symbol}/why"],
    freshness: "The day's macro reading",
    status: "connected",
  },
  {
    // backend/routes/mf_data.py, analytics.py (get_holding_detail) · screens/research/data.ts
    id: "mf-facts",
    name: "Mutual fund facts",
    provider: "Nivesh data platform and fund factsheets",
    what: "One fund's NAV, its returns, risk and rank against its category, and its size, cost, managers and holdings.",
    endpoints: ["GET /api/mf/lookup", "GET /api/portfolio/holding-detail/{isin}", "GET /api/mf/holdings"],
    freshness: "NAV on weekday evenings; factsheet figures as last fetched",
    status: "connected",
  },
  {
    // backend/routes/chat.py · hooks/use-instrument-search.ts
    id: "instrument-search",
    name: "Stock and fund search",
    provider: "The data platform's stock list and mutual fund scheme master",
    what: "Stocks and mutual funds that match what the user is typing.",
    endpoints: ["GET /api/chat/instrument-search"],
    freshness: "Looked up as the user types",
    status: "connected",
  },
  {
    // backend/routes/thematic_prefs.py · screens/markets/hooks.ts, hooks/useThematicQueries.ts
    id: "research-questions",
    name: "Research question history and favourites",
    provider: "Saved by the user",
    what: "The research questions the user has asked before and the ones they starred.",
    endpoints: ["GET /api/thematic/prefs", "POST /api/thematic/history", "POST /api/thematic/favorites/toggle"],
    freshness: "As the user last saved them",
    status: "connected",
  },
  {
    // backend/routes/screeners.py (run_screener), services/copilot_tools/stock_intelligence.py · screens/markets/screener-run.ts
    id: "nidp-features",
    name: "NIDP stock feature store",
    provider: "Nivesh data platform (nidp.stock_features_daily)",
    what: "Price, volume, technical and fundamental figures for every stock, one row per stock per day.",
    endpoints: ["POST /api/screeners/run"],
    freshness: "End of day; rebuilt on weekday nights",
    status: "partial",
    note: "Staging, 13 Oct 2026: the latest day has 2,469 stocks, with P/E, 1-year return, RSI and momentum filled and ROE, ROCE, debt-to-equity, P/B and market cap empty. The chat screener reads the same rows.",
  },
  {
    // backend/routes/strategy_builder.py · services/strategyBuilder.ts, pages/StrategyBuilder (mounted by screens/desk/StrategyBuilder.tsx),
    // screens/markets/StrategyScreens.tsx, screens/workspace/strategies.ts
    id: "strategy-builder",
    name: "Strategy-builder screens and backtests",
    provider: "Nivesh strategy engine, on the data platform's daily feature snapshots",
    what: "Stock universes, the built-in screens with their rules, the stocks that pass a screen on the latest day, the user's saved strategies, and backtests of one.",
    endpoints: [
      "GET /api/strategy-builder/templates",
      "GET /api/strategy-builder/universe-catalog",
      "GET /api/strategy-builder/universes",
      "POST /api/strategy-builder/universes",
      "POST /api/strategy-builder/screen",
      "GET /api/strategy-builder/strategies",
      "GET /api/strategy-builder/strategies/{strategy_id}",
      "POST /api/strategy-builder/strategies",
      "PATCH /api/strategy-builder/strategies/{strategy_id}",
      "DELETE /api/strategy-builder/strategies/{strategy_id}",
      "POST /api/strategy-builder/strategies/{strategy_id}/backtest",
      "GET /api/strategy-builder/runs/{run_id}",
    ],
    freshness: "The latest daily feature snapshot (end of day)",
    status: "connected",
  },
  {
    // backend/nidp/services/trendlyne_fundamentals (no app route) → nidp.nse_financials_quarterly
    // schedule: deploy/cloudpe/nidp/nidp-staging.cron
    id: "trendlyne-fundamentals",
    name: "Trendlyne fundamentals",
    provider: "Trendlyne, staged into the Nivesh data platform",
    what: "Quarterly revenue, profit, operating profit and EPS for each company.",
    endpoints: [],
    freshness: "One run each morning, within a daily call budget",
    status: "partial",
    note: "No app route of its own: it fills nidp.nse_financials_quarterly, which feeds the stock feature store and the company financials card. Staging, 13 Oct 2026: quarterly figures are loaded for about 2,180 companies; market cap and ratio fields are not loaded yet.",
  },
  {
    // backend/routes/fno.py (being added) → backend/nidp/services/daas_api/routers/fno.py · screens/trading/fno.ts
    id: "fno-bhavcopy",
    name: "NSE F&O bhavcopy",
    provider: "NSE, through the Nivesh data platform (nidp.fno_bhavcopy)",
    what: "Futures and options for every strike and expiry, with closing and settle prices, open interest, volume and lot size.",
    endpoints: ["GET /api/fno/{symbol}/chain", "GET /api/fno/{symbol}/expiries", "GET /api/fno/{symbol}/futures"],
    freshness: "End of day; loaded on weekday evenings",
    status: "connected",
    note: "Live on staging since 14 Oct 2026, lot size included. The exchange file has no implied volatility: the app works out implied volatility, the Greeks and the expected move from these prices as model estimates, labelled as such. Margin and intraday prices are not in this source.",
  },
  {
    // no app route serves Kite bars · backend/feature_flags.py (sim_lab, charting), backend/routes/sim_lab.py, research_chart.py, services/brokers/zerodha.py
    id: "kite-market-data",
    name: "Kite (Zerodha) market data",
    provider: "Zerodha Kite Connect",
    what: "Intraday and daily price bars for stocks and indices from Kite.",
    endpoints: [],
    freshness: "Not served to the app",
    status: "planned",
    note: "No app route serves Kite bars, and the Kite bar collector is not part of this branch yet. What exists here is frozen research built on Kite-derived prices, for invited accounts only: the simulation lab runs (GET /api/sim-lab/*) and the research charts snapshot (GET /api/research/chart/*). Zerodha sign-in through Kite Connect is one of the server's broker links.",
  },

  // ── trading ────────────────────────────────────────────────────────────
  {
    // backend/routes/positional.py, positional_journal.py · screens/trading/queries.ts
    id: "positional",
    name: "Positional scanner, watch levels and trade journal",
    provider: "Nivesh positional engine; the journal is the user's own log",
    what: "The scanner's scored signals, setups to watch with trigger and stop levels, and the trades the user has logged with their results.",
    endpoints: [
      "GET /api/positional/picks",
      "GET /api/positional/watchlist",
      "GET /api/positional/journal",
      "GET /api/positional/journal/summary/portfolio",
    ],
    freshness: "Signals for the latest signal date; the journal as the user logs it, with a last price when Yahoo Finance answers",
    status: "connected",
  },
  {
    // backend/routes/paper_trades.py · services/adapters/paperTrades.adapter.ts, screens/trading/queries.ts
    id: "paper-trades",
    name: "Paper trades",
    provider: "Nivesh paper-trade engine on the data platform",
    what: "The engine's recorded paper positions for each session, the stored evaluation of the record, and the status of the latest session.",
    endpoints: [
      "GET /api/paper-trades/portfolio",
      "GET /api/paper-trades/evaluation",
      "GET /api/paper-trades/live",
      "GET /api/paper-trades/trades/{trade_id}",
    ],
    freshness: "Each session is recorded after the close; the live status is delayed (Yahoo Finance 5-minute bars)",
    status: "connected",
    note: "Served only to accounts on the move-odds allow-list; other accounts get a 403.",
  },
  {
    // backend/routes/sim_lab.py (frozen runs; nothing is computed at request time) · screens/desk/SimulationLab.tsx
    id: "sim-lab",
    name: "Simulation lab runs",
    provider: "Nivesh paper-trade engine (frozen, pre-registered simulation runs)",
    what: "The engine's recorded simulation runs: the run, its configuration matrix, the candidates and every simulated trade.",
    endpoints: ["GET /api/sim-lab/run", "GET /api/sim-lab/matrix", "GET /api/sim-lab/trades", "GET /api/sim-lab/candidates"],
    freshness: "Frozen: a run does not change after it is recorded",
    status: "connected",
    note: "Switched on per account (the sim-lab research feature); other accounts get a 403. Internal research on Kite-derived prices: not signals, and not for redistribution.",
  },
  {
    // backend/routes/research_watchlist.py · hooks/use-research-watchlist.ts
    id: "research-watchlist",
    name: "Research watchlist",
    provider: "Nivesh research (dated lists); quotes from Yahoo Finance",
    what: "Dated lists of stocks under research, each with the price when it was listed and the price now.",
    endpoints: ["GET /api/public/research-watchlist"],
    freshness: "A new list when research publishes one; quotes are live, or the last stored price when Yahoo Finance does not answer",
    status: "connected",
    note: "A public route that needs no sign-in. Internal research, not a recommendation.",
  },
  {
    // backend/routes/watchlists.py · screens/workspace/personal-lists.ts
    id: "personal-watchlists",
    name: "Personal watchlists",
    provider: "Saved by the user; quotes from Yahoo Finance, else the data platform's end-of-day prices",
    what: "The lists of stocks a user has named, with the stocks in each and a price for each stock.",
    endpoints: [
      "GET /api/watchlists", "POST /api/watchlists", "POST /api/watchlists/starter", "GET /api/watchlists/{watchlist_id}",
      "PATCH /api/watchlists/{watchlist_id}", "DELETE /api/watchlists/{watchlist_id}",
      "POST /api/watchlists/{watchlist_id}/symbols", "DELETE /api/watchlists/{watchlist_id}/symbols/{symbol}",
    ],
    freshness: "As the user last changed them; prices are live for stocks in a research list, else the last end-of-day close",
    status: "partial",
    note: "Live quotes cover only stocks that are in a published research list. A first-time user is given one example list, copied from the newest research list. No price or volume alerts.",
  },
  {
    // backend/routes/screeners.py · hooks/use-screeners.ts
    id: "saved-screens",
    name: "Saved screens",
    provider: "Saved by the user",
    what: "The stock screens a user has named and kept, each with its rules.",
    endpoints: ["GET /api/screeners", "POST /api/screeners", "PUT /api/screeners/{screener_id}", "DELETE /api/screeners/{screener_id}"],
    freshness: "As the user last saved them",
    status: "connected",
  },
  {
    // backend/routes/broker_connect.py, broker_native.py, portfolio.py, services/brokers/* (read-only adapters)
    // · screens/account/brokers.tsx, screens/account/queries.ts, screens/desk/broker.ts, screens/trading/queries.ts
    id: "broker-accounts",
    name: "Broker portfolio and positions (read-only)",
    provider: "The user's broker, through a read-only link held by the server",
    what: "The holdings and positions in a user's broker accounts, fetched read-only; the broker link is never used to place an order.",
    endpoints: [
      "GET /api/broker/accounts",
      "GET /api/broker/native/supported",
      "GET /api/broker/native/start/{broker_slug}",
      "POST /api/broker/accounts/{account_id}/sync",
      "DELETE /api/broker/accounts/{account_id}",
      "GET /api/broker/positions",
      "GET /api/portfolio/holdings",
    ],
    freshness: "Holdings as of each account's last sync; positions at the moment they are read",
    status: "partial",
    note: "Sign-in happens on the broker's own page and only where the server marks a broker connectable (on staging, 14 Oct 2026, none has app keys set). Linked accounts can be listed, synced and disconnected; holdings a broker reported are stored, and open positions are read live and not stored. No route returns a broker's funds or day P&L.",
  },

  // ── advisor ────────────────────────────────────────────────────────────
  {
    // backend/routes/mfd.py, advisor.py, advisor_v4.py · hooks/use-advisor.ts, hooks/use-mfd.ts
    id: "advisor-book",
    name: "Advisor client book and SIP board",
    provider: "Nivesh advisor workspace",
    what: "Every client of an advisor with value, health and priority, the SIP totals for the book, and the advisor's daily lists.",
    endpoints: [
      "GET /api/mfd/profiles",
      "POST /api/mfd/profiles",
      "DELETE /api/mfd/profiles/{profile_id}",
      "POST /api/mfd/profiles/{profile_id}/activate",
      "POST /api/mfd/profiles/deactivate",
      "GET /api/advisor/sip-board/summary",
      "GET /api/advisor/today",
      "GET /api/advisor/aum",
      "GET /api/advisor/underperformers",
      "GET /api/advisor/rebalance",
      "GET /api/mfd/profiles/{profile_id}/needs-attention",
    ],
    freshness: "Scored for each client when the book is opened",
    status: "connected",
  },

  {
    // backend/routes/mfd.py, client_cas_invite.py, cas_snapshots.py, portfolio_export.py · screens/advisor/data.ts
    id: "client-records",
    name: "Client records on file",
    provider: "Nivesh advisor workspace",
    what: "What is on file for one client of an advisor: value and recent purchases, unrealised gains, statement history, statements the client shared, and notes.",
    endpoints: [
      "GET /api/mfd/profiles/{profile_id}/portfolio-trend",
      "GET /api/mfd/profiles/{profile_id}/tax-summary",
      "GET /api/mfd/profiles/{profile_id}/notes",
      "GET /api/portfolio/cas-snapshots",
      "GET /api/mfd/profiles/{profile_id}/cas-invites",
      "GET /api/mfd/profiles/{profile_id}/cas-uploads",
      "GET /api/mfd/profiles/{profile_id}/holdings/export",
    ],
    freshness: "As last recorded for the client",
    status: "connected",
    note: "Read only in the Copilot: writing a note, asking a client for a statement, logging a call and preparing a review pack are not wired.",
  },

  // ── the Copilot and the platform ───────────────────────────────────────
  {
    // backend/routes/chat.py, copilot_agents.py, copilot_prompts.py · services/adapters/chat.adapter.ts, lib/use-thread-engine.ts
    id: "copilot-chat",
    name: "Copilot chat and routing agents",
    provider: "Nivesh chat pipeline",
    what: "The streamed answer to a question with its tool steps and result card, the user's past threads, the specialist agents, and suggested questions.",
    endpoints: [
      "POST /api/chat/stream",
      "GET /api/chat/sessions",
      "DELETE /api/chat/sessions/{session_id}",
      "GET /api/chat/messages",
      "GET /api/chat/suggest-queries",
      "GET /api/copilot/agents",
      "GET /api/copilot/suggested-prompts",
    ],
    freshness: "Live, for each question",
    status: "connected",
  },
  {
    // backend/routes/compliance.py · screens/account/queries.ts, screens/internal/use-internal-data.ts
    id: "audit-trail",
    name: "Account audit trail",
    provider: "Nivesh compliance log",
    what: "The signed-in account's own record of actions, such as sign-ins and broker connect, sync and disconnect events.",
    endpoints: ["GET /api/compliance/audit"],
    freshness: "Written as each action happens",
    status: "connected",
  },
  {
    // backend/routes/admin_nidp.py · screens/internal/use-internal-data.ts
    id: "feed-health",
    name: "Data feed health",
    provider: "Nivesh data platform feed monitor",
    what: "Whether each data feed is healthy, stale, failing or has never run, and when it last ran.",
    endpoints: ["GET /api/admin/nidp/feeds/live"],
    freshness: "Read live when the page asks",
    status: "connected",
    note: "Admins only.",
  },
  {
    // components/EntityIcon.tsx, lib/logo-manifest.ts (every map is empty; no API the app calls returns a logo URL)
    id: "entity-logos",
    name: "Company, fund house and broker logos",
    provider: "None yet",
    what: "The logo shown beside a company, a fund house or a broker.",
    endpoints: [],
    freshness: "Not served to the app",
    status: "planned",
    note: "The icon slots are in place and draw a monogram tile today. Real logos need a licensed source, or an asset pack registered in the logo manifest (lib/logo-manifest.ts).",
  },
] as const satisfies readonly DataSource[];

/** Every id in the pool. A template that names another id does not compile. */
export type SourceId = (typeof POOL)[number]["id"];

export const DATA_SOURCES: readonly DataSource[] = POOL;

const BY_ID = new Map<string, DataSource>(DATA_SOURCES.map((s) => [s.id, s]));

export function sourceById(id: SourceId): DataSource {
  // Every SourceId is in the pool by construction.
  return BY_ID.get(id) as DataSource;
}

const key = (text: string) => text.replace(/\s+/g, " ").trim().toLowerCase();

const BY_NAME = new Map<string, DataSource>(DATA_SOURCES.map((s) => [key(s.name), s]));

/**
 * The pool source a data row refers to: its "Source" text is the source's name
 * (or its id), ignoring case and spacing. Undefined for a free-text row.
 */
export function matchSource(text: string): DataSource | undefined {
  const k = key(text);
  if (!k) return undefined;
  return BY_NAME.get(k) ?? BY_ID.get(k);
}

export const STATUS_LABEL: Record<SourceStatus, string> = {
  connected: "Connected",
  partial: "Partial",
  planned: "Planned",
};

export const STATUS_TONE: Record<SourceStatus, Tone> = {
  connected: "mint",
  partial: "amber",
  planned: "ink",
};

/** How many sources hold each status, for the pool's summary line. */
export function countByStatus(sources: readonly DataSource[]): Record<SourceStatus, number> {
  const counts: Record<SourceStatus, number> = { connected: 0, partial: 0, planned: 0 };
  for (const s of sources) counts[s.status] += 1;
  return counts;
}
