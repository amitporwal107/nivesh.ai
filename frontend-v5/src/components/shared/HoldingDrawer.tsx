/**
 * HoldingDrawer — shared slide-in detail panel for a single holding.
 *
 * Used by:
 *   - Holdings table row click (AC-20)
 *   - Performance heatmap cell click
 *   - Benchmark donut segment click (future)
 *
 * Animation: CSS transition at 200ms ease-out, gated on prefers-reduced-motion
 * (per UX decisions Step 2 / UX-2). No Framer Motion dependency needed.
 *
 * Accessibility: focus-trap via inert attribute on the rest of the page,
 * Escape key closes, aria-modal + role="dialog" on the panel.
 */

import React, { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { EnrichedHoldingC } from '../../services/contracts/portfolio.contract';
import type { z } from 'zod';
type EnrichedHolding = z.infer<typeof EnrichedHoldingC>;
import { formatINRCompact } from '../../lib/formatters';
import { http } from '../../services/api/http';

// ── Holding Detail (DaaS) types ──────────────────────────────────────────────

interface HoldingDetailReturns { '1m': number | null; '3m': number | null; '1y': number | null; '3y': number | null; }
interface HoldingDetailCategoryAvg { '1y': number | null; '3y': number | null; }
interface HoldingDetailRisk { sharpe: number | null; sortino: number | null; volatility_1y: number | null; max_drawdown: number | null; }
interface HoldingDetailRanking { composite_rank: number | null; category_size: number | null; top_position_pct: number | null; }
interface HoldingDetailPeer { name: string | null; return_1y: number | null; composite_rank: number | null; }

interface HoldingDetail {
  isin: string;
  name: string | null;
  category: string | null;
  returns: HoldingDetailReturns;
  category_avg: HoldingDetailCategoryAvg;
  risk: HoldingDetailRisk;
  ranking: HoldingDetailRanking;
  top_peers: HoldingDetailPeer[];
  daas_available: boolean;
}

async function fetchHoldingDetail(isin: string): Promise<HoldingDetail> {
  const res = await http<HoldingDetail>({ path: `/api/portfolio/holding-detail/${encodeURIComponent(isin)}` });
  return res.data;
}

const formatInr = formatINRCompact;

interface HoldingDrawerProps {
  holding: EnrichedHolding | null;
  onClose: () => void;
}

export function HoldingDrawer({ holding, onClose }: HoldingDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const open = holding !== null;

  // Fetch DaaS detail when drawer opens (only for ISINs)
  const isin = holding?.isin ?? null;
  const {
    data: detail,
    isLoading: detailLoading,
  } = useQuery<HoldingDetail>({
    queryKey: ['holding-detail', isin],
    queryFn: () => fetchHoldingDetail(isin!),
    enabled: open && !!isin,
    staleTime: 5 * 60 * 1000,   // 5 min
    retry: 1,
  });

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // Trap focus inside drawer when open
  useEffect(() => {
    if (!open) return;
    const el = panelRef.current;
    if (!el) return;
    el.focus();
  }, [open]);

  if (!open) return null;

  const h = holding!;
  const pnlPositive = (h.pnl_pct ?? 0) >= 0;
  const amfiUnmatched = (h as any).amfi_matched === false;

  return (
    <>
      {/* Backdrop */}
      <div
        role="presentation"
        className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
        style={{ transition: 'opacity 200ms ease-out' }}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`${h.name} holding detail`}
        tabIndex={-1}
        className="fixed right-0 top-0 z-50 h-full w-full max-w-md overflow-y-auto outline-none"
        style={{
          background: 'rgb(var(--surface-2))',
          borderLeft: '1px solid rgba(var(--line) / 0.12)',
          transition: 'transform 200ms ease-out',
          '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
        } as React.CSSProperties}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 p-5"
          style={{ background: 'rgb(var(--surface-2))', borderBottom: '1px solid rgba(var(--line) / 0.10)' }}>
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-widest opacity-50 mb-1"
              style={{ fontFamily: 'var(--font-mono)' }}>
              {h.asset_type?.replace('_', ' ')}
            </p>
            <h2 className="text-base font-semibold leading-snug" style={{ color: 'rgb(var(--ink-1))' }}>
              {h.name}
            </h2>
            {h.isin && (
              <p className="text-xs mt-0.5 opacity-40" style={{ fontFamily: 'var(--font-mono)' }}>
                {h.isin}
                {amfiUnmatched && (
                  <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded-sm"
                    style={{ background: 'rgb(var(--warm) / 0.15)', color: 'rgb(var(--warm))' }}
                    title="This fund is not matched in the AMFI registry. Benchmark and attribution data unavailable.">
                    AMFI unmatched
                  </span>
                )}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close holding detail"
            className="shrink-0 p-1.5 rounded opacity-50 hover:opacity-100 transition-opacity"
            style={{ color: 'rgb(var(--ink-1))' }}>
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-5">

          {/* KPI row */}
          <div className="grid grid-cols-2 gap-3">
            <Kpi label="Current value" value={h.value_rs != null ? formatInr(h.value_rs) : '—'} />
            <Kpi label="Invested" value={h.invested_rs != null ? formatInr(h.invested_rs) : '—'} />
            <Kpi
              label="P&L"
              value={h.pnl_rs != null ? formatInr(h.pnl_rs) : '—'}
              sub={h.pnl_pct != null ? `${pnlPositive ? '+' : ''}${h.pnl_pct.toFixed(1)}%` : undefined}
              tone={h.pnl_rs != null ? (pnlPositive ? 'positive' : 'negative') : 'neutral'}
            />
            <Kpi
              label="XIRR"
              value={h.xirr_pct != null ? `${h.xirr_pct > 0 ? '+' : ''}${h.xirr_pct.toFixed(1)}%` : '—'}
              tone={h.xirr_pct != null ? (h.xirr_pct >= 0 ? 'positive' : 'negative') : 'neutral'}
            />
          </div>

          <Divider />

          {/* Holdings details */}
          <div className="space-y-2">
            <Row label="Units / Qty" value={h.quantity != null ? h.quantity.toLocaleString('en-IN', { maximumFractionDigits: 3 }) : '—'} />
            <Row label="Current NAV / price" value={h.current_price != null ? formatInr(h.current_price) : '—'} />
            {h.buy_price != null && <Row label="Avg buy price" value={formatInr(h.buy_price)} />}
            {h.buy_date && <Row label="Buy date" value={h.buy_date} />}
            {h.weight_pct != null && <Row label="Portfolio weight" value={`${h.weight_pct.toFixed(2)}%`} />}
            {(h as any).asset_class && <Row label="Asset class" value={(h as any).asset_class} />}
            {h.sector && <Row label="Sector" value={h.sector} />}
            {h.category && <Row label="Category" value={h.category} />}
          </div>

          {/* Benchmark / attribution (AMFI-unmatched guard) */}
          {amfiUnmatched ? (
            <div className="rounded-lg p-3 text-sm"
              style={{ background: 'rgb(var(--warm) / 0.08)', color: 'rgb(var(--warm))' }}>
              <span aria-label="Benchmark data unavailable — fund not AMFI-matched">
                Benchmark and attribution data unavailable for this fund.
              </span>
            </div>
          ) : (
            <>
              {(h as any).benchmark_return != null && (
                <>
                  <Divider />
                  <div className="space-y-2">
                    <Row label="Benchmark return (1Y)" value={`${((h as any).benchmark_return as number).toFixed(1)}%`} />
                    {(h as any).benchmark_delta != null && (
                      <Row
                        label="Alpha vs benchmark"
                        value={`${(h as any).benchmark_delta > 0 ? '+' : ''}${((h as any).benchmark_delta as number).toFixed(1)} pp`}
                        tone={(h as any).benchmark_delta >= 0 ? 'positive' : 'negative'}
                      />
                    )}
                  </div>
                </>
              )}
            </>
          )}

          {/* Action badge */}
          {h.action_badge && (
            <>
              <Divider />
              <div>
                <p className="text-xs uppercase tracking-widest opacity-50 mb-2"
                  style={{ fontFamily: 'var(--font-mono)' }}>Recommendation</p>
                <span className="inline-block text-xs px-2 py-1 rounded"
                  style={{ background: 'rgb(var(--mint) / 0.12)', color: 'rgb(var(--mint))' }}>
                  {typeof h.action_badge === 'string' ? h.action_badge : (h.action_badge as any).action}
                </span>
              </div>
            </>
          )}

          {/* ── Performance & Scoring (DaaS) ── */}
          {isin && (
            <>
              <Divider />
              <PerformanceSection detail={detail ?? null} loading={detailLoading} />
            </>
          )}
        </div>
      </div>
    </>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────────

type Tone = 'positive' | 'negative' | 'neutral';

function Kpi({ label, value, sub, tone = 'neutral' }: {
  label: string; value: string; sub?: string; tone?: Tone;
}) {
  const color = tone === 'positive' ? 'rgb(var(--mint))' : tone === 'negative' ? 'rgb(var(--danger))' : 'rgb(var(--ink-1))';
  return (
    <div className="rounded-lg p-3" style={{ background: 'rgb(var(--surface-3))' }}>
      <p className="text-xs opacity-50 mb-1" style={{ fontFamily: 'var(--font-mono)' }}>{label}</p>
      <p className="text-lg font-semibold" style={{ color, fontFamily: 'var(--font-mono)' }}>{value}</p>
      {sub && (
        <p className="text-xs mt-0.5" style={{ color }}>
          {tone === 'positive' ? '▲' : tone === 'negative' ? '▼' : ''} {sub}
        </p>
      )}
    </div>
  );
}

function Row({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: Tone }) {
  const color = tone === 'positive' ? 'rgb(var(--mint))' : tone === 'negative' ? 'rgb(var(--danger))' : 'rgb(var(--ink-1))';
  return (
    <div className="flex justify-between items-baseline gap-3">
      <span className="text-sm opacity-50 shrink-0">{label}</span>
      <span className="text-sm font-medium text-right" style={{ color, fontFamily: 'var(--font-mono)' }}>{value}</span>
    </div>
  );
}

function Divider() {
  return <div className="h-px" style={{ background: 'rgba(var(--line) / 0.08)' }} />;
}

// ── Performance & Scoring section ────────────────────────────────────────────

function SkeletonLine({ w = 'w-24' }: { w?: string }) {
  return (
    <div
      className={`h-3 rounded animate-pulse ${w}`}
      style={{ background: 'rgba(var(--line) / 0.15)' }}
    />
  );
}

function ReturnCell({ value, categoryAvg, label }: {
  value: number | null;
  categoryAvg: number | null;
  label: string;
}) {
  const hasValue = value !== null;
  const positive = hasValue && value! >= 0;
  const valueColor = hasValue
    ? positive ? 'rgb(var(--mint))' : 'rgb(var(--danger))'
    : 'rgb(var(--ink-2))';

  return (
    <div className="flex flex-col gap-0.5 items-center">
      <span className="text-[10px] uppercase tracking-wider opacity-40" style={{ fontFamily: 'var(--font-mono)' }}>
        {label}
      </span>
      <span className="text-sm font-semibold" style={{ color: valueColor, fontFamily: 'var(--font-mono)' }}>
        {hasValue ? `${positive ? '+' : ''}${value!.toFixed(1)}%` : '—'}
      </span>
      {categoryAvg !== null && (
        <span className="text-[10px] opacity-40" style={{ fontFamily: 'var(--font-mono)' }}>
          avg {categoryAvg >= 0 ? '+' : ''}{categoryAvg.toFixed(1)}%
        </span>
      )}
    </div>
  );
}

function PerformanceSection({ detail, loading }: { detail: HoldingDetail | null; loading: boolean }) {
  return (
    <div className="space-y-4">
      <p className="text-xs uppercase tracking-widest opacity-50" style={{ fontFamily: 'var(--font-mono)' }}>
        Performance &amp; Scoring
      </p>

      {loading ? (
        <div className="space-y-3">
          <div className="flex justify-between gap-2">
            {['1M', '3M', '1Y', '3Y'].map((l) => (
              <div key={l} className="flex flex-col items-center gap-1">
                <SkeletonLine w="w-8" />
                <SkeletonLine w="w-14" />
                <SkeletonLine w="w-12" />
              </div>
            ))}
          </div>
          <SkeletonLine w="w-full" />
          <SkeletonLine w="w-3/4" />
        </div>
      ) : !detail || !detail.daas_available ? (
        <div
          className="rounded-lg p-3 text-sm"
          style={{ background: 'rgb(var(--surface-3))', color: 'rgb(var(--ink-2))' }}
        >
          Data not available — this fund is not yet in the NIDP analytics lake.
        </div>
      ) : (
        <div className="space-y-4">

          {/* Returns table: 1M / 3M / 1Y / 3Y */}
          <div
            className="rounded-lg p-3"
            style={{ background: 'rgb(var(--surface-3))' }}
          >
            <p className="text-[10px] uppercase tracking-wider opacity-40 mb-3" style={{ fontFamily: 'var(--font-mono)' }}>
              Returns (fund vs category avg)
            </p>
            <div className="grid grid-cols-4 gap-2">
              <ReturnCell value={detail.returns['1m']} categoryAvg={null} label="1M" />
              <ReturnCell value={detail.returns['3m']} categoryAvg={null} label="3M" />
              <ReturnCell value={detail.returns['1y']} categoryAvg={detail.category_avg['1y']} label="1Y" />
              <ReturnCell value={detail.returns['3y']} categoryAvg={detail.category_avg['3y']} label="3Y" />
            </div>
          </div>

          {/* Risk row: Sharpe / Volatility / Max Drawdown */}
          <div className="space-y-2">
            <p className="text-[10px] uppercase tracking-wider opacity-40" style={{ fontFamily: 'var(--font-mono)' }}>
              Risk metrics
            </p>
            {detail.risk.sharpe !== null && (
              <Row label="Sharpe ratio" value={detail.risk.sharpe.toFixed(2)}
                tone={detail.risk.sharpe >= 1 ? 'positive' : detail.risk.sharpe < 0 ? 'negative' : 'neutral'} />
            )}
            {detail.risk.sortino !== null && (
              <Row label="Sortino ratio" value={detail.risk.sortino.toFixed(2)}
                tone={detail.risk.sortino >= 1 ? 'positive' : detail.risk.sortino < 0 ? 'negative' : 'neutral'} />
            )}
            {detail.risk.volatility_1y !== null && (
              <Row label="Volatility (1Y)" value={`${detail.risk.volatility_1y.toFixed(1)}%`} />
            )}
            {detail.risk.max_drawdown !== null && (
              <Row label="Max drawdown" value={`${detail.risk.max_drawdown.toFixed(1)}%`} tone="negative" />
            )}
            {detail.risk.sharpe === null && detail.risk.volatility_1y === null && (
              <span className="text-xs opacity-40">No risk data available</span>
            )}
          </div>

          {/* Category rank */}
          {detail.ranking.composite_rank !== null && (
            <div
              className="rounded-lg p-3"
              style={{ background: 'rgb(var(--surface-3))' }}
            >
              <p className="text-[10px] uppercase tracking-wider opacity-40 mb-1" style={{ fontFamily: 'var(--font-mono)' }}>
                Category rank
              </p>
              <p className="text-sm font-semibold" style={{ color: 'rgb(var(--ink-1))', fontFamily: 'var(--font-mono)' }}>
                {detail.ranking.composite_rank}
                {detail.ranking.category_size !== null && ` of ${detail.ranking.category_size}`}
                {detail.category && ` in ${detail.category}`}
              </p>
              {detail.ranking.top_position_pct !== null && (
                <p className="text-xs mt-0.5 opacity-50">
                  Top {detail.ranking.top_position_pct.toFixed(0)}% of category
                </p>
              )}
            </div>
          )}

          {/* Top 3 peers */}
          {detail.top_peers.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] uppercase tracking-wider opacity-40" style={{ fontFamily: 'var(--font-mono)' }}>
                Top peers in category
              </p>
              {detail.top_peers.map((peer, i) => (
                <div key={i} className="flex justify-between items-baseline gap-2">
                  <span className="text-xs opacity-60 truncate min-w-0">{peer.name ?? '—'}</span>
                  <span className="text-xs shrink-0" style={{
                    fontFamily: 'var(--font-mono)',
                    color: peer.return_1y != null
                      ? peer.return_1y >= 0 ? 'rgb(var(--mint))' : 'rgb(var(--danger))'
                      : 'rgb(var(--ink-2))',
                  }}>
                    {peer.return_1y != null
                      ? `${peer.return_1y >= 0 ? '+' : ''}${peer.return_1y.toFixed(1)}%`
                      : '—'}
                  </span>
                </div>
              ))}
            </div>
          )}

        </div>
      )}
    </div>
  );
}
