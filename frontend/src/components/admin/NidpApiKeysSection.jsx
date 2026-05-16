import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  KeyRound, RefreshCw, Eye, EyeOff, Copy, Check,
  RotateCcw, Save, AlertTriangle, ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const KEY_META = {
  NIDP_DAAS_API_KEY: {
    label: "DaaS API Key",
    header: "X-API-Key",
    desc: "Sent as X-API-Key header to the NIDP DaaS API. Tokens start with nvd_.",
    color: "indigo",
  },
  NIDP_QUERY_API_TOKEN: {
    label: "Query API Token",
    header: "Authorization: Bearer",
    desc: "Bearer token for the NIDP Query API (internal Cloud Run service). Tokens start with nqt_.",
    color: "violet",
  },
};

function KeyCard({ secretKey, env }) {
  const meta = KEY_META[secretKey];
  const [masked, setMasked] = useState("—");
  const [configured, setConfigured] = useState(false);
  const [revealed, setRevealed] = useState(null);
  const [showing, setShowing] = useState(false);
  const [revealing, setRevealing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editVal, setEditVal] = useState("");
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [newGenerated, setNewGenerated] = useState(null); // shown once after regen
  const [newGenCopied, setNewGenCopied] = useState(false);

  const loadMasked = useCallback(async () => {
    try {
      const res = await axios.get(
        `${API}/admin/secrets?env=${encodeURIComponent(env)}`,
        { withCredentials: true },
      );
      const entry = (res.data.secrets || []).find((s) => s.key === secretKey);
      if (entry) {
        setMasked(entry.masked_value || "—");
        setConfigured(entry.configured);
      }
    } catch {
      // silent
    }
  }, [secretKey, env]);

  useEffect(() => {
    loadMasked();
    // Reset ephemeral state when env changes
    setRevealed(null);
    setShowing(false);
    setNewGenerated(null);
  }, [loadMasked, env]);

  const handleReveal = async () => {
    if (showing) { setShowing(false); return; }
    if (revealed !== null) { setShowing(true); return; }
    setRevealing(true);
    try {
      const res = await axios.get(
        `${API}/admin/secrets/${secretKey}/reveal?env=${encodeURIComponent(env)}`,
        { withCredentials: true },
      );
      setRevealed(res.data.value || "");
      setShowing(true);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to reveal");
    } finally {
      setRevealing(false);
    }
  };

  const copyValue = async (val) => {
    try {
      await navigator.clipboard.writeText(val);
      setCopied(true);
      toast.success(`Copied ${secretKey}`);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Clipboard write blocked");
    }
  };

  const handleSave = async () => {
    if (!editVal.trim()) return;
    setSaving(true);
    try {
      await axios.put(
        `${API}/admin/secrets/${secretKey}?env=${encodeURIComponent(env)}`,
        { value: editVal.trim() },
        { withCredentials: true },
      );
      toast.success(`${secretKey} saved`);
      setEditing(false);
      setEditVal("");
      setRevealed(null);
      setShowing(false);
      loadMasked();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleRegenerate = async () => {
    if (!window.confirm(
      `Regenerate ${secretKey}?\n\nThis will create a new token and invalidate the current one. Any service using the old token will need to be updated.`,
    )) return;
    setRegenerating(true);
    try {
      const res = await axios.post(
        `${API}/admin/nidp/api-keys/${secretKey}/regenerate`,
        {},
        { withCredentials: true },
      );
      setNewGenerated(res.data.new_value);
      setNewGenCopied(false);
      setRevealed(null);
      setShowing(false);
      loadMasked();
      toast.success(`${secretKey} regenerated — copy the new token now`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Regenerate failed");
    } finally {
      setRegenerating(false);
    }
  };

  const copyNewGen = async () => {
    if (!newGenerated) return;
    try {
      await navigator.clipboard.writeText(newGenerated);
      setNewGenCopied(true);
      toast.success("New token copied");
      setTimeout(() => setNewGenCopied(false), 1500);
    } catch {
      toast.error("Clipboard write blocked");
    }
  };

  const colorMap = {
    indigo: "bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 border-indigo-100 dark:border-indigo-900/40",
    violet: "bg-violet-50 dark:bg-violet-950/40 text-violet-600 dark:text-violet-400 border-violet-100 dark:border-violet-900/40",
  };

  return (
    <div className={`rounded-xl border p-4 ${colorMap[meta.color]}`}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap mb-0.5">
            <span className="font-semibold text-sm">{meta.label}</span>
            <code className="text-[10px] font-mono bg-white/60 dark:bg-black/20 px-1.5 py-0.5 rounded">
              {meta.header}
            </code>
            {configured ? (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-400">
                SET
              </span>
            ) : (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-400">
                NOT SET
              </span>
            )}
          </div>
          <p className="text-[11px] opacity-70 mb-2">{meta.desc}</p>
          <code className={`font-mono text-xs break-all select-all ${showing ? "text-emerald-700 dark:text-emerald-400" : ""}`}>
            {showing ? (revealed || "(empty)") : masked}
          </code>
        </div>

        <div className="flex items-center gap-1 flex-shrink-0">
          {configured && (
            <>
              <Button variant="ghost" size="sm" className="h-8 px-2" onClick={handleReveal} disabled={revealing} title={showing ? "Hide" : "Reveal"}>
                {revealing ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : showing ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
              </Button>
              {showing && (
                <Button variant="ghost" size="sm" className={`h-8 px-2 ${copied ? "text-emerald-600" : ""}`} onClick={() => copyValue(revealed || "")} title="Copy">
                  {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                </Button>
              )}
            </>
          )}
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => { setEditing(!editing); setEditVal(""); }}>
            {editing ? "Cancel" : "Edit"}
          </Button>
          <Button
            variant="ghost" size="sm"
            className="h-8 text-xs text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-950/30"
            onClick={handleRegenerate}
            disabled={regenerating}
            title="Generate a new random token and save it"
          >
            {regenerating ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />}
            <span className="ml-1 hidden sm:inline">Regenerate</span>
          </Button>
        </div>
      </div>

      {editing && (
        <div className="mt-3 pt-3 border-t border-current/10 flex flex-col sm:flex-row gap-2">
          <Input
            type="text"
            value={editVal}
            onChange={(e) => setEditVal(e.target.value)}
            placeholder={`Paste new value for ${secretKey}…`}
            className="flex-1 rounded-xl font-mono text-sm bg-white/70 dark:bg-black/20"
          />
          <Button onClick={handleSave} disabled={saving || !editVal.trim()} className="rounded-xl bg-teal-600 hover:bg-teal-700 text-white">
            <Save className="w-4 h-4 mr-1.5" />
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      )}

      {newGenerated && (
        <div className="mt-3 pt-3 border-t border-current/10">
          <div className="flex items-start gap-2 p-2.5 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/40">
            <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-[11px] font-semibold text-amber-800 dark:text-amber-300 mb-1">
                New token — copy it now. It won't be shown again in full.
              </p>
              <code className="font-mono text-xs text-amber-900 dark:text-amber-200 break-all select-all block">
                {newGenerated}
              </code>
            </div>
            <Button
              variant="ghost" size="sm"
              className={`h-7 px-2 flex-shrink-0 ${newGenCopied ? "text-emerald-600" : "text-amber-700"}`}
              onClick={copyNewGen}
            >
              {newGenCopied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function NidpApiKeysSection() {
  const [env, setEnv] = useState("production");

  return (
    <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none overflow-hidden">
      <CardContent className="p-5 sm:p-6">
        <div className="flex items-start justify-between gap-3 mb-5 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 flex items-center justify-center">
              <KeyRound className="w-5 h-5" strokeWidth={2} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">NIDP API Keys</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Shared secrets for DaaS and Query API. Regenerate to rotate; update the env on the NIDP VM to match.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-900">
              {["preview", "production"].map((e) => (
                <button
                  key={e}
                  type="button"
                  onClick={() => setEnv(e)}
                  className={`px-3 py-1 text-[11px] font-semibold rounded-lg transition-colors ${
                    env === e
                      ? e === "production"
                        ? "bg-rose-600 text-white shadow-sm"
                        : "bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-900 shadow-sm"
                      : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200"
                  }`}
                >
                  {e.toUpperCase()}
                </button>
              ))}
            </div>

            <a
              href="/api/admin/swagger"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[11px] text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              <ExternalLink className="w-3 h-3" /> Swagger UI
            </a>
          </div>
        </div>

        <div className="space-y-3">
          {Object.keys(KEY_META).map((k) => (
            <KeyCard key={k} secretKey={k} env={env} />
          ))}
        </div>

        <div className="mt-4 p-3 rounded-xl bg-slate-50 dark:bg-slate-900/50 border border-slate-100 dark:border-slate-700 text-[11px] text-slate-500 dark:text-slate-400 space-y-1">
          <p><strong className="font-semibold text-slate-700 dark:text-slate-300">After rotating a key:</strong></p>
          <p>1. Copy the new token from the amber box above.</p>
          <p>2. SSH into the NIDP VM and update the relevant env var in <code className="font-mono">/opt/nidp/.env</code>.</p>
          <p>3. Restart the affected service: <code className="font-mono">sudo systemctl restart nidp-daas</code> or <code className="font-mono">nidp-query</code>.</p>
          <p>4. The Nivesh backend picks up the new value automatically (secrets are hot-reloaded from DB).</p>
        </div>
      </CardContent>
    </Card>
  );
}
