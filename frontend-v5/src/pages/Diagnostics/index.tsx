import { useEffect, useState } from "react";
import { Activity, Flag, Bug, Globe, Copy, ExternalLink, CheckCircle, XCircle, AlertCircle } from "lucide-react";
import { getHealthRegistry, getOverallHealth, type ComponentHealthRecord } from "@/lib/health-registry";
import { getAllFlags, enableFlag, disableFlag, type WidgetFlagKey } from "@/lib/feature-flags";
import { getCrashRegistry, type CrashFingerprint } from "@/lib/crash-fingerprint";
import { buildDiagnosticPayload, copyDiagnosticsToClipboard, formatAsGitHubIssueUrl } from "@/lib/diagnostic-payload";

const BUILD_VERSION =
  (import.meta as unknown as { env: Record<string, string> }).env?.VITE_APP_VERSION ?? "unknown";
const GIT_SHA =
  (import.meta as unknown as { env: Record<string, string> }).env?.VITE_GIT_SHA ?? "local-dev";

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: "healthy" | "degraded" | "dead" | string }) {
  const map: Record<string, string> = {
    healthy: "text-pos bg-[rgb(var(--pos)/0.10)]",
    degraded: "text-warm bg-[rgb(var(--warm)/0.10)]",
    dead: "text-neg bg-[rgb(var(--neg)/0.10)]",
  };
  return (
    <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded uppercase tracking-[.1em] ${map[status] ?? "text-ink-3 bg-surface-2"}`}>
      {status}
    </span>
  );
}

function SectionHeader({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className="text-ink-3">{icon}</span>
      <span className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">{label}</span>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function DiagnosticsPage() {
  const [apiLatency, setApiLatency] = useState<number | null>(null);
  const [apiStatus, setApiStatus] = useState<"checking" | "ok" | "down">("checking");
  const [, forceUpdate] = useState(0);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const t0 = performance.now();
    fetch("/api/auth/me", { credentials: "include" })
      .then((r) => {
        setApiLatency(Math.round(performance.now() - t0));
        setApiStatus(r.ok || r.status === 401 ? "ok" : "down");
      })
      .catch(() => {
        setApiLatency(Math.round(performance.now() - t0));
        setApiStatus("down");
      });
  }, []);

  const healthEntries = [...getHealthRegistry().entries()];
  const overall = getOverallHealth();
  const flags = getAllFlags();
  const crashes = [...getCrashRegistry().values()].sort((a, b) => b.lastSeen - a.lastSeen);

  const payload = buildDiagnosticPayload();

  async function handleCopy() {
    await copyDiagnosticsToClipboard(payload);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function toggleFlag(key: WidgetFlagKey, currentValue: boolean) {
    if (currentValue) disableFlag(key, "manual override via diagnostics");
    else enableFlag(key);
    forceUpdate((n) => n + 1);
  }

  // Memory info (Chrome-only)
  type PerfMem = { usedJSHeapSize: number; totalJSHeapSize: number; jsHeapSizeLimit: number };
  const mem = (performance as unknown as { memory?: PerfMem }).memory;

  return (
    <div className="min-h-screen bg-bg text-ink px-6 py-8 lg:px-10 lg:py-10">
      <div className="max-w-[920px] mx-auto w-full">

        {/* Header */}
        <div className="mb-8">
          <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Platform</div>
          <h1 className="font-display text-3xl tracking-tightish mt-1">Diagnostics</h1>
          <div className="flex items-center gap-3 mt-3">
            <span className="font-mono text-[11px] text-ink-3 bg-surface-1 border border-hairline rounded px-2 py-1">
              v{BUILD_VERSION}
            </span>
            <span className="font-mono text-[11px] text-ink-3 bg-surface-1 border border-hairline rounded px-2 py-1">
              {GIT_SHA}
            </span>
            <StatusBadge status={overall} />
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

          {/* API Health */}
          <div className="rounded-lg bg-surface-1 border border-hairline p-5">
            <SectionHeader icon={<Activity className="h-4 w-4" />} label="API Health" />
            <div className="flex items-center gap-3 text-[13px]">
              {apiStatus === "checking" ? (
                <span className="text-ink-3">Checking…</span>
              ) : apiStatus === "ok" ? (
                <CheckCircle className="h-4 w-4 text-pos" />
              ) : (
                <XCircle className="h-4 w-4 text-neg" />
              )}
              <span className="text-ink">
                {apiStatus === "checking" ? "Connecting…" : apiStatus === "ok" ? "Reachable" : "Unreachable"}
              </span>
              {apiLatency !== null && (
                <span className="font-mono text-[10px] text-ink-4 ml-auto">{apiLatency}ms</span>
              )}
            </div>
          </div>

          {/* Browser info */}
          <div className="rounded-lg bg-surface-1 border border-hairline p-5">
            <SectionHeader icon={<Globe className="h-4 w-4" />} label="Browser" />
            <div className="space-y-1.5 text-[12px]">
              <div className="flex justify-between gap-2">
                <span className="text-ink-3 shrink-0">Online</span>
                <span className="font-mono text-[10px] text-ink-2 truncate">{navigator.onLine ? "Yes" : "No"}</span>
              </div>
              <div className="flex justify-between gap-2">
                <span className="text-ink-3 shrink-0">Language</span>
                <span className="font-mono text-[10px] text-ink-2">{navigator.language}</span>
              </div>
              {mem && (
                <div className="flex justify-between gap-2">
                  <span className="text-ink-3 shrink-0">Heap used</span>
                  <span className="font-mono text-[10px] text-ink-2">
                    {Math.round(mem.usedJSHeapSize / 1024 / 1024)}MB / {Math.round(mem.jsHeapSizeLimit / 1024 / 1024)}MB
                  </span>
                </div>
              )}
              <div className="mt-2 text-[10px] text-ink-4 font-mono break-all leading-relaxed">
                {navigator.userAgent.slice(0, 80)}…
              </div>
            </div>
          </div>

          {/* Component health */}
          <div className="rounded-lg bg-surface-1 border border-hairline p-5 lg:col-span-2">
            <SectionHeader icon={<Activity className="h-4 w-4" />} label="Component Health" />
            {healthEntries.length === 0 ? (
              <p className="text-[13px] text-ink-3">No components registered yet. Load the Dashboard to populate.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[12px]">
                  <thead>
                    <tr className="border-b border-hairline">
                      <th className="text-left font-mono text-[10px] text-ink-3 uppercase tracking-[.1em] pb-2 pr-4">Component</th>
                      <th className="text-left font-mono text-[10px] text-ink-3 uppercase tracking-[.1em] pb-2 pr-4">Status</th>
                      <th className="text-left font-mono text-[10px] text-ink-3 uppercase tracking-[.1em] pb-2 pr-4">Crashes</th>
                      <th className="text-left font-mono text-[10px] text-ink-3 uppercase tracking-[.1em] pb-2">Last FP</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[rgb(var(--line)/0.06)]">
                    {healthEntries.map(([name, rec]: [string, ComponentHealthRecord]) => (
                      <tr key={name}>
                        <td className="py-2 pr-4 font-medium">{name}</td>
                        <td className="py-2 pr-4"><StatusBadge status={rec.status} /></td>
                        <td className="py-2 pr-4 font-mono text-[10px] text-ink-3">{rec.crashCount}</td>
                        <td className="py-2 font-mono text-[10px] text-ink-4">{rec.lastFingerprintId ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Feature flags */}
          <div className="rounded-lg bg-surface-1 border border-hairline p-5">
            <SectionHeader icon={<Flag className="h-4 w-4" />} label="Feature Flags" />
            <div className="space-y-2">
              {Object.entries(flags).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between gap-2">
                  <span className="text-[12px] font-mono text-ink-2">{key}</span>
                  <button
                    onClick={() => toggleFlag(key as WidgetFlagKey, value)}
                    className={`relative h-5 w-9 rounded-full transition-colors ${value ? "bg-pos" : "bg-surface-2 border border-hairline"}`}
                  >
                    <span
                      className={`absolute top-0.5 h-4 w-4 rounded-full bg-bg transition-transform shadow-sm ${value ? "translate-x-4" : "translate-x-0.5"}`}
                    />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Recent crashes */}
          <div className="rounded-lg bg-surface-1 border border-hairline p-5">
            <SectionHeader icon={<Bug className="h-4 w-4" />} label="Recent Crashes" />
            {crashes.length === 0 ? (
              <div className="flex items-center gap-2 text-[13px] text-pos">
                <CheckCircle className="h-4 w-4" />
                No crashes recorded this session
              </div>
            ) : (
              <div className="space-y-3">
                {crashes.slice(0, 8).map((fp: CrashFingerprint) => (
                  <div key={fp.id} className="rounded-md bg-surface-2 border border-hairline p-3">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-[10px] text-neg font-bold">{fp.id}</span>
                      <AlertCircle className="h-3 w-3 text-neg" />
                      <span className="font-mono text-[10px] text-ink-4 ml-auto">×{fp.count}</span>
                    </div>
                    <p className="text-[11px] text-ink-2 truncate">{fp.errorMessage}</p>
                    <p className="text-[10px] text-ink-3 mt-0.5">{fp.affectedComponents.join(", ")}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Diagnostic actions */}
          <div className="rounded-lg bg-surface-1 border border-hairline p-5 lg:col-span-2">
            <SectionHeader icon={<Copy className="h-4 w-4" />} label="Diagnostics" />
            <div className="flex gap-3 flex-wrap">
              <button
                onClick={handleCopy}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-surface-2 border border-hairline text-[13px] text-ink-2 hover:text-ink transition-colors"
              >
                <Copy className="h-3.5 w-3.5" />
                {copied ? "Copied!" : "Copy diagnostics JSON"}
              </button>
              <a
                href={formatAsGitHubIssueUrl(payload)}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-surface-2 border border-hairline text-[13px] text-ink-2 hover:text-ink transition-colors"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Open GitHub issue
              </a>
              <a
                href="/dashboard"
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-accent text-on-accent text-[13px] font-medium hover:opacity-90 transition-opacity ml-auto"
              >
                ← Back to Dashboard
              </a>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
