import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { Loader2, ExternalLink, Copy, AlertTriangle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * Admin → Infra & Data → NIDP Diagnostic Dump
 *
 * One button: bundles feed-health verdict, recent FAILED runs, validation
 * findings, deployed image tags, logs for non-green feeds, schema
 * migrations, and per-feed data depth into a single private GitHub gist.
 * The URL is what gets pasted into chat for Claude to read — replaces
 * screenshot-and-paste loops while debugging NIDP.
 *
 * Backend: POST /api/admin/nidp/dump  (runs dump_for_claude.sh on the VM)
 */
export default function NidpDumpRunner() {
  const [running, setRunning]   = useState(false);
  const [result, setResult]     = useState(null);   // { gist_url, tmp_path, stdout_tail }
  const [error, setError]       = useState(null);
  const [health, setHealth]     = useState(null);   // { exists, executable, gh_on_path }

  // Pre-flight: confirm the script is on this host + gh is installed
  // before showing the Run button. Keeps the UX from offering an action
  // that's guaranteed to fail.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await axios.get(`${API}/api/admin/nidp/script`, { withCredentials: true });
        if (!cancelled) setHealth(r.data);
      } catch (e) {
        if (!cancelled) setHealth({ exists: false, error: e?.response?.data?.detail || String(e) });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const runDump = useCallback(async () => {
    if (running) return;
    setRunning(true);
    setError(null);
    setResult(null);
    toast.loading("Running NIDP dump — querying Postgres + gcloud + uploading gist...", { id: "nidp-dump" });
    try {
      const r = await axios.post(
        `${API}/api/admin/nidp/dump`, {},
        { withCredentials: true, timeout: 200 * 1000 },  // 200s — backend caps at 180s
      );
      setResult(r.data);
      if (r.data?.gist_url) {
        toast.success("Dump uploaded. Click the URL to copy.", { id: "nidp-dump" });
      } else {
        toast.success(`Dump written to ${r.data?.tmp_path || "/tmp/"} (gh CLI missing on VM — paste file contents instead).`,
                      { id: "nidp-dump" });
      }
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || String(e);
      setError(detail);
      toast.error("Dump failed — see panel for details.", { id: "nidp-dump" });
    } finally {
      setRunning(false);
    }
  }, [running]);

  const copyUrl = useCallback(() => {
    if (!result?.gist_url) return;
    navigator.clipboard.writeText(result.gist_url);
    toast.success("Gist URL copied — paste into chat.");
  }, [result]);

  // ── Render ────────────────────────────────────────────────────────
  const scriptMissing = health && !health.exists;
  const ghMissing     = health && health.exists && !health.gh_on_path;

  return (
    <section
      data-testid="admin-nidp-dump"
      className="rounded-2xl border border-slate-100 dark:border-slate-700 bg-white dark:bg-slate-800 p-5"
    >
      <div className="flex items-start justify-between gap-4 mb-3">
        <div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white">
            NIDP Diagnostic Dump
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-xl">
            Bundles feed-health verdict, recent FAILED runs, validation findings,
            deployed Cloud Run images, recent logs for non-green feeds, schema
            migrations, and per-feed data depth into a private GitHub gist.
            Paste the resulting URL into chat for diagnosis.
          </p>
        </div>
        <button
          type="button"
          onClick={runDump}
          disabled={running || scriptMissing}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 transition-colors"
        >
          {running ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Running…
            </>
          ) : (
            <>Run dump</>
          )}
        </button>
      </div>

      {/* Pre-flight banners */}
      {scriptMissing && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-3 py-2 text-xs text-red-700 dark:text-red-300">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <div>
            <strong>Script not found on this host.</strong> Expected at <code>{health?.script_path}</code>.
            Pull the latest <code>nidp</code> branch on the API server: <code>git pull origin nidp</code>.
          </div>
        </div>
      )}
      {ghMissing && (
        <div className="flex items-start gap-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 px-3 py-2 text-xs text-amber-700 dark:text-amber-300 mb-3">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <div>
            <strong>gh CLI not installed on this host.</strong> The dump will still run and write
            to <code>/tmp/nidp_dump_*.md</code>, but won't auto-upload to a gist.
            Install + auth: <code>sudo apt install gh && gh auth login</code>.
          </div>
        </div>
      )}

      {/* Result */}
      {result?.gist_url && (
        <div className="rounded-lg bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 px-4 py-3 mt-3">
          <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300 text-sm font-medium">
            <CheckCircle2 className="w-4 h-4" />
            Dump uploaded
          </div>
          <div className="mt-2 flex items-center gap-2">
            <a
              href={result.gist_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 truncate text-xs font-mono text-indigo-600 dark:text-indigo-400 hover:underline inline-flex items-center gap-1"
            >
              {result.gist_url}
              <ExternalLink className="w-3 h-3" />
            </a>
            <button
              type="button"
              onClick={copyUrl}
              className="inline-flex items-center gap-1 rounded border border-slate-200 dark:border-slate-600 px-2 py-1 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700"
            >
              <Copy className="w-3 h-3" /> Copy
            </button>
          </div>
          <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-2">
            Paste this URL into chat. The gist is <em>secret</em> (URL-only access) — treat the link like a password.
          </p>
        </div>
      )}

      {result && !result.gist_url && (
        <div className="rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 px-4 py-3 mt-3 text-xs">
          <div className="font-medium text-amber-700 dark:text-amber-300">
            Dump completed but no gist URL was returned.
          </div>
          {result.tmp_path && (
            <div className="mt-2 text-slate-600 dark:text-slate-300">
              File on the API server: <code>{result.tmp_path}</code>
            </div>
          )}
          {result.stdout_tail && (
            <details className="mt-2">
              <summary className="cursor-pointer text-slate-600 dark:text-slate-400">Last 1500 bytes of script output</summary>
              <pre className="mt-2 max-h-64 overflow-auto bg-slate-50 dark:bg-slate-900 p-2 rounded text-[11px] text-slate-700 dark:text-slate-300 whitespace-pre-wrap break-words">
                {result.stdout_tail}
              </pre>
            </details>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 mt-3 text-xs text-red-700 dark:text-red-300">
          <div className="font-medium flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" /> Dump failed
          </div>
          <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words text-[11px]">
            {error}
          </pre>
        </div>
      )}
    </section>
  );
}
