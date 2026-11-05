/**
 * Write dialogs of the Policies screen. Each changes nothing on screen until the API has answered, and shows the
 * API's own message when it refuses (409 / 422, or 403 when a non-admin makes a limit looser than the default).
 */
import { useMemo, useState } from "react";
import { errorText } from "../../api";
import { num } from "../../format";
import { Modal } from "../../shell/dialogs";
import type { Account, OperatingMode, PolicyDetail } from "../../types";
import { Button } from "../../ui";
import { MODE_NOTE, MODE_OPTIONS, useNewPolicyVersion, useSetMode } from "./data";
import { AUTONOMY_FIELDS, FIELDS, parseEdit, plain, type FieldDef, type PolicyBodyJson } from "./fields";

const field = { width: "100%", padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 14, fontFamily: "var(--sans)" } as const;

export const MODE_REASON = "Changed from Policies & permissions";
export const LIMITS_REASON = "Edited from Policies & permissions";

export function ModeDialog({ account, mode, onClose, onDone }: {
  account: Account; mode: OperatingMode; onClose: () => void; onDone: (a: Account) => void;
}) {
  const m = useSetMode();
  const [reason, setReason] = useState(MODE_REASON);
  const label = MODE_OPTIONS.find((o) => o.mode === mode)?.label ?? mode;
  const submit = () => {
    const r = reason.trim();
    if (!r) return;
    m.mutate({ accountId: account.account_id, mode, reason: r.slice(0, 300) }, { onSuccess: (a) => onDone(a) });
  };
  return (
    <Modal title={`Switch ${account.name} to ${label.toLowerCase()}?`} onClose={onClose} testId="mode-dialog">
      <span style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--ink-2)" }}>{MODE_NOTE[mode]}</span>
      <span style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--ink-3)" }}>
        The change is recorded in the audit log with your reason. Plans approved earlier keep the approval they were given.
      </span>
      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span className="nv-eyebrow">Reason (kept in the audit log)</span>
        <textarea data-testid="mode-reason" value={reason} maxLength={300} rows={2} onChange={(e) => setReason(e.target.value)} style={{ ...field, resize: "vertical" }} />
      </label>
      {m.error && <span role="alert" data-testid="mode-error" style={{ fontSize: 13, color: "var(--danger)" }}>{errorText(m.error)}</span>}
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button kind="primary" onClick={submit} disabled={m.isPending || !reason.trim()} testId="mode-confirm">
          {m.isPending ? "Saving…" : `Switch to ${label.toLowerCase()}`}
        </Button>
      </div>
    </Modal>
  );
}

function Row({ f, value, onChange, error }: { f: FieldDef; value: string; onChange: (v: string) => void; error?: string }) {
  return (
    <label style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 120px", gap: 10, alignItems: "center", padding: "7px 0", borderTop: "1px solid var(--line)" }}>
      <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
        <span style={{ fontSize: 13 }}>{f.label}{f.kind === "pct" ? " (%)" : f.kind === "rs" ? " (₹)" : ""}</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.06em", color: error ? "var(--danger)" : "var(--ink-4)" }}>
          {error ?? (f.stricter === "lower" ? "LOWER IS STRICTER" : "HIGHER IS STRICTER")}
        </span>
      </span>
      <input data-testid={`limit-input-${f.key}`} inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)}
        style={{ ...field, padding: "8px 10px", fontFamily: "var(--mono)", fontSize: 13, textAlign: "right" }} />
    </label>
  );
}

export function EditLimitsDialog({ policy, accountsUsing, onClose, onDone }: {
  policy: PolicyDetail; accountsUsing: number; onClose: () => void; onDone: (version: number) => void;
}) {
  const body = policy.body as PolicyBodyJson;
  const auto = body.autonomy ?? {};
  const editable = FIELDS.filter((f) => f.editable);
  const init = useMemo(() => Object.fromEntries(editable.map((f) => [f.key, plain(body[f.key])])), [policy.policy_id, policy.version]); // eslint-disable-line react-hooks/exhaustive-deps
  const initAuto = useMemo(() => Object.fromEntries(AUTONOMY_FIELDS.map((f) => [f.key, plain((auto as Record<string, unknown>)[f.key])])), [policy.policy_id, policy.version]); // eslint-disable-line react-hooks/exhaustive-deps
  const [vals, setVals] = useState<Record<string, string>>(init);
  const [autoVals, setAutoVals] = useState<Record<string, string>>(initAuto);
  const [autoApprove, setAutoApprove] = useState<boolean>(auto.auto_approve !== false);
  const [reason, setReason] = useState(LIMITS_REASON);
  const m = useNewPolicyVersion();

  const errors: Record<string, string> = {};
  const changes: Record<string, unknown> = {};
  for (const f of editable) {
    if (vals[f.key] === init[f.key]) continue;
    const p = parseEdit(f, vals[f.key]);
    if (!p.ok) { errors[f.key] = p.error; continue; }
    if (num(p.value) !== num(body[f.key])) changes[f.key] = p.value;
  }
  const autoChanges: Record<string, unknown> = {};
  for (const f of AUTONOMY_FIELDS) {
    if (autoVals[f.key] === initAuto[f.key]) continue;
    const p = parseEdit(f, autoVals[f.key]);
    if (!p.ok) { errors[`autonomy.${f.key}`] = p.error; continue; }
    if (num(p.value) !== num((auto as Record<string, unknown>)[f.key])) autoChanges[f.key] = p.value;
  }
  if (autoApprove !== (auto.auto_approve !== false)) autoChanges.auto_approve = autoApprove;
  // The API merges top-level keys only (`{**current, **changes}`), so autonomy goes as one whole object.
  if (Object.keys(autoChanges).length) changes.autonomy = { ...auto, ...autoChanges };
  const nChanged = Object.keys(changes).length;
  const invalid = Object.keys(errors).length > 0;

  const submit = () => {
    const r = reason.trim();
    if (!r || !nChanged || invalid) return;
    m.mutate({ policyId: policy.policy_id, changes, reason: r.slice(0, 300) }, { onSuccess: (res) => onDone(res.version) });
  };

  return (
    <Modal title={`Edit limits · ${policy.name}`} onClose={onClose} testId="limits-dialog">
      <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--ink-2)" }}>
        Saving creates version {policy.current_version + 1} of this policy for {accountsUsing === 1 ? "the 1 account" : `the ${accountsUsing} accounts`} that
        use{accountsUsing === 1 ? "s" : ""} it. You may tighten any limit; a limit looser than the default needs an admin.
      </span>
      <div style={{ maxHeight: "46vh", overflowY: "auto", paddingRight: 4 }}>
        {editable.map((f) => (
          <Row key={f.key} f={f} value={vals[f.key]} error={errors[f.key]} onChange={(v) => setVals((x) => ({ ...x, [f.key]: v }))} />
        ))}
        <div style={{ padding: "12px 0 4px" }}><span className="nv-eyebrow">Autonomy rules</span></div>
        <label style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 0", borderTop: "1px solid var(--line)", fontSize: 13 }}>
          <input type="checkbox" data-testid="autonomy-auto-approve" checked={autoApprove} onChange={(e) => setAutoApprove(e.target.checked)} />
          <span>Middle Office may approve plans inside the rules (Autonomous paper)</span>
        </label>
        {AUTONOMY_FIELDS.map((f) => (
          <Row key={f.key} f={{ ...f, key: `autonomy-${f.key}` }} value={autoVals[f.key]} error={errors[`autonomy.${f.key}`]}
            onChange={(v) => setAutoVals((x) => ({ ...x, [f.key]: v }))} />
        ))}
      </div>
      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span className="nv-eyebrow">Reason (kept with the version)</span>
        <textarea data-testid="limits-reason" value={reason} maxLength={300} rows={2} onChange={(e) => setReason(e.target.value)} style={{ ...field, resize: "vertical" }} />
      </label>
      {m.error && <span role="alert" data-testid="limits-error" style={{ fontSize: 13, color: "var(--danger)", overflowWrap: "anywhere" }}>{errorText(m.error)}</span>}
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "center", flexWrap: "wrap" }}>
        <span data-testid="limits-count" style={{ flex: 1, fontSize: 12, color: "var(--ink-3)" }}>{nChanged ? `${nChanged} change${nChanged === 1 ? "" : "s"}` : "No change yet"}</span>
        <Button onClick={onClose}>Cancel</Button>
        <Button kind="primary" onClick={submit} disabled={m.isPending || !nChanged || invalid || !reason.trim()} testId="limits-save">
          {m.isPending ? "Saving…" : "Save new version"}
        </Button>
      </div>
    </Modal>
  );
}
