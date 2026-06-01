import { Gauge, Shield, Target, ArrowRightLeft, TrendingUp, Activity, RefreshCw, Loader2, Save } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { useToastStore } from "@/stores/toast.store";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

const COMPOSITES = [
  { key: "quality", label: "Quality", icon: Gauge, tone: "good" as const, weights: [
    { k: "Performance (ret_1y/3y/5y vs cat avg)", v: 25 }, { k: "Risk-Adjusted (Sharpe + Sortino)", v: 20 },
    { k: "Consistency (rolling 12m)", v: 20 }, { k: "Drawdown (max_drawdown_pct)", v: 15 },
    { k: "Cost (expense_ratio)", v: 10 }, { k: "AUM / Age", v: 10 },
  ]},
  { key: "health", label: "Health", icon: Activity, tone: "accent" as const, weights: [
    { k: "Manager Tenure", v: 25 }, { k: "AUM Stability", v: 20 }, { k: "Turnover Ratio", v: 15 },
    { k: "Top-10 Concentration", v: 15 }, { k: "Downside Protection", v: 15 }, { k: "Expense Trend", v: 10 },
  ]},
  { key: "exit", label: "Exit", icon: ArrowRightLeft, tone: "neg" as const, weights: [
    { k: "Performance vs cat (1y)", v: 30 }, { k: "Risk-Adjusted score", v: 25 },
    { k: "Consistency score", v: 20 }, { k: "Drawdown severity", v: 15 }, { k: "Cost delta", v: 10 },
  ]},
  { key: "governance", label: "Governance", icon: Shield, tone: "warm" as const, weights: [
    { k: "Regulatory compliance", v: 35 }, { k: "AMC reputation score", v: 25 },
    { k: "Disclosure quality", v: 20 }, { k: "Proxy voting record", v: 20 },
  ]},
  { key: "momentum", label: "Momentum", icon: TrendingUp, tone: "good" as const, weights: [
    { k: "1m return vs cat", v: 25 }, { k: "3m return vs cat", v: 25 },
    { k: "6m relative strength", v: 25 }, { k: "Inflow momentum", v: 25 },
  ]},
  { key: "alignment", label: "Alignment", icon: Target, tone: "accent" as const, weights: [
    { k: "Stated mandate fit", v: 40 }, { k: "Category adherence", v: 30 }, { k: "Benchmark tracking", v: 30 },
  ]},
];

interface RulesConfig {
  [key: string]: number | string | boolean;
}

export function V3EngineSection() {
  const push = useToastStore((s) => s.push);
  const qc = useQueryClient();
  const [editedRules, setEditedRules] = useState<RulesConfig>({});
  const [saving, setSaving] = useState(false);

  const { data: rulesData, isFetching, refetch } = useQuery({
    queryKey: ["admin", "v3-rules"],
    queryFn: () => http<{ rules: RulesConfig }>({ path: "/api/admin/v3/rules" }).then((r) => r.data.rules).catch(() => ({} as RulesConfig)),
  });

  const rules = { ...(rulesData ?? {}), ...editedRules };

  const saveRules = async () => {
    setSaving(true);
    try {
      await http({ method: "PUT", path: "/api/admin/v3/rules", body: editedRules });
      push({ kind: "success", title: "V3 rules saved" });
      setEditedRules({});
      qc.invalidateQueries({ queryKey: ["admin", "v3-rules"] });
    } catch { push({ kind: "error", title: "Failed to save rules" }); }
    finally { setSaving(false); }
  };

  return (
    <div className="space-y-6">
      {/* Composites overview */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <CardLabel>V3 Composite Weights (read-only — mirrored from v3_scoring.py)</CardLabel>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {COMPOSITES.map(({ key, label, icon: Icon, tone, weights }) => (
              <div key={key} className="rounded-lg border border-hairline p-3">
                <div className="flex items-center gap-2 mb-2">
                  <Badge tone={tone}><Icon className="w-3 h-3" /> {label}</Badge>
                </div>
                <div className="space-y-1">
                  {weights.map(({ k, v }) => (
                    <div key={k} className="flex items-center gap-2 text-[11px]">
                      <div className="flex-1 text-ink-3 truncate" title={k}>{k}</div>
                      <div className="flex items-center gap-1 shrink-0">
                        <div className="w-16 h-1.5 bg-surface-2 rounded-full overflow-hidden">
                          <div className="h-full bg-accent rounded-full" style={{ width: `${v}%` }} />
                        </div>
                        <span className="text-ink-2 font-mono w-7 text-right">{v}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Tunable rules */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <CardLabel>Tunable Rule Thresholds</CardLabel>
            <div className="flex gap-2">
              {Object.keys(editedRules).length > 0 && (
                <Button size="sm" onClick={saveRules} disabled={saving}>
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />} Save
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
                {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              </Button>
            </div>
          </div>

          {Object.keys(rules).length === 0 && !isFetching && (
            <div className="text-sm text-ink-3 text-center py-6">No tunable rules found at <code>/api/admin/v3/rules</code>.</div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {Object.entries(rules).map(([key, val]) => (
              <div key={key} className="rounded-lg border border-hairline bg-surface-1 p-3">
                <div className="text-xs font-mono text-ink-3 mb-1">{key}</div>
                <input
                  type={typeof val === "number" ? "number" : "text"}
                  value={String(editedRules[key] ?? val)}
                  onChange={(e) => setEditedRules((r) => ({ ...r, [key]: typeof val === "number" ? Number(e.target.value) : e.target.value }))}
                  className="w-full rounded border border-hairline-2 bg-bg px-2 py-1 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
