/**
 * Structured copilot chat widgets, rendered below the AI bubble in V5 styling.
 * Dispatched by `widget.widget_type`:
 *   - "fund_consolidation" → FundConsolidationWidget ("do I have too many funds?")
 *   - "fund_overlap"       → FundOverlapWidget       ("fix overlap in my funds")
 * Data is produced deterministically by the backend (copilot_tools.portfolio
 * build_consolidation_widget / build_overlap_widget). Unknown types render
 * nothing (the text bubble still shows).
 */
import { Fragment } from "react";
import { cn } from "@/lib/utils";

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
              {hero.body && <p className="text-[14px] text-ink-2 leading-relaxed mt-1.5">{hero.body}</p>}
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
              {hero.body && <p className="text-[14px] text-ink-2 leading-relaxed mt-1.5">{hero.body}</p>}
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

// ── dispatcher ─────────────────────────────────────────────────────────────
export function ChatWidget({ widget }: { widget?: { widget_type?: string; data?: any } }) {
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
    }
  } catch {
    return null;
  }
  return null;
}
