import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { KeyRound, RefreshCw, FlaskConical, CheckCircle2, XCircle, Sparkles, Server, Cloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const CasConfigSection = () => {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  // CAS parser provider switch (Claude Vision vs casparser.in API)
  const [provider, setProvider] = useState(null);
  const [providerSaving, setProviderSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cfgRes, provRes] = await Promise.all([
        axios.get(`${API}/admin/cas-config`, { withCredentials: true }),
        axios.get(`${API}/admin/cas-parser-provider`, { withCredentials: true })
          .catch(() => ({ data: { provider: "casparser_api" } })),
      ]);
      setConfig(cfgRes.data);
      setProvider(provRes.data);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to load CAS config");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const reloadPool = async () => {
    setReloading(true);
    try {
      const res = await axios.post(`${API}/admin/cas-config/reload`, {}, { withCredentials: true });
      setConfig(res.data.config);
      setTestResult(null);
      toast.success(`Pool reloaded · ${res.data.pool_size} key(s) from GSM`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Reload failed");
    } finally {
      setReloading(false);
    }
  };

  const toggleSandbox = async (checked) => {
    setSaving(true);
    try {
      const res = await axios.put(
        `${API}/admin/cas-config`,
        { use_sandbox: checked },
        { withCredentials: true }
      );
      setConfig(res.data.config);
      setTestResult(null);
      toast.success(checked ? "Sandbox mode ON" : "Sandbox mode OFF");
    } catch (err) {
      toast.error("Toggle failed");
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await axios.post(`${API}/admin/cas-config/test`, {}, { withCredentials: true });
      setTestResult(res.data);
      if (res.data.ok) toast.success(`Connection OK — ${res.data.mode} mode`);
      else toast.error(res.data.error || "Test failed");
    } catch (err) {
      setTestResult({ ok: false, error: err.response?.data?.detail || "Test failed" });
      toast.error("Test failed");
    } finally {
      setTesting(false);
    }
  };

  // Switch the active CAS parser provider (Claude Vision vs casparser.in API)
  const setProviderSwitch = async (newProvider) => {
    setProviderSaving(true);
    try {
      const res = await axios.put(
        `${API}/admin/cas-parser-provider`,
        { provider: newProvider },
        { withCredentials: true }
      );
      if (res.data?.ok) {
        toast.success(
          newProvider === "claude_vision"
            ? "Switched to Claude Vision parser"
            : newProvider === "nivesh_cas_parser"
              ? "Switched to Nivesh CAS Parser (Document AI)"
              : "Switched to casparser.in API"
        );
        load();
      } else {
        toast.error(res.data?.error || "Switch failed");
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Switch failed");
    } finally {
      setProviderSaving(false);
    }
  };

  return (
    <Card
      data-testid="admin-cas-config"
      className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none overflow-hidden"
    >
      <CardContent className="p-5 sm:p-6">
        <div className="flex items-start justify-between gap-3 mb-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 flex items-center justify-center">
              <KeyRound className="w-5 h-5" strokeWidth={2} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">
                CAS Parser API
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Manage the API key used for CAS PDF parsing + CAS Connect widget.
              </p>
            </div>
          </div>
          <Button
            data-testid="cas-config-refresh"
            variant="ghost"
            size="sm"
            onClick={load}
            disabled={loading}
            className="text-slate-500 dark:text-slate-400"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>

        {loading && !config ? (
          <div className="py-6 text-center text-sm text-slate-500 dark:text-slate-400">Loading…</div>
        ) : config ? (
          <div className="space-y-4">
            {/* Current state grid */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-700">
                <div className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400 mb-1">
                  Active Key
                </div>
                <div className="font-mono text-xs text-slate-900 dark:text-white break-all" data-testid="cas-active-key">
                  {config.active_key_masked || "—"}
                </div>
              </div>
              <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-700">
                <div className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400 mb-1">
                  Pool Size
                </div>
                <div className="font-mono text-xs text-slate-900 dark:text-white" data-testid="cas-pool-size">
                  {config.pool_size ?? 0} key{config.pool_size === 1 ? "" : "s"}
                </div>
              </div>
              <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-700">
                <div className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400 mb-1">
                  Base URL
                </div>
                <div className="font-mono text-xs text-slate-900 dark:text-white truncate">
                  {config.base_url}
                </div>
              </div>
            </div>

            {/* Parser provider switch (Claude Vision vs casparser.in) */}
            {provider && (
              <div className="rounded-xl border-2 border-indigo-200 dark:border-indigo-800 bg-gradient-to-br from-indigo-50/60 via-white to-white dark:from-indigo-900/20 dark:via-slate-900 dark:to-slate-900 p-4" data-testid="cas-provider-toggle">
                <div className="flex items-center gap-2 mb-3">
                  <Sparkles className="w-4 h-4 text-indigo-600" />
                  <span className="text-sm font-bold text-slate-900 dark:text-slate-100">CAS Parser Provider</span>
                  <span className="ml-auto text-[10px] uppercase tracking-wider text-indigo-600 font-bold">
                    Active: {
                      provider.provider === "claude_vision" ? "Claude Vision"
                      : provider.provider === "nivesh_cas_parser" ? "Nivesh Parser"
                      : "casparser.in"
                    }
                  </span>
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400 mb-3">
                  Switch between three CAS parsing engines: <strong>casparser.in</strong> (text-based PDFs, paid credits),{" "}
                  <strong>Claude Vision</strong> (Sonnet 4.5 image OCR via Emergent LLM key), or{" "}
                  <strong>Nivesh Parser</strong> (Google Document AI — works on scanned PDFs, requires GCP service account).
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  <button
                    type="button"
                    onClick={() => setProviderSwitch("casparser_api")}
                    disabled={providerSaving || provider.provider === "casparser_api"}
                    data-testid="cas-provider-casparser"
                    className={`text-left p-3 rounded-xl border-2 transition-colors ${
                      provider.provider === "casparser_api"
                        ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30"
                        : "border-slate-200 dark:border-slate-700 hover:border-indigo-300 bg-white dark:bg-slate-900"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <Server className="w-4 h-4 text-slate-500" />
                      <span className="text-sm font-bold text-slate-900 dark:text-slate-100">casparser.in API</span>
                      {provider.casparser_api_configured ? (
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 ml-auto" />
                      ) : (
                        <XCircle className="w-3.5 h-3.5 text-rose-500 ml-auto" />
                      )}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      Hosted endpoint · structured JSON · paid credits
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setProviderSwitch("claude_vision")}
                    disabled={providerSaving || provider.provider === "claude_vision"}
                    data-testid="cas-provider-claude"
                    className={`text-left p-3 rounded-xl border-2 transition-colors ${
                      provider.provider === "claude_vision"
                        ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30"
                        : "border-slate-200 dark:border-slate-700 hover:border-indigo-300 bg-white dark:bg-slate-900"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <Sparkles className="w-4 h-4 text-indigo-500" />
                      <span className="text-sm font-bold text-slate-900 dark:text-slate-100">Claude Vision</span>
                      {provider.claude_vision_configured ? (
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 ml-auto" />
                      ) : (
                        <XCircle className="w-3.5 h-3.5 text-rose-500 ml-auto" />
                      )}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      Image OCR via {provider.claude_model || "claude-sonnet-4-5"} · Emergent LLM key
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setProviderSwitch("nivesh_cas_parser")}
                    disabled={providerSaving || provider.provider === "nivesh_cas_parser"}
                    data-testid="cas-provider-nivesh"
                    className={`text-left p-3 rounded-xl border-2 transition-colors ${
                      provider.provider === "nivesh_cas_parser"
                        ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30"
                        : "border-slate-200 dark:border-slate-700 hover:border-indigo-300 bg-white dark:bg-slate-900"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <Sparkles className="w-4 h-4 text-emerald-500" />
                      <span className="text-sm font-bold text-slate-900 dark:text-slate-100">Nivesh Parser</span>
                      {provider.nivesh_cas_parser_configured ? (
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 ml-auto" />
                      ) : (
                        <XCircle className="w-3.5 h-3.5 text-rose-500 ml-auto" />
                      )}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      Google Document AI · scanned PDFs · pay-per-page
                    </div>
                  </button>
                </div>
                {providerSaving && (
                  <div className="text-[11px] text-slate-400 mt-2 flex items-center gap-1.5">
                    <RefreshCw className="w-3 h-3 animate-spin" /> Switching…
                  </div>
                )}
              </div>
            )}

            {/* Sandbox toggle */}
            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-700">
              <div className="flex items-center gap-3">
                <FlaskConical className={`w-4 h-4 ${config.use_sandbox ? "text-amber-500" : "text-slate-400"}`} />
                <div>
                  <Label htmlFor="cas-sandbox-toggle" className="text-sm font-medium text-slate-900 dark:text-white cursor-pointer">
                    Sandbox Mode
                  </Label>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {config.use_sandbox
                      ? "Returning sample CAS data (no real parsing)"
                      : "Using production API"}
                  </p>
                </div>
              </div>
              <Switch
                id="cas-sandbox-toggle"
                data-testid="cas-sandbox-toggle"
                checked={!!config.use_sandbox}
                onCheckedChange={toggleSandbox}
                disabled={saving}
              />
            </div>

            {/* GSM-managed key pool */}
            <div className="rounded-xl border border-sky-200 dark:border-sky-900 bg-sky-50/50 dark:bg-sky-950/30 p-4" data-testid="cas-gsm-panel">
              <div className="flex items-center gap-2 mb-2">
                <Cloud className="w-4 h-4 text-sky-600" />
                <span className="text-sm font-bold text-slate-900 dark:text-slate-100">
                  Key pool · managed in Google Secret Manager
                </span>
              </div>
              <p className="text-xs text-slate-600 dark:text-slate-400 mb-3">
                Keys are no longer editable from this console. Publish a new version with:
              </p>
              <pre className="text-[11px] bg-slate-900 text-slate-100 rounded-lg p-3 overflow-x-auto mb-3">
                {`echo -n "<space-or-newline-separated keys>" \\\n  | gcloud secrets versions add ${config.gsm_secret_name || "casparser-api-keys-<env>"} \\\n      --data-file=- --project=${config.gsm_project || "niveshdataintelligence"}`}
              </pre>
              <div className="flex items-center gap-2 flex-wrap">
                <Button
                  data-testid="cas-reload-pool"
                  onClick={reloadPool}
                  disabled={reloading}
                  size="sm"
                  className="bg-sky-600 hover:bg-sky-700 text-white rounded-lg"
                >
                  {reloading ? <RefreshCw className="w-3.5 h-3.5 mr-2 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5 mr-2" />}
                  Reload pool from GSM
                </Button>
                <span className="text-[11px] text-slate-500 dark:text-slate-400">
                  Secret: <code className="font-mono">{config.gsm_secret_name || "—"}</code>{" "}
                  · Project: <code className="font-mono">{config.gsm_project || "—"}</code>
                </span>
              </div>
            </div>

            {/* Test connection */}
            <div className="pt-3 border-t border-slate-100 dark:border-slate-700">
              <Button
                data-testid="cas-test-connection"
                onClick={testConnection}
                disabled={testing}
                variant="outline"
                className="rounded-xl border-slate-200 dark:border-slate-700"
              >
                {testing ? (
                  <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <CheckCircle2 className="w-4 h-4 mr-2" />
                )}
                Test Connection
              </Button>
              {testResult && (
                <div
                  data-testid="cas-test-result"
                  className={`mt-3 p-3 rounded-xl border flex items-start gap-2 text-sm ${
                    testResult.ok
                      ? "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-900 text-emerald-700 dark:text-emerald-400"
                      : "bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-900 text-red-700 dark:text-red-400"
                  }`}
                >
                  {testResult.ok ? (
                    <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" strokeWidth={2} />
                  ) : (
                    <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" strokeWidth={2} />
                  )}
                  <div className="flex-1">
                    {testResult.ok ? (
                      <>
                        Connection OK — <b className="uppercase">{testResult.mode}</b> mode
                        {testResult.expires_in && (
                          <span className="text-xs ml-1">(token valid {testResult.expires_in}s)</span>
                        )}
                      </>
                    ) : (
                      <>{testResult.error}</>
                    )}
                  </div>
                </div>
              )}
            </div>

          </div>
        ) : (
          <div className="py-6 text-center text-sm text-red-500">Couldn't load config</div>
        )}
      </CardContent>
    </Card>
  );
};

export default CasConfigSection;
