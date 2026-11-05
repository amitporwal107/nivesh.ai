/**
 * Paper Trading v2 — the ONE policy draft that 03 Capital allocation and 04 Portfolio risk both edit
 * (docs/scanner_paper_trading/UI_DESIGN_V2.md §3; §7 GET/PUT /api/v1/paper/accounts/{id}/policy).
 *
 *   One draft, one version   the draft lives in a module store (zustand), keyed by its target (your account, or an admin's
 *                            chosen user), so it survives switching between the two views; "Save policy" writes every changed
 *                            field of both panels as ONE new version with `expected_version`.
 *   Pill                     mint "Policy vN · saved" (no change) / amber "Policy vN+1 · draft" (a change).
 *   Buttons                  Defaults: this panel's fields back to the profile-derived defaults (null overrides) · Discard: the
 *                            whole draft back to the saved version · Save policy. Discard and Save are dimmed with no change.
 *   Rules (§3)               bucket targets are capped so the three never exceed 100 (reserve = 100 − the three, read-only, amber
 *                            under 5 %); the halt must sit above the restricted threshold (else the warning and Save refused);
 *                            every value within its range.
 *   Refusals                 403 admin_required names the loosened fields; 409 version_conflict offers Reload; 422 names the field.
 *   Admins                   a user-id picker; their writes go to /api/admin/spt/{user_id}/policy with a required reason.
 *
 * Live preview: the views read `eff(key)` (the draft's value, else the default) for their limit and bucket bars, so the bars move
 * before anything is saved. Nothing here reaches a broker.
 */
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { create } from "zustand";
import { useMe } from "@/hooks/use-auth";
import { LoadingBlock } from "../../../../../components/ui";
import { QueryProblem } from "../../../../trading/parts";
import { MONO } from "../pnl-ui";
import {
  ALLOCATION_KEYS, BUCKET_KEYS, RISK_KEYS, labelOf, policyProblem, targetKey, usePolicy, usePutPolicy,
  type PaperPolicy, type PolicyBody, type PolicyKey, type PolicyProblem, type PolicyTarget,
} from "./api-b";
import { Card, Note, Pill, mono10, toneColor } from "./ui";

// ── the store ────────────────────────────────────────────────────────────

interface DraftEntry {
  /** The saved version the draft started from. */
  version: number | null;
  /** The saved overrides: a field's value when overridden, else null (= its default). */
  base: Record<string, number | null>;
  /** The draft: null = the default. */
  values: Record<string, number | null>;
  /** A number box's raw text that is not a number (the field is then invalid). */
  bad: Record<string, string>;
}

interface PolicyStore {
  /** An admin's chosen user id; null = the caller's own policy. */
  adminUser: string | null;
  drafts: Record<string, DraftEntry>;
  setAdminUser: (u: string | null) => void;
  /** First read: start the draft. A later read: follow the server only while the draft is clean. */
  sync: (key: string, p: PaperPolicy) => void;
  /** After a save or a Reload: the draft becomes the saved policy. */
  reset: (key: string, p: PaperPolicy) => void;
  setValue: (key: string, field: string, v: number | null) => void;
  setBad: (key: string, field: string, text: string | null) => void;
  discard: (key: string) => void;
  defaults: (key: string, fields: readonly string[]) => void;
}

const baseOf = (p: PaperPolicy): Record<string, number | null> =>
  Object.fromEntries(Object.values(p.fields).map((f) => [f.key, f.overridden ? f.value : null]));
const entryOf = (p: PaperPolicy): DraftEntry => {
  const base = baseOf(p);
  return { version: p.version, base, values: { ...base }, bad: {} };
};
const isClean = (e: DraftEntry) => !Object.keys(e.bad).length && Object.keys({ ...e.base, ...e.values }).every((k) => (e.values[k] ?? null) === (e.base[k] ?? null));

export const usePolicyStore = create<PolicyStore>((set) => ({
  adminUser: null,
  drafts: {},
  setAdminUser: (u) => set({ adminUser: u }),
  sync: (key, p) => set((s) => {
    const cur = s.drafts[key];
    if (cur && (!isClean(cur) || cur.version === p.version)) return s;
    return { drafts: { ...s.drafts, [key]: entryOf(p) } };
  }),
  reset: (key, p) => set((s) => ({ drafts: { ...s.drafts, [key]: entryOf(p) } })),
  setValue: (key, field, v) => set((s) => {
    const cur = s.drafts[key];
    if (!cur) return s;
    const bad = { ...cur.bad };
    delete bad[field];
    return { drafts: { ...s.drafts, [key]: { ...cur, values: { ...cur.values, [field]: v }, bad } } };
  }),
  setBad: (key, field, text) => set((s) => {
    const cur = s.drafts[key];
    if (!cur) return s;
    const bad = { ...cur.bad };
    if (text == null) delete bad[field];
    else bad[field] = text;
    return { drafts: { ...s.drafts, [key]: { ...cur, bad } } };
  }),
  discard: (key) => set((s) => {
    const cur = s.drafts[key];
    if (!cur) return s;
    return { drafts: { ...s.drafts, [key]: { ...cur, values: { ...cur.base }, bad: {} } } };
  }),
  defaults: (key, fields) => set((s) => {
    const cur = s.drafts[key];
    if (!cur) return s;
    const values = { ...cur.values };
    const bad = { ...cur.bad };
    for (const f of fields) { values[f] = null; delete bad[f]; }
    return { drafts: { ...s.drafts, [key]: { ...cur, values, bad } } };
  }),
}));

// ── the hook both views use ──────────────────────────────────────────────

const fmtVal = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : String(Math.round(v * 10000) / 10000));
export const withUnit = (v: number | null | undefined, unit: string) => (v == null || !Number.isFinite(v) ? "—" : unit === "₹" ? `₹${fmtVal(v)}` : `${fmtVal(v)}${unit}`);

export interface PolicyDraft {
  isAdmin: boolean;
  target: PolicyTarget | null;
  key: string;
  q: ReturnType<typeof usePolicy>;
  policy: PaperPolicy | null;
  ready: boolean;
  /** The draft's value of a field, else its default (else the saved value): what the bars preview. */
  eff: (k: PolicyKey) => number | null;
  /** The saved policy's value of a field. */
  saved: (k: PolicyKey) => number | null;
  changed: string[];
  /** A change, or a number box holding text that is not a number. */
  dirty: boolean;
  /** Field → why it cannot be saved (not a number, out of its range). */
  invalid: Record<string, string>;
  bucketSum: number | null;
  reservePct: number | null;
  /** Halt ≤ restricted: the warning shows and Save is refused. */
  haltProblem: boolean;
  /** The most a bucket may take so the three never exceed 100. */
  bucketCap: (k: PolicyKey) => number | null;
  setValue: (k: PolicyKey, v: number | null) => void;
  setBad: (k: PolicyKey, text: string | null) => void;
  discard: () => void;
  defaults: (fields: readonly string[]) => void;
  reset: (p: PaperPolicy) => void;
  setAdminUser: (u: string | null) => void;
  adminUser: string | null;
}

const isBucket = (k: string) => (BUCKET_KEYS as readonly string[]).includes(k);

export function usePolicyDraft(accountId: string | null): PolicyDraft {
  const me = useMe();
  const isAdmin = (me.data as { is_admin?: boolean } | undefined)?.is_admin === true;
  const st = usePolicyStore();
  const adminUser = isAdmin ? st.adminUser : null;
  const target: PolicyTarget | null = adminUser ? { kind: "admin", userId: adminUser } : accountId ? { kind: "self", accountId } : null;
  const key = targetKey(target);
  const q = usePolicy(target);
  const policy = q.data ?? null;
  const { sync } = st;
  useEffect(() => { if (policy && key) sync(key, policy); }, [key, policy, sync]);
  const entry = key ? st.drafts[key] : undefined;
  const ready = !!policy && !!entry;

  return useMemo(() => {
    const field = (k: string) => policy?.fields[k] ?? null;
    const eff = (k: PolicyKey): number | null => {
      const f = field(k);
      if (!f) return null;
      const v = entry ? entry.values[k] : undefined;
      return v ?? f.default ?? f.value;
    };
    const saved = (k: PolicyKey): number | null => field(k)?.value ?? null;
    const keys = policy ? Object.keys(policy.fields) : [];
    const changed = entry ? keys.filter((k) => (entry.values[k] ?? null) !== (entry.base[k] ?? null)) : [];
    const invalid: Record<string, string> = {};
    for (const k of keys) {
      const f = field(k) as NonNullable<ReturnType<typeof field>>;
      if (entry?.bad[k] != null) { invalid[k] = `${labelOf(k)}: enter a number.`; continue; }
      const v = eff(k as PolicyKey);
      if (v == null) continue;
      if ((f.min != null && v < f.min) || (f.max != null && v > f.max)) {
        invalid[k] = `${labelOf(k)} must be between ${withUnit(f.min, f.unit)} and ${withUnit(f.max, f.unit)}.`;
      }
    }
    const bucketVals = BUCKET_KEYS.map((k) => eff(k));
    const bucketSum = bucketVals.every((v) => v != null) ? (bucketVals as number[]).reduce((a, b) => a + b, 0) : null;
    if (bucketSum != null && bucketSum > 100 + 1e-9) invalid._buckets = `The bucket targets total ${fmtVal(bucketSum)}%: they cannot exceed 100%.`;
    const reservePct = bucketSum == null ? null : Math.round((100 - bucketSum) * 10000) / 10000;
    const halt = eff("halt_at_pct");
    const restrict = eff("restrict_at_pct");
    const haltProblem = halt != null && restrict != null && halt <= restrict;
    const bucketCap = (k: PolicyKey): number | null => {
      if (!isBucket(k)) return field(k)?.max ?? null;
      const others = BUCKET_KEYS.filter((b) => b !== k).map((b) => eff(b));
      if (others.some((v) => v == null)) return field(k)?.max ?? null;
      const room = 100 - (others as number[]).reduce((a, b) => a + b, 0);
      const max = field(k)?.max;
      return Math.max(0, max != null ? Math.min(max, room) : room);
    };
    const dirty = changed.length > 0 || Object.keys(entry?.bad ?? {}).length > 0;
    return {
      isAdmin, target, key, q, policy, ready, eff, saved, changed, dirty, invalid, bucketSum, reservePct, haltProblem, bucketCap,
      setValue: (k, v) => {
        if (!key) return;
        // A bucket is capped so the three never exceed 100 (§2.03).
        const cap = isBucket(k) ? bucketCap(k) : null;
        st.setValue(key, k, v != null && cap != null && v > cap ? cap : v);
      },
      setBad: (k, text) => { if (key) st.setBad(key, k, text); },
      discard: () => { if (key) st.discard(key); },
      defaults: (fields) => { if (key) st.defaults(key, fields); },
      reset: (p) => { if (key) st.reset(key, p); },
      setAdminUser: st.setAdminUser,
      adminUser,
    };
    // st's actions are stable; `entry` carries the draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin, key, q, policy, entry, ready, adminUser]);
}

// ── one field: label, number box with its unit, the slider under it ──────

const box: CSSProperties = {
  width: 92, padding: "6px 8px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)",
  fontFamily: MONO, fontSize: 13, textAlign: "right", fontVariantNumeric: "tabular-nums",
};

function FieldRow({ k, d }: { k: PolicyKey; d: PolicyDraft }) {
  const f = d.policy?.fields[k] ?? null;
  const v = d.eff(k);
  const [text, setText] = useState<string | null>(null);
  const [capped, setCapped] = useState<number | null>(null);
  if (!f) {
    return (
      <div data-testid={`pv2-policy-field-${k}`} data-missing="true" className="flex min-w-0 flex-col" style={{ gap: 4 }}>
        <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>{labelOf(k)}</span>
        <Note>Not in the policy the route sent, so it cannot be set here.</Note>
      </div>
    );
  }
  const cap = d.bucketCap(k);
  const min = f.min ?? 0;
  const max = cap ?? f.max ?? (f.unit === "%" ? 100 : Math.max(min, v ?? min) * 2 || 10);
  const step = f.step ?? (f.unit === "%" ? 0.1 : 1);
  const unitText = f.unit === "%" ? "%" : f.unit === "₹" ? "₹" : "";
  const commit = (raw: string) => {
    setText(raw);
    const n = Number(raw);
    if (!raw.trim() || !Number.isFinite(n)) { d.setBad(k, raw); setCapped(null); return; }
    const over = cap != null && isBucket(k) && n > cap;
    setCapped(over ? cap : null);
    if (over) setText(fmtVal(cap));
    d.setValue(k, n);
  };
  const err = d.invalid[k];
  const changed = d.changed.includes(k);
  return (
    <div data-testid={`pv2-policy-field-${k}`} data-changed={changed ? "true" : "false"} data-value={v == null ? "" : String(v)} className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <div className="flex min-w-0 items-center justify-between" style={{ gap: 10 }}>
        <label htmlFor={`pv2-policy-input-${k}`} style={{ fontSize: 13, color: changed ? "var(--amber)" : "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{labelOf(k)}</label>
        <span className="flex flex-none items-center" style={{ gap: 6 }}>
          <input id={`pv2-policy-input-${k}`} data-testid={`pv2-policy-input-${k}`} type="text" inputMode="decimal" aria-invalid={err ? "true" : "false"}
            value={text ?? (v == null ? "" : fmtVal(v))} onChange={(e) => commit(e.target.value)} onBlur={() => { if (!d.invalid[k]) setText(null); }}
            style={{ ...box, borderColor: err ? "var(--danger-line)" : "var(--line-2)" }} />
          {unitText && <span style={{ ...mono10, color: "var(--cp-ink-3)", width: 12 }}>{unitText}</span>}
        </span>
      </div>
      <input type="range" data-testid={`pv2-policy-slider-${k}`} aria-label={labelOf(k)} min={min} max={Math.max(min, max)} step={step} disabled={v == null}
        value={v ?? min} onChange={(e) => { setText(null); setCapped(null); d.setValue(k, Number(e.target.value)); }}
        style={{ width: "100%", accentColor: changed ? "var(--amber)" : "var(--mint)" }} />
      <span className="flex min-w-0 flex-wrap justify-between" style={{ gap: 8, fontSize: 11, color: "var(--cp-ink-3)" }}>
        <span>default {withUnit(f.default, f.unit)}{f.overridden && !changed ? " · set by you" : ""}</span>
        <span>{withUnit(f.min, f.unit)} – {withUnit(f.max, f.unit)}</span>
      </span>
      {capped != null && <span data-testid="pv2-policy-capped" style={{ fontSize: 11.5, color: "var(--amber)" }}>Capped at {fmtVal(capped)}% so the three buckets never exceed 100%.</span>}
      {err && <span data-testid={`pv2-policy-invalid-${k}`} role="alert" style={{ fontSize: 11.5, color: "var(--cp-danger)" }}>{err}</span>}
    </div>
  );
}

// ── the card ─────────────────────────────────────────────────────────────

const btn = (on: boolean, primary = false): CSSProperties => ({
  cursor: on ? "pointer" : "not-allowed", opacity: on ? 1 : 0.35, padding: "6px 12px", borderRadius: 999, ...mono10,
  border: `1px solid ${primary ? "var(--mint-line)" : "var(--line-3)"}`, background: primary ? "var(--mint-soft)" : "transparent",
  color: primary ? "var(--mint)" : "var(--cp-ink)",
});

function ProblemBox({ p, onReload }: { p: PolicyProblem; onReload: () => void }) {
  let body: ReactNode;
  if (p.code === "admin_required" || (p.status === 403 && p.loosened.length)) {
    body = <>Loosening needs an admin{p.loosened.length ? `: ${p.loosened.map(labelOf).join(", ")}` : ""}. Nothing was saved. You may tighten any limit yourself.</>;
  } else if (p.code === "version_conflict" || p.status === 409) {
    body = (
      <>
        This policy was saved elsewhere after you opened it, so your draft was not saved.{" "}
        <button type="button" data-testid="pv2-policy-reload" onClick={onReload}
          style={{ padding: 0, border: 0, background: "none", color: "var(--mint)", textDecoration: "underline", cursor: "pointer", font: "inherit" }}>
          Reload
        </button>{" "}
        to see the saved version (your draft is discarded).
      </>
    );
  } else if (p.status === 422 || p.field) {
    body = <>{p.field ? `${labelOf(p.field)}: ` : ""}{p.message}</>;
  } else {
    body = <>The policy was not saved: {p.message}</>;
  }
  return (
    <div data-testid="pv2-policy-problem" data-code={p.code ?? String(p.status ?? "")} data-field={p.field ?? ""} role="alert"
      style={{ padding: "8px 12px", borderRadius: 10, border: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink)" }}>
      {body}
    </div>
  );
}

function AdminPicker({ d }: { d: PolicyDraft }) {
  const [uid, setUid] = useState(d.adminUser ?? "");
  return (
    <form data-testid="pv2-policy-admin" className="flex min-w-0 flex-wrap items-center" style={{ gap: 8, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--indigo-line)" }}
      onSubmit={(e) => { e.preventDefault(); const t = uid.trim(); if (t) d.setAdminUser(t); }}>
      <span style={{ ...mono10, color: toneColor("indigo") }}>Admin · user</span>
      <input data-testid="pv2-policy-admin-uid" aria-label="User id" placeholder="User id" value={uid} onChange={(e) => setUid(e.target.value)}
        style={{ ...box, width: 200, textAlign: "left", fontFamily: "inherit" }} />
      <button type="submit" data-testid="pv2-policy-admin-load" style={btn(!!uid.trim())} disabled={!uid.trim()}>Load</button>
      {d.adminUser && (
        <button type="button" data-testid="pv2-policy-admin-self" onClick={() => { setUid(""); d.setAdminUser(null); }} style={btn(true)}>My policy</button>
      )}
      <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)", flex: "1 1 220px" }}>
        {d.adminUser ? `Editing ${d.adminUser}'s policy. A reason is required to save. The bars on this page are your own account's figures, not theirs.` : "Load a user id to edit that user's policy (either direction, with a reason)."}
      </span>
    </form>
  );
}

export type PolicyPanel = "allocation" | "risk";

export function PolicyCard({ panel, d, sub, narrow }: { panel: PolicyPanel; d: PolicyDraft; sub: ReactNode; narrow: boolean }) {
  const put = usePutPolicy();
  const [problem, setProblem] = useState<PolicyProblem | null>(null);
  const [savedV, setSavedV] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const keys = (panel === "allocation" ? ALLOCATION_KEYS : RISK_KEYS) as readonly PolicyKey[];
  const v = d.policy?.version ?? null;
  const dirty = d.dirty;
  const invalidList = Object.values(d.invalid);
  // This panel's fields say their own problem under the field; the rest (the other panel's, the bucket total) are said here.
  const otherInvalid = Object.entries(d.invalid).filter(([k]) => !(keys as readonly string[]).includes(k)).map(([, m]) => m);
  const adminTarget = d.target?.kind === "admin";
  const needsReason = adminTarget && !reason.trim();
  const canSave = d.ready && d.changed.length > 0 && !invalidList.length && !d.haltProblem && !needsReason && !put.isPending;
  const title = panel === "allocation" ? "Configure · allocation policy" : "Configure · risk limits";

  const save = () => {
    if (!canSave || !d.target || !d.policy) return;
    setProblem(null);
    setSavedV(null);
    const values: Record<string, number | null> = {};
    const store = usePolicyStore.getState().drafts[d.key];
    for (const k of d.changed) values[k] = store?.values[k] ?? null;
    const body: PolicyBody = { expected_version: d.policy.version, values };
    if (reason.trim()) body.reason = reason.trim();
    put.mutate({ target: d.target, body }, {
      onSuccess: (p) => { d.reset(p); setSavedV(p.version); setReason(""); },
      onError: (e) => setProblem(policyProblem(e)),
    });
  };
  const reload = () => {
    setProblem(null);
    void d.q.refetch().then((r) => { if (r.data) d.reset(r.data); });
  };

  const pill = !d.ready ? null : dirty
    ? <Pill tone="amber" testId="pv2-policy-version" attrs={{ "data-state": "draft" }}>Policy v{v == null ? "?" : v + 1} · draft</Pill>
    : <Pill tone="mint" testId="pv2-policy-version" attrs={{ "data-state": "saved" }}>Policy v{v ?? "?"} · saved</Pill>;
  const right = (
    <>
      {pill}
      <button type="button" data-testid="pv2-policy-defaults" title="This panel's fields back to the profile-derived defaults" disabled={!d.ready}
        onClick={() => { setProblem(null); setSavedV(null); d.defaults(keys); }} style={btn(d.ready)}>Defaults</button>
      <button type="button" data-testid="pv2-policy-discard" title="The whole draft back to the saved version" disabled={!dirty}
        onClick={() => { setProblem(null); d.discard(); }} style={btn(dirty)}>Discard</button>
      <button type="button" data-testid="pv2-policy-save" disabled={!canSave} onClick={save} style={btn(canSave, true)}>
        {put.isPending ? "Saving…" : "Save policy"}
      </button>
    </>
  );

  let body: ReactNode;
  if (!d.target) body = <Note testId="pv2-policy-none">No paper account was returned for you, so there is no policy to configure.</Note>;
  else if (d.q.isPending) body = <LoadingBlock label="Reading your policy" rows={2} />;
  else if (d.q.isError) {
    body = <div data-testid="pv2-policy-error"><QueryProblem what={adminTarget ? `${d.adminUser}'s policy` : "Your policy"} error={d.q.error} onRetry={() => { void d.q.refetch(); }} /></div>;
  } else if (!d.ready) body = <LoadingBlock label="Preparing the draft" rows={1} />;
  else {
    const other = d.changed.filter((k) => !(keys as readonly string[]).includes(k));
    body = (
      <>
        <div className="grid min-w-0" style={{ gap: "16px 22px", gridTemplateColumns: narrow ? "minmax(0,1fr)" : "repeat(auto-fit,minmax(min(100%,240px),1fr))" }}>
          {keys.map((k) => <FieldRow key={`${d.key}:${k}`} k={k} d={d} />)}
          {panel === "allocation" && (
            <div data-testid="pv2-policy-reserve" data-value={d.reservePct == null ? "" : String(d.reservePct)} data-low={d.reservePct != null && d.reservePct < 5 ? "true" : "false"}
              className="flex min-w-0 flex-col" style={{ gap: 6, padding: "10px 12px", borderRadius: 12, background: "var(--bg-2)" }}>
              <div className="flex items-center justify-between" style={{ gap: 10 }}>
                <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>Unallocated reserve</span>
                <span data-testid="pv2-policy-reserve-value" style={{ fontFamily: MONO, fontSize: 15, fontVariantNumeric: "tabular-nums",
                  color: d.reservePct != null && d.reservePct < 5 ? "var(--amber)" : "var(--cp-ink)" }}>{withUnit(d.reservePct, "%")}</span>
              </div>
              <Note>Derived: 100% minus the three buckets. Keep at least 5%.</Note>
            </div>
          )}
        </div>
        {panel === "risk" && d.haltProblem && (
          <div data-testid="pv2-policy-halt-warning" role="alert" style={{ padding: "8px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 12.5, color: "var(--amber)" }}>
            Halt threshold must sit above the restricted threshold.
          </div>
        )}
        {(d.changed.length > 0 || otherInvalid.length > 0) && (
          <Note testId="pv2-policy-changes">
            {d.changed.length > 0 && <>
              {d.changed.length} unsaved change{d.changed.length === 1 ? "" : "s"}: {d.changed.map((k) => `${labelOf(k)} ${withUnit(d.saved(k as PolicyKey), d.policy?.fields[k]?.unit ?? "")} → ${withUnit(d.eff(k as PolicyKey), d.policy?.fields[k]?.unit ?? "")}`).join(" · ")}.
              {other.length > 0 ? ` ${other.length} of them ${other.length === 1 ? "is" : "are"} on ${panel === "allocation" ? "Portfolio risk" : "Capital allocation"}; Save policy writes them all as one version.` : ""}
            </>}
            {otherInvalid.map((m) => ` ${m}`)}
          </Note>
        )}
        {adminTarget && (
          <label className="flex min-w-0 flex-wrap items-center" style={{ gap: 8, fontSize: 12.5, color: "var(--cp-ink-2)" }}>
            Reason (required)
            <input data-testid="pv2-policy-reason" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)}
              style={{ ...box, width: "min(100%, 360px)", textAlign: "left", fontFamily: "inherit" }} />
          </label>
        )}
        {problem && <ProblemBox p={problem} onReload={reload} />}
        {savedV != null && !problem && d.changed.length === 0 && (
          <span data-testid="pv2-policy-saved" role="status" style={{ fontSize: 12.5, color: "var(--mint)" }}>Saved as policy v{savedV}. The risk engine applies it to new orders.</span>
        )}
        {d.policy?.savedAt && <Note testId="pv2-policy-meta">Saved {new Date(d.policy.savedAt).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })} IST{d.policy.savedBy ? ` by ${d.policy.savedBy}` : ""}. You may tighten any limit; loosening one needs an admin.</Note>}
      </>
    );
  }

  return (
    <Card testId="pv2-policy-card" attrs={{ "data-panel": panel }} title={title} right={right}>
      <Note testId="pv2-policy-sub" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>{sub}</Note>
      {d.isAdmin && <AdminPicker d={d} />}
      {body}
    </Card>
  );
}
