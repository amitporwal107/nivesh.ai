/**
 * Open Positions — what the server returns (backend/routes/positions.py, services/positions/*).
 *
 *   GET    /api/positions                       every open position, broker and paper, grouped by underlying
 *   GET    /api/positions/{key}/scenario        one group's scenario table (?moves=&iv_shift=&days_forward=)
 *   PUT    /api/positions/{underlying}/levels   the user's stop / target / trailing stop for a broker underlying
 *   DELETE /api/positions/{underlying}/levels
 *   POST   /api/fno/margin                      Zerodha's margin calculator for a group's F&O legs (a calculation;
 *                                               needs the platform's daily Kite session — 503 without it)
 *
 * Read-only towards brokers: nothing here places, modifies or cancels an order. The broker read is live on every
 * call, so nothing polls. Prices and P&L are RUPEES. A figure the server could not work out is null and is shown as
 * "—", never as zero. The fetchers validate the shape and throw ApiError("contract_drift") on anything else.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";

const n = z.number().nullable();

const Warning = z.object({ code: z.string(), tone: z.string(), text: z.string() });
export type PositionWarning = z.infer<typeof Warning>;

const Greeks = z.object({ delta: z.number(), gamma: z.number(), theta: z.number(), vega: z.number() });
export type PositionGreeks = z.infer<typeof Greeks>;

const Leg = z.object({
  key: z.string().nullable(),
  label: z.string().nullable(),
  instrument: z.string().nullable(),
  expiry: z.string().nullable(),
  strike: n,
  quantity: z.number(),
  lots: n,
  lot_size: n.optional(),
  avg_price: n,
  mark: n,
  iv_pct: n,
  greeks: Greeks.nullable(),
  ltp: n.optional(),
  ltp_source: z.string().nullable().optional(),
  ltp_date: z.string().nullable().optional(),
  pnl_rs: n.optional(),
  broker_code: z.string().nullable().optional(),
  account_id: z.string().nullable().optional(),
  broker_display: z.string().nullable().optional(),
}).passthrough();
export type PositionLeg = z.infer<typeof Leg>;

const ScenarioRow = z.object({ move_pct: z.number(), price: n, expiry_pnl_rs: n, today_pnl_rs: n });
export type PositionScenarioRow = z.infer<typeof ScenarioRow>;

const Payoff = z.object({
  breakevens: z.array(z.number().nullable()),
  max_profit: n,
  profit_unbounded: z.boolean(),
  max_loss: n,
  loss_unbounded: z.boolean(),
  risk_basis: z.enum(["stop", "expiry"]),
  pnl_at_stop_rs: n,
  loss_at_stop_rs: n,
  pnl_at_stop_basis: z.string().nullable(),
  risk_to_stop_rs: n,
  pnl_at_target_rs: n,
  gross: z.boolean(),
});
export type PositionPayoff = z.infer<typeof Payoff>;

const Analytics = z.object({
  greeks: Greeks.nullable(),
  delta_exposure_rs: n,
  exposure_rs: n,
  payoff: Payoff.nullable(),
  scenario: z.array(ScenarioRow),
  curve: z.array(z.array(z.number().nullable())),
  distance_to_stop_pct: n,
  distance_to_target_pct: n,
  direction: z.string().nullable(),
});

const Levels = z.object({
  stop: n,
  target: n,
  trail_pct: n,
  effective_stop: n,
  set_by: z.string(),
  updated_at: z.string().nullable().optional(),
});
export type PositionLevels = z.infer<typeof Levels>;

const Unmapped = z.object({
  broker_code: z.string().nullable(),
  broker_display: z.string().nullable(),
  quantity: n,
  pnl_rs: n,
  problem: z.string().nullable(),
}).passthrough();

const MarginLeg = z.object({ side: z.string(), option_type: z.string(), expiry: z.string(), strike: n, lots: z.number() });
const MarginRequest = z.object({ underlying: z.string(), legs: z.array(MarginLeg) });
export type PositionMarginRequest = z.infer<typeof MarginRequest>;

const Group = z.object({
  key: z.string(),
  source: z.enum(["broker", "paper"]),
  underlying: z.string(),
  kind: z.enum(["equity", "fno", "unmapped"]),
  label: z.string().nullable().optional(),
  accounts: z.array(z.object({ account_id: z.string(), broker_display: z.string().nullable() })),
  legs: z.array(Leg),
  unmapped: z.array(Unmapped),
  price: z.object({ spot: n, source: z.string().nullable(), as_of: z.string().nullable(), pricing_as_of: z.string().nullable() }),
  pnl_rs: n,
  pnl_source: z.string().nullable(),
  levels: Levels.nullable(),
  warnings: z.array(Warning),
  analytics: Analytics.nullable(),
  margin_request: MarginRequest.nullable(),
  paper_trade_id: z.string().nullable(),
});
export type PositionGroup = z.infer<typeof Group>;

const Source = z.object({
  source: z.enum(["broker", "paper"]),
  ok: z.boolean(),
  error: z.object({ code: z.string(), message: z.string() }).nullable(),
  account_id: z.string().nullable().optional(),
  broker_display: z.string().nullable().optional(),
  read_at: z.string().nullable().optional(),
  as_of: z.string().nullable().optional(),
  rows: z.number().nullable().optional(),
}).passthrough();
export type PositionSource = z.infer<typeof Source>;

const Summary = z.object({
  groups: z.number(),
  positions: z.number(),
  broker_positions: z.number(),
  paper_positions: z.number(),
  paper_waiting_entry: z.number(),
  unmapped_rows: z.number(),
  unrealised_pnl_rs: n,
  unrealised_partial: z.boolean(),
  open_risk_at_stops_rs: n,
  near_stop: z.number(),
  stop_breached: z.number(),
  without_stop: z.number(),
  expiring_soon: z.number(),
  exposure_rs: n,
  day_realised_pnl_rs: n,
  day_realised_note: z.string(),
});
export type PositionsSummary = z.infer<typeof Summary>;

const Book = z.object({
  as_of: z.string(),
  read_only: z.literal(true),
  note: z.string(),
  sources: z.array(Source),
  quotes: z.object({ source: z.string().nullable(), as_of: z.string().nullable(), why: z.string().nullable() }).partial(),
  summary: Summary,
  groups: z.array(Group),
  method: z.object({ near_stop_pct: z.number(), expiry_soon_days: z.number(), gross: z.string() }).passthrough(),
});
export type PositionsBook = z.infer<typeof Book>;

const Scenario = z.object({
  key: z.string(),
  as_of: z.string(),
  underlying: z.string(),
  iv_shift: z.number(),
  days_forward: z.number(),
  gross: z.boolean(),
  rows: z.array(ScenarioRow).nullable(),
  why: z.string().nullable(),
}).passthrough();
export type PositionScenario = z.infer<typeof Scenario>;

function parse<T>(schema: z.ZodType<T>, data: unknown, what: string): T {
  const r = schema.safeParse(data);
  if (!r.success) throw new ApiError("contract_drift", `${what}: the answer was not in the expected form.`, { cause: r.error });
  return r.data;
}

export async function fetchPositions(signal?: AbortSignal): Promise<PositionsBook> {
  const res = await http({ path: "/api/positions", signal });
  return parse(Book, res.data, "GET /api/positions");
}

/** Every open position. A live broker read on every call: no polling, no refetch on focus. */
export function usePositions() {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<PositionsBook>({
    queryKey: ["copilot", "positions", profile ?? "self"],
    staleTime: 120_000,
    refetchOnWindowFocus: false,
    retry: (count, e) => !(e instanceof ApiError && e.kind === "contract_drift") && count < 1,
    queryFn: ({ signal }) => fetchPositions(signal),
  });
}

export interface ScenarioInput { key: string; ivShift: number; daysForward: number }

export function useScenario(input: ScenarioInput | null) {
  return useQuery<PositionScenario>({
    queryKey: ["copilot", "positions", "scenario", input?.key, input?.ivShift, input?.daysForward],
    enabled: input != null,
    staleTime: 120_000,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const res = await http({
        path: `/api/positions/${encodeURIComponent(input!.key)}/scenario`,
        query: { iv_shift: input!.ivShift, days_forward: input!.daysForward },
        signal,
      });
      return parse(Scenario, res.data, "GET /api/positions/{key}/scenario");
    },
  });
}

export interface LevelsInput { underlying: string; stop: number | null; target: number | null; trail_pct: number | null }

export function useSaveLevels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ underlying, ...body }: LevelsInput) => {
      const res = await http({ method: "PUT", path: `/api/positions/${encodeURIComponent(underlying)}/levels`, body });
      return res.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["copilot", "positions"] }),
  });
}

export function useDeleteLevels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (underlying: string) => {
      const res = await http({ method: "DELETE", path: `/api/positions/${encodeURIComponent(underlying)}/levels` });
      return res.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["copilot", "positions"] }),
  });
}

const MarginResult = z.object({ required_margin: n, initial_margin: n, as_of: z.string().nullable().optional(),
  source: z.string().nullable().optional() }).passthrough();
export type PositionMargin = z.infer<typeof MarginResult>;

/** Zerodha's margin calculator for the group's legs (POST /api/fno/margin). */
export function useGroupMargin() {
  return useMutation({
    mutationFn: async (body: PositionMarginRequest) => {
      const res = await http({ method: "POST", path: "/api/fno/margin", body });
      return parse(MarginResult, res.data, "POST /api/fno/margin");
    },
  });
}
