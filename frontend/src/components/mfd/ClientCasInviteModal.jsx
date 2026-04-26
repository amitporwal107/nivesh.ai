import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  X, Link2, Copy, MessageSquare, Mail, Loader2, CheckCircle2,
  Clock, AlertCircle, ShieldCheck, Send, RefreshCw, User, Phone,
  RotateCw, FolderOpen,
} from "lucide-react";
import SharedCasFiles from "./SharedCasFiles";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const STATUS_TONE = {
  PENDING:          { bg: "bg-amber-100 text-amber-800",   icon: Clock,        label: "Waiting for client" },
  DETAILS_CAPTURED: { bg: "bg-sky-100 text-sky-800",        icon: User,         label: "Details captured" },
  AUTHORIZED:       { bg: "bg-indigo-100 text-indigo-800",  icon: ShieldCheck,  label: "Gmail authorized" },
  COMPLETED:        { bg: "bg-emerald-100 text-emerald-800", icon: CheckCircle2, label: "Imported" },
  EXPIRED:          { bg: "bg-slate-100 text-slate-500",    icon: AlertCircle,  label: "Expired" },
  REVOKED:          { bg: "bg-rose-100 text-rose-700",      icon: X,            label: "Revoked" },
};

/**
 * Client CAS Invite modal — shown from Client 360 header.
 *
 * MFD can:
 *   1. Generate a new invite link (24h expiry). Optionally pre-fill
 *      client name / mobile / email so the client sees a friendlier
 *      first screen.
 *   2. Regenerate a fresh link on demand (auto-deactivates prior).
 *   3. Copy / WhatsApp / Email the link.
 *   4. See invite history with status badges + processed holdings count.
 *   5. Revoke a pending invite.
 */
export default function ClientCasInviteModal({ profileId, profileName, open, onClose }) {
  const [invites, setInvites] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);

  // Pre-fill form
  const [form, setForm] = useState({ client_name: "", client_mobile: "", client_email: "" });

  const load = useCallback(async () => {
    if (!profileId) return;
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/mfd/profiles/${profileId}/cas-invites`, { withCredentials: true });
      setInvites(data.invites || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load invites");
    } finally {
      setLoading(false);
    }
  }, [profileId]);

  useEffect(() => {
    if (open) {
      load();
      // Pre-fill client name from profile
      setForm((f) => ({ ...f, client_name: f.client_name || profileName || "" }));
    }
  }, [open, load, profileName]);

  const createInvite = async (regenerate = false) => {
    setCreating(true);
    try {
      await axios.post(
        `${API}/mfd/profiles/${profileId}/cas-invite`,
        {
          client_name: form.client_name || null,
          client_mobile: form.client_mobile || null,
          client_email: form.client_email || null,
          regenerate,
        },
        { withCredentials: true },
      );
      toast.success(regenerate ? "Fresh link generated" : "Invite link created");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not create invite");
    } finally {
      setCreating(false);
    }
  };

  const copyLink = async (url) => {
    try { await navigator.clipboard.writeText(url); toast.success("Link copied"); }
    catch { toast.error("Could not copy — select the text manually"); }
  };

  const shareWhatsApp = (url, clientMobile) => {
    const msg = encodeURIComponent(
      `Hi ${form.client_name || profileName}, please use this secure link to share your latest CAS statements with me:\n\n${url}\n\nTakes 2 minutes — link expires in 24h.\nYou'll sign in with your Gmail and pick which statements to share. Nivesh never stores your email content.`
    );
    const phone = (clientMobile || form.client_mobile || "").replace(/\D/g, "");
    const waUrl = phone ? `https://wa.me/${phone}?text=${msg}` : `https://wa.me/?text=${msg}`;
    window.open(waUrl, "_blank");
  };

  const shareEmail = (url, clientEmail) => {
    const subject = encodeURIComponent("Share your CAS statements — secure link");
    const body = encodeURIComponent(
      `Hi ${form.client_name || profileName},\n\nPlease use this secure link to share your CAS statements:\n${url}\n\n(Link expires in 24 hours)\n\nThanks!`
    );
    const to = clientEmail || form.client_email || "";
    window.location.href = `mailto:${to}?subject=${subject}&body=${body}`;
  };

  const revoke = async (token) => {
    if (!window.confirm("Revoke this invite? The client will no longer be able to use the link.")) return;
    try {
      await axios.post(`${API}/mfd/profiles/${profileId}/cas-invite/${token}/revoke`, {}, { withCredentials: true });
      toast.success("Invite revoked");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Revoke failed");
    }
  };

  if (!open) return null;

  const activeInvite = invites.find((i) => i.is_active !== false && ["PENDING", "DETAILS_CAPTURED", "AUTHORIZED"].includes(i.status));

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40 backdrop-blur-sm" onClick={onClose} data-testid="invite-backdrop" />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-2xl max-h-[92vh] overflow-y-auto bg-white dark:bg-slate-950 rounded-xl shadow-2xl z-50 border border-slate-200 dark:border-slate-800" data-testid="invite-modal">
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800 bg-gradient-to-r from-indigo-600 to-violet-600 text-white rounded-t-xl">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Link2 className="w-4 h-4" />
              <div>
                <div className="text-sm font-bold">Invite client to connect Gmail</div>
                <div className="text-[11px] opacity-80">{profileName} · link valid 24 hours</div>
              </div>
            </div>
            <button type="button" onClick={onClose} data-testid="invite-close" className="w-7 h-7 rounded-md hover:bg-white/20 flex items-center justify-center">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="p-5 space-y-5">
          {/* Client contact pre-fill */}
          {!activeInvite && (
            <div data-testid="invite-prefill-form" className="space-y-2">
              <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500">Pre-fill client contact (optional)</div>
              <div className="grid grid-cols-2 gap-2">
                <Input placeholder="Client name" value={form.client_name}
                       onChange={(e) => setForm({ ...form, client_name: e.target.value })}
                       data-testid="invite-prefill-name" className="text-xs" />
                <Input placeholder="Mobile (for WhatsApp share)" value={form.client_mobile}
                       onChange={(e) => setForm({ ...form, client_mobile: e.target.value })}
                       data-testid="invite-prefill-mobile" className="text-xs" />
              </div>
              <Input placeholder="Email (for email share)" value={form.client_email}
                     onChange={(e) => setForm({ ...form, client_email: e.target.value })}
                     data-testid="invite-prefill-email" className="text-xs" />
            </div>
          )}

          {/* Active invite OR generate button */}
          {activeInvite ? (
            <div data-testid="invite-active" className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500">Active invite link</span>
                <StatusBadge status={activeInvite.status} />
                <span className="ml-auto text-[10px] text-slate-500">{expiresInText(activeInvite.expires_at)}</span>
              </div>
              <div className="flex items-center gap-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2">
                <Input readOnly value={publicUrl(activeInvite.invite_token)}
                       className="flex-1 text-[11px] bg-transparent border-0 outline-none focus-visible:ring-0 p-0 h-auto"
                       data-testid="invite-url-input" />
                <Button type="button" size="sm" variant="outline"
                        onClick={() => copyLink(publicUrl(activeInvite.invite_token))}
                        data-testid="invite-copy-btn" className="h-7 text-[11px]">
                  <Copy className="w-3 h-3 mr-1" /> Copy
                </Button>
              </div>
              <div className="flex items-center gap-2">
                <Button type="button" onClick={() => shareWhatsApp(publicUrl(activeInvite.invite_token), activeInvite.client_mobile_prefill)}
                        data-testid="invite-whatsapp-btn" className="flex-1 h-9 text-xs bg-emerald-600 hover:bg-emerald-700">
                  <MessageSquare className="w-3.5 h-3.5 mr-1.5" /> WhatsApp
                </Button>
                <Button type="button" variant="outline" onClick={() => shareEmail(publicUrl(activeInvite.invite_token), activeInvite.client_email_prefill)}
                        data-testid="invite-email-btn" className="flex-1 h-9 text-xs">
                  <Mail className="w-3.5 h-3.5 mr-1.5" /> Email
                </Button>
                <Button type="button" variant="outline" onClick={() => createInvite(true)}
                        disabled={creating}
                        data-testid="invite-regenerate-btn" className="flex-1 h-9 text-xs">
                  {creating ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <RotateCw className="w-3 h-3 mr-1" />} Regenerate
                </Button>
              </div>
              <div className="flex items-center justify-between text-[10px] text-slate-500">
                <span>
                  {activeInvite.processed_files?.length > 0
                    ? `${activeInvite.processed_files.filter((f) => f.status === "completed").length}/${activeInvite.processed_files.length} statement(s) processed`
                    : "Waiting for client to open the link"}
                </span>
                <button type="button" onClick={() => revoke(activeInvite.invite_token)}
                        className="text-rose-600 hover:underline" data-testid="invite-revoke-btn">
                  Revoke
                </button>
              </div>
            </div>
          ) : (
            <div className="text-center py-2" data-testid="invite-empty">
              <ShieldCheck className="w-8 h-8 text-indigo-400 mx-auto mb-2" />
              <h3 className="text-sm font-bold text-slate-800 dark:text-slate-100 mb-1">
                Generate a secure 24-hour link
              </h3>
              <p className="text-[11px] text-slate-500 mb-4 max-w-sm mx-auto">
                Your client signs in with their own Gmail on their device, picks CAS statements, and we attach holdings to this profile. Link auto-expires in 24h.
              </p>
              <Button type="button" onClick={() => createInvite(false)} disabled={creating}
                      data-testid="invite-create-btn" className="h-9 text-sm">
                {creating ? (<><Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> Creating…</>) :
                            (<><Send className="w-3.5 h-3.5 mr-1.5" /> Create invite link</>)}
              </Button>
            </div>
          )}

          {/* History */}
          {invites.length > 0 && (
            <div data-testid="invite-history">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500">History</span>
                <button type="button" onClick={load} className="text-[10px] text-indigo-600 hover:underline flex items-center gap-1" data-testid="invite-refresh">
                  <RefreshCw className={`w-2.5 h-2.5 ${loading ? "animate-spin" : ""}`} /> Refresh
                </button>
              </div>
              <div className="space-y-1.5">
                {invites.map((inv) => {
                  const holdings = (inv.processed_files || []).filter((f) => f.status === "completed").reduce((s, f) => s + (f.holdings_count || 0), 0);
                  return (
                    <div
                      key={inv.invite_token}
                      data-testid={`invite-row-${inv.invite_token}`}
                      className="flex items-center justify-between text-[11px] px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <StatusBadge status={inv.status} />
                        <span className="truncate text-slate-600 dark:text-slate-300">
                          {fmtDate(inv.created_at)}
                          {inv.client_email ? ` · ${inv.client_email}` : ""}
                        </span>
                      </div>
                      {holdings > 0 && (
                        <span className="text-emerald-600 font-semibold whitespace-nowrap">{holdings} holdings</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Shared CAS files (raw PDFs) — MFD audit + selective re-parse */}
          <div className="pt-3 border-t border-slate-200 dark:border-slate-800" data-testid="shared-cas-files-section">
            <div className="flex items-center gap-2 mb-2">
              <FolderOpen className="w-3.5 h-3.5 text-indigo-500" />
              <span className="text-xs font-bold text-slate-700 dark:text-slate-200">Shared CAS files</span>
              <span className="text-[10px] text-slate-400">PDFs the client has uploaded for this profile</span>
            </div>
            <SharedCasFiles profileId={profileId} compact />
          </div>
        </div>
      </div>
    </>
  );
}

function StatusBadge({ status }) {
  const tone = STATUS_TONE[status] || STATUS_TONE.PENDING;
  const Icon = tone.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded ${tone.bg}`} data-testid={`invite-status-${status}`}>
      <Icon className="w-2.5 h-2.5" /> {tone.label}
    </span>
  );
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch { return iso.slice(0, 10); }
}

function expiresInText(iso) {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return "Expired";
  const hours = Math.floor(ms / 3600000);
  const mins = Math.floor((ms % 3600000) / 60000);
  if (hours >= 1) return `Expires in ${hours}h ${mins}m`;
  return `Expires in ${mins}m`;
}

function publicUrl(token) {
  if (typeof window === "undefined") return `/cas-connect/${token}`;
  return `${window.location.origin}/cas-connect/${token}`;
}
