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

// ── dispatcher ─────────────────────────────────────────────────────────────
export function ChatWidget({ widget }: { widget?: { widget_type?: string; data?: any } }) {
  if (!widget?.widget_type) return null;
  try {
    if (widget.widget_type === "fund_consolidation") return <FundConsolidationWidget data={widget.data} />;
    if (widget.widget_type === "fund_overlap") return <FundOverlapWidget data={widget.data} />;
  } catch {
    return null;
  }
  return null;
}
