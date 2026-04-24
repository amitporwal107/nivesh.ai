import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  X, Link2, Copy, MessageSquare, Mail, Loader2, CheckCircle2,
  Clock, AlertCircle, ShieldCheck, Send, RefreshCw,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const STATUS_TONE = {
  PENDING:    { bg: "bg-amber-100 text-amber-800",   icon: Clock,        label: "Waiting for client" },
  AUTHORIZED: { bg: "bg-sky-100 text-sky-800",        icon: ShieldCheck,  label: "Client signed in" },
  COMPLETED:  { bg: "bg-emerald-100 text-emerald-800", icon: CheckCircle2, label: "Imported" },
  EXPIRED:    { bg: "bg-slate-100 text-slate-500",    icon: AlertCircle,  label: "Expired" },
  REVOKED:    { bg: "bg-rose-100 text-rose-700",      icon: X,            label: "Revoked" },
};

/**
 * Client CAS Invite modal — shown from Client 360 header.
 *
 * MFD can:
 *   1. Generate a new invite link (expires in 7 days)
 *   2. Copy / share via WhatsApp / Email
 *   3. See status of previous invites (pending / completed / expired)
 *   4. Revoke a pending invite
 */
export default function ClientCasInviteModal({ profileId, profileName, open, onClose }) {
  const [invites, setInvites] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);

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
    if (open) load();
  }, [open, load]);

  const createInvite = async () => {
    setCreating(true);
    try {
      await axios.post(`${API}/mfd/profiles/${profileId}/cas-invite`, {}, { withCredentials: true });
      toast.success("Invite link created — share it with the client");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not create invite");
    } finally {
      setCreating(false);
    }
  };

  const copyLink = async (url) => {
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Link copied to clipboard");
    } catch {
      toast.error("Could not copy — long-press the link above to copy manually");
    }
  };

  const shareWhatsApp = (url) => {
    const msg = encodeURIComponent(
      `Hi ${profileName}, please use this secure link to share your latest CAS statements with me:\n\n${url}\n\nTakes 2 minutes — you'll sign in with your Gmail and pick which statements to share. Nivesh never stores your email content.`
    );
    window.open(`https://wa.me/?text=${msg}`, "_blank");
  };

  const shareEmail = (url) => {
    const subject = encodeURIComponent("Share your CAS statements — secure link");
    const body = encodeURIComponent(
      `Hi ${profileName},\n\nPlease use this secure link to share your latest CAS statements with me:\n\n${url}\n\nIt takes 2 minutes:\n  1. Sign in with your Gmail (read-only access)\n  2. Pick which statements to import\n  3. We'll parse and update your portfolio\n\nThanks!`
    );
    window.location.href = `mailto:?subject=${subject}&body=${body}`;
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

  const pendingInvites = invites.filter((i) => ["PENDING", "AUTHORIZED"].includes(i.status));
  const activeInvite = pendingInvites[0]; // most recent not-yet-expired

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40 backdrop-blur-sm" onClick={onClose} data-testid="invite-backdrop" />
      <div
        className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-lg max-h-[90vh] overflow-y-auto bg-white dark:bg-slate-950 rounded-xl shadow-2xl z-50 border border-slate-200 dark:border-slate-800"
        data-testid="invite-modal"
      >
        {/* Header */}
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800 bg-gradient-to-r from-indigo-600 to-violet-600 text-white rounded-t-xl">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Link2 className="w-4 h-4" />
              <div>
                <div className="text-sm font-bold">Invite client to connect Gmail</div>
                <div className="text-[11px] opacity-80">{profileName} will share CAS statements from their own device</div>
              </div>
            </div>
            <button type="button" onClick={onClose} data-testid="invite-close" className="w-7 h-7 rounded-md hover:bg-white/20 flex items-center justify-center">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="p-5 space-y-5">
          {/* Active invite OR generate button */}
          {activeInvite ? (
            <div data-testid="invite-active" className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500">Active invite link</span>
                <StatusBadge status={activeInvite.status} />
              </div>
              <div className="flex items-center gap-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2">
                <Input
                  readOnly
                  value={publicUrl(activeInvite.invite_token)}
                  className="flex-1 text-[11px] bg-transparent border-0 outline-none focus-visible:ring-0 p-0 h-auto"
                  data-testid="invite-url-input"
                />
                <Button type="button" size="sm" variant="outline" onClick={() => copyLink(publicUrl(activeInvite.invite_token))} data-testid="invite-copy-btn" className="h-7 text-[11px]">
                  <Copy className="w-3 h-3 mr-1" /> Copy
                </Button>
              </div>
              <div className="flex items-center gap-2">
                <Button type="button" onClick={() => shareWhatsApp(publicUrl(activeInvite.invite_token))} data-testid="invite-whatsapp-btn" className="flex-1 h-9 text-xs bg-emerald-600 hover:bg-emerald-700">
                  <MessageSquare className="w-3.5 h-3.5 mr-1.5" /> Send via WhatsApp
                </Button>
                <Button type="button" variant="outline" onClick={() => shareEmail(publicUrl(activeInvite.invite_token))} data-testid="invite-email-btn" className="flex-1 h-9 text-xs">
                  <Mail className="w-3.5 h-3.5 mr-1.5" /> Email
                </Button>
              </div>
              <div className="flex items-center justify-between text-[10px] text-slate-500">
                <span>Expires {fmtDate(activeInvite.expires_at)} · {activeInvite.processed_files?.length || 0} statement{(activeInvite.processed_files?.length || 0) === 1 ? "" : "s"} processed</span>
                <button type="button" onClick={() => revoke(activeInvite.invite_token)} className="text-rose-600 hover:underline" data-testid="invite-revoke-btn">
                  Revoke
                </button>
              </div>
            </div>
          ) : (
            <div className="text-center py-4" data-testid="invite-empty">
              <ShieldCheck className="w-8 h-8 text-indigo-400 mx-auto mb-2" />
              <h3 className="text-sm font-bold text-slate-800 dark:text-slate-100 mb-1">
                Generate a secure link to request CAS statements
              </h3>
              <p className="text-[11px] text-slate-500 mb-4 max-w-sm mx-auto">
                Your client signs in with their own Gmail on their device. We scan only CAMS + KFintech CAS emails, and they pick which to share. The link expires in 7 days.
              </p>
              <Button type="button" onClick={createInvite} disabled={creating} data-testid="invite-create-btn" className="h-9 text-sm">
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
                {invites.map((inv) => (
                  <div
                    key={inv.invite_token}
                    data-testid={`invite-row-${inv.invite_token}`}
                    className="flex items-center justify-between text-[11px] px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <StatusBadge status={inv.status} />
                      <span className="truncate text-slate-600 dark:text-slate-300">
                        Created {fmtDate(inv.created_at)}
                        {inv.client_email ? ` · by ${inv.client_email}` : ""}
                      </span>
                    </div>
                    <span className="text-emerald-600 font-semibold whitespace-nowrap">
                      {(inv.processed_files || []).filter((f) => f.status === "completed").reduce((sum, f) => sum + (f.holdings_count || 0), 0) || ""}
                      {(inv.processed_files || []).filter((f) => f.status === "completed").reduce((sum, f) => sum + (f.holdings_count || 0), 0) > 0 ? " holdings" : ""}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
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
    return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
  } catch { return iso.slice(0, 10); }
}

// Build the public invite URL from the frontend's own origin so the
// link always uses the externally-reachable hostname (backend's
// base_url is the cluster-internal host behind the ingress).
function publicUrl(token) {
  if (typeof window === "undefined") return `/cas-connect/${token}`;
  return `${window.location.origin}/cas-connect/${token}`;
}
