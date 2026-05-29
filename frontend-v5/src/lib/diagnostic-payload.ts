import { getAllFlags } from "./feature-flags";
import { getHealthRegistry, getOverallHealth, type ComponentHealthRecord } from "./health-registry";
import { getCrashRegistry, fingerprintId, type CrashFingerprint } from "./crash-fingerprint";

const BUILD_VERSION = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_APP_VERSION ?? "unknown";
const GIT_SHA = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_GIT_SHA ?? "local-dev";

const GITHUB_REPO = "https://github.com/your-org/nivesh-copilot"; // update with real repo URL

export interface DiagnosticPayload {
  build: { version: string; gitSha: string; timestamp: string };
  component: string | null;
  stack: string | null;
  fingerprint: string | null;
  browser: { userAgent: string; language: string; online: boolean; cookiesEnabled: boolean };
  memory: { used?: number; total?: number; limit?: number } | null;
  timestamp: string;
  flags: Record<string, boolean>;
  health: { overall: string; components: Record<string, ComponentHealthRecord> };
  recentCrashes: CrashFingerprint[];
}

export function buildDiagnosticPayload(opts?: {
  error?: Error;
  component?: string;
}): DiagnosticPayload {
  const ts = new Date().toISOString();

  // Chrome-only memory API; undefined on other browsers
  type PerfWithMemory = Performance & {
    memory?: { usedJSHeapSize: number; totalJSHeapSize: number; jsHeapSizeLimit: number };
  };
  const mem = (performance as PerfWithMemory).memory;

  const fp =
    opts?.error && opts?.component
      ? fingerprintId(opts.error, opts.component, BUILD_VERSION)
      : null;

  const healthEntries = Object.fromEntries(getHealthRegistry()) as Record<
    string,
    ComponentHealthRecord
  >;

  return {
    build: { version: BUILD_VERSION, gitSha: GIT_SHA, timestamp: ts },
    component: opts?.component ?? null,
    stack: opts?.error?.stack ?? null,
    fingerprint: fp,
    browser: {
      userAgent: navigator.userAgent,
      language: navigator.language,
      online: navigator.onLine,
      cookiesEnabled: navigator.cookieEnabled,
    },
    memory: mem
      ? { used: mem.usedJSHeapSize, total: mem.totalJSHeapSize, limit: mem.jsHeapSizeLimit }
      : null,
    timestamp: ts,
    flags: getAllFlags(),
    health: { overall: getOverallHealth(), components: healthEntries },
    recentCrashes: [...getCrashRegistry().values()].slice(-20),
  };
}

export function formatAsGitHubIssueUrl(payload: DiagnosticPayload): string {
  const title = `[V5] Crash in ${payload.component ?? "unknown"} — ${payload.fingerprint ?? "no-fp"} (${payload.build.version})`;
  const body = [
    `**Fingerprint:** \`${payload.fingerprint ?? "n/a"}\``,
    `**Build:** ${payload.build.version} @ ${payload.build.gitSha}`,
    `**Component:** ${payload.component ?? "unknown"}`,
    `**Browser:** ${payload.browser.userAgent}`,
    ``,
    `**Stack trace:**`,
    `\`\`\``,
    payload.stack ?? "(no stack)",
    `\`\`\``,
    ``,
    `**Diagnostics (JSON):**`,
    `\`\`\`json`,
    JSON.stringify(payload, null, 2).slice(0, 3000),
    `\`\`\``,
  ].join("\n");

  return `${GITHUB_REPO}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
}

export async function copyDiagnosticsToClipboard(payload: DiagnosticPayload): Promise<void> {
  await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
}
