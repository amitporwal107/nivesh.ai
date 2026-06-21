/**
 * Structured copilot chat widgets, rendered below the AI bubble in V5 styling.
 * Dispatched by `widget.widget_type`:
 *   - "fund_consolidation" → FundConsolidationWidget ("do I have too many funds?")
 *   - "fund_overlap"       → FundOverlapWidget       ("fix overlap in my funds")
 * Data is produced deterministically by the backend (copilot_tools.portfolio
 * build_consolidation_widget / build_overlap_widget). Unknown types render
 * nothing (the text bubble still shows).
 */
import { Fragment, useState } from "react";
import { cn } from "@/lib/utils";
import { TypedText } from "@/components/chat/TypedHeadline";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, PieChart, Pie, Cell } from "recharts";

const BAR: Record<string, string> = {
  blue: "#3B82F6",
  green: "#10B981",
  amber: "#F59E0B",
  red: "#E5484D",
};

function Bar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="h-2 w-full rounded-full bg-surface-2 overflow-hidden">
      <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, Math.max(0, pct))}%`, background: color }} />
    </div>
  );
}

function Card({ children, tone = "white" }: { children: React.ReactNode; tone?: "white" | "cream" | "muted" }) {
  const base = tone === "cream" ? "bg-surface-2" : tone === "muted" ? "bg-surface-2/60" : "bg-surface-1";
  return <div className={`rounded-lg ${base} border border-hairline shadow-card p-5`}>{children}</div>;
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-surface-1 border border-hairline px-4 py-3 flex-1 min-w-[120px]">
      <div className="text-[12.5px] text-ink-3 leading-tight">{label}</div>
      <div className="font-display text-[26px] text-ink tracking-tightish mt-1 leading-none">{value}</div>
    </div>
  );
}

function ToneBadge({ text, tone }: { text: string; tone?: string }) {
  const cls =
    tone === "neg" ? "bg-[rgb(var(--neg)/0.10)] text-neg"
    : tone === "warm" ? "bg-[rgb(var(--warm)/0.10)] text-warm"
    : "bg-surface-2 text-ink-2";
  return <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium ${cls}`}>{text}</span>;
}

const Heading = ({ children }: { children: React.ReactNode }) => (
  <div className="font-display text-[17px] text-ink tracking-tightish leading-snug">{children}</div>
);

// ── fund_consolidation ────────────────────────────────────────────────────
function FundConsolidationWidget({ data }: { data: any }) {
  if (!data) return null;
  const { verdict, tiles, bars, step1, step2, caveat } = data;
  return (
    <div className="flex flex-col gap-3.5 mt-1 w-full">
      {verdict && (
        <div className="rounded-lg bg-surface-2 border border-hairline p-5">
          <div className="flex items-start gap-3">
            <span className="mt-1 h-3.5 w-3.5 rounded-[3px] border-2 border-warm shrink-0" />
            <div>
              <Heading>{verdict.title}</Heading>
              <p className="text-[14px] text-ink-2 leading-relaxed mt-1.5">{verdict.subtitle}</p>
            </div>
          </div>
        </div>
      )}

      {tiles?.length > 0 && (
        <div className="flex flex-wrap gap-2.5">
          {tiles.map((t: any, i: number) => <Tile key={i} label={t.label} value={t.value} />)}
        </div>
      )}

      {bars && (
        <Card>
          <Heading>{bars.title}</Heading>
          <div className="flex flex-col gap-3.5 mt-4">
            {bars.items.map((b: any, i: number) => (
              <div key={i}>
                <div className="flex items-baseline justify-between mb-1.5">
                  <span className="text-[14px] text-ink-2">
                    {b.label}{b.sublabel && <span className="text-ink-3"> ({b.sublabel})</span>}
                  </span>
                  <span className="font-display text-[16px] text-ink">{b.approx ? "~" : ""}{b.value}</span>
                </div>
                <Bar pct={(b.value / (bars.max || 1)) * 100} color={BAR[b.color] || BAR.blue} />
              </div>
            ))}
          </div>
          {bars.reading && <p className="text-[13.5px] text-ink-2 leading-relaxed mt-4">{bars.reading}</p>}
        </Card>
      )}

      {step1 && (
        <Card>
          <Heading>{step1.title}</Heading>
          {step1.subtitle && <p className="text-[13.5px] text-ink-3 mt-1">{step1.subtitle}</p>}
          <div className="flex flex-col mt-3">
            {step1.rows.map((r: any, i: number) => (
              <div key={i} className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-md odd:bg-surface-2/50">
                <span className="text-[14px] text-ink-2">{r.name}</span>
                <span className="text-[13px] text-ink-3 shrink-0">{r.meta}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {step2 && (
        <Card>
          <Heading>{step2.title}</Heading>
          <div className="flex flex-col gap-2 mt-3">
            {step2.rows.map((r: any, i: number) => (
              <div key={i} className="px-3 py-2.5 rounded-md bg-surface-2/50">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[14px] text-ink font-medium">{r.name}</span>
                  <span className="text-[13px] text-ink-3 shrink-0">{r.meta}</span>
                </div>
                {r.detail && <p className="text-[13px] text-ink-3 mt-1">{r.detail}</p>}
              </div>
            ))}
          </div>
        </Card>
      )}

      {caveat && <p className="text-[12px] text-ink-3 leading-relaxed px-1">{caveat}</p>}
    </div>
  );
}

// ── fund_overlap ──────────────────────────────────────────────────────────
function OverlapRows({ rows, color }: { rows: any[]; color: string }) {
  return (
    <div className="flex flex-col gap-3.5 mt-3">
      {rows.map((r: any, i: number) => (
        <div key={i}>
          <div className="flex items-baseline justify-between gap-3 mb-1.5">
            <span className="text-[14px] text-ink">{r.name}</span>
            <span className="font-display text-[15px] text-ink shrink-0">{r.overlap_pct}%</span>
          </div>
          <Bar pct={r.overlap_pct} color={color} />
          {r.detail && <p className="text-[12.5px] text-ink-3 mt-1.5">{r.detail}</p>}
        </div>
      ))}
    </div>
  );
}

function Heatmap({ labels, matrix }: { labels: any[]; matrix: (number | null)[][] }) {
  const n = labels.length;
  return (
    <div className="grid gap-1.5 mt-4" style={{ gridTemplateColumns: `minmax(40px,auto) repeat(${n}, minmax(0,1fr))` }}>
      <div />
      {labels.map((l) => (
        <div key={l.key} className="text-center font-mono text-[11px] text-ink-3 pb-0.5">{l.key}</div>
      ))}
      {matrix.map((row, i) => (
        <Fragment key={i}>
          <div className="flex items-center justify-end pr-2 font-mono text-[11px] text-ink-3">{labels[i].key}</div>
          {row.map((v, j) => (
            <div
              key={j}
              className="rounded-md grid place-items-center text-[13px] font-medium min-h-[44px]"
              style={{
                background: v == null ? "rgb(var(--surface-2))" : `rgba(229,72,77,${0.10 + (v / 100) * 0.72})`,
                color: v != null && v >= 55 ? "#fff" : "rgb(var(--ink))",
              }}
            >
              {v == null ? "—" : v}
            </div>
          ))}
        </Fragment>
      ))}
    </div>
  );
}

function FundOverlapWidget({ data }: { data: any }) {
  if (!data) return null;
  const { tiles, same_scheme, different_funds, heatmap, caveat } = data;
  return (
    <div className="flex flex-col gap-3.5 mt-1 w-full">
      {tiles?.length > 0 && (
        <div className="flex flex-wrap gap-2.5">
          {tiles.map((t: any, i: number) => <Tile key={i} label={t.label} value={t.value} />)}
        </div>
      )}

      {same_scheme && (
        <Card>
          <div className="flex items-start justify-between gap-3">
            <div>
              <Heading>{same_scheme.title}</Heading>
              {same_scheme.subtitle && <p className="text-[13.5px] text-ink-3 mt-1">{same_scheme.subtitle}</p>}
            </div>
            {same_scheme.badge && <ToneBadge text={same_scheme.badge} tone={same_scheme.tone} />}
          </div>
          <OverlapRows rows={same_scheme.rows} color={BAR.red} />
        </Card>
      )}

      {different_funds && (
        <Card>
          <div className="flex items-start justify-between gap-3">
            <div>
              <Heading>{different_funds.title}</Heading>
              {different_funds.subtitle && <p className="text-[13.5px] text-ink-3 mt-1">{different_funds.subtitle}</p>}
            </div>
            {different_funds.badge && <ToneBadge text={different_funds.badge} tone={different_funds.tone} />}
          </div>
          <OverlapRows rows={different_funds.rows} color={BAR.amber} />
          {different_funds.more_note && <p className="text-[12.5px] text-ink-3 mt-3">{different_funds.more_note}</p>}
        </Card>
      )}

      {heatmap && (
        <Card>
          <Heading>{heatmap.title}</Heading>
          {heatmap.subtitle && <p className="text-[13.5px] text-ink-3 mt-1">{heatmap.subtitle}</p>}
          <Heatmap labels={heatmap.labels} matrix={heatmap.matrix} />
          {heatmap.legend && <p className="text-[12px] text-ink-3 mt-3">{heatmap.legend}</p>}
        </Card>
      )}

      {caveat && <p className="text-[12px] text-ink-3 leading-relaxed px-1">{caveat}</p>}
    </div>
  );
}

// ── overlap_severity ───────────────────────────────────────────────────────
function OverlapSeverityWidget({ data }: { data: any }) {
  if (!data) return null;
  const { verdict, tiles, bands, offenders, caveat } = data;
  return (
    <div className="flex flex-col gap-3.5 mt-1 w-full">
      {verdict && (
        <div className="rounded-lg bg-surface-2 border border-hairline p-5">
          <div className="flex items-start gap-3">
            <span className="mt-1 h-3.5 w-3.5 rounded-[3px] border-2 border-warm shrink-0" />
            <div>
              <Heading>{verdict.title}</Heading>
              <p className="text-[14px] text-ink-2 leading-relaxed mt-1.5">{verdict.subtitle}</p>
            </div>
          </div>
        </div>
      )}
      {tiles?.length > 0 && (
        <div className="flex flex-wrap gap-2.5">{tiles.map((t: any, i: number) => <Tile key={i} {...t} />)}</div>
      )}
      {bands && (
        <Card>
          <Heading>{bands.title}</Heading>
          {bands.subtitle && <p className="text-[13.5px] text-ink-3 mt-1">{bands.subtitle}</p>}
          <div className="flex flex-col gap-3.5 mt-4">
            {bands.items.map((b: any, i: number) => (
              <div key={i}>
                <div className="flex items-baseline justify-between gap-3 mb-1.5">
                  <span className="text-[14px] text-ink">{b.label}{b.note && <span className="text-ink-3"> ({b.note})</span>}</span>
                  <span className="font-display text-[15px] text-ink shrink-0">{b.value} {b.unit}</span>
                </div>
                <Bar pct={(b.value / (bands.max || 1)) * 100} color={BAR[b.color] || BAR.blue} />
              </div>
            ))}
          </div>
          {bands.reading && <p className="text-[13.5px] text-ink-2 leading-relaxed mt-4">{bands.reading}</p>}
        </Card>
      )}
      {offenders && (
        <Card>
          <Heading>{offenders.title}</Heading>
          <div className="flex flex-col mt-3">
            {offenders.rows.map((r: any, i: number) => (
              <div key={i} className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-md odd:bg-surface-2/50">
                <span className="text-[14px] text-ink">{r.name}</span>
                <span className="text-[13px] font-medium text-neg shrink-0">{r.overlap_pct}%</span>
              </div>
            ))}
          </div>
          {offenders.note && <p className="text-[13px] text-ink-2 leading-relaxed mt-3">{offenders.note}</p>}
        </Card>
      )}
      {caveat && <p className="text-[12px] text-ink-3 leading-relaxed px-1">{caveat}</p>}
    </div>
  );
}

// ── risk_overview ──────────────────────────────────────────────────────────
function Gauge({ rating, score, max, profile, band }: any) {
  const pct = Math.min(100, Math.max(0, (score / max) * 100));
  const bLo = (band[0] / max) * 100;
  const bHi = (band[1] / max) * 100;
  return (
    <div>
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <span className="text-[14px] text-ink-2">Risk rating</span>
          <span className="rounded-full px-2.5 py-1 text-[12px] font-semibold bg-[rgb(var(--neg)/0.10)] text-neg">{rating}</span>
        </div>
        <div className="text-right leading-none">
          <span className="font-display text-[30px] text-ink">{score}</span>
          <span className="text-ink-3 text-[16px]"> /{max}</span>
        </div>
      </div>
      <div className="relative mt-7 mb-1.5">
        <div className="absolute -top-5 -translate-x-1/2 text-[12px] text-ink whitespace-nowrap" style={{ left: `${pct}%` }}>You · {score}</div>
        <div className="h-3.5 w-full rounded-full overflow-hidden flex">
          <div style={{ width: "40%", background: "#4CA845" }} />
          <div style={{ width: "30%", background: "#F59E0B" }} />
          <div style={{ width: "30%", background: "#E5484D" }} />
        </div>
        <div className="absolute top-[-2px] h-[18px] w-[2px] bg-ink -translate-x-1/2" style={{ left: `${pct}%` }} />
      </div>
      <div className="flex justify-between text-[12px] text-ink-3"><span>Low</span><span>Moderate</span><span>High</span></div>
      <div className="relative h-3 mt-2">
        <div className="absolute border-t border-x border-ink-3/40 h-2 rounded-t" style={{ left: `${bLo}%`, width: `${Math.max(0, bHi - bLo)}%` }} />
      </div>
      <div className="text-center text-[12.5px] text-ink-3 mt-0.5">{profile} tolerance</div>
    </div>
  );
}

function RiskOverviewWidget({ data }: { data: any }) {
  if (!data) return null;
  const { gauge, description, tiles, var: v, drivers, action, caveat } = data;
  return (
    <div className="flex flex-col gap-3.5 mt-1 w-full">
      {gauge && (
        <Card>
          <Gauge {...gauge} />
          {description && <p className="text-[14px] text-ink-2 leading-relaxed mt-5">{description}</p>}
        </Card>
      )}
      {tiles?.length > 0 && (
        <div className="flex flex-wrap gap-2.5">{tiles.map((t: any, i: number) => <Tile key={i} {...t} />)}</div>
      )}
      {v && (
        <div className="rounded-lg border border-hairline p-5" style={{ background: "rgb(var(--neg) / 0.07)" }}>
          <div className="text-[13px] text-neg">Worst-case 1-year loss · 95% confidence</div>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span className="font-display text-[34px] text-neg leading-none">{v.pct}%</span>
            {v.inr_label && <span className="text-[18px] text-neg">≈ {v.inr_label}</span>}
          </div>
          {v.subtitle && <p className="text-[13px] text-neg/90 leading-relaxed mt-2">{v.subtitle}</p>}
        </div>
      )}
      {drivers?.items?.length > 0 && (
        <Card>
          <Heading>{drivers.title}</Heading>
          <div className="flex flex-col gap-4 mt-4">
            {drivers.items.map((b: any, i: number) => (
              <div key={i}>
                <div className="flex items-baseline justify-between gap-3 mb-1.5">
                  <span className="text-[14px] text-ink">{b.label}</span>
                  <span className="font-display text-[15px] text-ink shrink-0">{b.value_label}</span>
                </div>
                <Bar pct={b.pct} color={BAR[b.color] || BAR.amber} />
                {b.note && <p className="text-[12.5px] text-ink-3 mt-1.5">{b.note}</p>}
              </div>
            ))}
          </div>
        </Card>
      )}
      {action && (
        <div className="rounded-lg bg-surface-2 border border-hairline p-5">
          <div className="flex items-start gap-3">
            <span className="mt-1 h-3.5 w-3.5 rounded-[3px] border-2 border-warm shrink-0" />
            <div>
              <Heading>{action.title}</Heading>
              <p className="text-[14px] text-ink-2 leading-relaxed mt-1.5">{action.text}</p>
            </div>
          </div>
        </div>
      )}
      {caveat && <p className="text-[12px] text-ink-3 leading-relaxed px-1">{caveat}</p>}
    </div>
  );
}

// ── cap_education ──────────────────────────────────────────────────────────
// "Large-cap vs flexi-cap vs mid-cap?" — a core→satellite spectrum, three
// category cards, an optional personalised overlap insight, and an
// illustrative allocation shape. Data: build_cap_education_widget.
function Spectrum({ data }: { data: any }) {
  if (!data) return null;
  const { title, left_label, right_label, points = [] } = data;
  return (
    <Card>
      {title && <Heading>{title}</Heading>}
      <div className="relative mt-8 mb-7 mx-2">
        <div className="h-1.5 w-full rounded-full" style={{ background: "linear-gradient(90deg,#3B82F6,#10B981,#F59E0B)" }} />
        {points.map((p: any, i: number) => (
          <div key={i} className="absolute -translate-x-1/2 flex flex-col items-center" style={{ left: `${(p.pos ?? 0.5) * 100}%`, top: -2 }}>
            <span className="h-3 w-3 rounded-full border-2 border-surface-1" style={{ background: BAR[p.color] || BAR.blue }} />
            <span className="mt-1.5 text-[12px] text-ink whitespace-nowrap">{p.label}</span>
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[11.5px] text-ink-3">
        <span>{left_label}</span>
        <span>{right_label}</span>
      </div>
    </Card>
  );
}

function CapEducationWidget({ data }: { data: any }) {
  if (!data) return null;
  const { spectrum, cards = [], insight, shape, caveat } = data;
  return (
    <div className="flex flex-col gap-3.5 mt-1 w-full">
      <Spectrum data={spectrum} />
      {cards.length > 0 && (
        <div className="flex flex-col gap-2.5">
          {cards.map((c: any, i: number) => (
            <Card key={i}>
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: BAR[c.color] || BAR.blue }} />
                <Heading>{c.title}</Heading>
              </div>
              {c.body && <p className="text-[14px] text-ink-2 leading-relaxed mt-2">{c.body}</p>}
              {c.watch && <p className="text-[12.5px] text-ink-3 leading-relaxed mt-2">Watch: {c.watch}</p>}
            </Card>
          ))}
        </div>
      )}
      {insight && (
        <div className="rounded-lg border border-hairline p-5" style={{ background: "rgb(var(--warm) / 0.08)" }}>
          <div className="flex items-start gap-2.5">
            <span className="mt-1 h-2.5 w-2.5 rounded-full bg-warm shrink-0" />
            <div>
              <Heading>{insight.title}</Heading>
              {insight.body && <p className="text-[14px] text-ink-2 leading-relaxed mt-1.5">{insight.body}</p>}
            </div>
          </div>
        </div>
      )}
      {shape?.bars?.length > 0 && (
        <Card>
          <Heading>{shape.title}</Heading>
          {shape.subtitle && <p className="text-[12.5px] text-ink-3 mt-1">{shape.subtitle}</p>}
          <div className="flex flex-col gap-4 mt-4">
            {shape.bars.map((b: any, i: number) => (
              <div key={i}>
                <div className="flex items-baseline justify-between gap-3 mb-1.5">
                  <span className="text-[14px] text-ink">{b.label}</span>
                  {b.note && <span className="text-[12px] text-ink-3 shrink-0">{b.note}</span>}
                </div>
                <Bar pct={b.weight} color={BAR[b.color] || BAR.blue} />
              </div>
            ))}
          </div>
        </Card>
      )}
      {caveat && <p className="text-[12px] text-ink-3 leading-relaxed px-1">{caveat}</p>}
    </div>
  );
}

// ── concentration ──────────────────────────────────────────────────────────
// "Where is concentration risk highest?" — hero verdict, 4 KPI tiles, three
// concentration lenses (asset-class stacked bar + top sector + top stock), the
// actionable fund-overlap layer, and a prioritised fix list.
// Data: build_concentration_widget.
const CIRCLE: Record<string, string> = { red: "#E5484D", amber: "#F59E0B", green: "#10B981", grey: "#9CA3AF", blue: "#3B82F6" };

function KpiTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg bg-surface-2/60 border border-hairline px-4 py-3 flex-1 min-w-[120px]">
      <div className="text-[12.5px] text-ink-3 leading-tight">{label}</div>
      <div className="font-display text-[26px] text-ink tracking-tightish mt-1 leading-none">{value}</div>
      {sub && <div className="text-[12px] text-ink-3 mt-1">{sub}</div>}
    </div>
  );
}

function StackedBar({ segments }: { segments: any[] }) {
  return (
    <div className="flex h-7 w-full rounded-md overflow-hidden">
      {segments.map((s: any, i: number) => (
        <div key={i} className="flex items-center px-2 min-w-0 whitespace-nowrap"
             style={{ width: `${Math.max(0.5, s.pct)}%`, background: CIRCLE[s.color] || CIRCLE.grey }}>
          {s.label && <span className="text-[12px] font-medium text-white truncate">{s.label}</span>}
        </div>
      ))}
    </div>
  );
}

function ConcentrationWidget({ data }: { data: any }) {
  if (!data) return null;
  const { hero, kpis = [], lenses, overlap, fix_order, caveat } = data;
  return (
    <div className="flex flex-col gap-3.5 mt-1 w-full">
      {hero && (
        <div className="rounded-lg border border-hairline p-5" style={{ background: "rgb(var(--warm) / 0.10)" }}>
          <div className="flex items-start gap-3">
            <span className="mt-1 h-3.5 w-3.5 rounded-[3px] border-2 border-warm shrink-0" />
            <div>
              <div className="font-display text-[17px] text-ink tracking-tightish leading-snug">{hero.title}</div>
              {hero.body && <p className="text-[14px] text-ink-2 leading-relaxed mt-1.5"><TypedText text={hero.body} /></p>}
            </div>
          </div>
        </div>
      )}

      {kpis.length > 0 && (
        <div className="flex flex-wrap gap-2.5">
          {kpis.map((k: any, i: number) => <KpiTile key={i} label={k.label} value={k.value} sub={k.sub} />)}
        </div>
      )}

      {lenses?.items?.length > 0 && (
        <Card>
          <Heading>{lenses.title}</Heading>
          <div className="flex flex-col gap-5 mt-4">
            {lenses.items.map((l: any, i: number) => (
              <div key={i}>
                <div className="text-[13.5px] text-ink mb-2">{l.label}</div>
                {l.kind === "stacked"
                  ? <StackedBar segments={l.segments || []} />
                  : <Bar pct={l.pct} color={CIRCLE[l.color] || CIRCLE.amber} />}
                {l.note && <p className="text-[12.5px] text-ink-3 leading-relaxed mt-2">{l.note}</p>}
              </div>
            ))}
          </div>
        </Card>
      )}

      {overlap?.rows?.length > 0 && (
        <Card>
          <div className="flex items-start justify-between gap-3">
            <Heading>{overlap.title}</Heading>
            {overlap.badge && <ToneBadge text={overlap.badge} tone="warm" />}
          </div>
          {overlap.subtitle && <p className="text-[13.5px] text-ink-2 leading-relaxed mt-1.5">{overlap.subtitle}</p>}
          <div className="flex flex-col gap-3.5 mt-4">
            {overlap.rows.map((r: any, i: number) => (
              <div key={i}>
                <div className="flex items-baseline justify-between gap-3 mb-1.5">
                  <span className="text-[14px] text-ink">{r.label}</span>
                  <span className="font-display text-[15px] text-ink shrink-0">{r.pct}%</span>
                </div>
                <Bar pct={r.pct} color={CIRCLE[r.color] || CIRCLE.red} />
              </div>
            ))}
          </div>
        </Card>
      )}

      {fix_order?.items?.length > 0 && (
        <div className="rounded-lg bg-surface-2 border border-hairline p-5">
          <Heading>{fix_order.title}</Heading>
          <div className="flex flex-col gap-3.5 mt-3.5">
            {fix_order.items.map((f: any, i: number) => (
              <div key={i} className="flex items-start gap-3">
                <span className="mt-0.5 h-5 w-5 rounded-full shrink-0 flex items-center justify-center text-[11px] font-semibold text-white"
                      style={{ background: CIRCLE[f.color] || CIRCLE.grey }}>{f.n}</span>
                <p className="text-[14px] text-ink-2 leading-relaxed">
                  <span className="font-medium text-ink">{f.title}</span> — {f.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {caveat && <p className="text-[12px] text-ink-3 leading-relaxed px-1">{caveat}</p>}
    </div>
  );
}

// ── allocation_review ───────────────────────────────────────────────────────
// "Is my wealth allocation optimal?" — verdict hero (over/under/aligned vs
// target), current-vs-target comparison, optional broken-XIRR alert, reliable
// figures, and a prioritised action list. Data: build_allocation_review_widget.
function TargetBar({ segments }: { segments: any[] }) {
  return (
    <div className="flex h-7 w-full rounded-md overflow-hidden border border-dashed border-hairline-2 bg-surface-2/40">
      {segments.map((s: any, i: number) => (
        <div key={i} className="flex items-center px-2 min-w-0 whitespace-nowrap border-r border-dashed border-hairline-2 last:border-r-0" style={{ width: `${Math.max(0.5, s.pct)}%` }}>
          {s.label && <span className="text-[12px] text-ink-2 truncate">{s.label}</span>}
        </div>
      ))}
    </div>
  );
}

function AllocationReviewWidget({ data }: { data: any }) {
  if (!data) return null;
  const { hero, comparison, xirr_alert, reliable, plan, actions, caveat } = data;
  const heroWarm = hero?.tone === "warm";
  return (
    <div className="flex flex-col gap-3.5 mt-1 w-full">
      {hero && (
        <div className="rounded-lg border border-hairline p-5" style={{ background: heroWarm ? "rgb(var(--warm) / 0.10)" : "rgb(var(--accent) / 0.08)" }}>
          <div className="flex items-start gap-3">
            <span className={cn("mt-1 h-3.5 w-3.5 rounded-[3px] border-2 shrink-0", heroWarm ? "border-warm" : "border-accent")} />
            <div>
              <div className="font-display text-[17px] text-ink tracking-tightish leading-snug">{hero.title}</div>
              {hero.body && <p className="text-[14px] text-ink-2 leading-relaxed mt-1.5"><TypedText text={hero.body} /></p>}
            </div>
          </div>
        </div>
      )}

      {comparison?.rows?.length > 0 && (
        <Card>
          <Heading>{comparison.title}</Heading>
          <div className="flex flex-col gap-4 mt-4">
            {comparison.rows.map((r: any, i: number) => (
              <div key={i}>
                <div className="text-[12.5px] text-ink-3 mb-1.5">{r.label}</div>
                {r.dashed ? <TargetBar segments={r.segments || []} /> : <StackedBar segments={r.segments || []} />}
              </div>
            ))}
          </div>
          {comparison.note && <p className="text-[13px] text-ink-2 leading-relaxed mt-4">{comparison.note}</p>}
        </Card>
      )}

      {xirr_alert && (
        <div className="rounded-lg border border-hairline p-5" style={{ background: "rgb(var(--neg) / 0.07)" }}>
          <div className="font-display text-[16px] text-neg tracking-tightish leading-snug">{xirr_alert.title}</div>
          {xirr_alert.body && <p className="text-[13.5px] text-neg/90 leading-relaxed mt-1.5">{xirr_alert.body}</p>}
        </div>
      )}

      {plan && (
        <Card>
          <Heading>{plan.title}</Heading>
          {plan.headline && <p className="text-[14px] text-ink leading-relaxed mt-1.5">{plan.headline}</p>}

          {plan.exit?.rows?.length > 0 && (
            <div className="mt-4">
              <div className="text-[13px] font-medium text-ink">{plan.exit.title}</div>
              {plan.exit.subtitle && <p className="text-[12.5px] text-ink-3 mt-0.5">{plan.exit.subtitle}</p>}
              <div className="flex flex-col mt-2.5">
                {plan.exit.rows.map((r: any, i: number) => (
                  <div key={i} className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-md odd:bg-surface-2/50">
                    <div className="min-w-0">
                      <span className="inline-flex items-center gap-1.5 text-[14px] text-ink">
                        <span className="h-1.5 w-1.5 rounded-full bg-neg shrink-0" />{r.name}
                      </span>
                      {r.note && <span className="block text-[12px] text-ink-3 mt-0.5 pl-3">{r.note}</span>}
                    </div>
                    {r.amount && <span className="font-display text-[15px] text-ink shrink-0">{r.amount}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {plan.redeploy?.rows?.length > 0 && (
            <div className="mt-4">
              <div className="text-[13px] font-medium text-ink">{plan.redeploy.title}</div>
              {plan.redeploy.subtitle && <p className="text-[12.5px] text-ink-3 mt-0.5">{plan.redeploy.subtitle}</p>}
              <div className="flex flex-col mt-2.5">
                {plan.redeploy.rows.map((r: any, i: number) => (
                  <div key={i} className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-md bg-surface-2/50">
                    <div className="min-w-0">
                      <span className="inline-flex items-center gap-1.5 text-[14px] text-ink">
                        <span className="h-1.5 w-1.5 rounded-full bg-accent shrink-0" />{r.label}
                      </span>
                      {r.note && <span className="block text-[12px] text-ink-3 mt-0.5 pl-3">{r.note}</span>}
                    </div>
                    {r.amount && <span className="font-display text-[15px] text-ink shrink-0">{r.amount}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {plan.switch?.names?.length > 0 && (
            <div className="mt-4">
              <div className="text-[13px] font-medium text-ink">{plan.switch.title}</div>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {plan.switch.names.map((nm: string, i: number) => (
                  <span key={i} className="rounded-full bg-surface-2 border border-hairline px-2.5 py-1 text-[12px] text-ink-2">{nm}</span>
                ))}
              </div>
            </div>
          )}

          {plan.note && <p className="text-[12px] text-ink-3 leading-relaxed mt-4">{plan.note}</p>}
        </Card>
      )}

      {reliable?.tiles?.length > 0 && (
        <Card>
          <Heading>{reliable.title}</Heading>
          <div className="flex flex-wrap gap-2.5 mt-4">
            {reliable.tiles.map((t: any, i: number) => <KpiTile key={i} label={t.label} value={t.value} sub={t.sub} />)}
          </div>
        </Card>
      )}

      {actions?.items?.length > 0 && (
        <div className="rounded-lg bg-surface-2 border border-hairline p-5">
          <Heading>{actions.title}</Heading>
          <div className="flex flex-col gap-3.5 mt-3.5">
            {actions.items.map((f: any, i: number) => (
              <div key={i} className="flex items-start gap-3">
                <span className="mt-0.5 h-5 w-5 rounded-full shrink-0 grid place-items-center text-[11px] font-semibold bg-ink text-on-accent">{f.n}</span>
                <p className="text-[14px] text-ink-2 leading-relaxed">
                  <span className="font-medium text-ink">{f.title}</span> — {f.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {caveat && <p className="text-[12px] text-ink-3 leading-relaxed px-1">{caveat}</p>}
    </div>
  );
}

// ── instrument_detail (stock / mutual-fund detail card) ────────────────────
// One card, two variants keyed by `data.kind`. Backend (NIDP DaaS) produces the
// shape deterministically; every value here is read straight from `data` — the
// widget invents nothing. Missing sections are omitted, never faked.

const TONE_HEX: Record<string, string> = {
  pos: "#0E8A55",   // --accent / --pos  (green)
  warm: "#B86A12",  // --warm            (amber)
  neg: "#C5303E",   // --neg             (red)
  info: "#3E6CA8",  // blue (neutral attention)
  grey: "#9CA3AF",
};

function toneText(tone?: string): string {
  return tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : tone === "warm" ? "text-warm" : "text-ink";
}

/** Single-value score ring, coloured by tone. Number centred, no inner sublabel
 *  (the qualitative label sits beside it, matching the design). */
function ScoreDonut({ score, tone = "pos", size = 96 }: { score: number; tone?: string; size?: number }) {
  const sw = 9;
  const r = (size - sw - 2) / 2;
  const C = 2 * Math.PI * r;
  const dash = C * Math.min(1, Math.max(0, score / 100));
  const cx = size / 2;
  const color = TONE_HEX[tone] ?? TONE_HEX.pos;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`Quality score ${score} out of 100`} className="shrink-0">
      <circle cx={cx} cy={cx} r={r} fill="none" stroke="rgb(var(--surface-3))" strokeWidth={sw} />
      <circle cx={cx} cy={cx} r={r} fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round"
        strokeDasharray={`${dash} ${C - dash}`} transform={`rotate(-90 ${cx} ${cx})`} />
      <text x={cx} y={cx} textAnchor="middle" dominantBaseline="central" className="fill-ink font-display"
        style={{ fontSize: size * 0.36, letterSpacing: "-0.04em" }}>{score}</text>
    </svg>
  );
}

/** label → value row used by the fundamental / technical columns. */
function DetailRow({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2.5 border-b border-hairline last:border-0">
      <span className="text-[14px] text-ink-2">{label}</span>
      <span className={`text-[14px] font-medium ${toneText(tone)}`}>{value}</span>
    </div>
  );
}

/** Compact KPI tile (trailing returns / risk ratios), value colour controllable. */
function StatTile({ label, value, valueCls = "text-ink", center }: { label: string; value: string; valueCls?: string; center?: boolean }) {
  return (
    <div className={`rounded-lg bg-surface-2/60 border border-hairline px-3.5 py-3 flex-1 min-w-[92px] ${center ? "text-center" : ""}`}>
      <div className="text-[12px] text-ink-3 leading-tight">{label}</div>
      <div className={`font-display text-[20px] tracking-tightish mt-1 leading-none ${valueCls}`}>{value}</div>
    </div>
  );
}

/** Composite score bar (Fundamentals / Technicals) — label, qualitative+number, filled bar. */
function ScoreBar({ title, s }: { title: string; s?: { score?: number; label?: string; tone?: string } }) {
  if (!s || s.score == null) return null;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[14px] text-ink-2">{title}</span>
        <span className={`text-[13px] font-medium ${toneText(s.tone)}`}>{s.label ? `${s.label} · ` : ""}{s.score}</span>
      </div>
      <div className="mt-1.5"><Bar pct={s.score} color={TONE_HEX[s.tone ?? "pos"] ?? TONE_HEX.pos} /></div>
    </div>
  );
}

/** Small colour square (highlights) / dot (metric cards). */
function Dot({ tone, square }: { tone?: string; square?: boolean }) {
  return (
    <span
      className={`shrink-0 ${square ? "h-2.5 w-2.5 rounded-[3px] mt-[5px]" : "h-2 w-2 rounded-full mt-1"}`}
      style={{ background: TONE_HEX[tone ?? "grey"] ?? TONE_HEX.grey }}
    />
  );
}

/** Benchmarked metric card: value (coloured only when signed) + note + tone dot. */
function MetricCard({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: string }) {
  const coloured = /^[+-]/.test(value.trim());
  return (
    <div className="rounded-lg bg-surface-2/60 border border-hairline px-3.5 py-3">
      <div className="flex items-start justify-between gap-1">
        <span className="text-[12px] text-ink-3 leading-tight">{label}</span>
        {tone && <Dot tone={tone} />}
      </div>
      <div className={`font-display text-[22px] tracking-tightish mt-1 leading-none ${coloured ? toneText(tone) : "text-ink"}`}>{value}</div>
      {note && <div className="text-[11.5px] text-ink-3 mt-1 leading-snug">{note}</div>}
    </div>
  );
}

interface PricePosition {
  current?: number; current_label?: string;
  support?: number; support_label?: string;
  sma50?: number; sma50_label?: string;
  resistance?: number; resistance_label?: string;
  trend?: { label?: string; tone?: string };
}

/** 'Where price sits' — current price marker + 50-DMA tick between support & resistance. */
function PricePositionBar({ pp }: { pp: PricePosition }) {
  const lo = pp.support ?? pp.current ?? 0;
  const hi = pp.resistance ?? pp.current ?? lo + 1;
  const span = hi - lo || 1;
  const pos = (v?: number) => (v == null ? 0 : Math.min(100, Math.max(0, ((v - lo) / span) * 100)));
  return (
    <div className="mt-3">
      <div className="relative h-5">
        {pp.current_label != null && (
          <span className="absolute -translate-x-1/2 text-[12px] font-medium text-ink whitespace-nowrap" style={{ left: `${pos(pp.current)}%` }}>{pp.current_label}</span>
        )}
      </div>
      <div className="relative h-2 rounded-full bg-surface-2">
        {pp.sma50 != null && <span className="absolute top-1/2 -translate-y-1/2 h-3 w-[2px] bg-ink-3" style={{ left: `${pos(pp.sma50)}%` }} aria-hidden />}
        {pp.current != null && <span className="absolute top-1/2 left-0 -translate-y-1/2 -translate-x-1/2 h-3.5 w-1 rounded bg-ink" style={{ left: `${pos(pp.current)}%` }} aria-hidden />}
      </div>
      <div className="flex justify-between text-[11.5px] text-ink-3 mt-2">
        <span>{pp.support_label ? `Support ${pp.support_label}` : ""}</span>
        {pp.sma50_label && <span>50-day MA {pp.sma50_label}</span>}
        <span>{pp.resistance_label ? `Resistance ${pp.resistance_label}` : ""}</span>
      </div>
    </div>
  );
}

/** mini bar coloured by score band — used by the score-breakdown pillars. */
function scoreColor(s: number): string {
  return s >= 60 ? BAR.green : s >= 40 ? BAR.amber : BAR.red;
}

function PillarBars({ pillars }: { pillars?: { label: string; score: number }[] }) {
  if (!pillars?.length) return null;
  return (
    <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-5 gap-y-2">
      {pillars.map((p, i) => (
        <div key={i}>
          <div className="flex justify-between text-[12px] text-ink-3"><span>{p.label}</span><span className="text-ink-2">{p.score}</span></div>
          <div className="mt-0.5"><Bar pct={p.score} color={scoreColor(p.score)} /></div>
        </div>
      ))}
    </div>
  );
}

function ScoreBreakdownPanel({ b }: { b: NonNullable<InstrumentDetailData["score_breakdown"]> }) {
  const w = b.weights ?? {};
  const seg = (label: string, key: string, node?: { score?: number; pillars?: { label: string; score: number }[] }) =>
    node?.score == null ? null : (
      <div>
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-[13.5px] text-ink">{label}{w[key] != null ? <span className="text-[12px] text-ink-3"> · {w[key]}% of quality</span> : null}</span>
          <span className="text-[13px] font-medium text-ink-2">{node.score}/100</span>
        </div>
        <PillarBars pillars={node.pillars} />
      </div>
    );
  return (
    <div className="flex flex-col gap-4">
      {seg("Fundamentals", "fundamental", b.fundamental)}
      {seg("Technicals", "technical", b.technical)}
      {seg("Business cycle", "cycle", b.cycle)}
    </div>
  );
}

function PeersPanel({ p }: { p: NonNullable<InstrumentDetailData["peers"]> }) {
  const rows = p.rows ?? [];
  return (
    <div>
      {p.current_rank != null && p.total != null && (
        <div className="text-[12.5px] text-ink-3 mb-2.5">Ranked #{p.current_rank} of {p.total}{p.sector ? ` in ${p.sector}` : ""} by quality score</div>
      )}
      <div className="flex flex-col gap-1.5">
        {rows.map((r, i) => (
          <div key={i} className={`flex items-center gap-3 rounded-md px-2.5 py-1.5 ${r.is_current ? "bg-surface-2 border border-hairline" : ""}`}>
            <span className={`text-[13px] w-28 shrink-0 truncate ${r.is_current ? "font-semibold text-ink" : "text-ink-2"}`}>{r.symbol}</span>
            <div className="flex-1 min-w-0"><Bar pct={r.quality} color={scoreColor(r.quality)} /></div>
            <span className="text-[13px] font-medium text-ink w-7 text-right">{r.quality}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ShareholdingPanel({ s }: { s: NonNullable<InstrumentDetailData["shareholding"]> }) {
  const rows = s.rows ?? [];
  return (
    <div>
      <div className="flex flex-col gap-2.5">
        {rows.map((r, i) => (
          <div key={i}>
            <div className="flex justify-between text-[13px]">
              <span className="text-ink-2">{r.label}</span>
              <span className="text-ink">{r.value}{r.change ? <span className={`ml-2 text-[12px] ${r.change_positive === false ? "text-neg" : "text-pos"}`}>{r.change}</span> : null}</span>
            </div>
            <div className="mt-1"><Bar pct={r.pct} color={BAR.blue} /></div>
          </div>
        ))}
      </div>
      {(s.pledge || s.as_of) && (
        <div className="flex justify-between text-[12px] text-ink-3 mt-3">
          {s.pledge ? <span>Promoter pledge: <span className={toneText(s.pledge.tone)}>{s.pledge.value}</span></span> : <span />}
          {s.as_of ? <span>As of {s.as_of}</span> : null}
        </div>
      )}
    </div>
  );
}

interface InstrumentDetailData {
  kind?: "stock" | "mf";
  name?: string;
  badge?: string;
  subtitle?: string;
  meta?: string;
  price?: { label?: string; value?: string; change?: string; change_positive?: boolean; asof?: string };
  quality?: { score?: number; label?: string; tone?: string };
  rank?: { value?: number; of?: number; caption?: string; label?: string };
  returns?: { label: string; value: string; muted?: boolean }[];
  fundamental?: { badge?: { text: string; tone?: string }; rows?: { label: string; value: string }[] };
  technical?: { title?: string; badge?: { text: string; tone?: string }; rows?: { label: string; value: string; tone?: string }[] };
  ratios?: { title?: string; items?: { label: string; value: string }[] };
  disclaimer?: string;
  source?: string;
  actions?: { label: string; expands?: string }[];
  // Rich stock card (deterministic, built by build_stock_widget)
  summary?: string;
  scores?: {
    fundamental?: { score?: number; label?: string; tone?: string };
    technical?: { score?: number; label?: string; tone?: string };
    explainer?: string;
  };
  highlights?: { tone?: string; text: string }[];
  fundamentals_grid?: { label: string; value: string; note?: string; tone?: string }[];
  price_position?: PricePosition;
  technicals_cards?: { label: string; value: string; note?: string; tone?: string }[];
  disclaimer_note?: string;
  // Inline expansions (toggled by the action buttons)
  score_breakdown?: {
    weights?: Record<string, number>;
    fundamental?: { score?: number; pillars?: { label: string; score: number }[] };
    technical?: { score?: number; pillars?: { label: string; score: number }[] };
    cycle?: { score?: number; pillars?: { label: string; score: number }[] };
  };
  peers?: {
    sector?: string;
    total?: number;
    current_rank?: number;
    rows?: { symbol: string; quality: number; industry?: string; market_cap?: string; is_current?: boolean }[];
  };
  shareholding?: {
    rows?: { label: string; pct: number; value: string; change?: string; change_positive?: boolean }[];
    pledge?: { value: string; tone?: string };
    as_of?: string;
  };
}

function InstrumentDetailWidget({ data }: { data: InstrumentDetailData }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!data || !data.name) return null;
  const isMf = data.kind === "mf";
  const badge = data.badge ?? (isMf ? "MUTUAL FUND" : "STOCK");
  const q = data.quality;
  const rank = data.rank;
  const fund = data.fundamental;
  const tech = data.technical;
  const scores = data.scores;
  const grid = data.fundamentals_grid;
  const pp = data.price_position;
  const cards = data.technicals_cards;
  const richStock = !isMf && (!!data.summary || !!scores || !!grid?.length);
  const headLine = [data.subtitle, data.meta].filter(Boolean).join(" · ");

  return (
    <div className="mt-1 w-full rounded-xl bg-surface-1 border border-hairline shadow-card p-5 sm:p-6 flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-display text-[19px] text-ink tracking-tightish leading-snug">{data.name}</span>
            <span className="shrink-0 rounded-full px-2.5 py-0.5 text-[10px] font-semibold tracking-wide" style={{ background: "#E7EEF9", color: "#3E6CA8" }}>{badge}</span>
          </div>
          {richStock
            ? (headLine && <div className="text-[13px] text-ink-2 mt-1">{headLine}</div>)
            : (<>
                {data.subtitle && <div className="text-[13.5px] text-ink-2 mt-1">{data.subtitle}</div>}
                {data.meta && <div className="text-[12.5px] text-ink-3 mt-0.5">{data.meta}</div>}
              </>)}
        </div>
        {data.price?.value && (
          <div className="text-right shrink-0">
            {data.price.label && <div className="text-[12px] text-ink-3">{data.price.label}</div>}
            <div className="font-display text-[22px] text-ink tracking-tightish leading-tight">{data.price.value}</div>
            {data.price.change && (
              <div className={`text-[13px] font-medium ${data.price.change_positive === false ? "text-neg" : "text-pos"}`}>{data.price.change}</div>
            )}
            {data.price.asof && <div className="text-[11.5px] text-ink-3 mt-0.5">{data.price.asof}</div>}
          </div>
        )}
      </div>

      {/* Quality + prose summary (rich stock) */}
      {richStock && q?.score != null ? (
        <div className="rounded-lg bg-surface-2/60 border border-hairline p-4 sm:p-5 flex items-start gap-4">
          <div className="text-center shrink-0 w-[60px]">
            <div className="font-display text-[34px] text-ink leading-none tracking-tightish">{q.score}</div>
            <div className="text-[11px] text-ink-3 mt-0.5">/ 100</div>
            <div className={`text-[12px] font-medium ${toneText(q.tone)}`}>{q.label}</div>
          </div>
          {(data.summary || (rank?.value != null && rank?.of != null)) && (
            <div className="min-w-0 border-l border-hairline pl-4">
              {data.summary && <p className="text-[13.5px] text-ink-2 leading-relaxed">{data.summary}</p>}
              {rank?.value != null && rank?.of != null && (
                <div className="text-[12px] text-ink-3 mt-2">Sector rank #{rank.value} of {rank.of}{rank.caption ? ` · ${rank.caption}` : ""}</div>
              )}
            </div>
          )}
        </div>
      ) : (q?.score != null || rank?.value != null) ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {q?.score != null && (
            <div className="rounded-lg bg-surface-2/60 border border-hairline p-4 flex items-center gap-4">
              <ScoreDonut score={q.score} tone={q.tone} />
              <div className="min-w-0">
                <div className="text-[13px] text-ink-3">Quality score</div>
                <div className={`font-display text-[20px] leading-tight ${toneText(q.tone)}`}>{q.label ?? "—"}</div>
                <div className="text-[12px] text-ink-3">out of 100</div>
              </div>
            </div>
          )}
          {rank?.value != null && rank?.of != null && (
            <div className="rounded-lg bg-surface-2/60 border border-hairline p-4 flex flex-col justify-center">
              <div className="text-[13px] text-ink-3">{rank.label ?? (isMf ? "Category rank" : "Sector rank")}</div>
              <div className="mt-0.5"><span className="font-display text-[24px] text-ink tracking-tightish">#{rank.value}</span><span className="text-[14px] text-ink-3"> of {rank.of}</span></div>
              <div className="mt-2"><Bar pct={((rank.of - rank.value + 1) / rank.of) * 100} color={BAR.blue} /></div>
              {rank.caption && <div className="text-[12px] text-ink-3 mt-2">{rank.caption}</div>}
            </div>
          )}
        </div>
      ) : null}

      {/* Composite score bars (stock) */}
      {scores && (scores.fundamental?.score != null || scores.technical?.score != null) ? (
        <div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3">
            <ScoreBar title="Fundamentals" s={scores.fundamental} />
            <ScoreBar title="Technicals" s={scores.technical} />
          </div>
          {scores.explainer && <p className="text-[12px] text-ink-3 mt-2.5 leading-snug">{scores.explainer}</p>}
        </div>
      ) : null}

      {/* What stands out (stock) */}
      {data.highlights?.length ? (
        <div>
          <Heading>What stands out</Heading>
          <div className="mt-2.5 flex flex-col gap-2">
            {data.highlights.map((h, i) => (
              <div key={i} className="flex items-start gap-2.5">
                <Dot tone={h.tone} square />
                <span className="text-[13.5px] text-ink-2 leading-snug">{h.text}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Benchmarked fundamentals grid (stock) */}
      {grid?.length ? (
        <div>
          <Heading>Fundamentals <span className="text-[12.5px] text-ink-3 font-normal">· each compared to its benchmark</span></Heading>
          <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            {grid.map((c, i) => <MetricCard key={i} label={c.label} value={c.value} note={c.note} tone={c.tone} />)}
          </div>
        </div>
      ) : null}

      {/* Where price sits (stock) */}
      {pp ? (
        <div>
          <div className="flex items-center justify-between gap-2">
            <Heading>Where price sits</Heading>
            {pp.trend?.label && <span className={`text-[13px] font-medium ${toneText(pp.trend.tone)}`}>{pp.trend.label}</span>}
          </div>
          <PricePositionBar pp={pp} />
          {cards?.length ? (
            <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              {cards.map((c, i) => <MetricCard key={i} label={c.label} value={c.value} note={c.note} tone={c.tone} />)}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Trailing returns (MF) */}
      {data.returns?.length ? (
        <div>
          <Heading>Trailing returns (CAGR)</Heading>
          <div className="flex flex-wrap gap-2.5 mt-3">
            {data.returns.map((r, i) => (
              <StatTile
                key={i}
                label={r.label}
                value={r.value}
                valueCls={r.muted ? "text-ink" : (String(r.value).trim().startsWith("-") ? "text-neg" : "text-pos")}
              />
            ))}
          </div>
        </div>
      ) : null}

      {/* Fundamental + technical columns */}
      {(fund?.rows?.length || tech?.rows?.length) ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-5">
          {fund?.rows?.length ? (
            <div>
              <div className="flex items-center justify-between gap-2">
                <Heading>Fundamental analysis</Heading>
                {fund.badge && <ToneBadge text={fund.badge.text} tone={fund.badge.tone} />}
              </div>
              <div className="mt-1.5">
                {fund.rows.map((r, i) => <DetailRow key={i} label={r.label} value={r.value} />)}
              </div>
            </div>
          ) : null}
          {tech?.rows?.length ? (
            <div>
              <div className="flex items-center justify-between gap-2">
                <Heading>{tech.title ?? "Technical analysis"}</Heading>
                {tech.badge && <ToneBadge text={tech.badge.text} tone={tech.badge.tone} />}
              </div>
              <div className="mt-1.5">
                {tech.rows.map((r, i) => <DetailRow key={i} label={r.label} value={r.value} tone={r.tone} />)}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Risk & ratios (MF) */}
      {data.ratios?.items?.length ? (
        <div>
          <Heading>{data.ratios.title ?? "Risk & ratios"}</Heading>
          <div className="flex flex-wrap gap-2.5 mt-3">
            {data.ratios.items.map((r, i) => <StatTile key={i} label={r.label} value={r.value} center />)}
          </div>
        </div>
      ) : null}

      {/* Disclaimer */}
      {data.disclaimer && (
        <div className="rounded-lg bg-surface-2/60 border border-hairline px-4 py-3 text-[12px] text-ink-3 leading-relaxed">{data.disclaimer}</div>
      )}

      {/* Action buttons — toggle an inline detail section */}
      {data.actions?.length ? (
        <div>
          <div className="flex flex-wrap gap-2">
            {data.actions.map((a, i) => {
              const isOpen = !!a.expands && open === a.expands;
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => a.expands && setOpen(isOpen ? null : a.expands!)}
                  aria-expanded={isOpen}
                  className={`rounded-full border px-3.5 py-1.5 text-[12.5px] transition-colors ${isOpen ? "border-ink-3 bg-surface-2 text-ink" : "border-hairline bg-surface-1 text-ink-2 hover:bg-surface-2 hover:text-ink"}`}
                >{a.label} {isOpen ? "▲" : "▾"}</button>
              );
            })}
          </div>
          {open && (data.score_breakdown || data.peers || data.shareholding) ? (
            <div className="mt-3 rounded-lg bg-surface-2/40 border border-hairline p-4">
              {open === "score_breakdown" && data.score_breakdown ? <ScoreBreakdownPanel b={data.score_breakdown} />
                : open === "peers" && data.peers ? <PeersPanel p={data.peers} />
                : open === "shareholding" && data.shareholding ? <ShareholdingPanel s={data.shareholding} />
                : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Footer */}
      {(data.source || data.disclaimer_note) && (
        <div className="text-[11.5px] text-ink-3 pt-3 border-t border-hairline -mb-0.5">
          {[data.source ? `Source: ${data.source}` : "", data.disclaimer_note].filter(Boolean).join(" · ")}
        </div>
      )}
    </div>
  );
}

// ── risk_assessment ─────────────────────────────────────────────────────────
// "How risky is my portfolio?" — overall suitability rating, VaR/vol KPIs, the
// stress-test downside per scenario, key risk drivers, and a misalignment
// alert. Data: build_risk_assessment_widget.
const RISK_TONE: Record<string, { bg: string; text: string }> = {
  neg: { bg: "rgb(var(--neg) / 0.08)", text: "text-neg" },
  warm: { bg: "rgb(var(--warm) / 0.12)", text: "text-warm" },
  accent: { bg: "rgb(var(--accent) / 0.10)", text: "text-accent" },
};

function RiskAssessmentWidget({ data }: { data: any }) {
  if (!data) return null;
  const { hero, kpis = [], stress, drivers, alert, caveat } = data;
  const tone = RISK_TONE[hero?.tone] || RISK_TONE.warm;
  return (
    <div className="flex flex-col gap-3.5 mt-1 w-full">
      {hero && (
        <div className="rounded-lg border border-hairline p-5 flex items-start justify-between gap-4" style={{ background: tone.bg }}>
          <div>
            <div className={cn("text-[13px]", tone.text)}>{hero.title}</div>
            <div className={cn("font-display text-[34px] leading-none tracking-tightish mt-1", tone.text)}>{hero.rating}</div>
          </div>
          <div className="text-right shrink-0">
            {hero.profile && <div className="text-[13px] text-ink-2">Profile: {hero.profile}</div>}
            {hero.var_model_risk && <div className="text-[12.5px] text-ink-3 mt-0.5">VaR model risk: {hero.var_model_risk}</div>}
          </div>
        </div>
      )}

      {kpis.length > 0 && (
        <div className="flex flex-wrap gap-2.5">
          {kpis.map((k: any, i: number) => <KpiTile key={i} label={k.label} value={k.value} sub={k.sub} />)}
        </div>
      )}

      {stress?.rows?.length > 0 && (
        <Card>
          <Heading>{stress.title}</Heading>
          {stress.subtitle && <p className="text-[13px] text-ink-3 leading-relaxed mt-1">{stress.subtitle}</p>}
          <div className="flex flex-col gap-4 mt-4">
            {stress.rows.map((r: any, i: number) => (
              <div key={i}>
                <div className="flex items-baseline justify-between gap-3 mb-1.5">
                  <span className="text-[14px] font-medium text-ink">{r.name}</span>
                  <span className="font-display text-[15px] shrink-0" style={{ color: BAR[r.color] || BAR.red }}>{r.drop_label}</span>
                </div>
                <Bar pct={r.bar_pct} color={BAR[r.color] || BAR.red} />
                <div className="flex items-baseline justify-between gap-3 mt-1.5 text-[12.5px] text-ink-3">
                  <span>Value after: {r.value_after}</span>
                  {r.loss && <span>Loss ≈ {r.loss}</span>}
                </div>
                {r.recovery_years && <p className="text-[12px] text-ink-3 mt-0.5">Recovery ≈ {r.recovery_years}y</p>}
              </div>
            ))}
          </div>
        </Card>
      )}

      {drivers?.items?.length > 0 && (
        <Card>
          <Heading>{drivers.title}</Heading>
          <div className="flex flex-col gap-2.5 mt-3.5">
            {drivers.items.map((d: string, i: number) => (
              <div key={i} className="flex items-start gap-2.5">
                <span className="mt-0.5 h-3.5 w-3.5 rounded-[3px] border-2 border-hairline-2 shrink-0" />
                <span className="text-[14px] text-ink-2 leading-snug">{d}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {alert && (
        <div className="rounded-lg border border-hairline p-5" style={{ background: "rgb(var(--warm) / 0.10)" }}>
          <div className="flex items-start gap-2.5">
            <span className="mt-1 h-3.5 w-3.5 rounded-[3px] border-2 border-warm shrink-0" />
            <div>
              <div className="font-display text-[16px] text-warm tracking-tightish leading-snug">{alert.title}</div>
              {alert.body && <p className="text-[14px] text-ink-2 leading-relaxed mt-1.5">{alert.body}</p>}
            </div>
          </div>
        </div>
      )}

      {caveat && <p className="text-[12px] text-ink-3 leading-relaxed px-1">{caveat}</p>}
    </div>
  );
}

// ── dispatcher ─────────────────────────────────────────────────────────────
// ── goal_simulation ─────────────────────────────────────────────────────────
// "Simulate my plan" — goal-funding progress, target/current/gap/SIP-needed
// KPIs, a projected-SIP-growth line chart (needed vs baseline vs target), the
// allocation donut, an overlap nudge, and actions. Data: build_goal_simulation_widget.
const DONUT_COLOR: Record<string, string> = { blue: "#3B82F6", amber: "#F59E0B", grey: "#9CA3AF", green: "#10B981", red: "#E5484D" };
const KPI_TONE: Record<string, string> = { neg: "text-neg", pos: "text-accent" };

function GoalKpi({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg bg-surface-2/60 border border-hairline px-4 py-3 flex-1 min-w-[130px]">
      <div className="text-[12.5px] text-ink-3 leading-tight">{label}</div>
      <div className={cn("font-display text-[26px] tracking-tightish mt-1 leading-none", tone ? KPI_TONE[tone] : "text-ink")}>{value}</div>
    </div>
  );
}

function GoalSimulationWidget({ data, onAction }: { data: any; onAction?: (a: WidgetAction) => void }) {
  if (!data) return null;
  const { hero, kpis = [], chart, donut, alert, actions = [], caveat } = data;
  const heroWarm = hero?.tone !== "accent";
  const yFmt = (v: number) => `₹${Math.round(v / 1e5)}L`;
  const dashFor = (d: string) => (d === "dotted" ? "2 4" : d === "dashed" ? "8 6" : undefined);
  return (
    <div className="flex flex-col gap-3.5 mt-1 w-full">
      {hero && (
        <div className="rounded-lg border border-hairline p-5" style={{ background: heroWarm ? "rgb(var(--warm) / 0.10)" : "rgb(var(--accent) / 0.08)" }}>
          <div className="flex items-start justify-between gap-3">
            <Heading>{hero.title}</Heading>
            {hero.badge && <ToneBadge text={hero.badge} tone={heroWarm ? "neg" : "accent"} />}
          </div>
          <div className="mt-3"><Bar pct={hero.funded_pct} color={BAR.blue} /></div>
          <div className="flex items-baseline justify-between gap-3 mt-1.5 text-[12.5px] text-ink-3">
            <span>{hero.funded_label}</span>
            <span>{hero.target_label}</span>
          </div>
        </div>
      )}

      {kpis.length > 0 && (
        <div className="flex flex-wrap gap-2.5">
          {kpis.map((k: any, i: number) => <GoalKpi key={i} label={k.label} value={k.value} tone={k.tone} />)}
        </div>
      )}

      {chart?.points?.length > 0 && (
        <Card>
          <Heading>{chart.title}</Heading>
          {chart.subtitle && <p className="text-[13px] text-ink-3 leading-relaxed mt-1">{chart.subtitle}</p>}
          <div className="flex flex-wrap gap-x-5 gap-y-1.5 mt-3">
            {chart.series.map((s: any, i: number) => (
              <span key={i} className="inline-flex items-center gap-1.5 text-[12px] text-ink-2">
                <svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke={BAR[s.color] || BAR.green} strokeWidth="2.5" strokeDasharray={dashFor(s.dash)} /></svg>
                {s.label}
              </span>
            ))}
          </div>
          <div className="h-[300px] mt-3 -ml-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chart.points} margin={{ top: 6, right: 10, bottom: 4, left: 0 }}>
                <CartesianGrid stroke="rgb(var(--hairline))" vertical={false} />
                <XAxis dataKey="year" tick={{ fontSize: 11, fill: "rgb(var(--ink-3))" }} tickLine={false} axisLine={false} />
                <YAxis tickFormatter={yFmt} tick={{ fontSize: 11, fill: "rgb(var(--ink-3))" }} tickLine={false} axisLine={false} width={48} />
                {chart.points[0]?.needed !== undefined && (
                  <Line type="monotone" dataKey="needed" stroke={BAR.green} strokeWidth={2.5} dot={false} isAnimationActive={false} />
                )}
                <Line type="monotone" dataKey="baseline" stroke={DONUT_COLOR.grey} strokeWidth={2} strokeDasharray="8 6" dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="target" stroke={BAR.red} strokeWidth={1.5} strokeDasharray="2 4" dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {donut?.slices?.length > 0 && (
        <Card>
          <Heading>{donut.title}</Heading>
          <div className="flex items-center gap-5 mt-3 flex-wrap">
            <div className="h-[160px] w-[160px] shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={donut.slices} dataKey="pct" nameKey="label" cx="50%" cy="50%" innerRadius={48} outerRadius={76} paddingAngle={1} stroke="none">
                    {donut.slices.map((s: any, i: number) => <Cell key={i} fill={DONUT_COLOR[s.color] || DONUT_COLOR.grey} />)}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="flex-1 min-w-[200px]">
              {donut.slices.map((s: any, i: number) => (
                <div key={i} className="flex items-center justify-between gap-3 py-1">
                  <span className="inline-flex items-center gap-2 text-[14px] text-ink-2">
                    <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: DONUT_COLOR[s.color] || DONUT_COLOR.grey }} />{s.label}
                  </span>
                  <span className="font-display text-[15px] text-ink">{s.pct}%</span>
                </div>
              ))}
              {(donut.top_stock || donut.top_sector) && (
                <div className="border-t border-hairline mt-2 pt-2 text-[13px] text-ink-3 flex flex-col gap-1">
                  {donut.top_stock && <div className="flex justify-between"><span>Top stock</span><span className="text-ink-2">{donut.top_stock}</span></div>}
                  {donut.top_sector && <div className="flex justify-between"><span>Top sector</span><span className="text-ink-2">{donut.top_sector}</span></div>}
                </div>
              )}
            </div>
          </div>
        </Card>
      )}

      {alert?.text && (
        <div className="rounded-lg border border-hairline p-5" style={{ background: "rgb(var(--warm) / 0.10)" }}>
          <div className="flex items-start gap-2.5">
            <span className="mt-1 h-3.5 w-3.5 rounded-[3px] border-2 border-warm shrink-0" />
            <p className="text-[14px] text-ink-2 leading-relaxed">{alert.text}</p>
          </div>
        </div>
      )}

      {actions.length > 0 && (
        <div className="flex flex-wrap gap-2.5">
          {actions.map((a: any, i: number) => (
            <button
              key={i}
              type="button"
              onClick={() => onAction?.(a)}
              disabled={!onAction}
              className="inline-flex items-center gap-1 px-3.5 py-2 rounded-md border border-hairline-2 text-[12.5px] text-ink-2 hover:bg-surface-2 hover:text-ink transition-colors disabled:opacity-60 disabled:cursor-default"
            >
              {a.label} <span className="text-ink-3">↗</span>
            </button>
          ))}
        </div>
      )}

      {caveat && <p className="text-[12px] text-ink-3 leading-relaxed px-1">{caveat}</p>}
    </div>
  );
}

// ── mutual-fund cards ───────────────────────────────────────────────────────
// Shared header (name + plan + NAV), tab bar (each tab re-prompts the chat), and
// action chips that drive follow-up prompts via onAction({ query }).

const ALLOC_HEX: Record<string, string> = {
  Equity: "#6366F1", Debt: "#10B981", Cash: "#94A3B8", Derivatives: "#F59E0B", REITs: "#0EA5E9",
};

function MfHeader({ data, onAction }: { data: any; onAction?: (a: WidgetAction) => void }) {
  const sub = [data.subtitle, data.risk].filter(Boolean).join(" · ");
  return (
    <>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-display text-[19px] text-ink tracking-tightish leading-snug">{data.name}</span>
            <span className="shrink-0 rounded-full px-2.5 py-0.5 text-[10px] font-semibold tracking-wide" style={{ background: "#E7EEF9", color: "#3E6CA8" }}>{data.badge ?? "MUTUAL FUND"}</span>
            {data.plan && <span className="text-[12px] text-ink-3">{data.plan}</span>}
          </div>
          {sub && <div className="text-[13px] text-ink-2 mt-1">{sub}</div>}
        </div>
        {data.nav?.value && (
          <div className="text-right shrink-0">
            {data.nav.asof && <div className="text-[12px] text-ink-3">NAV · {data.nav.asof}</div>}
            <div className="font-display text-[22px] text-ink tracking-tightish leading-tight">{data.nav.value}</div>
            {data.nav.change && (
              <div className={`text-[13px] font-medium ${data.nav.change_positive === false ? "text-neg" : "text-pos"}`}>{data.nav.change}</div>
            )}
          </div>
        )}
      </div>
      {data.tabs?.length ? (
        <div className="flex gap-1 flex-wrap border-b border-hairline -mt-1">
          {data.tabs.map((t: any) => (
            t.active ? (
              <span key={t.key} className="px-3 py-2 text-[13px] font-medium text-ink border-b-2 border-warm -mb-px">{t.label}</span>
            ) : (
              <button key={t.key} onClick={() => onAction?.({ query: t.prompt })} className="px-3 py-2 text-[13px] text-ink-3 hover:text-ink transition-colors">{t.label}</button>
            )
          ))}
        </div>
      ) : null}
    </>
  );
}

function MfFooter({ data, onAction }: { data: any; onAction?: (a: WidgetAction) => void }) {
  if (!data.source && !data.disclaimer_note && !data.actions?.length) return null;
  return (
    <div className="flex items-center justify-between gap-3 pt-3 border-t border-hairline">
      <span className="text-[11.5px] text-ink-3">
        {[data.source ? `Source: ${data.source}` : "", data.disclaimer_note].filter(Boolean).join(" · ")}
      </span>
      {data.actions?.length ? (
        <div className="flex flex-wrap gap-2 justify-end">
          {data.actions.map((a: any, i: number) => (
            <button key={i} onClick={() => onAction?.({ query: a.prompt ?? a.label })}
              className="rounded-full border border-hairline px-3.5 py-1.5 text-[12.5px] text-ink-2 bg-surface-1 hover:bg-surface-2 transition-colors">
              {a.label} →
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** instrument_detail for kind="mf": rich summary card (mockup #1). */
function MfSummaryWidget({ data, onAction }: { data: any; onAction?: (a: WidgetAction) => void }) {
  if (!data || !data.name) return null;
  const q = data.quality;
  const returns = data.returns as { label: string; value: string; muted?: boolean }[] | undefined;
  const ratios = data.ratios?.items as { label: string; value: string }[] | undefined;
  return (
    <div className="mt-1 w-full rounded-xl bg-surface-1 border border-hairline shadow-card p-5 sm:p-6 flex flex-col gap-5">
      <MfHeader data={data} onAction={onAction} />

      {q?.score != null && (
        <div className="rounded-lg bg-surface-2/60 border border-hairline p-4 sm:p-5 flex items-start gap-4">
          <div className="text-center shrink-0 w-[64px]">
            <div className="font-display text-[34px] text-ink leading-none tracking-tightish">{q.score}</div>
            <div className="text-[11px] text-ink-3 mt-0.5">/ 100</div>
            <div className={`text-[12px] font-medium ${toneText(q.tone)}`}>{q.label}</div>
          </div>
          <div className="min-w-0 border-l border-hairline pl-4">
            <div className="text-[12px] text-ink-3">Nivesh quality score</div>
            {data.summary && <p className="text-[13.5px] text-ink-2 leading-relaxed mt-1">{data.summary}</p>}
            {q.rank != null && q.of != null && (
              <div className="text-[12px] text-ink-3 mt-2">Category rank #{q.rank} of {q.of}</div>
            )}
          </div>
        </div>
      )}

      {(returns?.length || ratios?.length) ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-5">
          {returns?.length ? (
            <div>
              <div className="flex items-center justify-between gap-2 mb-1">
                <Heading>Returns</Heading>
                {data.returns_badge && <ToneBadge text={data.returns_badge.text} tone={data.returns_badge.tone} />}
              </div>
              {returns.map((r, i) => (
                <DetailRow key={i} label={r.label} value={r.value}
                  tone={r.muted ? undefined : (String(r.value).trim().startsWith("-") ? "neg" : "pos")} />
              ))}
            </div>
          ) : null}
          {ratios?.length ? (
            <div>
              <div className="flex items-center justify-between gap-2 mb-1">
                <Heading>{data.ratios?.title ?? "Risk & cost"}</Heading>
                {data.ratios?.badge && <ToneBadge text={data.ratios.badge.text} tone={data.ratios.badge.tone} />}
              </div>
              {ratios.map((r, i) => <DetailRow key={i} label={r.label} value={r.value} />)}
            </div>
          ) : null}
        </div>
      ) : null}

      {data.disclaimer && (
        <div className="rounded-lg bg-surface-2/60 border border-hairline px-4 py-3 text-[12px] text-ink-3 leading-relaxed">{data.disclaimer}</div>
      )}
      <MfFooter data={data} onAction={onAction} />
    </div>
  );
}

/** Stacked horizontal segment bar (asset allocation / market-cap). */
function SegmentBar({ items }: { items: { label: string; pct: number }[] }) {
  const total = items.reduce((s, i) => s + (i.pct || 0), 0) || 100;
  return (
    <div className="flex h-3 rounded-full overflow-hidden">
      {items.map((it, i) => (
        <div key={i} style={{ width: `${(it.pct / total) * 100}%`, background: ALLOC_HEX[it.label] ?? `hsl(${210 + i * 35} 55% 60%)` }} />
      ))}
    </div>
  );
}

/** One view's body (summary / overview / returns / holdings / peers). Reads a
 *  single view object `v` so the tabbed MfCard can swap bodies with no refetch. */
function MfViewBody({ v }: { v: any }) {
  const view = v?.view;

  if (view === "summary") {
    return (
      <>
        {v.quality?.score != null && (
          <div className="rounded-lg bg-surface-2/60 border border-hairline p-4 sm:p-5 flex items-start gap-4">
            <div className="text-center shrink-0 w-[64px]">
              <div className="font-display text-[34px] text-ink leading-none tracking-tightish">{v.quality.score}</div>
              <div className="text-[11px] text-ink-3 mt-0.5">/ 100</div>
              <div className={`text-[12px] font-medium ${toneText(v.quality.tone)}`}>{v.quality.label}</div>
            </div>
            <div className="min-w-0 border-l border-hairline pl-4">
              <div className="text-[12px] text-ink-3">Nivesh quality score</div>
              {v.summary && <p className="text-[13.5px] text-ink-2 leading-relaxed mt-1">{v.summary}</p>}
              {v.quality.rank != null && v.quality.of != null && (
                <div className="text-[12px] text-ink-3 mt-2">Category rank #{v.quality.rank} of {v.quality.of}</div>
              )}
            </div>
          </div>
        )}
        {(v.returns?.length || v.ratios?.items?.length) ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-5">
            {v.returns?.length ? (
              <div>
                <div className="flex items-center justify-between gap-2 mb-1">
                  <Heading>Returns</Heading>
                  {v.returns_badge && <ToneBadge text={v.returns_badge.text} tone={v.returns_badge.tone} />}
                </div>
                {v.returns.map((r: any, i: number) => (
                  <DetailRow key={i} label={r.label} value={r.value}
                    tone={r.muted ? undefined : (String(r.value).trim().startsWith("-") ? "neg" : "pos")} />
                ))}
              </div>
            ) : null}
            {v.ratios?.items?.length ? (
              <div>
                <div className="flex items-center justify-between gap-2 mb-1">
                  <Heading>{v.ratios.title ?? "Risk & cost"}</Heading>
                  {v.ratios.badge && <ToneBadge text={v.ratios.badge.text} tone={v.ratios.badge.tone} />}
                </div>
                {v.ratios.items.map((r: any, i: number) => <DetailRow key={i} label={r.label} value={r.value} />)}
              </div>
            ) : null}
          </div>
        ) : null}
        {v.disclaimer && (
          <div className="rounded-lg bg-surface-2/60 border border-hairline px-4 py-3 text-[12px] text-ink-3 leading-relaxed">{v.disclaimer}</div>
        )}
      </>
    );
  }

  return (
    <>
      {v.summary && (
        <div className="rounded-lg bg-surface-2/60 border border-hairline px-4 py-3">
          <p className="text-[13.5px] text-ink-2 leading-relaxed">{v.summary}</p>
        </div>
      )}

      {view === "overview" && (
        <>
          {v.quality?.score != null && (
            <div className="flex items-center gap-4">
              <ScoreDonut score={v.quality.score} tone={v.quality.tone} size={72} />
              <div>
                <div className={`font-display text-[18px] ${toneText(v.quality.tone)}`}>{v.quality.label}</div>
                {v.quality.rank != null && <div className="text-[12px] text-ink-3 mt-0.5">Category rank #{v.quality.rank} of {v.quality.of}</div>}
              </div>
            </div>
          )}
          {v.facts?.length ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
              {v.facts.map((f: any, i: number) => <DetailRow key={i} label={f.label} value={f.value} />)}
            </div>
          ) : null}
          {v.returns_snapshot?.length ? (
            <div>
              <Heading>Returns <span className="text-[12.5px] text-ink-3 font-normal">· CAGR</span></Heading>
              <div className="flex flex-wrap gap-2.5 mt-3">
                {v.returns_snapshot.map((r: any, i: number) => (
                  <StatTile key={i} label={r.label} value={r.value} center
                    valueCls={String(r.value).trim().startsWith("-") ? "text-neg" : "text-pos"} />
                ))}
              </div>
            </div>
          ) : null}
          {(v.consider?.length || v.watch?.length) ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-4">
              {v.consider?.length ? (
                <div>
                  <div className="text-[13px] font-medium text-pos mb-2">Reasons to consider</div>
                  {v.consider.map((c: string, i: number) => (
                    <div key={i} className="flex items-start gap-2 mb-1.5"><Dot tone="pos" square /><span className="text-[13px] text-ink-2 leading-snug">{c}</span></div>
                  ))}
                </div>
              ) : null}
              {v.watch?.length ? (
                <div>
                  <div className="text-[13px] font-medium text-warm mb-2">Watch-outs</div>
                  {v.watch.map((c: string, i: number) => (
                    <div key={i} className="flex items-start gap-2 mb-1.5"><Dot tone="warm" square /><span className="text-[13px] text-ink-2 leading-snug">{c}</span></div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          {v.managers && (
            <div className="text-[12.5px] text-ink-3">Fund managers: <span className="text-ink-2">{v.managers}</span></div>
          )}
        </>
      )}

      {view === "returns" && v.cagr?.length ? (
        <div className="flex flex-col gap-4">
          {(() => {
            const vals = v.cagr.flatMap((r: any) => [r.fund, r.category].filter((x: any) => x != null));
            const max = Math.max(...vals.map((x: number) => Math.abs(x)), 1);
            return v.cagr.map((r: any, i: number) => (
              <div key={i}>
                <div className="text-[12.5px] text-ink-2 mb-1.5">{r.label}</div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="w-[68px] text-[11px] text-ink-3">Fund</span>
                  <div className="flex-1"><Bar pct={(Math.abs(r.fund) / max) * 100} color={r.fund < 0 ? BAR.red : BAR.blue} /></div>
                  <span className={`w-[52px] text-right text-[12px] font-medium ${r.fund < 0 ? "text-neg" : "text-ink"}`}>{r.fund}%</span>
                </div>
                {r.category != null && (
                  <div className="flex items-center gap-2">
                    <span className="w-[68px] text-[11px] text-ink-3">Category</span>
                    <div className="flex-1"><Bar pct={(Math.abs(r.category) / max) * 100} color="#94A3B8" /></div>
                    <span className="w-[52px] text-right text-[12px] text-ink-3">{r.category}%</span>
                  </div>
                )}
              </div>
            ));
          })()}
          {v.note && <p className="text-[11.5px] text-ink-3">{v.note}</p>}
        </div>
      ) : null}

      {view === "holdings" && (
        <>
          {v.asset_allocation?.length ? (
            <div>
              <div className="flex items-center justify-between mb-2"><Heading>Asset allocation</Heading>{v.asof && <span className="text-[11.5px] text-ink-3">as of {v.asof}</span>}</div>
              <SegmentBar items={v.asset_allocation} />
              <div className="flex flex-wrap gap-x-5 gap-y-1 mt-2.5">
                {v.asset_allocation.map((a: any, i: number) => (
                  <span key={i} className="text-[12px] text-ink-2 flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: ALLOC_HEX[a.label] ?? `hsl(${210 + i * 35} 55% 60%)` }} />{a.label} {a.pct}%
                  </span>
                ))}
              </div>
            </div>
          ) : null}
          {v.top_holdings?.length ? (
            <div>
              <Heading>Top holdings <span className="text-[12.5px] text-ink-3 font-normal">· % of portfolio</span></Heading>
              <div className="mt-2">
                {v.top_holdings.map((h: any, i: number) => (
                  <div key={i} className="flex items-center gap-3 py-2 border-b border-hairline last:border-0 text-[13px]">
                    <span className="flex-1 text-ink-2 truncate">{h.name}</span>
                    {h.sector && <span className="text-[11px] text-ink-3 w-20 truncate hidden sm:block">{h.sector}</span>}
                    <span className="font-medium text-ink w-12 text-right">{h.weight}%</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {v.sectors?.length ? (
            <div>
              <Heading>Equity sectors</Heading>
              <div className="mt-2 flex flex-col gap-2">
                {(() => { const m = Math.max(...v.sectors.map((s: any) => s.pct), 1);
                  return v.sectors.map((s: any, i: number) => (
                    <div key={i} className="flex items-center gap-3 text-[12px]">
                      <span className="w-24 text-ink-2 truncate">{s.label}</span>
                      <div className="flex-1"><Bar pct={(s.pct / m) * 100} color={BAR.amber} /></div>
                      <span className="w-12 text-right text-ink font-medium">{s.pct}%</span>
                    </div>
                  )); })()}
              </div>
            </div>
          ) : null}
          {v.debt_quality?.length ? (
            <div>
              <Heading>Debt quality</Heading>
              <div className="mt-2 flex flex-col gap-2">
                {(() => { const m = Math.max(...v.debt_quality.map((s: any) => s.pct), 1);
                  return v.debt_quality.map((s: any, i: number) => (
                    <div key={i} className="flex items-center gap-3 text-[12px]">
                      <span className="w-24 text-ink-2 truncate">{s.label}</span>
                      <div className="flex-1"><Bar pct={(s.pct / m) * 100} color={BAR.green} /></div>
                      <span className="w-12 text-right text-ink font-medium">{s.pct}%</span>
                    </div>
                  )); })()}
              </div>
            </div>
          ) : null}
          {v.stats?.length ? (
            <div className="flex flex-wrap gap-2.5">
              {v.stats.map((s: any, i: number) => <StatTile key={i} label={s.label} value={s.value} center />)}
            </div>
          ) : null}
        </>
      )}

      {view === "peers" && v.rows?.length ? (
        <div>
          <div className="flex items-center gap-2 px-3 pb-2 text-[11px] text-ink-3 border-b border-hairline">
            <span className="flex-1">Fund</span>
            <span className="w-16 text-right">AUM Cr</span>
            <span className="w-12 text-right">1Y</span>
            <span className="w-14 text-right">3Y</span>
            <span className="w-12 text-right">Exp</span>
          </div>
          {v.rows.map((r: any, i: number) => (
            <div key={i} className={`flex items-center gap-2 px-3 py-2.5 text-[13px] rounded-md ${r.is_current ? "bg-[rgb(var(--warm)/0.08)]" : ""}`}>
              <span className={`flex-1 truncate ${r.is_current ? "text-ink font-medium" : "text-ink-2"}`}>{r.name}</span>
              <span className="w-16 text-right text-ink-2">{r.aum != null ? Math.round(r.aum).toLocaleString("en-IN") : "—"}</span>
              <span className={`w-12 text-right ${r.ret1y == null ? "text-ink-3" : r.ret1y < 0 ? "text-neg" : "text-pos"}`}>{r.ret1y != null ? `${r.ret1y.toFixed(1)}` : "—"}</span>
              <span className={`w-14 text-right ${r.ret3y == null ? "text-ink-3" : r.ret3y < 0 ? "text-neg" : "text-pos"}`}>{r.ret3y != null ? `${r.ret3y.toFixed(1)}` : "—"}</span>
              <span className="w-12 text-right text-ink-3">{r.ter != null ? `${r.ter.toFixed(2)}` : "—"}</span>
            </div>
          ))}
          {v.caption && <p className="text-[11.5px] text-ink-3 mt-3">{v.caption}</p>}
        </div>
      ) : null}
    </>
  );
}

/** mf_detail: ONE card holding every tab. Tabs switch the body via local state —
 *  no new chat message (data.views carries all tab payloads). */
function MfCard({ data, onAction }: { data: any; onAction?: (a: WidgetAction) => void }) {
  if (!data || !data.name) return null;
  const tabs: any[] = data.tabs || [];
  const views = data.views || {};
  const [active, setActive] = useState<string>(data.active && views[data.active] ? data.active : (tabs[0]?.key || "summary"));
  const v = views[active] || {};
  const sub = [data.subtitle, data.risk].filter(Boolean).join(" · ");
  return (
    <div className="mt-1 w-full rounded-xl bg-surface-1 border border-hairline shadow-card p-5 sm:p-6 flex flex-col gap-5">
      {/* header */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-display text-[19px] text-ink tracking-tightish leading-snug">{data.name}</span>
            <span className="shrink-0 rounded-full px-2.5 py-0.5 text-[10px] font-semibold tracking-wide" style={{ background: "#E7EEF9", color: "#3E6CA8" }}>{data.badge ?? "MUTUAL FUND"}</span>
            {data.plan && <span className="text-[12px] text-ink-3">{data.plan}</span>}
          </div>
          {sub && <div className="text-[13px] text-ink-2 mt-1">{sub}</div>}
        </div>
        {data.nav?.value && (
          <div className="text-right shrink-0">
            {data.nav.asof && <div className="text-[12px] text-ink-3">NAV · {data.nav.asof}</div>}
            <div className="font-display text-[22px] text-ink tracking-tightish leading-tight">{data.nav.value}</div>
            {data.nav.change && (
              <div className={`text-[13px] font-medium ${data.nav.change_positive === false ? "text-neg" : "text-pos"}`}>{data.nav.change}</div>
            )}
          </div>
        )}
      </div>

      {/* tab bar — switches the body locally, no new chat message */}
      {tabs.length > 1 && (
        <div className="flex gap-1 flex-wrap border-b border-hairline -mt-1" role="tablist">
          {tabs.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={t.key === active}
              onClick={() => setActive(t.key)}
              className={t.key === active
                ? "px-3 py-2 text-[13px] font-medium text-ink border-b-2 border-warm -mb-px"
                : "px-3 py-2 text-[13px] text-ink-3 hover:text-ink transition-colors"}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      <MfViewBody v={v} />

      <MfFooter data={data} onAction={onAction} />
    </div>
  );
}

// ── dispatcher ─────────────────────────────────────────────────────────────
// `onAction` lets a widget's action chips drive a follow-up — the host passes a
// handler that submits a chat query (or prefills the composer).
export type WidgetAction = { intent?: string; label?: string; query?: string };
export function ChatWidget({ widget, onAction }: { widget?: { widget_type?: string; data?: any }; onAction?: (a: WidgetAction) => void }) {
  if (!widget?.widget_type) return null;
  try {
    switch (widget.widget_type) {
      case "fund_consolidation": return <FundConsolidationWidget data={widget.data} />;
      case "fund_overlap":       return <FundOverlapWidget data={widget.data} />;
      case "overlap_severity":   return <OverlapSeverityWidget data={widget.data} />;
      case "risk_overview":      return <RiskOverviewWidget data={widget.data} />;
      case "cap_education":      return <CapEducationWidget data={widget.data} />;
      case "concentration":      return <ConcentrationWidget data={widget.data} />;
      case "allocation_review":  return <AllocationReviewWidget data={widget.data} />;
      case "instrument_detail":  return widget.data?.kind === "mf"
                                   ? <MfSummaryWidget data={widget.data} onAction={onAction} />
                                   : <InstrumentDetailWidget data={widget.data} />;
      case "mf_detail":          return <MfCard data={widget.data} onAction={onAction} />;
      case "risk_assessment":    return <RiskAssessmentWidget data={widget.data} />;
      case "goal_simulation":    return <GoalSimulationWidget data={widget.data} onAction={onAction} />;
    }
  } catch {
    return null;
  }
  return null;
}
