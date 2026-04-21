import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { AlertTriangle, Award, RefreshCw, Shield } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const scoreTone = (v) => {
  if (v == null) return { dot: 'bg-slate-300', text: 'text-slate-500' };
  if (v >= 75) return { dot: 'bg-emerald-500', text: 'text-emerald-700' };
  if (v >= 55) return { dot: 'bg-amber-500', text: 'text-amber-700' };
  return { dot: 'bg-rose-500', text: 'text-rose-700' };
};

const ScoreTile = ({ label, value, sub, testid }) => {
  const tone = scoreTone(value);
  return (
    <div
      data-testid={testid}
      className="flex flex-col gap-1 rounded-xl border border-slate-200 bg-white px-4 py-3 dark:bg-slate-900 dark:border-slate-700"
    >
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-400">
          {label}
        </span>
      </div>
      <div className="flex items-end gap-1">
        <span className={`text-2xl font-bold tabular-nums ${tone.text}`}>
          {value == null ? '—' : Math.round(value)}
        </span>
        <span className="text-xs text-slate-400 mb-1">/100</span>
      </div>
      {sub && <span className="text-[11px] text-slate-500 dark:text-slate-400">{sub}</span>}
    </div>
  );
};

export default function V3PortfolioInsights() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`${API}/api/insights/v3-portfolio`, {
        withCredentials: true,
      });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) {
    return (
      <Card className="p-6 animate-pulse" data-testid="v3-insights-loading">
        <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-40 mb-3" />
        <div className="h-20 bg-slate-100 dark:bg-slate-800 rounded" />
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card className="p-6" data-testid="v3-insights-error">
        <p className="text-sm text-rose-600">Couldn't load V3 scoring: {error || 'no data'}</p>
      </Card>
    );
  }

  const { portfolio, coverage_pct, funds, flagged, engine_version } = data;
  const top = (funds || []).slice(0, 3);
  const bottom = [...(funds || [])].filter(f => f.scores?.quality != null).slice(-3).reverse();

  return (
    <div className="space-y-4" data-testid="v3-portfolio-insights">
      {/* Headline tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <ScoreTile
          testid="v3-avg-quality"
          label="Avg Quality"
          value={portfolio.avg_quality_score}
          sub="Value-weighted across portfolio"
        />
        <ScoreTile
          testid="v3-avg-health"
          label="Avg Health"
          value={portfolio.avg_health_score}
          sub="Manager, turnover, concentration"
        />
        <div
          data-testid="v3-coverage-tile"
          className="flex flex-col gap-1 rounded-xl border border-slate-200 bg-white px-4 py-3 dark:bg-slate-900 dark:border-slate-700"
        >
          <div className="flex items-center gap-2">
            <Shield className="w-3 h-3 text-slate-500" />
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-400">
              Coverage
            </span>
          </div>
          <div className="flex items-end gap-1">
            <span className="text-2xl font-bold tabular-nums text-slate-800 dark:text-slate-100">
              {coverage_pct}
            </span>
            <span className="text-xs text-slate-400 mb-1">%</span>
          </div>
          <span className="text-[11px] text-slate-500 dark:text-slate-400">
            {portfolio.n_scored}/{portfolio.n_funds} funds scored
          </span>
        </div>
        <div
          data-testid="v3-flagged-tile"
          className="flex flex-col gap-1 rounded-xl border border-slate-200 bg-white px-4 py-3 dark:bg-slate-900 dark:border-slate-700"
        >
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-3 h-3 text-amber-500" />
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-400">
              Flagged
            </span>
          </div>
          <div className="flex items-end gap-1">
            <span className="text-2xl font-bold tabular-nums text-amber-700">
              {portfolio.n_flagged}
            </span>
            <span className="text-xs text-slate-400 mb-1">funds</span>
          </div>
          <span className="text-[11px] text-slate-500 dark:text-slate-400">
            Quality &lt; 50 or Health &lt; 50
          </span>
        </div>
      </div>

      {/* Top + bottom list */}
      <Card className="p-5 dark:bg-slate-900 dark:border-slate-700" data-testid="v3-leaderboard">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Award className="w-4 h-4 text-emerald-600" />
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              V3 Scoring Leaderboard
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-[10px] font-mono">{engine_version}</Badge>
            <Button
              variant="ghost"
              size="sm"
              onClick={fetchData}
              className="h-7 px-2"
              data-testid="v3-refresh-button"
            >
              <RefreshCw className="w-3.5 h-3.5 mr-1" /> Refresh
            </Button>
          </div>
        </div>

        <div className="grid md:grid-cols-2 gap-4">
          <div data-testid="v3-top-funds">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-emerald-700 mb-2">
              Top performers
            </h4>
            <ul className="space-y-1.5">
              {top.map((f, i) => (
                <li
                  key={f.scheme_name + i}
                  className="flex items-center justify-between gap-3 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 px-3 py-2"
                >
                  <span className="text-xs text-slate-800 dark:text-slate-200 truncate" title={f.scheme_name}>
                    {f.scheme_name}
                  </span>
                  <span className="text-sm font-bold tabular-nums text-emerald-700">
                    {f.scores?.quality ? Math.round(f.scores.quality) : '—'}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div data-testid="v3-bottom-funds">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-rose-700 mb-2">
              Needs review
            </h4>
            <ul className="space-y-1.5">
              {bottom.map((f, i) => (
                <li
                  key={f.scheme_name + i}
                  className="flex items-center justify-between gap-3 rounded-lg bg-rose-50 dark:bg-rose-900/20 px-3 py-2"
                >
                  <span className="text-xs text-slate-800 dark:text-slate-200 truncate" title={f.scheme_name}>
                    {f.scheme_name}
                  </span>
                  <span className="text-sm font-bold tabular-nums text-rose-700">
                    {f.scores?.quality ? Math.round(f.scores.quality) : '—'}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Flagged section */}
        {flagged && flagged.length > 0 && (
          <div className="mt-4 pt-4 border-t border-slate-200 dark:border-slate-700" data-testid="v3-flagged-list">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-700 mb-2">
              Review recommended
            </h4>
            <ul className="space-y-1">
              {flagged.map((f, i) => (
                <li key={i} className="flex items-center gap-2 text-xs">
                  <AlertTriangle className="w-3 h-3 text-amber-500 shrink-0" />
                  <span className="text-slate-700 dark:text-slate-300 truncate" title={f.scheme_name}>
                    {f.scheme_name}
                  </span>
                  <Badge variant="outline" className="text-[10px] bg-amber-50 text-amber-800 border-amber-200">
                    {f.reason.replace('_', ' ')}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>
    </div>
  );
}
