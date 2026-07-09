/**
 * Blog post registry. Static, frontend-only content for the public marketing
 * blog — no backend. Add a post by appending to POSTS (newest first) and giving
 * it a `Body` component. `getPost` powers the /blog/:slug reader.
 */
import type { ComponentType } from "react";
import RetailLossesArticle from "./RetailLossesArticle";
import MFBestPracticesArticle from "./MFBestPracticesArticle";
import HowWeUseClaudeArticle from "./HowWeUseClaudeArticle";
import SelfHealingArticle from "./SelfHealingArticle";
import TypesOfFundsArticle from "./TypesOfFundsArticle";
import SipVsLumpsumArticle from "./SipVsLumpsumArticle";
import TaxHarvestingArticle from "./TaxHarvestingArticle";
import DirectVsRegularArticle from "./DirectVsRegularArticle";
import CopilotTourArticle from "./CopilotTourArticle";

export type BlogPost = {
  slug: string;
  title: string;
  excerpt: string;
  category: string;
  readMins: number;
  dateLabel: string;
  Body: ComponentType;
};

export const POSTS: BlogPost[] = [
  {
    slug: "nivesh-copilot-2-minute-tour",
    title: "Watch: a 2-minute tour of Nivesh Copilot",
    excerpt:
      "See the full advisory loop end to end — ask what to fix first, compare options, get a ranked verdict, and approve. Investor and advisor, desktop and mobile, in two minutes.",
    category: "Product tour",
    readMins: 2,
    dateLabel: "July 2026",
    Body: CopilotTourArticle,
  },
  {
    slug: "types-of-mutual-funds-india",
    title: "Types of mutual funds in India — a plain-English guide",
    excerpt:
      "Equity, debt, hybrid, index, ELSS — there are really just a few families. Here's the map, and how to pick the one that fits your goal and timeline.",
    category: "Investor education",
    readMins: 6,
    dateLabel: "July 2026",
    Body: TypesOfFundsArticle,
  },
  {
    slug: "sip-vs-lumpsum",
    title: "SIP vs lump sum — which one's actually right for you?",
    excerpt:
      "Got a bonus and not sure whether to drip it in or dump it in? The honest breakdown of when each wins — plus the middle path most people miss.",
    category: "Investor education",
    readMins: 5,
    dateLabel: "July 2026",
    Body: SipVsLumpsumArticle,
  },
  {
    slug: "tax-harvesting-mutual-funds",
    title: "Tax harvesting in mutual funds — a legal way to cut your tax",
    excerpt:
      "You get ₹1.25 lakh of long-term equity gains tax-free every year. Skip it and you lose it. How harvesting gains (and losses) quietly lowers your tax bill.",
    category: "Investor education",
    readMins: 5,
    dateLabel: "July 2026",
    Body: TaxHarvestingArticle,
  },
  {
    slug: "direct-vs-regular-mutual-funds",
    title: "Direct vs regular mutual funds — what it really costs you",
    excerpt:
      "Same fund, same manager — but a Regular plan quietly pays a commission every year. Over 20 years that ~1% can cost you ₹16 lakh. The maths, and how to switch.",
    category: "Investor education",
    readMins: 5,
    dateLabel: "July 2026",
    Body: DirectVsRegularArticle,
  },
  {
    slug: "self-healing-software-autonomous-fixes",
    title: "Self-healing software: how our systems fix their own bugs — and stop at a pull request",
    excerpt:
      "An error in production becomes a triaged issue, a root-cause analysis, an auto-fix and an automated test — then it stops at a pull request for a human to merge. Inside our autonomous fix-it lifecycle and the Phoenix control plane.",
    category: "Engineering",
    readMins: 7,
    dateLabel: "July 2026",
    Body: SelfHealingArticle,
  },
  {
    slug: "how-we-build-with-claude",
    title: "How we build with Claude: an AI engineering team that can’t fake “done”",
    excerpt:
      "We don't treat Claude as autocomplete — we treat it as a team of disciplined engineers that loads the same context every session and is deterministically blocked from claiming “done” without real evidence. The six-part system, explained.",
    category: "Engineering",
    readMins: 6,
    dateLabel: "July 2026",
    Body: HowWeUseClaudeArticle,
  },
  {
    slug: "mutual-fund-investing-best-practices",
    title: "Mutual fund investing: 7 best practices that actually build wealth",
    excerpt:
      "SIPs you don't stop, the right asset allocation, Direct plans over Regular, and the discipline to stay put — the handful of habits that separate investors who compound from those who leak returns.",
    category: "Investor education",
    readMins: 6,
    dateLabel: "July 2026",
    Body: MFBestPracticesArticle,
  },
  {
    slug: "why-indian-retail-investors-lose-money",
    title: "Why Indian retail investors lose money — and how Nivesh Copilot helps",
    excerpt:
      "93% of F&O traders and 7 in 10 intraday traders lose money, while half of mutual-fund investors quit within two years. Here's the data — and the fix.",
    category: "Investor education",
    readMins: 4,
    dateLabel: "July 2026",
    Body: RetailLossesArticle,
  },
];

export function getPost(slug: string | undefined): BlogPost | undefined {
  return POSTS.find((p) => p.slug === slug);
}
