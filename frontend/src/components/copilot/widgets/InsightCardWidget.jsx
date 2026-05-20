import React, { useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  GraduationCap,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import FreshnessChip from "../shared/FreshnessChip";
import AgentRibbon from "../shared/AgentRibbon";

/**
 * InsightCardWidget — unified mobile-first conversational response.
 *
 * Section order (each is individually optional — missing data hides the
 * section rather than rendering an "unavailable" placeholder):
 *
 *   1. Hero (severity tint + headline + primary value)
 *   2. KPI carousel (horizontal swipe on mobile, grid on desktop)
 *   3. Priority findings list
 *   4. AI recommendation (with collapsible rationale)
 *   5. Impact preview (before / after)
 *   6. Action chips
 *   7. "Why this matters" education block (collapsed by default)
 *   8. Suggested follow-up questions (from envelope.suggestions)
 *   9. Sticky CTA bar — mobile only, derived from primary_cta
 *
 * Notes:
 *  - Mobile-first: <md uses sticky bottom CTA + swipeable KPIs.
 *  - Sections that the producer omits should not render at all.
 *  - All numeric formatting is server-owned; we never re-format strings.
 */

const SEVERITY_META = {
  critical: {
    label: "Critical",
    accent: "border-rose-300/70 dark:border-rose-700/60",
    tint:   "bg-gradient-to-br from-rose-50 to-rose-100/40 dark:from-rose-950/30 dark:to-rose-900/10",
    dot:    "bg-rose-500",
    text:   "text-rose-700 dark:text-rose-300",
    chip:   "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300",
  },
  high: {
    label: "High",
    accent: "border-amber-300/70 dark:border-amber-700/60",
    tint:   "bg-gradient-to-br from-amber-50 to-amber-100/40 dark:from-amber-950/30 dark:to-amber-900/10",
    dot:    "bg-amber-500",
    text:   "text-amber-700 dark:text-amber-300",
    chip:   "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  },
  medium: {
    label: "Medium",
    accent: "border-yellow-300/70 dark:border-yellow-700/60",
    tint:   "bg-gradient-to-br from-yellow-50 to-yellow-100/30 dark:from-yellow-950/20 dark:to-yellow-900/10",
    dot:    "bg-yellow-500",
    text:   "text-yellow-700 dark:text-yellow-300",
    chip:   "bg-yellow-100 text-yellow-800 dark:bg-yellow-950/40 dark:text-yellow-300",
  },
  info: {
    label: "Info",
    accent: "border-sky-300/70 dark:border-sky-700/60",
    tint:   "bg-gradient-to-br from-sky-50 to-sky-100/30 dark:from-sky-950/20 dark:to-sky-900/10",
    dot:    "bg-sky-500",
    text:   "text-sky-700 dark:text-sky-300",
    chip:   "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300",
  },
  healthy: {
    label: "Healthy",
    accent: "border-emerald-300/70 dark:border-emerald-700/60",
    tint:   "bg-gradient-to-br from-emerald-50 to-emerald-100/30 dark:from-emerald-950/20 dark:to-emerald-900/10",
    dot:    "bg-emerald-500",
    text:   "text-emerald-700 dark:text-emerald-300",
    chip:   "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
  },
};

const PRIORITY_CHIP = {
  high:   "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  low:    "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
};

const trendIcon = (trend) => {
  if (trend === "up")   return <TrendingUp className="w-3 h-3" />;
  if (trend === "down") return <TrendingDown className="w-3 h-3" />;
  return null;
};

const HeroBlock = ({ hero }) => {
  const sev = SEVERITY_META[hero.severity] || SEVERITY_META.info;
  return (
    <div
      data-testid="insight-card-hero"
      role="region"
      aria-label={`${sev.label} insight: ${hero.headline}`}
      className={`${sev.tint} border-b ${sev.accent} px-4 py-4 sm:py-5`}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span
          className={`inline-flex items-center gap-1 h-5 px-2 rounded-full text-[10px] font-semibold uppercase tracking-wide ${sev.chip}`}
          role="img"
          aria-label={`Severity: ${hero.eyebrow || sev.label}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${sev.dot}`} aria-hidden="true" />
          {hero.eyebrow || sev.label}
        </span>
      </div>
      {/* Dashboard-style hero: headline left, big primary value
          aligned right on lg+ so the card reads like a stat tile. */}
      <div className="md:flex md:items-center md:justify-between md:gap-6">
        <div className="min-w-0 flex-1">
          <h3 className="text-base sm:text-lg md:text-xl font-semibold leading-snug text-[color:var(--cp-text-primary)]">
            {hero.headline}
          </h3>
          {hero.subtitle && (
            <p className="mt-2 text-xs md:text-sm leading-relaxed text-[color:var(--cp-text-secondary)] md:max-w-2xl">
              {hero.subtitle}
            </p>
          )}
        </div>
        {hero.primary_value && (
          <div className="mt-3 md:mt-0 md:text-right flex md:flex-col items-baseline md:items-end gap-2 md:gap-0 shrink-0">
            <span className={`text-3xl sm:text-4xl md:text-5xl font-bold cp-num leading-none ${sev.text} flex items-center gap-1`}>
              {hero.primary_value}
              {trendIcon(hero.trend)}
            </span>
            {hero.primary_label && (
              <span className="text-[11px] md:mt-1 text-[color:var(--cp-text-secondary)]">
                {hero.primary_label}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const KpiCarousel = ({ kpis }) => {
  if (!kpis || kpis.length === 0) return null;
  return (
    <div
      data-testid="insight-card-kpis"
      role="region"
      aria-label="Key metrics"
      className="px-4 py-3 border-b border-[color:var(--cp-border-subtle)]"
    >
      <div
        className="flex gap-3 overflow-x-auto sm:overflow-visible sm:grid sm:grid-cols-2 xl:grid-cols-4 snap-x snap-mandatory -mx-1 px-1 scrollbar-thin"
        role="list"
      >
        {kpis.map((k, i) => {
          const tone = SEVERITY_META[k.tone] || null;
          const ariaLabel = `${k.label}: ${k.value}${k.sublabel ? `, ${k.sublabel}` : ""}`;
          return (
            <div
              key={`${k.label}-${i}`}
              data-testid={`insight-card-kpi-${i}`}
              role="listitem"
              aria-label={ariaLabel}
              className={`snap-start shrink-0 min-w-[42%] sm:min-w-0 sm:w-full rounded-xl border ${tone ? tone.accent : "border-[color:var(--cp-border-subtle)]"} ${tone ? tone.tint : "bg-[color:var(--cp-surface-1)]"} px-4 py-3 md:py-4`}
            >
              <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1 truncate">
                {k.label}
              </div>
              <div className={`text-lg md:text-xl font-bold cp-num flex items-center gap-1 leading-tight ${tone ? tone.text : "text-[color:var(--cp-text-primary)]"}`}>
                <span className="truncate">{k.value}</span>
                {trendIcon(k.trend)}
              </div>
              {k.sublabel && (
                <div className="text-[10px] text-slate-500 mt-1 truncate">{k.sublabel}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const FindingsBlock = ({ findings }) => {
  if (!findings || findings.length === 0) return null;
  return (
    <div
      data-testid="insight-card-findings"
      role="region"
      aria-label="Priority findings"
      className="px-4 py-3 border-b border-[color:var(--cp-border-subtle)] space-y-2"
    >
      <div className="text-[11px] font-semibold uppercase tracking-wide text-[color:var(--cp-text-secondary)] flex items-center gap-1.5">
        <AlertTriangle className="w-3 h-3" aria-hidden="true" />
        Priority findings
      </div>
      <ul className="list-none space-y-2 m-0 p-0">
      {findings.map((f, i) => (
        <li
          key={`${f.title}-${i}`}
          data-testid={`insight-card-finding-${i}`}
          className="rounded-lg border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-1)] px-3 py-2"
        >
          <div className="flex items-start gap-2">
            <span className={`mt-0.5 inline-flex items-center h-4 px-1.5 rounded text-[9px] font-semibold uppercase tracking-wide ${PRIORITY_CHIP[f.priority] || PRIORITY_CHIP.medium}`}>
              {f.priority || "med"}
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-[color:var(--cp-text-primary)] truncate">{f.title}</div>
              {f.detail && (
                <div className="text-[11px] text-[color:var(--cp-text-secondary)] mt-0.5">{f.detail}</div>
              )}
            </div>
          </div>
          {(f.impact_value || f.impact_label) && (
            <div className="mt-1.5 pt-1.5 border-t border-dashed border-[color:var(--cp-border-subtle)] flex items-baseline justify-between gap-2">
              {f.impact_label && (
                <span className="text-[10px] uppercase tracking-wide text-slate-400">{f.impact_label}</span>
              )}
              {f.impact_value && (
                <span className="text-xs font-semibold cp-num text-[color:var(--cp-text-primary)]">{f.impact_value}</span>
              )}
            </div>
          )}
        </li>
      ))}
      </ul>
    </div>
  );
};

const RecommendationBlock = ({ recommendation }) => {
  const [showRationale, setShowRationale] = useState(false);
  if (!recommendation) return null;
  return (
    <div
      data-testid="insight-card-recommendation"
      className="px-4 py-3 border-b border-[color:var(--cp-border-subtle)]"
    >
      <div className="text-[11px] font-semibold uppercase tracking-wide text-[color:var(--cp-text-secondary)] flex items-center gap-1.5 mb-1.5">
        <Sparkles className="w-3 h-3" />
        AI recommendation
        {recommendation.confidence_pct != null && (
          <span className="text-slate-400 normal-case font-normal cp-num">· {recommendation.confidence_pct}% confidence</span>
        )}
      </div>
      <p className="text-sm leading-relaxed text-[color:var(--cp-text-primary)]">
        {recommendation.summary}
      </p>
      {recommendation.rationale && (
        <>
          <button
            type="button"
            data-testid="insight-card-rationale-toggle"
            onClick={() => setShowRationale((v) => !v)}
            aria-expanded={showRationale}
            aria-controls="insight-card-rationale-body"
            className="mt-2 inline-flex items-center gap-1 text-[11px] text-[color:var(--cp-accent-brand)] hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--cp-accent-brand)]/40 rounded"
          >
            {showRationale
              ? <ChevronUp className="w-3 h-3" aria-hidden="true" />
              : <ChevronDown className="w-3 h-3" aria-hidden="true" />}
            {showRationale ? "Hide rationale" : "Why this recommendation?"}
          </button>
          {showRationale && (
            <p
              id="insight-card-rationale-body"
              className="mt-1.5 text-xs leading-relaxed text-[color:var(--cp-text-secondary)]"
            >
              {recommendation.rationale}
            </p>
          )}
        </>
      )}
    </div>
  );
};

const ImpactBlock = ({ impact }) => {
  if (!impact) return null;
  const tone = SEVERITY_META[impact.delta_tone] || SEVERITY_META.healthy;
  return (
    <div
      data-testid="insight-card-impact"
      className="px-4 py-3 border-b border-[color:var(--cp-border-subtle)]"
    >
      <div className="text-[11px] font-semibold uppercase tracking-wide text-[color:var(--cp-text-secondary)] mb-2">
        Impact preview
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-1)] px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">{impact.before_label}</div>
          <div className="text-sm font-semibold cp-num text-[color:var(--cp-text-primary)]">{impact.before_value}</div>
        </div>
        <div className={`rounded-lg border ${tone.accent} ${tone.tint} px-3 py-2`}>
          <div className="text-[10px] uppercase tracking-wide text-slate-400">{impact.after_label}</div>
          <div className={`text-sm font-semibold cp-num ${tone.text}`}>{impact.after_value}</div>
        </div>
      </div>
      {impact.delta_label && (
        <div className={`mt-2 text-[11px] font-medium ${tone.text} text-center`}>{impact.delta_label}</div>
      )}
    </div>
  );
};

const ACTION_STYLES = {
  primary:   "bg-[color:var(--cp-accent-brand)] text-white shadow-sm hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--cp-accent-brand)]/40",
  secondary: "border border-[color:var(--cp-border-subtle)] text-[color:var(--cp-text-primary)] hover:border-[color:var(--cp-accent-brand)] hover:text-[color:var(--cp-accent-brand)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--cp-accent-brand)]/40",
  tertiary:  "text-[color:var(--cp-text-secondary)] hover:text-[color:var(--cp-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--cp-accent-brand)]/40 rounded",
};

const ActionsBlock = ({ actions, onAction, envelope }) => {
  if (!actions || actions.length === 0) return null;
  return (
    <div
      data-testid="insight-card-actions"
      role="group"
      aria-label="Recommended actions"
      className="px-4 py-3 border-b border-[color:var(--cp-border-subtle)] flex flex-wrap gap-2"
    >
      {actions.map((a, i) => (
        <button
          key={a.action_id || i}
          type="button"
          data-testid={`insight-card-action-${a.action_id || i}`}
          onClick={() => onAction && onAction(a.action_id, { action: a, envelope })}
          className={`px-3 py-1.5 text-xs font-medium rounded-full ${ACTION_STYLES[a.style] || ACTION_STYLES.secondary}`}
        >
          {a.label}
        </button>
      ))}
    </div>
  );
};

const EducationBlock = ({ education }) => {
  const [open, setOpen] = useState(false);
  if (!education) return null;
  return (
    <div
      data-testid="insight-card-education"
      className="px-4 py-3 border-b border-[color:var(--cp-border-subtle)]"
    >
      <button
        type="button"
        data-testid="insight-card-education-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="insight-card-education-body"
        className="w-full flex items-center justify-between text-[11px] font-semibold uppercase tracking-wide text-[color:var(--cp-text-secondary)] hover:text-[color:var(--cp-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--cp-accent-brand)]/40 rounded"
      >
        <span className="inline-flex items-center gap-1.5">
          <GraduationCap className="w-3 h-3" aria-hidden="true" />
          {education.heading}
        </span>
        {open
          ? <ChevronUp className="w-3 h-3" aria-hidden="true" />
          : <ChevronDown className="w-3 h-3" aria-hidden="true" />}
      </button>
      {open && (
        <p
          id="insight-card-education-body"
          className="mt-2 text-xs leading-relaxed text-[color:var(--cp-text-secondary)]"
        >
          {education.body}
        </p>
      )}
    </div>
  );
};

const SuggestionsBlock = ({ suggestions, onAction, envelope }) => {
  if (!suggestions || suggestions.length === 0) return null;
  return (
    <div
      data-testid="insight-card-suggestions"
      className="px-4 py-3"
    >
      <div className="text-[11px] font-semibold uppercase tracking-wide text-[color:var(--cp-text-secondary)] mb-1.5">
        Ask a follow-up
      </div>
      <div
        className="flex gap-2 overflow-x-auto sm:flex-wrap snap-x -mx-1 px-1 scrollbar-thin"
        role="list"
        aria-label="Suggested follow-up questions"
      >
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            role="listitem"
            onClick={() => onAction && onAction("suggestion", { suggestion: s, envelope })}
            className="snap-start shrink-0 px-2.5 py-1 text-[11px] rounded-full border border-[color:var(--cp-border-subtle)] text-slate-600 dark:text-slate-300 hover:border-[color:var(--cp-accent-brand)] hover:text-[color:var(--cp-accent-brand)] whitespace-nowrap focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--cp-accent-brand)]/40"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
};

const InsightCardWidget = ({ envelope, onAction, testId }) => {
  if (!envelope) return null;
  const {
    title,
    freshness,
    agent,
    data = {},
    primary_cta,
    suggestions = [],
  } = envelope;
  const {
    hero,
    kpis = [],
    findings = [],
    recommendation,
    impact,
    actions = [],
    education,
  } = data;

  if (!hero) {
    // The card must have a hero; without it there's no headline. Render
    // nothing so an upstream renderer can fall back gracefully.
    return null;
  }

  return (
    <div
      data-testid={testId || "widget-insight-card"}
      className="rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60 overflow-hidden"
    >
      <header className="px-4 pt-3 pb-2 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-medium text-[color:var(--cp-text-secondary)] truncate">{title}</div>
          <div className="mt-0.5"><AgentRibbon agent={agent} compact /></div>
        </div>
        <FreshnessChip
          state={freshness?.state || "cached"}
          lastUpdated={freshness?.last_updated}
          source={freshness?.source || []}
          ageSeconds={freshness?.age_seconds}
          confidence={freshness?.confidence}
        />
      </header>

      <HeroBlock hero={hero} />

      {/* Dashboard-style grid: KPIs + Findings on the left, AI
          Recommendation + Education on the right at lg+. Stacks
          vertically at narrower widths so mobile still feels native. */}
      <div className="md:grid md:grid-cols-3 md:gap-0">
        <div className="md:col-span-2 md:border-r md:border-[color:var(--cp-border-subtle)]">
          <KpiCarousel kpis={kpis} />
          <FindingsBlock findings={findings} />
          <ImpactBlock impact={impact} />
        </div>
        <div className="md:col-span-1">
          <RecommendationBlock recommendation={recommendation} />
          <EducationBlock education={education} />
        </div>
      </div>

      <ActionsBlock actions={actions} onAction={onAction} envelope={envelope} />
      <SuggestionsBlock suggestions={suggestions} onAction={onAction} envelope={envelope} />

      {primary_cta && (
        <div
          data-testid="insight-card-sticky-cta"
          className="sm:hidden sticky bottom-0 left-0 right-0 px-4 py-2.5 bg-[color:var(--cp-surface-base)]/95 backdrop-blur border-t border-[color:var(--cp-border-subtle)]"
        >
          <button
            type="button"
            data-testid={`${testId || "widget-insight-card"}-primary-cta`}
            onClick={() => onAction && onAction(primary_cta.action, envelope)}
            aria-label={primary_cta.label}
            className="w-full px-4 py-2.5 text-sm font-semibold rounded-full text-white shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--cp-accent-brand)]/60 focus-visible:ring-offset-2"
            style={{ background: "var(--cp-accent-brand)" }}
          >
            {primary_cta.label}
          </button>
        </div>
      )}
    </div>
  );
};

export default InsightCardWidget;
