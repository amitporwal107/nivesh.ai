/**
 * HoldingsTable v2 — v5 Performance Dashboard
 *
 * - 8 visible columns on desktop (spec §4 REQ 10); sticky Name column
 * - Sort on any numeric column; default = current value DESC
 * - Text search by fund name / ISIN
 * - Filter by dimension via useHoldingsFilter (set by Composition Explorer, etc.)
 * - AMFI-unmatched rows: marker + "—" for benchmark/attribution fields (AC-19)
 * - Row click → HoldingDrawer (AC-20)
 * - Mobile: stacked cards (< 640 px)
 */

import { useState, useMemo, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Search, ChevronUp, ChevronDown } from "lucide-react";
import { formatINRCompact } from "@/lib/formatters";
import { EnrichedHoldingC } from "@/services/contracts/portfolio.contract";
import type { z } from "zod";
type EnrichedHolding = z.infer<typeof EnrichedHoldingC>;
import { HoldingDrawer } from "./HoldingDrawer";
import { useHoldingsFilter } from "@/hooks/use-holdings-filter";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────

type SortKey = "value_rs" | "pnl_pct" | "xirr_pct" | "weight_pct" | "benchmark_delta";
type SortDir = "asc" | "desc";

interface Props {
  holdings: EnrichedHolding[];
  className?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────

function sign(n: number | null | undefined) {
  return n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}

function pctCell(n: number | null | undefined) {
  if (n == null) return <span className="opacity-30" aria-label="unavailable">—</span>;
  const pos = n >= 0;
  return (
    <span style={{ color: pos ? "rgb(var(--pos))" : "rgb(var(--neg))" }}
      aria-label={`${pos ? "+" : ""}${n.toFixed(1)} percent`}>
      {pos ? "▲" : "▼"} {pos ? "+" : ""}{n.toFixed(1)}%
    </span>
  );
}

// Recommendation pill — colour by the action keyword (matches the V2 mapping).
function ActionBadge({ badge }: { badge: EnrichedHolding["action_badge"] }) {
  if (!badge) return <span className="opacity-30">—</span>;
  const action = (typeof badge === "string" ? badge : badge.action ?? "").trim();
  if (!action) return <span className="opacity-30">—</span>;
  const reason = typeof badge === "string" ? undefined : badge.reason;
  const a = action.toUpperCase();
  const color =
    /EXIT|SELL/.test(a)            ? "var(--neg)"   :
    /REDUCE|SWITCH|TRIM/.test(a)   ? "var(--warm)"  :
    /REVIEW|WATCH/.test(a)         ? "var(--accent)":
    /BUY|ADD|INCREASE/.test(a)     ? "var(--pos)"   :
    "var(--ink-3)"; // HOLD / unknown
  return (
    <span title={reason}
      className="inline-block text-[10px] px-2 py-0.5 rounded font-medium uppercase tracking-wide"
      style={{ background: `rgb(${color} / 0.14)`, color: `rgb(${color})` }}>
      {a}
    </span>
  );
}

// ── Column definitions ─────────────────────────────────────────────────────

const COLS: Array<{ key: string; label: string; sortKey?: SortKey; align?: "right" }> = [
  { key: "name",            label: "Fund" },
  { key: "asset_class",     label: "Asset class" },
  { key: "category",        label: "Category" },
  { key: "value_rs",        label: "Current value",  sortKey: "value_rs",       align: "right" },
  { key: "pnl_pct",         label: "P&L",            sortKey: "pnl_pct",        align: "right" },
  { key: "weight_pct",      label: "Weight",         sortKey: "weight_pct",     align: "right" },
  { key: "xirr_pct",        label: "XIRR",           sortKey: "xirr_pct",       align: "right" },
  { key: "benchmark_delta", label: "vs Benchmark",   sortKey: "benchmark_delta",align: "right" },
  { key: "action",          label: "Action" },
];

// ── Component ─────────────────────────────────────────────────────────────

export function HoldingsTable({ holdings, className }: Props) {
  const [sortKey, setSortKey]   = useState<SortKey>("value_rs");
  const [sortDir, setSortDir]   = useState<SortDir>("desc");
  const [search, setSearch]     = useState("");
  const [drawer, setDrawer]     = useState<EnrichedHolding | null>(null);
  const { filter, clearFilter } = useHoldingsFilter();

  // Sort toggle
  function handleSort(key: SortKey) {
    if (key === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("desc"); }
  }

  // Filter + search + sort
  const rows = useMemo(() => {
    let list = holdings;

    // Dimension filter from Composition Explorer / Benchmark donut
    if (filter) {
      list = list.filter((h) => {
        const any = h as any;
        switch (filter.dimension) {
          case "asset_class": return (any.asset_class ?? "").toLowerCase() === filter.value.toLowerCase();
          case "sector":      return (h.sector ?? "").toLowerCase() === filter.value.toLowerCase();
          case "fund":        return h.name === filter.value;
          case "group":
          case "amc":         return (any.amc_name ?? "").toLowerCase() === filter.value.toLowerCase();
          default:            return true;
        }
      });
    }

    // Text search
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((h) =>
        h.name.toLowerCase().includes(q) ||
        (h.isin ?? "").toLowerCase().includes(q)
      );
    }

    // Sort
    list = [...list].sort((a, b) => {
      const va = (a as any)[sortKey] ?? -Infinity;
      const vb = (b as any)[sortKey] ?? -Infinity;
      return sortDir === "asc" ? va - vb : vb - va;
    });

    return list;
  }, [holdings, filter, search, sortKey, sortDir]);

  const tableBodyRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => tableBodyRef.current,
    estimateSize: () => 64,
    overscan: 5,
  });

  const SortIcon = ({ k }: { k: SortKey }) => {
    if (k !== sortKey) return <span className="opacity-20 text-[9px]">↕</span>;
    return sortDir === "asc"
      ? <ChevronUp className="inline h-3 w-3" />
      : <ChevronDown className="inline h-3 w-3" />;
  };

  return (
    <>
      <div className={cn("rounded-lg overflow-hidden", className)}
        style={{ border: "1px solid rgba(var(--line),0.08)", background: "rgb(var(--surface-2))" }}>

        {/* Toolbar */}
        <div className="flex items-center gap-3 px-4 py-3"
          style={{ borderBottom: "1px solid rgba(var(--line),0.08)" }}>
          <div className="relative flex-1 max-w-xs">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 opacity-30" />
            <input
              type="search"
              placeholder="Search fund or ISIN…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-sm rounded-md outline-none"
              style={{
                background: "rgba(var(--surface-3),0.6)",
                border: "1px solid rgba(var(--line),0.10)",
                color: "rgb(var(--ink-1))",
              }}
            />
          </div>

          {/* Active filter chip */}
          {filter && (
            <div className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full"
              style={{ background: "rgba(var(--accent),0.12)", color: "rgb(var(--accent))" }}>
              <span>{filter.label ?? filter.value}</span>
              <button onClick={clearFilter} aria-label="Clear filter" className="hover:opacity-70 transition-opacity">✕</button>
            </div>
          )}

          <span className="text-xs opacity-40 ml-auto shrink-0" style={{ fontFamily: "var(--font-mono)" }}>
            {rows.length} holding{rows.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Desktop table */}
        <div className="hidden sm:block overflow-x-auto">
          <table className="w-full text-sm" style={{ minWidth: 880 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid rgba(var(--line),0.08)" }}>
                {COLS.map((col) => (
                  <th key={col.key}
                    className={cn(
                      "px-4 py-3 text-left font-normal select-none",
                      col.align === "right" && "text-right",
                      col.sortKey && "cursor-pointer hover:opacity-80"
                    )}
                    style={{ fontFamily: "var(--font-mono)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.1em", opacity: 0.45 }}
                    onClick={() => col.sortKey && handleSort(col.sortKey)}>
                    {col.label}
                    {col.sortKey && <span className="ml-1"><SortIcon k={col.sortKey} /></span>}
                  </th>
                ))}
                {/* empty header for action column */}
                <th className="w-8" />
              </tr>
            </thead>
          </table>
          {rows.length === 0 ? (
            <div className="px-4 py-12 text-center text-sm opacity-40" style={{ fontFamily: "var(--font-mono)" }}>
              {holdings.length === 0 ? "No holdings here yet." : "No holdings match your filter."}
            </div>
          ) : (
            <div ref={tableBodyRef} style={{ height: Math.min(rows.length * 64, 520), overflowY: "auto" }}>
              <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}>
                {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                  const h = rows[virtualRow.index];
                  const any = h as any;
                  const unmatched = h.amfi_matched === false;
                  const pnlPos = (h.pnl_pct ?? 0) >= 0;
                  return (
                    <table key={h.holding_id}
                      className="w-full text-sm"
                      style={{
                        minWidth: 880,
                        position: "absolute",
                        top: virtualRow.start,
                        left: 0,
                        right: 0,
                        tableLayout: "fixed",
                      }}>
                      <tbody>
                        <tr
                          onClick={() => setDrawer(h)}
                          className="cursor-pointer transition-colors"
                          style={{ borderTop: "1px solid rgba(var(--line),0.06)" }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(var(--surface-3),0.5)")}
                          onMouseLeave={(e) => (e.currentTarget.style.background = "")}>

                          {/* Name — full canonical scheme/stock name (wraps to 2 lines) */}
                          <td className="px-4 py-2.5 w-[40%] max-w-[360px]">
                            <div className="font-medium text-[13px] leading-snug" title={h.name}
                              style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                              {h.name}
                            </div>
                            <div className="flex items-center gap-1.5 mt-0.5">
                              {h.isin && (
                                <span className="text-[10px] opacity-35" style={{ fontFamily: "var(--font-mono)" }}>
                                  {h.isin}
                                </span>
                              )}
                              {unmatched && (
                                <span className="text-[9px] px-1 py-0.5 rounded"
                                  style={{ background: "rgba(var(--warm),0.15)", color: "rgb(var(--warm))" }}
                                  aria-label="Fund not AMFI-matched — benchmark data unavailable">
                                  ⚠ unmatched
                                </span>
                              )}
                            </div>
                          </td>

                          {/* Asset class */}
                          <td className="px-4 py-3 text-[11px] opacity-60" style={{ fontFamily: "var(--font-mono)" }}>
                            {any.asset_class ?? h.asset_type ?? "—"}
                          </td>

                          {/* Category */}
                          <td className="px-4 py-3 text-[11px] opacity-50 max-w-[120px]">
                            <span className="truncate block" title={h.category ?? ""}>{h.category ?? "—"}</span>
                          </td>

                          {/* Current value */}
                          <td className="px-4 py-3 text-right text-[13px]" style={{ fontFamily: "var(--font-mono)" }}>
                            {h.value_rs != null ? formatINRCompact(h.value_rs) : "—"}
                          </td>

                          {/* P&L */}
                          <td className="px-4 py-3 text-right text-[12px]" style={{ fontFamily: "var(--font-mono)" }}>
                            {h.pnl_pct != null ? (
                              <span style={{ color: pnlPos ? "rgb(var(--pos))" : "rgb(var(--neg))" }}
                                aria-label={`${pnlPos ? "+" : ""}${h.pnl_pct.toFixed(1)} percent`}>
                                {pnlPos ? "▲ +" : "▼ "}{h.pnl_pct.toFixed(1)}%
                              </span>
                            ) : <span className="opacity-30">—</span>}
                          </td>

                          {/* Weight */}
                          <td className="px-4 py-3 text-right text-[12px]" style={{ fontFamily: "var(--font-mono)" }}>
                            {h.weight_pct != null ? `${h.weight_pct.toFixed(1)}%` : "—"}
                          </td>

                          {/* XIRR */}
                          <td className="px-4 py-3 text-right text-[12px]">
                            {pctCell(h.xirr_pct)}
                          </td>

                          {/* vs Benchmark — relative delta + the index it's measured against */}
                          <td className="px-4 py-3 text-right text-[12px]">
                            {unmatched ? (
                              <span className="opacity-30" aria-label="benchmark data unavailable — fund not AMFI-matched">—</span>
                            ) : (
                              <div className="flex flex-col items-end leading-tight">
                                {pctCell(h.benchmark_delta)}
                                {h.benchmark_label && (
                                  <span className="text-[9.5px] opacity-40 mt-0.5" style={{ fontFamily: "var(--font-mono)" }}>
                                    vs {h.benchmark_label}{any.benchmark_delta_horizon ? ` · ${any.benchmark_delta_horizon}` : ""}
                                  </span>
                                )}
                              </div>
                            )}
                          </td>

                          {/* Action */}
                          <td className="px-4 py-3">
                            <ActionBadge badge={h.action_badge} />
                          </td>

                          {/* Chevron */}
                          <td className="px-3 py-3 text-right opacity-25 text-xs">›</td>
                        </tr>
                      </tbody>
                    </table>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Mobile: stacked cards */}
        <ul className="sm:hidden divide-y" style={{ borderColor: "rgba(var(--line),0.08)" }}>
          {rows.length === 0 && (
            <li className="px-5 py-10 text-center text-sm opacity-40"
              style={{ fontFamily: "var(--font-mono)" }}>
              {holdings.length === 0 ? "No holdings here yet." : "No holdings match your filter."}
            </li>
          )}
          {rows.map((h) => {
            const any = h as any;
            const pnlPos = (h.pnl_pct ?? 0) >= 0;
            return (
              <li key={h.holding_id}
                onClick={() => setDrawer(h)}
                className="px-4 py-4 active:opacity-70 cursor-pointer">
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="font-medium text-[14px] flex-1 truncate" title={h.name}>{h.name}</span>
                  <span className="font-mono text-[13px] shrink-0">
                    {h.value_rs != null ? formatINRCompact(h.value_rs) : "—"}
                  </span>
                </div>
                <div className="flex items-baseline gap-2 text-[11px] opacity-55">
                  <span style={{ fontFamily: "var(--font-mono)" }}>{h.category ?? any.asset_class ?? "—"}</span>
                  {h.pnl_pct != null && (
                    <span className="ml-auto" style={{ color: pnlPos ? "rgb(var(--pos))" : "rgb(var(--neg))" }}>
                      {pnlPos ? "▲ +" : "▼ "}{h.pnl_pct.toFixed(1)}%
                    </span>
                  )}
                </div>
                {h.action_badge && (
                  <div className="mt-1.5"><ActionBadge badge={h.action_badge} /></div>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      {/* Holding detail drawer */}
      <HoldingDrawer holding={drawer} onClose={() => setDrawer(null)} />
    </>
  );
}
