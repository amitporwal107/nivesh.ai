// ─── Nivesh · Advisor Client 360 — desktop + mobile ───
// Advisor's single-client surface · institutional density

function NVAdvSidebar({ active = 'clients' }) {
  const items = [
    ['Book', 'book', '▦'],
    ['Clients', 'clients', '●', true],
    ['SIP board', 'sip', '◫'],
    ['Tasks', 'tasks', '✓'],
    ['Compliance', 'comp', '⛨'],
  ];
  return (
    <aside style={{ width: 224, borderRight: '1px solid var(--line)', padding: '20px 14px', background: 'var(--bg-0)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 8px 16px' }}>
        <span className="nv-mark">न</span>
        <div>
          <div className="nv-serif" style={{ fontSize: 16 }}>Nivesh</div>
          <div className="nv-mono" style={{ fontSize: 8.5, letterSpacing: '.14em', color: 'var(--indigo)', textTransform: 'uppercase' }}>ADVISOR</div>
        </div>
      </div>
      <div style={{ position: 'relative', marginBottom: 14 }}>
        <input style={{ width: '100%', background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 8, padding: '7px 11px 7px 28px', fontSize: 12, color: 'var(--ink-2)', fontFamily: 'var(--sans)' }} placeholder="Search clients · ⌘K" readOnly />
        <span style={{ position: 'absolute', top: 7, left: 9, color: 'var(--ink-4)', fontSize: 12 }}>⌕</span>
      </div>
      {items.map(([t, k, i, isActive]) => {
        const on = isActive;
        return (
          <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', fontSize: 13, borderRadius: 8, color: on ? 'var(--ink)' : 'var(--ink-2)', background: on ? 'var(--bg-2)' : 'transparent', border: on ? '1px solid var(--line)' : '1px solid transparent', cursor: 'pointer' }}>
            <span style={{ color: on ? 'var(--indigo)' : 'var(--ink-4)', width: 14, textAlign: 'center', fontFamily: 'var(--mono)', fontSize: 12 }}>{i}</span>
            <span>{t}</span>
            {on && <span style={{ marginLeft: 'auto', width: 4, height: 16, background: 'var(--indigo)', borderRadius: 2 }} />}
          </div>
        );
      })}
      <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.18em', color: 'var(--ink-4)', padding: '18px 10px 6px', textTransform: 'uppercase' }}>Pinned</div>
      {[
        ['A. Mehta', '₹2.4 Cr', true],
        ['R. Iyer', '₹86 L'],
        ['Sharma F.', '₹1.1 Cr'],
        ['P. Khanna', '₹42 L'],
      ].map(([n, v, on]) => (
        <div key={n} style={{ display: 'flex', alignItems: 'center', padding: '6px 10px', borderRadius: 7, background: on ? 'var(--bg-2)' : 'transparent', border: on ? '1px solid var(--line)' : '1px solid transparent' }}>
          <div style={{ width: 22, height: 22, borderRadius: 7, background: 'var(--bg-3)', fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-2)', display: 'grid', placeItems: 'center', flex: 'none' }}>{n[0]}{n[n.length - 1]}</div>
          <div style={{ marginLeft: 8, fontSize: 12, color: on ? 'var(--ink)' : 'var(--ink-2)' }}>{n}</div>
          <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>{v}</span>
        </div>
      ))}
      <div style={{ marginTop: 'auto', padding: '12px 10px', borderTop: '1px solid var(--line)', display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ width: 28, height: 28, borderRadius: 8, background: 'var(--indigo-soft)', border: '1px solid var(--indigo-line)', display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--indigo)' }}>NV</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 500 }}>Niharika V.</div>
          <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)' }}>ARN-128459 · 87 clients</div>
        </div>
      </div>
    </aside>
  );
}

function NVAdvisorClient360Desktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVAdvSidebar />
      <main style={{ flex: 1, padding: '22px 32px 28px', overflow: 'hidden' }}>
        {/* breadcrumb + actions */}
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
          <div className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '.06em' }}>
            <span>Book</span> <span style={{ margin: '0 8px', color: 'var(--ink-4)' }}>›</span>
            <span>HNI · Tier-1</span> <span style={{ margin: '0 8px', color: 'var(--ink-4)' }}>›</span>
            <span style={{ color: 'var(--ink)' }}>Aaditya Mehta</span>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
            <button className="nv-btn" style={{ padding: '7px 12px', fontSize: 12 }}>⤢ Open as client</button>
            <button className="nv-btn" style={{ padding: '7px 12px', fontSize: 12 }}>≣ Notes</button>
            <button className="nv-btn" style={{ padding: '7px 12px', fontSize: 12 }}>↗ Share review</button>
            <button className="nv-btn nv-btn-primary" style={{ padding: '7px 12px', fontSize: 12 }}>New proposal →</button>
          </div>
        </div>

        {/* client identity row */}
        <div className="nv-card" style={{ padding: 22, marginBottom: 16, display: 'grid', gridTemplateColumns: '1fr 1px 1.4fr', gap: 28, alignItems: 'center' }}>
          <div style={{ display: 'flex', gap: 18, alignItems: 'center' }}>
            <div style={{ width: 72, height: 72, borderRadius: 18, background: 'linear-gradient(150deg, var(--indigo) 0%, var(--indigo-2) 100%)', display: 'grid', placeItems: 'center', color: 'var(--bg-0)', fontFamily: 'var(--display)', fontSize: 28, flex: 'none' }}>AM</div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span className="nv-pill nv-pill-indigo">HNI · TIER 1</span>
                <span className="nv-pill" style={{ background: 'var(--mint-soft)', color: 'var(--mint)', borderColor: 'var(--mint-line)' }}>ACTIVE</span>
              </div>
              <div className="nv-serif" style={{ fontSize: 32, letterSpacing: '-0.025em' }}>Aaditya Mehta</div>
              <div className="nv-mono" style={{ fontSize: 11.5, color: 'var(--ink-3)', letterSpacing: '.04em', marginTop: 2 }}>BENGALURU · 47Y · KYC ✓ · since 2019</div>
            </div>
          </div>
          <div style={{ width: 1, height: 80, background: 'var(--line)' }} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
            {[
              { l: 'AUM', v: '₹2.41', u: 'Cr', sub: '+12.4% YTD', c: 'mint' },
              { l: 'XIRR', v: '14.2', u: '%', sub: 'vs bench +2.1', c: 'mint' },
              { l: 'Health', v: '82', u: '/100', sub: 'Grade B+', c: 'amber' },
              { l: 'Risk drift', v: '+1.4', u: 'σ', sub: 'over target', c: 'amber' },
            ].map((m) => (
              <div key={m.l}>
                <div className="nv-mono" style={{ fontSize: 9.5, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>{m.l}</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginTop: 4 }}>
                  <span className="nv-serif nv-num" style={{ fontSize: 28, letterSpacing: '-0.03em', color: m.c === 'amber' ? 'var(--amber)' : 'var(--ink)' }}>{m.v}</span>
                  <span className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{m.u}</span>
                </div>
                <div className="nv-mono nv-num" style={{ fontSize: 10, color: `var(--${m.c})`, letterSpacing: '.02em', marginTop: 2 }}>{m.sub}</div>
              </div>
            ))}
          </div>
        </div>

        {/* main grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
          {/* LEFT — allocation + perf */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="nv-card" style={{ padding: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
                <span className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Performance · 12-month NAV</span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                  {['1M', '3M', '6M', '1Y', '3Y', 'Max'].map((t, i) => (
                    <span key={t} style={{ fontSize: 11, padding: '3px 9px', borderRadius: 5, background: i === 3 ? 'var(--bg-2)' : 'transparent', color: i === 3 ? 'var(--ink)' : 'var(--ink-3)', border: i === 3 ? '1px solid var(--line-2)' : '1px solid transparent', cursor: 'pointer' }}>{t}</span>
                  ))}
                </span>
              </div>
              <svg viewBox="0 0 720 200" style={{ width: '100%', height: 200 }}>
                <defs>
                  <linearGradient id="perf-g" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stopColor="var(--mint)" stopOpacity=".25" />
                    <stop offset="1" stopColor="var(--mint)" stopOpacity="0" />
                  </linearGradient>
                </defs>
                {[40, 80, 120, 160].map((y) => (
                  <line key={y} x1="0" y1={y} x2="720" y2={y} stroke="var(--line)" strokeDasharray="2 4" />
                ))}
                {/* benchmark */}
                <path d="M0,140 C60,135 110,130 160,128 C220,125 260,118 320,112 C380,108 420,98 480,90 C540,86 600,78 660,70 L720,62" fill="none" stroke="var(--ink-3)" strokeWidth="1.5" strokeDasharray="4 4" />
                {/* portfolio */}
                <path d="M0,150 C50,142 100,138 160,128 C200,118 260,110 320,98 C380,84 440,72 500,58 C540,48 600,40 660,28 L720,18 L720,200 L0,200 Z" fill="url(#perf-g)" />
                <path d="M0,150 C50,142 100,138 160,128 C200,118 260,110 320,98 C380,84 440,72 500,58 C540,48 600,40 660,28 L720,18" fill="none" stroke="var(--mint)" strokeWidth="2" />
                {/* annotation markers */}
                <g>
                  <circle cx="320" cy="98" r="5" fill="var(--bg-0)" stroke="var(--amber)" strokeWidth="2" />
                  <text x="328" y="92" fontFamily="var(--mono)" fontSize="9" fill="var(--amber)">↑ topped HDFC</text>
                  <circle cx="500" cy="58" r="5" fill="var(--bg-0)" stroke="var(--mint)" strokeWidth="2" />
                  <text x="508" y="52" fontFamily="var(--mono)" fontSize="9" fill="var(--mint)">+Infosys 4%</text>
                </g>
                {['Nov 25', 'Feb', 'May', 'Aug', 'Nov 26'].map((m, i) => (
                  <text key={m} x={i * 180} y="194" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">{m}</text>
                ))}
              </svg>
              <div style={{ display: 'flex', gap: 24, marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--line)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 14, height: 2, background: 'var(--mint)' }} />
                  <span style={{ fontSize: 11.5 }}>Portfolio · +18.7%</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 14, height: 1, background: 'var(--ink-3)', borderTop: '1px dashed var(--ink-3)' }} />
                  <span style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>NIFTY 500 · +16.6%</span>
                </div>
                <span style={{ marginLeft: 'auto', fontSize: 11.5, color: 'var(--mint)' }}>α +2.1% · β 0.86 · Sharpe 1.34</span>
              </div>
            </div>

            {/* allocation rings */}
            <div className="nv-card" style={{ padding: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
                <span className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Allocation · vs IPS policy</span>
                <span style={{ marginLeft: 'auto', fontSize: 11.5, color: 'var(--amber)' }}>2 of 5 outside band</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
                {[
                  { l: 'Equity',   v: 68, t: 60, hi: 70, c: 'mint' },
                  { l: 'Debt',     v: 18, t: 25, hi: 30, c: 'amber' },
                  { l: 'Gold',     v: 6,  t: 8,  hi: 12, c: 'mint' },
                  { l: 'Intl',     v: 6,  t: 5,  hi: 10, c: 'mint' },
                  { l: 'Cash',     v: 2,  t: 2,  hi: 5,  c: 'mint' },
                ].map((a) => {
                  const r = 26;
                  const C = 2 * Math.PI * r;
                  const dash = C * (a.v / 100);
                  return (
                    <div key={a.l} style={{ textAlign: 'center', padding: '8px 0' }}>
                      <svg width="80" height="80" viewBox="0 0 80 80">
                        <circle cx="40" cy="40" r={r} fill="none" stroke="var(--bg-3)" strokeWidth="6" />
                        <circle cx="40" cy="40" r={r} fill="none" stroke={`var(--${a.c})`} strokeWidth="6" strokeDasharray={`${dash} ${C - dash}`} strokeLinecap="round" transform="rotate(-90 40 40)" />
                        <text x="40" y="44" textAnchor="middle" fontFamily="var(--display)" fontSize="20" fill="var(--ink)">{a.v}</text>
                        <text x="40" y="56" textAnchor="middle" fontFamily="var(--mono)" fontSize="8" fill="var(--ink-3)">%</text>
                      </svg>
                      <div style={{ fontSize: 12.5, fontWeight: 500 }}>{a.l}</div>
                      <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.04em', marginTop: 1 }}>policy · {a.t} ({a.v}-{a.hi})</div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* RIGHT — alerts + activity + goals */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="nv-card-2" style={{ padding: 18 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
                <span className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Alerts · 3 open</span>
                <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--ink-3)' }}>auto-cleared · 12</span>
              </div>
              {[
                { sev: 'danger', t: 'KYC due in 38 days', s: 'PAN-Aadhaar relink', a: 'Send' },
                { sev: 'amber', t: 'Equity 8pt over policy', s: 'IPS band 60-70%', a: 'Rebal' },
                { sev: 'indigo', t: 'SIP failed Nov 5', s: 'Axis bluechip · ₹15k', a: 'Retry' },
              ].map((r) => (
                <div key={r.t} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 0', borderTop: '1px solid var(--line)' }}>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: `var(--${r.sev})`, flex: 'none' }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>{r.t}</div>
                    <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.05em', textTransform: 'uppercase', marginTop: 2 }}>{r.s}</div>
                  </div>
                  <button className="nv-btn" style={{ padding: '5px 11px', fontSize: 11 }}>{r.a}</button>
                </div>
              ))}
            </div>

            <div className="nv-card-2" style={{ padding: 18 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
                <span className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Activity · last 30 days</span>
                <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--indigo)' }}>open thread →</span>
              </div>
              {[
                { t: 'Approved · trim HDFC by ₹74k', d: '2 days ago', c: 'mint' },
                { t: 'Asked: should I add gold?', d: '5 days ago', c: 'indigo' },
                { t: 'SIP top-up · ₹3,500/mo retirement', d: '12 days ago', c: 'mint' },
                { t: 'Reviewed Q3 statement', d: '21 days ago', c: 'ink-3' },
                { t: 'Q&A: leaving Axis Bluechip?', d: '24 days ago', c: 'indigo' },
              ].map((a, i) => (
                <div key={i} style={{ display: 'flex', gap: 12, padding: '8px 0', position: 'relative' }}>
                  <div style={{ position: 'relative', width: 12, flex: 'none' }}>
                    <span style={{ position: 'absolute', top: 6, left: 4, width: 6, height: 6, borderRadius: '50%', background: `var(--${a.c})` }} />
                    {i < 4 && <span style={{ position: 'absolute', top: 16, left: 6, bottom: -8, width: 1, background: 'var(--line-2)' }} />}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12.5 }}>{a.t}</div>
                    <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.04em' }}>{a.d}</div>
                  </div>
                </div>
              ))}
            </div>

            <div className="nv-card-2" style={{ padding: 18 }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 12 }}>Goals · 3 active</div>
              {[
                { g: 'Retirement · 2046', p: 62, c: 'mint' },
                { g: 'House · 2029', p: 88, c: 'mint' },
                { g: 'Child · MS 2034', p: 41, c: 'amber' },
              ].map((g) => (
                <div key={g.g} style={{ padding: '8px 0', borderTop: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', marginBottom: 5 }}>
                    <span style={{ fontSize: 12.5 }}>{g.g}</span>
                    <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 11, color: `var(--${g.c})` }}>{g.p}%</span>
                  </div>
                  <div style={{ height: 4, background: 'var(--bg-3)', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ width: `${g.p}%`, height: '100%', background: `var(--${g.c})` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function NVAdvisorClient360Mobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '6px 18px 10px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ color: 'var(--ink-2)', fontSize: 18 }}>‹ Book</span>
        <span className="nv-pill nv-pill-indigo" style={{ marginLeft: 'auto', fontSize: 9 }}>HNI</span>
      </div>

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        {/* client header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
          <div style={{ width: 52, height: 52, borderRadius: 14, background: 'linear-gradient(150deg, var(--indigo) 0%, var(--indigo-2) 100%)', display: 'grid', placeItems: 'center', color: 'var(--bg-0)', fontFamily: 'var(--display)', fontSize: 20, flex: 'none' }}>AM</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="nv-serif" style={{ fontSize: 21, letterSpacing: '-0.02em' }}>Aaditya Mehta</div>
            <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.04em' }}>BENGALURU · 47Y · since 2019</div>
          </div>
        </div>

        {/* hero metrics */}
        <div className="nv-card" style={{ padding: 14, marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
            <div>
              <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>AUM</div>
              <div className="nv-serif nv-num" style={{ fontSize: 36, letterSpacing: '-0.035em', lineHeight: 1 }}>₹2.41<span style={{ fontSize: 16, color: 'var(--ink-3)' }}>Cr</span></div>
              <div className="nv-mono" style={{ fontSize: 10, color: 'var(--mint)', marginTop: 4 }}>+12.4% YTD</div>
            </div>
            <svg viewBox="0 0 110 50" style={{ width: 110, height: 50 }}>
              <defs><linearGradient id="ad-m" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--mint)" stopOpacity=".25" /><stop offset="1" stopColor="var(--mint)" stopOpacity="0" /></linearGradient></defs>
              <path d="M0,42 C20,38 40,32 60,24 C80,18 95,12 110,6 L110,50 L0,50 Z" fill="url(#ad-m)" />
              <path d="M0,42 C20,38 40,32 60,24 C80,18 95,12 110,6" fill="none" stroke="var(--mint)" strokeWidth="1.8" />
            </svg>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
            <div>
              <div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>XIRR</div>
              <div className="nv-serif nv-num" style={{ fontSize: 18 }}>14.2%</div>
            </div>
            <div>
              <div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>Health</div>
              <div className="nv-serif nv-num" style={{ fontSize: 18, color: 'var(--amber)' }}>82</div>
            </div>
            <div>
              <div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>Alerts</div>
              <div className="nv-serif nv-num" style={{ fontSize: 18, color: 'var(--danger)' }}>3</div>
            </div>
          </div>
        </div>

        {/* alerts */}
        <div className="nv-card-2" style={{ padding: 13, marginBottom: 10 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 8 }}>Open alerts · 3</div>
          {[
            { sev: 'danger', t: 'KYC due · 38 days' },
            { sev: 'amber', t: 'Equity 8pt over policy' },
            { sev: 'indigo', t: 'SIP failed Nov 5' },
          ].map((r) => (
            <div key={r.t} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderTop: '1px solid var(--line)' }}>
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: `var(--${r.sev})`, flex: 'none' }} />
              <span style={{ fontSize: 12.5, flex: 1 }}>{r.t}</span>
              <span style={{ color: 'var(--ink-3)' }}>›</span>
            </div>
          ))}
        </div>

        {/* recent activity */}
        <div className="nv-card-2" style={{ padding: 13 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 8 }}>Activity</div>
          {[
            { t: 'Approved trim HDFC ₹74k', d: '2d', c: 'mint' },
            { t: 'Q&A · gold allocation', d: '5d', c: 'indigo' },
            { t: 'SIP top-up ₹3,500/mo', d: '12d', c: 'mint' },
          ].map((a) => (
            <div key={a.t} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderTop: '1px solid var(--line)' }}>
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: `var(--${a.c})`, flex: 'none' }} />
              <span style={{ fontSize: 12, flex: 1 }}>{a.t}</span>
              <span className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>{a.d}</span>
            </div>
          ))}
        </div>
      </div>

      {/* sticky CTA */}
      <div style={{ padding: '10px 18px 14px', borderTop: '1px solid var(--line)', display: 'flex', gap: 8 }}>
        <button className="nv-btn" style={{ padding: '11px 14px', fontSize: 12.5 }}>≣ Notes</button>
        <button className="nv-btn nv-btn-primary" style={{ flex: 1, justifyContent: 'center', padding: '11px', fontSize: 13 }}>New proposal →</button>
      </div>
      <div className="nv-homebar"></div>
    </div>
  );
}

Object.assign(window, { NVAdvisorClient360Desktop, NVAdvisorClient360Mobile });
