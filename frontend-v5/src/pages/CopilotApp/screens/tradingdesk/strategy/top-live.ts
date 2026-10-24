/**
 * Strategy Builder, "Top by regime" — live premiums for the contracts on screen.
 *
 *   POST /api/live/fno-quotes   Kite REST quote() for the NAMED legs; read only
 *
 * One request for every leg the board is showing, not a chain subscription: the platform websocket
 * carries cash, indices, the near-month futures and only a window of NIFTY and BANKNIFTY options (the
 * two nearest expiries, 15 strikes either side of the money), so a leg outside that window is not on
 * it, and NIFTY plus BANKNIFTY alone run to thousands of listed strikes against Kite's instrument cap.
 *
 * The board's RANKING is not re-computed from these prices. It was produced from the end-of-day chain
 * and says so; a live premium is shown beside the figure it would replace, so the two are never
 * confused. If the read is unavailable the screen keeps the end-of-day prices and states the reason.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import type { OptionIdea } from "./top-contract";

export const FNO_QUOTES_PATH = "/api/live/fno-quotes";

export interface LiveLegRequest {
  underlying: string;
  kind: string;
  expiry?: string | null;
  strike?: number | null;
  option_type?: string | null;
}

export interface LiveQuote {
  key: string;
  last_price: number;
  previous_close?: number;
  oi?: number;
  volume?: number;
}

export interface LiveAnswer {
  available: boolean;
  reason?: string | null;
  quotes: Record<string, LiveQuote>;
  unresolved: Array<{ index: number; reason: string }>;
  as_of?: string | null;
  source?: string | null;
}

/** Every leg of every option idea on the board, with the index each one will carry in the answer. */
export function legsForBoard(ideas: OptionIdea[]): { legs: LiveLegRequest[]; at: Map<string, number> } {
  const legs: LiveLegRequest[] = [];
  const at = new Map<string, number>();
  ideas.forEach((idea) => {
    idea.legs.forEach((l, j) => {
      at.set(`${idea.underlying}|${idea.structure}|${idea.rank}|${j}`, legs.length);
      legs.push({
        underlying: idea.underlying,
        kind: l.kind,
        expiry: l.expiry ?? null,
        strike: l.strike ?? null,
        option_type: l.option_type ?? null,
      });
    });
  });
  return { legs, at };
}

export function legSlot(idea: OptionIdea, j: number): string {
  return `${idea.underlying}|${idea.structure}|${idea.rank}|${j}`;
}

/** Enabled only when the user asks for it: a board that polls Kite on every render would spend a
 *  rate-limited REST budget nobody requested. */
export function useFnoLive(legs: LiveLegRequest[], enabled: boolean) {
  return useQuery<LiveAnswer>({
    queryKey: ["copilot", "desk", "fno-live", legs],
    enabled: enabled && legs.length > 0,
    retry: false,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const res = await http({ method: "POST", path: FNO_QUOTES_PATH, body: { legs }, signal, noRetry: true });
      return res.data as LiveAnswer;
    },
  });
}

/** Net premium at live prices, ₹, signed the way the engine signs it (debit negative). Returns null
 *  unless EVERY option leg of the idea has a live price: a part-live total would be a number that
 *  belongs to no moment. */
export function liveNetPremium(idea: OptionIdea, answer: LiveAnswer | undefined,
                               at: Map<string, number>): number | null {
  if (!answer?.available) return null;
  let total = 0;
  let seen = 0;
  for (let j = 0; j < idea.legs.length; j += 1) {
    const l = idea.legs[j];
    if (l.kind !== "option") continue;
    const idx = at.get(legSlot(idea, j));
    const q = idx == null ? undefined : answer.quotes[String(idx)];
    if (!q || l.quantity == null || l.lot_size == null) return null;
    const units = l.quantity * l.lot_size;
    total += (l.side === "sell" ? 1 : -1) * q.last_price * units;
    seen += 1;
  }
  return seen ? Math.round(total * 100) / 100 : null;
}
