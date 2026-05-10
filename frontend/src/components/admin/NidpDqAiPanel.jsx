import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  Loader2, Plus, Pencil, Trash2, Check, X, Sparkles,
  AlertTriangle, Power, RefreshCcw, FileText,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;
const DQ = `${API}/api/admin/nidp/dq`;

const SEV = ["INFO", "WARN", "ERROR", "CRITICAL"];
const SEV_COLOR = {
  INFO: "bg-slate-100 text-slate-600",
  WARN: "bg-amber-100 text-amber-700",
  ERROR: "bg-rose-100 text-rose-700",
  CRITICAL: "bg-rose-200 text-rose-900 font-semibold",
};

/**
 * AI-assisted Data Quality — CRUD on expectations + review proposals +
 * one-click AI generation across all NIDP feeds.
 *
 * Tabs:
 *  1) Active     — list + add + edit + soft-delete
 *  2) Proposals  — review AI suggestions; accept → promotes to Active
 *  3) Generate   — pick a feed (or "all") → run AI author
 */
export default function NidpDqAiPanel() {
  const [tab, setTab] = useState("active");
  return (
    <div className="space-y-4" data-testid="dq-ai-panel">
      <div className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-700">
        {[
          { id: "active",    label: "Active Rules",   icon: FileText },
          { id: "proposals", label: "AI Proposals",   icon: Sparkles },
          { id: "generate",  label: "Generate (AI)",  icon: RefreshCcw },
        ].map(t => (
          <button
            key={t.id}
            data-testid={`dq-tab-${t.id}`}
            onClick={() => setTab(t.id)}
            className={
              "flex items-center gap-1.5 px-4 py-2 -mb-px text-sm border-b-2 transition " +
              (tab === t.id
                ? "border-indigo-500 text-indigo-600 font-medium"
                : "border-transparent text-slate-500 hover:text-slate-800")
            }
          >
            <t.icon className="w-4 h-4" /> {t.label}
          </button>
        ))}
      </div>
      {tab === "active"    && <ActiveRulesTab />}
      {tab === "proposals" && <ProposalsTab />}
      {tab === "generate"  && <GenerateTab />}
    </div>
  );
}

// ─────────── Active Rules Tab ───────────
function ActiveRulesTab() {
  const [rules, setRules]     = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [filter, setFilter]   = useState("");
  const [editing, setEditing] = useState(null);   // rule_id or "NEW"

  const reload = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await axios.get(`${DQ}/expectations/active?include_inactive=false&limit=500`, { withCredentials: true });
      setRules(r.data.data || []);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { reload(); }, [reload]);

  const filtered = rules.filter(r => {
    const q = filter.trim().toLowerCase();
    return !q
      || r.dataset_name?.toLowerCase().includes(q)
      || r.name?.toLowerCase().includes(q)
      || r.expression?.toLowerCase().includes(q);
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <input
          data-testid="dq-active-filter"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="filter by dataset / name / expression…"
          className="flex-1 px-3 py-1.5 text-sm border rounded-md dark:bg-slate-800"
        />
        <button
          data-testid="dq-active-add-btn"
          onClick={() => setEditing("NEW")}
          className="flex items-center gap-1 px-3 py-1.5 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700"
        ><Plus className="w-4 h-4" /> Add Rule</button>
        <button
          data-testid="dq-active-reload"
          onClick={reload}
          className="px-2 py-1.5 text-sm border rounded-md"
          title="reload"
        ><RefreshCcw className="w-4 h-4" /></button>
      </div>

      {editing === "NEW" && (
        <RuleEditor
          mode="create"
          onSaved={() => { setEditing(null); reload(); }}
          onCancel={() => setEditing(null)}
        />
      )}

      {error && <ErrorBanner error={error} />}
      {loading && <Loader2 className="w-5 h-5 animate-spin text-slate-400 mx-auto my-6" />}

      {!loading && (
        <div className="border rounded-md overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 dark:bg-slate-800 text-left">
              <tr>
                <th className="px-2 py-1.5">Dataset</th>
                <th className="px-2 py-1.5">Name</th>
                <th className="px-2 py-1.5">Severity</th>
                <th className="px-2 py-1.5">Source</th>
                <th className="px-2 py-1.5">Expression</th>
                <th className="px-2 py-1.5 w-24">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr><td colSpan={6} className="text-center py-6 text-slate-400">no rules — add one or generate via AI</td></tr>
              )}
              {filtered.map(r => editing === r.rule_id ? (
                <tr key={r.rule_id}>
                  <td colSpan={6} className="p-2 bg-slate-50 dark:bg-slate-900">
                    <RuleEditor
                      mode="edit"
                      rule={r}
                      onSaved={() => { setEditing(null); reload(); }}
                      onCancel={() => setEditing(null)}
                    />
                  </td>
                </tr>
              ) : (
                <tr key={r.rule_id} className="border-t hover:bg-slate-50 dark:hover:bg-slate-800" data-testid={`dq-rule-row-${r.rule_id}`}>
                  <td className="px-2 py-1.5 font-mono text-xs">{r.dataset_name}</td>
                  <td className="px-2 py-1.5 font-medium">{r.name}</td>
                  <td className="px-2 py-1.5"><span className={"inline-block px-1.5 py-0.5 rounded text-[10px] " + (SEV_COLOR[r.severity] || "")}>{r.severity}</span></td>
                  <td className="px-2 py-1.5"><span className="text-[10px] text-slate-500">{r.source}</span></td>
                  <td className="px-2 py-1.5 font-mono text-[11px] text-slate-600 max-w-[420px] truncate" title={r.expression}>{r.expression}</td>
                  <td className="px-2 py-1.5">
                    <div className="flex gap-1">
                      <button title="edit" onClick={() => setEditing(r.rule_id)} className="text-slate-500 hover:text-indigo-600"><Pencil className="w-3.5 h-3.5"/></button>
                      <ToggleActiveBtn rule={r} onChanged={reload} />
                      <DeleteRuleBtn rule={r} onDeleted={reload} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RuleEditor({ mode, rule, onSaved, onCancel }) {
  const [form, setForm] = useState(() => ({
    dataset_name: rule?.dataset_name || "",
    name:         rule?.name || "",
    expression:   rule?.expression || "",
    severity:     rule?.severity || "ERROR",
    description:  rule?.description || "",
    rationale:    rule?.rationale || "",
    business_impact: rule?.business_impact || "",
  }));
  const [saving, setSaving] = useState(false);
  const [err, setErr]       = useState(null);

  const save = async () => {
    setSaving(true); setErr(null);
    try {
      if (mode === "create") {
        await axios.post(`${DQ}/expectations/active`, { ...form, actor: "ui" }, { withCredentials: true });
      } else {
        const patch = {
          expression: form.expression, severity: form.severity,
          description: form.description, rationale: form.rationale,
          business_impact: form.business_impact, actor: "ui",
        };
        await axios.patch(`${DQ}/expectations/active/${rule.rule_id}`, patch, { withCredentials: true });
      }
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setSaving(false); }
  };

  return (
    <div className="space-y-2 p-3 border rounded-md bg-white dark:bg-slate-900" data-testid="dq-rule-editor">
      <div className="grid grid-cols-3 gap-2">
        <input data-testid="dq-rule-field-dataset_name" disabled={mode === "edit"}
               value={form.dataset_name}
               onChange={e => setForm({ ...form, dataset_name: e.target.value })}
               placeholder="dataset_name (e.g., prices_eod)"
               className="px-2 py-1 text-xs border rounded dark:bg-slate-800" />
        <input data-testid="dq-rule-field-name" disabled={mode === "edit"}
               value={form.name}
               onChange={e => setForm({ ...form, name: e.target.value })}
               placeholder="rule_name_snake_case"
               className="px-2 py-1 text-xs border rounded dark:bg-slate-800" />
        <select data-testid="dq-rule-field-severity"
                value={form.severity}
                onChange={e => setForm({ ...form, severity: e.target.value })}
                className="px-2 py-1 text-xs border rounded dark:bg-slate-800">
          {SEV.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <textarea data-testid="dq-rule-field-expression"
                value={form.expression}
                onChange={e => setForm({ ...form, expression: e.target.value })}
                placeholder="SQL boolean expression (e.g., close BETWEEN low AND high)"
                rows={2}
                className="w-full px-2 py-1 text-xs font-mono border rounded dark:bg-slate-800" />
      <input data-testid="dq-rule-field-description"
             value={form.description}
             onChange={e => setForm({ ...form, description: e.target.value })}
             placeholder="description (one line)"
             className="w-full px-2 py-1 text-xs border rounded dark:bg-slate-800" />
      <input data-testid="dq-rule-field-rationale"
             value={form.rationale}
             onChange={e => setForm({ ...form, rationale: e.target.value })}
             placeholder="rationale (why this rule exists)"
             className="w-full px-2 py-1 text-xs border rounded dark:bg-slate-800" />
      <input data-testid="dq-rule-field-business_impact"
             value={form.business_impact}
             onChange={e => setForm({ ...form, business_impact: e.target.value })}
             placeholder="business impact (what breaks if violated)"
             className="w-full px-2 py-1 text-xs border rounded dark:bg-slate-800" />
      {err && <ErrorBanner error={err} />}
      <div className="flex gap-2">
        <button data-testid="dq-rule-save-btn" disabled={saving} onClick={save}
                className="flex items-center gap-1 px-3 py-1 text-xs bg-emerald-600 text-white rounded hover:bg-emerald-700 disabled:opacity-50">
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin"/> : <Check className="w-3.5 h-3.5"/>}
          {mode === "create" ? "Create" : "Save"}
        </button>
        <button data-testid="dq-rule-cancel-btn" onClick={onCancel}
                className="px-3 py-1 text-xs border rounded hover:bg-slate-100 dark:hover:bg-slate-800">Cancel</button>
      </div>
    </div>
  );
}

function ToggleActiveBtn({ rule, onChanged }) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      title={rule.active ? "deactivate" : "reactivate"}
      disabled={busy}
      data-testid={`dq-rule-toggle-${rule.rule_id}`}
      onClick={async () => {
        setBusy(true);
        try {
          await axios.patch(`${DQ}/expectations/active/${rule.rule_id}`,
                            { active: !rule.active, actor: "ui" },
                            { withCredentials: true });
          onChanged();
        } finally { setBusy(false); }
      }}
      className={"text-slate-500 hover:" + (rule.active ? "text-amber-600" : "text-emerald-600")}
    ><Power className="w-3.5 h-3.5"/></button>
  );
}

function DeleteRuleBtn({ rule, onDeleted }) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      title="soft-delete"
      disabled={busy}
      data-testid={`dq-rule-delete-${rule.rule_id}`}
      onClick={async () => {
        if (!window.confirm(`Soft-delete rule "${rule.name}" on ${rule.dataset_name}?`)) return;
        setBusy(true);
        try {
          await axios.delete(`${DQ}/expectations/active/${rule.rule_id}?actor=ui`,
                             { withCredentials: true });
          onDeleted();
        } finally { setBusy(false); }
      }}
      className="text-slate-500 hover:text-rose-600"
    ><Trash2 className="w-3.5 h-3.5"/></button>
  );
}

// ─────────── Proposals Tab ───────────
function ProposalsTab() {
  const [proposals, setProposals] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [statusFilter, setStatusFilter] = useState("proposed");

  const reload = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const url = `${DQ}/proposals?status=${statusFilter}&limit=200`;
      const r = await axios.get(url, { withCredentials: true });
      setProposals(r.data.data || []);
    } catch (e) { setError(e?.response?.data?.detail || e.message); }
    finally { setLoading(false); }
  }, [statusFilter]);
  useEffect(() => { reload(); }, [reload]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <select data-testid="dq-proposals-status-filter"
                value={statusFilter}
                onChange={e => setStatusFilter(e.target.value)}
                className="px-2 py-1.5 text-sm border rounded-md dark:bg-slate-800">
          <option value="proposed">Proposed</option>
          <option value="accepted">Accepted</option>
          <option value="rejected">Rejected</option>
        </select>
        <button onClick={reload} className="px-2 py-1.5 text-sm border rounded-md"><RefreshCcw className="w-4 h-4"/></button>
        <span className="text-xs text-slate-400 ml-auto">{proposals.length} proposals</span>
      </div>
      {error && <ErrorBanner error={error} />}
      {loading && <Loader2 className="w-5 h-5 animate-spin text-slate-400 mx-auto my-6" />}
      {!loading && proposals.length === 0 && (
        <div className="text-center py-8 text-slate-400 text-sm">
          no {statusFilter} proposals — try the Generate tab
        </div>
      )}
      {!loading && proposals.map(p => (
        <ProposalCard key={p.proposal_id} proposal={p} onChanged={reload} />
      ))}
    </div>
  );
}

function ProposalCard({ proposal, onChanged }) {
  const rule = typeof proposal.proposed_rule_json === "string"
    ? JSON.parse(proposal.proposed_rule_json)
    : proposal.proposed_rule_json;
  const [busy, setBusy] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject]     = useState(false);

  const accept = async () => {
    setBusy(true);
    try {
      await axios.post(`${DQ}/proposals/${proposal.proposal_id}/accept`,
                       { reviewer: "ui" }, { withCredentials: true });
      onChanged();
    } finally { setBusy(false); }
  };
  const reject = async () => {
    if (!rejectReason.trim()) return;
    setBusy(true);
    try {
      await axios.post(`${DQ}/proposals/${proposal.proposal_id}/reject`,
                       { reviewer: "ui", reason: rejectReason }, { withCredentials: true });
      onChanged();
    } finally { setBusy(false); }
  };

  return (
    <div className="border rounded-md p-3 bg-white dark:bg-slate-900" data-testid={`dq-proposal-${proposal.proposal_id}`}>
      <div className="flex items-start gap-2">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-mono text-xs text-slate-500">{proposal.dataset_name}</span>
            <span className="font-medium text-sm">{rule.name}</span>
            <span className={"inline-block px-1.5 py-0.5 rounded text-[10px] " + (SEV_COLOR[rule.severity] || "")}>{rule.severity}</span>
            <span className="text-[10px] text-slate-400">{proposal.llm_model}</span>
          </div>
          <p className="text-xs text-slate-600 dark:text-slate-300">{rule.description}</p>
          <pre className="mt-1 text-[11px] font-mono p-1.5 bg-slate-50 dark:bg-slate-800 rounded overflow-x-auto">{rule.expression}</pre>
          {rule.rationale && <p className="mt-1 text-[11px] text-slate-500 italic">▸ {rule.rationale}</p>}
        </div>
        {proposal.status === "proposed" && (
          <div className="flex flex-col gap-1">
            <button data-testid={`dq-proposal-accept-${proposal.proposal_id}`} disabled={busy} onClick={accept}
                    className="flex items-center gap-1 px-2 py-1 text-xs bg-emerald-600 text-white rounded hover:bg-emerald-700 disabled:opacity-50">
              <Check className="w-3.5 h-3.5"/> Accept
            </button>
            <button data-testid={`dq-proposal-reject-${proposal.proposal_id}`} onClick={() => setShowReject(!showReject)}
                    className="flex items-center gap-1 px-2 py-1 text-xs border rounded hover:bg-rose-50">
              <X className="w-3.5 h-3.5"/> Reject
            </button>
          </div>
        )}
      </div>
      {showReject && proposal.status === "proposed" && (
        <div className="flex gap-2 mt-2">
          <input value={rejectReason} onChange={e => setRejectReason(e.target.value)}
                 placeholder="reason"
                 className="flex-1 px-2 py-1 text-xs border rounded dark:bg-slate-800"/>
          <button disabled={busy || !rejectReason.trim()} onClick={reject}
                  className="px-2 py-1 text-xs bg-rose-600 text-white rounded disabled:opacity-50">Confirm</button>
        </div>
      )}
    </div>
  );
}

// ─────────── Generate Tab ───────────
function GenerateTab() {
  const [feed, setFeed]   = useState("");
  const [sampleSize, setSampleSize]     = useState(200);
  const [failureDays, setFailureDays]   = useState(30);
  const [busy, setBusy]   = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError]   = useState(null);

  const run = async ({ all }) => {
    setBusy(true); setError(null); setResult(null);
    try {
      const url = all ? `${DQ}/proposals/generate-all` : `${DQ}/proposals/generate`;
      const body = all
        ? { sample_size: sampleSize, failure_history_days: failureDays }
        : { dataset: feed.trim(), sample_size: sampleSize, failure_history_days: failureDays };
      const r = await axios.post(url, body, { withCredentials: true });
      setResult(r.data);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-3 max-w-2xl">
      <div className="p-3 border rounded-md bg-slate-50 dark:bg-slate-800 space-y-2 text-xs">
        <p className="text-slate-600 dark:text-slate-300">
          AI generates strict, business-aware expectations per feed. Proposals appear on the <b>AI Proposals</b> tab for review. Nothing auto-applies.
        </p>
        <div className="grid grid-cols-3 gap-2">
          <input data-testid="dq-gen-feed" value={feed} onChange={e => setFeed(e.target.value)}
                 placeholder="dataset_name (e.g., prices_eod)"
                 className="px-2 py-1 border rounded dark:bg-slate-900"/>
          <label className="flex items-center gap-1">sample size
            <input type="number" data-testid="dq-gen-sample" value={sampleSize}
                   onChange={e => setSampleSize(parseInt(e.target.value, 10) || 200)}
                   className="w-20 px-2 py-1 border rounded dark:bg-slate-900"/></label>
          <label className="flex items-center gap-1">failure-history days
            <input type="number" data-testid="dq-gen-days" value={failureDays}
                   onChange={e => setFailureDays(parseInt(e.target.value, 10) || 30)}
                   className="w-20 px-2 py-1 border rounded dark:bg-slate-900"/></label>
        </div>
        <div className="flex gap-2 pt-1">
          <button data-testid="dq-gen-one-btn" disabled={busy || !feed.trim()} onClick={() => run({ all: false })}
                  className="flex items-center gap-1 px-3 py-1.5 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50">
            {busy ? <Loader2 className="w-4 h-4 animate-spin"/> : <Sparkles className="w-4 h-4"/>}
            Generate for this feed
          </button>
          <button data-testid="dq-gen-all-btn" disabled={busy} onClick={() => run({ all: true })}
                  className="flex items-center gap-1 px-3 py-1.5 border rounded hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-50">
            {busy ? <Loader2 className="w-4 h-4 animate-spin"/> : <Sparkles className="w-4 h-4"/>}
            Generate for ALL feeds
          </button>
        </div>
        {busy && <p className="text-[11px] text-slate-400">running… all-feeds may take 1-3 minutes</p>}
      </div>

      {error && <ErrorBanner error={error}/>}
      {result && (
        <div className="p-3 border rounded-md text-xs bg-white dark:bg-slate-900" data-testid="dq-gen-result">
          {result.attempted != null ? (
            <>
              <p className="font-medium mb-1">Generated across {result.attempted} feeds:</p>
              <table className="w-full text-[11px]">
                <thead><tr className="text-left text-slate-500"><th>feed</th><th>status</th><th>proposals</th><th>error</th></tr></thead>
                <tbody>
                  {result.results.map(r => (
                    <tr key={r.feed} className="border-t">
                      <td className="font-mono py-0.5">{r.feed}</td>
                      <td>{r.ok ? <span className="text-emerald-600">ok</span> : <span className="text-rose-600">fail</span>}</td>
                      <td>{r.proposals_count ?? "—"}</td>
                      <td className="text-rose-500 truncate max-w-[300px]">{r.error || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <pre className="text-[11px]">{JSON.stringify(result, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  );
}

function ErrorBanner({ error }) {
  let msg;
  if (Array.isArray(error)) {
    msg = error.map(x => x?.msg || JSON.stringify(x)).join("; ");
  } else if (error && typeof error === "object") {
    msg = error.msg || JSON.stringify(error);
  } else {
    msg = String(error);
  }
  return (
    <div className="flex items-center gap-2 px-2 py-1.5 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700">
      <AlertTriangle className="w-3.5 h-3.5"/> {msg}
    </div>
  );
}
