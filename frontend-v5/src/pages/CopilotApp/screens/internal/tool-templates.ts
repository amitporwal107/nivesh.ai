/**
 * Tool builder — one template for every tool that exists in the shell today,
 * written out the way the builder would define it.
 *
 * The list follows lib/views.ts and screens/index.ts: the tools of each mode,
 * the workspace pages, and the Copilot chat itself. Each template describes the
 * tool AS BUILT: the services are the routes the screen (and its hooks) call,
 * the data rows point at entries of the data source pool
 * (screens/internal/data-sources.ts), and `gaps` lists the blocks of the screen
 * that are not connected. Nothing here is a plan or a wish.
 *
 * `personas` is not typed in: it is read from lib/views.ts (the modes whose
 * rail shows the tool), so a template cannot disagree with the navigation.
 * `gaps` is shown in the builder and is not part of the generated contract.
 */
import { WORKSPACE_NAV, allToolsNav, type Mode } from "../../lib/views";
import { sourceById, type SourceId } from "./data-sources";
import { rowId, type DataNeed, type ToolDraft, type ToolInput, type Trigger } from "./tool-draft";

export interface TemplateDataRow {
  /** An id from the data source pool. */
  source: SourceId;
  need: DataNeed["need"];
  /** The freshness this tool needs. Left out, the source's own freshness is used. */
  freshness?: string;
}

export interface ToolTemplate {
  id: string;
  /** The view below the app base where the tool lives ("" is the Copilot home and its threads). */
  view: string;
  name: string;
  personas: Mode[];
  answerClass: string;
  objective: string;
  questions: string[];
  data: TemplateDataRow[];
  inputs: Array<Omit<ToolInput, "id">>;
  services: string[];
  outputs: string[];
  guardrails: string[];
  triggers: Array<Omit<Trigger, "id">>;
  /** Blocks of the tool that are not connected. Shown in the builder, not in the contract. */
  gaps: string[];
}

type TemplateSpec = Omit<ToolTemplate, "personas">;

// ── shared wording ───────────────────────────────────────────────────────

/** How lib/answer.ts labels an answer from the agent that produced it. */
const PERSONAL = "Personalised research";
const GENERAL = "General research";
const VALIDATION = "Research · validation";
/** A page of the user's own records and connections; it does not produce an answer. */
const WORKSPACE = "Workspace";

const NOT_ADVICE = "Educational, not investment advice";
const NO_ORDERS = "No order placement: nothing here buys, sells or moves money";
const EOD_LABELLED = "End-of-day data is labelled as end of day";
const NEVER_ESTIMATED = "A figure that is missing is shown as missing, never estimated";
const OWN_DATA = "Reads only the signed-in user's own portfolio";
const CLIENT_DATA = "Reads only the clients in the signed-in advisor's own book";
/** The product owner's rule for every broker link. */
const BROKER_READ_ONLY = "The broker link is read-only: it fetches the portfolio and positions and is never used to place an order";

const SESSION_USER: Omit<ToolInput, "id"> = {
  field: "user",
  type: "signed-in account",
  fallback: "",
  rule: "taken from the session, never typed",
};
const SESSION_ADVISOR: Omit<ToolInput, "id"> = {
  field: "advisor",
  type: "signed-in advisor account",
  fallback: "",
  rule: "taken from the session; the page is for advisor accounts",
};

const ON_OPEN: Omit<Trigger, "id"> = { type: "On demand", detail: "when the user opens the screen" };
const MARKET_STRIP: Omit<Trigger, "id"> = { type: "While open", detail: "the market quotes are read again every 60 seconds" };

// ── the templates ────────────────────────────────────────────────────────

const SPECS: TemplateSpec[] = [
  // ── investor tools ─────────────────────────────────────────────────────
  {
    id: "portfolio-analysis",
    view: "tool/analysis",
    name: "Portfolio analysis",
    answerClass: PERSONAL,
    objective: "Show an investor what they own, how it has performed and where it is concentrated, and what to fix first.",
    questions: [
      "Is my largest position too big?",
      "Why is my biggest loser down?",
      "Which of my funds overlap most?",
      "What do my Regular plans cost me?",
    ],
    data: [
      { source: "cas-holdings", need: "required", freshness: "The latest imported statement" },
      { source: "exposure", need: "required", freshness: "Worked out again on each open" },
      { source: "performance", need: "required", freshness: "The latest imported statement" },
      { source: "goals-risk-profile", need: "optional", freshness: "The saved risk profile, for the target mix" },
      { source: "plan-engine", need: "optional", freshness: "The active plan" },
      { source: "mf-rankings", need: "optional", freshness: "Daily" },
    ],
    inputs: [
      SESSION_USER,
      { field: "period", type: "inception | 1Y | 6M | 3M | 1M", fallback: "inception", rule: "the period for the performance section" },
    ],
    services: [
      "GET /api/portfolio/holdings-enriched",
      "GET /api/portfolio/exposure/concentration",
      "GET /api/portfolio/composition",
      "GET /api/user/risk-profile",
      "GET /api/dashboards/performance",
      "GET /api/portfolio/value-history",
      "GET /api/portfolio/fund-performance",
      "GET /api/portfolio/analytics",
      "GET /api/portfolio/recommendations/v5",
      "GET /api/mf/category-top",
      "GET /api/portfolio/exposure/fund-overlap/matrix",
      "GET /api/portfolio/exposure/remediation",
      "POST /api/portfolio/resync",
    ],
    outputs: [
      "Value, invested, unrealised gain and XIRR",
      "Exposure by sector, company, fund house, group, fund and asset class",
      "The asset mix against the target for the user's risk category",
      "Performance for the period: monthly returns against the benchmark, value history, best and worst performers",
      "Concentration ladder and the fund pairs that hold the same stocks",
      "What to fix: ranked actions with their projected impact",
    ],
    guardrails: [
      NOT_ADVICE,
      NO_ORDERS,
      OWN_DATA,
      "Figures are based on the statement's values; XIRR and alpha are shown as still calculating until they are ready",
      "The target mix is the one for the user's saved risk category; an asset class outside it is listed with no target",
    ],
    triggers: [
      ON_OPEN,
      { type: "On demand", detail: "Resync recomputes the performance figures from the holdings" },
    ],
    gaps: [],
  },
  {
    id: "recommendations",
    view: "tool/recommend",
    name: "Recommendations",
    answerClass: PERSONAL,
    objective: "List the open steps of the investor's active plan, what doing all of them would change, and let them record what they decide.",
    questions: [
      "What should I do first, and why?",
      "What is each recommendation based on?",
      "How would my portfolio's health change if I did all of this?",
      "How much tax would these steps cost me?",
    ],
    data: [
      { source: "plan-engine", need: "required", freshness: "The active plan" },
      { source: "goals-risk-profile", need: "required" },
      { source: "cas-holdings", need: "required", freshness: "The latest imported statement" },
    ],
    inputs: [
      SESSION_USER,
      { field: "filter", type: "all | reduce | add | hold", fallback: "all", rule: "which steps to list" },
    ],
    services: [
      "GET /api/plans/active",
      "GET /api/plans/active/health-projection",
      "GET /api/goals",
      "GET /api/user/risk-profile",
      "GET /api/portfolio/holdings-enriched",
      "PATCH /api/plans/{plan_id}/actions/{action_id}",
      "POST /api/plans/refresh",
    ],
    outputs: [
      "The open steps of the active plan, filtered by reduce, add or hold",
      "On each step: its verb, severity, suggested route, amount, reason, tax breakdown and expected effect",
      "Before and after: portfolio health, volatility and fund costs",
      "Estimated tax and the capital the steps would free",
      "What the plan was built from: goals, risk profile and holdings",
      "The plan's confidence tier",
    ],
    guardrails: [
      NOT_ADVICE,
      NO_ORDERS,
      OWN_DATA,
      "Marking a step records the user's decision; nothing is bought or sold",
      "Tax is shown as an estimate",
    ],
    triggers: [
      ON_OPEN,
      { type: "On demand", detail: "the user marks a step done or declined" },
      { type: "On demand", detail: "the user rebuilds the plan, or asks for a first one" },
    ],
    gaps: [],
  },
  {
    id: "risk",
    view: "tool/risk",
    name: "Risk",
    answerClass: PERSONAL,
    objective: "Tell an investor how much their portfolio could lose in a bad year, what drives that, and whether it fits their risk profile.",
    questions: [
      "How much could my portfolio lose in a bad year?",
      "What is making my portfolio risky?",
      "Does my portfolio match my risk profile?",
      "How would my portfolio hold up in a market fall?",
    ],
    data: [
      { source: "risk-metrics", need: "required", freshness: "The latest nightly run" },
      { source: "goals-risk-profile", need: "required" },
    ],
    inputs: [SESSION_USER],
    services: ["GET /api/dashboards/risk", "GET /api/user/risk-profile", "POST /api/user/risk-profile"],
    outputs: [
      "Value at risk over a year, volatility, maximum drawdown and beta",
      "The user's risk profile and its target mix",
      "What is making the portfolio risky",
      "Stress scenarios with their simulated impact",
      "A warning when the risk figures are missing or out of date",
    ],
    guardrails: [NOT_ADVICE, NO_ORDERS, OWN_DATA, "Stress results are simulations, labelled as simulated"],
    triggers: [
      ON_OPEN,
      { type: "Admin", detail: "an admin can start the risk engine run from the page" },
    ],
    gaps: [],
  },
  {
    id: "goals",
    view: "tool/goals",
    name: "Goals",
    answerClass: PERSONAL,
    objective: "Show an investor whether each goal is on track, and what a change in saving would do.",
    questions: [
      "Am I on track for my goals?",
      "Which goal needs attention first?",
      "What happens if I change how much I invest each month?",
    ],
    data: [{ source: "goals-risk-profile", need: "required" }],
    inputs: [
      SESSION_USER,
      { field: "goal", type: "one of the user's goals", fallback: "", rule: "the goal to run a what-if on" },
    ],
    services: ["GET /api/dashboards/goals", "GET /api/goals", "POST /api/goals/{goal_id}/what-if", "POST /api/goals"],
    outputs: [
      "The projected path to the goals",
      "A focus goal with a what-if simulation",
      "A table of every goal",
      "Suggested moves",
    ],
    guardrails: [NOT_ADVICE, NO_ORDERS, OWN_DATA, "Projections are labelled as projected"],
    triggers: [ON_OPEN],
    gaps: [],
  },
  {
    id: "tax",
    view: "tool/tax",
    name: "Tax",
    answerClass: PERSONAL,
    objective: "Show an investor the capital gains tax they face this year and the losses they could book to lower it.",
    questions: [
      "How much capital gains tax do I owe this year?",
      "Which holdings could I sell at a loss to lower my tax?",
      "How are my gains split between short term and long term?",
    ],
    data: [{ source: "tax", need: "required", freshness: "The latest imported statement" }],
    inputs: [SESSION_USER],
    services: ["GET /api/dashboards/tax"],
    outputs: [
      "The tax timeline for the financial year",
      "A harvest plan: the loss-making lots flagged, and the net saving",
      "Tax split by long-term and short-term gains",
      "Suggested moves",
    ],
    guardrails: [NOT_ADVICE, NO_ORDERS, OWN_DATA, "Tax figures are approximate and are shown as approximate"],
    triggers: [ON_OPEN],
    gaps: ["The “Schedule harvest” button has no action wired to it."],
  },

  // ── tools every mode has ───────────────────────────────────────────────
  {
    id: "research",
    view: "tool/research",
    name: "Stock & fund research",
    answerClass: GENERAL,
    objective: "Let anyone read what companies have filed, and open one stock or mutual fund to research it.",
    questions: [
      "Which recent company filings matter most, and why?",
      "What changed in a company's latest quarterly results?",
      "Who owns a company, and how has that changed?",
      "How has a fund done against its category?",
      "How would adding a stock change my portfolio?",
    ],
    data: [
      { source: "filings", need: "required", freshness: "Within the hour on trading days" },
      { source: "company-financials", need: "required", freshness: "The latest reported quarter" },
      { source: "instrument-search", need: "required" },
      { source: "mf-facts", need: "required", freshness: "The latest NAV and factsheet" },
      { source: "stock-research-card", need: "optional" },
      { source: "adjusted-prices", need: "optional", freshness: "End of day" },
      { source: "macro-backdrop", need: "optional" },
      { source: "market-pulse", need: "optional", freshness: "Daily, for corporate actions" },
      { source: "research-questions", need: "optional" },
    ],
    inputs: [
      { field: "query", type: "text", fallback: "", rule: "at least two characters; finds a stock or a fund" },
      { field: "kind", type: "filings | stock | fund", fallback: "filings", rule: "what to research" },
    ],
    services: [
      "GET /api/chat/instrument-search",
      "GET /api/filings/signals",
      "GET /api/filings/feed",
      "GET /api/filings/portfolio-held",
      "GET /api/thematic/prefs",
      "POST /api/copilot/widgets/company_financials",
      "GET /api/research/chart-live/{symbol}/ohlcv",
      "GET /api/move-odds/stocks/{symbol}/card",
      "GET /api/stock/{symbol}/why",
      "GET /api/markets/corporate-actions",
      "GET /api/mf/lookup",
      "GET /api/portfolio/holding-detail/{isin}",
      "GET /api/mf/holdings",
    ],
    outputs: [
      "Filings read for you: the most material recent filings",
      "Every filing, filtered by category",
      "For a stock: key figures, quarterly results, shareholding, price with its 52-week range, the research card, the market backdrop, corporate actions and filings",
      "For a fund: NAV, returns, risk and rank against its peers, size, cost, managers and holdings",
      "A “You hold” mark on companies in the user's portfolio",
      "The user's research question history and favourites",
    ],
    guardrails: [
      NOT_ADVICE,
      NO_ORDERS,
      "AI reads of a filing are summaries; the source filing is the reference",
      "A block the account is not switched on for says it is locked, instead of showing an error",
      NEVER_ESTIMATED,
    ],
    triggers: [ON_OPEN],
    gaps: [
      "Stock page: annual statements, a fair-value read against the stock's own history, bulk and block deals, and what a purchase would do to the user's portfolio have no source on the page.",
      "Fund page: a NAV chart, returns against the benchmark, the fund's score, its exit load and its overlap with the funds the user holds have no source on the page.",
      "The price history and the research card are switched on per account; other accounts see those two blocks as locked.",
    ],
  },
  {
    id: "screener",
    view: "tool/screener",
    name: "Screener",
    answerClass: GENERAL,
    objective: "Find the stocks that pass a list of rules on the day's data, and keep the screens worth running again.",
    questions: [
      "Which stocks pass these rules today?",
      "Which stocks pass one of the ready-made screens?",
      "How much of the day's data did each rule have to work with?",
      "Which of my saved screens has matches today?",
    ],
    data: [
      { source: "nidp-features", need: "required", freshness: "End of day" },
      { source: "strategy-builder", need: "required", freshness: "End of day" },
      { source: "saved-screens", need: "optional" },
    ],
    inputs: [
      { field: "conditions", type: "list of metric, over | under, value", fallback: "", rule: "every rule must pass; at least one rule or a size" },
      { field: "bucket", type: "any | large | mid | small", fallback: "any", rule: "market-cap size" },
      { field: "limit", type: "whole number", fallback: "200", rule: "1 to 500 matching stocks sent back" },
    ],
    services: [
      "POST /api/screeners/run",
      "GET /api/strategy-builder/templates",
      "POST /api/strategy-builder/screen",
      "POST /api/strategy-builder/strategies",
      "GET /api/screeners",
      "POST /api/screeners",
      "PUT /api/screeners/{screener_id}",
      "DELETE /api/screeners/{screener_id}",
    ],
    outputs: [
      "The matching stocks, in the same table the chat uses",
      "How many stocks match, and how many are shown",
      "A coverage line: how many stocks had a value for each rule's metric",
      "Ready-made screens with their ranked candidates",
      "Save as a watchlist: the rules that were run, kept for the Watchlist screen",
      "The user's saved screens, to run, edit or delete",
    ],
    guardrails: [
      NOT_ADVICE,
      NO_ORDERS,
      EOD_LABELLED,
      "Screen matches are candidates, not recommendations",
      "A rule on a metric the day's data does not carry is named as a data gap, not shown as a result",
    ],
    triggers: [
      { type: "On demand", detail: "when the user runs a screen" },
    ],
    gaps: [
      "Rules on ROE, ROCE, debt-to-equity, P/B and market cap match nothing on staging: the stock feature store has no values for them (checked 13 Oct 2026).",
    ],
  },
  {
    id: "markets",
    view: "tool/markets",
    name: "Markets",
    answerClass: GENERAL,
    objective: "Give anyone the state of the Indian market today: indices, sectors, earnings, institutional flows, corporate actions and the day's brief.",
    questions: [
      "How is the market doing today?",
      "Which sectors are leading and which are lagging?",
      "What are foreign and domestic institutions buying and selling?",
      "Which corporate actions are coming up?",
      "What happened in the market today?",
    ],
    data: [
      { source: "market-pulse", need: "required", freshness: "Live quotes in market hours; end of day for the rest" },
      { source: "filings", need: "optional", freshness: "The user's current holdings, for the “You hold” marks" },
    ],
    inputs: [
      { field: "cap", type: "all | large | mid | small", fallback: "all", rule: "size segment for the movers" },
      { field: "index", type: "index name", fallback: "Nifty 500", rule: "the universe for the earnings tracker" },
      { field: "date", type: "date", fallback: "today", rule: "which daily brief to read" },
    ],
    services: [
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
      "GET /api/filings/portfolio-held",
    ],
    outputs: [
      "Index levels with recent closes, breadth, top movers, 52-week and most-active lists, world indices and commodities",
      "One row per sector, opening to its figures, largest companies and commentary",
      "The earnings season by sector, each sector's companies, and results for the stocks the user holds",
      "FII and DII cash flows, and institutional positioning by sector",
      "Corporate actions for the 30 days either side of today",
      "News articles from classified filings, and the daily brief",
    ],
    guardrails: [
      NOT_ADVICE,
      NO_ORDERS,
      "The page names its sources: NSE and BSE through the Nivesh data platform, global quotes from Yahoo Finance",
    ],
    triggers: [ON_OPEN, MARKET_STRIP],
    gaps: [
      "How much each held stock usually moves on its results day is not available.",
    ],
  },

  // ── trader tools ───────────────────────────────────────────────────────
  // The old Trader desk and Options lab templates were removed with those screens (desk redesign step 6, 2026-10-27).
  {
    id: "strategy-builder",
    view: "trader/strategy",
    name: "Strategy builder",
    answerClass: VALIDATION,
    objective: "Let a trader pick a stock universe and a rule template, see which stocks pass today, backtest the rules and save the strategy.",
    questions: [
      "Which stocks pass this strategy today?",
      "How would this strategy have done over a past period?",
      "What are the entry and exit rules of this strategy?",
      "Which universe of stocks should I run it on?",
    ],
    data: [{ source: "strategy-builder", need: "required", freshness: "End of day" }],
    inputs: [
      { field: "universe", type: "a catalogue universe, or the user's own list of symbols", fallback: "", rule: "the stocks the strategy runs on" },
      { field: "template", type: "one of the built-in rule templates", fallback: "", rule: "sets the entry and exit rules; they can be edited" },
      { field: "from_date, to_date", type: "dates", fallback: "", rule: "the backtest period" },
      { field: "name", type: "text", fallback: "", rule: "needed to save the strategy" },
    ],
    services: [
      "GET /api/strategy-builder/universe-catalog",
      "GET /api/strategy-builder/universes",
      "POST /api/strategy-builder/universes",
      "GET /api/strategy-builder/templates",
      "POST /api/strategy-builder/screen",
      "POST /api/strategy-builder/strategies",
      "PATCH /api/strategy-builder/strategies/{strategy_id}",
      "POST /api/strategy-builder/strategies/{strategy_id}/backtest",
    ],
    outputs: [
      "Five steps: universe, strategy, screen, backtest, save",
      "Screen: the stocks that pass the rules today, ranked",
      "Backtest: total return, win rate, maximum drawdown, the number of trades and the equity curve",
      "Save the strategy, export the trades as a file, or copy its rules",
    ],
    guardrails: [
      "Research and validation only: the page has no order placement",
      NO_ORDERS,
      NOT_ADVICE,
      "A backtest is a simulation of the past, shown as a backtest",
    ],
    triggers: [
      { type: "On demand", detail: "when the user runs a screen or a backtest" },
    ],
    gaps: [
      "Live alerts on a saved strategy are not built: the page marks them as a later phase.",
    ],
  },

  // ── workspace pages ────────────────────────────────────────────────────
  {
    id: "watchlist",
    view: "page/watchlist",
    name: "Watchlist & alerts",
    answerClass: GENERAL,
    objective: "Show the stocks a user follows: the published research list, the stocks that pass each of their saved screens today, the scanner's levels to watch, and the filings they want to hear about.",
    questions: [
      "What is on the research watchlist, and how has each stock moved since it was listed?",
      "Which stocks pass my saved screens today?",
      "Which setups is the scanner watching, and at what level?",
      "Which filing alerts am I set up to receive?",
    ],
    data: [
      { source: "personal-watchlists", need: "required", freshness: "Live quotes, else the last end-of-day close" },
      { source: "research-watchlist", need: "required", freshness: "Live quotes" },
      { source: "saved-screens", need: "optional" },
      { source: "nidp-features", need: "optional", freshness: "End of day" },
      { source: "strategy-builder", need: "optional", freshness: "End of day" },
      { source: "positional", need: "optional", freshness: "End of day" },
      { source: "filings", need: "optional", freshness: "The user's saved alert choices" },
    ],
    inputs: [
      SESSION_USER,
      { field: "list_date", type: "date", fallback: "latest list", rule: "one of the dates a research list was published" },
    ],
    services: [
      "GET /api/watchlists",
      "POST /api/watchlists",
      "POST /api/watchlists/starter",
      "GET /api/watchlists/{watchlist_id}",
      "PATCH /api/watchlists/{watchlist_id}",
      "DELETE /api/watchlists/{watchlist_id}",
      "POST /api/watchlists/{watchlist_id}/symbols",
      "DELETE /api/watchlists/{watchlist_id}/symbols/{symbol}",
      "GET /api/filings/companies/search",
      "GET /api/public/research-watchlist",
      "GET /api/screeners",
      "POST /api/screeners/run",
      "GET /api/strategy-builder/strategies",
      "GET /api/strategy-builder/strategies/{strategy_id}",
      "POST /api/strategy-builder/screen",
      "DELETE /api/strategy-builder/strategies/{strategy_id}",
      "GET /api/positional/watchlist",
      "GET /api/filings/alerts",
      "PUT /api/filings/alerts",
    ],
    outputs: [
      "The user's own lists: the stocks in each, with a live price, a stored price and its date, or no quote",
      "The research watchlist for a date: each stock's place in the list, its price against the day it was added, and the research behind it",
      "A watchlist for each saved screen, rule screens and ready-made ones: the stocks that pass it today",
      "The scanner's setups to watch, each with its close, the level to cross and a stop",
      "The user's filing-alert choices, which can be changed here",
    ],
    guardrails: [
      NOT_ADVICE,
      NO_ORDERS,
      "The research list carries its disclaimer: information only, not a recommendation or a buy or sell call",
      "The scanner's levels are end-of-day levels to look at, not alerts: nothing is sent when one is crossed",
      "A filing-alert switch moves only after the save has succeeded",
    ],
    triggers: [
      ON_OPEN,
      { type: "While open", detail: "the research list and its quotes are read again every 30 seconds" },
    ],
    gaps: [
      "Being told when a price, a volume or a pledge level is crossed has nowhere to be stored.",
      "Filing-alert choices are saved, but nothing is sent until delivery is switched on.",
    ],
  },
  {
    id: "saved",
    view: "page/saved",
    name: "Saved",
    answerClass: WORKSPACE,
    objective: "Bring a user back to what they kept: their holdings file, saved screens, starred research questions and recent threads.",
    questions: [
      "Which screens have I saved?",
      "Which research questions did I star?",
      "Which threads did I have most recently?",
      "Can I download my holdings as a file?",
    ],
    data: [
      { source: "saved-screens", need: "required" },
      { source: "copilot-chat", need: "required", freshness: "The user's stored threads" },
      { source: "strategy-builder", need: "optional", freshness: "The user's saved strategies" },
      { source: "research-questions", need: "optional" },
      { source: "cas-holdings", need: "optional", freshness: "The latest imported statement, for the holdings file" },
    ],
    inputs: [
      SESSION_USER,
      { field: "format", type: "CSV | Excel", fallback: "", rule: "the format of the holdings file" },
    ],
    services: [
      "GET /api/portfolio/holdings/export",
      "GET /api/screeners",
      "GET /api/strategy-builder/strategies",
      "GET /api/thematic/prefs",
      "POST /api/thematic/favorites/toggle",
      "GET /api/chat/sessions",
      "DELETE /api/chat/sessions/{session_id}",
    ],
    outputs: [
      "Reports: the holdings file, as CSV or Excel",
      "Screens: saved rule screens, and ready-made screens kept from the Screener",
      "Questions: starred research questions, which can be un-starred",
      "Threads: the most recent ones, each with a way to continue or delete it",
    ],
    guardrails: ["Lists only the signed-in user's own files, screens, questions and threads", NO_ORDERS],
    triggers: [ON_OPEN],
    gaps: [
      "A Copilot answer cannot be kept as a report with the data it was built on: the product has no store for one.",
      "A thread cannot be pinned or renamed, so the most recent ones are listed.",
    ],
  },
  {
    id: "action-plan",
    view: "page/plan",
    name: "Action plan",
    answerClass: PERSONAL,
    objective: "Show an investor the steps of their active plan by where each stands, the record of what they decided, and what the plan expected against what their portfolio's record shows.",
    questions: [
      "What should I do first in my plan, and why?",
      "Which steps of my plan are still open?",
      "What did I decide on earlier steps?",
      "Is my portfolio moving the way the plan expected?",
    ],
    data: [
      { source: "plan-engine", need: "required", freshness: "The active plan" },
      { source: "portfolio-snapshots", need: "optional", freshness: "Daily, for expected against observed" },
    ],
    inputs: [SESSION_USER],
    services: [
      "GET /api/plans/active",
      "GET /api/plans/history",
      "GET /api/portfolio/trend",
      "GET /api/plans/active/health-projection",
      "PATCH /api/plans/{plan_id}/actions/{action_id}",
      "POST /api/plans/refresh",
    ],
    outputs: [
      "The plan board: step counts, the yearly saving, and each step under its current state",
      "On each card: the verb, the holding, the amount, the reason, severity, suggested route and tax",
      "The track record: what was done or declined, and when",
      "Expected and observed: what the plan expected against the portfolio's record as a whole",
    ],
    guardrails: [NOT_ADVICE, NO_ORDERS, OWN_DATA, "Moving a step records the user's decision; nothing is bought or sold"],
    triggers: [
      ON_OPEN,
      { type: "On demand", detail: "the user moves a step, or rebuilds the plan" },
    ],
    gaps: [
      "A result for each single step is not measured: nothing re-measures a step after it is marked done, so no met, partly met or missed verdict is shown.",
    ],
  },
  {
    id: "ledger",
    view: "page/ledger",
    name: "Portfolio ledger",
    answerClass: PERSONAL,
    objective: "Give an investor the full record of their portfolio: every holding and where it came from, realised gains, month-end value, and the statements, transactions and SIPs behind them.",
    questions: [
      "What do I hold, and what is each holding worth?",
      "Which holdings need a look first?",
      "What gains have I realised this financial year?",
      "What changed in my portfolio since last month?",
      "Which statements, transactions and SIPs are on record?",
    ],
    data: [
      { source: "cas-holdings", need: "required", freshness: "The latest imported statement" },
      { source: "statement-records", need: "required", freshness: "The latest imported statement" },
      { source: "tax", need: "required", freshness: "The latest imported statement" },
      { source: "portfolio-snapshots", need: "required", freshness: "Daily" },
    ],
    inputs: [
      SESSION_USER,
      { field: "correction", type: "buy price, purchase date or units of one holding", fallback: "", rule: "typed by the user; saved to the holdings on record" },
    ],
    services: [
      "GET /api/portfolio/holdings-enriched",
      "GET /api/portfolio/holdings",
      "PUT /api/portfolio/holdings/{holding_id}",
      "GET /api/portfolio/capital-gains-statement",
      "GET /api/portfolio/trend",
      "GET /api/onboarding/state",
      "GET /api/portfolio/compare",
      "GET /api/portfolio/cas-snapshots",
      "GET /api/portfolio/transactions",
      "GET /api/portfolio/sips",
    ],
    outputs: [
      "Health and the four headline figures",
      "The split by type, and the top gainers and losers",
      "Every holding with where it came from, the ones that need a look listed first, and a way to correct one",
      "Realised gains for the financial year",
      "Month-end value, and the change since last month",
      "The statements, transactions and SIPs on record",
    ],
    guardrails: [
      NOT_ADVICE,
      NO_ORDERS,
      OWN_DATA,
      "A correction changes the user's own record only; a newer statement replaces it, and the page says so",
      NEVER_ESTIMATED,
    ],
    triggers: [
      ON_OPEN,
      { type: "On demand", detail: "the user corrects a holding" },
    ],
    gaps: [
      "A log of corrections, with a way to undo one, is not kept.",
      "A holding cannot be matched to a different fund or stock, and two rows that are the same holding cannot be merged.",
      "There is no time-weighted return.",
    ],
  },
  {
    id: "paper-trades",
    view: "page/paper",
    name: "Paper trades",
    answerClass: VALIDATION,
    objective: "Show the paper-trade engine's recorded positions for each session, how the record has done, and the full record behind it.",
    questions: [
      "Which paper positions are open in the latest session?",
      "How has the paper record done so far?",
      "How does the record compare with every eligible stock?",
      "What happened to one paper trade, session by session?",
      "What fill rules did the engine assume?",
    ],
    data: [
      { source: "paper-trades", need: "required", freshness: "After each close; the live status is delayed" },
      { source: "adjusted-prices", need: "optional", freshness: "End of day, for one trade's chart" },
      { source: "sim-lab", need: "optional", freshness: "Frozen runs" },
    ],
    inputs: [
      { field: "view", type: "summary | full record | simulation lab", fallback: "summary", rule: "the simulation lab is offered only to accounts with that feature" },
      { field: "sample", type: "forward | replay", fallback: "forward", rule: "the two samples are never pooled" },
      { field: "portfolio", type: "P5-NEXT | P10-NEXT", fallback: "P5-NEXT", rule: "which paper portfolio" },
      { field: "prediction_date", type: "date", fallback: "latest session", rule: "one of the recorded sessions" },
    ],
    services: [
      "GET /api/paper-trades/portfolio",
      "GET /api/paper-trades/evaluation",
      "GET /api/paper-trades/live",
      "GET /api/paper-trades/trades/{trade_id}",
      "GET /api/research/chart-live/{symbol}/ohlcv",
      "GET /api/sim-lab/run",
      "GET /api/sim-lab/matrix",
      "GET /api/sim-lab/trades",
      "GET /api/sim-lab/candidates",
    ],
    outputs: [
      "Summary: open positions of the session and the closed ones",
      "The stored evaluation: net P&L, hit rate and the comparison with every eligible stock",
      "The delayed status of the latest forward session",
      "The fill assumptions the engine used",
      "Full record: the ranked universe, sizing what-ifs, one trade's path and lifecycle, every exit mode, the benchmarks and the calibration buckets",
      "Simulation lab: the engine's frozen simulation runs, trade by trade",
    ],
    guardrails: [
      "Paper only: no live orders",
      NO_ORDERS,
      NOT_ADVICE,
      "Forward and replay records are shown separately and never pooled",
      "Returns are shown as the engine stored them",
      "Only for accounts with the move-odds research feature; other accounts are told so",
    ],
    triggers: [
      ON_OPEN,
      { type: "While open", detail: "the live status is read again every 60 seconds" },
    ],
    gaps: [],
  },
  {
    id: "brokers",
    view: "page/brokers",
    name: "Broker connections",
    answerClass: WORKSPACE,
    objective: "Show a user where their portfolio data comes from, and let them add a statement or connect a broker for reading.",
    questions: [
      "Which statement is my portfolio built from?",
      "Is my Gmail connected for statement imports?",
      "Which broker accounts are linked to me, and what was read from each?",
      "What has been imported, and when?",
    ],
    data: [
      { source: "cas-holdings", need: "required", freshness: "The statement on file" },
      { source: "statement-imports", need: "required" },
      { source: "broker-accounts", need: "required", freshness: "The account's last sync" },
      { source: "audit-trail", need: "optional" },
    ],
    inputs: [
      SESSION_USER,
      { field: "statement", type: "CAS PDF file", fallback: "", rule: "uploaded by the user" },
      { field: "password", type: "text", fallback: "", rule: "the statement's password; kept in the page only for the upload" },
      { field: "broker", type: "one of the brokers the server can start a sign-in with", fallback: "", rule: "picked by the user" },
    ],
    services: [
      "GET /api/onboarding/state",
      "POST /api/onboarding/upload-cas",
      "GET /api/gmail/status",
      "GET /api/gmail/history",
      "GET /api/broker/accounts",
      "GET /api/portfolio/holdings",
      "POST /api/broker/accounts/{account_id}/sync",
      "DELETE /api/broker/accounts/{account_id}",
      "GET /api/broker/native/supported",
      "GET /api/broker/native/start/{broker_slug}",
      "GET /api/compliance/audit",
    ],
    outputs: [
      "The statement on file, and a way to add or replace it",
      "The Gmail connection and its import settings",
      "Linked broker accounts, with what was read from each, and sync and disconnect",
      "The brokers a sign-in can be started with",
      "The import log: Gmail imports and broker events",
    ],
    guardrails: [
      NO_ORDERS,
      BROKER_READ_ONLY,
      "The two broker routes that could lead to order placement are not called",
      "Lists only the signed-in user's own accounts and imports",
    ],
    triggers: [
      ON_OPEN,
      { type: "On demand", detail: "the user uploads a statement, runs a Gmail sync or syncs a broker account" },
    ],
    gaps: [
      "A broker sign-in can be started, but coming back to this page afterwards is not on the server yet.",
      "Reading holdings and positions from a signed-in account is not on the server yet; until then holdings come from a CAS statement.",
    ],
  },

  // ── advisor tools ──────────────────────────────────────────────────────
  {
    id: "advisor-book",
    view: "advisor",
    name: "Advisor client book",
    answerClass: PERSONAL,
    objective: "Show an advisor their whole book at a glance, who needs attention first, and the client list.",
    questions: [
      "Which clients need my attention first?",
      "Which clients are off their target allocation?",
      "Which clients hold too much in one fund or stock?",
      "Which clients stopped their SIPs recently?",
    ],
    data: [{ source: "advisor-book", need: "required", freshness: "Scored on each open" }],
    inputs: [SESSION_ADVISOR],
    services: [
      "GET /api/mfd/profiles",
      "GET /api/advisor/sip-board/summary",
      "POST /api/mfd/profiles/{profile_id}/activate",
      "POST /api/mfd/profiles/deactivate",
    ],
    outputs: [
      "Clients, AUM and the number at risk",
      "SIP totals for the book",
      "The clients that need attention, ranked by priority",
      "The client list: each client opens in the Copilot as that client, or in Client 360 without switching",
    ],
    guardrails: [NOT_ADVICE, NO_ORDERS, CLIENT_DATA, "While a client is open, the page says whose portfolio every screen and answer is about"],
    triggers: [ON_OPEN],
    gaps: [
      "Model portfolios are not stored, and no client is linked to one.",
      "Client report drafts: a request for a client's review pack can be taken, but nothing writes the document, so there are no drafts to list or approve.",
    ],
  },
  {
    id: "advisor-workspace",
    view: "advisor/workspace",
    name: "Advisor workspace",
    answerClass: PERSONAL,
    objective: "Give an advisor their working lists for the day: who to call, where the money is, who is lagging and who needs rebalancing.",
    questions: [
      "Who should I call today?",
      "Which clients are lagging the benchmark?",
      "Which clients need rebalancing?",
      "Which clients hold the most assets?",
    ],
    data: [{ source: "advisor-book", need: "required", freshness: "Scored on each open" }],
    inputs: [
      SESSION_ADVISOR,
      { field: "client", type: "name, mobile, email, PAN", fallback: "", rule: "typed when adding a client" },
    ],
    services: [
      "GET /api/mfd/profiles",
      "GET /api/advisor/today",
      "GET /api/advisor/aum",
      "GET /api/advisor/underperformers",
      "GET /api/advisor/rebalance",
      "POST /api/mfd/profiles",
      "DELETE /api/mfd/profiles/{profile_id}",
      "POST /api/mfd/profiles/{profile_id}/activate",
      "POST /api/mfd/profiles/{profile_id}/upload-cas",
      "POST /api/index/refresh",
    ],
    outputs: [
      "Today's calls, sorted by priority",
      "The AUM leaderboard",
      "Underperformers against a benchmark",
      "Rebalance opportunities",
      "The client table, with search, add and remove",
    ],
    guardrails: [NOT_ADVICE, NO_ORDERS, CLIENT_DATA],
    triggers: [ON_OPEN],
    gaps: [],
  },
  {
    id: "client-360",
    view: "advisor/client-360",
    name: "Client 360",
    answerClass: PERSONAL,
    objective: "Give an advisor one client's whole picture before a conversation: scores, the main issue, what needs attention and what is on file.",
    questions: [
      "How healthy is this client's portfolio?",
      "What is this client's main issue?",
      "What needs attention for this client now?",
      "Which statements and notes do we hold for this client?",
    ],
    data: [
      { source: "advisor-book", need: "required", freshness: "Scored on each open" },
      { source: "client-records", need: "required" },
    ],
    inputs: [
      SESSION_ADVISOR,
      { field: "client", type: "profile id", fallback: "", rule: "one of the advisor's clients, named in the address" },
    ],
    services: [
      "GET /api/mfd/profiles",
      "GET /api/mfd/profiles/{profile_id}/needs-attention",
      "GET /api/mfd/profiles/{profile_id}/portfolio-trend",
      "GET /api/mfd/profiles/{profile_id}/tax-summary",
      "GET /api/portfolio/cas-snapshots",
      "GET /api/mfd/profiles/{profile_id}/cas-invites",
      "GET /api/mfd/profiles/{profile_id}/cas-uploads",
      "GET /api/mfd/profiles/{profile_id}/notes",
      "GET /api/mfd/profiles/{profile_id}/holdings/export",
    ],
    outputs: [
      "Who the client is, with health and other scores, the top issue and the summary",
      "What needs attention",
      "Value and recent purchases, and unrealised gains",
      "Portfolio history, and the statements the client has shared",
      "Notes on file, and a download of the client's holdings",
    ],
    guardrails: [NOT_ADVICE, NO_ORDERS, CLIENT_DATA, "Read only: nothing on the page changes a client's record", "A request that fails says so, instead of reading as nothing to flag"],
    triggers: [ON_OPEN],
    gaps: [
      "Writing a note, sending the client a link to share a statement, logging a call and preparing a review pack cannot be started from here.",
    ],
  },

  // ── the Copilot itself ─────────────────────────────────────────────────
  {
    id: "copilot-chat",
    view: "",
    name: "Copilot chat",
    answerClass: "Set for each answer: general or personalised research",
    objective: "Answer a question in plain language, routed to the right specialist, with the steps and sources behind the answer in view.",
    questions: [
      "What stands out in my portfolio, and what should I look at first?",
      "Which of my funds overlap most?",
      "Which stocks are breaking out on above-average volume?",
      "What changed in a company's latest quarterly results?",
    ],
    data: [
      { source: "copilot-chat", need: "required", freshness: "Live, for each question" },
      { source: "cas-holdings", need: "optional", freshness: "The latest imported statement" },
      { source: "health-signals", need: "optional" },
      { source: "plan-engine", need: "optional", freshness: "The active plan" },
      { source: "goals-risk-profile", need: "optional" },
      { source: "market-pulse", need: "optional", freshness: "Live quotes in market hours" },
      { source: "instrument-search", need: "optional" },
    ],
    inputs: [
      SESSION_USER,
      { field: "question", type: "text", fallback: "", rule: "typed, or picked from a suggested question" },
      { field: "session_id", type: "thread id", fallback: "a new thread", rule: "continues the open thread when there is one" },
    ],
    services: [
      "POST /api/chat/stream",
      "GET /api/chat/messages",
      "GET /api/chat/sessions",
      "GET /api/copilot/suggested-prompts",
      "GET /api/chat/suggest-queries",
      "GET /api/chat/instrument-search",
    ],
    outputs: [
      "The answer as text",
      "A structured result card, with its source tags and freshness",
      "Which specialist answered, and how sure the routing was",
      "The tool steps, each with how long it took",
      "Follow-up questions",
      "Your context: portfolio value, health score, statement, risk profile, goals and data feeds",
    ],
    guardrails: [
      NOT_ADVICE,
      NO_ORDERS,
      "Each answer is labelled general or personalised research, from the agent that answered",
      "The evidence panel shows only what the answer stream reported; nothing is inferred",
      "A stopped or failed answer is never labelled as done",
    ],
    triggers: [
      { type: "On demand", detail: "when the user sends a question" },
      MARKET_STRIP,
    ],
    gaps: [
      "Tool steps, routing and follow-ups are not stored, so they are missing for answers loaded from history.",
      "No endpoint lists the Copilot's tools, their contracts or how often they run.",
      "Answer depth, constraints and memory cannot be set: Settings shows them as not connected.",
    ],
  },
];

// ── derived ──────────────────────────────────────────────────────────────

const ALL_MODES: Mode[] = ["investor", "trader", "advisor"];

/** The modes whose rail shows a view. Workspace pages and the chat are in every mode. */
function personasFor(view: string): Mode[] {
  if (view === "" || WORKSPACE_NAV.some((n) => n.view === view)) return [...ALL_MODES];
  return ALL_MODES.filter((m) => allToolsNav(m).some((n) => n.view === view));
}

export const TOOL_TEMPLATES: ToolTemplate[] = SPECS.map((t) => ({ ...t, personas: personasFor(t.view) }));

export function templateById(id: string | null | undefined): ToolTemplate | undefined {
  return id ? TOOL_TEMPLATES.find((t) => t.id === id) : undefined;
}

export type TemplateGroup = Mode | "all";

export const GROUP_LABEL: Record<TemplateGroup, string> = {
  investor: "Investor",
  trader: "Trader",
  advisor: "Advisor",
  all: "All",
};

const GROUP_ORDER: TemplateGroup[] = ["investor", "trader", "advisor", "all"];

/** A tool shown in every mode is under "All"; otherwise under the mode that has it. */
function groupOf(t: ToolTemplate): TemplateGroup {
  return t.personas.length === 1 ? t.personas[0] : "all";
}

/** The templates under Investor / Trader / Advisor / All, in that order. Empty groups are left out. */
export function templatesByGroup(): Array<{ group: TemplateGroup; templates: ToolTemplate[] }> {
  return GROUP_ORDER
    .map((group) => ({ group, templates: TOOL_TEMPLATES.filter((t) => groupOf(t) === group) }))
    .filter((g) => g.templates.length > 0);
}

/** The draft a template loads: every row gets a fresh id, every data row its pool source's name. */
export function draftFromTemplate(t: ToolTemplate): ToolDraft {
  return {
    name: t.name,
    personas: [...t.personas],
    answerClass: t.answerClass,
    objective: t.objective,
    questions: [...t.questions],
    data: t.data.map((d) => {
      const source = sourceById(d.source);
      return { id: rowId(), source: source.name, need: d.need, freshness: d.freshness ?? source.freshness };
    }),
    inputs: t.inputs.map((i) => ({ id: rowId(), ...i })),
    services: [...t.services],
    outputs: [...t.outputs],
    guardrails: [...t.guardrails],
    triggers: t.triggers.map((g) => ({ id: rowId(), ...g })),
  };
}

/** The templates that draw on one pool source. */
export function templatesUsing(sourceId: string): ToolTemplate[] {
  return TOOL_TEMPLATES.filter((t) => t.data.some((d) => d.source === sourceId));
}
