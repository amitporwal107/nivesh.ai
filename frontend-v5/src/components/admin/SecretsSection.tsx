import { useState, useCallback } from "react";
import {
  KeyRound, RefreshCw, Eye, EyeOff, Save, Trash2, Plus, FlaskConical,
  Copy, Check, Loader2, X, CheckCircle2, XCircle,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { http } from "@/services/api/http";
import { useToastStore } from "@/stores/toast.store";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

interface Secret {
  key: string;
  display_name: string;
  description?: string;
  category: string;
  masked_value?: string;
  is_set: boolean;
  has_test?: boolean;
  env?: string;
}

const CATEGORY_LABELS: Record<string, string> = {
  parsing: "Parsing", ai: "AI / LLM", auth: "Authentication", data: "Data Layer", custom: "Custom",
};

const inputCls = "w-full rounded-md border border-hairline-2 bg-surface-1 px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-accent";

function SecretRow({ secret, onRefresh }: { secret: Secret; onRefresh: () => void }) {
  const push = useToastStore((s) => s.push);
  const [editing, setEditing] = useState(false);
  const [newValue, setNewValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testOk, setTestOk] = useState<boolean | null>(null);
  const [revealed, setRevealed] = useState<string | null>(null);
  const [showing, setShowing] = useState(false);
  const [revealing, setRevealing] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleSave = async () => {
    if (!newValue.trim()) return;
    setSaving(true);
    try {
      await http({ method: "PUT", path: `/api/admin/secrets/${secret.key}`, body: { value: newValue.trim(), env: secret.env } });
      push({ kind: "success", title: `${secret.display_name} updated` });
      setEditing(false); setNewValue(""); setRevealed(null); onRefresh();
    } catch { push({ kind: "error", title: "Save failed" }); }
    finally { setSaving(false); }
  };

  const handleTest = async () => {
    setTesting(true); setTestOk(null);
    try {
      const r = await http<{ ok: boolean }>({ method: "POST", path: `/api/admin/secrets/${secret.key}/test`, body: {} });
      setTestOk(r.data.ok);
    } catch { setTestOk(false); }
    finally { setTesting(false); }
  };

  const handleReveal = async () => {
    if (showing) { setShowing(false); return; }
    if (revealed !== null) { setShowing(true); return; }
    setRevealing(true);
    try {
      const r = await http<{ value: string }>({ path: `/api/admin/secrets/${secret.key}/reveal`, query: secret.env ? { env: secret.env } : undefined });
      setRevealed(r.data.value || "");
      setShowing(true);
    } catch { push({ kind: "error", title: "Failed to reveal" }); }
    finally { setRevealing(false); }
  };

  const handleCopy = async () => {
    const v = revealed ?? "";
    if (!v) return;
    await navigator.clipboard.writeText(v);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const handleDelete = async () => {
    if (!window.confirm(`Delete secret "${secret.display_name}"?`)) return;
    try {
      await http({ method: "DELETE", path: `/api/admin/secrets/${secret.key}`, query: secret.env ? { env: secret.env } : undefined });
      push({ kind: "success", title: `${secret.display_name} deleted` });
      onRefresh();
    } catch { push({ kind: "error", title: "Delete failed" }); }
  };

  return (
    <div className="p-4 rounded-lg border border-hairline bg-surface-1 space-y-2">
      <div className="flex items-start justify-between gap-2 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-ink">{secret.display_name}</span>
            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${secret.is_set ? "bg-[rgb(var(--pos)/0.10)] text-pos" : "bg-[rgb(var(--neg)/0.10)] text-neg"}`}>
              {secret.is_set ? "set" : "unset"}
            </span>
            <code className="text-[10px] font-mono text-ink-3">{secret.key}</code>
          </div>
          {secret.description && <p className="text-xs text-ink-3 mt-0.5">{secret.description}</p>}
        </div>
        <div className="flex items-center gap-1">
          {secret.has_test && (
            <button onClick={handleTest} disabled={testing} title="Test secret" className="h-8 w-8 flex items-center justify-center rounded-md border border-hairline text-ink-2 hover:bg-surface-2 transition-colors">
              {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : testOk === true ? <CheckCircle2 className="w-3.5 h-3.5 text-pos" /> : testOk === false ? <XCircle className="w-3.5 h-3.5 text-neg" /> : <FlaskConical className="w-3.5 h-3.5" />}
            </button>
          )}
          <button onClick={handleReveal} disabled={revealing} title={showing ? "Hide" : "Reveal"} className="h-8 w-8 flex items-center justify-center rounded-md border border-hairline text-ink-2 hover:bg-surface-2 transition-colors">
            {revealing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : showing ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          </button>
          {showing && revealed && (
            <button onClick={handleCopy} title="Copy" className="h-8 w-8 flex items-center justify-center rounded-md border border-hairline text-ink-2 hover:bg-surface-2 transition-colors">
              {copied ? <Check className="w-3.5 h-3.5 text-pos" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          )}
          <button onClick={() => setEditing((v) => !v)} title="Edit" className="h-8 px-2 flex items-center gap-1 rounded-md border border-hairline text-xs text-ink-2 hover:bg-surface-2 transition-colors">
            {editing ? <X className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />}
          </button>
          <button onClick={handleDelete} title="Delete" className="h-8 w-8 flex items-center justify-center rounded-md border border-hairline text-neg hover:bg-[rgb(var(--neg)/0.05)] transition-colors">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {showing && revealed !== null && (
        <div className="font-mono text-xs bg-surface-2 rounded px-3 py-2 break-all text-ink-2">{revealed || "(empty)"}</div>
      )}

      {editing && (
        <div className="flex gap-2 mt-2">
          <input type="password" value={newValue} onChange={(e) => setNewValue(e.target.value)} placeholder="New value…" className={`${inputCls} flex-1`} autoFocus disabled={saving} />
          <Button size="sm" onClick={handleSave} disabled={saving || !newValue.trim()}>
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
          </Button>
          <Button size="sm" variant="outline" onClick={() => { setEditing(false); setNewValue(""); }}>Cancel</Button>
        </div>
      )}
    </div>
  );
}

export function SecretsSection() {
  const push = useToastStore((s) => s.push);
  const qc = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState({ key: "", display_name: "", description: "", value: "", category: "custom" });
  const [adding, setAdding] = useState(false);

  const { data: secrets = [], isFetching, refetch } = useQuery({
    queryKey: ["admin", "secrets"],
    queryFn: () => http<{ secrets: Secret[] }>({ path: "/api/admin/secrets" }).then((r) => r.data.secrets),
  });

  const grouped = secrets.reduce<Record<string, Secret[]>>((acc, s) => {
    const g = s.category || "custom";
    (acc[g] ??= []).push(s);
    return acc;
  }, {});

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addForm.key.trim() || !addForm.value.trim()) return;
    setAdding(true);
    try {
      await http({ method: "POST", path: "/api/admin/secrets", body: addForm });
      push({ kind: "success", title: `Secret "${addForm.key}" added` });
      setAddOpen(false);
      setAddForm({ key: "", display_name: "", description: "", value: "", category: "custom" });
      qc.invalidateQueries({ queryKey: ["admin", "secrets"] });
    } catch { push({ kind: "error", title: "Failed to add secret" }); }
    finally { setAdding(false); }
  };

  return (
    <Card>
      <CardContent className="p-5 sm:p-6">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
              <KeyRound className="w-5 h-5 text-accent" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">Secrets</h2>
              <p className="text-xs text-ink-3">API keys, tokens, and credentials. Values are masked at rest.</p>
            </div>
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => setAddOpen(true)}><Plus className="w-3.5 h-3.5" /> Add</Button>
            <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
              {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            </Button>
          </div>
        </div>

        {Object.entries(grouped).map(([cat, items]) => (
          <div key={cat} className="mb-5">
            <div className="font-mono text-[10px] uppercase tracking-[.16em] text-ink-3 mb-2">{CATEGORY_LABELS[cat] ?? cat}</div>
            <div className="space-y-2">
              {items.map((s) => <SecretRow key={s.key} secret={s} onRefresh={refetch} />)}
            </div>
          </div>
        ))}

        {!isFetching && secrets.length === 0 && (
          <div className="text-center text-sm text-ink-3 py-8">No secrets configured.</div>
        )}
      </CardContent>

      {addOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={() => !adding && setAddOpen(false)}>
          <form onSubmit={handleAdd} className="bg-bg border border-hairline rounded-xl shadow-2xl max-w-md w-full p-6 space-y-3" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-1">
              <h3 className="font-semibold text-ink">Add Secret</h3>
              <button type="button" onClick={() => setAddOpen(false)} className="text-ink-3 hover:text-ink"><X className="w-4 h-4" /></button>
            </div>
            {[
              { label: "Key", field: "key" as const, placeholder: "MY_SECRET_KEY" },
              { label: "Display name", field: "display_name" as const, placeholder: "My secret" },
              { label: "Description", field: "description" as const, placeholder: "What this key is used for" },
              { label: "Value", field: "value" as const, placeholder: "sk-…" },
            ].map(({ label, field, placeholder }) => (
              <div key={field}>
                <label className="block text-xs font-medium text-ink-2 mb-1">{label}</label>
                <input value={addForm[field]} onChange={(e) => setAddForm((f) => ({ ...f, [field]: e.target.value }))} placeholder={placeholder} className={inputCls} disabled={adding} required={field === "key" || field === "value"} />
              </div>
            ))}
            <div>
              <label className="block text-xs font-medium text-ink-2 mb-1">Category</label>
              <select value={addForm.category} onChange={(e) => setAddForm((f) => ({ ...f, category: e.target.value }))} className={inputCls}>
                {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" variant="outline" onClick={() => setAddOpen(false)} disabled={adding}>Cancel</Button>
              <Button type="submit" disabled={adding || !addForm.key.trim() || !addForm.value.trim()}>
                {adding ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Adding…</> : <><Plus className="w-3.5 h-3.5" /> Add</>}
              </Button>
            </div>
          </form>
        </div>
      )}
    </Card>
  );
}
