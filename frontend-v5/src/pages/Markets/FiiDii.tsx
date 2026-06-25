import { useState } from "react";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer, Legend,
  PieChart, Pie, Cell,
} from "recharts";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/formatters";
import { useMarketsFiiDii, useInstitutionalPositioning } from "@/hooks/use-markets";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import type { FiiDiiFlowRow, SectorPositioning } from "@/services/contracts/markets.contract";

type Gran = "daily" | "monthly";

/** Categorical series colours (data identity, not theme chrome). */
const C_FII = "#60a5fa";   // light blue
const C_DII = "#1d4ed8";   // deep blue
const C_OVERALL = "#9333ea"; // purple

const cr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtCr = (n: number | null | undefined) => (n == null ? "—" : cr2.format(n));
/** Compact ₹-crore axis tick, e.g. 8 KCr / −15 KCr. */
function fmtAxis(n: number): string {
  const k = n / 1000;
  return `${k < 0 ? "−" : ""}${Math.abs(k).toFixed(0)} KCr`;
}
function dayLabel(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
function monthLabel(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

export default function FiiDiiPage() {
  const [gran, setGran] = useState<Gran>("daily");
  const q = useMarketsFiiDii(90);

  if (q.isPending) {
    return (
      <div className="mx-auto w-full max-w-[1180px] px-6 py-8 lg:px-10">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }
  if (q.isError) {
    return (
      <ErrorState
        title="Couldn't load FII/DII activity"
        error={q.error}
        onRetry={() => q.refetch()}
      />
    );
  }

  const series: FiiDiiFlowRow[] = gran === "daily" ? q.data.daily : q.data.monthly;

  if (series.length === 0) {
    return (
      <EmptyState
        title="No institutional-flow data yet"
        description="Daily FII/DII cash figures aren't available right now. This refreshes after the NSE provisional release."
      />
    );
  }

  // Chart: oldest → newest, left to right; trimmed to a readable window.
  const chartRows = [...series]
    .slice(0, gran === "daily" ? 30 : 18)
    .reverse()
    .map((r) => ({
      label: gran === "daily" ? dayLabel(r.date!) : monthLabel(r.month!),
      FII: r.fii_net ?? 0,
      DII: r.dii_net ?? 0,
      Overall: (r.fii_net ?? 0) + (r.dii_net ?? 0),
    }));

  return (
    <div className="mx-auto w-full max-w-[1180px] px-6 pb-12 pt-6 lg:px-10">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl text-ink">FII / DII Activity</h1>
          <p className="mt-0.5 text-xs text-ink-3">
            Cash-segment net flows, ₹ crore · NSE provisional
            {q.data.as_of ? ` · as of ${formatDate(q.data.as_of)}` : ""}
          </p>
        </div>
        <GranToggle gran={gran} onChange={setGran} />
      </div>

      {/* ── Chart ──────────────────────────────────────────────── */}
      <Card className="mt-5 p-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[10.5px] font-semibold uppercase tracking-[0.13em] text-ink-3">
            Net flows
          </span>
          <span className="text-[10.5px] uppercase tracking-[0.08em] text-ink-4">
            {gran === "daily" ? "last 30 sessions" : "last 18 months"}
          </span>
        </div>
        <div className="h-[320px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartRows} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line) / 0.14)" vertical={false} />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                tick={{ fill: "rgb(var(--ink-3))", fontSize: 10 }}
                minTickGap={16}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={56}
                tick={{ fill: "rgb(var(--ink-3))", fontSize: 10 }}
                tickFormatter={(v) => fmtAxis(v as number)}
              />
              <ReferenceLine y={0} stroke="rgb(var(--ink-4) / 0.5)" />
              <Tooltip
                cursor={{ fill: "rgb(var(--line) / 0.06)" }}
                contentStyle={{
                  background: "rgb(var(--surface-1))",
                  border: "1px solid rgb(var(--line) / 0.16)",
                  borderRadius: 10,
                  padding: "8px 12px",
                  fontSize: 12,
                }}
                labelStyle={{ color: "rgb(var(--ink))", fontWeight: 600 }}
                formatter={(v: number, name) => [`₹${fmtCr(v)} Cr`, name]}
              />
              <Legend
                wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                iconType="circle"
              />
              <Bar dataKey="FII" fill={C_FII} radius={[2, 2, 0, 0]} maxBarSize={22} />
              <Bar dataKey="DII" fill={C_DII} radius={[2, 2, 0, 0]} maxBarSize={22} />
              <Line
                type="monotone"
                dataKey="Overall"
                stroke={C_OVERALL}
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* ── Summary table ──────────────────────────────────────── */}
      <Card className="mt-5 p-0">
        <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
          <span className="text-[10.5px] font-semibold uppercase tracking-[0.13em] text-ink-3">
            FII / DII summary
          </span>
          <span className="text-[10.5px] uppercase tracking-[0.08em] text-ink-4">in crore</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[12.5px]">
            <thead>
              <tr className="text-[9.5px] uppercase tracking-[0.1em] text-ink-4">
                <th className="px-4 py-2.5 text-left font-medium">{gran === "daily" ? "Date" : "Month"}</th>
                <th className="px-4 py-2.5 text-right font-medium">FII Buy</th>
                <th className="px-4 py-2.5 text-right font-medium">FII Sell</th>
                <th className="px-4 py-2.5 text-right font-medium">FII Net</th>
                <th className="px-4 py-2.5 text-right font-medium">DII Buy</th>
                <th className="px-4 py-2.5 text-right font-medium">DII Sell</th>
                <th className="px-4 py-2.5 text-right font-medium">DII Net</th>
              </tr>
            </thead>
            <tbody>
              {series.map((r) => {
                const key = r.date ?? r.month ?? "";
                const label = r.date ? formatDate(r.date) : monthLabel(r.month!);
                return (
                  <tr key={key} className="border-t border-hairline">
                    <td className="px-4 py-2.5 text-ink">{label}</td>
                    <td className="num px-4 py-2.5 text-right text-ink-2">{fmtCr(r.fii_buy)}</td>
                    <td className="num px-4 py-2.5 text-right text-ink-2">{fmtCr(r.fii_sell)}</td>
                    <td className={cn("num px-4 py-2.5 text-right font-medium", netTone(r.fii_net))}>{fmtCr(r.fii_net)}</td>
                    <td className="num px-4 py-2.5 text-right text-ink-2">{fmtCr(r.dii_buy)}</td>
                    <td className="num px-4 py-2.5 text-right text-ink-2">{fmtCr(r.dii_sell)}</td>
                    <td className={cn("num px-4 py-2.5 text-right font-medium", netTone(r.dii_net))}>{fmtCr(r.dii_net)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ── Institutional holdings by sector (positioning, not flows) ── */}
      <InstitutionalPositioning />

      <p className="mt-6 text-[11px] text-ink-4">
        Source: NSE provisional FII/DII cash-segment figures from the NIDP data lake. Net = buy − sell;
        a positive net means institutions were net buyers that {gran === "daily" ? "session" : "month"}.
      </p>
    </div>
  );
}

/* ─────────────── Institutional holdings by sector ─────────────── */

type Lens = "fii" | "dii" | "combined";

const SECTOR_COLORS = [
  "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#a855f7", "#c084fc",
  "#f59e0b", "#fb923c", "#10b981", "#34d399", "#ef4444", "#f87171",
];

/** Compact ₹-crore, e.g. ₹21.85 L Cr / ₹3.7 K Cr. */
function fmtCrShort(n: number | null | undefined): string {
  if (n == null) return "—";
  const a = Math.abs(n);
  if (a >= 1e5) return `₹${(n / 1e5).toFixed(2)} L Cr`;
  if (a >= 1e3) return `₹${(n / 1e3).toFixed(1)} K Cr`;
  return `₹${Math.round(n)} Cr`;
}

function lensValue(s: SectorPositioning, lens: Lens): number {
  if (lens === "fii") return s.fii_cr ?? 0;
  if (lens === "dii") return s.dii_cr ?? 0;
  return (s.fii_cr ?? 0) + (s.dii_cr ?? 0);
}

function InstitutionalPositioning() {
  const [lens, setLens] = useState<Lens>("fii");
  const q = useInstitutionalPositioning();

  const ranked = [...(q.data?.sectors ?? [])]
    .map((s) => ({ ...s, v: lensValue(s, lens) }))
    .filter((s) => s.v > 0)
    .sort((a, b) => b.v - a.v);
  const top = ranked.slice(0, 10);
  const pie = top.map((s, i) => ({ name: s.sector, value: s.v, fill: SECTOR_COLORS[i % SECTOR_COLORS.length] }));

  return (
    <Card className="mt-5 p-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.13em] text-ink-3">
          Institutional holdings by sector
        </span>
        <div className="inline-flex rounded-md border border-hairline bg-surface-1 p-0.5 text-[11px]">
          {(["fii", "dii", "combined"] as Lens[]).map((l) => (
            <button
              key={l}
              onClick={() => setLens(l)}
              className={cn(
                "rounded px-2.5 py-1 font-medium uppercase transition-colors",
                lens === l ? "bg-surface-3 text-ink" : "text-ink-3 hover:text-ink-2",
              )}
            >
              {l === "combined" ? "FII+DII" : l}
            </button>
          ))}
        </div>
      </div>
      <p className="mb-3 text-[11px] text-ink-4">
        Holding value (holding % × market cap) ·{" "}
        {q.data?.universe ?? "Nifty 500"}
        {q.data?.period_end ? ` · ${formatDate(q.data.period_end)} shareholding` : ""} · positioning, not flows
      </p>

      {q.isError ? (
        <ErrorState title="Couldn't load institutional holdings" error={q.error} onRetry={() => q.refetch()} />
      ) : q.isPending ? (
        <p className="py-8 text-center text-sm text-ink-3">Loading…</p>
      ) : top.length === 0 ? (
        <p className="py-8 text-center text-sm text-ink-3">No shareholding data available.</p>
      ) : (
        <div className="grid items-center gap-4 sm:[grid-template-columns:200px_1fr]">
          <div className="h-[200px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={pie} dataKey="value" nameKey="name" cx="50%" cy="50%"
                     innerRadius={48} outerRadius={84} paddingAngle={1} stroke="none">
                  {pie.map((p) => <Cell key={p.name} fill={p.fill} />)}
                </Pie>
                <Tooltip
                  contentStyle={{ background: "rgb(var(--surface-1))", border: "1px solid rgb(var(--line)/0.16)", borderRadius: 10, fontSize: 12 }}
                  formatter={(v: number, name) => [fmtCrShort(v), name]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div>
            {top.map((s, i) => (
              <div key={s.sector} className="grid items-center gap-2 border-t border-hairline py-[7px] first:border-t-0 [grid-template-columns:14px_1fr_auto]">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SECTOR_COLORS[i % SECTOR_COLORS.length] }} />
                <span className="truncate text-[12.5px] text-ink-2">{s.sector} <span className="text-ink-4">· {s.n}</span></span>
                <span className="num text-right text-[12.5px] font-medium text-ink">{fmtCrShort(s.v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

function netTone(n: number | null | undefined): string {
  if (n == null || n === 0) return "text-ink-3";
  return n > 0 ? "text-pos" : "text-neg";
}

function GranToggle({ gran, onChange }: { gran: Gran; onChange: (g: Gran) => void }) {
  return (
    <div className="inline-flex rounded-md border border-hairline bg-surface-1 p-0.5 text-[12px]">
      {(["daily", "monthly"] as Gran[]).map((g) => (
        <button
          key={g}
          onClick={() => onChange(g)}
          className={cn(
            "rounded px-3 py-1 font-medium capitalize transition-colors",
            gran === g ? "bg-surface-3 text-ink" : "text-ink-3 hover:text-ink-2",
          )}
        >
          {g}
        </button>
      ))}
    </div>
  );
}
