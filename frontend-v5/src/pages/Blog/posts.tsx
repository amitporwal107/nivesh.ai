/**
 * Blog post registry. Static, frontend-only content for the public marketing
 * blog — no backend. Add a post by appending to POSTS (newest first) and giving
 * it a `Body` component. `getPost` powers the /blog/:slug reader.
 */
import type { ComponentType } from "react";
import RetailLossesArticle from "./RetailLossesArticle";

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
