/**
 * Shell dialogs: Stop / Resume new entries (POST /desk/controls/STOP_NEW_ENTRIES) and New paper account
 * (POST /accounts). Each shows the API's own error and changes nothing on screen until the API has answered.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { errorText } from "../api";
import { useCreateAccount, useSetStopEntries } from "../hooks";
import { Button } from "../ui";

export function Modal({ title, children, onClose, testId, tone = "ink" }: {
  title: ReactNode; children: ReactNode; onClose: () => void; testId?: string; tone?: "ink" | "danger" | "mint";
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const line = tone === "danger" ? "var(--danger-line)" : tone === "mint" ? "var(--mint-line)" : "var(--line-2)";
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 80, display: "grid", placeItems: "center", padding: 16 }}>
      <div onClick={onClose} style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,.5)" }} />
      <div role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined} data-testid={testId}
        style={{ position: "relative", width: "min(460px, 100%)", display: "flex", flexDirection: "column", gap: 14, padding: "22px 24px", borderRadius: 18, border: `1px solid ${line}`, background: "var(--bg-1)", boxShadow: "var(--shadow-pop)", color: "var(--ink)", fontFamily: "var(--sans)" }}>
        <span style={{ fontFamily: "var(--display)", fontSize: 26, lineHeight: 1.12, letterSpacing: "-0.01em" }}>{title}</span>
        {children}
      </div>
    </div>
  );
}

const field = { width: "100%", padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 14 } as const;

export function StopEntriesDialog({ halted, onClose }: { halted: boolean; onClose: () => void }) {
  const m = useSetStopEntries();
  const [reason, setReason] = useState(halted ? "Resumed from the desk header" : "Stopped from the desk header");
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { ref.current?.select(); }, []);
  const submit = () => {
    const r = reason.trim();
    if (!r) return;
    m.mutate({ active: !halted, reason: r.slice(0, 300) }, { onSuccess: onClose });
  };
  return (
    <Modal title={halted ? "Resume new entries?" : "Stop new entries?"} onClose={onClose} testId="stop-dialog" tone={halted ? "mint" : "danger"}>
      <span style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--ink-2)" }}>
        {halted
          ? "Agents may propose new trade plans again, and approvals become possible on the desk's accounts."
          : "No new trade plans are proposed and nothing is approved on the desk's accounts until you resume. Signals are still scanned, and simulations of past sessions are not affected. There are no orders in this phase, so nothing is cancelled."}
      </span>
      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span className="nv-eyebrow">Reason (kept in the audit log)</span>
        <textarea ref={ref} data-testid="stop-reason" value={reason} maxLength={300} rows={2} onChange={(e) => setReason(e.target.value)} style={{ ...field, resize: "vertical" }} />
      </label>
      {m.error && <span role="alert" data-testid="stop-error" style={{ fontSize: 13, color: "var(--danger)" }}>{errorText(m.error)}</span>}
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button kind={halted ? "mint" : "danger"} onClick={submit} disabled={m.isPending || !reason.trim()} testId="stop-confirm">
          {m.isPending ? "Saving…" : halted ? "Resume entries" : "Stop new entries"}
        </Button>
      </div>
    </Modal>
  );
}

export function NewAccountDialog({ onClose }: { onClose: () => void }) {
  const m = useCreateAccount();
  const [name, setName] = useState("Desk A");
  const [capital, setCapital] = useState("1000000");
  const cap = Number(capital);
  const valid = name.trim().length > 0 && name.trim().length <= 80 && Number.isFinite(cap) && cap > 0 && cap <= 1e9;
  return (
    <Modal title="New paper account" onClose={onClose} testId="account-dialog">
      <span style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--ink-2)" }}>
        A paper account for the desk's agents. It starts in Research mode (signals, plans and risk reports, nothing approved);
        change the mode under Policies &amp; permissions.
      </span>
      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span className="nv-eyebrow">Name</span>
        <input data-testid="account-name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} style={field} />
      </label>
      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span className="nv-eyebrow">Starting capital (₹)</span>
        <input data-testid="account-capital" inputMode="numeric" value={capital} onChange={(e) => setCapital(e.target.value.replace(/[^\d]/g, ""))} style={field} />
      </label>
      {m.error && <span role="alert" data-testid="account-error" style={{ fontSize: 13, color: "var(--danger)" }}>{errorText(m.error)}</span>}
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button kind="primary" disabled={!valid || m.isPending} testId="account-create"
          onClick={() => m.mutate({ name: name.trim(), starting_capital_rs: cap }, { onSuccess: onClose })}>
          {m.isPending ? "Creating…" : "Create"}
        </Button>
      </div>
    </Modal>
  );
}
