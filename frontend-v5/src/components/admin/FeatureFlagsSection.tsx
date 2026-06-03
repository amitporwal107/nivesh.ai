import { useState } from "react";
import { Flag, RefreshCw, Plus, X, Users, Power, Ban, Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { http } from "@/services/api/http";
import { useToastStore } from "@/stores/toast.store";
import { useQuery, useQueryClient } from "@tanstack/react-query";

interface FeatureFlag {
  key: string;
  display_name: string;
  description?: string;
  mode: "off" | "allowlist" | "everyone";
  allowed_emails?: string[];
}

const MODE_CONFIG = {
  off: { label: "Off", icon: Ban, cls: "bg-surface-2 text-ink-3" },
  allowlist: { label: "Allowlist", icon: Users, cls: "bg-[rgb(var(--warm)/0.12)] text-warm" },
  everyone: { label: "Everyone", icon: Power, cls: "bg-[rgb(var(--pos)/0.10)] text-pos" },
};

const inputCls = "w-full rounded-md border border-hairline-2 bg-surface-1 px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-accent";

function FlagRow({ flag, onRefresh }: { flag: FeatureFlag; onRefresh: () => void }) {
  const push = useToastStore((s) => s.push);
  const [newEmail, setNewEmail] = useState("");
  const [adding, setAdding] = useState(false);

  const mode = MODE_CONFIG[flag.mode] ?? MODE_CONFIG.off;
  const ModeIcon = mode.icon;

  const changeMode = async (m: string) => {
    try {
      await http({ method: "PUT", path: `/api/admin/feature-flags/${flag.key}`, body: { mode: m } });
      push({ kind: "success", title: `${flag.display_name} → ${m}` });
      onRefresh();
    } catch { push({ kind: "error", title: "Failed to update flag" }); }
  };

  const addUser = async () => {
    if (!newEmail.trim()) return;
    setAdding(true);
    try {
      await http({ method: "POST", path: `/api/admin/feature-flags/${flag.key}/users`, body: { email: newEmail.trim() } });
      push({ kind: "success", title: `${newEmail} added to ${flag.key}` });
      setNewEmail(""); onRefresh();
    } catch { push({ kind: "error", title: "Failed to add user" }); }
    finally { setAdding(false); }
  };

  const removeUser = async (email: string) => {
    try {
      await http({ method: "DELETE", path: `/api/admin/feature-flags/${flag.key}/users/${encodeURIComponent(email)}` });
      push({ kind: "success", title: `${email} removed` });
      onRefresh();
    } catch { push({ kind: "error", title: "Failed to remove user" }); }
  };

  return (
    <div className="p-4 rounded-lg border border-hairline">
      <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-ink">{flag.display_name}</span>
            <span className={`inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded ${mode.cls}`}>
              <ModeIcon className="w-3 h-3" strokeWidth={2.5} /> {mode.label}
            </span>
            <code className="text-[10px] font-mono text-ink-3">{flag.key}</code>
          </div>
          {flag.description && <p className="text-xs text-ink-3 mt-0.5">{flag.description}</p>}
        </div>
        <select value={flag.mode} onChange={(e) => changeMode(e.target.value)} className="rounded-md border border-hairline bg-surface-1 px-2 py-1.5 text-xs text-ink focus:outline-none focus:ring-1 focus:ring-accent">
          <option value="off">Off</option>
          <option value="allowlist">Allowlist</option>
          <option value="everyone">Everyone</option>
        </select>
      </div>

      {flag.mode === "allowlist" && (
        <div className="mt-2 space-y-1.5">
          {(flag.allowed_emails || []).map((email) => (
            <div key={email} className="flex items-center justify-between bg-surface-1 rounded px-3 py-1.5 text-xs text-ink-2">
              <span>{email}</span>
              <button onClick={() => removeUser(email)} className="text-neg hover:text-neg/80 ml-2"><X className="w-3.5 h-3.5" /></button>
            </div>
          ))}
          <div className="flex gap-2 mt-2">
            <input value={newEmail} onChange={(e) => setNewEmail(e.target.value)} placeholder="user@example.com" className={`${inputCls} text-xs py-1.5`} onKeyDown={(e) => e.key === "Enter" && addUser()} disabled={adding} />
            <Button size="sm" onClick={addUser} disabled={adding || !newEmail.trim()}>
              {adding ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function FeatureFlagsSection() {
  const qc = useQueryClient();
  const { data: flags = [], isFetching, refetch } = useQuery({
    queryKey: ["admin", "feature-flags"],
    queryFn: () => http<{ flags: FeatureFlag[] }>({ path: "/api/admin/feature-flags" }).then((r) => r.data.flags),
  });

  return (
    <Card>
      <CardContent className="p-5 sm:p-6">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
              <Flag className="w-5 h-5 text-accent" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">Feature Flags</h2>
              <p className="text-xs text-ink-3">Off · Allowlist · Everyone — hot-reloaded, no deploy needed.</p>
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          </Button>
        </div>
        <div className="space-y-3">
          {flags.map((f) => (
            <FlagRow key={f.key} flag={f} onRefresh={() => qc.invalidateQueries({ queryKey: ["admin", "feature-flags"] })} />
          ))}
          {!isFetching && flags.length === 0 && (
            <div className="text-center text-sm text-ink-3 py-8">No feature flags defined.</div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
