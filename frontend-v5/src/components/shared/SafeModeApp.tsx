import { useEffect, useState } from "react";
import { ShieldAlert, RefreshCw, Copy, AlertTriangle } from "lucide-react";
import { getAllFlags } from "@/lib/feature-flags";
import { buildDiagnosticPayload, copyDiagnosticsToClipboard } from "@/lib/diagnostic-payload";
import { apiFetch } from "@/services/api/authed-fetch";

interface SafeModeAppProps {
  error?: Error;
  onReset: () => void;
}

export function SafeModeApp({ error, onReset }: SafeModeAppProps) {
  const [apiStatus, setApiStatus] = useState<"checking" | "ok" | "down">("checking");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    apiFetch("/api/auth/me")
      .then((r) => setApiStatus(r.ok || r.status === 401 ? "ok" : "down"))
      .catch(() => setApiStatus("down"));
  }, []);

  const flags = getAllFlags();
  const disabled = Object.entries(flags)
    .filter(([, v]) => !v)
    .map(([k]) => k.replace(/_/g, " "));

  const payload = buildDiagnosticPayload({ error, component: "root" });

  async function handleCopy() {
    await copyDiagnosticsToClipboard(payload);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="min-h-screen bg-bg text-ink flex flex-col items-center justify-center p-8">
      <div className="max-w-[520px] w-full">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <ShieldAlert className="h-7 w-7 text-warm shrink-0" />
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Safe Mode</div>
            <h1 className="font-display text-2xl tracking-tightish">NiveshCopilot</h1>
          </div>
        </div>

        {/* API status */}
        <div className="rounded-lg bg-surface-1 border border-hairline p-5 mb-4">
          <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3 mb-3">Service Status</div>
          <div className="flex items-center gap-2 text-[13px]">
            <span
              className={`h-2 w-2 rounded-full shrink-0 ${
                apiStatus === "checking"
                  ? "bg-ink-4"
                  : apiStatus === "ok"
                  ? "bg-pos"
                  : "bg-neg"
              }`}
            />
            <span>
              Portfolio &amp; market data:{" "}
              <span className={apiStatus === "ok" ? "text-pos" : apiStatus === "down" ? "text-neg" : "text-ink-3"}>
                {apiStatus === "checking" ? "Checking…" : apiStatus === "ok" ? "Available" : "Unavailable"}
              </span>
            </span>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-lg bg-[rgb(var(--neg)/0.07)] border border-[rgb(var(--neg)/0.25)] p-4 mb-4">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle className="h-4 w-4 text-neg shrink-0" />
              <span className="font-mono text-[10px] uppercase tracking-[.12em] text-neg">Render error</span>
            </div>
            <p className="text-[12px] text-ink-2 font-mono break-all">{error.message}</p>
          </div>
        )}

        {/* Disabled features */}
        {disabled.length > 0 && (
          <div className="rounded-lg bg-surface-1 border border-hairline p-5 mb-4">
            <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3 mb-2">Disabled</div>
            <ul className="space-y-1">
              {disabled.map((f) => (
                <li key={f} className="flex items-center gap-2 text-[13px] text-ink-2 capitalize">
                  <span className="h-1.5 w-1.5 rounded-full bg-warm shrink-0" />
                  {f}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 mt-6">
          <button
            onClick={() => window.location.reload()}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-accent text-on-accent text-[13px] font-medium hover:opacity-90 transition-opacity"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Reload App
          </button>
          <button
            onClick={handleCopy}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-surface-1 border border-hairline text-[13px] text-ink-2 hover:text-ink transition-colors"
          >
            <Copy className="h-3.5 w-3.5" />
            {copied ? "Copied!" : "Copy diagnostics"}
          </button>
        </div>

        {/* Build info */}
        <div className="mt-8 font-mono text-[10px] text-ink-4">
          {payload.build.version} · {payload.build.gitSha}
        </div>
      </div>
    </div>
  );
}
