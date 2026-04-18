import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Flag, RefreshCw, Plus, X, Users, Power, Ban } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const MODE_STYLES = {
  off: { label: "Off", bg: "bg-slate-100 dark:bg-slate-800", text: "text-slate-500", icon: Ban },
  allowlist: { label: "Allowlist", bg: "bg-amber-100 dark:bg-amber-950", text: "text-amber-700 dark:text-amber-400", icon: Users },
  everyone: { label: "Everyone", bg: "bg-emerald-100 dark:bg-emerald-950", text: "text-emerald-700 dark:text-emerald-400", icon: Power },
};

const FlagRow = ({ flag, onModeChange, onAddUser, onRemoveUser }) => {
  const [newEmail, setNewEmail] = useState("");
  const [adding, setAdding] = useState(false);

  const style = MODE_STYLES[flag.mode] || MODE_STYLES.off;
  const Icon = style.icon;

  const handleAdd = async () => {
    if (!newEmail.trim()) return;
    setAdding(true);
    await onAddUser(flag.key, newEmail.trim());
    setNewEmail("");
    setAdding(false);
  };

  return (
    <div
      data-testid={`flag-row-${flag.key}`}
      className="p-4 rounded-xl border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50"
    >
      <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="font-semibold text-sm text-slate-900 dark:text-white">{flag.display_name}</h4>
            <span className={`inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${style.bg} ${style.text}`}>
              <Icon className="w-3 h-3" strokeWidth={2.5} /> {style.label}
            </span>
            <code className="text-[10px] font-mono text-slate-400">{flag.key}</code>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{flag.description}</p>
        </div>
        <Select
          value={flag.mode}
          onValueChange={(v) => onModeChange(flag.key, v)}
        >
          <SelectTrigger data-testid={`flag-mode-${flag.key}`} className="w-32 rounded-xl text-sm h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="off">Off</SelectItem>
            <SelectItem value="allowlist">Allowlist</SelectItem>
            <SelectItem value="everyone">Everyone</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {flag.mode === "allowlist" && (
        <div className="pt-3 border-t border-slate-100 dark:border-slate-800 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400">
              Enabled for ({flag.allowlist.length})
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5" data-testid={`flag-allowlist-${flag.key}`}>
            {flag.allowlist.length === 0 ? (
              <span className="text-xs text-slate-400 italic">No users — feature is effectively disabled</span>
            ) : (
              flag.allowlist.map((email) => (
                <span
                  key={email}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-xs"
                >
                  <span className="text-slate-700 dark:text-slate-300">{email}</span>
                  <button
                    onClick={() => onRemoveUser(flag.key, email)}
                    className="text-slate-400 hover:text-red-500"
                    data-testid={`flag-remove-${flag.key}-${email}`}
                    aria-label={`Remove ${email}`}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))
            )}
          </div>
          <div className="flex flex-col sm:flex-row gap-2 pt-1">
            <Input
              type="email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAdd()}
              placeholder="email@example.com"
              className="rounded-xl text-sm flex-1"
              data-testid={`flag-add-input-${flag.key}`}
            />
            <Button
              onClick={handleAdd}
              disabled={adding || !newEmail.trim()}
              className="bg-teal-600 hover:bg-teal-700 text-white rounded-xl text-sm"
              data-testid={`flag-add-btn-${flag.key}`}
            >
              <Plus className="w-3.5 h-3.5 mr-1" />
              {adding ? "Adding…" : "Add"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

const FeatureFlagsSection = () => {
  const [flags, setFlags] = useState([]);
  const [meta, setMeta] = useState({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/feature-flags`, { withCredentials: true });
      setFlags(res.data.flags || []);
      setMeta({ updated_at: res.data.updated_at, updated_by: res.data.updated_by });
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to load feature flags");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleModeChange = async (key, mode) => {
    try {
      await axios.put(`${API}/admin/feature-flags/${key}`, { mode }, { withCredentials: true });
      toast.success(`${key} → ${mode}`);
      load();
    } catch (err) {
      toast.error("Update failed");
    }
  };

  const handleAddUser = async (key, email) => {
    try {
      await axios.post(`${API}/admin/feature-flags/${key}/users`, { email }, { withCredentials: true });
      toast.success(`${email} added to ${key}`);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Add failed");
    }
  };

  const handleRemoveUser = async (key, email) => {
    try {
      await axios.delete(`${API}/admin/feature-flags/${key}/users/${encodeURIComponent(email)}`, { withCredentials: true });
      toast.success(`${email} removed from ${key}`);
      load();
    } catch (err) {
      toast.error("Remove failed");
    }
  };

  return (
    <Card
      data-testid="admin-feature-flags-section"
      className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none overflow-hidden"
    >
      <CardContent className="p-5 sm:p-6">
        <div className="flex items-start justify-between gap-3 mb-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 flex items-center justify-center">
              <Flag className="w-5 h-5" strokeWidth={2} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">Feature Flags</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Control which features each user can access.
              </p>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={load} data-testid="flags-refresh">
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>

        {loading && flags.length === 0 ? (
          <div className="py-6 text-center text-sm text-slate-500 dark:text-slate-400">Loading…</div>
        ) : (
          <div className="space-y-3">
            {flags.map((f) => (
              <FlagRow
                key={f.key}
                flag={f}
                onModeChange={handleModeChange}
                onAddUser={handleAddUser}
                onRemoveUser={handleRemoveUser}
              />
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

export default FeatureFlagsSection;
