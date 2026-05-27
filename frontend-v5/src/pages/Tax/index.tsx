/**
 * Tax dashboard — placeholder wired to the dashboards service.
 * Shows tax summary data from the backend when available.
 */
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

type BadgeTone = "good" | "warm" | "neg" | "accent";

interface TaxBreakdownRow {
  label: string;
  value: string;
  rate: string;
  tax: string;
}

const TAX_ROWS: TaxBreakdownRow[] = [
  { label: "Short-term gains",  value: "Connect portfolio", rate: "15%",        tax: "—" },
  { label: "Long-term gains",   value: "to see your",       rate: "10% > 1L",   tax: "—" },
  { label: "Dividend income",   value: "actual numbers",    rate: "slab",       tax: "—" },
  { label: "After harvest",     value: "here",              rate: "net",        tax: "—" },
];

function TaxKpiCard({ label, value, sub, tone }: { label: string; value: string; sub: string; tone: BadgeTone }) {
  const colorMap: Record<BadgeTone, string> = { good: "text-pos", warm: "text-warm", neg: "text-neg", accent: "text-accent" };
  return (
    <div className="rounded-lg bg-surface-1 border border-hairline p-4">
      <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3">{label}</div>
      <div className={`font-display text-2xl num mt-1 ${colorMap[tone]}`}>{value}</div>
      <div className="font-mono text-[10px] text-ink-3 mt-0.5">{sub}</div>
    </div>
  );
}

export default function TaxPage() {
  const fy = new Date().getFullYear();
  const fyLabel = `FY ${String(fy).slice(2)}–${String(fy + 1).slice(2)}`;
  const daysToMar31 = (() => {
    const mar31 = new Date(fy + 1, 2, 31);
    const today = new Date();
    return Math.max(0, Math.round((mar31.getTime() - today.getTime()) / 86_400_000));
  })();

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">
        Tax · {fyLabel}
      </div>
      <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
        Your tax picture, plain and simple.
      </h1>
      <p className="text-[15.5px] text-ink-2 mt-3 max-w-[600px] leading-relaxed">
        Connect your portfolio to see realised gains, available losses to harvest, and exactly how much you can save before March 31.
      </p>

      {/* KPIs */}
      <div className="mt-7 grid grid-cols-2 sm:grid-cols-4 gap-3">
        <TaxKpiCard label="Net tax owed"      value="—" sub={`${fyLabel} estimate`}    tone="warm" />
        <TaxKpiCard label="Harvest available" value="—" sub="unrealised losses"         tone="good" />
        <TaxKpiCard label="Net you save"      value="—" sub="if you harvest"            tone="good" />
        <TaxKpiCard label="Days to Mar 31"    value={String(daysToMar31)} sub="window open" tone="accent" />
      </div>

      {/* Tax breakdown */}
      <Card className="mt-5 p-6">
        <CardLabel>Tax breakdown · {fyLabel}</CardLabel>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
          {TAX_ROWS.map((row) => (
            <div key={row.label} className="rounded-lg bg-surface-2 border border-hairline p-4">
              <div className="font-mono text-[10px] uppercase tracking-[.10em] text-ink-3">{row.label}</div>
              <div className="font-display text-xl num mt-1">{row.value}</div>
              <div className="font-mono text-[10px] text-ink-3 mt-1">
                {row.rate} · <span className="num">{row.tax}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Harvest plan */}
      <Card className="mt-4 p-6">
        <div className="flex items-center mb-4">
          <CardLabel>Harvest plan</CardLabel>
          <Badge tone="accent" className="ml-auto">0 lots flagged</Badge>
        </div>
        <div className="py-10 text-center font-mono text-[12px] text-ink-3">
          No lots flagged yet — connect your holdings to see harvest opportunities.
        </div>
        <button className="mt-2 w-full rounded-lg bg-accent text-white font-medium text-[13px] py-3 hover:bg-accent/90 transition-colors">
          Import portfolio →
        </button>
      </Card>

      {/* deadline notice */}
      {daysToMar31 < 90 && (
        <div className="mt-4 rounded-lg bg-warm-soft border border-warm/20 p-4 text-[13.5px]">
          <span className="font-medium text-warm">{daysToMar31} days left</span>
          {" "}until the FY end harvest window closes. Act before March 31 to lock in your savings.
        </div>
      )}
    </div>
  );
}
