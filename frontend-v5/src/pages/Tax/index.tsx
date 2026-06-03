/**
 * Tax dashboard — wired to GET /api/dashboards/tax
 * Design: timeline stack chart + harvest lots + tax breakdown
 */
import { useDashboard } from "@/hooks/use-dashboards";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";

function toneCls(tone?: string) {
  if (tone === "good") return "text-pos";
  if (tone === "warm") return "text-warm";
  if (tone === "neg") return "text-neg";
  if (tone === "info") return "text-accent";
  return "text-ink";
}

/** Tax timeline stack chart (gains above axis, losses below) */
function TaxTimeline({ projection }: { projection: unknown }) {
  const data = projection as {
    months?: Array<{ label: string; gains: number; losses: number; highlighted?: boolean }>;
  } | null;
  if (!data?.months?.length) return null;

  const { months } = data;
  const maxGain = Math.max(...months.map((m) => m.gains), 1);
  const maxLoss = Math.max(...months.map((m) => Math.abs(m.losses)), 1);
  const maxVal = Math.max(maxGain, maxLoss);

  const W = 640, H = 240;
  const pad = { t: 20, r: 20, b: 30, l: 50 };
  const iW = W - pad.l - pad.r, iH = H - pad.t - pad.b;
  const midY = pad.t + iH / 2;
  const barW = iW / months.length - 4;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 240 }}>
      {/* zero line */}
      <line x1={pad.l} y1={midY} x2={W - pad.r} y2={midY} stroke="var(--color-ink-4)" strokeWidth={0.5} opacity={0.4} />

      {/* y labels */}
      <text x={pad.l - 8} y={pad.t + 10} textAnchor="end" fontSize={9} fontFamily="var(--font-mono)" fill="var(--color-ink-3)">
        ₹{(maxVal / 1_00_000).toFixed(0)}L
      </text>
      <text x={pad.l - 8} y={H - pad.b - 4} textAnchor="end" fontSize={9} fontFamily="var(--font-mono)" fill="var(--color-ink-3)">
        -₹{(maxVal / 1_00_000).toFixed(0)}L
      </text>

      {months.map((m, i) => {
        const x = pad.l + (i * iW) / months.length + 2;
        const gainH = (m.gains / maxVal) * (iH / 2);
        const lossH = (Math.abs(m.losses) / maxVal) * (iH / 2);
        return (
          <g key={m.label}>
            {/* gain bar above */}
            {gainH > 0 && (
              <rect x={x} y={midY - gainH} width={barW} height={gainH} rx={2} fill="var(--color-warm)" opacity={0.8} />
            )}
            {/* loss bar below */}
            {lossH > 0 && (
              <rect x={x} y={midY} width={barW} height={lossH} rx={2} fill="var(--color-pos)" opacity={0.7} />
            )}
            {/* month label */}
            <text x={x + barW / 2} y={H - 8} textAnchor="middle" fontSize={9} fontFamily="var(--font-mono)" fill={m.highlighted ? "var(--color-warm)" : "var(--color-ink-3)"}>
              {m.label}
            </text>
            {/* highlight marker */}
            {m.highlighted && (
              <rect x={x - 1} y={pad.t} width={barW + 2} height={iH} rx={3} fill="var(--color-warm)" opacity={0.06} />
            )}
          </g>
        );
      })}

      {/* legend */}
      <rect x={W - 180} y={6} width={8} height={8} rx={1.5} fill="var(--color-warm)" opacity={0.8} />
      <text x={W - 168} y={14} fontSize={9} fontFamily="var(--font-mono)" fill="var(--color-ink-3)">Gains booked</text>
      <rect x={W - 90} y={6} width={8} height={8} rx={1.5} fill="var(--color-pos)" opacity={0.7} />
      <text x={W - 78} y={14} fontSize={9} fontFamily="var(--font-mono)" fill="var(--color-ink-3)">Losses avail.</text>
    </svg>
  );
}

export default function TaxPage() {
  const dash = useDashboard("tax");

  if (dash.isPending) {
    return <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full"><LoadingSkeleton variant="card" /></div>;
  }
  if (dash.isError) {
    return <ErrorState onRetry={() => dash.refetch()} error={dash.error} />;
  }

  const env = dash.data;
  const breakdown = env?.breakdown as Array<{ label: string; value: string; rate: string; tax: string; tone?: string }> | null;
  const harvestLots = (env as any)?.harvest_lots as Array<{ name: string; loss: number; ticker?: string }> | null;
  const netSaved = (env as any)?.net_saved as number | null;

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
          <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Dashboard · tax</div>
          <h1 className="font-display text-[38px] tracking-tightish leading-[1.05] mt-1">
            {insightText ?? "Your tax picture, plain and simple."}
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

      {/* main grid: timeline + harvest panel */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-5">
        {/* timeline chart */}
        <Card className="p-5">
          <CardLabel>Tax timeline · FY {new Date().getFullYear().toString().slice(2)}–{(new Date().getFullYear() + 1).toString().slice(2)}</CardLabel>
          {env?.projection ? (
            <div className="mt-3">
              <TaxTimeline projection={env.projection} />
            </div>
          ) : (
            <div className="h-[180px] flex items-center justify-center text-ink-3 font-mono text-[12px]">
              Timeline will appear once gains/losses are computed.
            </div>
          )}
        </Card>

        {/* harvest plan */}
        <Card className="p-5">
          <div className="flex items-center mb-3">
            <CardLabel>Harvest plan</CardLabel>
            <Badge tone="accent" className="ml-auto text-[9px]">{harvestLots?.length ?? 0} lots flagged</Badge>
          </div>
          {harvestLots && harvestLots.length > 0 ? (
            <>
              <div className="space-y-2">
                {harvestLots.map((lot) => (
                  <div key={lot.name} className="flex items-center gap-3 py-2 border-b border-hairline/50 last:border-0">
                    <span className="w-1.5 self-stretch rounded-sm bg-pos" />
                    <div className="flex-1">
                      <div className="text-[14px] font-medium">{lot.name}</div>
                      {lot.ticker && <div className="font-mono text-[10px] text-ink-3">{lot.ticker}</div>}
                    </div>
                    <span className="font-mono text-[13px] text-neg">
                      -₹{Math.abs(lot.loss).toLocaleString("en-IN")}
                    </span>
                  </div>
                ))}
              </div>
              {netSaved != null && (
                <div className="mt-4 rounded-md bg-surface-2 p-3 text-center">
                  <div className="font-mono text-[9px] text-ink-3 uppercase tracking-widest">Net you save</div>
                  <div className="font-display text-2xl text-pos mt-1">₹{netSaved.toLocaleString("en-IN")}</div>
                </div>
              )}
              <button className="mt-4 w-full rounded-lg bg-accent text-on-accent font-medium text-[13px] py-2.5 hover:opacity-90 transition-opacity">
                Schedule harvest →
              </button>
            </>
          ) : (
            <div className="py-8 text-center font-mono text-[12px] text-ink-3">
              No lots flagged yet.
            </div>
          )}
        </Card>
      </div>

      {/* Tax breakdown grid */}
      {breakdown && breakdown.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-5">
          {breakdown.map((row) => (
            <Card key={row.label} className="p-4">
              <div className="font-mono text-[10px] uppercase tracking-[.10em] text-ink-3">{row.label}</div>
              <div className={`font-display text-xl mt-1 ${toneCls(row.tone)}`}>{row.value}</div>
              <div className="font-mono text-[10px] text-ink-3 mt-1">{row.rate} · {row.tax}</div>
            </Card>
          ))}
        </div>
      )}

      {/* recs from envelope */}
      {env?.recommendations && env.recommendations.length > 0 && (
        <Card className="mt-4 p-5">
          <CardLabel>Suggested moves</CardLabel>
          <div className="mt-3 space-y-2">
            {env.recommendations.map((r) => (
              <div key={r.id} className="flex items-center gap-3 py-2 border-b border-hairline/50 last:border-0">
                <span className="w-1.5 self-stretch rounded-sm bg-pos" />
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
