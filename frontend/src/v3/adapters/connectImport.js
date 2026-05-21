// Connect SDK + import adapter — mirrors the V2 CasUploadButton flow
// (frontend/src/components/CasUploadButton.jsx) so V3 onboarding gets the
// same proven import path:
//
//   1. POST /api/casparser/access-token   → short-lived at_* token
//   2. Dynamically import("@cas-parser/connect") and open the widget with
//      enableInbox: true so Gmail CAS auto-fetch, CDSL OTP fetch, and PDF
//      upload are all available in-modal
//   3. Widget returns parsed CAS JSON (or null if cancelled)
//   4. POST /api/portfolio/import-connect → backend persists holdings
//
// Single function so screens don't need to know about the SDK shape. Caller
// supplies `onProgress` to surface the parser source / count as findings.

import axios from "axios";
import { BACKEND_URL } from "./apiClient";

const API = `${BACKEND_URL}/api`;
const cfg = { withCredentials: true };

const CONNECT_HINTS = {
  cas: { method: "upload" },   // user picked "Upload CAS statement"
  gmail: { method: "inbox" },  // user picked "Import from Gmail"
};

/**
 * Open the Connect SDK widget and persist the parsed result.
 *
 * @param {object} args
 * @param {"cas"|"gmail"} args.method - which entry point the user picked
 * @param {(msg:string)=>void} [args.onProgress] - status updates for the UI
 * @returns {Promise<{ ok, count?, investor?, holdings?, error?, cancelled? }>}
 */
export async function openConnectAndImport({ method = "cas", onProgress } = {}) {
  const log = (m) => { if (onProgress) onProgress(m); };
  try {
    log("Minting access token…");
    const tokenRes = await axios.post(`${API}/casparser/access-token`, {}, cfg);
    const accessToken = tokenRes?.data?.access_token;
    if (!accessToken) {
      return { ok: false, error: { message: "No access token returned" } };
    }

    log("Opening Connect widget…");
    const mod = await import("@cas-parser/connect");
    const openWidget = mod.open || mod.PortfolioConnect?.open || mod.default?.open;
    if (typeof openWidget !== "function") {
      return { ok: false, error: { message: "Connect SDK did not expose .open()" } };
    }

    const hint = CONNECT_HINTS[method] || CONNECT_HINTS.cas;
    const result = await openWidget({
      accessToken,
      config: {
        enableGenerator: true,                // MF email request via KFintech
        enableCdslFetch: true,                // CDSL OTP flow
        enableInbox: true,                    // Gmail CAS auto-fetch
        ...hint,
        inbox: {
          // Must keep the SPA basename so React Router matches CasCallback
          // and the popup posts inbox_token back to the opener.
          redirectUri: `${window.location.origin}/v2/cas-callback`,
        },
      },
    });

    const parsed = result?.data;
    if (!parsed) {
      return { ok: false, cancelled: true };
    }

    log("Saving holdings…");
    const importRes = await axios.post(
      `${API}/portfolio/import-connect`,
      { data: parsed, metadata: result?.metadata || {}, portfolio_id: "" },
      cfg,
    );
    const data = importRes.data || {};
    return {
      ok: true,
      count: data.count ?? 0,
      investor: data.investor || null,
      holdings: data.holdings || [],
    };
  } catch (err) {
    const msg = err?.message || "";
    if (msg.includes("closed by user") || msg.includes("cancel")) {
      return { ok: false, cancelled: true };
    }
    return {
      ok: false,
      error: {
        status: err?.response?.status || 0,
        message: err?.response?.data?.detail || err?.message || "Import failed",
      },
    };
  }
}
