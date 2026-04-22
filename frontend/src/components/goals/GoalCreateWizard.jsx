import React, { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const TYPE_PRESETS = {
  retirement: { name: "Retirement corpus", target: 20000000, years: 20 },
  education:  { name: "Child's education", target: 5000000, years: 15 },
  home:       { name: "Home purchase", target: 10000000, years: 7 },
  wealth:     { name: "Wealth build-up", target: 10000000, years: 15 },
  custom:     { name: "", target: 0, years: 10 },
};

export default function GoalWizard({ open, onOpenChange, onCreated }) {
  const [step, setStep] = useState(1);
  const [form, setForm] = useState({
    goal_type: "retirement",
    goal_name: TYPE_PRESETS.retirement.name,
    target_amount_rs: TYPE_PRESETS.retirement.target,
    horizon_years: TYPE_PRESETS.retirement.years,
    priority: "high",
    current_corpus_rs: 0,
    monthly_sip_rs: 10000,
  });
  const [saving, setSaving] = useState(false);

  const update = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const applyType = (type) => {
    const p = TYPE_PRESETS[type];
    setForm(f => ({
      ...f,
      goal_type: type,
      goal_name: p.name || f.goal_name,
      target_amount_rs: p.target || f.target_amount_rs,
      horizon_years: p.years || f.horizon_years,
    }));
  };

  const submit = async () => {
    setSaving(true);
    try {
      const payload = {
        ...form,
        target_amount_rs: Number(form.target_amount_rs),
        horizon_years: Number(form.horizon_years),
        current_corpus_rs: Number(form.current_corpus_rs || 0),
        monthly_sip_rs: Number(form.monthly_sip_rs || 0),
      };
      await axios.post(`${API}/goals`, payload, { withCredentials: true });
      toast.success("Goal created — simulation running");
      onCreated?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to create goal");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="goal-wizard">
        <DialogHeader>
          <DialogTitle>Create a goal · step {step} / 3</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          {step === 1 && (
            <>
              <div>
                <Label className="text-xs">Goal type</Label>
                <Select value={form.goal_type} onValueChange={v => { update("goal_type", v); applyType(v); }}>
                  <SelectTrigger data-testid="gw-type"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="retirement">Retirement</SelectItem>
                    <SelectItem value="education">Child's education</SelectItem>
                    <SelectItem value="home">Home purchase</SelectItem>
                    <SelectItem value="wealth">Wealth build-up</SelectItem>
                    <SelectItem value="custom">Custom</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs">Goal name</Label>
                <Input value={form.goal_name} onChange={e => update("goal_name", e.target.value)} data-testid="gw-name" />
              </div>
              <div>
                <Label className="text-xs">Priority</Label>
                <Select value={form.priority} onValueChange={v => update("priority", v)}>
                  <SelectTrigger data-testid="gw-priority"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="high">High</SelectItem>
                    <SelectItem value="medium">Medium</SelectItem>
                    <SelectItem value="low">Low</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </>
          )}
          {step === 2 && (
            <>
              <div>
                <Label className="text-xs">Target amount (in today's rupees)</Label>
                <Input type="number" value={form.target_amount_rs} onChange={e => update("target_amount_rs", e.target.value)} data-testid="gw-target" />
                <div className="text-[10px] text-slate-500 mt-1">Example: ₹20,00,000 = 20 lakh · ₹2,00,00,000 = 2 Cr</div>
              </div>
              <div>
                <Label className="text-xs">Horizon (years until you need it)</Label>
                <Input type="number" value={form.horizon_years} onChange={e => update("horizon_years", e.target.value)} data-testid="gw-horizon" />
              </div>
            </>
          )}
          {step === 3 && (
            <>
              <div>
                <Label className="text-xs">Already saved for this goal (₹)</Label>
                <Input type="number" value={form.current_corpus_rs} onChange={e => update("current_corpus_rs", e.target.value)} data-testid="gw-corpus" />
              </div>
              <div>
                <Label className="text-xs">Monthly SIP you can commit (₹)</Label>
                <Input type="number" value={form.monthly_sip_rs} onChange={e => update("monthly_sip_rs", e.target.value)} data-testid="gw-sip" />
                <div className="text-[10px] text-slate-500 mt-1">
                  We'll check if this is enough to hit your target. If not, we'll recommend an increase.
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 p-3 text-xs">
                <div className="font-semibold mb-1">Review</div>
                <div>Type: <b>{form.goal_type}</b></div>
                <div>Name: <b>{form.goal_name}</b></div>
                <div>Target: <b>₹{Number(form.target_amount_rs).toLocaleString("en-IN")}</b> in <b>{form.horizon_years}y</b></div>
                <div>SIP: <b>₹{Number(form.monthly_sip_rs).toLocaleString("en-IN")}/mo</b> · existing corpus: <b>₹{Number(form.current_corpus_rs).toLocaleString("en-IN")}</b></div>
              </div>
            </>
          )}
        </div>
        <DialogFooter className="flex items-center justify-between">
          <Button variant="outline" onClick={() => step > 1 ? setStep(step - 1) : onOpenChange(false)} data-testid="gw-back">
            {step > 1 ? "Back" : "Cancel"}
          </Button>
          {step < 3 ? (
            <Button onClick={() => setStep(step + 1)} className="bg-emerald-600 hover:bg-emerald-700" data-testid="gw-next">
              Next →
            </Button>
          ) : (
            <Button onClick={submit} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700" data-testid="gw-submit">
              {saving ? "Creating…" : "Create goal"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
