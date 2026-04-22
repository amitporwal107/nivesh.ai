import React, { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function SnapshotWizard({ open, onOpenChange, initial, onSaved }) {
  const [form, setForm] = useState({
    age: initial?.age ?? "",
    marital_status: initial?.marital_status ?? "single",
    dependents: initial?.dependents ?? 0,
    monthly_income_rs: initial?.monthly_income_rs ?? "",
    monthly_expenses_rs: initial?.monthly_expenses_rs ?? "",
    current_corpus_rs: initial?.current_corpus_rs ?? 0,
    total_liabilities_rs: initial?.total_liabilities_rs ?? 0,
    risk_profile: initial?.risk_profile ?? "moderate",
    inflation_pct: initial?.inflation_pct ?? 6.0,
  });
  const [saving, setSaving] = useState(false);

  const update = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    setSaving(true);
    try {
      await axios.put(`${API}/goals/snapshot`, {
        ...form,
        age: form.age ? Number(form.age) : null,
        dependents: Number(form.dependents || 0),
        monthly_income_rs: form.monthly_income_rs ? Number(form.monthly_income_rs) : null,
        monthly_expenses_rs: form.monthly_expenses_rs ? Number(form.monthly_expenses_rs) : null,
        current_corpus_rs: Number(form.current_corpus_rs || 0),
        total_liabilities_rs: Number(form.total_liabilities_rs || 0),
        inflation_pct: Number(form.inflation_pct || 6),
      }, { withCredentials: true });
      toast.success("Financial snapshot saved");
      onSaved?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to save snapshot");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="snapshot-wizard">
        <DialogHeader>
          <DialogTitle>Financial snapshot</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <p className="text-xs text-slate-600 dark:text-slate-400">
            One-time. Powers every goal recommendation — risk profile + allocation + SIP math all derive from these fields.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Age</Label>
              <Input type="number" value={form.age} onChange={e => update("age", e.target.value)} data-testid="snap-age" />
            </div>
            <div>
              <Label className="text-xs">Dependents</Label>
              <Input type="number" value={form.dependents} onChange={e => update("dependents", e.target.value)} data-testid="snap-dependents" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Monthly income (₹)</Label>
              <Input type="number" value={form.monthly_income_rs} onChange={e => update("monthly_income_rs", e.target.value)} data-testid="snap-income" />
            </div>
            <div>
              <Label className="text-xs">Monthly expenses (₹)</Label>
              <Input type="number" value={form.monthly_expenses_rs} onChange={e => update("monthly_expenses_rs", e.target.value)} data-testid="snap-expenses" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Current corpus (₹)</Label>
              <Input type="number" value={form.current_corpus_rs} onChange={e => update("current_corpus_rs", e.target.value)} data-testid="snap-corpus" />
            </div>
            <div>
              <Label className="text-xs">Liabilities (₹)</Label>
              <Input type="number" value={form.total_liabilities_rs} onChange={e => update("total_liabilities_rs", e.target.value)} data-testid="snap-liab" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Risk profile</Label>
              <Select value={form.risk_profile} onValueChange={v => update("risk_profile", v)}>
                <SelectTrigger data-testid="snap-risk"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="conservative">Conservative</SelectItem>
                  <SelectItem value="moderate">Moderate</SelectItem>
                  <SelectItem value="aggressive">Aggressive</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Inflation assumption (%)</Label>
              <Input type="number" step="0.5" value={form.inflation_pct} onChange={e => update("inflation_pct", e.target.value)} data-testid="snap-inflation" />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700" data-testid="snap-save">
            {saving ? "Saving…" : "Save snapshot"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
