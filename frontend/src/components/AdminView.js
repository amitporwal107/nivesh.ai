import React, { useState, useEffect, useRef } from "react";
import axios from "axios";
import {
  UserPlus, Trash2, Upload, Shield, ShieldCheck, ShieldX,
  Users, BarChart3, RefreshCw, Search, AlertCircle, Check,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import CasConfigSection from "@/components/admin/CasConfigSection";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const STATUS_CONFIG = {
  active: { label: "Active", color: "text-emerald-600", bg: "bg-emerald-50 dark:bg-emerald-900/20", border: "border-emerald-200 dark:border-emerald-800" },
  invited: { label: "Pending", color: "text-amber-600", bg: "bg-amber-50 dark:bg-amber-900/20", border: "border-amber-200 dark:border-amber-800" },
  blocked: { label: "Blocked", color: "text-red-500", bg: "bg-red-50 dark:bg-red-900/20", border: "border-red-200 dark:border-red-800" },
};

const AdminView = () => {
  const [whitelist, setWhitelist] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [newEmail, setNewEmail] = useState("");
  const [newIsAdmin, setNewIsAdmin] = useState(false);
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");
  const [bulkText, setBulkText] = useState("");
  const [showBulk, setShowBulk] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [wlRes, stRes] = await Promise.all([
        axios.get(`${API}/admin/whitelist`, { withCredentials: true }),
        axios.get(`${API}/admin/stats`, { withCredentials: true }),
      ]);
      setWhitelist(wlRes.data);
      setStats(stRes.data);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to load admin data");
    } finally {
      setLoading(false);
    }
  };

  const addEmail = async (e) => {
    e.preventDefault();
    if (!newEmail.trim()) return;
    setAdding(true);
    try {
      await axios.post(`${API}/admin/whitelist/add`, { email: newEmail.trim(), is_admin: newIsAdmin }, { withCredentials: true });
      toast.success(`${newEmail.trim()} added to whitelist`);
      setNewEmail("");
      setNewIsAdmin(false);
      loadData();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to add email");
    } finally {
      setAdding(false);
    }
  };

  const removeEmail = async (email) => {
    if (!window.confirm(`Remove ${email} from whitelist? Their sessions will be invalidated.`)) return;
    try {
      await axios.delete(`${API}/admin/whitelist/${encodeURIComponent(email)}`, { withCredentials: true });
      toast.success(`${email} removed`);
      loadData();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to remove");
    }
  };

  const toggleAdmin = async (email, currentIsAdmin) => {
    try {
      await axios.patch(`${API}/admin/whitelist/${encodeURIComponent(email)}`, { is_admin: !currentIsAdmin }, { withCredentials: true });
      toast.success(`${email} admin status updated`);
      loadData();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to update");
    }
  };

  const toggleBlock = async (email, currentStatus) => {
    const newStatus = currentStatus === "blocked" ? "invited" : "blocked";
    try {
      await axios.patch(`${API}/admin/whitelist/${encodeURIComponent(email)}`, { status: newStatus }, { withCredentials: true });
      toast.success(`${email} ${newStatus === "blocked" ? "blocked" : "unblocked"}`);
      loadData();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to update");
    }
  };

  const bulkUpload = async () => {
    const emails = bulkText.split(/[\n,;]+/).map(e => e.trim()).filter(e => e && e.includes("@"));
    if (!emails.length) { toast.error("No valid emails found"); return; }
    try {
      const res = await axios.post(`${API}/admin/whitelist/bulk-upload`, { emails }, { withCredentials: true });
      toast.success(`Added: ${res.data.added}, Skipped: ${res.data.skipped}`);
      setBulkText("");
      setShowBulk(false);
      loadData();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Bulk upload failed");
    }
  };

  const handleCSVUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target.result;
      const emails = text.split(/[\n,;]+/).map(l => l.trim()).filter(l => l.includes("@"));
      setBulkText(emails.join("\n"));
      setShowBulk(true);
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const filtered = whitelist.filter(w =>
    w.email.includes(search.toLowerCase()) ||
    (w.user_name || "").toLowerCase().includes(search.toLowerCase())
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div data-testid="admin-view" className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Admin Panel
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">Manage invite-only access and whitelisted users</p>
        </div>
        <Button onClick={loadData} variant="outline" className="rounded-xl border-slate-200 dark:border-slate-700" data-testid="refresh-admin">
          <RefreshCw className="w-4 h-4 mr-2" /> Refresh
        </Button>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[
            { label: "Whitelisted", value: stats.whitelist.total, color: "text-slate-900 dark:text-white" },
            { label: "Active", value: stats.whitelist.active, color: "text-emerald-600" },
            { label: "Pending", value: stats.whitelist.pending, color: "text-amber-600" },
            { label: "Blocked", value: stats.whitelist.blocked, color: "text-red-500" },
            { label: "Conversion", value: `${stats.whitelist.conversion_rate}%`, color: "text-blue-600" },
          ].map(s => (
            <Card key={s.label} className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
              <CardContent className="p-4">
                <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">{s.label}</p>
                <p className={`text-xl font-semibold mt-1 ${s.color}`} style={{ fontFamily: "'Outfit', sans-serif" }} data-testid={`stat-${s.label.toLowerCase()}`}>{s.value}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* CAS Parser API Config */}
      <CasConfigSection />

      {/* Add Email Form */}
      <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
        <CardContent className="p-6">
          <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-4" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Add to Whitelist
          </h3>
          <form onSubmit={addEmail} className="flex items-center gap-3 flex-wrap">
            <input
              data-testid="add-email-input"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              placeholder="email@example.com"
              type="email"
              className="flex-1 min-w-[200px] bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl px-4 py-2.5 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none focus:border-emerald-500"
            />
            <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={newIsAdmin}
                onChange={(e) => setNewIsAdmin(e.target.checked)}
                className="rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
              />
              Admin
            </label>
            <Button type="submit" disabled={adding || !newEmail.trim()} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl" data-testid="add-email-button">
              <UserPlus className="w-4 h-4 mr-2" /> {adding ? "Adding..." : "Add"}
            </Button>
            <Button type="button" variant="outline" className="rounded-xl border-slate-200 dark:border-slate-700" onClick={() => setShowBulk(!showBulk)} data-testid="bulk-toggle">
              <Upload className="w-4 h-4 mr-2" /> Bulk
            </Button>
            <input ref={fileRef} type="file" accept=".csv,.txt" onChange={handleCSVUpload} className="hidden" />
            <Button type="button" variant="outline" className="rounded-xl border-slate-200 dark:border-slate-700" onClick={() => fileRef.current?.click()} data-testid="csv-upload-button">
              CSV
            </Button>
          </form>

          {/* Bulk upload text area */}
          <AnimatePresence>
            {showBulk && (
              <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="mt-4">
                <textarea
                  data-testid="bulk-emails-input"
                  value={bulkText}
                  onChange={(e) => setBulkText(e.target.value)}
                  placeholder="Paste emails, one per line or comma-separated..."
                  rows={4}
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none focus:border-emerald-500"
                />
                <div className="flex justify-end mt-2">
                  <Button onClick={bulkUpload} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl" data-testid="bulk-upload-submit">
                    Upload {bulkText.split(/[\n,;]+/).filter(e => e.trim().includes("@")).length} emails
                  </Button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </CardContent>
      </Card>

      {/* Whitelist Table */}
      <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl overflow-hidden">
        <CardContent className="p-0">
          <div className="p-4 border-b border-slate-100 dark:border-slate-700 flex items-center gap-3">
            <Search className="w-4 h-4 text-slate-400" />
            <input
              data-testid="whitelist-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by email or name..."
              className="flex-1 bg-transparent text-sm text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none"
            />
            <span className="text-xs text-slate-400">{filtered.length} of {whitelist.length}</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full" data-testid="whitelist-table">
              <thead>
                <tr className="border-b border-slate-100 dark:border-slate-700">
                  <th className="text-left p-4 text-[10px] font-bold tracking-wider uppercase text-slate-400">Email</th>
                  <th className="text-left p-4 text-[10px] font-bold tracking-wider uppercase text-slate-400">Status</th>
                  <th className="text-left p-4 text-[10px] font-bold tracking-wider uppercase text-slate-400">Role</th>
                  <th className="text-left p-4 text-[10px] font-bold tracking-wider uppercase text-slate-400">Invited</th>
                  <th className="text-right p-4 text-[10px] font-bold tracking-wider uppercase text-slate-400">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((entry, i) => {
                  const cfg = STATUS_CONFIG[entry.status] || STATUS_CONFIG.invited;
                  return (
                    <tr key={entry.email} className="border-b border-slate-50 dark:border-slate-700/50 hover:bg-slate-50/50 dark:hover:bg-slate-700/20 transition-colors" data-testid={`whitelist-row-${i}`}>
                      <td className="p-4">
                        <div className="flex items-center gap-3">
                          {entry.user_picture ? (
                            <img src={entry.user_picture} alt="" className="w-8 h-8 rounded-full" />
                          ) : (
                            <div className="w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 flex items-center justify-center text-xs font-bold text-slate-400">
                              {entry.email.charAt(0).toUpperCase()}
                            </div>
                          )}
                          <div>
                            <p className="text-sm font-medium text-slate-900 dark:text-white">{entry.email}</p>
                            {entry.user_name && <p className="text-xs text-slate-400">{entry.user_name}</p>}
                          </div>
                        </div>
                      </td>
                      <td className="p-4">
                        <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-lg ${cfg.bg} ${cfg.border} border ${cfg.color}`}>
                          {cfg.label}
                        </span>
                      </td>
                      <td className="p-4">
                        {entry.is_admin ? (
                          <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-lg bg-violet-50 dark:bg-violet-900/20 border border-violet-200 dark:border-violet-800 text-violet-600">
                            Admin
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">User</span>
                        )}
                      </td>
                      <td className="p-4 text-xs text-slate-400">
                        {entry.invited_at ? new Date(entry.invited_at).toLocaleDateString() : "—"}
                      </td>
                      <td className="p-4 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => toggleAdmin(entry.email, entry.is_admin)}
                            className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                            title={entry.is_admin ? "Remove admin" : "Make admin"}
                            data-testid={`toggle-admin-${i}`}
                          >
                            {entry.is_admin ? <ShieldCheck className="w-4 h-4 text-violet-600" /> : <Shield className="w-4 h-4 text-slate-400" />}
                          </button>
                          <button
                            onClick={() => toggleBlock(entry.email, entry.status)}
                            className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                            title={entry.status === "blocked" ? "Unblock" : "Block"}
                            data-testid={`toggle-block-${i}`}
                          >
                            <ShieldX className={`w-4 h-4 ${entry.status === "blocked" ? "text-red-500" : "text-slate-400"}`} />
                          </button>
                          <button
                            onClick={() => removeEmail(entry.email)}
                            className="p-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                            title="Remove from whitelist"
                            data-testid={`remove-${i}`}
                          >
                            <Trash2 className="w-4 h-4 text-slate-400 hover:text-red-500" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {filtered.length === 0 && (
            <div className="p-8 text-center">
              <Users className="w-12 h-12 text-slate-300 mx-auto mb-4" />
              <p className="text-sm text-slate-500">{search ? "No matching users" : "No whitelisted users yet"}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default AdminView;
