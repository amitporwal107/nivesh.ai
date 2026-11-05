/**
 * Trade Desk › Paper Trading › Settings (?tab=trade&view=paper&sub=settings) — Scanner-to-Paper Trading (owner, 5 Nov 2026;
 * PRD §16.1, §26; DESIGN.md D4). Test cases SPT-UI-P-16 … P-25 in test_reports/spt_ui_paper_TESTCASES.md.
 *
 * The owner's decisions of 5 Nov ~06:50 IST: the SPT limits default from the user's risk profile (or the owner-approved SPT
 * default); each user may TIGHTEN any value, only an ADMIN may loosen one; an admin may edit any user's config and the
 * market-wide settings. The backend decides (services/spt/policy.py): this screen shows the effective value, the default and
 * its source, whether it is overridden, and sends ONLY the changed leaves (a reset sends that leaf as null).
 *
 *   GET /api/v1/paper/accounts · GET /api/v1/paper/accounts/{id}        the config and its version history
 *   PUT /api/v1/paper/accounts/{id}/config                             {mode?, extras?, reason?, expected_version}
 *   GET/PUT /api/admin/spt/{user_id}/config · GET/PUT /api/admin/spt/settings   admins only (useMe().is_admin, as the
 *                                                                      rest of the app's admin UI; the routes check again)
 */
import { useState, type ReactNode } from "react";
import { LoadingBlock } from "../../../../components/ui";
import { QueryProblem } from "../../../trading/parts";
import { useMe } from "@/hooks/use-auth";
import { linkBtn, quiet } from "./parts";
import { MONO, Pill, card, eyebrow, serifTitle } from "./pnl-ui";
import {
  LEAVES, MODES, MODE_WORDS, nest, sptProblem, useAdminConfig, useAdminSettings, usePutAdminConfig, usePutAdminSettings, usePutConfig, useSptAccount,
  useSptAccountDetail, type ConfigBody, type ConfigVersion, type LeafDef, type SptConfig, type SptMode, type Unit,
} from "./spt-api";
import { ProblemLine, Section, btn, btnPrimary, input, istTime, mono, rupees, useNarrow } from "./spt-parts";

/** The unit beside an input, and after a shown value. */
const UNIT: Record<Unit, string> = { pct: "%", factor: "×", count: "", rs: "₹", min: "min", ratio: "R" };
const LABEL_OF = new Map(LEAVES.map((l) => [l.path, l.label]));
const labelOf = (path: string) => LABEL_OF.get(path) ?? path;

const showNum = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : String(Math.round(v * 10000) / 10000));
const showVal = (l: LeafDef, v: number | null | undefined) => {
  if (v == null || !Number.isFinite(v)) return "—";
  if (l.unit === "rs") return `${rupees(v)} (${showNum(v)})`;
  if (l.unit === "pct") return `${showNum(v)}%`;
  return UNIT[l.unit] ? `${showNum(v)} ${UNIT[l.unit]}` : showNum(v);
};
const sourceKind = (s: string | null) => (!s ? null : /^risk profile/i.test(s) ? "Risk profile" : "SPT default");

export default function SptSettings() {
  const me = useMe();
  const isAdmin = me.data?.is_admin === true;
  const acct = useSptAccount();
  const accountId = acct.data?.accountId ?? null;
  const detail = useSptAccountDetail(accountId);
  const cfg = detail.data?.config ?? acct.data?.config ?? null;
  const putMode = usePutConfig();
  const putLimits = usePutConfig();
  const [narrow, ref] = useNarrow(640);
  const reload = () => { acct.refetch(); detail.refetch(); putLimits.reset(); putMode.reset(); };

  return (
    <div ref={ref} data-testid="spt-settings" data-narrow={narrow ? "true" : "false"} className="flex min-w-0 flex-col" style={{ gap: 20 }}>
      <header className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span style={eyebrow}>Paper Trading · Scanner-to-paper</span>
        <h2 className="m-0" style={serifTitle}>Settings</h2>
        <span style={quiet}>Your paper account's mode and limits. The limits start from your risk profile; you can tighten any of them here. Loosening one needs an admin.</span>
      </header>
      {acct.isError ? <QueryProblem what="Your paper account" error={acct.error} onRetry={() => acct.refetch()} />
        : !cfg ? <LoadingBlock label="Reading your settings" rows={4} />
        : (
          <>
            <ModePicker cfg={cfg} pending={putMode.isPending} error={putMode.error} onReload={reload}
              onPick={(mode) => accountId && putMode.mutate({ accountId, body: { mode, ...(cfg.version != null ? { expected_version: cfg.version } : {}) } })} />
            <LimitsForm key={`${cfg.version ?? "x"}`} cfg={cfg} testId="spt-limits" requireReason={false} narrow={narrow}
              saving={putLimits.isPending} error={putLimits.error} saved={putLimits.isSuccess} onReload={reload}
              onSave={(body) => accountId && putLimits.mutate({ accountId, body })} />
            <VersionList versions={detail.data?.versions ?? null} testId="spt-versions" pending={detail.isPending} />
          </>
        )}
      {isAdmin && <AdminPanel narrow={narrow} />}
    </div>
  );
}

// ── mode ─────────────────────────────────────────────────────────────────

function ModePicker({ cfg, pending, error, onPick, onReload }: { cfg: SptConfig; pending: boolean; error: unknown; onPick: (m: SptMode) => void; onReload: () => void }) {
  const [confirmAuto, setConfirmAuto] = useState(false);
  const pick = (m: SptMode) => {
    if (m === cfg.mode || pending) return;
    if (m === "auto") { setConfirmAuto(true); return; }
    setConfirmAuto(false);
    onPick(m);
  };
  return (
    <section data-testid="spt-mode" data-mode={cfg.mode ?? ""} className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", gap: 10, padding: "16px 16px 14px" }}>
      <h3 className="cp-eyebrow m-0" style={{ color: "var(--cp-ink-2)" }}>Mode</h3>
      <div role="group" aria-label="Mode" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,200px),1fr))", gap: 8 }}>
        {MODES.map((m) => {
          const on = m === cfg.mode;
          return (
            <button key={m} type="button" data-testid={`spt-mode-${m}`} aria-pressed={on} disabled={pending} onClick={() => pick(m)} className="flex flex-col text-left"
              style={{ gap: 4, padding: "10px 12px", borderRadius: 12, font: "inherit", cursor: on ? "default" : "pointer", color: "var(--cp-ink)",
                border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`, background: on ? "var(--mint-soft)" : "transparent" }}>
              <span style={{ fontFamily: MONO, fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase", color: on ? "var(--mint)" : "var(--cp-ink)" }}>{MODE_WORDS[m].label}{on ? " · current" : ""}</span>
              <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{MODE_WORDS[m].line}</span>
            </button>
          );
        })}
      </div>
      {confirmAuto && (
        <div data-testid="spt-mode-confirm" role="alertdialog" aria-label="Switch to Auto" className="flex flex-wrap items-center" style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
          <span style={{ fontSize: 12.5, color: "var(--cp-ink)", flex: "1 1 240px" }}>Switch to Auto? Every proposal the risk engine approves becomes a paper order at once, without asking you.</span>
          <button type="button" data-testid="spt-mode-confirm-yes" style={btnPrimary} onClick={() => { setConfirmAuto(false); onPick("auto"); }}>Switch to Auto</button>
          <button type="button" data-testid="spt-mode-confirm-no" style={btn} onClick={() => setConfirmAuto(false)}>Cancel</button>
        </div>
      )}
      {pending && <span style={quiet}>Saving…</span>}
      {error ? <ConfigProblem e={error} onReload={onReload} testId="spt-mode-error" /> : null}
    </section>
  );
}

// ── the refusal, in the owner's terms ────────────────────────────────────

function ConfigProblem({ e, onReload, testId }: { e: unknown; onReload: () => void; testId: string }) {
  const p = sptProblem(e);
  if (p.code === "admin_required" || (p.status === 403 && p.loosened.length)) {
    const fields = p.loosened.length ? p.loosened : p.field ? [p.field] : [];
    return (
      <div data-testid={testId} data-code="admin_required" role="alert" className="flex flex-col" style={{ gap: 4, padding: "8px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 12.5 }}>
        <span data-testid={`${testId}-admin`} style={{ color: "var(--amber)", fontWeight: 600 }}>Loosening needs an admin{fields.length ? `: ${fields.map(labelOf).join(", ")}` : ""}.</span>
        {fields.length > 0 && <span data-testid={`${testId}-fields`} style={{ ...mono, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{fields.join(" · ")}</span>}
        <span style={{ color: "var(--cp-ink-2)" }}>{p.message}</span>
      </div>
    );
  }
  if (p.code === "concurrent_change" || p.status === 409) {
    return (
      <div data-testid={testId} data-code="concurrent_change" role="alert" className="flex flex-wrap items-center" style={{ gap: 8, padding: "8px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 12.5 }}>
        <span style={{ color: "var(--cp-ink)" }}>These settings changed elsewhere since you opened them. Reload to see the current values, then make your change again.</span>
        <button type="button" data-testid={`${testId}-reload`} style={btn} onClick={onReload}>Reload</button>
      </div>
    );
  }
  return <ProblemLine p={p} testId={testId} lead={p.field ? `${labelOf(p.field)}:` : "Not saved:"} />;
}

// ── the limits form (the user's own, and an admin's view of any user) ────

function LimitsForm({ cfg, testId, requireReason, narrow, saving, error, saved, onSave, onReload, modeEditable }: {
  cfg: SptConfig; testId: string; requireReason: boolean; narrow: boolean; saving: boolean; error: unknown; saved: boolean;
  onSave: (body: ConfigBody) => void; onReload: () => void; modeEditable?: boolean;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [resets, setResets] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");
  const [mode, setMode] = useState<SptMode | "">(cfg.mode ?? "");
  const [needReason, setNeedReason] = useState(false);
  const v2 = cfg.shape === "v2";
  const errField = sptProblem(error).field;

  const changes: Record<string, number | null> = {};
  const bad: string[] = [];
  for (const l of LEAVES) {
    if (resets.has(l.path)) { changes[l.path] = null; continue; }
    const t = draft[l.path];
    if (t == null) continue;
    const n = t.trim() === "" ? NaN : Number(t);
    if (!Number.isFinite(n)) { bad.push(l.path); continue; }
    if (n !== cfg.extras[l.path]) changes[l.path] = n;
  }
  const modeChanged = !!modeEditable && mode !== "" && mode !== cfg.mode;
  const nChanged = Object.keys(changes).length + (modeChanged ? 1 : 0);

  const save = () => {
    if (!nChanged || bad.length) return;
    if (requireReason && !reason.trim()) { setNeedReason(true); return; }
    const body: ConfigBody = {};
    if (Object.keys(changes).length) body.extras = nest(changes);
    if (modeChanged) body.mode = mode as SptMode;
    if (reason.trim()) body.reason = reason.trim();
    if (cfg.version != null) body.expected_version = cfg.version;
    onSave(body);
  };

  const groups = [...new Set(LEAVES.map((l) => l.group))];
  return (
    <section data-testid={testId} data-shape={cfg.shape} className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", gap: 14, padding: "16px 16px 14px" }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 12px" }}>
        <h3 className="cp-eyebrow m-0" style={{ color: "var(--cp-ink-2)" }}>Limits</h3>
        <span style={{ ...quiet, fontSize: 11 }}>version {cfg.version ?? "—"}{cfg.updatedAt ? ` · changed ${istTime(cfg.updatedAt)}${cfg.updatedBy ? ` by ${cfg.updatedBy}` : ""}` : cfg.stored === false ? " · all defaults" : ""}</span>
      </div>
      {cfg.profile && (
        <div data-testid={`${testId}-profile`} className="flex flex-col" style={{ gap: 4, fontSize: 12 }}>
          <span style={{ color: "var(--cp-ink-2)" }}>Risk profile <span style={mono}>{cfg.profile.name ?? "—"}</span>{cfg.profile.limitsVersion ? <> · limits <span style={mono}>{cfg.profile.limitsVersion}</span></> : null}{cfg.profile.stored === false ? " (the default profile; none saved)" : ""}</span>
          <span style={{ ...mono, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{Object.entries(cfg.profile.limits).map(([k, v]) => `${k} ${showNum(v)}`).join(" · ") || "no limits returned"}</span>
        </div>
      )}
      {!v2 && <span data-testid={`${testId}-old-shape`} style={{ ...quiet, color: "var(--amber)" }}>This server does not report the defaults or which values you set, so reset to default is not available.</span>}
      {cfg.warnings.length > 0 && (
        <ul data-testid={`${testId}-warnings`} className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, fontSize: 12, color: "var(--amber)" }}>
          {cfg.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
      {modeEditable && (
        <label className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 12.5 }}>
          <span style={{ color: "var(--cp-ink-3)" }}>Mode</span>
          <select data-testid={`${testId}-mode`} value={mode} onChange={(e) => setMode(e.target.value as SptMode)} style={input}>
            {MODES.map((m) => <option key={m} value={m}>{MODE_WORDS[m].label}</option>)}
          </select>
        </label>
      )}
      {groups.map((g) => (
        <div key={g} className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <span style={{ ...eyebrow, fontSize: 9.5 }}>{g}</span>
          {LEAVES.filter((l) => l.group === g).map((l) => {
            const eff = cfg.extras[l.path] ?? null;
            const def = cfg.defaults ? cfg.defaults[l.path] ?? null : null;
            const overridden = cfg.overrides ? cfg.overrides[l.path] != null : null;
            const src = cfg.sources[l.path] ?? null;
            const reset = resets.has(l.path);
            const value = reset ? (def == null ? "" : String(def)) : draft[l.path] ?? (eff == null ? "" : String(eff));
            const dirty = reset || (draft[l.path] != null && l.path in changes);
            return (
              <div key={l.path} data-testid={`${testId}-leaf`} data-path={l.path} data-overridden={overridden == null ? "" : overridden ? "true" : "false"}
                className="grid" style={{ gridTemplateColumns: narrow ? "minmax(0,1fr)" : "minmax(0,1.5fr) minmax(0,0.8fr) minmax(0,2fr)", gap: narrow ? 4 : 12, alignItems: "center",
                  padding: "8px 10px", borderRadius: 10, border: `1px solid ${errField === l.path || bad.includes(l.path) ? "var(--danger-line)" : dirty ? "var(--mint-line)" : "var(--cp-line)"}` }}>
                <label htmlFor={`${testId}-${l.path}`} style={{ fontSize: 12.5, color: "var(--cp-ink)" }}>{l.label}</label>
                <span className="flex items-center" style={{ gap: 6 }}>
                  <input id={`${testId}-${l.path}`} data-testid={`${testId}-input`} data-path={l.path} type="number" step={l.step} inputMode="decimal" value={value} disabled={reset}
                    onChange={(e) => setDraft((d) => ({ ...d, [l.path]: e.target.value }))} style={{ ...input, width: 120, fontFamily: MONO }} />
                  <span style={{ ...quiet, fontSize: 11 }}>{UNIT[l.unit]}</span>
                </span>
                <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px", fontSize: 11.5, color: "var(--cp-ink-3)" }}>
                  {overridden ? <Pill tone="indigo" testId={`${testId}-overridden`} style={{ padding: "1px 7px", fontSize: 9 }}>overridden</Pill>
                    : overridden === false ? <Pill tone="ink" style={{ padding: "1px 7px", fontSize: 9 }}>default</Pill> : null}
                  <span data-testid={`${testId}-default`}>default {showVal(l, def)}</span>
                  {src && <span data-testid={`${testId}-source`} title={src} style={{ overflowWrap: "anywhere" }}>· {sourceKind(src)}: {src}</span>}
                  {v2 && overridden && !reset && <button type="button" data-testid={`${testId}-reset`} style={{ ...linkBtn, fontSize: 11.5 }} onClick={() => setResets((s) => new Set(s).add(l.path))}>Reset to default</button>}
                  {reset && <button type="button" data-testid={`${testId}-undo`} style={{ ...linkBtn, fontSize: 11.5 }} onClick={() => setResets((s) => { const n = new Set(s); n.delete(l.path); return n; })}>Undo reset</button>}
                  {bad.includes(l.path) && <span style={{ color: "var(--cp-danger)" }}>not a number</span>}
                </span>
              </div>
            );
          })}
        </div>
      ))}
      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <label htmlFor={`${testId}-reason`} style={{ ...quiet, color: "var(--cp-ink-2)" }}>Reason{requireReason ? " (required)" : " (recorded with the change; required to loosen)"}</label>
        <input id={`${testId}-reason`} data-testid={`${testId}-reason`} type="text" maxLength={500} value={reason} onChange={(e) => { setReason(e.target.value); setNeedReason(false); }} style={{ ...input, width: "100%" }} />
        {needReason && <span data-testid={`${testId}-need-reason`} role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>A reason is required for this change.</span>}
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <button type="button" data-testid={`${testId}-save`} style={btnPrimary} disabled={saving || !nChanged || bad.length > 0} onClick={save}>
          {saving ? "Saving…" : nChanged ? `Save ${nChanged} change${nChanged === 1 ? "" : "s"}` : "Nothing changed"}
        </button>
        {nChanged > 0 && <button type="button" data-testid={`${testId}-discard`} style={btn} onClick={() => { setDraft({}); setResets(new Set()); setMode(cfg.mode ?? ""); }}>Discard</button>}
        {saved && !nChanged && <span data-testid={`${testId}-saved`} role="status" style={{ ...quiet, color: "var(--mint)" }}>Saved.</span>}
      </div>
      {error ? <ConfigProblem e={error} onReload={onReload} testId={`${testId}-error`} /> : null}
    </section>
  );
}

function VersionList({ versions, testId, pending }: { versions: ConfigVersion[] | null; testId: string; pending?: boolean }) {
  return (
    <Section title="Change history" testId={testId}>
      {versions == null ? <span style={quiet}>{pending ? "Reading the history…" : "The history was not returned."}</span>
        : versions.length === 0 ? <span data-testid={`${testId}-empty`} style={quiet}>No change recorded yet.</span>
        : (
          <ol className="m-0 flex flex-col" style={{ gap: 6, padding: 0, listStyle: "none" }}>
            {versions.map((v) => (
              <li key={v.id} data-testid={`${testId}-row`} className="flex min-w-0 flex-col" style={{ gap: 2, padding: "6px 0", borderBottom: "1px solid var(--cp-line)", fontSize: 12.5 }}>
                <span className="flex flex-wrap items-baseline" style={{ gap: "2px 10px" }}>
                  <span style={mono}>v{v.version ?? "—"}</span>
                  <span style={{ ...mono, color: "var(--cp-ink-3)" }}>{istTime(v.at)}</span>
                  <span style={{ color: "var(--cp-ink-2)" }}>{v.actor ?? "—"}{v.actorIsAdmin ? " (admin)" : ""}</span>
                  {v.status && v.status !== "applied" && <Pill tone="amber" style={{ padding: "1px 6px", fontSize: 9 }}>{v.status}</Pill>}
                </span>
                <span style={{ ...mono, fontSize: 11, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{v.changed.join(" · ") || "—"}{v.loosened.length ? ` · loosened: ${v.loosened.join(", ")}` : ""}</span>
                {v.reason && <span style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>“{v.reason}”</span>}
              </li>
            ))}
          </ol>
        )}
    </Section>
  );
}

// ── admin ────────────────────────────────────────────────────────────────

function AdminPanel({ narrow }: { narrow: boolean }) {
  const [uidText, setUidText] = useState("");
  const [uid, setUid] = useState<string | null>(null);
  const q = useAdminConfig(uid);
  const put = usePutAdminConfig();
  return (
    <section data-testid="spt-admin" className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", gap: 14, padding: "16px 16px 14px", borderColor: "var(--indigo-line)" }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 12px" }}>
        <h3 className="cp-eyebrow m-0" style={{ color: "var(--cp-indigo)" }}>Admin</h3>
        <span style={{ ...quiet, fontSize: 11 }}>An admin may set any value within the allowed ranges, in either direction. A reason is required.</span>
      </div>
      <form data-testid="spt-admin-load" className="flex flex-wrap items-center" style={{ gap: 8 }} onSubmit={(e) => { e.preventDefault(); const t = uidText.trim(); if (t) { put.reset(); setUid(t); } }}>
        <input data-testid="spt-admin-uid" aria-label="User id" placeholder="User id" value={uidText} onChange={(e) => setUidText(e.target.value)} style={{ ...input, width: 240 }} />
        <button type="submit" data-testid="spt-admin-load-btn" style={btn}>Load config</button>
      </form>
      {uid && (q.isError ? <ProblemLine p={sptProblem(q.error)} testId="spt-admin-load-error" lead={`${uid}:`} />
        : q.isPending ? <LoadingBlock label={`Reading ${uid}`} rows={3} />
        : q.data?.config ? (
          <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
            <span data-testid="spt-admin-user" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>User <span style={mono}>{q.data.accountId}</span> · mode <span style={mono}>{q.data.config.mode ?? "—"}</span></span>
            <LimitsForm key={`${uid}:${q.data.config.version ?? "x"}`} cfg={q.data.config} testId="spt-admin-limits" requireReason narrow={narrow} modeEditable
              saving={put.isPending} error={put.error} saved={put.isSuccess} onReload={() => { put.reset(); q.refetch(); }}
              onSave={(body) => put.mutate({ userId: uid, body })} />
            <VersionList versions={q.data.versions} testId="spt-admin-versions" />
          </div>
        ) : null)}
      <MarketSettings />
    </section>
  );
}

const MARKET_LABEL: Record<string, string> = {
  min_adv_rs: "Minimum average daily traded value to qualify (₹)",
  positional_window_sessions: "Positional opportunity window (sessions)",
  validate_max_per_round: "Validations per round",
  quote_max_age_s: "Oldest live quote used (seconds)",
};

function MarketSettings() {
  const q = useAdminSettings(true);
  const put = usePutAdminSettings();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [resets, setResets] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");
  const [needReason, setNeedReason] = useState(false);
  const d = q.data;
  const fields = d ? Object.keys({ ...d.fields, ...d.values }) : [];
  const changes: Record<string, number | null> = {};
  let bad = false;
  for (const f of fields) {
    if (resets.has(f)) { changes[f] = null; continue; }
    const t = draft[f];
    if (t == null) continue;
    const n = t.trim() === "" ? NaN : Number(t);
    if (!Number.isFinite(n)) { bad = true; continue; }
    if (n !== d?.values[f]) changes[f] = n;
  }
  const n = Object.keys(changes).length;
  const reload = () => { setDraft({}); setResets(new Set()); put.reset(); q.refetch(); };
  const save = () => {
    if (!n || bad) return;
    if (!reason.trim()) { setNeedReason(true); return; }
    put.mutate({ values: changes, reason: reason.trim(), ...(d?.version != null ? { expected_version: d.version } : {}) },
      { onSuccess: () => { setDraft({}); setResets(new Set()); setReason(""); } });
  };
  let body: ReactNode;
  if (q.isError) body = <ProblemLine p={sptProblem(q.error)} testId="spt-market-error-load" />;
  else if (!d) body = <LoadingBlock label="Reading the market-wide settings" rows={2} />;
  else body = (
    <>
      <span style={{ ...quiet, fontSize: 11 }}>version {d.version ?? "—"}{d.updatedAt ? ` · changed ${istTime(d.updatedAt)}${d.updatedBy ? ` by ${d.updatedBy}` : ""}` : ""} · a stored value wins over the environment, which wins over the default.</span>
      {fields.map((f) => {
        const spec = d.fields[f];
        const stored = d.stored[f] != null;
        const reset = resets.has(f);
        return (
          <div key={f} data-testid="spt-market-field" data-field={f} className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px", padding: "8px 10px", borderRadius: 10, border: "1px solid var(--cp-line)" }}>
            <label htmlFor={`spt-market-${f}`} style={{ fontSize: 12.5, flex: "1 1 220px", minWidth: 0 }}>{MARKET_LABEL[f] ?? f}</label>
            <input id={`spt-market-${f}`} data-testid="spt-market-input" data-field={f} type="number" value={reset ? "" : draft[f] ?? (d.values[f] == null ? "" : String(d.values[f]))} disabled={reset}
              placeholder={reset ? "default" : undefined} onChange={(e) => setDraft((x) => ({ ...x, [f]: e.target.value }))} style={{ ...input, width: 140, fontFamily: MONO }} />
            <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)", flex: "1 1 260px", minWidth: 0, overflowWrap: "anywhere" }}>
              {d.sources[f] ?? "—"} · default {showNum(spec?.default)}{spec?.range ? ` · range ${showNum(spec.range[0])}–${showNum(spec.range[1])}` : ""}{spec?.usedBy ? ` · ${spec.usedBy}` : ""}
            </span>
            {stored && !reset && <button type="button" data-testid="spt-market-reset" style={{ ...linkBtn, fontSize: 11.5 }} onClick={() => setResets((s) => new Set(s).add(f))}>Remove the stored value</button>}
          </div>
        );
      })}
      <input data-testid="spt-market-reason" aria-label="Reason (required)" placeholder="Reason (required)" value={reason} maxLength={500} onChange={(e) => { setReason(e.target.value); setNeedReason(false); }} style={{ ...input, width: "100%" }} />
      {needReason && <span data-testid="spt-market-need-reason" role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>A reason is required.</span>}
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <button type="button" data-testid="spt-market-save" style={btnPrimary} disabled={put.isPending || !n || bad} onClick={save}>{put.isPending ? "Saving…" : n ? `Save ${n} change${n === 1 ? "" : "s"}` : "Nothing changed"}</button>
        {put.isSuccess && !n && <span data-testid="spt-market-saved" role="status" style={{ ...quiet, color: "var(--mint)" }}>Saved.</span>}
      </div>
      {put.isError && <ConfigProblem e={put.error} onReload={reload} testId="spt-market-error" />}
      <VersionList versions={d.versions} testId="spt-market-versions" />
    </>
  );
  return (
    <div data-testid="spt-market" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <span style={{ ...eyebrow, fontSize: 10, color: "var(--cp-ink-2)" }}>Market-wide settings (every account)</span>
      {body}
    </div>
  );
}
