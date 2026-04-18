import React, { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Slider } from "@/components/ui/slider";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Sliders, Play } from "lucide-react";

const CustomScenarioBuilder = ({ open, onOpenChange, onRun, running }) => {
  const [equity, setEquity] = useState(70);
  const [debt, setDebt] = useState(20);
  const [gold, setGold] = useState(10);
  const [amcCap, setAmcCap] = useState(25);
  const [stockCap, setStockCap] = useState(5);

  // Normalize equity/debt/gold to sum to 100 when user drags one
  const handleEquity = (v) => {
    const newEq = v[0];
    const diff = newEq - equity;
    // Subtract from debt first, then gold
    let newDebt = Math.max(0, debt - diff);
    let leftover = debt - diff - newDebt;
    let newGold = Math.max(0, gold - leftover);
    setEquity(newEq);
    setDebt(newDebt);
    setGold(newGold);
  };
  const handleDebt = (v) => {
    const newDebt = v[0];
    const diff = newDebt - debt;
    let newGold = Math.max(0, gold - diff);
    let leftover = gold - diff - newGold;
    let newEq = Math.max(0, equity - leftover);
    setDebt(newDebt);
    setGold(newGold);
    setEquity(newEq);
  };
  const handleGold = (v) => {
    const newGold = v[0];
    const diff = newGold - gold;
    let newEq = Math.max(0, equity - diff);
    let leftover = equity - diff - newEq;
    let newDebt = Math.max(0, debt - leftover);
    setGold(newGold);
    setEquity(newEq);
    setDebt(newDebt);
  };

  const total = equity + debt + gold;

  const handleRun = () => {
    onRun({
      scenario_id: "custom",
      target_equity: equity,
      target_debt: debt,
      target_gold: gold,
      target_amc_cap: amcCap,
      target_max_stock: stockCap,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg rounded-2xl max-h-[90vh] overflow-y-auto" data-testid="custom-scenario-builder">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sliders className="w-5 h-5 text-teal-600" />
            Custom Scenario Builder
          </DialogTitle>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Tweak allocation targets and concentration limits, then simulate.
          </p>
        </DialogHeader>

        <div className="space-y-5 py-2">
          {/* Equity slider */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <Label className="text-sm font-medium text-slate-700 dark:text-slate-300">Equity</Label>
              <span className="text-sm font-semibold text-blue-600 dark:text-blue-400" data-testid="custom-equity-value">
                {equity}%
              </span>
            </div>
            <Slider
              data-testid="custom-equity-slider"
              value={[equity]}
              min={0}
              max={100}
              step={5}
              onValueChange={handleEquity}
              className="[&_[role=slider]]:bg-blue-600 [&_[role=slider]]:border-blue-600 [&>span>span]:bg-blue-500"
            />
          </div>

          {/* Debt slider */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <Label className="text-sm font-medium text-slate-700 dark:text-slate-300">Debt</Label>
              <span className="text-sm font-semibold text-emerald-600 dark:text-emerald-400" data-testid="custom-debt-value">
                {debt}%
              </span>
            </div>
            <Slider
              data-testid="custom-debt-slider"
              value={[debt]}
              min={0}
              max={100}
              step={5}
              onValueChange={handleDebt}
              className="[&_[role=slider]]:bg-emerald-600 [&_[role=slider]]:border-emerald-600 [&>span>span]:bg-emerald-500"
            />
          </div>

          {/* Gold slider */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <Label className="text-sm font-medium text-slate-700 dark:text-slate-300">Gold</Label>
              <span className="text-sm font-semibold text-amber-600 dark:text-amber-400" data-testid="custom-gold-value">
                {gold}%
              </span>
            </div>
            <Slider
              data-testid="custom-gold-slider"
              value={[gold]}
              min={0}
              max={30}
              step={5}
              onValueChange={handleGold}
              className="[&_[role=slider]]:bg-amber-600 [&_[role=slider]]:border-amber-600 [&>span>span]:bg-amber-500"
            />
          </div>

          <div className={`text-xs text-center p-2 rounded-lg ${total === 100 ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400" : "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400"}`}>
            Total: {total}% {total !== 100 && "(should sum to 100%)"}
          </div>

          <div className="pt-3 border-t border-slate-100 dark:border-slate-800 space-y-4">
            <div>
              <Label htmlFor="amc-cap" className="text-sm font-medium text-slate-700 dark:text-slate-300">
                Max AMC Concentration: <span className="font-semibold">{amcCap}%</span>
              </Label>
              <Slider
                data-testid="custom-amc-slider"
                value={[amcCap]}
                min={10}
                max={50}
                step={5}
                onValueChange={(v) => setAmcCap(v[0])}
                className="mt-2"
              />
            </div>
            <div>
              <Label htmlFor="stock-cap" className="text-sm font-medium text-slate-700 dark:text-slate-300">
                Max Single Stock Exposure: <span className="font-semibold">{stockCap}%</span>
              </Label>
              <Slider
                data-testid="custom-stock-slider"
                value={[stockCap]}
                min={1}
                max={15}
                step={1}
                onValueChange={(v) => setStockCap(v[0])}
                className="mt-2"
              />
            </div>
          </div>
        </div>

        <DialogFooter className="flex-col sm:flex-row gap-2">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            className="rounded-xl w-full sm:w-auto"
            data-testid="custom-cancel-btn"
          >
            Cancel
          </Button>
          <Button
            data-testid="custom-run-btn"
            onClick={handleRun}
            disabled={running || total !== 100}
            className="bg-teal-600 hover:bg-teal-700 text-white rounded-xl w-full sm:w-auto"
          >
            <Play className="w-4 h-4 mr-2" />
            {running ? "Simulating…" : "Run Simulation"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default CustomScenarioBuilder;
