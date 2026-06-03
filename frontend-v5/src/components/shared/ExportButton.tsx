/**
 * ExportButton — downloads holdings as CSV (AC-24).
 * Reflects active filter and selected period.
 */
import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { useHoldingsFilter } from "@/hooks/use-holdings-filter";

interface Props {
  period?: string;
  label?: string;
  className?: string;
}

export function ExportButton({ period, label = "Export CSV", className }: Props) {
  const { filter } = useHoldingsFilter();
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  async function handleExport() {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ format: "csv" });
      if (period) params.set("period", period);
      if (filter) {
        params.set("filter_dimension", filter.dimension);
        params.set("filter_value", filter.value);
      }

      const res = await fetch(`/api/portfolio/holdings/export?${params}`, {
        credentials: "include",
      });

      if (!res.ok) {
        throw new Error(res.status === 404 ? "No holdings to export." : `Export failed (${res.status})`);
      }

      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      const cd   = res.headers.get("content-disposition") ?? "";
      const fn   = cd.match(/filename="?([^"]+)"?/)?.[1] ?? "holdings.csv";
      a.href = url; a.download = fn;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Export failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="inline-flex flex-col items-end gap-1">
      <button
        onClick={handleExport}
        disabled={loading}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-opacity disabled:opacity-50 ${className ?? ""}`}
        style={{
          background: "rgba(var(--surface-3),0.8)",
          border: "1px solid rgba(var(--line),0.12)",
          color: "rgb(var(--ink-1))",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
        }}
        aria-label={`${label}${filter ? ` — filtered to ${filter.label ?? filter.value}` : ""}${period ? `, period ${period}` : ""}`}>
        {loading
          ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          : <Download className="h-3.5 w-3.5" aria-hidden="true" />}
        {label}
      </button>
      {error && (
        <span className="text-[10px]" style={{ color: "rgb(var(--neg))", fontFamily: "var(--font-mono)" }}>
          {error}
        </span>
      )}
    </div>
  );
}
