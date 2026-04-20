import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  SlidersHorizontal, RefreshCw, RotateCcw, Save, Power, PowerOff,
  Plus, Trash2, CheckCircle2, AlertCircle, PlayCircle, Copy,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/components/ui/select";
import { motion, AnimatePresence } from "framer-motion";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const RULE_BADGES = {
  rule_1_regular_to_direct: { bg: "bg-indigo-50 dark:bg-indigo-950/40", text: "text-indigo-700 dark:text-indigo-300", tag: "P0" },
  rule_2_amc_concentration: { bg: "bg-rose-50 dark:bg-rose-950/40", text: "text-rose-700 dark:text-rose-300", tag: "P0" },
  rule_2b_category_concentration: { bg: "bg-rose-50 dark:bg-rose-950/40", text: "text-rose-700 dark:text-rose-300", tag: "P0" },
  rule_3_underperformer_replacement: { bg: "bg-amber-50 dark:bg-amber-950/40", text: "text-amber-700 dark:text-amber-300", tag: "P1" },
  rule_4_different_fund_overlap: { bg: "bg-amber-50 dark:bg-amber-950/40", text: "text-amber-700 dark:text-amber-300", tag: "P1" },
  rule_5_debt_allocation: { bg: "bg-emerald-50 dark:bg-emerald-950/40", text: "text-emerald-700 dark:text-emerald-300", tag: "P2" },
  rule_6_cost_leak_switch: { bg: "bg-indigo-50 dark:bg-indigo-950/40", text: "text-indigo-700 dark:text-indigo-300", tag: "P0" },
  rule_7_do_nothing: { bg: "bg-teal-50 dark:bg-teal-950/40", text: "text-teal-700 dark:text-teal-300", tag: "P2" },
};

const PARAM_LABELS = {
  threshold_pct: { label: "Threshold", suffix: "%", step: 0.5, min: 0, max: 100 },
  overlap_threshold_pct: { label: "Overlap threshold", suffix: "%", step: 1, min: 0, max: 100 },
  total_leak_threshold_rs: { label: "Total cost leak trigger", suffix: "₹/yr", step: 500, min: 0 },
  max_switches: { label: "Max switch actions", suffix: "", step: 1, min: 1, max: 10 },
  max_replacements: { label: "Max replacement actions", suffix: "", step: 1, min: 1, max: 10 },
  max_overlap_exits: { label: "Max overlap exits", suffix: "", step: 1, min: 1, max: 10 },
  debt_target_conservative_pct: { label: "Conservative target", suffix: "%", step: 1, min: 0, max: 100 },
  debt_target_medium_pct: { label: "Medium target", suffix: "%", step: 1, min: 0, max: 100 },
  debt_target_aggressive_pct: { label: "Aggressive target", suffix: "%", step: 1, min: 0, max: 100 },
  portfolio_score_threshold: { label: "Healthy score cutoff", suffix: "", step: 1, min: 0, max: 100 },
};

const ACTION_TYPES = [
  { value: "FLAG_ONLY", label: "Flag Only — raise a review card, no transaction" },
  { value: "ADD_DEBT_FUND", label: "Add Debt Fund — suggest debt allocation" },
  { value: "EXIT_HIGHEST_EXIT_SCORE", label: "Exit Highest Score — trim fund in category/AMC" },
];

const SAMPLE_CTX = {
  portfolio_score: 64,
  confidence_score: 98,
  total_value: 6490000,
  equity_pct: 78,
  debt_pct: 5,
  gold_pct: 17,
  max_category_pct: 42,
  max_amc_pct: 23,
  avg_overlap_pct: 55,
  mf_count: 20,
  stock_count: 44,
  fund_count: 20,
};

const RuleRow = ({ rid, rule, defaults, onToggle, onParamChange }) => {
  const badge = RULE_BADGES[rid] || { bg: "bg-slate-100", text: "text-slate-600", tag: "" };
  const isEnabled = rule.enabled !== false;
  const paramKeys = Object.keys(rule.params || {});

  return (
    <div
      data-testid={`rule-row-${rid}`}
      className={`p-5 rounded-2xl border border-slate-100 dark:border-slate-800 ${isEnabled ? "bg-white dark:bg-slate-900/60" : "bg-slate-50 dark:bg-slate-900/30 opacity-75"} transition-all`}
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center gap-1 text-[10px] font-bold tracking-wider uppercase px-2 py-0.5 rounded-md ${badge.bg} ${badge.text}`}>
              {badge.tag}
            </span>
            <h4 className="text-sm font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
              {rule.label}
            </h4>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{rule.description}</p>
        </div>
        <button
          data-testid={`rule-toggle-${rid}`}
          onClick={() => onToggle(rid, !isEnabled)}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-colors ${isEnabled ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100" : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200"}`}
          title={isEnabled ? "Disable this rule" : "Enable this rule"}
        >
          {isEnabled ? <Power className="w-3.5 h-3.5" /> : <PowerOff className="w-3.5 h-3.5" />}
          {isEnabled ? "Enabled" : "Disabled"}
        </button>
      </div>

      {paramKeys.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
          {paramKeys.map((pk) => {
            const meta = PARAM_LABELS[pk] || { label: pk, suffix: "", step: 1 };
            const current = rule.params[pk];
            const dflt = defaults?.params?.[pk];
            const changed = dflt !== undefined && Number(dflt) !== Number(current);
            return (
              <div key={pk} className="min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <Label className="text-[11px] font-medium text-slate-600 dark:text-slate-300">
                    {meta.label} {meta.suffix && <span className="text-slate-400">({meta.suffix})</span>}
                  </Label>
                  {changed && (
                    <span className="text-[10px] text-amber-600 dark:text-amber-400">
                      default {dflt}
                    </span>
                  )}
                </div>
                <Input
                  data-testid={`rule-param-${rid}-${pk}`}
                  type="number"
                  step={meta.step}
                  min={meta.min}
                  max={meta.max}
                  value={current}
                  onChange={(e) => onParamChange(rid, pk, e.target.value)}
                  disabled={!isEnabled}
                  className="h-9 text-sm bg-slate-50 dark:bg-slate-900 border-slate-200 dark:border-slate-700 rounded-lg"
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

const CustomRuleEditor = ({ onSave, onCancel, initial, allowedKeys, allowedActions }) => {
  const [form, setForm] = useState(initial || {
    name: "", description: "", expression: "", action_type: "FLAG_ONLY",
    reason_code: "", reason_text: "", enabled: true, target: {},
  });
  const [validation, setValidation] = useState(null);
  const [saving, setSaving] = useState(false);

  const validate = useCallback(async (evaluate = false) => {
    if (!form.expression.trim()) {
      setValidation({ ok: false, error: "Expression is empty" });
      return;
    }
    try {
      const { data } = await axios.post(
        `${API}/admin/rules-config/custom/validate`,
        { expression: form.expression, sample_context: evaluate ? SAMPLE_CTX : null },
        { withCredentials: true },
      );
      setValidation(data);
    } catch (err) {
      setValidation({ ok: false, error: err.response?.data?.detail || "validation failed" });
    }
  }, [form.expression]);

  const save = async () => {
    if (!form.name.trim() || !form.expression.trim()) {
      toast.error("Name and expression required"); return;
    }
    setSaving(true);
    try {
      await axios.post(`${API}/admin/rules-config/custom`, form, { withCredentials: true });
      toast.success(initial ? "Custom rule updated" : "Custom rule created");
      onSave();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const isExit = form.action_type === "EXIT_HIGHEST_EXIT_SCORE";
  const isAddDebt = form.action_type === "ADD_DEBT_FUND";

  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
      className="p-5 rounded-2xl border border-emerald-200 dark:border-emerald-900 bg-emerald-50/30 dark:bg-emerald-950/20 space-y-4"
      data-testid="custom-rule-editor"
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <Label className="text-xs font-medium text-slate-600 dark:text-slate-300">Rule name</Label>
          <Input data-testid="custom-rule-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Conservative debt floor" className="mt-1 h-9 text-sm rounded-lg" />
        </div>
        <div>
          <Label className="text-xs font-medium text-slate-600 dark:text-slate-300">Action type</Label>
          <Select value={form.action_type} onValueChange={(v) => setForm({ ...form, action_type: v })}>
            <SelectTrigger data-testid="custom-rule-action" className="mt-1 h-9 text-sm rounded-lg">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {allowedActions.map((a) => (
                <SelectItem key={a.value} value={a.value}>{a.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div>
        <Label className="text-xs font-medium text-slate-600 dark:text-slate-300">
          Trigger expression <span className="text-slate-400">(allowed: {allowedKeys.join(", ")} + min/max/abs/len/sum/round)</span>
        </Label>
        <Textarea
          data-testid="custom-rule-expression"
          value={form.expression}
          onChange={(e) => { setForm({ ...form, expression: e.target.value }); setValidation(null); }}
          placeholder="debt_pct < 5 and equity_pct > 90"
          rows={2}
          className="mt-1 font-mono text-[13px] rounded-lg"
        />
        <div className="flex items-center gap-2 mt-2 flex-wrap">
          <Button size="sm" variant="outline" onClick={() => validate(false)} className="h-8 text-xs rounded-lg" data-testid="validate-btn">
            <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Validate
          </Button>
          <Button size="sm" variant="outline" onClick={() => validate(true)} className="h-8 text-xs rounded-lg" data-testid="evaluate-btn">
            <PlayCircle className="w-3.5 h-3.5 mr-1" /> Test against sample portfolio
          </Button>
          {validation && (
            <span className={`text-xs inline-flex items-center gap-1 px-2 py-1 rounded-md ${validation.ok ? "bg-emerald-100 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300" : "bg-rose-100 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300"}`}>
              {validation.ok ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertCircle className="w-3.5 h-3.5" />}
              {validation.ok
                ? (validation.evaluated !== undefined ? `ok — evaluated: ${validation.evaluated ? "TRUE" : "FALSE"}` : "valid")
                : validation.error}
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <Label className="text-xs font-medium text-slate-600 dark:text-slate-300">Reason code</Label>
          <Input data-testid="custom-rule-code" value={form.reason_code} onChange={(e) => setForm({ ...form, reason_code: e.target.value })}
            placeholder="CUSTOM_DEBT_FLOOR" className="mt-1 h-9 text-sm rounded-lg font-mono" />
        </div>
        <div>
          <Label className="text-xs font-medium text-slate-600 dark:text-slate-300">User-facing reason text</Label>
          <Input data-testid="custom-rule-reason" value={form.reason_text} onChange={(e) => setForm({ ...form, reason_text: e.target.value })}
            placeholder="Your debt allocation is dangerously low (<5%)." className="mt-1 h-9 text-sm rounded-lg" />
        </div>
      </div>

      {isExit && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 p-3 rounded-xl bg-white/60 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800">
          <div>
            <Label className="text-xs text-slate-500">Category filter (optional)</Label>
            <Input data-testid="target-category" placeholder="Mid Cap" value={form.target?.category || ""}
              onChange={(e) => setForm({ ...form, target: { ...form.target, category: e.target.value } })}
              className="mt-1 h-9 text-sm rounded-lg" />
          </div>
          <div>
            <Label className="text-xs text-slate-500">AMC filter (optional)</Label>
            <Input data-testid="target-amc" placeholder="HDFC" value={form.target?.amc || ""}
              onChange={(e) => setForm({ ...form, target: { ...form.target, amc: e.target.value } })}
              className="mt-1 h-9 text-sm rounded-lg" />
          </div>
          <div>
            <Label className="text-xs text-slate-500">Max exits per plan</Label>
            <Input data-testid="target-max-exits" type="number" min={1} max={5}
              value={form.target?.max_exits || 1}
              onChange={(e) => setForm({ ...form, target: { ...form.target, max_exits: Number(e.target.value) || 1 } })}
              className="mt-1 h-9 text-sm rounded-lg" />
          </div>
        </div>
      )}

      {isAddDebt && (
        <div className="p-3 rounded-xl bg-white/60 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800">
          <Label className="text-xs text-slate-500">Suggested ADD amount (₹, blank = 5% of portfolio)</Label>
          <Input data-testid="target-amount" type="number" value={form.target?.amount_rs || ""}
            onChange={(e) => setForm({ ...form, target: { ...form.target, amount_rs: Number(e.target.value) || 0 } })}
            className="mt-1 h-9 text-sm rounded-lg w-48" />
        </div>
      )}

      <div className="flex items-center justify-end gap-2">
        <Button variant="outline" onClick={onCancel} className="rounded-lg" data-testid="cancel-custom">Cancel</Button>
        <Button onClick={save} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg" data-testid="save-custom">
          <Save className="w-4 h-4 mr-1" /> {saving ? "Saving..." : initial ? "Update" : "Create rule"}
        </Button>
      </div>
    </motion.div>
  );
};

const RulesConfigSection = () => {
  const [cfg, setCfg] = useState(null);
  const [dirty, setDirty] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editingCustom, setEditingCustom] = useState(null);
  const [showNewCustom, setShowNewCustom] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/admin/rules-config`, { withCredentials: true });
      setCfg(data);
      setDirty({});
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to load rules config");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const workingConfig = cfg ? { ...cfg.config, rules: { ...cfg.config.rules, ...dirty } } : null;

  const onToggle = (rid, enabled) => {
    const existing = workingConfig.rules[rid];
    setDirty((d) => ({ ...d, [rid]: { ...existing, enabled } }));
  };

  const onParamChange = (rid, pk, value) => {
    const existing = workingConfig.rules[rid];
    const newParams = { ...existing.params, [pk]: value === "" ? 0 : Number(value) };
    setDirty((d) => ({ ...d, [rid]: { ...existing, params: newParams } }));
  };

  const save = async () => {
    if (!Object.keys(dirty).length) { toast.info("No changes to save"); return; }
    setSaving(true);
    try {
      const payload = {
        rules: Object.fromEntries(
          Object.entries(dirty).map(([rid, cfg]) => [rid, { enabled: cfg.enabled, params: cfg.params }]),
        ),
        custom_rules: workingConfig.custom_rules,
      };
      await axios.put(`${API}/admin/rules-config`, payload, { withCredentials: true });
      toast.success("Rules config saved — live on next plan generation");
      await load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const resetAll = async () => {
    if (!window.confirm("Reset ALL rules (including custom rules) to defaults? This cannot be undone.")) return;
    try {
      await axios.post(`${API}/admin/rules-config/reset`, {}, { withCredentials: true });
      toast.success("Rules config reset to defaults");
      await load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Reset failed");
    }
  };

  const deleteCustom = async (ruleId) => {
    if (!window.confirm("Delete this custom rule?")) return;
    try {
      await axios.delete(`${API}/admin/rules-config/custom/${ruleId}`, { withCredentials: true });
      toast.success("Custom rule deleted");
      await load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Delete failed");
    }
  };

  const hasDirty = Object.keys(dirty).length > 0;
  const customRules = workingConfig?.custom_rules || [];
  const allowedKeys = (editingCustom?.allowed_context_keys) || ["portfolio_score", "confidence_score", "total_value", "equity_pct", "debt_pct", "gold_pct", "max_category_pct", "max_amc_pct", "avg_overlap_pct", "mf_count", "stock_count", "fund_count"];

  if (loading) {
    return (
      <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
        <CardContent className="p-6 flex items-center gap-3 text-sm text-slate-500">
          <div className="w-5 h-5 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
          Loading V2 rules…
        </CardContent>
      </Card>
    );
  }

  return (
    <Card data-testid="rules-config-section" className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
      <CardContent className="p-6 space-y-5">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 flex items-center justify-center">
              <SlidersHorizontal className="w-5 h-5 text-emerald-600" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                V2 Engine Rules
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Tune built-in rule thresholds and add custom rules. Changes apply to the next plan generation.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={load} className="rounded-lg" data-testid="rules-refresh">
              <RefreshCw className="w-4 h-4 mr-1" /> Refresh
            </Button>
            <Button variant="outline" size="sm" onClick={resetAll} className="rounded-lg" data-testid="rules-reset-all">
              <RotateCcw className="w-4 h-4 mr-1" /> Reset to defaults
            </Button>
            <Button
              size="sm" onClick={save} disabled={!hasDirty || saving}
              className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg disabled:opacity-50"
              data-testid="rules-save"
            >
              <Save className="w-4 h-4 mr-1" /> {saving ? "Saving…" : `Save${hasDirty ? ` (${Object.keys(dirty).length})` : ""}`}
            </Button>
          </div>
        </div>

        <div className="space-y-3">
          {Object.entries(workingConfig.rules).map(([rid, rule]) => (
            <RuleRow
              key={rid} rid={rid} rule={rule}
              defaults={cfg.defaults.rules[rid]}
              onToggle={onToggle} onParamChange={onParamChange}
            />
          ))}
        </div>

        {/* ── Custom Rules ── */}
        <div className="pt-4 border-t border-slate-100 dark:border-slate-800">
          <div className="flex items-center justify-between gap-3 mb-3">
            <div>
              <h4 className="text-sm font-semibold text-slate-900 dark:text-white">Custom Rules</h4>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Admin-authored rules evaluated after built-ins. Safe DSL — no code execution.
              </p>
            </div>
            <Button size="sm" onClick={() => { setShowNewCustom(true); setEditingCustom(null); }}
              className="bg-slate-900 hover:bg-slate-800 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100 text-white rounded-lg"
              data-testid="add-custom-rule"
            >
              <Plus className="w-4 h-4 mr-1" /> New custom rule
            </Button>
          </div>

          <AnimatePresence>
            {showNewCustom && (
              <CustomRuleEditor
                initial={null}
                allowedKeys={allowedKeys}
                allowedActions={ACTION_TYPES}
                onCancel={() => setShowNewCustom(false)}
                onSave={() => { setShowNewCustom(false); load(); }}
              />
            )}
            {editingCustom && (
              <CustomRuleEditor
                initial={editingCustom}
                allowedKeys={allowedKeys}
                allowedActions={ACTION_TYPES}
                onCancel={() => setEditingCustom(null)}
                onSave={() => { setEditingCustom(null); load(); }}
              />
            )}
          </AnimatePresence>

          <div className="mt-3 space-y-2">
            {customRules.length === 0 && !showNewCustom && (
              <div className="p-6 text-center text-xs text-slate-400 border border-dashed border-slate-200 dark:border-slate-800 rounded-xl">
                No custom rules yet. Click "New custom rule" to add one.
              </div>
            )}
            {customRules.map((r) => (
              <div key={r.id}
                data-testid={`custom-rule-${r.id}`}
                className={`p-4 rounded-xl border border-slate-100 dark:border-slate-800 ${r.enabled ? "bg-slate-50/50 dark:bg-slate-900/40" : "bg-slate-50 dark:bg-slate-900/20 opacity-60"}`}
              >
                <div className="flex items-start justify-between gap-2 flex-wrap">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[10px] font-bold tracking-wider uppercase px-2 py-0.5 rounded-md bg-violet-100 dark:bg-violet-950/40 text-violet-700 dark:text-violet-300">CUSTOM</span>
                      <h5 className="text-sm font-semibold text-slate-900 dark:text-white">{r.name}</h5>
                      <span className="text-[10px] font-mono text-slate-400">{r.action_type}</span>
                    </div>
                    <code className="block mt-1 text-[12px] font-mono text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-800 px-2 py-1 rounded-md truncate">
                      {r.expression}
                    </code>
                    {r.reason_text && <p className="text-xs text-slate-500 mt-1">{r.reason_text}</p>}
                  </div>
                  <div className="flex items-center gap-1">
                    <button onClick={() => { setEditingCustom(r); setShowNewCustom(false); }}
                      className="p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 hover:text-emerald-600"
                      data-testid={`edit-custom-${r.id}`}
                      title="Edit"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                    <button onClick={() => deleteCustom(r.id)}
                      className="p-1.5 rounded-md hover:bg-rose-50 dark:hover:bg-rose-950/40 text-slate-500 hover:text-rose-600"
                      data-testid={`delete-custom-${r.id}`}
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

export default RulesConfigSection;
