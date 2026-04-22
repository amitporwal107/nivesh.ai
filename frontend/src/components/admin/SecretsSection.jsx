import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { KeyRound, RefreshCw, Eye, EyeOff, CheckCircle2, XCircle, Save, Trash2, Plus, FlaskConical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const CATEGORY_LABELS = {
  parsing: "Parsing",
  ai: "AI / LLM",
  auth: "Authentication",
  data: "Data Layer",
  custom: "Custom",
};

const SecretRow = ({ secret, onUpdate, onDelete, onTest }) => {
  const [editing, setEditing] = useState(false);
  const [newValue, setNewValue] = useState("");
  const [showValue, setShowValue] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const handleSave = async () => {
    if (!newValue.trim()) return;
    setSaving(true);
    await onUpdate(secret.key, newValue.trim());
    setSaving(false);
    setEditing(false);
    setNewValue("");
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    const r = await onTest(secret.key);
    setTestResult(r);
    setTesting(false);
  };

  return (
    <div
      data-testid={`secret-row-${secret.key}`}
      className="p-4 rounded-xl border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50"
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="font-semibold text-sm text-slate-900 dark:text-white">{secret.display_name}</h4>
            {secret.has_override && (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-teal-100 dark:bg-teal-950 text-teal-700 dark:text-teal-400">
                DB OVERRIDE
              </span>
            )}
            {!secret.has_override && secret.has_env_fallback && (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400">
                FROM ENV
              </span>
            )}
            {!secret.configured && (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-400">
                NOT SET
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 mb-2">{secret.description}</p>
          <code className="font-mono text-xs text-slate-700 dark:text-slate-300 break-all" data-testid={`secret-value-${secret.key}`}>
            {secret.masked_value || "—"}
          </code>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {secret.test_fn && (
            <Button
              data-testid={`secret-test-${secret.key}`}
              variant="ghost"
              size="sm"
              onClick={handleTest}
              disabled={testing || !secret.configured}
              className="h-8 text-xs"
            >
              {testing ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <FlaskConical className="w-3.5 h-3.5" />}
              <span className="ml-1 hidden sm:inline">Test</span>
            </Button>
          )}
          <Button
            data-testid={`secret-edit-${secret.key}`}
            variant="ghost"
            size="sm"
            onClick={() => setEditing(!editing)}
            className="h-8 text-xs"
          >
            {editing ? "Cancel" : "Edit"}
          </Button>
          {secret.has_override && (
            <Button
              data-testid={`secret-delete-${secret.key}`}
              variant="ghost"
              size="sm"
              onClick={() => onDelete(secret.key)}
              className="h-8 px-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          )}
        </div>
      </div>

      {editing && (
        <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-800 flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1">
            <Input
              data-testid={`secret-input-${secret.key}`}
              type={showValue ? "text" : "password"}
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
              placeholder={`New value for ${secret.key}…`}
              className="pr-10 rounded-xl font-mono text-sm"
            />
            <button
              type="button"
              onClick={() => setShowValue(!showValue)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400"
            >
              {showValue ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          <Button
            data-testid={`secret-save-${secret.key}`}
            onClick={handleSave}
            disabled={saving || !newValue.trim()}
            className="bg-teal-600 hover:bg-teal-700 text-white rounded-xl"
          >
            <Save className="w-4 h-4 mr-1.5" />
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      )}

      {testResult && (
        <div
          data-testid={`secret-test-result-${secret.key}`}
          className={`mt-3 p-2.5 rounded-lg flex items-start gap-2 text-xs ${
            testResult.ok
              ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400"
              : "bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-400"
          }`}
        >
          {testResult.ok ? (
            <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0" strokeWidth={2} />
          ) : (
            <XCircle className="w-4 h-4 mt-0.5 flex-shrink-0" strokeWidth={2} />
          )}
          <span>{testResult.ok ? testResult.detail : testResult.error}</span>
        </div>
      )}
    </div>
  );
};

const SecretsSection = ({ categoryFilter = null, title = "Secrets", subtitle = "API keys and credentials. DB overrides take precedence over env vars.", allowAddCustom = true }) => {
  const [list, setList] = useState([]);
  const [meta, setMeta] = useState({});
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");
  const [currentEnv, setCurrentEnv] = useState("preview");
  const [viewingEnv, setViewingEnv] = useState("preview");

  const load = useCallback(async (envOverride = null) => {
    setLoading(true);
    try {
      const envParam = envOverride || viewingEnv;
      const res = await axios.get(`${API}/admin/secrets?env=${encodeURIComponent(envParam)}`, { withCredentials: true });
      setList(res.data.secrets || []);
      setMeta({ updated_at: res.data.updated_at, updated_by: res.data.updated_by });
      setCurrentEnv(res.data.current_env || "preview");
      setViewingEnv(res.data.viewing_env || envParam);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to load secrets");
    } finally {
      setLoading(false);
    }
  }, [viewingEnv]);

  useEffect(() => { load(); /* initial load — viewingEnv defaults to preview */ /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const switchEnv = (env) => {
    setViewingEnv(env);
    load(env);
  };

  const handleUpdate = async (key, value) => {
    try {
      await axios.put(`${API}/admin/secrets/${key}?env=${encodeURIComponent(viewingEnv)}`, { value }, { withCredentials: true });
      toast.success(`${key} updated (${viewingEnv})`);
      load(viewingEnv);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Update failed");
    }
  };

  const handleDelete = async (key) => {
    if (!window.confirm(`Clear ${viewingEnv} override for ${key}? Will fall back to env var.`)) return;
    try {
      await axios.delete(`${API}/admin/secrets/${key}?env=${encodeURIComponent(viewingEnv)}`, { withCredentials: true });
      toast.success(`${key} override cleared (${viewingEnv})`);
      load(viewingEnv);
    } catch (err) {
      toast.error("Delete failed");
    }
  };

  const handleTest = async (key) => {
    try {
      const res = await axios.post(`${API}/admin/secrets/${key}/test`, {}, { withCredentials: true });
      if (res.data.ok) toast.success(`${key}: ${res.data.detail}`);
      else toast.error(`${key}: ${res.data.error}`);
      return res.data;
    } catch (err) {
      const msg = err.response?.data?.detail || "Test failed";
      toast.error(msg);
      return { ok: false, error: msg };
    }
  };

  const handleAddCustom = async () => {
    if (!newKey.trim() || !newVal.trim()) return;
    await handleUpdate(newKey.trim().toUpperCase(), newVal.trim());
    setNewKey("");
    setNewVal("");
    setShowAdd(false);
  };

  const filteredList = categoryFilter
    ? list.filter(s => {
        const cats = Array.isArray(categoryFilter) ? categoryFilter : [categoryFilter];
        return cats.includes(s.category || "custom");
      })
    : list;

  const grouped = filteredList.reduce((acc, s) => {
    const cat = s.category || "custom";
    (acc[cat] = acc[cat] || []).push(s);
    return acc;
  }, {});

  return (
    <Card
      data-testid="admin-secrets-section"
      className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none overflow-hidden"
    >
      <CardContent className="p-5 sm:p-6">
        <div className="flex items-start justify-between gap-3 mb-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 flex items-center justify-center">
              <KeyRound className="w-5 h-5" strokeWidth={2} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">{title}</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {subtitle}
              </p>
            </div>
          </div>
          <div className="flex gap-2 items-center flex-wrap">
            {/* Environment switcher — isolated secrets per env */}
            <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-900" data-testid="secrets-env-switcher">
              {["preview", "production"].map(e => {
                const active = viewingEnv === e;
                const isCurrent = currentEnv === e;
                return (
                  <button
                    key={e}
                    type="button"
                    onClick={() => switchEnv(e)}
                    data-testid={`secrets-env-${e}`}
                    className={`px-3 py-1 text-[11px] font-semibold rounded-lg transition-colors flex items-center gap-1 ${
                      active
                        ? (e === "production"
                            ? "bg-rose-600 text-white shadow-sm"
                            : "bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-900 shadow-sm")
                        : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200"
                    }`}
                  >
                    {e.toUpperCase()}
                    {isCurrent && <span className="text-[8px] opacity-80">● live</span>}
                  </button>
                );
              })}
            </div>
            {allowAddCustom && (<Button
              data-testid="secrets-add-custom"
              variant="outline"
              size="sm"
              onClick={() => setShowAdd(!showAdd)}
              className="rounded-xl"
            >
              <Plus className="w-4 h-4 mr-1" /> Custom
            </Button>)}
            <Button variant="ghost" size="sm" onClick={() => load(viewingEnv)} data-testid="secrets-refresh">
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>

        {/* Viewing-env warning banner */}
        {viewingEnv !== currentEnv && (
          <div
            data-testid="secrets-cross-env-warning"
            className="mb-4 p-3 rounded-xl border border-rose-200 dark:border-rose-900/40 bg-rose-50 dark:bg-rose-950/20 text-[11px] text-rose-800 dark:text-rose-300 flex items-start gap-2"
          >
            <span className="font-bold">⚠ Editing {viewingEnv.toUpperCase()} secrets from {currentEnv.toUpperCase()} deploy.</span>
            <span>
              Changes are persisted to the <code className="font-mono">secrets:{viewingEnv}</code> doc and will only take effect when a {viewingEnv} pod restarts.
              Your running {currentEnv} deploy is unaffected.
            </span>
          </div>
        )}

        {showAdd && allowAddCustom && (
          <div className="mb-4 p-3 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-700 flex flex-col sm:flex-row gap-2">
            <Input
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              placeholder="MY_CUSTOM_KEY"
              className="rounded-xl font-mono text-sm uppercase"
              data-testid="custom-secret-key"
            />
            <Input
              type="password"
              value={newVal}
              onChange={(e) => setNewVal(e.target.value)}
              placeholder="Value"
              className="rounded-xl font-mono text-sm flex-1"
              data-testid="custom-secret-value"
            />
            <Button onClick={handleAddCustom} disabled={!newKey.trim() || !newVal.trim()} className="bg-teal-600 text-white rounded-xl" data-testid="custom-secret-save">
              <Save className="w-4 h-4 mr-1.5" /> Add
            </Button>
          </div>
        )}

        {loading && list.length === 0 ? (
          <div className="py-6 text-center text-sm text-slate-500 dark:text-slate-400">Loading…</div>
        ) : (
          <div className="space-y-4">
            {Object.entries(grouped).map(([cat, secrets]) => (
              <div key={cat}>
                <h5 className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400 mb-2">
                  {CATEGORY_LABELS[cat] || cat}
                </h5>
                <div className="space-y-2">
                  {secrets.map((s) => (
                    <SecretRow
                      key={s.key}
                      secret={s}
                      onUpdate={handleUpdate}
                      onDelete={handleDelete}
                      onTest={handleTest}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {meta.updated_at && (
          <div className="text-[11px] text-slate-400 dark:text-slate-500 pt-3 mt-3 border-t border-slate-100 dark:border-slate-700">
            Last updated: {new Date(meta.updated_at).toLocaleString("en-IN")}
            {meta.updated_by && ` · by ${meta.updated_by}`}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default SecretsSection;
