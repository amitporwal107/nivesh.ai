import { Layers, Info } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { usePortfolioXray, type XraySnapshot, type XrayLeader } from "@/hooks/use-analytics";
import { useMountProgress } from "@/hooks/use-animate";
import { formatINRCompact } from "@/lib/formatters";
import { cn } from "@/lib/utils";

/**
 * Portfolio X-ray — the dashboard's "look-through" wow moment.
 *
 * Every number is real, sourced from /api/portfolio/exposure/concentration
 * (the compute_concentration look-through engine). When the look-through is
 * empty (no holdings / no fund-overlap data) we render nothing rather than
 * inventing a fallback state.
 */
export function PortfolioXray() {
  const { data } = usePortfolioXray();
  // Need at least one real leader to be worth showing.
  if (!data || !(data.topAmc || data.topSector || data.topStock)) return null;
  return <XrayContent x={data} />;
}

// Tone the headline % by how concentrated the bucket is.
function pctTone(pct: number, warn: number, bad: number): string {
  if (pct >= bad) return "text-neg";
  if (pct >= warn) return "text-warm";
  return "text-accent";
}

function XrayContent({ x }: { x: XraySnapshot }) {
  const navigate = useNavigate();
  const p = useMountProgress(1200, 120); // drives the count-ups + bar fills
  const bets = Math.round(x.effectiveBets * p);
  // Only tell the "look-through" story when we genuinely dissolved funds into a
  // larger universe of stocks; otherwise lead with the concentration leaders.
  const hasLookThrough = x.effectiveBets > 0 && x.companyCount > x.effectiveBets;

  return (
    <section className="mt-7">
      {/* eyebrow + ref */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3 flex items-center gap-2">
          <Layers className="h-3 w-3" /> Portfolio X-ray
        </div>
        <div className="font-mono text-[10px] uppercase tracking-[.08em] text-ink-4">
          Look-through · what you actually own
        </div>
      </div>

      {/* headline */}
      <h2 className="font-display text-2xl sm:text-[28px] tracking-tightish leading-[1.1] mt-3">
        {hasLookThrough ? (
          <>Your {x.holdingsCount} holdings look through to {x.companyCount} stocks — but really behave like about{" "}
            <span className="text-warm">{bets}</span> bets.</>
        ) : (
          <>Here's what your portfolio really looks like underneath.</>
        )}
      </h2>
      <p className="text-[14px] sm:text-[15px] text-ink-2 mt-2.5 leading-relaxed max-w-[640px]">
        {hasLookThrough ? (
          <>We dissolved every fund into the companies it actually owns. Those{" "}
            {x.companyCount} underlying stocks overlap heavily — so they move like roughly{" "}
            {x.effectiveBets} independent bets, which is what really drives your diversification.</>
        ) : (
          <>We looked through every holding to surface your real concentration — by fund house, sector and underlying stock.</>
        )}
      </p>

      {/* three real leaders */}
      <div className="mt-5 rounded-lg bg-surface-1 border border-hairline shadow-card overflow-hidden">
        <div className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-[rgb(var(--line)/0.10)]">
          {x.topAmc && (
            <XrayCard
              kicker="Top fund house"
              big={`${Math.round(x.topAmc.pct * p)}%`}
              bigTone={pctTone(x.topAmc.pct, 30, 45)}
              name={x.topAmc.name}
              meta={x.topAmc.valueInr ? `${formatINRCompact(x.topAmc.valueInr)} of your MF corpus` : "of your MF corpus"}
              say={<>A big share of your fund money rides with <b>one</b> asset manager.</>}
            >
              <StackedBar items={x.amcBars} p={p} />
            </XrayCard>
          )}

          {x.topSector && (
            <XrayCard
              kicker="Largest sector"
              big={`${Math.round(x.topSector.pct * p)}%`}
              bigTone={pctTone(x.topSector.pct, 35, 50)}
              name={x.topSector.name}
              meta="of your look-through allocation"
              say={<>Your single biggest sector bet — look-through across every fund.</>}
            >
              <MiniBars items={x.sectorBars} p={p} highlight={x.topSector.name} />
            </XrayCard>
          )}

          {x.topStock && (
            <XrayCard
              kicker="Most-owned stock"
              big={`${(x.topStock.pct * p).toFixed(1)}%`}
              bigTone={pctTone(x.topStock.pct, 8, 12)}
              name={x.topStock.name}
              meta={x.topStock.funds > 0 ? `held across ${x.topStock.funds} of your funds` : "your single largest stock"}
              say={x.topStock.funds > 0
                ? <>You never picked this stock directly — yet it sits inside <b>{x.topStock.funds} funds</b>, quietly stacking up.</>
                : <>Your single largest underlying company exposure.</>}
            >
              {x.topStock.funds > 0 && <FundChips count={x.topStock.funds} names={x.topStock.fundNames} p={p} />}
            </XrayCard>
          )}
        </div>

        <button
          onClick={() => navigate("/ai-insights")}
          className="w-full flex items-center gap-2 px-6 py-3 border-t border-hairline bg-surface-1 hover:bg-surface-2 transition-colors font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 hover:text-ink-2"
        >
          <Info className="h-3 w-3" /> See the full look-through analysis
        </button>
      </div>
    </section>
  );
}

function XrayCard({
  kicker, big, bigTone, name, meta, say, children,
}: {
  kicker: string; big: string; bigTone: string; name: string; meta: string;
  say: React.ReactNode; children?: React.ReactNode;
}) {
  return (
    <div className="p-6">
      <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-4">{kicker}</div>
      <div className={cn("font-display num text-[44px] sm:text-[48px] leading-none tracking-tightish mt-3", bigTone)}>{big}</div>
      <div className="text-[14px] font-medium mt-2">{name}</div>
      <div className="text-[12px] text-ink-3 mt-0.5">{meta}</div>
      <p className="text-[12.5px] text-ink-2 leading-relaxed mt-3">{say}</p>
      {children}
    </div>
  );
}

// AMC stacked share bar — the leader in accent-warm, the rest in fading neutral.
function StackedBar({ items, p }: { items: XrayLeader[]; p: number }) {
  if (!items.length) return null;
  const shades = ["rgb(var(--warm))", "rgb(var(--warm)/0.45)", "rgb(var(--ink-3)/0.40)", "rgb(var(--ink-3)/0.28)", "rgb(var(--ink-3)/0.18)"];
  return (
    <div className="flex h-2.5 rounded-full overflow-hidden bg-surface-2 mt-4">
      {items.map((a, i) => (
        <div key={a.name} className="h-full transition-[width] duration-700 ease-out"
          style={{ width: `${a.pct * p}%`, background: shades[i] ?? shades[shades.length - 1] }} />
      ))}
    </div>
  );
}

// Sector mini-bars — labelled rows with the top sector highlighted.
function MiniBars({ items, p, highlight }: { items: XrayLeader[]; p: number; highlight: string }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-col gap-1.5 mt-4">
      {items.map((s) => (
        <div key={s.name} className="flex items-center gap-2 text-[11px] text-ink-2">
          <span className="w-[64px] shrink-0 truncate">{s.name}</span>
          <span className="flex-1 h-[5px] rounded-full bg-surface-2 overflow-hidden">
            <span className="block h-full rounded-full transition-[width] duration-700 ease-out"
              style={{ width: `${s.pct * p}%`, background: s.name === highlight ? "rgb(var(--warm))" : "rgb(var(--warm)/0.32)" }} />
          </span>
          <span className="w-7 text-right font-mono text-[10px] text-ink-3">{Math.round(s.pct)}%</span>
        </div>
      ))}
    </div>
  );
}

// One chip per fund the top stock hides inside — staggered in.
// Falls back to a numbered label only if a fund name is missing.
function FundChips({ count, names, p }: { count: number; names: string[]; p: number }) {
  const labels = Array.from({ length: count }, (_, i) => names[i] ?? `Fund ${i + 1}`);
  const shown = Math.round(count * p);
  return (
    <div className="flex flex-wrap gap-1.5 mt-4">
      {labels.map((label, i) => (
        <span
          key={`${label}-${i}`}
          title={label}
          className="font-mono text-[9px] px-2 py-0.5 rounded-md border transition-opacity duration-300 max-w-[180px] truncate"
          style={{
            opacity: i < shown ? 1 : 0,
            color: "rgb(var(--neg))",
            borderColor: "rgb(var(--neg)/0.28)",
            background: "rgb(var(--neg)/0.08)",
          }}
        >
          {label}
        </span>
      ))}
    </div>
  );
}
