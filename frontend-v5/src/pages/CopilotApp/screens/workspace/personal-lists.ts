/**
 * Personal watchlists — lists of stocks the user names, adds to and removes from.
 *
 *   GET    /api/watchlists                         the user's lists, the limits, and whether the example list is still owed
 *   POST   /api/watchlists               {name}    make a list
 *   POST   /api/watchlists/starter                 make the example list (once per user; `created: false` after that)
 *   GET    /api/watchlists/{id}                    one list: its stocks, each with a quote or null
 *   PATCH  /api/watchlists/{id}          {name}    rename
 *   DELETE /api/watchlists/{id}
 *   POST   /api/watchlists/{id}/symbols  {symbol}  add a stock (already there → `added: false`, not an error)
 *   DELETE /api/watchlists/{id}/symbols/{symbol}   remove a stock
 *   GET    /api/filings/companies/search           the stock search behind "Add a stock": the symbol master
 *                                                  the add route checks a symbol against
 *
 * Contract: backend/routes/watchlists.py. Every body is checked here, so one in
 * the wrong shape is an error and never an empty list.
 *
 * Nothing is drawn ahead of the server. A write resolves only after the lists it
 * touched have been read again, so the screen changes when the stored data has,
 * and a failed write leaves it as it was.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { z, ZodError } from "zod";
import { filingsService, type Company } from "@/services/adapters/filings.adapter";
import { ApiError } from "@/services/api/errors";
import { http } from "@/services/api/http";

const BASE = "/api/watchlists";

/** Every personal-list query sits under this key. */
const ROOT = ["watchlists"] as const;
const INDEX_KEY = [...ROOT, "index"] as const;
const listKey = (id: string) => [...ROOT, "list", id] as const;

const SummaryC = z.object({
  watchlist_id: z.string().min(1),
  name: z.string(),
  symbol_count: z.number(),
  is_starter: z.boolean(),
  /** The date of the research list an example list was copied from. */
  seeded_from: z.string().nullable(),
  created_at: z.string().nullable().optional(),
  updated_at: z.string().nullable().optional(),
});
export type ListSummary = z.infer<typeof SummaryC>;

const IndexC = z.object({
  lists: z.array(SummaryC),
  limits: z.object({ max_lists: z.number(), max_symbols: z.number() }),
  /** True when this user has never had a list: the example list is made on this visit. */
  starter_pending: z.boolean(),
});
export type ListIndex = z.infer<typeof IndexC>;

const QuoteC = z.object({
  price: z.number(),
  day_change: z.number().nullable(),
  day_change_pct: z.number().nullable(),
  /** A time for a live quote, a calendar day for a stored one. */
  as_of: z.string().nullable(),
  is_live: z.boolean(),
});
export type ListQuote = z.infer<typeof QuoteC>;

const StockC = z.object({
  symbol: z.string().min(1),
  company_name: z.string().nullable(),
  added_at: z.string().nullable().optional(),
  /** Null when neither a live nor a stored price exists. Never a zero. */
  quote: QuoteC.nullable(),
});
export type ListStock = z.infer<typeof StockC>;

const DetailC = SummaryC.extend({
  stocks: z.array(StockC),
  quotes: z.object({ live: z.number(), stored: z.number(), none: z.number() }),
});
export type ListDetail = z.infer<typeof DetailC>;

const StarterC = z.object({
  created: z.boolean(),
  /** Why nothing was made: "already_had_a_list" | "no_research_list" | "viewing_a_client". */
  reason: z.string().nullable(),
  watchlist: SummaryC.nullable(),
});
export type StarterAnswer = z.infer<typeof StarterC>;

const AddC = z.object({
  added: z.boolean(),
  reason: z.string().nullable(),
  stock: z.object({ symbol: z.string(), company_name: z.string().nullable() }),
  watchlist: SummaryC,
});
export type AddAnswer = z.infer<typeof AddC>;

const RemoveC = z.object({ removed: z.boolean(), symbol: z.string(), watchlist: SummaryC });
export type RemoveAnswer = z.infer<typeof RemoveC>;

/** One more try for a read, unless the answer was final: a wrong shape, or a list that is not there. */
const readRetry = (count: number, error: unknown) =>
  !(error instanceof ZodError) && !(error instanceof ApiError && (error.kind === "contract_drift" || error.status === 404)) && count < 1;

/**
 * What to show for a failed write. The watchlist routes word their own refusals
 * (a name already used, a full list, an unknown symbol) in plain sentences, and
 * for "could not be checked just now" (503) that sentence is the useful part.
 */
export function writeFailure(error: unknown): unknown {
  return error instanceof ApiError && error.status === 503 && error.detail ? error.detail : error;
}

// ── reads ────────────────────────────────────────────────────────────────

export function usePersonalLists() {
  return useQuery<ListIndex>({
    queryKey: INDEX_KEY,
    staleTime: 30_000,
    retry: readRetry,
    queryFn: async ({ signal }) => IndexC.parse((await http({ path: BASE, signal })).data),
  });
}

/** One list with a quote for each stock, read again every 30 seconds like the research watchlist. */
export function usePersonalList(id: string | null) {
  return useQuery<ListDetail>({
    queryKey: listKey(id ?? ""),
    enabled: !!id,
    staleTime: 20_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    retry: readRetry,
    queryFn: async ({ signal }) => DetailC.parse((await http({ path: `${BASE}/${encodeURIComponent(id ?? "")}`, signal })).data),
  });
}

/** Stocks whose symbol or company name matches, from the symbol master. Nothing is asked under two characters. */
export function useStockSearch(term: string) {
  const q = term.trim();
  return useQuery<Company[]>({
    queryKey: ["filings", "companies-search", q],
    enabled: q.length >= 2,
    staleTime: 60_000,
    retry: readRetry,
    queryFn: () => filingsService.searchCompanies(q, 8),
  });
}

// ── writes ───────────────────────────────────────────────────────────────

const rereadIndex = (qc: QueryClient) => qc.invalidateQueries({ queryKey: INDEX_KEY });
const rereadList = (qc: QueryClient, id: string) => qc.invalidateQueries({ queryKey: listKey(id) });

/** Make the example list. Answers `created: false` with the reason when there is nothing to make. */
export function useStarterList() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<StarterAnswer> =>
      StarterC.parse((await http({ method: "POST", path: `${BASE}/starter`, noRetry: true })).data),
    onSuccess: () => rereadIndex(qc),
  });
}

export function useCreateList() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (name: string): Promise<ListSummary> =>
      SummaryC.parse((await http({ method: "POST", path: BASE, body: { name }, noRetry: true })).data),
    onSuccess: () => rereadIndex(qc),
  });
}

export function useRenameList() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, name }: { id: string; name: string }): Promise<ListSummary> =>
      SummaryC.parse((await http({ method: "PATCH", path: `${BASE}/${encodeURIComponent(id)}`, body: { name }, noRetry: true })).data),
    onSuccess: (_saved, { id }) => Promise.all([rereadIndex(qc), rereadList(qc, id)]),
  });
}

export function useDeleteList() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string): Promise<string> => {
      await http({ method: "DELETE", path: `${BASE}/${encodeURIComponent(id)}`, noRetry: true });
      return id;
    },
    onSuccess: () => rereadIndex(qc),
  });
}

export function useAddStock() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, symbol }: { id: string; symbol: string }): Promise<AddAnswer> =>
      AddC.parse((await http({ method: "POST", path: `${BASE}/${encodeURIComponent(id)}/symbols`, body: { symbol }, noRetry: true })).data),
    onSuccess: (_answer, { id }) => Promise.all([rereadIndex(qc), rereadList(qc, id)]),
  });
}

export function useRemoveStock() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, symbol }: { id: string; symbol: string }): Promise<RemoveAnswer> =>
      RemoveC.parse((await http({ method: "DELETE", path: `${BASE}/${encodeURIComponent(id)}/symbols/${encodeURIComponent(symbol)}`, noRetry: true })).data),
    onSuccess: (_answer, { id }) => Promise.all([rereadIndex(qc), rereadList(qc, id)]),
  });
}
