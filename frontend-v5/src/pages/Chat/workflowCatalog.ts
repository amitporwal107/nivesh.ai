/**
 * workflowCatalog — single source of truth for the copilot chat's workflow
 * tiles. Replaces the triplicated investor / duplicated advisor definitions
 * that used to live across CopilotOnboarding + the /copilot tour sections, so
 * the persona list, the guided-tour stepper and the prompt each tile sends can
 * never drift.
 *
 * `prompt` is the routing-safe question the tile sends to the real copilot
 * (submitMessage). `stages` is the tour's ASK → ANALYZE → DECIDE → ACT copy
 * shown in the guided-tour tile (illustrative until a live feed backs it —
 * see the phased plan; investor headline metrics are prefilled live where a
 * hook exists). `tag` is the compact right-aligned label on the list row.
 */
export type WorkflowStage = { label: "ASK" | "ANALYZE" | "DECIDE" | "ACT"; text: string };

export type Workflow = {
  key: string;
  n: string;
  title: string;
  sub: string;
  prompt: string;
  tag: string;
  /** which live metric (if any) prefills the list row / tile headline */
  metric?: "health" | "overlap" | "tax" | "sips" | "goal" | "value"
    | "aum" | "atrisk" | "reviews" | "harvest";
  stages: WorkflowStage[];
};

export const INVESTOR_WORKFLOWS: Workflow[] = [
  {
    key: "health", n: "01", title: "Portfolio health review", sub: "Health agent · score H",
    prompt: "What's the one thing I should fix first?", tag: "H", metric: "health",
    stages: [
      { label: "ASK", text: "What's the one thing I should fix first?" },
      { label: "ANALYZE", text: "Health score, concentration and the biggest ₹ leaks." },
      { label: "DECIDE", text: "Top 3 fixes, ranked by rupee impact." },
      { label: "ACT", text: "Approve the #1 fix — nothing runs without you." },
    ],
  },
  {
    key: "fund", n: "02", title: "Fund deep-dive", sub: "Quality agent · score Q",
    prompt: "Is HDFC Flexi Cap still worth holding?", tag: "Q",
    stages: [
      { label: "ASK", text: "Is this fund still worth holding?" },
      { label: "ANALYZE", text: "Quartile quality, fees trend, red-flag events." },
      { label: "DECIDE", text: "Hold / trim / switch verdict." },
      { label: "ACT", text: "Set a review alert or switch." },
    ],
  },
  {
    key: "newmoney", n: "03", title: "Where to invest new money", sub: "Add agent · score A",
    prompt: "Where should I put ₹2L this month?", tag: "A",
    stages: [
      { label: "ASK", text: "Where should I put fresh money?" },
      { label: "ANALYZE", text: "Which sleeve you're light on vs your target." },
      { label: "DECIDE", text: "A ranked, matched split." },
      { label: "ACT", text: "Place the buys." },
    ],
  },
  {
    key: "sell", n: "04", title: "Should I sell?", sub: "Exit agent · score E",
    prompt: "Should I exit my IT sector fund?", tag: "E",
    stages: [
      { label: "ASK", text: "Should I exit this holding?" },
      { label: "ANALYZE", text: "Exit signal, momentum and tax on exit." },
      { label: "DECIDE", text: "Full / partial / hold verdict." },
      { label: "ACT", text: "Redeem and redeploy." },
    ],
  },
  {
    key: "tax", n: "05", title: "Tax-loss harvesting", sub: "Tax agent · deadline Mar 31",
    prompt: "Cut my tax before March 31.", tag: "TAX", metric: "tax",
    stages: [
      { label: "ASK", text: "Cut my tax before the deadline." },
      { label: "ANALYZE", text: "Harvestable losses across your holdings." },
      { label: "DECIDE", text: "Book both, repurchase to stay invested." },
      { label: "ACT", text: "Approve the harvest." },
    ],
  },
  {
    key: "goal", n: "06", title: "Goal on track?", sub: "Goals agent · projection",
    prompt: "Am I on track to retire at 55 with ₹5Cr?", tag: "GOAL", metric: "goal",
    stages: [
      { label: "ASK", text: "Am I on track for my goal?" },
      { label: "ANALYZE", text: "Projected corpus vs target." },
      { label: "DECIDE", text: "Ways to close the gap." },
      { label: "ACT", text: "Step up the SIP." },
    ],
  },
  {
    key: "rebalance", n: "07", title: "Rebalance my mix", sub: "Allocation agent · drift",
    prompt: "Bring me back to a moderate allocation.", tag: "REBAL",
    stages: [
      { label: "ASK", text: "Bring me back to my target mix." },
      { label: "ANALYZE", text: "How far you've drifted." },
      { label: "DECIDE", text: "The moves that reset it." },
      { label: "ACT", text: "Place the rebalancing orders." },
    ],
  },
  {
    key: "overlap", n: "08", title: "Too many funds?", sub: "Overlap agent · score Q",
    prompt: "I hold too many funds — is that too many?", tag: "OVERLAP", metric: "overlap",
    stages: [
      { label: "ASK", text: "Do I hold too many funds?" },
      { label: "ANALYZE", text: "Which funds overlap most." },
      { label: "DECIDE", text: "Merge to cut fees and clutter." },
      { label: "ACT", text: "Redeem the duplicates." },
    ],
  },
  {
    key: "sips", n: "09", title: "Optimize my SIPs", sub: "SIP agent · cashflow",
    prompt: "Are my monthly SIPs set up right?", tag: "SIP", metric: "sips",
    stages: [
      { label: "ASK", text: "Are my SIPs set up right?" },
      { label: "ANALYZE", text: "Active SIPs, overlaps and step-up room." },
      { label: "DECIDE", text: "Pause overlaps, step up with inflation." },
      { label: "ACT", text: "Update the SIPs." },
    ],
  },
  {
    key: "market", n: "10", title: "What moved today", sub: "Market agent · daily brief",
    prompt: "What happened to my portfolio today?", tag: "MKT",
    stages: [
      { label: "ASK", text: "What happened to my portfolio today?" },
      { label: "ANALYZE", text: "What dragged, what helped." },
      { label: "DECIDE", text: "Whether it changes your plan." },
      { label: "ACT", text: "Set an alert for big moves." },
    ],
  },
];

export const ADVISOR_WORKFLOWS: Workflow[] = [
  {
    key: "book", n: "A", title: "AUM & book health", sub: "AUM health agent · book level",
    prompt: "How's my book doing this quarter?", tag: "AUM", metric: "aum",
    stages: [
      { label: "ASK", text: "How's my book doing this quarter?" },
      { label: "ANALYZE", text: "AUM, net flow and book health." },
      { label: "DECIDE", text: "Which clients drag the score." },
      { label: "ACT", text: "Open the book dashboard." },
    ],
  },
  {
    key: "churn", n: "B", title: "At-risk & churn", sub: "Retention agent",
    prompt: "Which clients might leave?", tag: "RISK", metric: "atrisk",
    stages: [
      { label: "ASK", text: "Which clients might leave?" },
      { label: "ANALYZE", text: "Churn signals — redemptions, gone quiet." },
      { label: "DECIDE", text: "Who to call first, by AUM at risk." },
      { label: "ACT", text: "Build the call list." },
    ],
  },
  {
    key: "reviews", n: "C", title: "Reviews due", sub: "Review agent",
    prompt: "Who's overdue for a portfolio review?", tag: "REVIEWS", metric: "reviews",
    stages: [
      { label: "ASK", text: "Who's overdue for a review?" },
      { label: "ANALYZE", text: "Days since last review, per client." },
      { label: "DECIDE", text: "Agendas drafted for each." },
      { label: "ACT", text: "Schedule them all." },
    ],
  },
  {
    key: "bookharvest", n: "D", title: "Harvest across the book", sub: "Tax agent · Mar 31",
    prompt: "Any tax savings for my clients this FY?", tag: "TAX", metric: "harvest",
    stages: [
      { label: "ASK", text: "Any tax savings for my clients this FY?" },
      { label: "ANALYZE", text: "Harvestable losses across the book." },
      { label: "DECIDE", text: "Who to propose to, before Mar 31." },
      { label: "ACT", text: "Bulk-propose." },
    ],
  },
  {
    key: "idlecash", n: "E", title: "Idle cash to deploy", sub: "Deploy agent",
    prompt: "Which clients are sitting on cash?", tag: "CASH",
    stages: [
      { label: "ASK", text: "Which clients are sitting on cash?" },
      { label: "ANALYZE", text: "Idle balances losing to inflation." },
      { label: "DECIDE", text: "A deploy plan per client." },
      { label: "ACT", text: "Propose the plan." },
    ],
  },
  {
    key: "offmandate", n: "F", title: "Off-mandate clients", sub: "Allocation agent · drift",
    prompt: "Who's drifted from their mandate?", tag: "DRIFT",
    stages: [
      { label: "ASK", text: "Who's drifted from their mandate?" },
      { label: "ANALYZE", text: "Who's off their target mix, by how much." },
      { label: "DECIDE", text: "Who needs rebalancing." },
      { label: "ACT", text: "Rebalance in a batch." },
    ],
  },
  {
    key: "stepup", n: "G", title: "SIP step-ups", sub: "SIP agent · growth",
    prompt: "Who can step up their SIP?", tag: "STEP-UP",
    stages: [
      { label: "ASK", text: "Who can step up their SIP?" },
      { label: "ANALYZE", text: "Who can absorb a step-up on rising income." },
      { label: "DECIDE", text: "Proposed step-up per client." },
      { label: "ACT", text: "Propose to all." },
    ],
  },
  {
    key: "onboarding", n: "H", title: "Onboarding stuck", sub: "Onboarding agent",
    prompt: "Any new clients stuck in onboarding?", tag: "STUCK",
    stages: [
      { label: "ASK", text: "Any new clients stuck in onboarding?" },
      { label: "ANALYZE", text: "Who's stalled — KYC, mandate, unfunded." },
      { label: "DECIDE", text: "What each one needs to finish." },
      { label: "ACT", text: "Nudge them all." },
    ],
  },
  {
    key: "suitability", n: "I", title: "Suitability & disclosures", sub: "Compliance agent · guardrail",
    prompt: "Anything I need to flag for compliance?", tag: "GUARD",
    stages: [
      { label: "ASK", text: "Anything I need to flag for compliance?" },
      { label: "ANALYZE", text: "Unsuitable holdings, disclosures due." },
      { label: "DECIDE", text: "What to review first." },
      { label: "ACT", text: "Review the flags." },
    ],
  },
];

export const workflowsFor = (isAdvisor: boolean): Workflow[] =>
  isAdvisor ? ADVISOR_WORKFLOWS : INVESTOR_WORKFLOWS;
