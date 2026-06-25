/**
 * AddClientModal — create a client profile (mirrors V2 AddClientDialog).
 *
 * Collects Name + Mobile + Email + AUM + Tags + Notes and POSTs to
 * /api/mfd/profiles. CAS upload happens later from inside the client context.
 * V5 has no Dialog primitive, so this uses the project's modal pattern
 * (fixed overlay + backdrop) with token-styled raw inputs.
 */
import { useState } from "react";
import { UserPlus, X } from "lucide-react";
import { useCreateClient } from "@/hooks/use-advisor";
import { useToastStore } from "@/stores/toast.store";
import { ApiError } from "@/services/api/errors";
import { fmtRs } from "./derive";

const SUGGESTED_TAGS = ["Retail", "HNI", "Ultra-HNI", "Conservative", "Moderate", "Aggressive"];

const inputCls =
  "w-full rounded-md bg-bg border border-hairline px-3 py-2 text-sm text-ink placeholder:text-ink-4 focus:outline-none focus:ring-1 focus:ring-accent mt-1";

export function AddClientModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated?: () => void }) {
  const push = useToastStore((s) => s.push);
  const create = useCreateClient();

  const [name, setName] = useState("");
  const [mobile, setMobile] = useState("");
  const [email, setEmail] = useState("");
  const [aum, setAum] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [notes, setNotes] = useState("");

  if (!open) return null;

  const reset = () => {
    setName(""); setMobile(""); setEmail(""); setAum("");
    setTags([]); setTagInput(""); setNotes("");
  };
  const close = () => { reset(); onClose(); };

  const addTag = (t: string) => {
    const clean = t.trim();
    if (!clean || tags.includes(clean) || tags.length >= 5) return;
    setTags([...tags, clean]);
    setTagInput("");
  };
  const removeTag = (t: string) => setTags(tags.filter((x) => x !== t));

  const submit = () => {
    if (!name.trim()) { push({ kind: "warn", title: "Client name is required" }); return; }
    if (!/^\d{10,}$/.test(mobile.replace(/\D/g, ""))) {
      push({ kind: "warn", title: "Mobile is required", description: "≥10 digits — used to send the CAS invite link." });
      return;
    }
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      push({ kind: "warn", title: "Email is required", description: "We'll send a backup link there." });
      return;
    }
    create.mutate(
      {
        name: name.trim(),
        mobile: mobile.trim(),
        email: email.trim(),
        aum_rs: aum ? Number(aum) : null,
        tags: tags.length ? tags : null,
        notes: notes.trim() || null,
      },
      {
        onSuccess: (res) => {
          push({ kind: "success", title: `${res.name} added to your client book` });
          reset();
          onCreated?.();
          onClose();
        },
        onError: (e) => {
          const conflict = e instanceof ApiError && e.kind === "conflict";
          push({
            kind: conflict ? "warn" : "error",
            title: conflict ? "Client already exists" : "Could not add client",
            description: e instanceof Error ? e.message : undefined,
          });
        },
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" onClick={close} />
      <div
        data-testid="add-client-dialog"
        className="relative w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-lg border border-hairline bg-surface-1 shadow-pop p-6"
      >
        <button onClick={close} className="absolute top-4 right-4 text-ink-4 hover:text-ink-2" aria-label="Close">
          <X className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-2">
          <UserPlus className="w-5 h-5 text-accent" />
          <h2 className="font-display text-lg tracking-tightish text-ink">Add client</h2>
        </div>
        <p className="text-xs text-ink-3 mt-1">
          Create a client profile. You can upload their CAS statement right after, from inside their portfolio view.
        </p>

        <div className="space-y-4 mt-4">
          <div>
            <label htmlFor="ac-name" className="text-xs text-ink-2">Full name *</label>
            <input id="ac-name" data-testid="add-client-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Rahul Sharma" className={inputCls} autoFocus />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="ac-mobile" className="text-xs text-ink-2">Mobile (WhatsApp) *</label>
              <input id="ac-mobile" data-testid="add-client-mobile" value={mobile} onChange={(e) => setMobile(e.target.value)} placeholder="98xxxxxxxx" inputMode="tel" className={`${inputCls} font-mono tabular-nums`} />
            </div>
            <div>
              <label htmlFor="ac-email" className="text-xs text-ink-2">Email *</label>
              <input id="ac-email" data-testid="add-client-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="rahul@example.com" className={inputCls} />
            </div>
          </div>
          <div className="text-[10px] text-ink-4 -mt-2">Used for the secure CAS invite — WhatsApp first, email as backup.</div>

          <div>
            <label htmlFor="ac-aum" className="text-xs text-ink-2">AUM (₹) <span className="text-ink-4">· optional, used for priority</span></label>
            <input id="ac-aum" data-testid="add-client-aum" type="number" value={aum} onChange={(e) => setAum(e.target.value)} placeholder="2500000" className={`${inputCls} font-mono tabular-nums`} />
            {aum && Number(aum) > 0 && <div className="text-[10px] text-ink-4 mt-1">≈ {fmtRs(Number(aum))}</div>}
          </div>

          <div>
            <label className="text-xs text-ink-2">Tags <span className="text-ink-4">· optional, up to 5</span></label>
            <div className="flex flex-wrap gap-1.5 mt-1 mb-1.5 min-h-[26px]">
              {tags.map((t) => (
                <span key={t} className="inline-flex items-center gap-1 text-[10px] rounded-full border border-hairline px-2 py-0.5 text-ink-2" data-testid={`add-client-tag-${t}`}>
                  {t}
                  <button onClick={() => removeTag(t)} className="hover:bg-surface-2 rounded-full p-0.5" aria-label={`Remove ${t}`}>
                    <X className="w-2.5 h-2.5" />
                  </button>
                </span>
              ))}
            </div>
            <input
              data-testid="add-client-tag-input" value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(tagInput); } }}
              placeholder="Add a tag and press Enter" className={`${inputCls} text-xs`}
            />
            <div className="flex flex-wrap gap-1 mt-1.5">
              {SUGGESTED_TAGS.filter((t) => !tags.includes(t)).map((t) => (
                <button key={t} type="button" onClick={() => addTag(t)} className="text-[10px] px-2 py-0.5 rounded-full border border-dashed border-hairline text-ink-3 hover:border-accent hover:text-accent" data-testid={`add-client-suggestion-${t}`}>
                  + {t}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label htmlFor="ac-notes" className="text-xs text-ink-2">Notes <span className="text-ink-4">· optional</span></label>
            <textarea id="ac-notes" data-testid="add-client-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="E.g. SIP of ₹25k/mo, wife is co-client, next review due Aug…" className={`${inputCls} min-h-[60px] text-xs`} />
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-6">
          <button onClick={close} disabled={create.isPending} className="px-3 py-1.5 rounded-md border border-hairline text-sm text-ink-2 hover:bg-surface-2 disabled:opacity-60">
            Cancel
          </button>
          <button onClick={submit} disabled={create.isPending || !name.trim()} data-testid="add-client-submit" className="px-3 py-1.5 rounded-md bg-accent text-accent-fg text-sm font-medium hover:opacity-90 disabled:opacity-60">
            {create.isPending ? "Adding…" : "Add client"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default AddClientModal;
