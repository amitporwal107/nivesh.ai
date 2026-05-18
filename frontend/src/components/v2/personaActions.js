/**
 * personaActions.js — Quick-action registry keyed by persona.
 *
 * Each persona gets 4 high-signal actions tailored to its goals.
 * Falls back to retail_investor when persona is unknown.
 * Icons are lucide names resolved in V2HomeScreen.
 */
import {
  TrendingUp, BarChart3, RefreshCw, Shield, FileText, Search,
  Target, Briefcase, ArrowUpRight, AlertTriangle, Bell, Zap,
  Receipt, Globe, BookOpen, Sprout, Activity, Users,
  Landmark, Crosshair, Timer, Wallet, PieChart, LineChart,
} from "lucide-react";

// Map screen IDs that exist in V2Layout — keep in sync if routes change
const SCR = {
  copilot:   "copilot",
  portfolio: "portfolio",
  insights:  "insights",
  markets:   "markets",
  goals:     "goals",
  plans:     "plan_board",
  strategy:  "strategy",
};

const ACTIONS = {
  retail_investor: [
    { label: "AI Copilot Chat",      icon: TrendingUp,  screen: SCR.copilot,   color: "indigo",  desc: "Ask anything about your portfolio" },
    { label: "Portfolio Analysis",   icon: Briefcase,   screen: SCR.portfolio, color: "emerald", desc: "Holdings, returns, allocation" },
    { label: "Run Rebalance",        icon: RefreshCw,   screen: SCR.plans,     color: "violet",  desc: "Target vs actual allocation" },
    { label: "Set Financial Goal",   icon: Target,      screen: SCR.goals,     color: "rose",    desc: "Plan for retirement, home, etc." },
  ],

  mutual_fund_investor: [
    { label: "Compare My Funds",     icon: BarChart3,   screen: SCR.portfolio, color: "blue",    desc: "Rolling returns · expense · alpha" },
    { label: "Detect Fund Overlap",  icon: Search,      screen: SCR.insights,  color: "violet",  desc: "Are you paying twice for the same stocks?" },
    { label: "SIP Top-up Plan",      icon: Zap,         screen: SCR.goals,     color: "emerald", desc: "Project growth with higher SIP" },
    { label: "Switch to Direct",     icon: RefreshCw,   screen: SCR.plans,     color: "amber",   desc: "Save 0.6%+ p.a. on expense ratio" },
  ],

  stock_investor: [
    { label: "Stock Quality Scan",   icon: Activity,    screen: SCR.portfolio, color: "violet",  desc: "Quality · health · exit scores" },
    { label: "Sector Exposure",      icon: PieChart,    screen: SCR.insights,  color: "indigo",  desc: "Concentration · over/underweight" },
    { label: "Valuation Check",      icon: LineChart,   screen: SCR.copilot,   color: "amber",   desc: "Which stocks are overvalued?" },
    { label: "Drawdown Analysis",    icon: TrendingUp,  screen: SCR.insights,  color: "rose",    desc: "Max drawdown · recovery time" },
  ],

  swing_trader: [
    { label: "Trade Setup Scanner",  icon: Zap,         screen: SCR.markets,   color: "amber",   desc: "Breakouts · trends · momentum" },
    { label: "Market Regime",        icon: Activity,    screen: SCR.markets,   color: "indigo",  desc: "Bullish · bearish · sideways" },
    { label: "Position Sizing",      icon: Target,      screen: SCR.copilot,   color: "emerald", desc: "Risk per trade · stop loss" },
    { label: "Price Alerts",         icon: Bell,        screen: SCR.copilot,   color: "rose",    desc: "Watchlist triggers" },
  ],

  intraday_trader: [
    { label: "Opening Gap Dashboard",icon: Timer,       screen: SCR.markets,   color: "orange",  desc: "Gap up/down scanner" },
    { label: "Volume Spike Scanner", icon: BarChart3,   screen: SCR.markets,   color: "amber",   desc: "Unusual volume signals" },
    { label: "Market Regime",        icon: Activity,    screen: SCR.markets,   color: "indigo",  desc: "Today's regime + sectors" },
    { label: "Risk Calculator",      icon: AlertTriangle,screen: SCR.copilot,  color: "rose",    desc: "Daily loss limit · sizing" },
  ],

  options_trader: [
    { label: "Greeks Dashboard",     icon: Crosshair,   screen: SCR.markets,   color: "rose",    desc: "Delta · gamma · vega · theta" },
    { label: "IV Rank Monitor",      icon: BarChart3,   screen: SCR.markets,   color: "amber",   desc: "Implied vol percentile" },
    { label: "Payoff Analyzer",      icon: LineChart,   screen: SCR.copilot,   color: "violet",  desc: "Strategy P&L visualisation" },
    { label: "Margin Monitor",       icon: AlertTriangle,screen: SCR.portfolio,color: "indigo",  desc: "Margin used · available" },
  ],

  mfd_advisor: [
    { label: "Client Drift Alerts",  icon: AlertTriangle,screen: SCR.insights, color: "rose",    desc: "Portfolios above 10% drift" },
    { label: "Generate Proposal",    icon: FileText,    screen: SCR.copilot,   color: "violet",  desc: "Client-ready fund proposal" },
    { label: "Cross-Sell Radar",     icon: Search,      screen: SCR.insights,  color: "emerald", desc: "SIP top-ups · debt allocation" },
    { label: "Suitability Monitor",  icon: Shield,      screen: SCR.insights,  color: "indigo",  desc: "Risk-profile mismatches" },
  ],

  hni_investor: [
    { label: "Wealth Stress Test",   icon: AlertTriangle,screen: SCR.insights, color: "rose",    desc: "2008 crash · rate shock" },
    { label: "Tax Optimization",     icon: Receipt,     screen: SCR.copilot,   color: "emerald", desc: "LTCG · harvest · 80C" },
    { label: "Concentration Risk",   icon: PieChart,    screen: SCR.insights,  color: "amber",   desc: "Top-5 holding exposure" },
    { label: "Family Wealth View",   icon: Users,       screen: SCR.portfolio, color: "indigo",  desc: "Multi-portfolio rollup" },
  ],

  retirement_planner: [
    { label: "Retirement Tracker",   icon: Landmark,    screen: SCR.goals,     color: "teal",    desc: "Corpus progress · gap" },
    { label: "Safe Withdrawal Plan", icon: Wallet,      screen: SCR.copilot,   color: "emerald", desc: "4% rule · sustainability" },
    { label: "Shift to Debt",        icon: Shield,      screen: SCR.plans,     color: "blue",    desc: "Reduce equity volatility" },
    { label: "Probability of Success",icon: Target,     screen: SCR.copilot,   color: "violet",  desc: "Monte Carlo on your plan" },
  ],

  tax_saver: [
    { label: "Tax Harvest",          icon: Receipt,     screen: SCR.insights,  color: "emerald", desc: "Realize losses to offset gains" },
    { label: "80C Utilization",      icon: Shield,      screen: SCR.copilot,   color: "blue",    desc: "How much room left this FY?" },
    { label: "LTCG / STCG Summary",  icon: BarChart3,   screen: SCR.insights,  color: "amber",   desc: "Realized gains this year" },
    { label: "ELSS Recommendations", icon: Zap,         screen: SCR.copilot,   color: "violet",  desc: "Best ELSS funds right now" },
  ],

  beginner_investor: [
    { label: "Start My First SIP",   icon: Sprout,      screen: SCR.copilot,   color: "emerald", desc: "Pick a fund · set amount" },
    { label: "Beginner's Guide",     icon: BookOpen,    screen: SCR.copilot,   color: "blue",    desc: "Mutual funds · SIPs · risk" },
    { label: "Build Emergency Fund", icon: Shield,      screen: SCR.copilot,   color: "amber",   desc: "How much · where to park" },
    { label: "Set Your Goal",        icon: Target,      screen: SCR.goals,     color: "violet",  desc: "What are you investing for?" },
  ],

  nri_investor: [
    { label: "Currency Exposure",    icon: Globe,       screen: SCR.insights,  color: "sky",     desc: "INR vs USD · hedge ratio" },
    { label: "Repatriation Tracker", icon: ArrowUpRight,screen: SCR.portfolio, color: "emerald", desc: "Repatriable vs non-repatriable" },
    { label: "Compliance Checklist", icon: FileText,    screen: SCR.copilot,   color: "amber",   desc: "FEMA · TDS · tax filing" },
    { label: "AI Copilot Chat",      icon: TrendingUp,  screen: SCR.copilot,   color: "indigo",  desc: "Ask anything about NRI investing" },
  ],
};

export function getPersonaActions(personaKey) {
  return ACTIONS[personaKey] || ACTIONS.retail_investor;
}

// Persona-specific hero greeting headline and AI summary template
const HEADLINES = {
  retail_investor:      { title: "Your Wealth Cockpit",         tagline: "Holdings, health, and what to do next." },
  mutual_fund_investor: { title: "Fund Intelligence",           tagline: "Optimize SIPs, overlap, and expense leak." },
  stock_investor:       { title: "Equity Command Center",       tagline: "Quality · valuation · sector exposure." },
  swing_trader:         { title: "Trade Cockpit",               tagline: "Setups, regime, and position sizing." },
  intraday_trader:      { title: "Intraday War Room",           tagline: "Regime · scanners · risk per trade." },
  options_trader:       { title: "Options Greeks Cockpit",      tagline: "Delta · IV · margin · payoff." },
  mfd_advisor:          { title: "Advisor Command Center",      tagline: "Clients · drift · proposals · suitability." },
  hni_investor:         { title: "Private Wealth Cockpit",      tagline: "Preserve · compound · optimize tax." },
  retirement_planner:   { title: "Retirement Path",             tagline: "Corpus progress and withdrawal safety." },
  tax_saver:            { title: "Tax Optimization Hub",        tagline: "Harvest · 80C · realized gains." },
  beginner_investor:    { title: "Your First Step",             tagline: "Build the foundation, one SIP at a time." },
  nri_investor:         { title: "NRI Investment Hub",          tagline: "Currency · compliance · repatriation." },
};

export function getPersonaHeadline(personaKey) {
  return HEADLINES[personaKey] || HEADLINES.retail_investor;
}
