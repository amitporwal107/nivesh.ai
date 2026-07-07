/**
 * Blog post registry. Static, frontend-only content for the public marketing
 * blog — no backend. Add a post by appending to POSTS (newest first) and giving
 * it a `Body` component. `getPost` powers the /blog/:slug reader.
 */
import type { ComponentType } from "react";
import RetailLossesArticle from "./RetailLossesArticle";
import MFBestPracticesArticle from "./MFBestPracticesArticle";

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
