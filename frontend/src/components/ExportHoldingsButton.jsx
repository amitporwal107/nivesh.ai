import React, { useState } from "react";
import { Download, FileText, Sheet, Loader2, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * ExportHoldingsButton — drop-in CSV / XLSX exporter.
 *
 * Two modes:
 *   • profileId omitted → calls /api/portfolio/holdings/export (self).
 *   • profileId set     → calls /api/mfd/profiles/{id}/holdings/export
 *                          (advisor mode, workspace-scoped on the server).
 *
 * Renders a compact dropdown so the user can pick CSV or Excel without
 * occupying two slots in the toolbar.
 */
export default function ExportHoldingsButton({
  profileId = null,
  variant = "outline",
  size = "default",
  className = "",
  label = "Export",
  testId = "export-holdings-btn",
}) {
  const [busy, setBusy] = useState(false);

  const triggerDownload = async (format) => {
    setBusy(true);
    const url = profileId
      ? `${API}/mfd/profiles/${profileId}/holdings/export?format=${format}`
      : `${API}/portfolio/holdings/export?format=${format}`;
    try {
      const res = await axios.get(url, {
        withCredentials: true,
        responseType: "blob",
      });
      // Pull filename out of Content-Disposition (server gives us a
      // descriptive name like "Amit_Porwal_holdings_20260428.xlsx").
      const cd = res.headers["content-disposition"] || "";
      const m = cd.match(/filename="?([^"]+)"?/);
      const filename = m ? m[1] : `holdings.${format}`;
      const blob = new Blob([res.data], {
        type: res.headers["content-type"] ||
          (format === "xlsx"
            ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            : "text/csv"),
      });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(link.href);
      toast.success(`Downloaded ${filename}`);
    } catch (err) {
      const status = err.response?.status;
      if (status === 404) {
        toast.error("No holdings to export yet. Import a portfolio first.");
      } else if (status === 403) {
        toast.error("You don't have access to this client's portfolio.");
      } else {
        toast.error("Could not export holdings — please try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant={variant}
          size={size}
          disabled={busy}
          className={className}
          data-testid={testId}
        >
          {busy ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <Download className="w-4 h-4 mr-2" />
          )}
          {label}
          <ChevronDown className="w-3 h-3 ml-1.5 opacity-60" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        <DropdownMenuItem
          onClick={() => triggerDownload("xlsx")}
          data-testid={`${testId}-xlsx`}
          className="gap-2"
        >
          <Sheet className="w-4 h-4 text-emerald-600" />
          <div className="flex flex-col">
            <span className="text-sm">Excel (.xlsx)</span>
            <span className="text-[10px] text-slate-500">Formatted, with totals</span>
          </div>
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => triggerDownload("csv")}
          data-testid={`${testId}-csv`}
          className="gap-2"
        >
          <FileText className="w-4 h-4 text-indigo-600" />
          <div className="flex flex-col">
            <span className="text-sm">CSV (.csv)</span>
            <span className="text-[10px] text-slate-500">Plain text, universal</span>
          </div>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
