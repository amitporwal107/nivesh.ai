// Persona × question catalog derived from docs/COPILOT_PROMPT_CATALOG.md.
// Hero (tier=primary), compact secondaries, and tiny advanced chips — keyed by persona id.
//
// Cat codes from catalog:
//   PH = health, PA = performance, RD = risk, TX = tax, GP = goal

const CAT_MAP = { PH: "health", PA: "performance", RD: "risk", TX: "tax", GP: "goal" };

function mk(label, cat, tier = "secondary") {
  return { label, category: CAT_MAP[cat], tier };
}

export const PROMPT_CATALOG = {
  salaried_beginner: {
    primary: mk("Is my portfolio well diversified?", "RD", "primary"),
    secondary: [
      mk("Am I taking too much risk?", "RD"),
      mk("Which mutual funds are underperforming?", "PA"),
      mk("Should I sell any of my stocks or funds?", "PH"),
    ],
    advanced: [
      mk("How much return am I making vs FD?", "PA", "advanced"),
      mk("How much should I invest every month?", "GP", "advanced"),
      mk("Which funds are best for long-term wealth?", "PH", "advanced"),
      mk("Stocks or mutual funds for me?", "GP", "advanced"),
      mk("How do I save tax under 80C?", "TX", "advanced"),
      mk("Corpus needed for retirement?", "GP", "advanced"),
    ],
  },
  mf_focused: {
    primary: mk("Do you have too many mutual funds?", "PH", "primary"),
    secondary: [
      mk("Are any of my funds overlapping significantly?", "RD"),
      mk("Which funds are dragging down performance?", "PA"),
      mk("Is my SIP allocation optimal?", "GP"),
    ],
    advanced: [
      mk("Should I switch to direct plans?", "TX", "advanced"),
      mk("Which funds are best for SIP?", "PH", "advanced"),
      mk("Large-cap vs flexi-cap vs mid-cap?", "RD", "advanced"),
      mk("Equity allocation for my age?", "RD", "advanced"),
      mk("Continue SIPs in a market correction?", "GP", "advanced"),
      mk("How do expense ratios eat returns?", "PA", "advanced"),
    ],
  },
  direct_equity: {
    primary: mk("Which stocks are overvalued?", "PA", "primary"),
    secondary: [
      mk("Which stocks have weak fundamentals?", "PH"),
      mk("What is my concentration risk?", "RD"),
      mk("Top return contributors?", "PA"),
    ],
    advanced: [
      mk("Should I rebalance my holdings?", "PH", "advanced"),
      mk("Which sectors are likely to outperform?", "PA", "advanced"),
      mk("How do I identify undervalued stocks?", "RD", "advanced"),
      mk("Valuation metrics that matter most?", "PA", "advanced"),
      mk("Building a long-term stock portfolio?", "GP", "advanced"),
      mk("How much cash should I keep?", "RD", "advanced"),
    ],
  },
  hni: {
    primary: mk("Is my wealth allocation optimal?", "RD", "primary"),
    secondary: [
      mk("Where is concentration risk highest?", "RD"),
      mk("How tax-efficient is my portfolio?", "TX"),
      mk("Which assets need rebalancing?", "PH"),
    ],
    advanced: [
      mk("What is my downside in a market crash?", "RD", "advanced"),
      mk("Allocation across equity, debt, gold, international?", "RD", "advanced"),
      mk("Best tax-saving strategies?", "TX", "advanced"),
      mk("Should I use PMS or AIFs?", "PH", "advanced"),
      mk("Wealth preservation across generations?", "GP", "advanced"),
      mk("How should I structure estate planning?", "GP", "advanced"),
    ],
  },
  retirement_planner: {
    primary: mk("Will my investments be sufficient for retirement?", "GP", "primary"),
    secondary: [
      mk("Is my debt allocation adequate?", "RD"),
      mk("How much monthly income can this generate?", "GP"),
      mk("Probability of running out of money?", "GP"),
    ],
    advanced: [
      mk("Which assets should I shift to safer investments?", "PH", "advanced"),
      mk("How much corpus do I need?", "GP", "advanced"),
      mk("How should retirees invest?", "RD", "advanced"),
      mk("What withdrawal rate is safe?", "GP", "advanced"),
      mk("Protect against inflation?", "GP", "advanced"),
      mk("Should I invest in annuities?", "GP", "advanced"),
    ],
  },
  parents_for_kids: {
    primary: mk("Is my child education corpus on track?", "GP", "primary"),
    secondary: [
      mk("Are current SIPs sufficient?", "GP"),
      mk("What return assumptions are realistic?", "GP"),
      mk("How much shortfall exists?", "GP"),
    ],
    advanced: [
      mk("Which investments to earmark for education?", "PH", "advanced"),
      mk("Higher-education cost estimate?", "GP", "advanced"),
      mk("Equity funds for education planning?", "GP", "advanced"),
      mk("Goal only 5 years away — what now?", "GP", "advanced"),
      mk("Protect the goal with insurance?", "GP", "advanced"),
      mk("Monthly investment to close the gap?", "GP", "advanced"),
    ],
  },
  tax_conscious: {
    primary: mk("What are my unrealized capital gains?", "TX", "primary"),
    secondary: [
      mk("Which holdings can be sold for tax harvesting?", "TX"),
      mk("Which assets generate tax inefficiency?", "TX"),
      mk("Tax cost of rebalancing today?", "TX"),
    ],
    advanced: [
      mk("Hold or sell before FY end?", "TX", "advanced"),
      mk("How does capital gains tax work?", "TX", "advanced"),
      mk("What is tax-loss harvesting?", "TX", "advanced"),
      mk("Most tax-efficient investments?", "TX", "advanced"),
      mk("Growth or IDCW option?", "TX", "advanced"),
      mk("Minimize taxes legally?", "TX", "advanced"),
    ],
  },
  conservative: {
    primary: mk("Is my portfolio too aggressive?", "RD", "primary"),
    secondary: [
      mk("How much downside risk do I face?", "RD"),
      mk("Allocation to debt and fixed income?", "RD"),
      mk("Which holdings are volatile?", "RD"),
    ],
    advanced: [
      mk("Better returns than FD with low risk?", "PA", "advanced"),
      mk("What are safe investment options?", "RD", "advanced"),
      mk("Which debt funds are suitable?", "PH", "advanced"),
      mk("How much equity should I own?", "RD", "advanced"),
      mk("Is gold a safe hedge?", "RD", "advanced"),
      mk("How do I preserve capital?", "GP", "advanced"),
    ],
  },
  active_trader: {
    primary: mk("Best returns this quarter?", "PA", "primary"),
    secondary: [
      mk("Where am I overexposed?", "RD"),
      mk("Realized vs unrealized P&L?", "PA"),
      mk("Which trades are consistently losing?", "PA"),
    ],
    advanced: [
      mk("Which sectors show momentum?", "PA", "advanced"),
      mk("Effective swing-trading setup?", "PA", "advanced"),
      mk("How do I manage risk?", "RD", "advanced"),
      mk("What position size should I use?", "RD", "advanced"),
      mk("Improve trading discipline?", "PA", "advanced"),
      mk("Set stop-losses for swing trades?", "RD", "advanced"),
    ],
  },
  nri_global: {
    primary: mk("How much of my portfolio is India-focused?", "RD", "primary"),
    secondary: [
      mk("Do I have adequate global diversification?", "RD"),
      mk("What are my currency risks?", "RD"),
      mk("NRI tax inefficiency?", "TX"),
    ],
    advanced: [
      mk("Rebalance between geographies?", "PH", "advanced"),
      mk("Invest in India or abroad?", "PA", "advanced"),
      mk("How do tax treaties work?", "TX", "advanced"),
      mk("Which international ETFs suit me?", "PH", "advanced"),
      mk("Currency movements vs returns?", "PA", "advanced"),
      mk("Best global diversification allocation?", "RD", "advanced"),
    ],
  },
  universal: {
    primary: mk("Is my portfolio healthy?", "PH", "primary"),
    secondary: [
      mk("Am I properly diversified?", "RD"),
      mk("Which investments should I sell?", "PH"),
      mk("How much risk am I taking?", "RD"),
    ],
    advanced: [
      mk("What is my expected long-term return?", "PA", "advanced"),
      mk("What happens if markets fall 20%?", "RD", "advanced"),
      mk("How can I reduce taxes?", "TX", "advanced"),
      mk("What should I buy next?", "PH", "advanced"),
      mk("Am I on track to meet my goals?", "GP", "advanced"),
      mk("Compare with recommended allocations?", "RD", "advanced"),
    ],
  },
};

export function getCatalogFor(personaId) {
  return PROMPT_CATALOG[personaId] || PROMPT_CATALOG.universal;
}

export function countsByCategory(catalog) {
  const all = [catalog.primary, ...catalog.secondary, ...catalog.advanced];
  const out = { all: all.length, health: 0, performance: 0, risk: 0, tax: 0, goal: 0 };
  all.forEach((p) => {
    if (out[p.category] != null) out[p.category]++;
  });
  return out;
}
