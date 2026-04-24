import React, { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { UserPlus, X } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * AddClientDialog — minimal MVP per PRD Module 1.
 *
 * Collects Name + AUM + Tags + Notes and POSTs to `/api/mfd/profiles`.
 * CAS upload happens later inside the client context — after creating
 * the profile, the MFD is invited to "Open client → Upload CAS" which
 * then hits the existing `/api/portfolio/upload` endpoint against the
 * impersonated client's shadow user. That keeps this form tight.
 */

const SUGGESTED_TAGS = ["Retail", "HNI", "Ultra-HNI", "Conservative", "Moderate", "Aggressive"];

export default function AddClientDialog({ open, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [mobile, setMobile] = useState("");
  const [email, setEmail] = useState("");
  const [aum, setAum] = useState("");
  const [tags, setTags] = useState([]);
  const [tagInput, setTagInput] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const reset = () => {
    setName(""); setMobile(""); setEmail(""); setAum("");
    setTags([]); setTagInput(""); setNotes("");
  };

  const addTag = (t) => {
    const clean = t.trim();
    if (!clean || tags.includes(clean) || tags.length >= 5) return;
    setTags([...tags, clean]);
    setTagInput("");
  };

  const removeTag = (t) => setTags(tags.filter((x) => x !== t));

  const submit = async () => {
    if (!name.trim()) { toast.error("Client name is required"); return; }
    if (!/^\d{10,}$/.test(mobile.replace(/\D/g, ""))) {
      toast.error("Mobile is required (≥10 digits) — we use it to send the CAS invite link");
      return;
    }
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      toast.error("Email is required — we'll send a backup link there");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: name.trim(),
        mobile: mobile.trim(),
        email: email.trim(),
        aum_rs: aum ? Number(aum) : null,
        tags: tags.length ? tags : null,
        notes: notes.trim() || null,
      };
      const res = await axios.post(`${API}/mfd/profiles`, payload,
                                   { withCredentials: true });
      toast.success(`${res.data.name} added to your client book`);
      reset();
      onCreated?.(res.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not add client");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) { reset(); onClose?.(); } }}>
      <DialogContent data-testid="add-client-dialog" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserPlus className="w-5 h-5 text-indigo-600" /> Add Client
          </DialogTitle>
          <p className="text-xs text-slate-500 mt-1">
            Create a client profile. You can upload their CAS statement right
            after, from inside their portfolio view.
          </p>
        </DialogHeader>

        <div className="space-y-4 mt-2">
          <div>
            <Label htmlFor="mfd-client-name" className="text-xs">Full name *</Label>
            <Input
              id="mfd-client-name"
              data-testid="add-client-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Rahul Sharma"
              className="mt-1"
              autoFocus
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <Label htmlFor="mfd-client-mobile" className="text-xs">Mobile (WhatsApp) *</Label>
              <Input
                id="mfd-client-mobile"
                data-testid="add-client-mobile"
                value={mobile}
                onChange={(e) => setMobile(e.target.value)}
                placeholder="98xxxxxxxx"
                inputMode="tel"
                className="mt-1 font-mono tabular-nums"
              />
            </div>
            <div>
              <Label htmlFor="mfd-client-email" className="text-xs">Email *</Label>
              <Input
                id="mfd-client-email"
                data-testid="add-client-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="rahul@example.com"
                className="mt-1"
              />
            </div>
          </div>
          <div className="text-[10px] text-slate-500 -mt-2">
            Used for the secure CAS invite — WhatsApp first, email as backup.
          </div>

          <div>
            <Label htmlFor="mfd-client-aum" className="text-xs">
              AUM (₹) <span className="text-slate-400">· optional, used for priority</span>
            </Label>
            <Input
              id="mfd-client-aum"
              data-testid="add-client-aum"
              type="number"
              value={aum}
              onChange={(e) => setAum(e.target.value)}
              placeholder="2500000"
              className="mt-1 font-mono tabular-nums"
            />
            {aum && Number(aum) > 0 && (
              <div className="text-[10px] text-slate-500 mt-1">
                ≈ {formatRs(Number(aum))}
              </div>
            )}
          </div>

          <div>
            <Label className="text-xs">Tags <span className="text-slate-400">· optional, up to 5</span></Label>
            <div className="flex flex-wrap gap-1.5 mt-1 mb-1.5 min-h-[26px]">
              {tags.map((t) => (
                <Badge
                  key={t}
                  variant="outline"
                  className="text-[10px] gap-1 pr-1"
                  data-testid={`add-client-tag-${t}`}
                >
                  {t}
                  <button
                    onClick={() => removeTag(t)}
                    className="hover:bg-slate-200 rounded-full p-0.5"
                    aria-label={`Remove ${t}`}
                  >
                    <X className="w-2.5 h-2.5" />
                  </button>
                </Badge>
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                data-testid="add-client-tag-input"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") { e.preventDefault(); addTag(tagInput); }
                }}
                placeholder="Add a tag and press Enter"
                className="text-xs h-8"
              />
            </div>
            <div className="flex flex-wrap gap-1 mt-1.5">
              {SUGGESTED_TAGS.filter((t) => !tags.includes(t)).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => addTag(t)}
                  className="text-[10px] px-2 py-0.5 rounded-full border border-dashed border-slate-300 text-slate-500 hover:border-indigo-400 hover:text-indigo-700"
                  data-testid={`add-client-suggestion-${t}`}
                >
                  + {t}
                </button>
              ))}
            </div>
          </div>

          <div>
            <Label htmlFor="mfd-client-notes" className="text-xs">
              Notes <span className="text-slate-400">· optional</span>
            </Label>
            <Textarea
              id="mfd-client-notes"
              data-testid="add-client-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="E.g. SIP of ₹25k/mo, wife is co-client, next review due Aug…"
              className="mt-1 text-xs min-h-[60px]"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={submit}
            disabled={saving || !name.trim()}
            data-testid="add-client-submit"
            className="bg-indigo-600 hover:bg-indigo-700"
          >
            {saving ? "Adding…" : "Add client"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function formatRs(n) {
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}
