import React, { useEffect, useState } from "react";
import axios from "axios";
import { ExternalLink, RefreshCw, Loader2, BarChart3, AlertTriangle } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * Embedded Grafana — auto-authenticated via the Anonymous-Admin SSO
 * configured on the VM (GF_AUTH_ANONYMOUS_ENABLED=true,
 * GF_AUTH_ANONYMOUS_ORG_ROLE=Admin). No login prompt, kiosk=tv hides
 * the Grafana chrome so it feels native to the Nivesh admin console.
 */
export default function NidpGrafanaEmbed() {
  const [embedUrl, setEmbedUrl] = useState(null);
  const [openUrl,  setOpenUrl]  = useState(null);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);
  const [iframeKey, setIframeKey] = useState(0);   // bump → reload iframe

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await axios.get(`${API}/api/admin/nidp/jobs`, { withCredentials: true });
        if (cancelled) return;
        setEmbedUrl(r.data?.grafana_embed_url || r.data?.grafana_url || null);
        setOpenUrl(r.data?.grafana_url || null);
      } catch (e) {
        if (!cancelled) setError(e?.response?.data?.detail || e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div
      data-testid="admin-nidp-grafana"
      className="rounded-2xl border border-slate-100 dark:border-slate-700 bg-white dark:bg-slate-800 overflow-hidden"
    >
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100 dark:border-slate-700">
        <div className="flex items-center gap-2 min-w-0">
          <BarChart3 className="w-4 h-4 text-indigo-600 shrink-0" />
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white truncate">
              NIDP Job Health · Grafana
            </h3>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
              Live cron pipeline metrics — no login required (anonymous-admin SSO)
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() => setIframeKey(k => k + 1)}
            data-testid="admin-nidp-grafana-reload"
            disabled={loading}
            title="Reload dashboard"
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs px-2.5 py-1.5 disabled:opacity-50"
          >
            {loading
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <RefreshCw className="w-3.5 h-3.5" />}
            Reload
          </button>
          {openUrl && (
            <a
              href={openUrl}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="admin-nidp-grafana-open"
              className="inline-flex items-center gap-1.5 rounded-md border border-indigo-200 dark:border-indigo-700 bg-indigo-50 dark:bg-indigo-900/30 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 text-xs px-2.5 py-1.5"
              title="Open dashboard in a new tab"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              Open
            </a>
          )}
        </div>
      </div>

      {loading && !embedUrl && (
        <div className="px-5 py-12 flex items-center justify-center text-xs text-slate-500">
          <Loader2 className="w-4 h-4 animate-spin mr-2" />
          Loading Grafana embed URL…
        </div>
      )}

      {error && (
        <div className="px-5 py-4 flex items-start gap-2 text-xs text-rose-700 bg-rose-50 dark:bg-rose-900/20 dark:text-rose-300">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold">Couldn't load Grafana embed URL</div>
            <div className="opacity-80">{String(error)}</div>
          </div>
        </div>
      )}

      {!loading && !error && embedUrl && (
        <div className="bg-slate-950">
          <iframe
            key={iframeKey}
            data-testid="admin-nidp-grafana-iframe"
            src={embedUrl}
            title="NIDP Job Health · Grafana"
            className="w-full"
            style={{ height: "calc(100vh - 280px)", minHeight: "760px", border: 0 }}
            // Same-origin iframe still benefits from sandbox to limit
            // accidental top-level navigation from Grafana links.
            sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox"
            referrerPolicy="no-referrer-when-downgrade"
          />
        </div>
      )}

      {!loading && !error && !embedUrl && (
        <div className="px-5 py-8 text-xs text-slate-500 text-center">
          Grafana URL not configured. Set <code>NIDP_GRAFANA_URL</code> in the backend env.
        </div>
      )}
    </div>
  );
}
