// ─── Nivesh · Concentration dashboard — desktop + mobile ───
// Hero chart is a treemap (best for showing weights at a glance + drill-down)

// pre-computed treemap layout — width 640, height 400, exact-proportional
const TM = {
  // sector blocks
  fin:    { x: 0,   y: 0,   w: 301, h: 272, label: 'Financials',   pct: 32, severity: 'amber',  alarm: true },
  tech:   { x: 301, y: 0,   w: 207, h: 272, label: 'Technology',   pct: 22, severity: 'indigo' },
  energy: { x: 508, y: 0,   w: 132, h: 272, label: 'Energy',       pct: 14, severity: 'neutral' },
  cons:   { x: 0,   y: 272, w: 220, h: 128, label: 'Consumer',     pct: 11, severity: 'neutral' },
  pharma: { x: 220, y: 272, w: 180, h: 128, label: 'Pharma',       pct: 9,  severity: 'mint' },
  auto:   { x: 400, y: 272, w: 140, h: 128, label: 'Auto',         pct: 7,  severity: 'neutral' },
  mat:    { x: 540, y: 272, w: 60,  h: 128, label: 'Materials',    pct: 3,  severity: 'neutral' },
  cash:   { x: 600, y: 272, w: 40,  h: 128, label: 'Cash',         pct: 2,  severity: 'neutral' },
};
// sub-cells, parent-relative offsets
const SUB = {
  fin: [
    { n: 'HDFC Bank',     p: 8.0, h: 68,    sel: true },
    { n: 'ICICI Bank',    p: 6.5, h: 55.25 },
    { n: 'Axis Bank',     p: 5.5, h: 46.75 },
    { n: 'Bajaj Finance', p: 4.5, h: 38.25 },
    { n: 'SBI',           p: 4.0, h: 34 },
    { n: 'HDFC Life',     p: 3.5, h: 29.75 },
  ],
  tech: [
    { n: 'Infosys',         p: 7, h: 86.5 },
    { n: 'TCS',             p: 6, h: 74.2 },
    { n: 'HCL Tech',        p: 4, h: 49.5 },
    { n: 'Wipro',           p: 3, h: 37.1 },
    { n: 'Tech Mahindra',   p: 2, h: 24.7 },
  ],
  energy: [
    { n: 'Reliance', p: 7, h: 136 },
    { n: 'ONGC',     p: 4, h: 78 },
    { n: 'NTPC',     p: 3, h: 58 },
  ],
  cons:   [{ n: 'HUL', p: 4, h: 46.5 }, { n: 'Nestle', p: 3, h: 34.9 }, { n: 'ITC', p: 2, h: 23.3 }, { n: 'Britannia', p: 2, h: 23.3 }],
  pharma: [{ n: 'Sun Pharma', p: 3.5, h: 49.8 }, { n: 'Dr Reddy', p: 3, h: 42.7 }, { n: 'Cipla', p: 2.5, h: 35.5 }],
  auto:   [{ n: 'Maruti', p: 3, h: 54.9 }, { n: 'M&M', p: 2, h: 36.6 }, { n: 'Tata Motors', p: 2, h: 36.6 }],
  mat:    [{ n: 'UltraTech', p: 3, h: 128 }],
  cash:   [{ n: 'Liquid', p: 2, h: 128 }],
};

function NVTreemap({ scale = 1 }) {
  const W = 640 * scale, H = 400 * scale;
  return (
    <svg viewBox="0 0 640 400" width={W} height={H} style={{ display: 'block' }}>
      <defs>
        <pattern id="tm-diag" x="0" y="0" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke="var(--amber)" strokeWidth="1" opacity=".18" />
        </pattern>
      </defs>
      {Object.entries(TM).map(([k, b]) => {
        const subs = SUB[k] || [];
        const sevColor =
          b.severity === 'amber' ? 'var(--amber)'
          : b.severity === 'indigo' ? 'var(--indigo)'
          : b.severity === 'mint' ? 'var(--mint)'
          : 'var(--ink-3)';
        const fillBg =
          b.severity === 'amber' ? 'var(--amber-soft)'
          : b.severity === 'indigo' ? 'var(--indigo-soft)'
          : b.severity === 'mint' ? 'var(--mint-soft)'
          : 'var(--bg-2)';
        return (
          <g key={k}>
            {/* sector background */}
            <rect x={b.x} y={b.y} width={b.w} height={b.h} fill={fillBg} stroke="var(--bg-0)" strokeWidth="2" />
            {/* sub cells */}
            {subs.reduce((acc, s, i) => {
              const yOff = subs.slice(0, i).reduce((sum, x) => sum + x.h, 0);
              acc.push(
                <g key={s.n}>
                  <rect
                    x={b.x + 1} y={b.y + yOff + 1}
                    width={b.w - 2} height={s.h - 2}
                    fill="transparent"
                    stroke={s.sel ? 'var(--mint)' : 'rgba(255,255,255,0.05)'}
                    strokeWidth={s.sel ? 2 : 1}
                  />
                  {s.h > 22 && b.w > 70 && (
                    <text x={b.x + 10} y={b.y + yOff + 16} fontFamily="var(--sans)" fontSize="11" fontWeight="500" fill="var(--ink)">{s.n}</text>
                  )}
                  {s.h > 38 && b.w > 70 && (
                    <text x={b.x + 10} y={b.y + yOff + 32} fontFamily="var(--mono)" fontSize="10" fill="var(--ink-3)">{s.p.toFixed(1)}%</text>
                  )}
                </g>
              );
              return acc;
            }, [])}
            {/* sector label */}
            {b.w > 80 && (
              <>
                <text x={b.x + b.w - 10} y={b.y + b.h - 14} textAnchor="end" fontFamily="var(--mono)" fontSize="9" letterSpacing="1" fill={sevColor} opacity=".95">{b.label.toUpperCase()}</text>
                <text x={b.x + b.w - 10} y={b.y + b.h - 4} textAnchor="end" fontFamily="var(--display)" fontSize="11" fill={sevColor}>{b.pct}%</text>
              </>
            )}
            {b.alarm && (
              <rect x={b.x} y={b.y} width={b.w} height={b.h} fill="url(#tm-diag)" pointerEvents="none" />
            )}
          </g>
        );
      })}
    </svg>
  );
}

function NVSidebar({ active = 'concentration' }) {
  const items = [
    ['Overview', 'overview', '◐'],
    ['Concentration', 'concentration', '▢'],
    ['Diversification', 'diversification', '◇'],
    ['Risk', 'risk', '△'],
    ['Performance', 'performance', '↗'],
    ['Goals', 'goals', '○'],
    ['Tax', 'tax', '₹'],
  ];
  return (
    <aside style={{ width: 224, borderRight: '1px solid var(--line)', padding: '20px 14px', background: 'var(--bg-0)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 8px 20px' }}>
        <span className="nv-mark">न</span>
        <span className="nv-serif" style={{ fontSize: 17 }}>Nivesh</span>
      </div>
      <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.18em', color: 'var(--ink-4)', padding: '4px 10px 6px', textTransform: 'uppercase' }}>Dashboards</div>
      {items.map(([t, k, i]) => {
        const on = k === active;
        return (
          <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', fontSize: 13, borderRadius: 8, color: on ? 'var(--ink)' : 'var(--ink-2)', background: on ? 'var(--bg-2)' : 'transparent', border: on ? '1px solid var(--line)' : '1px solid transparent', cursor: 'pointer' }}>
            <span style={{ color: on ? 'var(--mint)' : 'var(--ink-4)', width: 14, textAlign: 'center', fontFamily: 'var(--mono)', fontSize: 12 }}>{i}</span>
            <span>{t}</span>
            {on && <span style={{ marginLeft: 'auto', width: 4, height: 16, background: 'var(--mint)', borderRadius: 2 }} />}
          </div>
        );
      })}
      <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.18em', color: 'var(--ink-4)', padding: '20px 10px 6px', textTransform: 'uppercase' }}>Workspace</div>
      {['Plan board', 'Portfolio builder', 'Chat copilot'].map((t) => (
        <div key={t} style={{ padding: '8px 10px 8px 32px', fontSize: 13, color: 'var(--ink-2)', borderRadius: 8 }}>{t}</div>
      ))}
      <div style={{ marginTop: 'auto', padding: '12px 10px', borderTop: '1px solid var(--line)', display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ width: 28, height: 28, borderRadius: 8, background: 'var(--bg-3)', display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-2)' }}>AK</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 500 }}>Aarav Kumar</div>
          <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)' }}>₹ 24.8 L · NIDP ✓</div>
        </div>
      </div>
    </aside>
  );
}

function NVDashConcentrationDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVSidebar active="concentration" />

      <main style={{ flex: 1, padding: '24px 36px 32px', overflow: 'hidden' }}>
        {/* header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 18, marginBottom: 18 }}>
          <div>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Dashboard · concentration</div>
            <h1 className="nv-serif" style={{ fontSize: 38, letterSpacing: '-0.025em', margin: '4px 0 0', lineHeight: 1.05 }}>One in three rupees sits in financials.</h1>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
            <div className="nv-pill nv-pill-amber"><span className="nv-dot" style={{ background: 'var(--amber)' }} />ATTENTION</div>
            <button className="nv-btn" style={{ padding: '8px 13px', fontSize: 12 }}>↓ Export</button>
            <button className="nv-btn" style={{ padding: '8px 13px', fontSize: 12 }}>⟳ Resync</button>
            <button className="nv-btn nv-btn-primary" style={{ padding: '8px 13px', fontSize: 12 }}>Simulate trim →</button>
          </div>
        </div>

        {/* metrics strip */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 18 }}>
          {[
            { l: 'Top sector', v: '32%', s: 'Financials', sub: 'cap · 25%', c: 'amber' },
            { l: 'Top holding', v: '8.0%', s: 'HDFC Bank', sub: 'cap · 8%', c: 'amber' },
            { l: 'Sectors > 20%', v: '2', s: 'Fin · Tech', sub: 'target ≤ 1', c: 'amber' },
            { l: 'Herfindahl', v: '1,640', s: 'Moderate', sub: 'target ≤ 1,500', c: 'indigo' },
          ].map((m) => (
            <div key={m.l} className="nv-card" style={{ padding: '14px 16px' }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>{m.l}</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 6 }}>
                <span className="nv-serif nv-num" style={{ fontSize: 36, letterSpacing: '-0.03em', color: `var(--${m.c})` }}>{m.v}</span>
                <span style={{ fontSize: 13, color: 'var(--ink-2)' }}>{m.s}</span>
              </div>
              <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4, letterSpacing: '.04em' }}>{m.sub}</div>
            </div>
          ))}
        </div>

        {/* main grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18 }}>
          {/* treemap card */}
          <div className="nv-card" style={{ padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Allocation map · sector / holding</div>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                {['Sector', 'Stock', 'Market cap', 'Geo'].map((t, i) => (
                  <span key={t} style={{ fontSize: 11, padding: '4px 9px', borderRadius: 6, background: i === 0 ? 'var(--bg-2)' : 'transparent', border: i === 0 ? '1px solid var(--line-2)' : '1px solid transparent', color: i === 0 ? 'var(--ink)' : 'var(--ink-3)', cursor: 'pointer' }}>{t}</span>
                ))}
              </div>
            </div>
            <div style={{ width: '100%', overflow: 'hidden', borderRadius: 8 }}>
              <NVTreemap scale={1} />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--line)' }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Legend</div>
              {[['Over cap', 'amber'], ['Watch', 'indigo'], ['Healthy', 'mint'], ['Neutral', 'ink-3']].map(([t, c]) => (
                <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 10, height: 10, background: `var(--${c}${c==='ink-3'?'':'-soft'})`, border: `1px solid var(--${c}${c==='ink-3'?'':'-line'})`, borderRadius: 2 }} />
                  <span style={{ fontSize: 11.5, color: 'var(--ink-2)' }}>{t}</span>
                </div>
              ))}
              <span style={{ marginLeft: 'auto', fontSize: 11.5, color: 'var(--ink-3)' }}>Click any tile to drill down →</span>
            </div>
          </div>

          {/* drill-down panel */}
          <aside className="nv-card-2" style={{ padding: 18, display: 'flex', flexDirection: 'column' }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--mint)', textTransform: 'uppercase' }}>● Selected</div>
            <div className="nv-serif" style={{ fontSize: 26, letterSpacing: '-0.02em', marginTop: 6 }}>HDFC Bank</div>
            <div className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '.04em' }}>HDFCBANK · NSE · BANKNIFTY</div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginTop: 16 }}>
              <div style={{ padding: '10px 12px', background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
                <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.1em', textTransform: 'uppercase' }}>Current value</div>
                <div className="nv-serif nv-num" style={{ fontSize: 24, marginTop: 2, letterSpacing: '-0.02em' }}>₹1.98<span style={{ fontSize: 14, color: 'var(--ink-3)' }}>L</span></div>
              </div>
              <div style={{ padding: '10px 12px', background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
                <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.1em', textTransform: 'uppercase' }}>Unrealised P&L</div>
                <div className="nv-serif nv-num" style={{ fontSize: 24, marginTop: 2, color: 'var(--mint)', letterSpacing: '-0.02em' }}>+₹46.3<span style={{ fontSize: 14 }}>k</span></div>
              </div>
              <div style={{ padding: '10px 12px', background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
                <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.1em', textTransform: 'uppercase' }}>Of portfolio</div>
                <div className="nv-serif nv-num" style={{ fontSize: 24, marginTop: 2, color: 'var(--amber)', letterSpacing: '-0.02em' }}>8.0%</div>
              </div>
              <div style={{ padding: '10px 12px', background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
                <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.1em', textTransform: 'uppercase' }}>Of sector</div>
                <div className="nv-serif nv-num" style={{ fontSize: 24, marginTop: 2, letterSpacing: '-0.02em' }}>25%</div>
              </div>
            </div>

            {/* sparkline */}
            <div style={{ marginTop: 16, padding: '12px 12px 10px', background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
              <div style={{ display: 'flex', alignItems: 'flex-end', marginBottom: 6 }}>
                <span className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.1em', textTransform: 'uppercase' }}>1Y · vs Nifty Bank</span>
                <span className="nv-num" style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--mint)' }}>+23.4%</span>
              </div>
              <svg viewBox="0 0 320 64" style={{ width: '100%', height: 64 }}>
                <defs>
                  <linearGradient id="spark-g" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stopColor="var(--mint)" stopOpacity=".35" />
                    <stop offset="1" stopColor="var(--mint)" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <path d="M0,52 C30,48 50,42 80,40 C120,38 150,30 180,26 C210,22 240,18 270,12 L320,6 L320,64 L0,64 Z" fill="url(#spark-g)" />
                <path d="M0,52 C30,48 50,42 80,40 C120,38 150,30 180,26 C210,22 240,18 270,12 L320,6" fill="none" stroke="var(--mint)" strokeWidth="1.5" />
                <path d="M0,46 C40,44 80,46 120,40 C160,34 200,38 240,30 C260,26 290,24 320,20" fill="none" stroke="var(--ink-3)" strokeWidth="1" strokeDasharray="3 3" opacity=".7" />
              </svg>
            </div>

            {/* why concentrated */}
            <div className="nv-mono" style={{ fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginTop: 18 }}>Why this is flagged</div>
            <ul style={{ listStyle: 'none', padding: 0, margin: '8px 0 0' }}>
              {[
                'Single-stock cap exceeded · 8.0% vs 5% policy',
                'Sector cap exceeded · Financials 32% vs 25%',
                'Correlated with ICICI · 0.86 over 3Y',
              ].map((t) => (
                <li key={t} style={{ display: 'flex', gap: 9, padding: '6px 0', fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.5 }}>
                  <span style={{ color: 'var(--amber)', marginTop: 4, width: 4, height: 4, borderRadius: '50%', background: 'var(--amber)', flex: 'none' }} />
                  <span>{t}</span>
                </li>
              ))}
            </ul>

            <div style={{ display: 'flex', gap: 8, marginTop: 18 }}>
              <button className="nv-btn nv-btn-primary" style={{ flex: 1, justifyContent: 'center', padding: '11px', fontSize: 13 }}>Simulate trim</button>
              <button className="nv-btn" style={{ padding: '11px 14px', fontSize: 13 }}>↗ Chat</button>
            </div>
          </aside>
        </div>

        {/* bottom row — sector breakdown */}
        <div className="nv-card" style={{ padding: 18, marginTop: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Sector exposure · vs Nifty 500</div>
            <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--ink-3)' }}>policy max</span>
          </div>
          {[
            { s: 'Financials', y: 32, b: 28, cap: 25, c: 'amber' },
            { s: 'Technology', y: 22, b: 14, cap: 25, c: 'indigo' },
            { s: 'Energy',     y: 14, b: 11, cap: 25, c: 'ink-3' },
            { s: 'Consumer',   y: 11, b: 9,  cap: 25, c: 'ink-3' },
            { s: 'Pharma',     y: 9,  b: 6,  cap: 25, c: 'mint' },
            { s: 'Auto',       y: 7,  b: 6,  cap: 25, c: 'ink-3' },
            { s: 'Materials',  y: 3,  b: 4,  cap: 25, c: 'ink-3' },
            { s: 'Cash',       y: 2,  b: 1,  cap: 25, c: 'ink-3' },
          ].map((r) => (
            <div key={r.s} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 80px 60px', alignItems: 'center', gap: 14, padding: '8px 0', borderTop: '1px solid var(--line)' }}>
              <div style={{ fontSize: 13, fontWeight: 500 }}>{r.s}</div>
              <div style={{ position: 'relative', height: 12, background: 'var(--bg-2)', borderRadius: 3 }}>
                <div style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width: `${(r.b / 40) * 100}%`, background: 'var(--ink-4)', opacity: .55, borderRadius: 3 }} />
                <div style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width: `${(r.y / 40) * 100}%`, background: `var(--${r.c})`, borderRadius: 3, opacity: r.c === 'ink-3' ? 0.7 : 1 }} />
                <div style={{ position: 'absolute', top: -4, bottom: -4, left: `${(r.cap / 40) * 100}%`, width: 2, background: 'var(--ink)', opacity: .4 }} />
              </div>
              <div className="nv-mono nv-num" style={{ fontSize: 12, color: 'var(--ink)', textAlign: 'right' }}>{r.y}%</div>
              <div className="nv-mono nv-num" style={{ fontSize: 11, color: r.y > r.b ? 'var(--amber)' : 'var(--mint)', textAlign: 'right' }}>{r.y - r.b > 0 ? '+' : ''}{r.y - r.b}pt</div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function NVDashConcentrationMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '6px 18px 12px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ color: 'var(--ink-2)', fontSize: 18 }}>‹</span>
        <div>
          <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Dashboard</div>
          <div className="nv-serif" style={{ fontSize: 18, marginTop: 1 }}>Concentration</div>
        </div>
        <span className="nv-pill nv-pill-amber" style={{ marginLeft: 'auto', fontSize: 9 }}>ATTENTION</span>
      </div>

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        {/* lead callout */}
        <div className="nv-card" style={{ padding: 14, marginBottom: 12 }}>
          <div className="nv-serif" style={{ fontSize: 22, lineHeight: 1.15, letterSpacing: '-0.02em' }}>
            1 in 3 rupees sits in <span style={{ color: 'var(--amber)' }}>financials</span>.
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <div style={{ flex: 1 }}>
              <div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Top sector</div>
              <div className="nv-serif nv-num" style={{ fontSize: 22, color: 'var(--amber)', letterSpacing: '-0.02em' }}>32%</div>
            </div>
            <div style={{ flex: 1 }}>
              <div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Top stock</div>
              <div className="nv-serif nv-num" style={{ fontSize: 22, letterSpacing: '-0.02em' }}>8.0%</div>
            </div>
            <div style={{ flex: 1 }}>
              <div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>HHI</div>
              <div className="nv-serif nv-num" style={{ fontSize: 22, color: 'var(--indigo)', letterSpacing: '-0.02em' }}>1640</div>
            </div>
          </div>
        </div>

        {/* treemap card */}
        <div className="nv-card" style={{ padding: 10, marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', padding: '0 4px 8px' }}>
            <span className="nv-mono" style={{ fontSize: 9, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Allocation map</span>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
              {['Sector', 'Stock'].map((t, i) => (
                <span key={t} style={{ fontSize: 10, padding: '3px 7px', borderRadius: 5, background: i === 0 ? 'var(--bg-2)' : 'transparent', color: i === 0 ? 'var(--ink)' : 'var(--ink-3)' }}>{t}</span>
              ))}
            </div>
          </div>
          <div style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
            <NVTreemap scale={0.535} />
          </div>
        </div>

        {/* drill-down — collapsed card */}
        <div className="nv-card-2" style={{ padding: 12 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--mint)', textTransform: 'uppercase' }}>● Selected</div>
          <div style={{ display: 'flex', alignItems: 'baseline', marginTop: 2 }}>
            <span className="nv-serif" style={{ fontSize: 19, letterSpacing: '-0.02em' }}>HDFC Bank</span>
            <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--amber)' }}>8.0% of book</span>
          </div>
          <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.04em' }}>HDFCBANK · ₹1.98L · +₹46.3k</div>
          <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
            <button className="nv-btn nv-btn-primary" style={{ flex: 1, justifyContent: 'center', padding: '9px', fontSize: 12 }}>Simulate trim</button>
            <button className="nv-btn" style={{ padding: '9px 11px', fontSize: 12 }}>↗</button>
          </div>
        </div>
      </div>

      {/* bottom tabs */}
      <div style={{ display: 'flex', justifyContent: 'space-around', padding: '10px 18px 22px', borderTop: '1px solid var(--line)', background: 'var(--bg-0)' }}>
        {[['◐', 'Health'], ['▢', 'Holdings', true], ['＋', 'Plan'], ['◔', 'Chat'], ['⚙', 'You']].map(([i, l, on]) => (
          <div key={l} style={{ textAlign: 'center', color: on ? 'var(--mint)' : 'var(--ink-3)' }}>
            <div style={{ fontSize: 16 }}>{i}</div>
            <div className="nv-mono" style={{ fontSize: 8.5, letterSpacing: '.1em', marginTop: 2 }}>{l}</div>
          </div>
        ))}
      </div>
      <div className="nv-homebar"></div>
    </div>
  );
}

Object.assign(window, { NVDashConcentrationDesktop, NVDashConcentrationMobile });
