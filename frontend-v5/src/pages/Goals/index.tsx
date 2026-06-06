/**
 * Goals dashboard — wired to GET /api/dashboards/goals
 * Design: fan trajectory chart + drill panel + goal table
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useDashboard } from "@/hooks/use-dashboards";
import { useGoals, useGoalWhatIf } from "@/hooks/use-goals";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { ProfileWizardModal } from "@/pages/Dashboard/ProfileWizardModal";
import type { WhatIfRes } from "@/services/contracts/goal.contract";

function formatRs(paise: number) {
  const rs = Math.abs(paise) / 100;
  const sign = paise < 0 ? "-" : "";
  if (rs >= 1_00_00_000) return `${sign}₹${(rs / 1_00_00_000).toFixed(1)} Cr`;
  if (rs >= 1_00_000) return `${sign}₹${(rs / 1_00_000).toFixed(1)} L`;
  if (rs >= 1_000) return `${sign}₹${(rs / 1_000).toFixed(1)}k`;
  return `${sign}₹${rs.toLocaleString("en-IN")}`;
}

function toneCls(tone?: string) {
  if (tone === "good") return "text-pos";
  if (tone === "warm") return "text-warm";
  if (tone === "neg") return "text-neg";
  if (tone === "info") return "text-accent";
  return "text-ink";
}

function badgeTone(tone?: string): "good" | "warm" | "neg" | "accent" | "default" {
  if (tone === "good") return "good";
  if (tone === "warm") return "warm";
  if (tone === "neg") return "neg";
  if (tone === "info") return "accent";
  return "default";
}

/** Simple SVG fan trajectory chart */
function GoalTrajectory({ projection }: { projection: unknown }) {
  const proj = projection as {
    years?: number[];
    median?: number[];
    band_68_lo?: number[];
    band_68_hi?: number[];
    band_95_lo?: number[];
    band_95_hi?: number[];
    required?: number[];
    goals?: Array<{ year: number; label: string; amount: number; on_track: boolean }>;
  } | null;
  if (!proj?.years?.length || !proj.median?.length) return null;

  const { years, median, band_68_lo, band_68_hi, band_95_lo, band_95_hi, required, goals: markers } = proj;
  const W = 640, H = 280, pad = { t: 20, r: 20, b: 40, l: 60 };
  const iW = W - pad.l - pad.r, iH = H - pad.t - pad.b;

  const allVals = [
    ...(band_95_hi ?? band_68_hi ?? median),
    ...(band_95_lo ?? band_68_lo ?? median),
    ...(required ?? []),
  ];
  const maxV = Math.max(...allVals) * 1.1;
  const minV = 0;

  const xScale = (i: number) => pad.l + (i / (years.length - 1)) * iW;
  const yScale = (v: number) => pad.t + iH - ((v - minV) / (maxV - minV)) * iH;
  const toPath = (vals: number[]) => vals.map((v, i) => `${i === 0 ? "M" : "L"}${xScale(i)},${yScale(v)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 280 }}>
      {/* grid lines */}
      {[0, 0.25, 0.5, 0.75, 1].map((f) => {
        const y = pad.t + iH * (1 - f);
        const val = minV + (maxV - minV) * f;
        return (
          <g key={f}>
            <line x1={pad.l} y1={y} x2={W - pad.r} y2={y} stroke="var(--color-ink-4)" strokeWidth={0.5} opacity={0.3} />
            <text x={pad.l - 8} y={y + 3} textAnchor="end" fontSize={9} fontFamily="var(--font-mono)" fill="var(--color-ink-3)">
              ₹{(val / 1_00_00_000).toFixed(1)}Cr
            </text>
          </g>
        );
      })}

      {/* 95% band */}
      {band_95_lo && band_95_hi && (
        <path
          d={toPath(band_95_hi) + " " + [...band_95_lo].reverse().map((v, i) => `L${xScale(years.length - 1 - i)},${yScale(v)}`).join(" ") + " Z"}
          fill="var(--color-pos)" opacity={0.06}
        />
      )}

      {/* 68% band */}
      {band_68_lo && band_68_hi && (
        <path
          d={toPath(band_68_hi) + " " + [...band_68_lo].reverse().map((v, i) => `L${xScale(years.length - 1 - i)},${yScale(v)}`).join(" ") + " Z"}
          fill="var(--color-pos)" opacity={0.12}
        />
      )}

      {/* required line */}
      {required && <path d={toPath(required)} fill="none" stroke="var(--color-ink-3)" strokeWidth={1.5} strokeDasharray="6 4" />}

      {/* median line */}
      <path d={toPath(median)} fill="none" stroke="var(--color-pos)" strokeWidth={2.5} />

      {/* goal markers */}
      {markers?.map((g) => {
        const idx = years.indexOf(g.year);
        if (idx < 0) return null;
        const x = xScale(idx);
        const y = yScale(g.amount);
        return (
          <g key={g.label}>
            <circle cx={x} cy={y} r={5} fill={g.on_track ? "var(--color-pos)" : "var(--color-warm)"} stroke="var(--color-bg)" strokeWidth={2} />
            <text x={x} y={y - 12} textAnchor="middle" fontSize={10} fontFamily="var(--font-mono)" fill={g.on_track ? "var(--color-pos)" : "var(--color-warm)"}>
              {g.label}
            </text>
          </g>
        );
      })}

      {/* x-axis years */}
      {years.filter((_, i) => i % Math.max(1, Math.floor(years.length / 6)) === 0 || i === years.length - 1).map((yr, _, arr) => {
        const idx = years.indexOf(yr);
        return (
          <text key={yr} x={xScale(idx)} y={H - 8} textAnchor="middle" fontSize={10} fontFamily="var(--font-mono)" fill="var(--color-ink-3)">
            {yr}
          </text>
        );
      })}
    </svg>
  );
}

// ── Simulate what-if panel ────────────────────────────────────────────────────

function SimulatePanel({ goal }: { goal: { id: string; monthlySip: number; targetAmount: number; progress: number } }) {
  const whatIf = useGoalWhatIf();
  const [sipDelta, setSipDelta] = useState(0);   // ₹ offset from current SIP
  const [result, setResult] = useState<WhatIfRes | null>(null);

  const baseSipRs = goal.monthlySip / 100;       // paise → ₹
  const newSipRs  = Math.max(0, baseSipRs + sipDelta);

  async function simulate() {
    const res = await whatIf.mutateAsync({
      goalId: goal.id,
      body: { monthly_sip_rs: newSipRs },
    });
    setResult(res);
  }

  const deltaLabel = sipDelta >= 0 ? `+₹${sipDelta.toLocaleString("en-IN")}` : `-₹${Math.abs(sipDelta).toLocaleString("en-IN")}`;

  return (
    <div className="mt-4 rounded-lg border border-hairline bg-surface-2 p-3">
      <div className="font-mono text-[9px] uppercase tracking-[.14em] text-ink-3 mb-3">What if I change my SIP?</div>
      <div className="flex items-center gap-3 mb-3">
        <input
          type="range"
          min={-Math.round(baseSipRs * 0.5)}
          max={Math.round(baseSipRs * 2)}
          step={500}
          value={sipDelta}
          onChange={e => { setSipDelta(Number(e.target.value)); setResult(null); }}
          className="flex-1 accent-accent"
        />
        <span className="font-mono text-[11px] text-ink-2 shrink-0 w-20 text-right">{deltaLabel}/mo</span>
      </div>
      <div className="font-mono text-[10px] text-ink-3 mb-3">
        New SIP: ₹{Math.round(newSipRs).toLocaleString("en-IN")}/mo
      </div>
      <button
        onClick={simulate}
        disabled={whatIf.isPending}
        className="w-full py-2 rounded-md bg-accent text-on-accent text-[12px] font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
      >
        {whatIf.isPending ? "Simulating…" : "Run simulation"}
      </button>
      {result && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-md bg-surface-1 p-2 text-center">
            <div className="font-mono text-[9px] text-ink-3 uppercase tracking-widest">Current</div>
            <div className={`font-display text-[18px] mt-0.5 ${result.current_on_track_pct >= 70 ? "text-pos" : "text-warm"}`}>
              {Math.round(result.current_on_track_pct)}%
            </div>
          </div>
          <div className="rounded-md bg-surface-1 p-2 text-center">
            <div className="font-mono text-[9px] text-ink-3 uppercase tracking-widest">With change</div>
            <div className={`font-display text-[18px] mt-0.5 ${result.what_if_on_track_pct >= 70 ? "text-pos" : "text-warm"}`}>
              {Math.round(result.what_if_on_track_pct)}%
            </div>
          </div>
        </div>
      )}
      {result?.verdict && (
        <p className="mt-2 text-[11px] text-ink-2 leading-relaxed">{result.verdict}</p>
      )}
      {whatIf.isError && (
        <p className="mt-2 text-[11px] text-neg">Simulation failed — try again.</p>
      )}
    </div>
  );
}

export default function GoalsPage() {
  const dash = useDashboard("goals");
  const goalsQ = useGoals();
  const qc = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [simulateOpen, setSimulateOpen] = useState(false);

  if (dash.isPending || goalsQ.isLoading) {
    return <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full"><LoadingSkeleton variant="card" /></div>;
  }
  if (dash.isError) {
    return <ErrorState onRetry={() => dash.refetch()} error={dash.error} />;
  }

  const env = dash.data;
  const goals = goalsQ.data?.goals ?? [];
  const totals = goalsQ.data?.totals;

  const badgeText = typeof env?.badge === "object" ? env.badge.label : env?.badge;
  const insightText = typeof env?.insight === "object" ? env.insight.headline : env?.insight;
  const badgeToneRaw = typeof env?.badge === "object" ? env.badge.tone : undefined;

  const sevBadge = badgeToneRaw ?? (badgeText?.toLowerCase().includes("healthy") ? "good"
    : badgeText?.toLowerCase().includes("watch") ? "warm"
    : badgeText?.toLowerCase().includes("attention") ? "neg" : "accent");

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1200px] mx-auto w-full">
      {/* header */}
      <div className="flex items-start gap-4 mb-5">
        <div className="flex-1">
          <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Dashboard · goals</div>
          <h1 className="font-display text-[38px] tracking-tightish leading-[1.05] mt-1">
            {insightText ?? (totals ? `${totals.onTrack} of ${totals.total} goals on track.` : "Your goals at a glance.")}
          </h1>
        </div>
        {badgeText && (
          <Badge tone={sevBadge as any} className="mt-2 text-[10px]">{badgeText}</Badge>
        )}
      </div>

      {/* KPI strip */}
      {env?.stat_tiles && env.stat_tiles.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          {env.stat_tiles.map((tile) => (
            <div key={tile.label} className="rounded-lg bg-surface-1 border border-hairline p-4">
              <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3">{tile.label}</div>
              <div className={`font-display text-[36px] leading-none tracking-tight mt-1.5 ${toneCls(tile.tone)}`}>
                {tile.value ?? "—"}{tile.unit && <span className="text-[14px] text-ink-3 ml-1">{tile.unit}</span>}
              </div>
              {tile.sub && <div className="font-mono text-[10px] text-ink-3 mt-1 tracking-wide">{tile.sub}</div>}
            </div>
          ))}
        </div>
      )}

      {/* Nearly-achieved banner */}
      {goals.filter(g => g.progress >= 0.9 && g.progress < 1).map(g => (
        <div key={g.id} className="mb-5 rounded-lg border border-[rgba(var(--pos)/0.35)] bg-[rgba(var(--pos)/0.06)] px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-2">
          <span className="text-[15px] shrink-0">{g.icon}</span>
          <div className="flex-1 min-w-0">
            <div className="font-medium text-[13.5px] text-ink">
              {g.name} is {Math.round(g.progress * 100)}% funded — nearly there!
            </div>
            <div className="text-[12px] text-ink-3 mt-0.5">
              Consider shifting to lower-risk funds to lock in your gains before the finish line.
            </div>
          </div>
          <span className="shrink-0 font-mono text-[10px] text-pos bg-[rgba(var(--pos)/0.12)] px-2.5 py-1 rounded-full">De-risk recommended</span>
        </div>
      ))}

      {/* main grid: trajectory chart + drill panel */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-5">
        {/* trajectory chart */}
        <Card className="p-5">
          <CardLabel>Goal trajectory · projected</CardLabel>
          {env?.projection ? (
            <div className="mt-3">
              <GoalTrajectory projection={env.projection} />
            </div>
          ) : (
            <div className="h-[200px] flex items-center justify-center text-ink-3 font-mono text-[12px]">
              No projection data available yet.
            </div>
          )}
        </Card>

        {/* drill panel — first at-risk goal */}
        <Card className="p-5">
          <CardLabel>Focus</CardLabel>
          {goals.length > 0 ? (() => {
            const focus = goals.find((g) => !g.onTrack) ?? goals[0];
            const pct = Math.round(focus.progress * 100);
            return (
              <div className="mt-3">
                <div className="text-[16px] font-medium">{focus.icon} {focus.name}</div>
                <div className="font-mono text-[10px] text-ink-3 mt-1">Target: {formatRs(focus.targetAmount)} · by {focus.targetDate}</div>
                <div className="mt-4 flex items-center gap-3">
                  <div className="text-[13px] font-mono text-ink-3">Funded</div>
                  <div className="flex-1 h-2 bg-surface-3 rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${pct}%`, background: focus.onTrack ? "var(--color-pos)" : "var(--color-warm)" }} />
                  </div>
                  <div className={`font-mono text-[13px] ${focus.onTrack ? "text-pos" : "text-warm"}`}>{pct}%</div>
                </div>
                <div className="grid grid-cols-2 gap-3 mt-4">
                  <div className="rounded-md bg-surface-2 p-3">
                    <div className="font-mono text-[9px] text-ink-3 uppercase tracking-widest">On hand</div>
                    <div className="font-display text-lg mt-0.5">{formatRs(focus.currentAmount)}</div>
                  </div>
                  <div className="rounded-md bg-surface-2 p-3">
                    <div className="font-mono text-[9px] text-ink-3 uppercase tracking-widest">Required</div>
                    <div className="font-display text-lg mt-0.5">{formatRs(focus.targetAmount)}</div>
                  </div>
                  <div className="rounded-md bg-surface-2 p-3">
                    <div className="font-mono text-[9px] text-ink-3 uppercase tracking-widest">Monthly SIP</div>
                    <div className="font-display text-lg mt-0.5">{formatRs(focus.monthlySip)}</div>
                  </div>
                  <div className="rounded-md bg-surface-2 p-3">
                    <div className="font-mono text-[9px] text-ink-3 uppercase tracking-widest">Gap</div>
                    <div className="font-display text-lg mt-0.5 text-warm">{formatRs(Math.max(0, focus.targetAmount - focus.currentAmount))}</div>
                  </div>
                </div>
                {!focus.onTrack && (
                  <button
                    onClick={() => setSimulateOpen(o => !o)}
                    className="mt-4 w-full rounded-lg bg-accent text-on-accent font-medium text-[13px] py-2.5 hover:opacity-90 transition-opacity"
                  >
                    {simulateOpen ? "Hide simulator" : "Simulate fix →"}
                  </button>
                )}
                {simulateOpen && !focus.onTrack && (
                  <SimulatePanel goal={focus} />
                )}
              </div>
            );
          })() : (
            <div className="mt-3 py-8 text-center font-mono text-[12px] text-ink-3">
              No goals found. Add your first goal.
            </div>
          )}
        </Card>
      </div>

      {/* Goal wizard — opened by + Add goal */}
      <ProfileWizardModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        completeness={{ hasRiskProfile: true, hasGoal: goals.length > 0, hasSnapshot: false }}
        startStep={1}
        onComplete={() => {
          setAddOpen(false);
          qc.invalidateQueries({ queryKey: ["goals"] });
          qc.invalidateQueries({ queryKey: ["plans"] });
          dash.refetch();
        }}
      />

      {/* All goals table */}
      <Card className="mt-5 p-5">
        <div className="flex items-center mb-3">
          <CardLabel>All goals</CardLabel>
          <button
            onClick={() => setAddOpen(true)}
            className="ml-auto text-[12px] text-accent hover:underline underline-offset-4"
          >
            + Add goal
          </button>
        </div>
        {goals.length === 0 ? (
          <div className="py-8 text-center font-mono text-[12px] text-ink-3">No goals yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-hairline text-ink-3 font-mono text-[9px] uppercase tracking-widest">
                  <th className="text-left py-2 pr-4">Goal</th>
                  <th className="text-left py-2 pr-4">By</th>
                  <th className="text-right py-2 pr-4">Target</th>
                  <th className="text-right py-2 pr-4">Funded</th>
                  <th className="text-right py-2 pr-4">Monthly SIP</th>
                  <th className="text-right py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {goals.map((g) => {
                  const pct = Math.round(g.progress * 100);
                  return (
                    <tr key={g.id} className="border-b border-hairline/50 hover:bg-surface-1/50 transition-colors">
                      <td className="py-3 pr-4 font-medium">{g.icon} {g.name}</td>
                      <td className="py-3 pr-4 font-mono text-ink-2">{g.targetDate}</td>
                      <td className="py-3 pr-4 text-right font-mono">{formatRs(g.targetAmount)}</td>
                      <td className="py-3 pr-4 text-right">
                        <span className={`font-mono ${g.onTrack ? "text-pos" : "text-warm"}`}>{pct}%</span>
                      </td>
                      <td className="py-3 pr-4 text-right font-mono text-ink-2">{formatRs(g.monthlySip)}/mo</td>
                      <td className="py-3 text-right">
                        <Badge tone={g.progress >= 1 ? "good" : g.onTrack ? "good" : "warm"} className="text-[9px]">
                          {g.progress >= 1 ? "DONE" : g.onTrack ? "ON TRACK" : "BEHIND"}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* recs from envelope */}
      {env?.recommendations && env.recommendations.length > 0 && (
        <Card className="mt-4 p-5">
          <CardLabel>Suggested moves</CardLabel>
          <div className="mt-3 space-y-2">
            {env.recommendations.map((r) => (
              <div key={r.id} className="flex items-center gap-3 py-2 border-b border-hairline/50 last:border-0">
                <span className="w-1.5 self-stretch rounded-sm bg-accent" />
                <div className="flex-1">
                  <div className="text-[14px] font-medium">{r.title}</div>
                  {r.impact && <div className="font-mono text-[10px] text-ink-3 mt-0.5">{r.impact}</div>}
                </div>
                {r.expected_impact && <span className="font-mono text-[12px] text-pos">{r.expected_impact}</span>}
                <span className="text-ink-3">›</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
