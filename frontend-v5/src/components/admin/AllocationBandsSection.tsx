import { useState } from "react";
import { RotateCcw, Save, RefreshCw, Loader2, TrendingUp } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { useToastStore } from "@/stores/toast.store";
import { useQuery, useQueryClient } from "@tanstack/react-query";

const TIERS = ["conservative", "moderate", "balanced", "growth", "aggressive"] as const;
const ASSETS = ["equity", "debt", "gold", "cash"] as const;
type Tier = typeof TIERS[number];
type Asset = typeof ASSETS[number];

const TIER_TONES: Record<Tier, "good" | "accent" | "default" | "warm" | "neg"> = {
  conservative: "accent",
  moderate:     "good",
  balanced:     "default",
  growth:       "warm",
  aggressive:   "neg",
};

interface Band { min: number; target: number; max: number; }
type BandsConfig = Record<Tier, Record<Asset, Band>>;

interface BandsResponse {
  bands: BandsConfig;
  defaults: BandsConfig;
}

function BandInput({
  value,
  field,
  onChange,
}: {
  value: number;
  field: "min" | "target" | "max";
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="text-[9px] uppercase tracking-wider text-ink-3">{field}</span>
      <input
        type="number"
        min={0}
        max={100}
        step={0.5}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-14 rounded border border-hairline-2 bg-bg px-1.5 py-0.5 text-xs text-center font-mono text-ink focus:outline-none focus:ring-1 focus:ring-accent"
      />
    </div>
  );
}

export function AllocationBandsSection() {
  const push = useToastStore((s) => s.push);
  const qc = useQueryClient();
  const [edits, setEdits] = useState<Partial<BandsConfig>>({});
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

  const { data, isFetching, refetch } = useQuery({
    queryKey: ["admin", "allocation-bands"],
    queryFn: () =>
      http<BandsResponse>({ path: "/api/admin/allocation-bands" })
        .then((r) => r.data)
        .catch(() => null),
  });

  const bands: BandsConfig = {
    ...((data?.bands ?? {}) as BandsConfig),
    ...edits,
  } as BandsConfig;

  const hasEdits = Object.keys(edits).length > 0;

  function setBand(tier: Tier, asset: Asset, field: "min" | "target" | "max", val: number) {
    setEdits((prev) => ({
      ...prev,
      [tier]: {
        ...(bands[tier] ?? {}),
        ...(prev[tier] ?? {}),
        [asset]: {
          ...(bands[tier]?.[asset] ?? { min: 0, target: 0, max: 0 }),
          ...(prev[tier]?.[asset] ?? {}),
          [field]: val,
        },
      },
    }));
  }

  async function save() {
    setSaving(true);
    try {
      await http({ method: "PUT", path: "/api/admin/allocation-bands", body: { bands } });
      push({ kind: "success", title: "Allocation bands saved" });
      setEdits({});
      qc.invalidateQueries({ queryKey: ["admin", "allocation-bands"] });
    } catch {
      push({ kind: "error", title: "Failed to save allocation bands" });
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    setResetting(true);
    try {
      await http({ method: "POST", path: "/api/admin/allocation-bands/reset" });
      push({ kind: "success", title: "Allocation bands reset to defaults" });
      setEdits({});
      qc.invalidateQueries({ queryKey: ["admin", "allocation-bands"] });
    } catch {
      push({ kind: "error", title: "Failed to reset allocation bands" });
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-5">
            <div>
              <CardLabel>Canonical Allocation Bands</CardLabel>
              <p className="text-[12px] text-ink-3 mt-1">
                Single source of truth for portfolio target allocation. Changes take effect immediately — no deploy required.
              </p>
            </div>
            <div className="flex gap-2 shrink-0">
              {hasEdits && (
                <Button size="sm" onClick={save} disabled={saving}>
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />} Save
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={reset} disabled={resetting}>
                {resetting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />} Reset
              </Button>
              <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
                {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              </Button>
            </div>
          </div>

          {!data && isFetching && (
            <div className="flex items-center justify-center py-10 text-ink-3">
              <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading…
            </div>
          )}

          {data && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr>
                    <th className="text-left text-[11px] uppercase tracking-wider text-ink-3 pb-3 pr-4 font-medium w-20">Asset</th>
                    {TIERS.map((tier) => (
                      <th key={tier} className="pb-3 px-2 text-center">
                        <Badge tone={TIER_TONES[tier]} className="capitalize">
                          <TrendingUp className="w-3 h-3" /> {tier}
                        </Badge>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ASSETS.map((asset) => (
                    <tr key={asset} className="border-t border-hairline">
                      <td className="py-3 pr-4 text-xs font-mono text-ink-2 capitalize">{asset}</td>
                      {TIERS.map((tier) => {
                        const b = bands[tier]?.[asset] ?? { min: 0, target: 0, max: 0 };
                        const def = data.defaults[tier]?.[asset];
                        const isDirty =
                          edits[tier]?.[asset] !== undefined &&
                          (edits[tier]![asset]!.min !== def?.min ||
                           edits[tier]![asset]!.target !== def?.target ||
                           edits[tier]![asset]!.max !== def?.max);
                        return (
                          <td key={tier} className={`py-3 px-2 text-center ${isDirty ? "bg-accent/5 rounded" : ""}`}>
                            <div className="flex items-end gap-1 justify-center">
                              <BandInput value={b.min} field="min" onChange={(v) => setBand(tier, asset, "min", v)} />
                              <span className="text-ink-3 text-xs pb-1">–</span>
                              <BandInput value={b.target} field="target" onChange={(v) => setBand(tier, asset, "target", v)} />
                              <span className="text-ink-3 text-xs pb-1">–</span>
                              <BandInput value={b.max} field="max" onChange={(v) => setBand(tier, asset, "max", v)} />
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-[11px] text-ink-3 mt-3">
                Each cell: <span className="font-mono">min – target – max</span> (%). Target is the base allocation point; min/max define the no-rebalance band.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
