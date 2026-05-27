// ─── Nivesh · Advisor book + SIP board ───

// ═══════════════════════════════════════════════════════════
// ADVISOR BOOK — client cohort scatter + cohort table
// ═══════════════════════════════════════════════════════════
function NVCohortScatter() {
  // bubbles: (aum_lakhs, xirr%) — size = health score
  const clients = [
    { x: 240, y: 14.2, h: 82, n: 'A. Mehta', c: 'mint' },
    { x: 86,  y: 12.4, h: 88, n: 'R. Iyer', c: 'mint' },
    { x: 110, y: 11.1, h: 92, n: 'Sharma F.', c: 'mint' },
    { x: 42,  y: 9.4,  h: 74, n: 'P. Khanna', c: 'amber' },
    { x: 178, y: 16.8, h: 86, n: 'V. Joshi', c: 'mint' },
    { x: 62,  y: 7.2,  h: 58, n: 'D. Rao', c: 'danger' },
    { x: 18,  y: 11.6, h: 90, n: 'M. Banerjee', c: 'mint' },
    { x: 156, y: 13.9, h: 81, n: 'N. Pillai', c: 'mint' },
    { x: 320, y: 11.8, h: 76, n: 'Trust BL', c: 'amber' },
    { x: 96,  y: 8.4,  h: 62, n: 'K. Verma', c: 'danger' },
    { x: 24,  y: 10.1, h: 79, n: 'S. Iyengar', c: 'amber' },
    { x: 144, y: 15.6, h: 90, n: 'Capital P', c: 'mint' },
    { x: 72,  y: 13.2, h: 84, n: 'L. Shah', c: 'mint' },
    { x: 200, y: 17.4, h: 88, n: 'R. Kapoor', c: 'mint' },
    { x: 36,  y: 6.2,  h: 54, n: 'B. Sen', c: 'danger' },
    { x: 128, y: 14.8, h: 86, n: 'M. Reddy', c: 'mint' },
  ];

  const W = 720, H = 360, padL = 50, padR = 20, padT = 20, padB = 32;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const maxX = 360, maxY = 22;
  const xScale = (v) => padL + (v / maxX) * plotW;
  const yScale = (v) => H - padB - (v / maxY) * plotH;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: H }}>
      {/* y grid */}
      {[0, 5, 10, 15, 20].map((v) => (
        <g key={v}>
          <line x1={padL} y1={yScale(v)} x2={W - padR} y2={yScale(v)} stroke="var(--line)" strokeDasharray="2 4" />
          <text x={padL - 8} y={yScale(v) + 4} textAnchor="end" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">{v}%</text>
        </g>
      ))}
      {/* x ticks */}
      {[0, 50, 100, 200, 300].map((v) => (
        <g key={v}>
          <line x1={xScale(v)} y1={padT} x2={xScale(v)} y2={H - padB} stroke="var(--line)" strokeDasharray="2 4" opacity={v === 0 ? 0 : 1} />
          <text x={xScale(v)} y={H - padB + 16} textAnchor="middle" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">{v === 0 ? '0' : '₹' + v + 'L'}</text>
        </g>
      ))}
      {/* benchmark hline */}
      <line x1={padL} y1={yScale(13.5)} x2={W - padR} y2={yScale(13.5)} stroke="var(--ink-3)" strokeDasharray="3 3" />
      <text x={W - padR - 6} y={yScale(13.5) - 6} textAnchor="end" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">BOOK AVG 13.5%</text>

      {/* quadrant subtle labels */}
      <text x={W - padR - 8} y={padT + 14} textAnchor="end" fontFamily="var(--mono)" fontSize="9" fill="var(--mint)" opacity=".7">STAR · GROW</text>
      <text x={padL + 8} y={H - padB - 8} textAnchor="start" fontFamily="var(--mono)" fontSize="9" fill="var(--danger)" opacity=".7">UNDERPERFORM</text>

      {/* bubbles */}
      {clients.map((c, i) => {
        const r = 4 + (c.h - 50) / 7;
        return (
          <g key={c.n}>
            <circle cx={xScale(c.x)} cy={yScale(c.y)} r={r} fill={`var(--${c.c})`} fillOpacity=".3" stroke={`var(--${c.c})`} strokeWidth="1.5" />
            {(i === 0 || c.c === 'danger' || c.n === 'Trust BL') && (
              <text x={xScale(c.x) + r + 4} y={yScale(c.y) + 3} fontFamily="var(--sans)" fontSize="10" fill="var(--ink-2)">{c.n}</text>
            )}
          </g>
        );
      })}
      <text x={W / 2} y={H - 2} textAnchor="middle" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-4)" letterSpacing="2">AUM (₹L)</text>
      <text x="14" y={H / 2} textAnchor="middle" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-4)" letterSpacing="2" transform={`rotate(-90 14 ${H / 2})`}>XIRR (%)</text>
    </svg>
  );
}

function NVAdvisorBookDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVAdvSidebar active="book" />
      <main style={{ flex: 1, padding: '22px 32px 28px', overflow: 'hidden' }}>
        {/* header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 18 }}>
          <div>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Advisor · book</div>
            <h1 className="nv-serif" style={{ fontSize: 36, letterSpacing: '-0.025em', margin: '4px 0 0', lineHeight: 1.05 }}>87 clients · ₹64.2 Cr under advice.</h1>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button className="nv-btn" style={{ padding: '8px 12px', fontSize: 12 }}>Segment · HNI ▾</button>
            <button className="nv-btn" style={{ padding: '8px 12px', fontSize: 12 }}>Period · 1Y ▾</button>
            <button className="nv-btn" style={{ padding: '8px 12px', fontSize: 12 }}>↓ Export</button>
            <button className="nv-btn nv-btn-primary" style={{ padding: '8px 12px', fontSize: 12 }}>＋ Onboard client</button>
          </div>
        </div>

        {/* KPI strip */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 18 }}>
          {[
            { l: 'AUM', v: '₹64.2', s: 'Cr', sub: '+18.4% YTD', c: 'mint' },
            { l: 'Clients', v: '87', s: '', sub: '+6 this mo', c: 'mint' },
            { l: 'Avg XIRR', v: '13.5%', s: '', sub: 'vs NIFTY +1.4', c: 'mint' },
            { l: 'Avg health', v: '79', s: '/100', sub: '4 below 70', c: 'amber' },
            { l: 'At-risk', v: '4', s: 'clients', sub: 'attention', c: 'danger' },
          ].map((m) => (
            <div key={m.l} className="nv-card" style={{ padding: '14px 16px' }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>{m.l}</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 6 }}>
                <span className="nv-serif nv-num" style={{ fontSize: 30, letterSpacing: '-0.03em', color: m.c === 'danger' ? 'var(--danger)' : m.c === 'amber' ? 'var(--amber)' : 'var(--ink)' }}>{m.v}</span>
                <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>{m.s}</span>
              </div>
              <div className="nv-mono" style={{ fontSize: 10, color: `var(--${m.c})`, marginTop: 4, letterSpacing: '.04em' }}>{m.sub}</div>
            </div>
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18 }}>
          <div className="nv-card" style={{ padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Book scatter · AUM × XIRR · bubble = health</div>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 14, fontSize: 11 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--mint)', opacity: .5 }} />on track</span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--amber)', opacity: .5 }} />attention</span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--danger)', opacity: .5 }} />at-risk</span>
              </span>
            </div>
            <NVCohortScatter />
          </div>

          <aside className="nv-card-2" style={{ padding: 18 }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--danger)', textTransform: 'uppercase' }}>● At-risk · 4 clients</div>
            <div className="nv-serif" style={{ fontSize: 20, letterSpacing: '-0.02em', marginTop: 6 }}>Below cohort floor</div>

            <div style={{ marginTop: 14 }}>
              {[
                { n: 'D. Rao', a: '₹62 L', x: '+7.2%', h: 58, w: 'Allocation drift · 11pt' },
                { n: 'K. Verma', a: '₹96 L', x: '+8.4%', h: 62, w: 'Stale SIP · 4 missed' },
                { n: 'B. Sen', a: '₹36 L', x: '+6.2%', h: 54, w: 'KYC expiring' },
                { n: 'M. Tandon', a: '₹54 L', x: '+9.1%', h: 64, w: 'Concentration · 41%' },
              ].map((r) => (
                <div key={r.n} style={{ padding: '10px 0', borderTop: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{ width: 26, height: 26, borderRadius: 7, background: 'var(--bg-3)', fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-2)', display: 'grid', placeItems: 'center' }}>{r.n[0]}{r.n[r.n.length - 1]}</div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{r.n}</div>
                      <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.04em' }}>{r.a} · {r.x} · h {r.h}</div>
                    </div>
                    <span style={{ color: 'var(--ink-3)' }}>›</span>
                  </div>
                  <div className="nv-mono" style={{ fontSize: 10, color: 'var(--danger)', marginTop: 6, marginLeft: 36, letterSpacing: '.04em' }}>● {r.w}</div>
                </div>
              ))}
            </div>

            <button className="nv-btn nv-btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '10px', marginTop: 16, fontSize: 12 }}>Open review queue · 4 →</button>
          </aside>
        </div>

        {/* book table */}
        <div className="nv-card" style={{ padding: 18, marginTop: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Top 8 by AUM</div>
            <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--ink-3)' }}>Sorted · AUM ↓</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '36px 1.4fr 100px 80px 80px 100px 1fr 50px', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
            {['', 'Client', 'AUM', 'XIRR', 'Health', 'Last touch', 'Open · alerts', ''].map((h) => (
              <span key={h} className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>{h}</span>
            ))}
          </div>
          {[
            { n: 'Trust BL', a: '₹3.20 Cr', x: '11.8%', h: 76, t: '4d', al: 'KYC due', alC: 'amber', c: 'amber' },
            { n: 'A. Mehta', a: '₹2.41 Cr', x: '14.2%', h: 82, t: '2d', al: 'Drift +1.4σ', alC: 'amber', c: 'mint' },
            { n: 'R. Kapoor', a: '₹2.00 Cr', x: '17.4%', h: 88, t: '7d', al: '—', alC: 'mint', c: 'mint' },
            { n: 'V. Joshi', a: '₹1.78 Cr', x: '16.8%', h: 86, t: '1d', al: 'Q3 review', alC: 'indigo', c: 'mint' },
            { n: 'N. Pillai', a: '₹1.56 Cr', x: '13.9%', h: 81, t: '11d', al: '—', alC: 'mint', c: 'mint' },
            { n: 'Capital P', a: '₹1.44 Cr', x: '15.6%', h: 90, t: '3d', al: '—', alC: 'mint', c: 'mint' },
            { n: 'M. Reddy', a: '₹1.28 Cr', x: '14.8%', h: 86, t: '6d', al: '—', alC: 'mint', c: 'mint' },
            { n: 'Sharma F.', a: '₹1.10 Cr', x: '11.1%', h: 92, t: '9d', al: '—', alC: 'mint', c: 'mint' },
          ].map((r) => (
            <div key={r.n} style={{ display: 'grid', gridTemplateColumns: '36px 1.4fr 100px 80px 80px 100px 1fr 50px', alignItems: 'center', gap: 12, padding: '10px 0', borderTop: '1px solid var(--line)' }}>
              <div style={{ width: 28, height: 28, borderRadius: 7, background: 'var(--bg-3)', fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-2)', display: 'grid', placeItems: 'center' }}>{r.n[0]}{r.n[r.n.length - 1]}</div>
              <div style={{ fontSize: 13, fontWeight: 500 }}>{r.n}</div>
              <div className="nv-mono nv-num" style={{ fontSize: 12 }}>{r.a}</div>
              <div className="nv-mono nv-num" style={{ fontSize: 12, color: 'var(--mint)' }}>{r.x}</div>
              <div className="nv-mono nv-num" style={{ fontSize: 12, color: `var(--${r.c})` }}>{r.h}</div>
              <div className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{r.t}</div>
              <div>{r.al === '—' ? <span className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>—</span> : <span className={`nv-pill nv-pill-${r.alC}`} style={{ fontSize: 9 }}>{r.al}</span>}</div>
              <span style={{ color: 'var(--ink-3)', textAlign: 'right' }}>›</span>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function NVAdvisorBookMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '6px 18px 10px', display: 'flex', alignItems: 'center' }}>
        <div>
          <div className="nv-mono" style={{ fontSize: 9, color: 'var(--indigo)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Advisor</div>
          <div className="nv-serif" style={{ fontSize: 18 }}>Book</div>
        </div>
        <span className="nv-pill nv-pill-danger" style={{ marginLeft: 'auto', fontSize: 9 }}>4 AT-RISK</span>
      </div>

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        <div className="nv-card" style={{ padding: 14, marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'baseline' }}>
            <div>
              <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>AUM under advice</div>
              <div className="nv-serif nv-num" style={{ fontSize: 32, letterSpacing: '-0.035em', lineHeight: 1 }}>₹64.2<span style={{ fontSize: 14, color: 'var(--ink-3)' }}>Cr</span></div>
              <div className="nv-mono" style={{ fontSize: 10, color: 'var(--mint)', marginTop: 2 }}>+18.4% YTD · 87 clients</div>
            </div>
            <svg viewBox="0 0 100 50" style={{ width: 100, height: 50, marginLeft: 'auto' }}>
              <path d="M0,42 C20,38 40,30 60,22 C80,14 95,8 100,4" fill="none" stroke="var(--mint)" strokeWidth="1.8" />
              <circle cx="100" cy="4" r="3" fill="var(--mint)" />
            </svg>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--line)' }}>
            <div><div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>XIRR</div><div className="nv-serif nv-num" style={{ fontSize: 18, color: 'var(--mint)' }}>13.5%</div></div>
            <div><div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>Health</div><div className="nv-serif nv-num" style={{ fontSize: 18, color: 'var(--amber)' }}>79</div></div>
            <div><div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>Alerts</div><div className="nv-serif nv-num" style={{ fontSize: 18, color: 'var(--danger)' }}>12</div></div>
          </div>
        </div>

        {/* compact scatter */}
        <div className="nv-card" style={{ padding: 10, marginBottom: 12 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase', paddingLeft: 4, marginBottom: 4 }}>Book scatter</div>
          <div style={{ display: 'flex', justifyContent: 'center' }}>
            <NVCohortScatter />
          </div>
        </div>

        <div className="nv-card-2" style={{ padding: 13 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--danger)', textTransform: 'uppercase', marginBottom: 4 }}>● 4 at-risk</div>
          {[
            { n: 'D. Rao', w: 'Allocation drift', a: '₹62L' },
            { n: 'K. Verma', w: 'Stale SIP', a: '₹96L' },
            { n: 'B. Sen', w: 'KYC expiring', a: '₹36L' },
          ].map((r) => (
            <div key={r.n} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderTop: '1px solid var(--line)' }}>
              <div style={{ width: 24, height: 24, borderRadius: 7, background: 'var(--bg-3)', fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-2)', display: 'grid', placeItems: 'center' }}>{r.n[0]}{r.n[r.n.length - 1]}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 500 }}>{r.n}</div>
                <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--danger)' }}>{r.w}</div>
              </div>
              <span className="nv-mono nv-num" style={{ fontSize: 11, color: 'var(--ink-2)' }}>{r.a}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-around', padding: '10px 18px 22px', borderTop: '1px solid var(--line)', background: 'var(--bg-0)' }}>
        {[['▦', 'Book', true], ['●', 'Clients'], ['◫', 'SIP'], ['✓', 'Tasks'], ['⛨', 'Comply']].map(([i, l, on]) => (
          <div key={l} style={{ textAlign: 'center', color: on ? 'var(--indigo)' : 'var(--ink-3)' }}>
            <div style={{ fontSize: 16 }}>{i}</div>
            <div className="nv-mono" style={{ fontSize: 8.5, letterSpacing: '.1em', marginTop: 2 }}>{l}</div>
          </div>
        ))}
      </div>
      <div className="nv-homebar"></div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// SIP BOARD — calendar heatmap + funnel
// ═══════════════════════════════════════════════════════════
function NVSipCalendar({ scale = 1 }) {
  // 35-day grid (Nov 2026), each cell shows SIP runs / failures
  const cells = [];
  const seed = [
    { d: 0, dy: '', }, { d: 0, dy: '' },
    // start Nov 1
    ...Array(30).fill(0).map((_, i) => {
      const day = i + 1;
      const sip = [3, 4, 5, 7, 10, 15, 22].includes(day) ? 8 + (i % 4)
        : [11, 19, 27].includes(day) ? 14 + (i % 3)
        : [1, 6, 12, 18, 25, 28].includes(day) ? 2 + (i % 2)
        : 0;
      const failed = day === 5 ? 2 : day === 19 ? 1 : day === 27 ? 1 : 0;
      const isToday = day === 26;
      return { d: day, sip, failed, isToday };
    }),
  ];
  const cellSize = 70 * scale;
  const W = cellSize * 7 + 40, H = 36 + cellSize * 5;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W }}>
      {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d, i) => (
        <text key={d} x={20 + i * cellSize + 8} y="22" fontFamily="var(--mono)" fontSize={10 * scale} fill="var(--ink-3)" letterSpacing="1">{d.toUpperCase()}</text>
      ))}
      {seed.map((c, i) => {
        const col = i % 7, row = Math.floor(i / 7);
        const x = 20 + col * cellSize, y = 36 + row * cellSize;
        const intensity = c.sip ? Math.min(1, c.sip / 22) : 0;
        const fill = c.sip ? `rgba(106, 240, 168, ${0.06 + intensity * 0.32})` : 'var(--bg-2)';
        return (
          <g key={i}>
            <rect x={x} y={y} width={cellSize - 6} height={cellSize - 6} fill={fill} stroke={c.isToday ? 'var(--mint)' : 'var(--line)'} strokeWidth={c.isToday ? 2 : 1} rx="4" />
            {c.d > 0 && (
              <>
                <text x={x + 8} y={y + 16} fontFamily="var(--mono)" fontSize={10 * scale} fill={c.isToday ? 'var(--mint)' : 'var(--ink-3)'}>{c.d}</text>
                {c.sip > 0 && (
                  <text x={x + 8} y={y + cellSize - 14} fontFamily="var(--display)" fontSize={20 * scale} fill="var(--ink)" letterSpacing="-0.02em">{c.sip}</text>
                )}
                {c.failed > 0 && (
                  <g>
                    <circle cx={x + cellSize - 14} cy={y + 14} r={6} fill="var(--danger)" />
                    <text x={x + cellSize - 14} y={y + 17} textAnchor="middle" fontFamily="var(--mono)" fontSize={8 * scale} fill="var(--bg-0)" fontWeight="600">{c.failed}</text>
                  </g>
                )}
              </>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function NVSipBoardDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVAdvSidebar active="sip" />
      <main style={{ flex: 1, padding: '22px 32px 28px', overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 18 }}>
          <div>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Advisor · SIP board · November 2026</div>
            <h1 className="nv-serif" style={{ fontSize: 36, letterSpacing: '-0.025em', margin: '4px 0 0', lineHeight: 1.05 }}>148 SIPs · ₹14.2 L flowing this month.</h1>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button className="nv-btn" style={{ padding: '8px 12px', fontSize: 12 }}>‹ Oct</button>
            <button className="nv-btn" style={{ padding: '8px 12px', fontSize: 12 }}>Nov 26 ▾</button>
            <button className="nv-btn" style={{ padding: '8px 12px', fontSize: 12 }}>Dec ›</button>
            <button className="nv-btn nv-btn-primary" style={{ padding: '8px 12px', fontSize: 12 }}>Re-run failed · 4</button>
          </div>
        </div>

        {/* KPI strip */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 18 }}>
          {[
            { l: 'Active SIPs', v: '148', s: '/ 152', sub: '4 paused', c: 'mint' },
            { l: 'Volume', v: '₹14.2', s: 'L', sub: '+8% MoM', c: 'mint' },
            { l: 'Failed', v: '4', s: 'this month', sub: '2 mandate', c: 'danger' },
            { l: 'Top-ups', v: '11', s: 'pending', sub: 'avg ₹3,500', c: 'indigo' },
            { l: 'Renewals', v: '8', s: 'due Dec', sub: '₹2.4 L', c: 'amber' },
          ].map((m) => (
            <div key={m.l} className="nv-card" style={{ padding: '14px 16px' }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>{m.l}</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 6 }}>
                <span className="nv-serif nv-num" style={{ fontSize: 30, letterSpacing: '-0.03em', color: m.c === 'danger' ? 'var(--danger)' : m.c === 'amber' ? 'var(--amber)' : 'var(--ink)' }}>{m.v}</span>
                <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>{m.s}</span>
              </div>
              <div className="nv-mono" style={{ fontSize: 10, color: `var(--${m.c})`, marginTop: 4, letterSpacing: '.04em' }}>{m.sub}</div>
            </div>
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 18 }}>
          {/* calendar heatmap */}
          <div className="nv-card" style={{ padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>SIP runs · per day · count + failures</div>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 14, fontSize: 11, alignItems: 'center' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ width: 10, height: 10, background: 'rgba(106, 240, 168, .1)', border: '1px solid var(--line)' }} />
                  <span style={{ width: 10, height: 10, background: 'rgba(106, 240, 168, .25)', border: '1px solid var(--line)' }} />
                  <span style={{ width: 10, height: 10, background: 'rgba(106, 240, 168, .45)', border: '1px solid var(--line)' }} />
                  <span style={{ marginLeft: 4, color: 'var(--ink-3)' }}>activity</span>
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--danger)' }} />failed</span>
              </span>
            </div>
            <NVSipCalendar scale={0.78} />
          </div>

          <aside className="nv-card-2" style={{ padding: 18 }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--danger)', textTransform: 'uppercase' }}>● Failed runs · 4</div>
            <div className="nv-serif" style={{ fontSize: 22, letterSpacing: '-0.02em', marginTop: 6 }}>₹1.34 L stuck</div>

            <div style={{ marginTop: 14 }}>
              {[
                { c: 'D. Rao', f: 'Axis Bluechip', a: '₹15k', d: 'Nov 5', r: 'NACH bounce', sev: 'danger' },
                { c: 'K. Verma', f: 'PPFAS Flexi', a: '₹25k', d: 'Nov 5', r: 'Mandate expired', sev: 'amber' },
                { c: 'B. Sen', f: 'Mirae Tax', a: '₹10k', d: 'Nov 19', r: 'Insufficient', sev: 'amber' },
                { c: 'P. Khanna', f: 'Quant Small', a: '₹84k', d: 'Nov 27', r: 'Top-up failed', sev: 'danger' },
              ].map((r, i) => (
                <div key={i} style={{ padding: '10px 0', borderTop: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', alignItems: 'baseline' }}>
                    <span style={{ fontSize: 12.5, fontWeight: 500 }}>{r.c}</span>
                    <span className="nv-mono" style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>{r.d}</span>
                  </div>
                  <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 2 }}>{r.f} · <span className="nv-num">{r.a}</span></div>
                  <div className="nv-mono" style={{ fontSize: 10, color: `var(--${r.sev})`, marginTop: 4, letterSpacing: '.04em' }}>● {r.r}</div>
                </div>
              ))}
            </div>

            <button className="nv-btn nv-btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '10px', marginTop: 16, fontSize: 12 }}>Auto-retry all →</button>
          </aside>
        </div>

        {/* upcoming SIPs queue */}
        <div className="nv-card" style={{ padding: 18, marginTop: 16 }}>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 12 }}>Tomorrow · 22 SIPs · ₹2.1 L scheduled</div>
          <div style={{ display: 'grid', gridTemplateColumns: '36px 1.2fr 1.4fr 100px 100px 80px 50px', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
            {['', 'Client', 'Fund', 'Amount', 'Schedule', 'Status', ''].map((h) => (
              <span key={h} className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>{h}</span>
            ))}
          </div>
          {[
            { c: 'A. Mehta', f: 'PPFAS Flexi Cap Direct', a: '₹18,500', sc: 'Monthly · 27', st: 'Mandate ✓', sv: 'mint' },
            { c: 'R. Iyer', f: 'Axis Small Cap Direct', a: '₹10,000', sc: 'Monthly · 27', st: 'Mandate ✓', sv: 'mint' },
            { c: 'V. Joshi', f: 'Mirae Asset Large Direct', a: '₹25,000', sc: 'Weekly · Mon', st: 'Top-up due', sv: 'indigo' },
            { c: 'Sharma F.', f: 'Quant Active Direct', a: '₹50,000', sc: 'Monthly · 27', st: 'Mandate ✓', sv: 'mint' },
            { c: 'N. Pillai', f: 'Parag Parikh Flexi', a: '₹12,500', sc: 'Monthly · 27', st: 'Mandate ✓', sv: 'mint' },
          ].map((r, i) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '36px 1.2fr 1.4fr 100px 100px 80px 50px', alignItems: 'center', gap: 12, padding: '10px 0', borderTop: '1px solid var(--line)' }}>
              <div style={{ width: 28, height: 28, borderRadius: 7, background: 'var(--bg-3)', fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-2)', display: 'grid', placeItems: 'center' }}>{r.c[0]}{r.c[r.c.length - 1]}</div>
              <div style={{ fontSize: 13, fontWeight: 500 }}>{r.c}</div>
              <div style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>{r.f}</div>
              <div className="nv-mono nv-num" style={{ fontSize: 12.5, color: 'var(--mint)' }}>{r.a}</div>
              <div className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{r.sc}</div>
              <span className={`nv-pill nv-pill-${r.sv}`} style={{ fontSize: 9 }}>{r.st}</span>
              <span style={{ color: 'var(--ink-3)', textAlign: 'right' }}>›</span>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function NVSipBoardMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>
      <div style={{ padding: '6px 18px 10px', display: 'flex', alignItems: 'center' }}>
        <div>
          <div className="nv-mono" style={{ fontSize: 9, color: 'var(--indigo)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Advisor</div>
          <div className="nv-serif" style={{ fontSize: 18 }}>SIP board · Nov</div>
        </div>
        <span className="nv-pill nv-pill-danger" style={{ marginLeft: 'auto', fontSize: 9 }}>4 FAILED</span>
      </div>

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        <div className="nv-card" style={{ padding: 14, marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'baseline' }}>
            <div>
              <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Volume this month</div>
              <div className="nv-serif nv-num" style={{ fontSize: 32, letterSpacing: '-0.035em', lineHeight: 1 }}>₹14.2<span style={{ fontSize: 14, color: 'var(--ink-3)' }}>L</span></div>
            </div>
            <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
              <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>Tomorrow</div>
              <div className="nv-serif" style={{ fontSize: 20 }}>22 SIPs</div>
              <div className="nv-mono nv-num" style={{ fontSize: 10, color: 'var(--mint)' }}>₹2.1L</div>
            </div>
          </div>
        </div>

        <div className="nv-card" style={{ padding: 10, marginBottom: 12 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase', paddingLeft: 4, marginBottom: 4 }}>Calendar</div>
          <div style={{ overflow: 'hidden', display: 'flex', justifyContent: 'center' }}>
            <NVSipCalendar scale={0.4} />
          </div>
        </div>

        <div className="nv-card-2" style={{ padding: 13 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--danger)', textTransform: 'uppercase' }}>● 4 failed · ₹1.34 L stuck</div>
          {[
            { c: 'D. Rao', f: 'Axis Bluechip', a: '₹15k', r: 'NACH bounce' },
            { c: 'K. Verma', f: 'PPFAS Flexi', a: '₹25k', r: 'Mandate' },
            { c: 'P. Khanna', f: 'Quant Small', a: '₹84k', r: 'Top-up fail' },
          ].map((r, i) => (
            <div key={i} style={{ padding: '8px 0', borderTop: '1px solid var(--line)' }}>
              <div style={{ display: 'flex' }}>
                <span style={{ fontSize: 12.5, fontWeight: 500 }}>{r.c}</span>
                <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 11.5, color: 'var(--danger)' }}>{r.a}</span>
              </div>
              <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', marginTop: 2 }}>{r.f} · <span style={{ color: 'var(--danger)' }}>{r.r}</span></div>
            </div>
          ))}
          <button className="nv-btn nv-btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '10px', marginTop: 10, fontSize: 12 }}>Auto-retry all →</button>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-around', padding: '10px 18px 22px', borderTop: '1px solid var(--line)', background: 'var(--bg-0)' }}>
        {[['▦', 'Book'], ['●', 'Clients'], ['◫', 'SIP', true], ['✓', 'Tasks'], ['⛨', 'Comply']].map(([i, l, on]) => (
          <div key={l} style={{ textAlign: 'center', color: on ? 'var(--indigo)' : 'var(--ink-3)' }}>
            <div style={{ fontSize: 16 }}>{i}</div>
            <div className="nv-mono" style={{ fontSize: 8.5, letterSpacing: '.1em', marginTop: 2 }}>{l}</div>
          </div>
        ))}
      </div>
      <div className="nv-homebar"></div>
    </div>
  );
}

Object.assign(window, {
  NVAdvisorBookDesktop, NVAdvisorBookMobile,
  NVSipBoardDesktop, NVSipBoardMobile,
});
