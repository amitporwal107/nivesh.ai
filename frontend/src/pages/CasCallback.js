import { useEffect, useState } from "react";
import { handleInboxCallback, isInboxCallbackPage } from "@cas-parser/connect";

/**
 * OAuth callback page for CAS Parser SDK Gmail inbox import.
 *
 * When the user authorizes Gmail in a popup, Google redirects here.
 * `handleInboxCallback()` reads the URL params (inbox_token, email, error),
 * posts them back to the opener window via postMessage, stores them in
 * sessionStorage, and closes the popup.
 */
export default function CasCallback() {
  const [status, setStatus] = useState("processing");

  useEffect(() => {
    if (isInboxCallbackPage()) {
      try {
        handleInboxCallback();
        setStatus("success");
      } catch (err) {
        console.error("CAS inbox callback error:", err);
        setStatus("error");
      }
    } else {
      setStatus("invalid");
    }
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950">
      <div className="text-center p-8">
        {status === "processing" && (
          <>
            <div className="w-8 h-8 border-3 border-emerald-600 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <p className="text-sm text-slate-600 dark:text-slate-400">Completing Gmail authorization...</p>
          </>
        )}
        {status === "success" && (
          <>
            <p className="text-sm text-emerald-600 font-medium">Gmail connected. This window will close automatically.</p>
          </>
        )}
        {status === "error" && (
          <p className="text-sm text-red-500">Something went wrong. Please close this window and try again.</p>
        )}
        {status === "invalid" && (
          <p className="text-sm text-slate-500">Invalid callback. Please close this window.</p>
        )}
      </div>
    </div>
  );
}
