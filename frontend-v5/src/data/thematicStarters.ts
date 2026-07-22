/**
 * Curated thematic starter queries for the Copilot's cross-company research
 * (stocks_insights). Grouped by theme; `featured` marks the priority ("*") picks.
 * Shared by the Research page welcome card and the Stocks-Insight landing so the
 * list lives in one place.
 */
export type ThematicStarter = { q: string; featured?: boolean };

export const THEMATIC_GROUPS: { title: string; queries: ThematicStarter[] }[] = [
  {
    title: "Growth & order momentum",
    queries: [
      { q: "Biggest order wins this fortnight — by value, sector, and counterparty (govt/PSU/private)", featured: true },
      { q: "Which companies won their largest-ever order this year?" },
      { q: "Companies whose order book grew fastest per their own concall disclosures" },
      { q: "Which smallcaps entered new export markets or won first international orders?" },
    ],
  },
  {
    title: "Capex cycle — both ends of it",
    queries: [
      { q: "Major capacity expansions or new-plant announcements this quarter", featured: true },
      { q: "Whose capex is turning into revenue — plants commissioned in the last two quarters?", featured: true },
      { q: "Who deferred or shelved capex (the hidden demand warning)?" },
      { q: "Which companies announced expansion but are funding it with equity dilution?" },
    ],
  },
  {
    title: "Quality of earnings & results season",
    queries: [
      { q: "Who swung to a loss or saw profit fall despite higher revenue?", featured: true },
      { q: "Which companies beat on headline PAT only because of one-off/exceptional gains?" },
      { q: "Who flagged margin pressure or input-cost inflation in their concalls this quarter?", featured: true },
      { q: "Which companies missed or lowered their own previously stated guidance?" },
      { q: "Results accompanied by auditor qualifications or emphasis-of-matter this season" },
    ],
  },
  {
    title: "Stress & governance radar",
    queries: [
      { q: "Which companies are showing combined stress signals — pledge increases + rating downgrades + auditor changes + delayed filings?", featured: true },
      { q: "Governance red flags this month: auditor resignations, abrupt CFO exits, defeated AGM resolutions", featured: true },
      { q: "Fresh insolvency petitions or debt-default disclosures across the market" },
      { q: 'Which companies moved to "Issuer Not Cooperating" rating status?' },
      { q: "Who's under new exchange surveillance (ASM/GSM) this week?" },
    ],
  },
  {
    title: "Ownership & conviction signals",
    queries: [
      { q: "Where are promoters buying from the open market or releasing pledges?", featured: true },
      { q: "Where are promoters selling or pledging more?" },
      { q: "Which companies had preferential allotments to promoters at near-floor pricing?" },
      { q: "Where did FIIs/DIIs meaningfully raise stake per the latest shareholding patterns?" },
    ],
  },
  {
    title: "Capital returns & balance sheet",
    queries: [
      { q: "Dividends raised, cut, or specials declared vs last year", featured: true },
      { q: "Buybacks announced this quarter — size, premium, promoter participation" },
      { q: "Who's deleveraging — debt prepayments and improving leverage commentary?", featured: true },
    ],
  },
  {
    title: "Theme & technology exposure",
    queries: [
      { q: "Which companies put hard numbers on AI/GenAI revenue — and who declines to disclose?", featured: true },
      { q: "AI data-centre and compute-infrastructure buildout — who's investing, at what scale?" },
      { q: "Which companies are manufacturing under PLI schemes or citing China+1 order flows?" },
      { q: "Renewable/green-energy capacity announcements and commissioning" },
    ],
  },
  {
    title: "Sector-regulatory pulse",
    queries: [
      { q: "USFDA scorecard — clean EIRs vs 483s vs Warning Letters, by company and facility", featured: true },
      { q: "Which IT companies are cautious vs constructive on FY27 demand?" },
      { q: "M&A pipeline board — announced → CCI → NCLT → completed, with stage dates", featured: true },
      { q: "Which companies are directly named in new anti-dumping/tariff actions?" },
    ],
  },
];

/** Flat, ordered list carrying the theme label per item — for 5-at-a-time reveal. */
export const THEMATIC_STARTERS: { q: string; featured?: boolean; category: string }[] =
  THEMATIC_GROUPS.flatMap((g) => g.queries.map((s) => ({ ...s, category: g.title })));

/** Reveal step for the "show more" control. */
export const STARTERS_PAGE = 5;
