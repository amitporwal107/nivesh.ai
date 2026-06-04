import { AlertTriangle, Pencil, UserCircle2 } from "lucide-react";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MetricCard } from "@/components/shared/MetricCard";
import { CapBar } from "@/components/charts/CapBar";
import { formatINR, formatPct } from "@/lib/formatters";
import { TARGET_ALLOCATION, type RiskProfile } from "@/hooks/use-risk-profile";
import type { RiskSnapshot } from "@/types/risk";

const ALLOC_COLOR: Record<string, string> = {
  equity: "bg-[#3B82F6]",
  debt:   "bg-[#10B981]",
  gold:   "bg-[#F59E0B]",
  cash:   "bg-ink-4",
};

interface Props {
  data: RiskSnapshot;
  isAdmin?: boolean;
  onRunPra?: () => void;
  isPraRunning?: boolean;
  profile?: RiskProfile | null;
  profileLoading?: boolean;
  onAmendProfile?: () => void;
}

export function Risk({ data, isAdmin, onRunPra, isPraRunning, profile, profileLoading, onAmendProfile }: Props) {
  const meta = data.meta;
  const showWarning = meta && (!meta.praAvailable || !meta.praRunToday);

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      <div className="flex items-start gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Risk analysis</div>
          <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
            One bad year could cost <span className="text-warm">{formatINR(data.vaR95Paise, { compact: true })}</span>.
          </h1>
          <p className="text-[15.5px] text-ink-2 mt-3 max-w-[600px] leading-relaxed">
            That's the 95th-percentile worst case over 12 months — a 1-in-20 scenario. Likely milder, useful to know.
          </p>
        </div>
        <Badge tone="warm" className="ml-auto shrink-0">ATTENTION</Badge>
      </div>

      {/* PRA staleness / error warning */}
      {showWarning && (
        <div className="mt-5 rounded-xl border border-warm/30 bg-warm/5 px-5 py-4 flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-warm mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-[13.5px] font-medium text-ink-1">
              {!meta.praAvailable ? "Risk data unavailable" : "Risk data may be outdated"}
            </div>
            <div className="text-[12.5px] text-ink-3 mt-0.5">
              {meta.praError
                ? meta.praError
                : meta.praComputedDate
                  ? `PRA engine last ran on ${meta.praComputedDate}. Showing previous results.`
                  : "PRA engine has not run for this user yet."}
            </div>
          </div>
          {isAdmin && onRunPra && (
            <button
              onClick={onRunPra}
              disabled={isPraRunning}
              className="shrink-0 text-[12px] font-medium px-3 py-1.5 rounded-lg border border-warm/40 text-warm hover:bg-warm/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isPraRunning ? "Triggering…" : "Run PRA now"}
            </button>
          )}
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-7">
        <MetricCard label="VaR · 95th · 1Y"
          value={formatPct(-data.vaR95Pct, { signed: true })}
          subtext={`~${formatINR(data.vaR95Paise, { compact: true })}`}
          tone="warm" />
        <MetricCard label="Volatility"
          value={formatPct(data.annualVolPct)}
          subtext={`Bench ${formatPct(data.benchmarkVolPct)}`} />
        <MetricCard label="Max drawdown"
          value={formatPct(data.maxDrawdownPct)}
          subtext="historical worst" tone="accent" />
        <MetricCard label="Beta"
          value={data.beta.toFixed(2)}
          subtext="vs NIFTY 500" />
      </div>

      {/* Risk profile */}
      <Card className="mt-5 p-6">
        <div className="flex items-start justify-between gap-4">
          <CardLabel>Your risk profile</CardLabel>
          {!profileLoading && (
            <button
              onClick={onAmendProfile}
              className="flex items-center gap-1.5 text-[12px] text-ink-3 hover:text-ink transition-colors shrink-0"
            >
              <Pencil className="w-3 h-3" />
              {profile ? "Amend profile" : "Set profile"}
            </button>
          )}
        </div>

        {profileLoading ? (
          <div className="mt-4 h-20 rounded-lg bg-surface-2 animate-pulse" />
        ) : profile ? (
          <div className="mt-4">
            <div className="flex items-baseline gap-3 mb-4">
              <span className="font-display text-2xl">{profile.category}</span>
              <span className="font-mono text-[12px] text-ink-3">Score {profile.score}/100</span>
            </div>
            <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 mb-3">
              Target allocation
            </div>
            <div className="space-y-2.5">
              {(["equity", "debt", "gold", "cash"] as const).map((k) => {
                const alloc = TARGET_ALLOCATION[profile.category];
                return (
                  <div key={k} className="flex items-center gap-3">
                    <span className="font-mono text-[11px] text-ink-3 w-10 uppercase">{k}</span>
                    <div className="relative flex-1 h-1.5 rounded-full bg-surface-2">
                      <div
                        className={`absolute inset-y-0 left-0 rounded-full ${ALLOC_COLOR[k]}`}
                        style={{ width: `${alloc[k]}%` }}
                      />
                    </div>
                    <span className="font-mono text-[11px] text-ink-2 w-8 text-right">{alloc[k]}%</span>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="mt-4 flex items-start gap-3">
            <UserCircle2 className="w-8 h-8 text-ink-4 shrink-0 mt-0.5" />
            <div>
              <div className="text-[14px] font-medium text-ink-1">No risk profile set yet</div>
              <div className="text-[12.5px] text-ink-3 mt-0.5 max-w-[420px]">
                Answer 6 quick questions to get your risk score and see how your portfolio
                aligns with your actual risk appetite.
              </div>
              <button
                onClick={onAmendProfile}
                className="mt-3 text-[13px] font-medium text-accent hover:underline"
              >
                Set my risk profile →
              </button>
            </div>
          </div>
        )}
      </Card>

      {/* Risk drivers */}
      <Card className="mt-5 p-6">
        <CardLabel>What's making it risky · composite risk</CardLabel>
        <ul className="mt-4 flex flex-col gap-3">
          {data.riskDrivers.map((d) => (
            <li key={d.name} className="py-1">
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="text-[14px]">{d.name}</span>
                <div className="flex items-center gap-2 shrink-0">
                  {d.fundamentalScore != null && d.fundamentalScore > 0 && (
                    <span
                      className="text-[11px] font-mono px-1.5 py-0.5 rounded"
                      style={{
                        background: d.fundamentalScore >= 50 ? "rgba(220,60,60,0.18)" : "rgba(220,140,30,0.18)",
                        color:      d.fundamentalScore >= 50 ? "#e05555" : "#d08030",
                      }}
                    >
                      F{d.fundamentalScore}
                    </span>
                  )}
                  <span className="font-mono num text-[13px]">{d.sharePct}%</span>
                </div>
              </div>
              {d.riskFlags.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-1.5">
                  {d.riskFlags.map((f) => (
                    <span
                      key={f}
                      className="text-[10px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded"
                      style={{ background: "rgba(255,255,255,0.07)", color: "var(--color-ink-3)" }}
                    >
                      {f.replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              )}
              <CapBar pct={d.sharePct} height={6} />
            </li>
          ))}
        </ul>
        <p className="mt-4 text-[11px] text-ink-3 leading-relaxed">
          Ranked by composite risk (60% fundamental · 40% market volatility contribution).
          F-score = fundamental risk 0–100. Flags highlight specific risk factors.
        </p>
      </Card>

      {/* Stress scenarios */}
      <Card className="mt-5 p-6">
        <div className="flex items-center mb-4">
          <CardLabel>Stress scenarios · simulated impact</CardLabel>
          <span className="ml-auto text-[12px] text-ink-3">5 scenarios</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" style={{ minWidth: 340 }}>
            <thead>
              <tr className="border-b border-hairline">
                {["Scenario", "Portfolio", "Benchmark", "Recovery"].map((h) => (
                  <th key={h} className="text-left font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 font-normal px-3 py-2">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.stressScenarios.map((s) => {
                const tone = s.portfolioPct < -0.2 ? "text-neg" : s.portfolioPct < -0.05 ? "text-warm" : "text-pos";
                return (
                  <tr key={s.name} className="border-t border-hairline">
                    <td className="px-3 py-3 text-[14px] font-medium">{s.name}</td>
                    <td className={`px-3 py-3 font-mono num text-[13px] ${tone}`}>{formatPct(s.portfolioPct, { signed: true })}</td>
                    <td className="px-3 py-3 font-mono num text-[12px] text-ink-3">{formatPct(s.benchPct, { signed: true })}</td>
                    <td className="px-3 py-3 text-[12px] text-ink-3">{s.recovery}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
