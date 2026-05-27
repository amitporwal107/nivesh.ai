/**
 * use-advisor — Advisor Home book/AUM/underperformers/rebalance + v4 summary & SIP board.
 */
import { useQuery } from "@tanstack/react-query";
import { advisorService } from "@/services";
export function useAdvisorSummary() {
    return useQuery({
        queryKey: ["advisor", "summary"],
        queryFn: () => advisorService.summary(),
    });
}
export function useAdvisorToday(limit = 100) {
    return useQuery({
        queryKey: ["advisor", "today", limit],
        queryFn: () => advisorService.today(limit),
    });
}
export function useAdvisorAum(limit = 100) {
    return useQuery({
        queryKey: ["advisor", "aum", limit],
        queryFn: () => advisorService.aum(limit),
    });
}
export function useAdvisorUnderperformers(gapPct, benchmark) {
    return useQuery({
        queryKey: ["advisor", "underperformers", gapPct ?? 5, benchmark ?? "nifty_50"],
        queryFn: () => advisorService.underperformers(gapPct, benchmark),
    });
}
export function useAdvisorRebalance(gapPp) {
    return useQuery({
        queryKey: ["advisor", "rebalance", gapPp ?? 10],
        queryFn: () => advisorService.rebalance(gapPp),
    });
}
export function useSipBoard(state, cycle) {
    return useQuery({
        queryKey: ["advisor", "sipBoard", state ?? "all", cycle ?? "current"],
        queryFn: () => advisorService.sipBoard(state, cycle),
    });
}
export function useSipBoardSummary() {
    return useQuery({
        queryKey: ["advisor", "sipBoard", "summary"],
        queryFn: () => advisorService.sipBoardSummary(),
    });
}
