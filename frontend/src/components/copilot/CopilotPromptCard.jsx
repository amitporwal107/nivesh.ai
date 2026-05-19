import React from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, RadialBarChart, RadialBar } from "recharts";
import { ArrowRight } from "lucide-react";

// Short labels for the 5 product taxonomy buckets — rendered as a tiny chip
// next to each prompt label so users see why a card was suggested.
const CATEGORY_LABEL = {
  portfolio_health:     "Health",
  performance:          "Performance",
  risk_diversification: "Risk",
  tax:                  "Tax",
  goal_planning:        "Goal",
};

function CategoryChip({ category }) {
  if (!category || !CATEGORY_LABEL[category]) return null;
  return (
    <span
      data-testid={`copilot-prompt-category-${category}`}
      className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border border-slate-200 dark:border-slate-700"
    >
      {CATEGORY_LABEL[category]}
    </span>
  );
}

/**
 * Compact, context-aware prompt card used inside the Nivesh Copilot.
 *
 * Replaces the old purely-static prompt chip with an interactive card that
 * shows the user a tiny Recharts visual (donut / bar / gauge / split / stat)
 * built from their real portfolio signals. Clicking the card runs the prompt
 * in chat (the same behaviour as before), so it stays zero-friction.
 *
 * Variants:
 *   • hero      — the Primary prompt (big card, full-width, 2-col layout)
 *   • compact   — the Secondary prompts (smaller, dense row)
 *   • tiny      — the Advanced prompts (chips with just headline + label)
 */
const MiniDonut = ({ series, size = 62, headline, stroke = 2 }) => {
  const data = (series || []).filter((s) => (s.value || 0) > 0);
  if (data.length === 0) {
    return (
      <div style={{ width: size, height: size }} className="flex items-center justify-center rounded-full bg-slate-100 dark:bg-slate-800 text-[11px] text-slate-500 dark:text-slate-400">
        —
      </div>
    );
  }
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            cx="50%"
            cy="50%"
            innerRadius={size * 0.32}
            outerRadius={size * 0.48}
            paddingAngle={2}
            stroke="transparent"
            isAnimationActive={false}
          >
            {data.map((s, i) => (
              <Cell key={i} fill={s.color} strokeWidth={stroke} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      {headline && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span className="text-[11px] font-bold text-slate-800 dark:text-slate-100 tabular-nums">{headline}</span>
        </div>
      )}
    </div>
  );
};

const MiniBar = ({ series, headline, height = 62 }) => {
  const data = (series || []).slice(0, 3);
  if (data.length === 0) return null;
  const max = Math.max(100, ...data.map((d) => d.value || 0));
  return (
    <div className="flex items-center gap-2" style={{ minWidth: 110 }}>
      <div className="flex-1 space-y-1" style={{ height }}>
        {data.map((d, i) => (
          <div key={i} className="flex items-center gap-1">
            <div className="h-1.5 rounded-full flex-1 bg-slate-100 dark:bg-slate-800 overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${Math.min(100, (d.value / max) * 100)}%`, background: d.color }}
              />
            </div>
            <span className="text-[9px] font-semibold text-slate-500 dark:text-slate-400 tabular-nums w-7 text-right">
              {Math.round(d.value)}%
            </span>
          </div>
        ))}
      </div>
      {headline && (
        <span className="text-base font-bold text-slate-800 dark:text-slate-100 tabular-nums">
          {headline}
        </span>
      )}
    </div>
  );
};

const MiniGauge = ({ series, headline, size = 62 }) => {
  // Render as a radial bar — first series = "have", rest = "gap"
  const total = (series || []).reduce((a, b) => a + (b.value || 0), 0);
  const filled = series?.[0]?.value || 0;
  const pct = total > 0 ? Math.min(100, (filled / total) * 100) : 0;
  const data = [
    { name: "gap", value: 100, fill: "#e2e8f0" },
    { name: "filled", value: pct, fill: series?.[0]?.color || "#10b981" },
  ];
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <ResponsiveContainer width="100%" height="100%">
        <RadialBarChart innerRadius="70%" outerRadius="100%" data={data} startAngle={90} endAngle={-270}>
          <RadialBar dataKey="value" background={{ fill: "transparent" }} cornerRadius={8} isAnimationActive={false} />
        </RadialBarChart>
      </ResponsiveContainer>
      {headline && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span className="text-[11px] font-bold text-slate-800 dark:text-slate-100 tabular-nums">{headline}</span>
        </div>
      )}
    </div>
  );
};

const MiniStat = ({ headline, caption }) => (
  <div className="flex flex-col items-center justify-center text-center min-w-[62px] px-2 gap-1">
    {/* Decorative mini bars — keeps the visual footprint of stat-only cards
        consistent with donut/bar/gauge siblings. */}
    <div className="flex items-end gap-0.5 h-4">
      <span className="w-1 h-1.5 rounded-sm bg-slate-300 dark:bg-slate-600" />
      <span className="w-1 h-3 rounded-sm bg-slate-400 dark:bg-slate-500" />
      <span className="w-1 h-2.5 rounded-sm bg-slate-300 dark:bg-slate-600" />
      <span className="w-1 h-4 rounded-sm bg-emerald-500" />
      <span className="w-1 h-2 rounded-sm bg-slate-300 dark:bg-slate-600" />
    </div>
    <span className="text-xl font-bold text-slate-800 dark:text-slate-100 tabular-nums leading-none">
      {headline}
    </span>
    {caption && (
      <span className="text-[9px] text-slate-500 dark:text-slate-400 line-clamp-1">{caption}</span>
    )}
  </div>
);

const MiniSplit = ({ series, headline, size = 62 }) => {
  const total = (series || []).reduce((a, b) => a + (b.value || 0), 0);
  if (total === 0) {
    return <MiniStat headline={headline || "0"} caption="No data yet" />;
  }
  return <MiniDonut series={series} headline={headline} size={size} />;
};

/**
 * Renders the correct viz based on `viz.kind`.
 */
export const CopilotVizInline = ({ viz, size = 62 }) => {
  if (!viz) return null;
  const { kind, series, headline, caption } = viz;
  if (kind === "bar") return <MiniBar series={series} headline={headline} />;
  if (kind === "gauge") return <MiniGauge series={series} headline={headline} size={size} />;
  if (kind === "stat") return <MiniStat headline={headline} caption={caption} />;
  if (kind === "split") return <MiniSplit series={series} headline={headline} size={size} />;
  return <MiniDonut series={series} headline={headline} size={size} />;
};

/**
 * The interactive prompt card itself.
 */
const CopilotPromptCard = ({ prompt, variant = "compact", onClick, disabled, colorClasses, Icon }) => {
  const c = colorClasses;
  const viz = prompt.viz;

  if (variant === "hero") {
    return (
      <button
        data-testid={`copilot-prompt-primary-${prompt.id}`}
        onClick={onClick}
        disabled={disabled}
        className={`group relative w-full text-left p-4 rounded-2xl border-2 ${c.bg} ${c.border} ${c.hover} shadow-sm hover:shadow-md transition-all disabled:opacity-60`}
      >
        <div className="flex items-start gap-4">
          {/* Left: icon + viz */}
          <div className="flex flex-col items-center gap-2">
            <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 bg-white/80 dark:bg-white/10 ${c.text}`}>
              {Icon && <Icon className="w-5 h-5" strokeWidth={2} />}
            </div>
            {viz && <CopilotVizInline viz={viz} size={68} />}
          </div>
          {/* Right: labels */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${c.bg} ${c.text} border ${c.border}`}>
                Start here
              </span>
              <CategoryChip category={prompt.intent_category} />
              {prompt.badge && (
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-white/80 dark:bg-white/10 ${c.text}`}>
                  {prompt.badge}
                </span>
              )}
            </div>
            <p className={`text-base font-bold mt-1.5 ${c.text}`}>{prompt.label}</p>
            <p className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">→ {prompt.outcome}</p>
            {viz?.caption && (
              <p className="text-[10px] text-slate-500 dark:text-slate-500 mt-2 italic">
                {viz.caption}
              </p>
            )}
          </div>
          <ArrowRight className={`w-5 h-5 mt-1 ${c.text} opacity-60 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all`} />
        </div>
      </button>
    );
  }

  if (variant === "tiny") {
    return (
      <button
        data-testid={`copilot-prompt-advanced-${prompt.id}`}
        onClick={onClick}
        disabled={disabled}
        className={`group flex items-center gap-2 text-left p-2.5 rounded-lg border ${c.bg} ${c.border} ${c.hover} transition-all disabled:opacity-60`}
      >
        {Icon && <Icon className={`w-3.5 h-3.5 ${c.text} flex-shrink-0`} strokeWidth={2} />}
        <span className={`text-xs font-medium ${c.text} truncate flex-1`}>{prompt.label}</span>
        {viz?.headline && (
          <span className={`text-[11px] font-bold tabular-nums ${c.text} opacity-80`}>
            {viz.headline}
          </span>
        )}
      </button>
    );
  }

  // compact (secondary)
  return (
    <button
      data-testid={`copilot-prompt-secondary-${prompt.id}`}
      onClick={onClick}
      disabled={disabled}
      className={`group flex items-stretch gap-3 text-left p-3 rounded-xl border ${c.bg} ${c.border} ${c.hover} transition-all disabled:opacity-60`}
    >
      {/* viz block on the left */}
      <div className="flex items-center justify-center flex-shrink-0" style={{ minWidth: 68 }}>
        {viz ? (
          <CopilotVizInline viz={viz} size={56} />
        ) : (
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center bg-white/70 dark:bg-white/5 ${c.text}`}>
            {Icon && <Icon className="w-4 h-4" strokeWidth={1.8} />}
          </div>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-sm font-semibold ${c.text}`}>{prompt.label}</span>
          <CategoryChip category={prompt.intent_category} />
          {prompt.badge && (
            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-white/80 dark:bg-white/10 ${c.text}`}>
              {prompt.badge}
            </span>
          )}
        </div>
        <p className="text-[11px] text-slate-600 dark:text-slate-400 mt-0.5 line-clamp-2">
          → {prompt.outcome}
        </p>
        {viz?.caption && (
          <p className="text-[10px] text-slate-500 dark:text-slate-500 mt-0.5 italic line-clamp-1">
            {viz.caption}
          </p>
        )}
      </div>
      <ArrowRight className={`w-4 h-4 mt-1 ${c.text} opacity-0 group-hover:opacity-100 transition-opacity`} />
    </button>
  );
};

export default CopilotPromptCard;
