// ─── Nivesh · Goals + Tax dashboards — desktop + mobile ───

// ═══════════════════════════════════════════════════════════
// GOALS — multi-goal fan trajectory
// ═══════════════════════════════════════════════════════════
function NVGoalFanChart() {
  return (
    <svg viewBox="0 0 720 280" style={{ width: '100%', height: 280 }}>
      <defs>
        <linearGradient id="goal-fan-low" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--mint)" stopOpacity=".35" />
          <stop offset="1" stopColor="var(--mint)" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="goal-fan-high" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--mint)" stopOpacity=".18" />
          <stop offset="1" stopColor="var(--mint)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* gridlines */}
      {[40, 100, 160, 220].map((y) => <line key={y} x1="40" y1={y} x2="720" y2={y} stroke="var(--line)" strokeDasharray="2 4" />)}
      {['₹6 Cr', '₹4 Cr', '₹2 Cr', '₹0'].map((l, i) => (
        <text key={l} x="32" y={40 + i * 60 + 4} textAnchor="end" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">{l}</text>
      ))}

      {/* 95% band */}
      <path d="M40,220 C150,210 280,180 420,130 C540,80 640,40 720,12 L720,90 C640,108 540,134 420,158 C280,190 150,210 40,222 Z" fill="url(#goal-fan-high)" />
      {/* 68% band */}
      <path d="M40,220 C150,212 280,188 420,148 C540,108 640,72 720,40 L720,80 C640,98 540,124 420,148 C280,182 150,206 40,222 Z" fill="url(#goal-fan-low)" />

      {/* required line (target) */}
      <path d="M40,220 C150,200 280,160 420,108 C540,68 640,32 720,12" fill="none" stroke="var(--ink-3)" strokeWidth="1.2" strokeDasharray="4 4" />
      {/* median projection */}
      <path d="M40,220 C150,206 280,178 420,138 C540,98 640,58 720,28" fill="none" stroke="var(--mint)" strokeWidth="2.5" />

      {/* goal targets */}
      {[
        { x: 178, y: 188, l: 'Home', y2: 2029, ok: true },
        { x: 380, y: 142, l: 'Daughter MS', y2: 2034, ok: false },
        { x: 720, y: 28, l: 'Retirement', y2: 2046, ok: true },
      ].map((g, i) => (
        <g key={g.l}>
          <line x1={g.x} y1="20" x2={g.x} y2="240" stroke={g.ok ? 'var(--mint-line)' : 'var(--amber-line)'} strokeWidth="1" strokeDasharray="2 3" />
          <circle cx={g.x} cy={g.y} r="7" fill={g.ok ? 'var(--mint)' : 'var(--amber)'} stroke="var(--bg-0)" strokeWidth="2" />
          <text x={g.x + (i === 2 ? -8 : 10)} y={g.y - 8} textAnchor={i === 2 ? 'end' : 'start'} fontFamily="var(--sans)" fontSize="11" fontWeight="500" fill={g.ok ? 'var(--mint)' : 'var(--amber)'}>{g.l}</text>
          <text x={g.x + (i === 2 ? -8 : 10)} y={g.y + 8} textAnchor={i === 2 ? 'end' : 'start'} fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">{g.y2}</text>
        </g>
      ))}

      {/* x axis */}
      <line x1="40" y1="240" x2="720" y2="240" stroke="var(--ink-4)" strokeWidth="1" />
      {[2026, 2030, 2034, 2038, 2042, 2046].map((y, i) => (
        <text key={y} x={40 + i * 136} y="258" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">{y}</text>
      ))}
    </svg>
  );
}

function NVDashGoalsDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVSidebar active="goals" />
      <main style={{ flex: 1, padding: '24px 36px 32px', overflow: 'hidden' }}>
        <NVDashHeader kind="goals" title="Two on track, one ₹1.4 Cr short." sev="amber"
          kpis={[
            { l: 'On track', v: '2 / 3', s: 'goals', sub: 'home · retire', c: 'mint' },
            { l: 'Total target', v: '₹6.5', s: 'Cr', sub: 'by 2046', c: 'indigo' },
            { l: 'Current trajectory', v: '₹5.1', s: 'Cr', sub: 'at median', c: 'amber' },
            { l: 'Gap to close', v: '₹1.4', s: 'Cr', sub: '+₹3,500/mo', c: 'amber' },
          ]}
        />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18 }}>
          <div className="nv-card" style={{ padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Trajectory · median + 68% / 95% bands</div>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 16, fontSize: 11 }}>
                <span><span style={{ width: 10, height: 2, background: 'var(--mint)', display: 'inline-block', marginRight: 6 }} />you · median</span>
                <span><span style={{ width: 10, height: 0, borderBottom: '1px dashed var(--ink-3)', display: 'inline-block', marginRight: 6, verticalAlign: 'middle' }} />required</span>
              </span>
            </div>
            <NVGoalFanChart />
          </div>

          <aside className="nv-card-2" style={{ padding: 18 }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--amber)', textTransform: 'uppercase' }}>● Daughter · MS · 2034</div>
            <div className="nv-serif" style={{ fontSize: 24, letterSpacing: '-0.02em', marginTop: 6 }}>₹85 L target</div>

            <div style={{ marginTop: 16 }}>
              <div style={{ display: 'flex', alignItems: 'baseline' }}>
                <span className="nv-serif nv-num" style={{ fontSize: 36, letterSpacing: '-0.03em' }}>41<span style={{ fontSize: 14, color: 'var(--ink-3)' }}>%</span></span>
                <span className="nv-mono" style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--ink-3)' }}>funded</span>
              </div>
              <div style={{ height: 8, background: 'var(--bg-3)', borderRadius: 4, marginTop: 6, overflow: 'hidden' }}>
                <div style={{ width: '41%', height: '100%', background: 'linear-gradient(90deg, var(--amber-2), var(--amber))' }} />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginTop: 16 }}>
              {[
                { l: 'On hand', v: '₹34.6 L' },
                { l: 'Required', v: '₹85.0 L' },
                { l: 'Monthly now', v: '₹7,200' },
                { l: 'Need', v: '₹11,200', warn: true },
              ].map((m) => (
                <div key={m.l} style={{ padding: '10px 12px', background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
                  <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.1em', textTransform: 'uppercase' }}>{m.l}</div>
                  <div className="nv-serif nv-num" style={{ fontSize: 18, marginTop: 2, color: m.warn ? 'var(--amber)' : 'var(--ink)' }}>{m.v}</div>
                </div>
              ))}
            </div>

            <div className="nv-card" style={{ padding: 14, marginTop: 16, background: 'var(--bg-1)' }}>
              <div className="nv-mono" style={{ fontSize: 9, color: 'var(--mint)', letterSpacing: '.14em', textTransform: 'uppercase' }}>SUGGESTED MOVE</div>
              <div style={{ fontSize: 13, fontWeight: 500, marginTop: 6 }}>↑ SIP by ₹4,000/mo · close gap by 2032</div>
              <button className="nv-btn nv-btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '10px', marginTop: 10, fontSize: 12 }}>Apply →</button>
            </div>
          </aside>
        </div>

        {/* all goals */}
        <div className="nv-card" style={{ padding: 18, marginTop: 16 }}>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 12 }}>All goals · funded %</div>
          {[
            { g: 'Home · down payment', y: 2029, t: '40 L', f: 88, m: 12400, s: 'mint' },
            { g: 'Daughter · MS', y: 2034, t: '85 L', f: 41, m: 7200, s: 'amber' },
            { g: 'Retirement', y: 2046, t: '4.2 Cr', f: 62, m: 18500, s: 'mint' },
            { g: 'Emergency fund', y: 2026, t: '6 L', f: 100, m: 0, s: 'mint' },
          ].map((g) => (
            <div key={g.g} style={{ display: 'grid', gridTemplateColumns: '1.6fr 80px 1fr 80px 90px 50px', alignItems: 'center', gap: 14, padding: '10px 0', borderTop: '1px solid var(--line)' }}>
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 500 }}>{g.g}</div>
                <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 2, letterSpacing: '.04em' }}>by {g.y} · ₹{g.t}</div>
              </div>
              <div className="nv-mono nv-num" style={{ fontSize: 13, color: `var(--${g.s})` }}>{g.f}%</div>
              <div style={{ height: 6, background: 'var(--bg-2)', borderRadius: 3 }}>
                <div style={{ width: `${g.f}%`, height: '100%', background: `var(--${g.s})`, borderRadius: 3 }} />
              </div>
              <div className="nv-mono nv-num" style={{ fontSize: 12, color: 'var(--ink-2)' }}>₹{g.m.toLocaleString()}/mo</div>
              <span className={`nv-pill nv-pill-${g.s}`} style={{ fontSize: 9 }}>{g.f === 100 ? 'DONE' : g.s === 'mint' ? 'ON TRACK' : 'BEHIND'}</span>
              <span style={{ color: 'var(--ink-3)', textAlign: 'right' }}>›</span>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function NVDashGoalsMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>
      <NVMobileDashHead tag="WATCH" title="Goals" sev="amber" />

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        <div className="nv-card" style={{ padding: 14, marginBottom: 12 }}>
          <div className="nv-serif" style={{ fontSize: 21, lineHeight: 1.18, letterSpacing: '-0.02em' }}>
            <span style={{ color: 'var(--mint)' }}>2 of 3</span> on track. One <span style={{ color: 'var(--amber)' }}>₹1.4 Cr</span> short.
          </div>
        </div>

        {/* fan chart compact */}
        <div className="nv-card" style={{ padding: '12px 10px 6px', marginBottom: 12 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase', paddingLeft: 4 }}>Trajectory · 2026–2046</div>
          <svg viewBox="0 0 320 120" style={{ width: '100%', marginTop: 4 }}>
            <defs><linearGradient id="g-mn" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--mint)" stopOpacity=".3"/><stop offset="1" stopColor="var(--mint)" stopOpacity="0"/></linearGradient></defs>
            <path d="M0,108 C60,100 120,80 200,46 C260,22 300,8 320,4 L320,40 C300,42 260,54 200,72 C120,96 60,106 0,110 Z" fill="url(#g-mn)" />
            <path d="M0,108 C60,98 120,76 200,42 C260,18 300,6 320,2" fill="none" stroke="var(--ink-3)" strokeWidth="1" strokeDasharray="3 3" />
            <path d="M0,108 C60,102 120,84 200,52 C260,28 300,14 320,8" fill="none" stroke="var(--mint)" strokeWidth="1.8" />
            <circle cx="80" cy="90" r="4" fill="var(--mint)" /><text x="86" y="86" fontFamily="var(--mono)" fontSize="8" fill="var(--mint)">Home</text>
            <circle cx="160" cy="56" r="4" fill="var(--amber)" /><text x="166" y="52" fontFamily="var(--mono)" fontSize="8" fill="var(--amber)">MS · short</text>
            <circle cx="318" cy="8" r="4" fill="var(--mint)" /><text x="312" y="20" textAnchor="end" fontFamily="var(--mono)" fontSize="8" fill="var(--mint)">Retire</text>
          </svg>
        </div>

        {[
          { g: 'Home · 2029', f: 88, m: '₹12.4k', s: 'mint' },
          { g: 'Daughter · MS 2034', f: 41, m: '₹7.2k', s: 'amber' },
          { g: 'Retirement · 2046', f: 62, m: '₹18.5k', s: 'mint' },
        ].map((g) => (
          <div key={g.g} className="nv-card-2" style={{ padding: 12, marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'baseline' }}>
              <span style={{ fontSize: 13, fontWeight: 500 }}>{g.g}</span>
              <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 12, color: `var(--${g.s})` }}>{g.f}%</span>
            </div>
            <div style={{ height: 4, background: 'var(--bg-3)', borderRadius: 2, marginTop: 8 }}>
              <div style={{ width: `${g.f}%`, height: '100%', background: `var(--${g.s})` }} />
            </div>
            <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6, letterSpacing: '.04em' }}>SIP · {g.m}/mo</div>
          </div>
        ))}
      </div>
      <NVMobileTabs />
      <div className="nv-homebar"></div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// TAX — harvest stack + window timeline
// ═══════════════════════════════════════════════════════════
function NVTaxStackChart() {
  // months Apr → Mar
  const months = ['Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar'];
  const gains = [0, 2.4, 0, 4.1, 1.8, 0, 3.2, 0, 5.6, 0, 0, 0]; // STCG
  const losses = [-1.2, 0, -2.8, 0, 0, -1.4, 0, 0, 0, -2.6, -3.8, -1.2]; // potential harvest
  const W = 720, H = 220, bot = 110, top = 110, mw = (W - 60) / months.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: H }}>
      <line x1="40" y1={bot} x2={W} y2={bot} stroke="var(--ink-4)" />
      {[2, 4, 6].map((v) => (
        <g key={v}>
          <line x1="40" y1={bot - v * 12} x2={W} y2={bot - v * 12} stroke="var(--line)" strokeDasharray="2 4" />
          <line x1="40" y1={bot + v * 12} x2={W} y2={bot + v * 12} stroke="var(--line)" strokeDasharray="2 4" />
          <text x="32" y={bot - v * 12 + 4} textAnchor="end" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">{v}L</text>
          <text x="32" y={bot + v * 12 + 4} textAnchor="end" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">{v}L</text>
        </g>
      ))}
      {months.map((m, i) => {
        const x = 50 + i * mw;
        const g = gains[i], l = losses[i];
        return (
          <g key={m}>
            {g > 0 && <rect x={x} y={bot - g * 12} width={mw - 12} height={g * 12} fill="var(--amber)" fillOpacity=".4" stroke="var(--amber)" strokeWidth="1" rx="2" />}
            {l < 0 && <rect x={x} y={bot} width={mw - 12} height={Math.abs(l) * 12} fill="var(--mint)" fillOpacity=".4" stroke="var(--mint)" strokeWidth="1" rx="2" />}
            <text x={x + (mw - 12) / 2} y={H - 6} textAnchor="middle" fontFamily="var(--mono)" fontSize="9" fill={i === 11 ? 'var(--mint)' : 'var(--ink-3)'} fontWeight={i === 11 ? 600 : 400}>{m}</text>
            {i === 11 && (
              <g>
                <rect x={x - 4} y={2} width={mw - 4} height={H - 18} fill="none" stroke="var(--mint)" strokeWidth="1.5" strokeDasharray="3 3" rx="4" />
                <text x={x + (mw - 12) / 2} y={14} textAnchor="middle" fontFamily="var(--mono)" fontSize="9" fill="var(--mint)" fontWeight="600">DEADLINE</text>
              </g>
            )}
          </g>
        );
      })}
      <text x="50" y={bot - 90} fontFamily="var(--mono)" fontSize="9" fill="var(--amber)">▲ realised gains</text>
      <text x="50" y={bot + 96} fontFamily="var(--mono)" fontSize="9" fill="var(--mint)">▼ available losses to harvest</text>
    </svg>
  );
}

function NVDashTaxDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVSidebar active="tax" />
      <main style={{ flex: 1, padding: '24px 36px 32px', overflow: 'hidden' }}>
        <NVDashHeader kind="tax · FY 25–26" title="₹11,520 in your hands if you act by March 31." sev="mint"
          kpis={[
            { l: 'Net tax owed', v: '₹52.4', s: 'k FY', sub: '15% STCG + LTCG', c: 'amber' },
            { l: 'Harvest available', v: '₹38.4', s: 'k loss', sub: 'in 3 lots', c: 'mint' },
            { l: 'Net saved', v: '₹11.5', s: 'k', sub: 'if you harvest', c: 'mint' },
            { l: 'Days to Mar 31', v: '124', s: 'days', sub: 'window open', c: 'indigo' },
          ]}
        />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18 }}>
          <div className="nv-card" style={{ padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Tax timeline · FY 25–26</div>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 16, fontSize: 11 }}>
                <span><span style={{ width: 10, height: 10, background: 'var(--amber-soft)', border: '1px solid var(--amber)', display: 'inline-block', marginRight: 6, verticalAlign: 'middle' }} />gains booked</span>
                <span><span style={{ width: 10, height: 10, background: 'var(--mint-soft)', border: '1px solid var(--mint)', display: 'inline-block', marginRight: 6, verticalAlign: 'middle' }} />losses available</span>
              </span>
            </div>
            <NVTaxStackChart />
          </div>

          <aside className="nv-card-2" style={{ padding: 18 }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--mint)', textTransform: 'uppercase' }}>● 3 lots flagged</div>
            <div className="nv-serif" style={{ fontSize: 24, letterSpacing: '-0.02em', marginTop: 6 }}>Harvest plan</div>

            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
              {[
                { n: 'Wipro · 32 sh', l: '-₹14,200', c: 'mint' },
                { n: 'IDFC First · 180 sh', l: '-₹18,900', c: 'mint' },
                { n: 'Yes Bank · 240 sh', l: '-₹5,300', c: 'mint' },
              ].map((r) => (
                <div key={r.n} style={{ padding: '10px 12px', background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10, display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ width: 26, height: 26, borderRadius: 7, background: 'var(--mint-soft)', border: '1px solid var(--mint-line)', color: 'var(--mint)', display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)', fontSize: 11, flex: 'none' }}>▼</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 500 }}>{r.n}</div>
                    <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.04em' }}>rebuy after day 31</div>
                  </div>
                  <span className="nv-mono nv-num" style={{ fontSize: 12.5, color: `var(--${r.c})` }}>{r.l}</span>
                </div>
              ))}
            </div>

            <div className="nv-card" style={{ padding: 14, marginTop: 16, background: 'var(--bg-1)' }}>
              <div style={{ display: 'flex', alignItems: 'baseline' }}>
                <span className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Net you save</span>
                <span className="nv-serif nv-num" style={{ marginLeft: 'auto', fontSize: 28, color: 'var(--mint)' }}>₹11,520</span>
              </div>
              <button className="nv-btn nv-btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '10px', marginTop: 10, fontSize: 12 }}>Schedule harvest →</button>
            </div>
          </aside>
        </div>

        {/* tax breakdown */}
        <div className="nv-card" style={{ padding: 18, marginTop: 16 }}>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 12 }}>Tax breakdown · FY 25–26</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
            {[
              { l: 'Short-term gains', v: '₹1.18 L', t: '15%', tax: '₹17,700', c: 'amber' },
              { l: 'Long-term gains', v: '₹3.42 L', t: '10% > 1L', tax: '₹24,200', c: 'amber' },
              { l: 'Dividend income', v: '₹46,400', t: 'slab', tax: '₹10,440', c: 'indigo' },
              { l: 'After harvest', v: '₹40.9 k', t: 'net', tax: '-₹11,520', c: 'mint' },
            ].map((r) => (
              <div key={r.l} style={{ padding: '14px 16px', background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
                <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '.1em', textTransform: 'uppercase' }}>{r.l}</div>
                <div className="nv-serif nv-num" style={{ fontSize: 22, marginTop: 4, letterSpacing: '-0.025em' }}>{r.v}</div>
                <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>{r.t} · <span className="nv-num" style={{ color: `var(--${r.c})` }}>{r.tax}</span></div>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}

function NVDashTaxMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>
      <NVMobileDashHead tag="HEALTHY" title="Tax" sev="mint" />

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        <div className="nv-card" style={{ padding: 14, marginBottom: 12 }}>
          <div className="nv-serif" style={{ fontSize: 22, lineHeight: 1.15, letterSpacing: '-0.02em' }}>
            <span style={{ color: 'var(--mint)' }}>₹11,520</span> saved if you act by Mar 31.
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <div style={{ flex: 1 }}><div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Owe</div><div className="nv-serif nv-num" style={{ fontSize: 20, color: 'var(--amber)' }}>₹52.4k</div></div>
            <div style={{ flex: 1 }}><div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Harvest</div><div className="nv-serif nv-num" style={{ fontSize: 20, color: 'var(--mint)' }}>₹38.4k</div></div>
            <div style={{ flex: 1 }}><div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Days</div><div className="nv-serif nv-num" style={{ fontSize: 20, color: 'var(--indigo)' }}>124</div></div>
          </div>
        </div>

        {/* mini timeline */}
        <div className="nv-card" style={{ padding: 12, marginBottom: 12 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 6 }}>FY 25–26 · gains vs harvest</div>
          <svg viewBox="0 0 320 100" style={{ width: '100%' }}>
            <line x1="0" y1="50" x2="320" y2="50" stroke="var(--ink-4)" />
            {['A','M','J','J','A','S','O','N','D','J','F','M'].map((m, i) => {
              const x = i * 26 + 4;
              const gains = [0,2.4,0,4.1,1.8,0,3.2,0,5.6,0,0,0][i];
              const loss = [-1.2,0,-2.8,0,0,-1.4,0,0,0,-2.6,-3.8,-1.2][i];
              return (
                <g key={i}>
                  {gains > 0 && <rect x={x} y={50 - gains * 6} width={20} height={gains * 6} fill="var(--amber)" fillOpacity=".5" rx="2"/>}
                  {loss < 0 && <rect x={x} y={50} width={20} height={Math.abs(loss) * 6} fill="var(--mint)" fillOpacity=".5" rx="2"/>}
                  <text x={x + 10} y={96} textAnchor="middle" fontFamily="var(--mono)" fontSize="8" fill={i === 11 ? 'var(--mint)' : 'var(--ink-3)'}>{m}</text>
                </g>
              );
            })}
          </svg>
        </div>

        <div className="nv-card-2" style={{ padding: 13 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--mint)', textTransform: 'uppercase', marginBottom: 6 }}>Harvest plan · 3 lots</div>
          {[
            { n: 'Wipro · 32 sh', v: '-₹14.2k' },
            { n: 'IDFC First · 180 sh', v: '-₹18.9k' },
            { n: 'Yes Bank · 240 sh', v: '-₹5.3k' },
          ].map((r) => (
            <div key={r.n} style={{ display: 'flex', padding: '7px 0', borderTop: '1px solid var(--line)' }}>
              <span style={{ fontSize: 12 }}>{r.n}</span>
              <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--mint)' }}>{r.v}</span>
            </div>
          ))}
          <button className="nv-btn nv-btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '10px', marginTop: 12, fontSize: 12 }}>Schedule harvest →</button>
        </div>
      </div>
      <NVMobileTabs />
      <div className="nv-homebar"></div>
    </div>
  );
}

Object.assign(window, {
  NVDashGoalsDesktop, NVDashGoalsMobile,
  NVDashTaxDesktop, NVDashTaxMobile,
});
