import React, { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { AlertTriangle, ChevronDown, ChevronRight, AlertOctagon, Info } from 'lucide-react';

// ── Score colouring ──────────────────────────────────────────────────────
const scoreTone = (v) => {
  if (v == null) return 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400';
  if (v >= 75) return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300';
  if (v >= 55) return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
  return 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300';
};

// Exit score is interpreted inverted: high = bad (stronger exit recommendation)
const exitTone = (v) => {
  if (v == null) return 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400';
  if (v >= 75) return 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300';
  if (v >= 60) return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
  return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300';
};

const switchTone = (v) => {
  if (v == null) return 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400';
  if (v >= 2.0) return 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300';
  if (v >= 1.0) return 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300';
  return 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400';
};

const ScorePill = ({ label, value, tone, suffix = '/100', testid }) => (
  <div
    data-testid={testid}
    className={`flex flex-col items-center justify-center rounded-md px-2 py-1 min-w-[52px] ${tone}`}
    title={value == null ? `${label}: not available` : `${label}: ${value}`}
  >
    <span className="text-[9px] font-bold uppercase tracking-wider opacity-80">{label}</span>
    <span className="text-sm font-bold tabular-nums leading-tight">
      {value == null ? '—' : (typeof value === 'number' ? value.toFixed(value < 10 ? 1 : 0) : value)}
      {value != null && suffix && <span className="text-[9px] font-normal opacity-60 ml-0.5">{suffix}</span>}
    </span>
  </div>
);

// ── Renders explanation markdown (**bold** only) ─────────────────────────
const renderExplanation = (text) => {
  if (!text) return null;
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) {
      return (
        <strong key={i} className="font-semibold text-slate-900 dark:text-slate-100">
          {p.slice(2, -2)}
        </strong>
      );
    }
    return <span key={i}>{p}</span>;
  });
};

// ── Danger banner ────────────────────────────────────────────────────────
const DangerBanner = ({ danger }) => {
  if (!danger || danger.level === 'ok') return null;
  const isCritical = danger.level === 'critical';
  const tone = isCritical
    ? 'bg-rose-50 border-rose-200 text-rose-800 dark:bg-rose-950/40 dark:border-rose-900/60 dark:text-rose-300'
    : 'bg-amber-50 border-amber-200 text-amber-800 dark:bg-amber-950/40 dark:border-amber-900/60 dark:text-amber-300';
  const Icon = isCritical ? AlertOctagon : AlertTriangle;
  return (
    <div className={`flex items-start gap-2 mt-2 rounded-md border px-3 py-2 text-xs ${tone}`}
         data-testid={`danger-banner-${danger.level}`}>
      <Icon className="w-3.5 h-3.5 shrink-0 mt-0.5" />
      <div className="flex-1">
        <div className="font-semibold uppercase tracking-wide text-[10px] mb-0.5">
          {isCritical ? 'Critical — action recommended' : 'Warning — review'}
        </div>
        <ul className="list-disc list-inside space-y-0.5 leading-snug">
          {(danger.reasons || []).map((r, i) => (
            <li key={i}><span>{r.message}</span></li>
          ))}
        </ul>
      </div>
    </div>
  );
};

// ── Per-fund row ─────────────────────────────────────────────────────────
const FundRow = ({ fund }) => {
  const [expanded, setExpanded] = useState(false);
  const s = fund.scores || {};
  const danger = fund.danger || {};
  const isCritical = danger.level === 'critical';
  const isWarning = danger.level === 'warning';
  const borderTone = isCritical
    ? 'border-l-rose-500'
    : isWarning
      ? 'border-l-amber-500'
      : 'border-l-transparent';

  const missingQ = s.quality_missing?.length || 0;
  const missingH = s.health_missing?.length || 0;

  return (
    <div
      className={`rounded-lg border border-slate-200 dark:border-slate-700 border-l-4 ${borderTone} bg-white dark:bg-slate-900 overflow-hidden`}
      data-testid={`v3-fund-row-${fund.instrument_id || fund.scheme_name}`}
    >
      <button
        type="button"
        onClick={() => setExpanded(x => !x)}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
        data-testid={`v3-fund-toggle-${fund.instrument_id || fund.scheme_name}`}
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-800 dark:text-slate-200 truncate"
                  title={fund.scheme_name}>
              {fund.scheme_name}
            </span>
            {isCritical && (
              <Badge className="text-[9px] bg-rose-600 text-white hover:bg-rose-600 h-4 px-1.5">
                DANGER
              </Badge>
            )}
            {isWarning && (
              <Badge className="text-[9px] bg-amber-500 text-white hover:bg-amber-500 h-4 px-1.5">
                WARN
              </Badge>
            )}
            {fund.plan_type === 'regular' && (
              <Badge variant="outline" className="text-[9px] h-4 px-1.5 border-slate-300 text-slate-600 dark:text-slate-400">
                Regular
              </Badge>
            )}
          </div>
          <div className="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">
            ₹{Math.round(fund.value_rs || 0).toLocaleString('en-IN')}
            {fund.cost_leak_rs_per_yr ? ` · ~₹${Math.round(fund.cost_leak_rs_per_yr).toLocaleString('en-IN')}/yr cost leak` : ''}
            {(missingQ + missingH > 0) && ` · ${missingQ + missingH} primitives missing`}
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <ScorePill label="Q" value={s.quality} tone={scoreTone(s.quality)} testid={`v3-q-${fund.instrument_id || fund.scheme_name}`} />
          <ScorePill label="H" value={s.health} tone={scoreTone(s.health)} testid={`v3-h-${fund.instrument_id || fund.scheme_name}`} />
          <ScorePill label="E" value={s.exit} tone={exitTone(s.exit)} testid={`v3-e-${fund.instrument_id || fund.scheme_name}`} />
          <ScorePill label="A" value={s.add} tone={scoreTone(s.add)} testid={`v3-a-${fund.instrument_id || fund.scheme_name}`} />
          <ScorePill label="SW" value={s.switch} tone={switchTone(s.switch)} suffix="" testid={`v3-sw-${fund.instrument_id || fund.scheme_name}`} />
        </div>
      </button>
      {expanded && (
        <div className="px-4 pb-3 pt-1 border-t border-slate-100 dark:border-slate-800">
          <div className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed mt-2"
               data-testid={`v3-fund-explain-${fund.instrument_id || fund.scheme_name}`}>
            {renderExplanation(fund.explanation)}
          </div>
          <DangerBanner danger={danger} />
          {/* Primitives summary */}
          {fund.primitives && (
            <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
              {Object.entries(fund.primitives).filter(([, v]) => v != null).map(([k, v]) => (
                <div key={k} className="rounded bg-slate-50 dark:bg-slate-800/60 px-2 py-1">
                  <div className="text-[9px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
                    {k.replace(/_/g, ' ')}
                  </div>
                  <div className="font-mono tabular-nums text-slate-800 dark:text-slate-200">
                    {typeof v === 'number' ? (Math.abs(v) > 100 ? v.toFixed(0) : v.toFixed(2)) : String(v)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ── Public component ─────────────────────────────────────────────────────
export default function V3FundBreakdown({ funds = [], portfolio = {} }) {
  const [filter, setFilter] = useState('all');

  const filtered = funds.filter(f => {
    if (filter === 'all') return true;
    if (filter === 'danger') return (f.danger?.level) === 'critical' || (f.danger?.level) === 'warning';
    if (filter === 'critical') return (f.danger?.level) === 'critical';
    return true;
  });

  const nCritical = portfolio.n_danger_critical ?? funds.filter(f => f.danger?.level === 'critical').length;
  const nWarning = portfolio.n_danger_warning ?? funds.filter(f => f.danger?.level === 'warning').length;

  return (
    <div className="space-y-3" data-testid="v3-fund-breakdown">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Per-fund V3 breakdown
          </h3>
          <Info className="w-3.5 h-3.5 text-slate-400" aria-label="Click any fund to see the full score explanation." />
        </div>
        <div className="flex items-center gap-1 text-xs" data-testid="v3-breakdown-filters">
          <button
            type="button"
            onClick={() => setFilter('all')}
            className={`px-2 py-1 rounded border ${filter === 'all'
              ? 'bg-slate-800 text-white border-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:border-slate-100'
              : 'bg-white text-slate-600 border-slate-200 dark:bg-slate-900 dark:text-slate-400 dark:border-slate-700'}`}
            data-testid="v3-filter-all"
          >
            All · {funds.length}
          </button>
          <button
            type="button"
            onClick={() => setFilter('danger')}
            className={`px-2 py-1 rounded border ${filter === 'danger'
              ? 'bg-amber-500 text-white border-amber-500'
              : 'bg-white text-amber-700 border-amber-200 dark:bg-slate-900 dark:text-amber-300 dark:border-amber-900/60'}`}
            data-testid="v3-filter-danger"
          >
            Danger · {nCritical + nWarning}
          </button>
          <button
            type="button"
            onClick={() => setFilter('critical')}
            className={`px-2 py-1 rounded border ${filter === 'critical'
              ? 'bg-rose-600 text-white border-rose-600'
              : 'bg-white text-rose-700 border-rose-200 dark:bg-slate-900 dark:text-rose-300 dark:border-rose-900/60'}`}
            data-testid="v3-filter-critical"
          >
            Critical · {nCritical}
          </button>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center flex-wrap gap-3 text-[10px] text-slate-500 dark:text-slate-400">
        <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-emerald-500" /> ≥75 strong</span>
        <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-amber-500" /> 55–74 watch</span>
        <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-rose-500" /> &lt;55 weak</span>
        <span className="ml-2 opacity-75">Q=Quality · H=Health · E=Exit (higher = stronger exit signal) · A=Add · SW=Switch score (Regular plans only, ≥2.0 = recommended)</span>
      </div>

      <div className="space-y-2">
        {filtered.length === 0 ? (
          <div className="text-xs text-slate-500 dark:text-slate-400 italic py-4 text-center">
            No funds match this filter.
          </div>
        ) : (
          filtered.map((f, i) => (
            <FundRow key={(f.instrument_id || f.scheme_name) + i} fund={f} />
          ))
        )}
      </div>
    </div>
  );
}
