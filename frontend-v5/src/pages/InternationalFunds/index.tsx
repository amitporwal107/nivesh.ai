import { useMemo, useState } from "react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell, LabelList,
} from "recharts";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { ErrorState } from "@/components/shared/ErrorState";
import { useInternationalFunds } from "@/hooks/use-international-funds";
import type {
  InternationalFund, IntlRoute, StatusClass,
} from "@/services/internationalFunds";

/* ── formatters ─────────────────────────────────────────────────────── */
const fmtPct = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
const fmtNum = (n: number | null | undefined, d = 2) =>
  n === null || n === undefined ? "—" : n.toFixed(d);
const tone = (n: number | null | undefined) =>
  n === null || n === undefined ? "text-ink-3" : n > 0 ? "text-pos" : n < 0 ? "text-neg" : "text-ink-2";
const fmtPrice = (f: InternationalFund) => {
  if (f.price === null || f.price === undefined) return "—";
  const sym = f.price_currency === "USD" ? "$" : f.price_currency === "INR" ? "₹" : "";
  return `${sym}${f.price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
};

/* ── route presentation ─────────────────────────────────────────────── */
const ROUTES: { key: IntlRoute; label: string; short: string; hex: string }[] = [
  { key: "Indian FoF",      label: "Indian FoF",      short: "FoF",      hex: "#3b82f6" },
  { key: "Indian Feeder",   label: "Indian Feeder",   short: "Feeder",   hex: "#10b981" },
  { key: "Indian ETF",      label: "Indian ETF",      short: "ETF",      hex: "#f59e0b" },
  { key: "Indian Domestic", label: "Indian Domestic", short: "Domestic", hex: "#a855f7" },
  { key: "LRS Direct",      label: "LRS Direct",      short: "LRS",      hex: "#ec4899" },
];
const routeHex = (r: string) => ROUTES.find((x) => x.key === r)?.hex ?? "#64748b";
const routeShort = (r: string) => ROUTES.find((x) => x.key === r)?.short ?? r;

/* ── sortable columns ───────────────────────────────────────────────── */
type SortKey = "expense_ratio_pct" | "change_pct" | "ret_1y" | "ret_3y";
// Expense sorts ascending (cheaper first); everything else descending.
const sortDir = (k: SortKey): 1 | -1 => (k === "expense_ratio_pct" ? 1 : -1);

export default function InternationalFundsPage() {
  const [active, setActive] = useState<IntlRoute | "all">("all");
  const [sort, setSort] = useState<SortKey>("expense_ratio_pct");
  const query = useInternationalFunds(); // fetch all once; filter client-side

  const all = query.data?.funds ?? [];
  const routes = query.data?.routes ?? [];

  const funds = useMemo(() => {
    const rows = active === "all" ? all : all.filter((f) => f.route === active);
    const dir = sortDir(sort);
    return [...rows].sort((a, b) => {
      const av = a[sort], bv = b[sort];
      if (av === null || av === undefined) return 1;   // nulls last
      if (bv === null || bv === undefined) return -1;
      return (av - bv) * dir;
    });
  }, [all, active, sort]);

  const chartData = useMemo(
    () => ROUTES
      .map((r) => ({ name: r.short, route: r.key,
                     count: routes.find((x) => x.route === r.key)?.count ?? 0 }))
      .filter((d) => d.count > 0),
    [routes],
  );

  const totalFunds = query.data?.count ?? 0;
  const openNow = routes.reduce((s, r) => s + r.open, 0);
  const pricedLive = routes.reduce((s, r) => s + r.priced, 0);

  if (query.isError) {
    return (
      <div className="mx-auto w-full max-w-[1180px] px-6 pt-6 lg:px-10">
        <ErrorState title="Couldn't load international funds"
          error={query.error} onRetry={() => query.refetch()} />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1180px] px-6 pb-16 pt-6 lg:px-10">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div>
        <h1 className="font-display text-2xl text-ink">International Funds</h1>
        <p className="mt-0.5 text-xs text-ink-3">
          Every route to global exposure for an Indian investor — FoFs, feeder funds,
          NSE-listed overseas ETFs, indirect-global domestic funds, and LRS-direct US ETFs ·
          grounded in AMFI + NIDP data
        </p>
      </div>

      {/* ── KPI strip ──────────────────────────────────────────────── */}
      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Funds tracked" value={query.isLoading ? "…" : String(totalFunds)} />
        <Kpi label="Open now"      value={query.isLoading ? "…" : String(openNow)} />
        <Kpi label="Priced live"   value={query.isLoading ? "…" : String(pricedLive)} />
        <Kpi label="Access routes" value={query.isLoading ? "…" : String(routes.length)} />
      </div>

      {/* ── Funds by access route ──────────────────────────────────── */}
      <Card className="mt-5 p-4">
        <div className="text-xs font-medium uppercase tracking-wide text-ink-3">
          Funds by access route
        </div>
        <div className="mt-3 h-[200px] w-full">
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 16, right: 8, left: -16, bottom: 0 }}>
                <XAxis dataKey="name" tick={{ fontSize: 12, fill: "rgb(var(--ink-3))" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: "rgb(var(--ink-4))" }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip
                  cursor={{ fill: "rgb(var(--surface-2))" }}
                  formatter={(v: number) => [`${v} funds`, "Count"]}
                  contentStyle={{ background: "rgb(var(--surface-1))", border: "1px solid rgb(var(--hairline))",
                    borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {chartData.map((d) => <Cell key={d.route} fill={routeHex(d.route)} />)}
                  <LabelList dataKey="count" position="top" fontSize={11} fill="rgb(var(--ink-2))" />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="grid h-full place-items-center text-sm text-ink-4">
              {query.isLoading ? "Loading…" : "No data"}
            </div>
          )}
        </div>
      </Card>

      {/* ── Route filter tabs ──────────────────────────────────────── */}
      <div className="mt-6 flex flex-wrap gap-2">
        <Tab label={`All (${totalFunds})`} active={active === "all"} onClick={() => setActive("all")} />
        {ROUTES.map((r) => {
          const n = routes.find((x) => x.route === r.key)?.count ?? 0;
          if (n === 0) return null;
          return (
            <Tab key={r.key} label={`${r.label} (${n})`} hex={r.hex}
              active={active === r.key} onClick={() => setActive(r.key)} />
          );
        })}
      </div>

      {/* ── Fund table ─────────────────────────────────────────────── */}
      <Card className="mt-3 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] text-sm">
            <thead>
              <tr className="border-b border-hairline text-left text-[11px] uppercase tracking-wide text-ink-4">
                <th className="px-4 py-3 font-medium">Fund</th>
                <th className="px-3 py-3 font-medium">Route</th>
                <th className="px-3 py-3 font-medium">Geography</th>
                <Th label="Expense" k="expense_ratio_pct" sort={sort} setSort={setSort} />
                <th className="px-3 py-3 font-medium">Status</th>
                <th className="px-3 py-3 font-medium">Price</th>
                <Th label="Δ Day" k="change_pct" sort={sort} setSort={setSort} />
                <Th label="3Y" k="ret_3y" sort={sort} setSort={setSort} />
              </tr>
            </thead>
            <tbody>
              {query.isLoading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="border-b border-hairline/60">
                    <td className="px-4 py-4" colSpan={8}>
                      <div className="h-4 w-full animate-pulse rounded bg-surface-2" />
                    </td>
                  </tr>
                ))
              ) : funds.length === 0 ? (
                <tr><td className="px-4 py-10 text-center text-ink-4" colSpan={8}>No funds in this route.</td></tr>
              ) : (
                funds.map((f) => <FundRow key={f.instrument_key} f={f} />)
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="mt-4 text-[11px] leading-relaxed text-ink-4">
        Expense ratios and subscription status are curated; many overseas funds are periodically
        closed under the SEBI/RBI overseas-investment caps — always reconfirm before investing.
        LRS-direct ETF prices are delayed quotes (yfinance) in USD; Indian-fund prices are AMFI NAV in INR.
        Returns &amp; analytics show only for funds NIDP scores. Educational information, not investment advice —
        for a personalised allocation see Recommendations.
      </p>
    </div>
  );
}

/* ── sub-components ─────────────────────────────────────────────────── */
function Kpi({ label, value, small }: { label: string; value: string; small?: boolean }) {
  return (
    <Card className="p-4">
      <div className="text-[11px] uppercase tracking-wide text-ink-4">{label}</div>
      <div className={cn("mt-1 font-display text-ink", small ? "text-base" : "text-2xl")}>{value}</div>
    </Card>
  );
}

function Tab({ label, active, onClick, hex }:
  { label: string; active: boolean; onClick: () => void; hex?: string }) {
  return (
    <button onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-[13px] transition-colors",
        active ? "border-ink bg-surface-2 text-ink" : "border-hairline text-ink-3 hover:text-ink",
      )}>
      {hex && <span className="h-2 w-2 rounded-full" style={{ background: hex }} />}
      {label}
    </button>
  );
}

function Th({ label, k, sort, setSort }:
  { label: string; k: SortKey; sort: SortKey; setSort: (k: SortKey) => void }) {
  return (
    <th className="px-3 py-3 font-medium">
      <button onClick={() => setSort(k)}
        className={cn("inline-flex items-center gap-1 hover:text-ink", sort === k && "text-ink")}>
        {label}{sort === k && <span aria-hidden>{k === "expense_ratio_pct" ? "↑" : "↓"}</span>}
      </button>
    </th>
  );
}

const STATUS_STYLE: Record<StatusClass, { label: string; cls: string }> = {
  open:   { label: "Open",   cls: "bg-[rgb(var(--pos)/0.12)] text-pos" },
  closed: { label: "Closed", cls: "bg-[rgb(var(--neg)/0.12)] text-neg" },
  verify: { label: "Verify", cls: "bg-surface-2 text-ink-3" },
};

function FundRow({ f }: { f: InternationalFund }) {
  const st = STATUS_STYLE[f.status_class] ?? STATUS_STYLE.verify;
  return (
    <tr className="border-b border-hairline/60 hover:bg-surface-2/40">
      <td className="px-4 py-3">
        <div className="font-medium text-ink">{f.fund_name}</div>
        <div className="text-[11px] text-ink-4">{f.amc ?? (f.ticker ? `${f.ticker} · US-listed` : "—")}</div>
      </td>
      <td className="px-3 py-3">
        <span className="inline-flex items-center gap-1.5 text-xs text-ink-2">
          <span className="h-2 w-2 rounded-full" style={{ background: routeHex(f.route) }} />
          {routeShort(f.route)}
        </span>
      </td>
      <td className="px-3 py-3 text-xs text-ink-2">{f.geography ?? "—"}</td>
      <td className="px-3 py-3 tabular-nums text-ink-2">{f.expense_ratio_text ?? (f.expense_ratio_pct === null ? "—" : `${fmtNum(f.expense_ratio_pct)}%`)}</td>
      <td className="px-3 py-3">
        <span className={cn("inline-block rounded px-1.5 py-0.5 text-[11px]", st.cls)}
          title={f.subscription_status ?? undefined}>{st.label}</span>
      </td>
      <td className="px-3 py-3 tabular-nums text-ink-2">{fmtPrice(f)}</td>
      <td className={cn("px-3 py-3 tabular-nums", tone(f.change_pct))}>{fmtPct(f.change_pct)}</td>
      <td className={cn("px-3 py-3 tabular-nums", tone(f.ret_3y))}>{fmtPct(f.ret_3y)}</td>
    </tr>
  );
}
