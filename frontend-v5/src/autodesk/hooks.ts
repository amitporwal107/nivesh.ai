/**
 * Shared data hooks (TanStack Query). Screen-specific queries live with their screen; these are the ones the shell
 * and several screens read. Query keys start with "desk" so one invalidate refreshes the desk after a write.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deskGet, deskPost, mainGet } from "./api";
import { num } from "./format";
import type { Account, ApprovalRow, DeskControlRow, DeskStatus, Me } from "./types";

export const keys = {
  status: ["desk", "status"] as const,
  accounts: ["desk", "accounts"] as const,
  controls: ["desk", "controls"] as const,
  pending: ["desk", "approvals", "pending"] as const,
  me: ["main", "me"] as const,
  indices: ["main", "live", "indices"] as const,
};

export function useDeskStatus() {
  return useQuery({ queryKey: keys.status, queryFn: () => deskGet<DeskStatus>("/desk/status"), refetchInterval: 30_000 });
}

/** The desk's own accounts (paper; simulation accounts are left out). */
export function useAccounts() {
  return useQuery({ queryKey: keys.accounts, queryFn: () => deskGet<Account[]>("/accounts") });
}

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: () => mainGet<Me>("/auth/me"), staleTime: 5 * 60_000 });
}

/** Approval requests waiting on a person for the desk's real-time accounts (simulation requests are the simulator's). */
export function usePendingApprovals() {
  return useQuery({
    queryKey: keys.pending,
    queryFn: async () => (await deskGet<ApprovalRow[]>("/approvals", { pending: true })).filter((a) => !a.simulation_id),
    refetchInterval: 30_000,
  });
}

export function stopEntriesOf(status: DeskStatus | undefined): DeskControlRow | null {
  return status?.controls?.find((c) => c.control === "STOP_NEW_ENTRIES" && c.active) ?? null;
}

export function useSetStopEntries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { active: boolean; reason: string }) =>
      deskPost<DeskControlRow & { changed?: boolean }>("/desk/controls/STOP_NEW_ENTRIES", { active: v.active, reason: v.reason }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["desk"] }),
  });
}

export function useCreateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { name: string; starting_capital_rs: number }) =>
      deskPost<Account>("/accounts", { name: v.name, operating_mode: "RESEARCH", starting_capital_rs: v.starting_capital_rs }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["desk"] }),
  });
}

// ── index quotes and the NSE session, from the main app's read-only Kite feed ───────────────────────────────────────

export const INDEX_SYMBOLS = [
  { symbol: "NIFTY 50", label: "NIFTY" },
  { symbol: "NIFTY BANK", label: "BANKNIFTY" },
  { symbol: "INDIA VIX", label: "VIX" },
] as const;

export type FeedMode = "live" | "delayed" | "closed" | "expired" | "not_connected" | "disabled" | "unknown";

export interface IndexQuotes {
  mode: FeedMode;
  /** "open" | "pre_open" | "closed" from the feed's holiday-aware session clock; null when unknown. */
  session: string | null;
  stale: boolean;
  final: boolean;
  dataAt: string | null;
  quotes: Record<string, { ltp: number; changePct: number | null }>;
}

const MODES: FeedMode[] = ["live", "delayed", "closed", "expired", "not_connected", "disabled"];

export function parseIndexQuotes(body: unknown): IndexQuotes {
  const b = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
  const raw = (b.quotes && typeof b.quotes === "object" && !Array.isArray(b.quotes) ? b.quotes : {}) as Record<string, unknown>;
  const quotes: IndexQuotes["quotes"] = {};
  for (const [sym, v] of Object.entries(raw)) {
    const r = (v && typeof v === "object" ? v : {}) as Record<string, unknown>;
    const ltp = num(r.ltp);
    if (ltp == null || ltp <= 0) continue;               // a price the feed did not have is absent, never 0
    quotes[sym.toUpperCase()] = { ltp, changePct: num(r.change_pct) };
  }
  return {
    mode: MODES.find((m) => m === b.mode) ?? "unknown",
    session: typeof b.session === "string" && b.session ? b.session : null,
    stale: b.stale !== false,
    final: b.final === true,
    dataAt: typeof b.data_at === "string" ? b.data_at : null,
    quotes,
  };
}

export function useIndexQuotes() {
  return useQuery({
    queryKey: keys.indices,
    queryFn: async () => parseIndexQuotes(await mainGet<unknown>("/live/quotes", { symbols: INDEX_SYMBOLS.map((s) => s.symbol).join(",") })),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    retry: 1,
  });
}

/** Wall clock that re-renders every `ms`. */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

/** Below 760 px the desk uses the phone layout of the design (top bar, bottom tabs, More sheet). */
export function useIsMobile(breakpoint = 760): boolean {
  const q = `(max-width: ${breakpoint - 1}px)`;
  const [m, setM] = useState(() => typeof window !== "undefined" && window.matchMedia(q).matches);
  useEffect(() => {
    const mq = window.matchMedia(q);
    const on = () => setM(mq.matches);
    mq.addEventListener("change", on);
    on();
    return () => mq.removeEventListener("change", on);
  }, [q]);
  return m;
}
