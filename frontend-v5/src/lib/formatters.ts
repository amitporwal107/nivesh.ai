import type { Paise } from "@/types/common";

const inrFmt = new Intl.NumberFormat("en-IN");
const pctFmt = new Intl.NumberFormat("en-IN", { style: "percent", maximumFractionDigits: 1 });

/** ₹24,82,400 — full rupee value */
export function formatINR(paise: Paise, { compact = false }: { compact?: boolean } = {}): string {
  const rupees = paise / 100;
  if (compact) return formatINRCompact(rupees);
  return "₹" + inrFmt.format(Math.round(rupees));
}

/** ₹24.8 L, ₹2.4 Cr — for KPIs */
export function formatINRCompact(rupees: number): string {
  if (Math.abs(rupees) >= 1_00_00_000) return "₹" + (rupees / 1_00_00_000).toFixed(2) + " Cr";
  if (Math.abs(rupees) >= 1_00_000) return "₹" + (rupees / 1_00_000).toFixed(2) + " L";
  if (Math.abs(rupees) >= 1_000) return "₹" + (rupees / 1_000).toFixed(1) + "k";
  return "₹" + Math.round(rupees);
}

/** +18.7% */
export function formatPct(ratio: number, { signed = false }: { signed?: boolean } = {}): string {
  const v = pctFmt.format(ratio);
  return signed && ratio > 0 ? "+" + v : v;
}

/** "May 27 2026" */
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
