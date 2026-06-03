import { useState } from "react";
import { KeyRound, RefreshCw, Eye, EyeOff, Copy, Check, Loader2, Plus, Trash2, X, Save } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { http } from "@/services/api/http";
import { useToastStore } from "@/stores/toast.store";
import { useQuery, useQueryClient } from "@tanstack/react-query";

interface ApiKey {
  key_id: string;
  display_name: string;
  key_type: "daas" | "query" | "custom";
  masked_value?: string;
  is_active: boolean;
  created_at?: string;
  last_used_at?: string;
}

const KEY_TYPE_LABELS: Record<string, string> = {
  daas: "DaaS (X-API-Key)", query: "Query (Bearer)", custom: "Custom",
};

const inputCls = "w-full rounded-md border border-hairline-2 bg-surface-1 px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-accent";

export function ApiKeysSection() {
  const push = useToastStore((s) => s.push);
  const qc = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState({ display_name: "", value: "", key_type: "daas" });
  const [adding, setAdding] = useState(false);
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [showing, setShowing] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState<string | null>(null);

  const { data: keys = [], isFetching, refetch } = useQuery({
    queryKey: ["nidp", "api-keys"],
    queryFn: () => http<{ keys: ApiKey[] }>({ path: "/api/admin/nidp/api-keys" }).then((r) => r.data.keys),
  });

  const handleReveal = async (k: ApiKey) => {
    if (showing[k.key_id]) { setShowing((s) => ({ ...s, [k.key_id]: false })); return; }
    if (revealed[k.key_id] !== undefined) { setShowing((s) => ({ ...s, [k.key_id]: true })); return; }
    try {
      const r = await http<{ value: string }>({ path: `/api/admin/nidp/api-keys/${k.key_id}/reveal` });
      setRevealed((rv) => ({ ...rv, [k.key_id]: r.data.value }));
      setShowing((s) => ({ ...s, [k.key_id]: true }));
    } catch { push({ kind: "error", title: "Failed to reveal key" }); }
  };

  const handleCopy = async (id: string) => {
    await navigator.clipboard.writeText(revealed[id] ?? "");
    setCopied(id);
    setTimeout(() => setCopied(null), 1500);
  };

  const handleDelete = async (k: ApiKey) => {
    if (!window.confirm(`Delete key "${k.display_name}"?`)) return;
    try {
      await http({ method: "DELETE", path: `/api/admin/nidp/api-keys/${k.key_id}` });
      push({ kind: "success", title: `Key "${k.display_name}" deleted` });
      qc.invalidateQueries({ queryKey: ["nidp", "api-keys"] });
    } catch { push({ kind: "error", title: "Delete failed" }); }
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addForm.display_name.trim() || !addForm.value.trim()) return;
    setAdding(true);
    try {
      await http({ method: "POST", path: "/api/admin/nidp/api-keys", body: addForm });
      push({ kind: "success", title: `Key "${addForm.display_name}" added` });
      setAddOpen(false);
      setAddForm({ display_name: "", value: "", key_type: "daas" });
      qc.invalidateQueries({ queryKey: ["nidp", "api-keys"] });
    } catch { push({ kind: "error", title: "Failed to add key" }); }
    finally { setAdding(false); }
  };

  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
              <KeyRound className="w-5 h-5 text-accent" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">NIDP API Keys</h2>
              <p className="text-xs text-ink-3">DaaS X-API-Key and Query Bearer tokens. Reveal is audit-logged.</p>
            </div>
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => setAddOpen(true)}><Plus className="w-3.5 h-3.5" /> Add</Button>
            <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
              {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            </Button>
          </div>
        </div>

        <div className="space-y-2">
          {keys.map((k) => (
            <div key={k.key_id} className="rounded-lg border border-hairline p-3 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-ink">{k.display_name}</span>
                    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${k.is_active ? "bg-[rgb(var(--pos)/0.10)] text-pos" : "bg-surface-2 text-ink-3"}`}>
                      {k.is_active ? "active" : "inactive"}
                    </span>
                    <span className="text-[10px] text-ink-3">{KEY_TYPE_LABELS[k.key_type] ?? k.key_type}</span>
                  </div>
                  <div className="font-mono text-xs text-ink-3 mt-0.5">{k.masked_value ?? "••••••••"}</div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button onClick={() => handleReveal(k)} title={showing[k.key_id] ? "Hide" : "Reveal"} className="h-7 w-7 flex items-center justify-center rounded border border-hairline text-ink-2 hover:bg-surface-2 transition-colors">
                    {showing[k.key_id] ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                  {showing[k.key_id] && <button onClick={() => handleCopy(k.key_id)} title="Copy" className="h-7 w-7 flex items-center justify-center rounded border border-hairline text-ink-2 hover:bg-surface-2 transition-colors">
                    {copied === k.key_id ? <Check className="w-3.5 h-3.5 text-pos" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>}
                  <button onClick={() => handleDelete(k)} title="Delete" className="h-7 w-7 flex items-center justify-center rounded border border-hairline text-neg hover:bg-[rgb(var(--neg)/0.05)] transition-colors">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              {showing[k.key_id] && revealed[k.key_id] !== undefined && (
                <div className="font-mono text-xs bg-surface-2 rounded px-3 py-2 break-all text-ink-2">{revealed[k.key_id] || "(empty)"}</div>
              )}
            </div>
          ))}
          {!isFetching && keys.length === 0 && (
            <div className="text-center text-sm text-ink-3 py-8">No API keys configured.</div>
          )}
        </div>
      </CardContent>

      {addOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={() => !adding && setAddOpen(false)}>
          <form onSubmit={handleAdd} className="bg-bg border border-hairline rounded-xl shadow-2xl max-w-md w-full p-6 space-y-3" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between"><h3 className="font-semibold text-ink">Add API Key</h3><button type="button" onClick={() => setAddOpen(false)} className="text-ink-3 hover:text-ink"><X className="w-4 h-4" /></button></div>
            <div>
              <label className="block text-xs font-medium text-ink-2 mb-1">Display name</label>
              <input value={addForm.display_name} onChange={(e) => setAddForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="Production DaaS key" className={inputCls} required />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-2 mb-1">Key value</label>
              <input type="password" value={addForm.value} onChange={(e) => setAddForm((f) => ({ ...f, value: e.target.value }))} placeholder="sk-nidp-…" className={inputCls} required />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-2 mb-1">Type</label>
              <select value={addForm.key_type} onChange={(e) => setAddForm((f) => ({ ...f, key_type: e.target.value }))} className={inputCls}>
                {Object.entries(KEY_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" variant="outline" onClick={() => setAddOpen(false)} disabled={adding}>Cancel</Button>
              <Button type="submit" disabled={adding || !addForm.display_name.trim() || !addForm.value.trim()}>
                {adding ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Adding…</> : <><Plus className="w-3.5 h-3.5" /> Add</>}
              </Button>
            </div>
          </form>
        </div>
      )}
    </Card>
  );
}
