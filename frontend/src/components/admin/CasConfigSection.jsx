import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { KeyRound, RefreshCw, Eye, EyeOff, FlaskConical, CheckCircle2, XCircle, Save, Sparkles, Server } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const CasConfigSection = () => {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [newKey, setNewKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
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

  const saveKey = async () => {
    if (!newKey.trim()) {
      toast.error("Enter a key first");
      return;
    }
    setSaving(true);
    try {
      const res = await axios.put(
        `${API}/admin/cas-config`,
        { prod_key: newKey.trim() },
        { withCredentials: true }
      );
      setConfig(res.data.config);
      setNewKey("");
      setTestResult(null);
      toast.success("API key updated");
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Update failed");
    } finally {
      setSaving(false);
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
                  Prod Key
                </div>
                <div className="font-mono text-xs text-slate-900 dark:text-white" data-testid="cas-prod-key">
                  {config.prod_key_configured ? config.prod_key_masked : "Not configured"}
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
                    Active: {provider.provider === "claude_vision" ? "Claude Vision" : "casparser.in"}
                  </span>
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400 mb-3">
                  Switch between Anthropic Claude Vision (image-based parsing via Sonnet 4.5) and the
                  casparser.in API. Claude Vision is great when casparser credits are exhausted or when
                  you want richer extraction (transactions, accounts, investor info).
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
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

            {/* Update key */}
            <div>
              <Label className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-2 block">
                Update API Key
              </Label>
              <div className="flex flex-col sm:flex-row gap-2">
                <div className="relative flex-1">
                  <Input
                    data-testid="cas-key-input"
                    type={showKey ? "text" : "password"}
                    value={newKey}
                    onChange={(e) => setNewKey(e.target.value)}
                    placeholder="sk_live_..."
                    className="pr-10 rounded-xl border-slate-200 dark:border-slate-700 font-mono text-sm"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                  >
                    {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <Button
                  data-testid="cas-key-save"
                  onClick={saveKey}
                  disabled={saving || !newKey.trim()}
                  className="bg-teal-600 hover:bg-teal-700 text-white rounded-xl"
                >
                  <Save className="w-4 h-4 mr-2" />
                  {saving ? "Saving…" : "Save"}
                </Button>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
                Paste a new key to override the env variable. Persists in DB across restarts.
              </p>
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

            {config.persisted_at && (
              <div className="text-[11px] text-slate-400 dark:text-slate-500 pt-2 border-t border-slate-100 dark:border-slate-700">
                Last updated: {new Date(config.persisted_at).toLocaleString("en-IN")}
                {config.persisted_by && ` · by ${config.persisted_by}`}
              </div>
            )}
          </div>
        ) : (
          <div className="py-6 text-center text-sm text-red-500">Couldn't load config</div>
        )}
      </CardContent>
    </Card>
  );
};

export default CasConfigSection;
