import { useState, useCallback } from "react";
import {
  Search, Users, RefreshCw, Loader2, Trash2, AlertTriangle,
  ShieldCheck, ShieldOff, LogOut, Eraser, X, BarChart3, Database, UserPlus, Mail,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { http } from "@/services/api/http";
import { useToastStore } from "@/stores/toast.store";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

interface AdminUser {
  user_id: string;
  email: string;
  name?: string;
  picture?: string;
  is_admin: boolean;
  holdings_count: number;
  plans_count: number;
  session_active?: boolean;
}

interface ResetResult {
  user_email: string;
  total_deleted: number;
  pg_total_deleted?: number;
  redis_keys_cleared: number;
  deleted_per_collection?: Record<string, number>;
  pg_deleted_per_table?: Record<string, number>;
  profile_reset?: boolean;
}

function fetchUsers(q: string) {
  return http<{ users: AdminUser[] }>({
    path: "/api/admin/users",
    query: q ? { q } : undefined,
  }).then((r) => r.data.users);
}

export function UserManagement() {
  const qc = useQueryClient();
  const push = useToastStore((s) => s.push);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");

  const { data: users = [], isFetching, refetch } = useQuery({
    queryKey: ["admin", "users", q],
    queryFn: () => fetchUsers(q),
  });

  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [resetMode, setResetMode] = useState<"portfolio" | "full">("portfolio");
  const [confirmText, setConfirmText] = useState("");
  const [resetResult, setResetResult] = useState<ResetResult | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState({ email: "", name: "", is_admin: false });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["admin", "users"] });

  const toggleAdmin = useMutation({
    mutationFn: (u: AdminUser) =>
      http({ method: "PATCH", path: `/api/admin/users/${u.user_id}`, body: { is_admin: !u.is_admin } }),
    onSuccess: (_, u) => {
      push({ kind: "success", title: `${u.is_admin ? "Revoked" : "Granted"} admin: ${u.email}` });
      invalidate();
    },
    onError: () => push({ kind: "error", title: "Failed to update admin flag" }),
  });

  const invalidateSessions = useMutation({
    mutationFn: (u: AdminUser) =>
      http({ method: "POST", path: `/api/admin/users/${u.user_id}/invalidate-sessions`, body: {} }),
    onSuccess: (res, u) => {
      push({ kind: "success", title: `Logged out ${u.email} (${(res.data as { deleted_sessions?: number }).deleted_sessions ?? 0} sessions)` });
      invalidate();
    },
    onError: () => push({ kind: "error", title: "Failed to invalidate sessions" }),
  });

  const [resetting, setResetting] = useState(false);
  const doReset = async () => {
    if (!resetTarget) return;
    if (confirmText.trim().toLowerCase() !== resetTarget.email.toLowerCase()) {
      push({ kind: "warn", title: "Email confirmation does not match" });
      return;
    }
    setResetting(true);
    const endpoint = resetMode === "full" ? "reset-full" : "reset-portfolio";
    try {
      const res = await http<ResetResult>({ method: "POST", path: `/api/admin/users/${resetTarget.user_id}/${endpoint}`, body: {} });
      setResetResult(res.data);
      push({ kind: "success", title: `Reset complete · ${res.data.total_deleted} docs` });
      invalidate();
    } catch {
      push({ kind: "error", title: "Reset failed" });
    } finally {
      setResetting(false);
    }
  };

  const addMutation = useMutation({
    mutationFn: () =>
      http({ method: "POST", path: "/api/admin/users", body: { email: addForm.email.trim().toLowerCase(), name: addForm.name.trim() || null, is_admin: addForm.is_admin } }),
    onSuccess: () => {
      push({ kind: "success", title: `Added ${addForm.email}${addForm.is_admin ? " (admin)" : ""}` });
      setAddOpen(false);
      setAddForm({ email: "", name: "", is_admin: false });
      invalidate();
    },
    onError: () => push({ kind: "error", title: "Failed to add user" }),
  });

  const inputCls = "w-full rounded-md border border-hairline-2 bg-surface-1 px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-accent";

  return (
    <Card>
      <CardContent className="p-5 sm:p-6">
        <div className="flex items-center justify-between flex-wrap gap-3 mb-5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
              <Users className="w-5 h-5 text-accent" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-ink">User Management</h2>
              <p className="text-xs text-ink-3">Reset portfolio · toggle admin · invalidate sessions</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => setAddOpen(true)}>
              <UserPlus className="w-3.5 h-3.5" /> Add user
            </Button>
            <Button variant="outline" size="sm" onClick={() => { setQ(search); refetch(); }} disabled={isFetching}>
              {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            </Button>
          </div>
        </div>

        <form onSubmit={(e) => { e.preventDefault(); setQ(search); }} className="flex gap-2 mb-4">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by email…" className={`${inputCls} pl-9`} />
          </div>
          <Button type="submit" variant="outline" size="sm">Search</Button>
        </form>

        <div className="text-xs text-ink-3 mb-3">{isFetching ? "Loading…" : `${users.length} user${users.length === 1 ? "" : "s"}`}</div>

        <div className="space-y-2">
          {users.map((u) => (
            <div key={u.user_id} className="border border-hairline rounded-lg p-3 sm:p-4 flex items-center gap-3 sm:gap-4 hover:bg-surface-1 transition-colors">
              <div className="flex items-center gap-3 min-w-0 flex-1">
                {u.picture
                  ? <img src={u.picture} alt="" className="w-9 h-9 rounded-full shrink-0" />
                  : <div className="w-9 h-9 rounded-full bg-surface-2 flex items-center justify-center text-xs font-bold text-ink-2 shrink-0">{(u.email || "?")[0].toUpperCase()}</div>
                }
                <div className="min-w-0">
                  <div className="text-sm font-medium text-ink truncate flex items-center gap-1.5">
                    {u.name || u.email}
                    {u.is_admin && <span className="text-[9px] font-bold uppercase bg-accent-soft text-accent px-1.5 py-0.5 rounded">admin</span>}
                  </div>
                  <div className="text-[11px] text-ink-3 truncate">{u.email}</div>
                </div>
              </div>
              <div className="hidden md:flex items-center gap-4 text-[11px] text-ink-3 shrink-0">
                <span className="flex items-center gap-1"><BarChart3 className="w-3 h-3" /><strong className="text-ink-2">{u.holdings_count}</strong> holdings</span>
                <span className="flex items-center gap-1"><Database className="w-3 h-3" /><strong className="text-ink-2">{u.plans_count}</strong> plans</span>
                {u.session_active && <span className="text-pos text-[10px] font-medium">online</span>}
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button onClick={() => { setResetTarget(u); setResetMode("portfolio"); setConfirmText(""); setResetResult(null); }} title="Reset portfolio data" className="h-8 px-2 rounded-md text-[11px] border border-hairline text-neg hover:bg-[rgb(var(--neg)/0.05)] transition-colors flex items-center gap-1">
                  <Eraser className="w-3.5 h-3.5" /><span className="hidden sm:inline">Reset</span>
                </button>
                <button onClick={() => { setResetTarget(u); setResetMode("full"); setConfirmText(""); setResetResult(null); }} title="Full reset (NIDP included)" className="h-8 px-2 rounded-md text-[11px] border border-hairline text-neg hover:bg-[rgb(var(--neg)/0.05)] transition-colors flex items-center gap-1">
                  <Trash2 className="w-3.5 h-3.5" /><span className="hidden sm:inline">Full</span>
                </button>
                <button onClick={() => window.confirm(`${u.is_admin ? "Revoke" : "Grant"} admin to ${u.email}?`) && toggleAdmin.mutate(u)} title={u.is_admin ? "Revoke admin" : "Grant admin"} className="h-8 w-8 rounded-md border border-hairline text-ink-2 hover:bg-surface-2 transition-colors flex items-center justify-center">
                  {u.is_admin ? <ShieldOff className="w-3.5 h-3.5" /> : <ShieldCheck className="w-3.5 h-3.5" />}
                </button>
                <button onClick={() => window.confirm(`Force-logout ${u.email}?`) && invalidateSessions.mutate(u)} title="Force-logout all devices" className="h-8 w-8 rounded-md border border-hairline text-ink-2 hover:bg-surface-2 transition-colors flex items-center justify-center">
                  <LogOut className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))}
          {!isFetching && users.length === 0 && (
            <div className="text-center text-sm text-ink-3 py-8">No users found.</div>
          )}
        </div>
      </CardContent>

      {/* Reset modal */}
      {resetTarget && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={() => !resetting && (setResetTarget(null), setResetResult(null))}>
          <div className="bg-bg border border-hairline rounded-xl shadow-2xl max-w-md w-full p-6" onClick={(e) => e.stopPropagation()}>
            {!resetResult ? (
              <>
                <div className="flex items-start gap-3 mb-4">
                  <div className="w-10 h-10 rounded-lg bg-[rgb(var(--neg)/0.10)] flex items-center justify-center shrink-0">
                    <AlertTriangle className="w-5 h-5 text-neg" />
                  </div>
                  <div className="flex-1">
                    <h3 className="font-semibold text-ink">{resetMode === "full" ? "Full reset this user?" : "Reset portfolio?"}</h3>
                    <p className="text-xs text-ink-3 mt-1">Wipes holdings, plans, insights, cache. Resets onboarding flags.</p>
                    {resetMode === "full" && <p className="text-xs text-neg mt-1">Also wipes NIDP Postgres tables. Unrecoverable.</p>}
                  </div>
                  <button onClick={() => !resetting && (setResetTarget(null), setResetResult(null))} className="text-ink-3 hover:text-ink"><X className="w-4 h-4" /></button>
                </div>
                <div className="bg-surface-1 rounded-lg p-3 mb-4 text-xs">
                  <div className="text-ink-3">Target</div>
                  <div className="font-medium text-ink truncate">{resetTarget.name || resetTarget.email}</div>
                  <div className="text-ink-3 truncate">{resetTarget.email}</div>
                </div>
                <label className="block text-xs font-medium text-ink-2 mb-1">Type the user's email to confirm:</label>
                <input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} placeholder={resetTarget.email} className={`${inputCls} mb-4`} autoFocus disabled={resetting} />
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => !resetting && (setResetTarget(null), setResetResult(null))} disabled={resetting}>Cancel</Button>
                  <Button
                    onClick={doReset}
                    disabled={resetting || confirmText.trim().toLowerCase() !== resetTarget.email.toLowerCase()}
                    className="bg-neg text-white hover:bg-neg/90"
                  >
                    {resetting ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Resetting…</> : <><Trash2 className="w-3.5 h-3.5" /> {resetMode === "full" ? "Full Reset" : "Reset Portfolio"}</>}
                  </Button>
                </div>
              </>
            ) : (
              <>
                <div className="flex items-start gap-3 mb-4">
                  <div className="w-10 h-10 rounded-lg bg-[rgb(var(--pos)/0.10)] flex items-center justify-center shrink-0"><ShieldCheck className="w-5 h-5 text-pos" /></div>
                  <div>
                    <h3 className="font-semibold text-ink">Reset complete</h3>
                    <p className="text-xs text-ink-3 mt-1"><strong>{resetResult.user_email}</strong> will re-run onboarding next login.</p>
                  </div>
                </div>
                <div className="bg-surface-1 rounded-lg p-3 mb-4 text-[11px] max-h-48 overflow-y-auto space-y-0.5">
                  <div className="font-medium text-ink-2 mb-1">Wiped {resetResult.total_deleted} mongo doc(s) · {resetResult.redis_keys_cleared} Redis key(s)</div>
                  {Object.entries(resetResult.deleted_per_collection || {}).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]).map(([col, n]) => (
                    <div key={col} className="flex justify-between"><code className="text-ink-3">{col}</code><span className="font-medium text-ink-2">{n}</span></div>
                  ))}
                </div>
                <div className="flex justify-end"><Button onClick={() => { setResetTarget(null); setResetResult(null); }}>Done</Button></div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Add user modal */}
      {addOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={() => !addMutation.isPending && setAddOpen(false)}>
          <form onSubmit={(e) => { e.preventDefault(); addMutation.mutate(); }} className="bg-bg border border-hairline rounded-xl shadow-2xl max-w-md w-full p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-3 mb-4">
              <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center shrink-0"><UserPlus className="w-5 h-5 text-accent" /></div>
              <div className="flex-1">
                <h3 className="font-semibold text-ink">Add user</h3>
                <p className="text-xs text-ink-3 mt-1">Whitelists the email; account activates on first login.</p>
              </div>
              <button type="button" onClick={() => setAddOpen(false)} className="text-ink-3 hover:text-ink"><X className="w-4 h-4" /></button>
            </div>
            <label className="block text-xs font-medium text-ink-2 mb-1">Email <span className="text-neg">*</span></label>
            <div className="relative mb-3">
              <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
              <input type="email" value={addForm.email} onChange={(e) => setAddForm((f) => ({ ...f, email: e.target.value }))} placeholder="user@example.com" className={`${inputCls} pl-9`} required autoFocus disabled={addMutation.isPending} />
            </div>
            <label className="block text-xs font-medium text-ink-2 mb-1">Name <span className="text-ink-3 font-normal">(optional)</span></label>
            <input value={addForm.name} onChange={(e) => setAddForm((f) => ({ ...f, name: e.target.value }))} placeholder="Full name" className={`${inputCls} mb-3`} disabled={addMutation.isPending} />
            <label className="flex items-center gap-2 text-sm text-ink-2 mb-5 cursor-pointer">
              <input type="checkbox" checked={addForm.is_admin} onChange={(e) => setAddForm((f) => ({ ...f, is_admin: e.target.checked }))} className="rounded" disabled={addMutation.isPending} />
              Grant admin privileges
            </label>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setAddOpen(false)} disabled={addMutation.isPending}>Cancel</Button>
              <Button type="submit" disabled={addMutation.isPending || !addForm.email.trim()}>
                {addMutation.isPending ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Adding…</> : <><UserPlus className="w-3.5 h-3.5" /> Add user</>}
              </Button>
            </div>
          </form>
        </div>
      )}
    </Card>
  );
}
