/**
 * Smart trading desk · Market intelligence — the event list's data.
 *
 *   GET /api/filings/feed?days=&category=&sort=&limit=   classified NSE / BSE filings (backend/routes/filings.py, filings_feed)
 *
 * The route takes ONE `category` (an exact match on the classifier's
 * event_category). A chip that groups several categories therefore makes one
 * request per category and merges the rows here, in the route's own order
 * (material: high impact first, then newest; latest: newest first). Without a
 * category the route leaves out `regulatory` and `other`; `category=regulatory`
 * is the only way to list regulatory filings. The query keys are the same as
 * useFilingsFeed (screens/markets/hooks.ts), so both share one cache.
 */
import { useQueries } from "@tanstack/react-query";
import { filingsService, type FeedParams, type FeedResp, type FilingRow } from "@/services/adapters/filings.adapter";
import type { Tone } from "../../components/ui";

/** The classifier's window is 30 days; a trading desk reads the last week. */
export const FEED_DAYS = 7;
/** Rows per request: one category on its own, or each category of a group. */
const LIMIT_SINGLE = 40;
const LIMIT_GROUPED = 20;

export type FeedSort = "material" | "latest";
export type IntelChip = "all" | "results" | "orders" | "corporate" | "regulatory" | "flows";

export interface ChipDef {
  key: IntelChip;
  label: string;
  /** The categories the chip reads; [undefined] = no category (the route's default mix). Empty for FII / DII. */
  categories: Array<string | undefined>;
  tone: Tone;
}

/** The design's chips, mapped to the classifier's categories (backend: nidp.corporate_announcements.event_category). */
export const INTEL_CHIPS: ChipDef[] = [
  { key: "all", label: "All", categories: [undefined], tone: "ink" },
  { key: "results", label: "Results", categories: ["earnings"], tone: "indigo" },
  { key: "orders", label: "Orders & deals", categories: ["orders", "mna"], tone: "mint" },
  { key: "corporate", label: "Corporate", categories: ["capex", "management", "dividend", "buyback", "qip", "rating", "litigation"], tone: "amber" },
  { key: "regulatory", label: "Regulatory", categories: ["regulatory"], tone: "ink" },
  { key: "flows", label: "FII / DII", categories: [], tone: "ink" },
];

const CATEGORY_LABEL: Record<string, string> = {
  earnings: "Results",
  orders: "Order",
  mna: "M&A",
  capex: "Capex",
  management: "Management",
  dividend: "Dividend",
  buyback: "Buyback",
  qip: "QIP",
  rating: "Rating",
  litigation: "Litigation",
  regulatory: "Regulatory",
  other: "Other",
  // The articles query sends "Markets" for a filing the classifier has not labelled yet.
  markets: "Unclassified",
};

/** The feed row's category ("Earnings", "Mna") as the classifier's key ("earnings", "mna"). */
export function categoryKey(category: string | null | undefined): string {
  return (category ?? "").trim().toLowerCase().replace(/\s+/g, "_");
}

export function categoryLabel(category: string | null | undefined): string {
  const k = categoryKey(category);
  if (!k) return "Unclassified";
  return CATEGORY_LABEL[k] ?? k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** A category's colour: the colour of the chip that holds it. */
export function categoryTone(category: string | null | undefined): Tone {
  const k = categoryKey(category);
  return INTEL_CHIPS.find((c) => c.key !== "all" && c.categories.includes(k))?.tone ?? "ink";
}

/** Count of filings per chip, from the route's facets (which leave out regulatory and other). */
export function chipCount(chip: ChipDef, facets: Record<string, number> | null): number | null {
  if (!facets || chip.key === "all" || chip.key === "flows" || chip.key === "regulatory") return null;
  let n = 0;
  for (const c of chip.categories) n += c ? facets[c] ?? 0 : 0;
  return n;
}

const IST = "Asia/Kolkata";
const istDay = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: IST });

/** "09:12" for a filing made today (India time), "13 Oct" before that, and the full stamp. */
export function eventWhen(iso: string | null | undefined): { short: string; full: string } {
  if (!iso) return { short: "—", full: "—" };
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso);
  const d = new Date(dateOnly ? `${iso}T12:00:00+05:30` : iso);
  if (!Number.isFinite(d.getTime())) return { short: "—", full: "—" };
  const day = d.toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short" });
  if (dateOnly) return { short: day, full: d.toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short", year: "numeric" }) };
  const time = d.toLocaleTimeString("en-IN", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false });
  return {
    short: istDay(d) === istDay(new Date()) ? time : day,
    full: `${d.toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short", year: "numeric" })}, ${time} IST`,
  };
}

/** The exchange a filing was made on, read from its document link (the feed row does not carry it). */
export function exchangeOf(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.includes("nseindia")) return "NSE";
    if (host.includes("bseindia")) return "BSE";
    return host.replace(/^www\./, "");
  } catch {
    return null;
  }
}

const filedAt = (r: FilingRow) => {
  const t = r.date ? new Date(r.date).getTime() : NaN;
  return Number.isFinite(t) ? t : -Infinity;
};

/** The route's own order, applied to rows merged from several requests. */
function routeOrder(sort: FeedSort) {
  return (a: FilingRow, b: FilingRow) => {
    if (sort === "material") {
      const ha = (a.impact ?? "").toLowerCase() === "high" ? 0 : 1;
      const hb = (b.impact ?? "").toLowerCase() === "high" ? 0 : 1;
      if (ha !== hb) return ha - hb;
    }
    return filedAt(b) - filedAt(a);
  };
}

export interface EventFeed {
  status: "loading" | "error" | "ready";
  rows: FilingRow[];
  /** Filings matching the chip in the window (the routes' `total`s added up), not the rows loaded. */
  total: number | null;
  /** Per-category counts for the window (every response carries the same facets). */
  facets: Record<string, number> | null;
  /** Some of a group's requests failed; the rows shown are the rest. */
  partial: boolean;
  error: unknown;
  refetch: () => void;
}

/** The filings behind one chip. FII / DII reads no filings. */
export function useEventFeed(chip: IntelChip, sort: FeedSort): EventFeed {
  const def = INTEL_CHIPS.find((c) => c.key === chip) ?? INTEL_CHIPS[0];
  const cats = def.categories;
  const limit = cats.length > 1 ? LIMIT_GROUPED : LIMIT_SINGLE;
  const queries = useQueries({
    queries: cats.map((category) => {
      const params: FeedParams = { days: FEED_DAYS, category, sort, limit };
      return {
        queryKey: ["filings", "feed", params],
        queryFn: () => filingsService.getFeed(params),
        staleTime: 60_000,
      };
    }),
  });

  const refetch = () => {
    for (const q of queries) if (q.isError) void q.refetch();
  };
  const done = queries.filter((q) => q.isSuccess).map((q) => q.data as FeedResp);
  const failed = queries.filter((q) => q.isError);
  const facets = done.find((d) => d.facets)?.facets ?? null;
  if (cats.length === 0) return { status: "ready", rows: [], total: null, facets: null, partial: false, error: null, refetch };
  if (failed.length === queries.length) return { status: "error", rows: [], total: null, facets: null, partial: false, error: failed[0].error, refetch };
  if (queries.some((q) => q.isPending)) return { status: "loading", rows: [], total: null, facets, partial: false, error: null, refetch };

  const seen = new Set<string>();
  const rows: FilingRow[] = [];
  for (const d of done) {
    for (const r of d.rows) {
      if (seen.has(r.id)) continue;
      seen.add(r.id);
      rows.push(r);
    }
  }
  if (done.length > 1) rows.sort(routeOrder(sort));
  const total = done.reduce((n, d) => n + (d.total ?? d.rows.length), 0);
  return { status: "ready", rows, total, facets, partial: failed.length > 0, error: failed[0]?.error ?? null, refetch };
}
