import React, { useState } from "react";
import axios from "axios";
import { Sparkles, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

/**
 * CAS Parser Portfolio Connect widget trigger.
 *
 * One button → opens the official CAS Parser modal that handles:
 *   • PDF upload (any size — uploads go direct to CAS Parser, not our backend)
 *   • Gmail inbox import of CAS statements
 *   • CDSL OTP live-holdings fetch
 *
 * Flow: backend mints a short-lived `at_` access token, widget opens, user
 * imports, widget returns parsed ParsedData, we POST it to /portfolio/import-connect.
 */
export default function CasConnectButton({ onSuccess, className = "", variant = "default", size = "default", label = "Import via CAS Connect", testId = "cas-connect-btn" }) {
  const [loading, setLoading] = useState(false);

  const openConnect = async () => {
    setLoading(true);
    try {
      // 1. Mint access token from backend
      const tokenRes = await axios.post(
        `${API}/casparser/access-token`,
        {},
        { withCredentials: true }
      );
      const accessToken = tokenRes.data?.access_token;
      if (!accessToken) throw new Error("No access token returned");

      // 2. Dynamically import the SDK (keeps initial bundle small)
      const mod = await import("@cas-parser/connect");
      // The npm package exposes `open` as a named export; the `PortfolioConnect`
      // export is a React component, not a class with static methods.
      const openWidget = mod.open || mod.PortfolioConnect?.open || mod.default?.open;
      if (typeof openWidget !== "function") {
        throw new Error("SDK did not expose .open()");
      }

      // 3. Launch the widget modal
      const result = await openWidget({
        accessToken,
        config: {
          enableGenerator: true,   // MF email request via KFintech
          enableCdslFetch: true,   // CDSL OTP flow
          enableInbox: true,       // Gmail CAS auto-fetch
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

      // 4. Persist on backend
      const importRes = await axios.post(
        `${API}/portfolio/import-connect`,
        { data: parsed, metadata: result?.metadata || {} },
        { withCredentials: true }
      );
      const count = importRes.data?.count ?? 0;
      const investor = importRes.data?.investor;
      toast.success(
        `Imported ${count} holdings${investor ? ` for ${investor}` : ""}`
      );
      if (onSuccess) onSuccess(importRes.data);
    } catch (err) {
      // SDK throws "Widget closed by user" when user cancels — soft-handle it
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
          <Sparkles className="w-4 h-4 mr-2" /> {label}
        </>
      )}
    </Button>
  );
}
