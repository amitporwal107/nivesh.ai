import React, { useState } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * CasUploadButton — opens the casparser.in Portfolio Connect widget.
 *
 * Replaces the direct-upload-to-backend flow. The widget uploads the
 * PDF straight to casparser.in (browser → casparser.in), so there's no
 * 1.8 MiB nginx cap and no relay through our backend. After the widget
 * returns the parsed JSON we POST it to /api/portfolio/import-connect
 * which runs masterdata enrichment + saves holdings.
 *
 * Flow:
 *   1. Click → backend mints a short-lived `at_*` access token
 *   2. SDK widget opens (PDF upload | Gmail inbox | CDSL OTP all in-widget)
 *   3. Widget returns parsed CAS JSON
 *   4. We POST it to /portfolio/import-connect with optional portfolio_id
 *   5. onSuccess(result) fires once holdings are saved
 *
 * Prop signature kept identical to the previous direct-upload button so
 * existing call sites don't need JSX changes.
 */
export default function CasUploadButton({
  onSuccess,
  className = "",
  variant = "default",
  size = "default",
  label = "Import CAS PDF",
  testId = "cas-upload-btn",
  portfolioId = "",
  buttonIcon: ButtonIcon = Sparkles,
}) {
  const [loading, setLoading] = useState(false);

  const openConnect = async () => {
    setLoading(true);
    try {
      // 1. Mint access token
      const tokenRes = await axios.post(
        `${API}/casparser/access-token`,
        {},
        { withCredentials: true }
      );
      const accessToken = tokenRes.data?.access_token;
      if (!accessToken) throw new Error("No access token returned");

      // 2. Dynamically import the SDK (keeps initial bundle small)
      const mod = await import("@cas-parser/connect");
      const openWidget = mod.open || mod.PortfolioConnect?.open || mod.default?.open;
      if (typeof openWidget !== "function") {
        throw new Error("SDK did not expose .open()");
      }

      // 3. Launch the widget modal
      const result = await openWidget({
        accessToken,
        config: {
          enableGenerator: true, // MF email request via KFintech
          enableCdslFetch: true, // CDSL OTP flow
          enableInbox: true,     // Gmail CAS auto-fetch
          inbox: {
            redirectUri: `${window.location.origin}/cas-callback`,
          },
        },
      });

      const parsed = result?.data;
      if (!parsed) {
        toast.info("Import cancelled — no data received.");
        return;
      }

      // 4. Persist on backend (forward portfolio_id so multi-portfolio
      //    users get their holdings tagged correctly).
      const importRes = await axios.post(
        `${API}/portfolio/import-connect`,
        {
          data: parsed,
          metadata: result?.metadata || {},
          portfolio_id: portfolioId || "",
        },
        { withCredentials: true }
      );
      const count = importRes.data?.count ?? 0;
      const investor = importRes.data?.investor;
      toast.success(
        `Imported ${count} holdings${investor ? ` for ${investor}` : ""}`
      );
      if (onSuccess) onSuccess(importRes.data);
    } catch (err) {
      const msg = err?.message || "";
      if (msg.includes("closed by user") || msg.includes("cancel")) {
        toast.info("Import cancelled");
      } else if (err?.response?.status === 503) {
        toast.error("CAS Parser isn't configured on this environment.");
      } else {
        console.error("CAS Connect error:", err);
        toast.error(
          err?.response?.data?.detail || err?.message || "Import failed"
        );
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      onClick={openConnect}
      disabled={loading}
      variant={variant}
      size={size}
      className={className}
      data-testid={testId}
    >
      {loading ? (
        <>
          <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Opening…
        </>
      ) : (
        <>
          <ButtonIcon className="w-4 h-4 mr-2" /> {label}
        </>
      )}
    </Button>
  );
}
