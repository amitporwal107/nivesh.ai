import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Search, Users, RefreshCw, Loader2, Trash2, AlertTriangle, ShieldCheck,
  ShieldOff, LogOut, Eraser, X, BarChart3, Database, UserPlus, Mail,
} from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * UserManagementSection — admin-only directory of all platform users.
 * Per-row actions:
 *   • Reset Portfolio Data (wipes holdings + insights + caches and
 *     flips onboarding flags off so admins can re-test the onboarding
 *     flow on a real user without DB surgery).
 *   • Toggle is_admin · Invalidate sessions (force log-out everywhere).
 *
 * Reset is gated by an explicit confirm dialog that asks the admin to
 * type the user's email — destructive ops should never be one-click.
 */
export default function UserManagementSection() {
  const [loading, setLoading] = useState(true);
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState("");
  const [resetTarget, setResetTarget] = useState(null);    // user being reset
  const [resetMode, setResetMode] = useState("portfolio"); // "portfolio" | "full"
  const [confirmText, setConfirmText] = useState("");
  const [resetting, setResetting] = useState(false);
  const [resetResult, setResetResult] = useState(null);
  // Add-user modal state
  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState({ email: "", name: "", is_admin: false });
  const [adding, setAdding] = useState(false);

  const load = useCallback(async (q = "") => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/users`, {
        params: q ? { q } : {},
        withCredentials: true,
      });
      setUsers(res.data?.users || []);
    } catch (e) {
      toast.error("Failed to load users");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load("");
  }, [load]);

  const onSearch = (e) => {
    e.preventDefault();
    load(search.trim());
  };

  const toggleAdmin = async (u) => {
    if (!window.confirm(`${u.is_admin ? "Revoke" : "Grant"} admin to ${u.email}?`)) return;
    try {
      await axios.patch(
        `${API}/admin/users/${u.user_id}`,
        { is_admin: !u.is_admin },
        { withCredentials: true }
      );
      toast.success(`${u.is_admin ? "Revoked" : "Granted"} admin: ${u.email}`);
      load(search.trim());
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to update admin flag");
    }
  };

  const invalidateSessions = async (u) => {
    if (!window.confirm(`Force-logout ${u.email} from all devices?`)) return;
    try {
      const res = await axios.post(
        `${API}/admin/users/${u.user_id}/invalidate-sessions`,
        {},
        { withCredentials: true }
      );
      toast.success(`Logged out ${u.email} (${res.data?.deleted_sessions ?? 0} sessions)`);
      load(search.trim());
    } catch (e) {
      toast.error("Failed to invalidate sessions");
    }
  };

  const openAdd = () => {
    setAddForm({ email: "", name: "", is_admin: false });
    setAddOpen(true);
  };
  const closeAdd = () => { if (!adding) setAddOpen(false); };

  const submitAdd = async (e) => {
    e?.preventDefault?.();
    const email = addForm.email.trim().toLowerCase();
    const emailOk = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email);
    if (!emailOk) { toast.error("Enter a valid email"); return; }
    setAdding(true);
    try {
      const res = await axios.post(
        `${API}/admin/users`,
        { email, name: addForm.name.trim() || null, is_admin: addForm.is_admin },
        { withCredentials: true }
      );
      toast.success(`Added ${res.data?.user?.email}${addForm.is_admin ? " (admin)" : ""}`);
      setAddOpen(false);
      load(search.trim());
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to add user");
    } finally {
      setAdding(false);
    }
  };

  const openReset = (u, mode = "portfolio") => {
    setResetTarget(u);
    setResetMode(mode);
    setConfirmText("");
    setResetResult(null);
  };

  const closeReset = () => {
    if (resetting) return;
    setResetTarget(null);
    setConfirmText("");
    setResetResult(null);
  };

  const doReset = async () => {
    if (!resetTarget) return;
    if (confirmText.trim().toLowerCase() !== (resetTarget.email || "").toLowerCase()) {
      toast.error("Email confirmation does not match");
      return;
    }
    setResetting(true);
    const endpoint = resetMode === "full" ? "reset-full" : "reset-portfolio";
    try {
      const res = await axios.post(
        `${API}/admin/users/${resetTarget.user_id}/${endpoint}`,
        {},
        { withCredentials: true }
      );
      setResetResult(res.data);
      const pgPart = resetMode === "full"
        ? ` · ${res.data?.pg_total_deleted ?? 0} NIDP rows`
        : "";
      toast.success(
        `${resetMode === "full" ? "Full reset" : "Reset"} complete · ${res.data?.total_deleted ?? 0} docs${pgPart} · ${res.data?.redis_keys_cleared ?? 0} cache keys`
      );
      load(search.trim());
    } catch (e) {
      toast.error(e.response?.data?.detail || "Reset failed");
    } finally {
      setResetting(false);
    }
  };

  return (
    <Card
      data-testid="user-management-section"
      className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl"
    >
      <CardContent className="p-5 sm:p-6">
        <div className="flex items-center justify-between flex-wrap gap-3 mb-5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center">
              <Users className="w-5 h-5 text-indigo-600 dark:text-indigo-300" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">User Management</h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Reset portfolio data · toggle admin · invalidate sessions
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={openAdd}
              data-testid="user-mgmt-add"
              className="rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white"
            >
              <UserPlus className="w-3.5 h-3.5 mr-1.5" />
              Add user
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => load(search.trim())}
              disabled={loading}
              data-testid="user-mgmt-refresh"
              className="rounded-xl border-slate-200 dark:border-slate-700"
            >
              {loading ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5 mr-1.5" />}
              Refresh
            </Button>
          </div>
        </div>

        <form onSubmit={onSearch} className="flex items-center gap-2 mb-4">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <Input
              data-testid="user-mgmt-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by email…"
              className="pl-10 rounded-xl border-slate-200 dark:border-slate-700 dark:bg-slate-900"
            />
          </div>
          <Button type="submit" variant="outline" className="rounded-xl">Search</Button>
        </form>

        <div className="text-xs text-slate-500 dark:text-slate-400 mb-3">
          {loading ? "Loading…" : `${users.length} user${users.length === 1 ? "" : "s"}`}
        </div>

        {/* User list */}
        <div className="space-y-2">
          {users.map((u) => (
            <div
              key={u.user_id}
              data-testid={`user-row-${u.user_id}`}
              className="border border-slate-100 dark:border-slate-700 rounded-xl p-3 sm:p-4 flex items-center gap-3 sm:gap-4 hover:bg-slate-50 dark:hover:bg-slate-900/40"
            >
              {/* Avatar + email */}
              <div className="flex items-center gap-3 min-w-0 flex-1">
                {u.picture ? (
                  <img src={u.picture} alt="" className="w-9 h-9 rounded-full flex-shrink-0" />
                ) : (
                  <div className="w-9 h-9 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center text-xs font-bold text-slate-600 dark:text-slate-300 flex-shrink-0">
                    {(u.email || "?")[0].toUpperCase()}
                  </div>
                )}
                <div className="min-w-0">
                  <div className="text-sm font-medium text-slate-900 dark:text-white truncate flex items-center gap-1.5">
                    {u.name || u.email}
                    {u.is_admin && (
                      <span className="text-[9px] font-bold uppercase bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 px-1.5 py-0.5 rounded">
                        admin
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">{u.email}</div>
                </div>
              </div>

              {/* Stats */}
              <div className="hidden md:flex items-center gap-4 text-[11px] text-slate-500 dark:text-slate-400 flex-shrink-0">
                <div className="flex items-center gap-1">
                  <BarChart3 className="w-3 h-3" />
                  <span><strong className="text-slate-700 dark:text-slate-200">{u.holdings_count}</strong> holdings</span>
                </div>
                <div className="flex items-center gap-1">
                  <Database className="w-3 h-3" />
                  <span><strong className="text-slate-700 dark:text-slate-200">{u.plans_count}</strong> plans</span>
                </div>
                {u.session_active && (
                  <span className="text-emerald-600 font-medium">online</span>
                )}
              </div>

              {/* Actions */}
              <div className="flex items-center gap-1.5 flex-shrink-0">
                <Button
                  data-testid={`reset-portfolio-btn-${u.user_id}`}
                  size="sm"
                  variant="outline"
                  onClick={() => openReset(u, "portfolio")}
                  className="rounded-lg border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/20 h-8 px-2"
                  title="Wipe portfolio + insights (Mongo + Redis). Keeps NIDP analytics."
                >
                  <Eraser className="w-3.5 h-3.5 sm:mr-1.5" />
                  <span className="hidden sm:inline">Reset</span>
                </Button>
                <Button
                  data-testid={`reset-full-btn-${u.user_id}`}
                  size="sm"
                  variant="outline"
                  onClick={() => openReset(u, "full")}
                  className="rounded-lg border-rose-300 dark:border-rose-700 bg-rose-50/40 dark:bg-rose-950/30 text-rose-800 dark:text-rose-300 hover:bg-rose-100 dark:hover:bg-rose-900/40 h-8 px-2"
                  title="Full reset — Mongo + Redis + NIDP Postgres (intelligence + holdings snapshots + validation findings). Unrecoverable without re-sync."
                >
                  <Trash2 className="w-3.5 h-3.5 sm:mr-1.5" />
                  <span className="hidden sm:inline">Full Reset</span>
                </Button>
                <Button
                  data-testid={`toggle-admin-btn-${u.user_id}`}
                  size="sm"
                  variant="ghost"
                  onClick={() => toggleAdmin(u)}
                  className="rounded-lg h-8 px-2 text-slate-500 hover:text-slate-700"
                  title={u.is_admin ? "Revoke admin" : "Grant admin"}
                >
                  {u.is_admin ? <ShieldOff className="w-3.5 h-3.5" /> : <ShieldCheck className="w-3.5 h-3.5" />}
                </Button>
                <Button
                  data-testid={`invalidate-sessions-btn-${u.user_id}`}
                  size="sm"
                  variant="ghost"
                  onClick={() => invalidateSessions(u)}
                  className="rounded-lg h-8 px-2 text-slate-500 hover:text-slate-700"
                  title="Force-logout from all devices"
                >
                  <LogOut className="w-3.5 h-3.5" />
                </Button>
              </div>
            </div>
          ))}
          {!loading && users.length === 0 && (
            <div className="text-center text-sm text-slate-400 py-8">No users found.</div>
          )}
        </div>
      </CardContent>

      {/* Reset confirmation modal */}
      {resetTarget && (
        <div
          data-testid="reset-portfolio-modal"
          className="fixed inset-0 z-50 bg-slate-900/70 flex items-center justify-center p-4"
          onClick={closeReset}
        >
          <div
            className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl max-w-md w-full p-6"
            onClick={(e) => e.stopPropagation()}
          >
            {!resetResult ? (
              <>
                <div className="flex items-start gap-3 mb-4">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${resetMode === "full" ? "bg-rose-200 dark:bg-rose-900/60" : "bg-rose-100 dark:bg-rose-900/40"}`}>
                    <AlertTriangle className={`w-5 h-5 ${resetMode === "full" ? "text-rose-700" : "text-rose-600"}`} />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-slate-900 dark:text-white">
                      {resetMode === "full" ? "Full reset this user?" : "Reset portfolio for this user?"}
                    </h3>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                      Wipes holdings, action plans, AI insights, snapshots, transactions,
                      SIP detections, CAS parsed responses, chat history, copilot cache,
                      and all V3 / Redis caches. Then flips <code>onboarding_completed=false</code>{" "}
                      so they re-run the welcome flow on next login.
                    </p>
                    {resetMode === "full" && (
                      <p className="text-xs text-rose-700 dark:text-rose-400 mt-2 font-medium">
                        <strong>Also wipes NIDP Postgres:</strong> portfolio.user_intelligence_snapshot,
                        portfolio.user_holdings_snapshot (cascades to holding_security_map),
                        nidp.validation_findings. Unrecoverable without re-running portfolio_intelligence_sync.
                      </p>
                    )}
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
                      <strong>Preserved:</strong> the user account itself, sessions,
                      whitelist entry, Gmail tokens, family member profiles.
                    </p>
                  </div>
                  <button onClick={closeReset} className="text-slate-400 hover:text-slate-600">
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <div className="bg-slate-50 dark:bg-slate-900 rounded-xl p-3 mb-4 text-xs">
                  <div className="text-slate-500">Target</div>
                  <div className="font-medium text-slate-900 dark:text-white truncate">
                    {resetTarget.name || resetTarget.email}
                  </div>
                  <div className="text-slate-500 truncate">{resetTarget.email}</div>
                  <div className="mt-1.5 text-[11px] text-slate-500">
                    {resetTarget.holdings_count} holdings · {resetTarget.plans_count} plans
                  </div>
                </div>

                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                  Type the user's email to confirm:
                </label>
                <Input
                  data-testid="reset-confirm-email-input"
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  placeholder={resetTarget.email}
                  className="rounded-xl border-slate-200 dark:border-slate-700 dark:bg-slate-900 mb-4"
                  autoFocus
                  disabled={resetting}
                />

                <div className="flex items-center justify-end gap-2">
                  <Button
                    variant="outline"
                    onClick={closeReset}
                    disabled={resetting}
                    data-testid="reset-cancel-btn"
                    className="rounded-xl"
                  >
                    Cancel
                  </Button>
                  <Button
                    onClick={doReset}
                    disabled={
                      resetting ||
                      confirmText.trim().toLowerCase() !==
                        (resetTarget.email || "").toLowerCase()
                    }
                    data-testid="reset-confirm-btn"
                    className="rounded-xl bg-rose-600 hover:bg-rose-700 text-white"
                  >
                    {resetting ? (
                      <><Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> Resetting…</>
                    ) : resetMode === "full" ? (
                      <><Trash2 className="w-3.5 h-3.5 mr-1.5" /> Full Reset</>
                    ) : (
                      <><Trash2 className="w-3.5 h-3.5 mr-1.5" /> Reset Portfolio</>
                    )}
                  </Button>
                </div>
              </>
            ) : (
              <>
                <div className="flex items-start gap-3 mb-4">
                  <div className="w-10 h-10 rounded-xl bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center flex-shrink-0">
                    <ShieldCheck className="w-5 h-5 text-emerald-600" />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-slate-900 dark:text-white">
                      Reset complete
                    </h3>
                    <p className="text-xs text-slate-500 mt-1">
                      <strong>{resetResult.user_email}</strong> is now a clean slate. They'll
                      re-run onboarding next login.
                    </p>
                  </div>
                </div>
                <div className="bg-slate-50 dark:bg-slate-900 rounded-xl p-3 mb-4 text-[11px] max-h-64 overflow-y-auto">
                  <div className="font-bold text-slate-700 dark:text-slate-200 mb-2">
                    Wiped {resetResult.total_deleted} mongo doc(s)
                    {resetResult.pg_total_deleted != null && (
                      <> · {resetResult.pg_total_deleted} NIDP row(s)</>
                    )}
                    {" "}· {resetResult.redis_keys_cleared} Redis key(s)
                  </div>
                  <ul className="space-y-0.5">
                    {Object.entries(resetResult.deleted_per_collection || {})
                      .filter(([, n]) => n > 0)
                      .sort((a, b) => b[1] - a[1])
                      .map(([col, n]) => (
                        <li key={col} className="flex justify-between">
                          <code className="text-slate-600 dark:text-slate-400">{col}</code>
                          <span className="font-medium text-slate-700 dark:text-slate-300">{n}</span>
                        </li>
                      ))}
                  </ul>
                  {resetResult.pg_deleted_per_table && Object.values(resetResult.pg_deleted_per_table).some(n => n > 0) && (
                    <>
                      <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-700 font-medium text-slate-700 dark:text-slate-200 mb-1">
                        NIDP Postgres
                      </div>
                      <ul className="space-y-0.5">
                        {Object.entries(resetResult.pg_deleted_per_table)
                          .filter(([, n]) => n > 0)
                          .sort((a, b) => b[1] - a[1])
                          .map(([tbl, n]) => (
                            <li key={tbl} className="flex justify-between">
                              <code className="text-slate-600 dark:text-slate-400">{tbl}</code>
                              <span className="font-medium text-slate-700 dark:text-slate-300">{n}</span>
                            </li>
                          ))}
                      </ul>
                    </>
                  )}
                  {resetResult.profile_reset && (
                    <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-700 text-emerald-600 dark:text-emerald-400">
                      ✓ Onboarding flags reset
                    </div>
                  )}
                </div>
                <div className="flex justify-end">
                  <Button onClick={closeReset} className="rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white" data-testid="reset-done-btn">
                    Done
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Add user modal */}
      {addOpen && (
        <div
          data-testid="add-user-modal"
          className="fixed inset-0 z-50 bg-slate-900/70 flex items-center justify-center p-4"
          onClick={closeAdd}
        >
          <form
            onSubmit={submitAdd}
            className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl max-w-md w-full p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3 mb-4">
              <div className="w-10 h-10 rounded-xl bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center flex-shrink-0">
                <UserPlus className="w-5 h-5 text-indigo-600" />
              </div>
              <div className="flex-1">
                <h3 className="text-base font-bold text-slate-900 dark:text-white">Add user</h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  Whitelists the email so they can sign in via Google. The
                  account appears here immediately and becomes fully active
                  on first login.
                </p>
              </div>
              <button type="button" onClick={closeAdd} className="text-slate-400 hover:text-slate-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
              Email <span className="text-rose-500">*</span>
            </label>
            <div className="relative mb-3">
              <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <Input
                data-testid="add-user-email"
                type="email"
                value={addForm.email}
                onChange={(e) => setAddForm((f) => ({ ...f, email: e.target.value }))}
                placeholder="user@example.com"
                className="pl-10 rounded-xl border-slate-200 dark:border-slate-700 dark:bg-slate-900"
                autoFocus
                disabled={adding}
                required
              />
            </div>

            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
              Name <span className="text-slate-400 font-normal">(optional)</span>
            </label>
            <Input
              data-testid="add-user-name"
              value={addForm.name}
              onChange={(e) => setAddForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="Full name"
              className="rounded-xl border-slate-200 dark:border-slate-700 dark:bg-slate-900 mb-3"
              disabled={adding}
            />

            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300 mb-5 cursor-pointer">
              <input
                type="checkbox"
                data-testid="add-user-is-admin"
                checked={addForm.is_admin}
                onChange={(e) => setAddForm((f) => ({ ...f, is_admin: e.target.checked }))}
                className="rounded"
                disabled={adding}
              />
              Grant admin privileges
            </label>

            <div className="flex items-center justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={closeAdd}
                disabled={adding}
                className="rounded-xl"
                data-testid="add-user-cancel"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={adding || !addForm.email.trim()}
                data-testid="add-user-submit"
                className="rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white"
              >
                {adding ? (
                  <><Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> Adding…</>
                ) : (
                  <><UserPlus className="w-3.5 h-3.5 mr-1.5" /> Add user</>
                )}
              </Button>
            </div>
          </form>
        </div>
      )}
    </Card>
  );
}
