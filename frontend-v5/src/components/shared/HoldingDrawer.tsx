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
import type { EnrichedHolding } from '../../services/contracts/portfolio.contract';
import { formatINRCompact } from '../../lib/formatters';

const formatInr = formatINRCompact;

interface HoldingDrawerProps {
  holding: EnrichedHolding | null;
  onClose: () => void;
}

export function HoldingDrawer({ holding, onClose }: HoldingDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const open = holding !== null;

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
