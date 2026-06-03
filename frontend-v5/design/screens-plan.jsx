// ─── Nivesh · Plan board + Portfolio builder + Instrument allocation ───

// ═══════════════════════════════════════════════════════════
// PLAN BOARD — kanban
// ═══════════════════════════════════════════════════════════
function NVPlanCard({ sev, title, sub, value, due, owner }) {
  return (
    <div className="nv-card" style={{ padding: 12, marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span className={`nv-pill nv-pill-${sev}`} style={{ fontSize: 9 }}>{sub}</span>
        {value && <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 11, color: `var(--${sev})` }}>{value}</span>}
      </div>
      <div style={{ fontSize: 13, fontWeight: 500, letterSpacing: '-0.005em', lineHeight: 1.3 }}>{title}</div>
      <div style={{ display: 'flex', alignItems: 'center', marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--line)' }}>
        <div style={{ width: 18, height: 18, borderRadius: 5, background: 'var(--bg-3)', display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--ink-2)' }}>{owner}</div>
        {due && <span className="nv-mono" style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)', letterSpacing: '.04em' }}>{due}</span>}
      </div>
    </div>
  );
}

function NVPlanBoardDesktop() {
  const cols = [
    { id: 'backlog', name: 'Backlog', count: 4, accent: 'ink-3', cards: [
      { sev: 'amber', title: 'Cut exposure to Yes Bank — earnings risk', sub: 'RISK', value: '₹1.2L', due: 'No date', owner: 'AK' },
      { sev: 'indigo', title: 'Review SIP frequency · monthly vs weekly', sub: 'OPTIM', due: 'Q1', owner: 'AK' },
      { sev: 'mint', title: 'Switch from regular → direct mutual funds (3 funds)', sub: 'COST', value: '₹26k/yr', due: 'No date', owner: 'AK' },
      { sev: 'indigo', title: 'Open NPS Tier-1 for 80CCD(1B) ₹50k extra', sub: 'TAX', value: '₹15k', due: 'Mar', owner: 'AK' },
    ]},
    { id: 'week', name: 'This week', count: 3, accent: 'amber', cards: [
      { sev: 'amber', title: 'Trim HDFC Bank from 8.0% → 5.0%', sub: 'CONC', value: '+₹0.42L/yr', due: 'Mon, Dec 2', owner: 'AK' },
      { sev: 'indigo', title: 'Consolidate 3 large-cap funds with 71% overlap', sub: 'DIVERSE', value: '₹14k', due: 'Wed, Dec 4', owner: 'AK' },
      { sev: 'mint', title: 'Schedule tax-loss harvest of 3 lots', sub: 'TAX', value: '₹11.5k', due: 'Fri, Dec 6', owner: 'AK' },
    ]},
    { id: 'flight', name: 'In flight', count: 2, accent: 'indigo', cards: [
      { sev: 'indigo', title: 'Move ₹1.2L from savings → Quant Liquid Direct', sub: 'CASH', value: '+₹3.9k/yr', due: 'T+2 settle', owner: 'AK' },
      { sev: 'mint', title: '↑ Retirement SIP from ₹15k → ₹18.5k/mo', sub: 'GOAL', value: '₹1.4Cr by 2046', due: 'Active', owner: 'AK' },
    ]},
    { id: 'done', name: 'Done · 30d', count: 5, accent: 'mint', cards: [
      { sev: 'mint', title: 'Sold ICICI Pru Bluechip — reinvested PPFAS', sub: 'COST', value: '₹8.2k saved', due: 'Nov 18', owner: 'AK' },
      { sev: 'mint', title: 'Linked KYC after PAN-Aadhaar fix', sub: 'COMPLY', due: 'Nov 11', owner: 'AK' },
      { sev: 'mint', title: 'Reduced gold from 8% → 6% per IPS', sub: 'IPS', due: 'Nov 4', owner: 'AK' },
    ]},
  ];

  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVSidebar active="overview" />
      <main style={{ flex: 1, padding: '24px 32px 32px', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {/* header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 18 }}>
          <div>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Workspace · plan board</div>
            <h1 className="nv-serif" style={{ fontSize: 36, letterSpacing: '-0.025em', margin: '4px 0 0', lineHeight: 1.05 }}>Your plan, end-to-end.</h1>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 11px', borderRadius: 999, background: 'var(--bg-2)', border: '1px solid var(--line-2)' }}>
              <span className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '.06em' }}>OWNER</span>
              <span style={{ fontSize: 12 }}>You</span>
            </div>
            <button className="nv-btn" style={{ padding: '8px 12px', fontSize: 12 }}>Filter</button>
            <button className="nv-btn" style={{ padding: '8px 12px', fontSize: 12 }}>＋ Move</button>
            <button className="nv-btn nv-btn-primary" style={{ padding: '8px 12px', fontSize: 12 }}>Execute week →</button>
          </div>
        </div>

        {/* summary strip */}
        <div className="nv-card-2" style={{ padding: '14px 20px', marginBottom: 20, display: 'flex', alignItems: 'center', gap: 30 }}>
          <div>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>This week</div>
            <div className="nv-serif nv-num" style={{ fontSize: 26, letterSpacing: '-0.025em' }}>3 moves · <span style={{ color: 'var(--mint)' }}>+₹25.9k/yr</span></div>
          </div>
          <div style={{ width: 1, height: 36, background: 'var(--line)' }} />
          {[
            { l: 'Health change', v: '+4 pt', c: 'mint' },
            { l: 'Cash needed', v: '₹0', c: 'mint' },
            { l: 'Compliance', v: 'all ✓', c: 'mint' },
            { l: 'Auto-batch', v: 'on', c: 'indigo' },
          ].map((m) => (
            <div key={m.l}>
              <div className="nv-mono" style={{ fontSize: 9.5, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>{m.l}</div>
              <div style={{ fontSize: 14, color: `var(--${m.c})`, marginTop: 4 }}>{m.v}</div>
            </div>
          ))}
        </div>

        {/* kanban */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, flex: 1, minHeight: 0 }}>
          {cols.map((c) => (
            <div key={c.id} style={{ background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 14, padding: 14, display: 'flex', flexDirection: 'column' }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: `var(--${c.accent})`, marginRight: 8 }} />
                <span style={{ fontSize: 13, fontWeight: 500 }}>{c.name}</span>
                <span className="nv-mono" style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)', letterSpacing: '.06em' }}>{c.count}</span>
                <span style={{ color: 'var(--ink-3)', marginLeft: 8, fontSize: 12 }}>＋</span>
              </div>
              <div>
                {c.cards.map((card, i) => <NVPlanCard key={i} {...card} />)}
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function NVPlanBoardMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>
      <div style={{ padding: '6px 18px 8px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <div>
          <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Workspace</div>
          <div className="nv-serif" style={{ fontSize: 18 }}>Plan board</div>
        </div>
        <span className="nv-pill nv-pill-amber" style={{ marginLeft: 'auto', fontSize: 9 }}>3 THIS WK</span>
      </div>

      {/* segmented control */}
      <div style={{ padding: '4px 18px 10px', display: 'flex', gap: 4 }}>
        {[['Week', 3, true], ['Flight', 2], ['Backlog', 4], ['Done', 5]].map(([t, n, on]) => (
          <div key={t} style={{ flex: 1, textAlign: 'center', padding: '7px 8px', borderRadius: 7, background: on ? 'var(--bg-2)' : 'transparent', border: on ? '1px solid var(--line-2)' : '1px solid transparent' }}>
            <div style={{ fontSize: 11.5, color: on ? 'var(--ink)' : 'var(--ink-3)' }}>{t}</div>
            <div className="nv-mono" style={{ fontSize: 9, color: on ? 'var(--mint)' : 'var(--ink-4)', letterSpacing: '.04em' }}>{n}</div>
          </div>
        ))}
      </div>

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        <div className="nv-card-2" style={{ padding: 12, marginBottom: 12, display: 'flex', alignItems: 'center' }}>
          <div>
            <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>This week</div>
            <div className="nv-serif" style={{ fontSize: 18 }}>+<span className="nv-num">₹25.9k</span>/yr</div>
          </div>
          <button className="nv-btn nv-btn-primary" style={{ marginLeft: 'auto', padding: '8px 12px', fontSize: 11.5 }}>Execute all →</button>
        </div>
        {[
          { sev: 'amber', t: 'Trim HDFC Bank · 8 → 5%', v: '+₹0.42L', d: 'Mon · Dec 2' },
          { sev: 'indigo', t: 'Consolidate 3 large-caps', v: '₹14k', d: 'Wed · Dec 4' },
          { sev: 'mint', t: 'Tax-loss harvest · 3 lots', v: '₹11.5k', d: 'Fri · Dec 6' },
        ].map((c, i) => (
          <div key={i} className="nv-card" style={{ padding: 12, marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className={`nv-pill nv-pill-${c.sev}`} style={{ fontSize: 9 }}>{c.sev === 'amber' ? 'CONC' : c.sev === 'indigo' ? 'DIVERSE' : 'TAX'}</span>
              <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 11, color: `var(--${c.sev})` }}>{c.v}</span>
            </div>
            <div style={{ fontSize: 13, fontWeight: 500, marginTop: 8 }}>{c.t}</div>
            <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6, letterSpacing: '.04em' }}>{c.d}</div>
          </div>
        ))}
      </div>
      <div className="nv-homebar"></div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// PORTFOLIO BUILDER — sliders + live projection
// ═══════════════════════════════════════════════════════════
function NVAllocSlider({ label, value, min, max, color, target }) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div style={{ padding: '12px 0', borderTop: '1px solid var(--line)' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 500 }}>{label}</span>
        <span className="nv-mono" style={{ marginLeft: 12, fontSize: 10, color: 'var(--ink-3)' }}>target {target}%</span>
        <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 16, color: `var(--${color})` }}>{value}<span style={{ fontSize: 11, color: 'var(--ink-3)' }}>%</span></span>
      </div>
      <div style={{ position: 'relative', height: 6, background: 'var(--bg-3)', borderRadius: 3 }}>
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width: `${pct}%`, background: `var(--${color})`, borderRadius: 3 }} />
        <div style={{ position: 'absolute', top: -2, left: `${pct}%`, width: 12, height: 12, marginLeft: -6, borderRadius: 6, background: `var(--${color})`, border: '2px solid var(--bg-0)' }} />
        <div style={{ position: 'absolute', top: -4, bottom: -4, left: `${((target - min) / (max - min)) * 100}%`, width: 2, background: 'var(--ink-2)', opacity: .5 }} />
      </div>
    </div>
  );
}

function NVPortfolioBuilderDesktop() {
  // donut math
  const segs = [
    { l: 'Equity', v: 62, c: 'mint' },
    { l: 'Debt', v: 22, c: 'indigo' },
    { l: 'Gold', v: 8, c: 'amber' },
    { l: 'Intl', v: 6, c: 'rose' },
    { l: 'Cash', v: 2, c: 'ink-3' },
  ];
  const C = 2 * Math.PI * 64;
  let offset = 0;

  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVSidebar active="overview" />
      <main style={{ flex: 1, padding: '24px 32px 32px', overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 18 }}>
          <div>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Workspace · portfolio builder</div>
            <h1 className="nv-serif" style={{ fontSize: 36, letterSpacing: '-0.025em', margin: '4px 0 0', lineHeight: 1.05 }}>Compose by hand. Simulate live.</h1>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button className="nv-btn" style={{ padding: '8px 13px', fontSize: 12 }}>Reset to current</button>
            <button className="nv-btn" style={{ padding: '8px 13px', fontSize: 12 }}>Save as draft</button>
            <button className="nv-btn nv-btn-primary" style={{ padding: '8px 13px', fontSize: 12 }}>Send to plan →</button>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr 320px', gap: 18 }}>
          {/* left — sliders */}
          <div className="nv-card" style={{ padding: 20 }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 8 }}>Asset mix</div>
            <NVAllocSlider label="Equity" value={62} min={0} max={100} color="mint" target={60} />
            <NVAllocSlider label="Debt" value={22} min={0} max={50} color="indigo" target={25} />
            <NVAllocSlider label="Gold" value={8} min={0} max={20} color="amber" target={8} />
            <NVAllocSlider label="International" value={6} min={0} max={20} color="rose" target={5} />
            <NVAllocSlider label="Cash" value={2} min={0} max={20} color="ink-3" target={2} />

            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginTop: 22, marginBottom: 8 }}>Investment style</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6 }}>
              {[['Value', false], ['Blend', true], ['Growth', false]].map(([t, on]) => (
                <div key={t} style={{ padding: '10px 6px', textAlign: 'center', borderRadius: 8, fontSize: 12, background: on ? 'var(--bg-2)' : 'transparent', color: on ? 'var(--ink)' : 'var(--ink-3)', border: on ? '1px solid var(--mint-line)' : '1px solid var(--line)', cursor: 'pointer' }}>{t}</div>
              ))}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, marginTop: 6 }}>
              {[['Large', true], ['Mid', false], ['Small', false]].map(([t, on]) => (
                <div key={t} style={{ padding: '10px 6px', textAlign: 'center', borderRadius: 8, fontSize: 12, background: on ? 'var(--bg-2)' : 'transparent', color: on ? 'var(--ink)' : 'var(--ink-3)', border: on ? '1px solid var(--mint-line)' : '1px solid var(--line)', cursor: 'pointer' }}>{t}</div>
              ))}
            </div>
          </div>

          {/* center — donut + projection */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div className="nv-card" style={{ padding: 22, display: 'flex', alignItems: 'center', gap: 30 }}>
              <svg width="180" height="180" viewBox="0 0 180 180">
                <circle cx="90" cy="90" r="64" fill="none" stroke="var(--bg-2)" strokeWidth="22" />
                {segs.map((s) => {
                  const dash = C * (s.v / 100);
                  const el = <circle key={s.l} cx="90" cy="90" r="64" fill="none" stroke={`var(--${s.c})`} strokeWidth="22" strokeDasharray={`${dash} ${C - dash}`} strokeDashoffset={-offset} transform="rotate(-90 90 90)" strokeLinecap="butt" />;
                  offset += dash;
                  return el;
                })}
                <text x="90" y="88" textAnchor="middle" fontFamily="var(--display)" fontSize="34" fill="var(--ink)" letterSpacing="-0.04em">86</text>
                <text x="90" y="106" textAnchor="middle" fontFamily="var(--mono)" fontSize="9" fill="var(--mint)" letterSpacing="2">SCORE →89</text>
              </svg>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {segs.map((s) => (
                  <div key={s.l} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{ width: 12, height: 12, background: `var(--${s.c})`, borderRadius: 3 }} />
                    <span style={{ fontSize: 13 }}>{s.l}</span>
                    <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--ink-2)' }}>{s.v}%</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="nv-card" style={{ padding: 20 }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 10 }}>20-year projection · vs current</div>
              <svg viewBox="0 0 600 200" style={{ width: '100%', height: 200 }}>
                <defs>
                  <linearGradient id="pb-mn" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stopColor="var(--mint)" stopOpacity=".3" />
                    <stop offset="1" stopColor="var(--mint)" stopOpacity="0" />
                  </linearGradient>
                </defs>
                {[40, 80, 120, 160].map((y) => <line key={y} x1="0" y1={y} x2="600" y2={y} stroke="var(--line)" strokeDasharray="2 4" />)}
                {/* current path */}
                <path d="M0,180 C100,160 200,130 300,90 C400,52 500,28 600,18" fill="none" stroke="var(--ink-3)" strokeWidth="1.5" strokeDasharray="4 4" />
                {/* new path */}
                <path d="M0,180 C100,154 200,118 300,72 C400,32 500,12 600,4 L600,200 L0,200 Z" fill="url(#pb-mn)" />
                <path d="M0,180 C100,154 200,118 300,72 C400,32 500,12 600,4" fill="none" stroke="var(--mint)" strokeWidth="2.5" />
                <text x="596" y="22" textAnchor="end" fontFamily="var(--mono)" fontSize="10" fill="var(--mint)">new · ₹6.1 Cr</text>
                <text x="596" y="40" textAnchor="end" fontFamily="var(--mono)" fontSize="10" fill="var(--ink-3)">current · ₹5.4 Cr</text>
                {[2026, 2030, 2036, 2042, 2046].map((y, i) => (
                  <text key={y} x={i * 150} y="196" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">{y}</text>
                ))}
              </svg>
            </div>
          </div>

          {/* right — impact rail */}
          <aside className="nv-card-2" style={{ padding: 18 }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--mint)', textTransform: 'uppercase' }}>● Live impact</div>
            <div className="nv-serif" style={{ fontSize: 24, letterSpacing: '-0.02em', marginTop: 6 }}>+3 health pts</div>
            <div className="nv-mono nv-num" style={{ fontSize: 11, color: 'var(--ink-3)' }}>86 → 89 · grade A→A+</div>

            <div style={{ marginTop: 14 }}>
              {[
                { l: 'Expected return', cur: '11.2%', nxt: '12.4%', dir: 'up' },
                { l: 'Volatility (σ)', cur: '14.6%', nxt: '13.2%', dir: 'down' },
                { l: 'Sharpe', cur: '1.34', nxt: '1.49', dir: 'up' },
                { l: 'Max drawdown', cur: '-18%', nxt: '-15%', dir: 'down' },
                { l: 'Annual cost', cur: '₹14.2k', nxt: '₹8.8k', dir: 'down' },
              ].map((r) => (
                <div key={r.l} style={{ display: 'grid', gridTemplateColumns: '1fr 60px 12px 60px', alignItems: 'center', gap: 6, padding: '8px 0', borderTop: '1px solid var(--line)' }}>
                  <span style={{ fontSize: 12 }}>{r.l}</span>
                  <span className="nv-mono nv-num" style={{ fontSize: 11, color: 'var(--ink-3)', textAlign: 'right' }}>{r.cur}</span>
                  <span style={{ color: 'var(--ink-3)', textAlign: 'center' }}>→</span>
                  <span className="nv-mono nv-num" style={{ fontSize: 11.5, color: 'var(--mint)', textAlign: 'right' }}>{r.nxt}</span>
                </div>
              ))}
            </div>

            <div className="nv-card" style={{ padding: 12, marginTop: 16, background: 'var(--bg-1)' }}>
              <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Trades required</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginTop: 8 }}>
                {['Buy Nifty Next 50 · ₹2.1 L', 'Sell HDFC Bank · ₹74k', 'Switch to direct funds'].map((t, i) => (
                  <div key={i} style={{ fontSize: 11.5, color: 'var(--ink-2)', display: 'flex', gap: 8 }}>
                    <span style={{ color: 'var(--mint)' }}>•</span><span>{t}</span>
                  </div>
                ))}
              </div>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}

function NVPortfolioBuilderMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>
      <div style={{ padding: '6px 18px 10px', display: 'flex', alignItems: 'center' }}>
        <span style={{ color: 'var(--ink-2)', fontSize: 18 }}>‹</span>
        <div style={{ marginLeft: 8 }}>
          <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Builder</div>
          <div className="nv-serif" style={{ fontSize: 18 }}>Compose</div>
        </div>
        <span className="nv-pill nv-pill-mint" style={{ marginLeft: 'auto', fontSize: 9 }}>86 → 89</span>
      </div>

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        {/* donut */}
        <div className="nv-card" style={{ padding: 14, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 14 }}>
          <svg width="100" height="100" viewBox="0 0 180 180">
            <circle cx="90" cy="90" r="64" fill="none" stroke="var(--bg-2)" strokeWidth="22" />
            {(() => {
              const segs = [{v:62,c:'mint'},{v:22,c:'indigo'},{v:8,c:'amber'},{v:6,c:'rose'},{v:2,c:'ink-3'}];
              const C = 2 * Math.PI * 64; let off = 0;
              return segs.map((s, i) => {
                const d = C * (s.v / 100);
                const el = <circle key={i} cx="90" cy="90" r="64" fill="none" stroke={`var(--${s.c})`} strokeWidth="22" strokeDasharray={`${d} ${C - d}`} strokeDashoffset={-off} transform="rotate(-90 90 90)" />;
                off += d; return el;
              });
            })()}
            <text x="90" y="96" textAnchor="middle" fontFamily="var(--display)" fontSize="32" fill="var(--ink)" letterSpacing="-0.04em">89</text>
          </svg>
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {[['Equity','mint',62],['Debt','indigo',22],['Gold','amber',8],['Intl','rose',6]].map(([l, c, v]) => (
              <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5 }}>
                <span style={{ width: 10, height: 10, background: `var(--${c})`, borderRadius: 2 }} />
                <span>{l}</span>
                <span className="nv-mono nv-num" style={{ marginLeft: 'auto', color: 'var(--ink-2)' }}>{v}%</span>
              </div>
            ))}
          </div>
        </div>

        <div className="nv-card-2" style={{ padding: 12, marginBottom: 10 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 4 }}>Adjust</div>
          <NVAllocSlider label="Equity" value={62} min={0} max={100} color="mint" target={60} />
          <NVAllocSlider label="Debt" value={22} min={0} max={50} color="indigo" target={25} />
          <NVAllocSlider label="Gold" value={8} min={0} max={20} color="amber" target={8} />
        </div>

        <div className="nv-card-2" style={{ padding: 12 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--mint)', textTransform: 'uppercase', marginBottom: 6 }}>Live impact</div>
          {[
            { l: 'Sharpe', n: '1.49', up: true },
            { l: 'Vol', n: '13.2%', up: false },
            { l: '₹ by 2046', n: '₹6.1 Cr', up: true },
          ].map((r) => (
            <div key={r.l} style={{ display: 'flex', padding: '5px 0', borderTop: '1px solid var(--line)' }}>
              <span style={{ fontSize: 12 }}>{r.l}</span>
              <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 12, color: r.up ? 'var(--mint)' : 'var(--indigo)' }}>{r.n}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ padding: '10px 18px 22px', borderTop: '1px solid var(--line)', display: 'flex', gap: 8 }}>
        <button className="nv-btn" style={{ padding: '11px 12px', fontSize: 12 }}>↺</button>
        <button className="nv-btn nv-btn-primary" style={{ flex: 1, justifyContent: 'center', padding: '11px', fontSize: 13 }}>Send to plan →</button>
      </div>
      <div className="nv-homebar"></div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// INSTRUMENT ALLOCATION — Sankey
// ═══════════════════════════════════════════════════════════
function NVSankey({ scale = 1 }) {
  // 3-stage sankey: vehicles → asset class → sector
  // hand-laid for clarity
  const W = 760 * scale, H = 420 * scale;
  const s = scale;
  // node positions (x, y, h, label, color, sub)
  const nodes = {
    // level 0 — vehicles
    direct: { x: 0, y: 10, h: 180, l: 'Direct stocks', sub: '42%', col: 0, c: 'mint' },
    mf:     { x: 0, y: 200, h: 140, l: 'Mutual funds', sub: '34%', col: 0, c: 'indigo' },
    etf:    { x: 0, y: 350, h: 30,  l: 'ETFs', sub: '7%',  col: 0, c: 'amber' },
    fd:     { x: 0, y: 390, h: 70,  l: 'FD / Debt', sub: '17%', col: 0, c: 'rose' },
    // level 1 — asset class
    eq:     { x: 290 * s, y: 10,  h: 330, l: 'Equity', sub: '68%', col: 1, c: 'mint' },
    debt:   { x: 290 * s, y: 350, h: 70,  l: 'Debt', sub: '18%',  col: 1, c: 'rose' },
    // level 2 — sectors / categories
    fin:    { x: 580 * s, y: 10,  h: 120, l: 'Financials', sub: '32%', col: 2, c: 'amber' },
    tech:   { x: 580 * s, y: 140, h: 80,  l: 'Technology', sub: '22%', col: 2, c: 'indigo' },
    ene:    { x: 580 * s, y: 230, h: 50,  l: 'Energy', sub: '14%', col: 2, c: 'ink-3' },
    other:  { x: 580 * s, y: 290, h: 50,  l: 'Other eq.', sub: '12%', col: 2, c: 'ink-3' },
    debtcat:{ x: 580 * s, y: 350, h: 70,  l: 'Bonds / FD', sub: '20%', col: 2, c: 'rose' },
  };
  // node widths
  const NW = 14 * s;
  // links: source → target with thickness
  const linkPaths = [
    // direct → eq
    { s: 'direct', t: 'eq', h: 160, soy: 0, toy: 0, c: 'mint' },
    // direct → fin (more direct)
    { s: 'direct', t: 'fin', h: 80, soy: 0, toy: 0, c: 'amber' },
    { s: 'mf', t: 'eq', h: 100, soy: 0, toy: 160, c: 'indigo' },
    { s: 'etf', t: 'eq', h: 24, soy: 0, toy: 0, c: 'amber' },
    { s: 'fd', t: 'debt', h: 60, soy: 0, toy: 0, c: 'rose' },
    { s: 'eq', t: 'fin', h: 90, soy: 0, toy: 0, c: 'amber' },
    { s: 'eq', t: 'tech', h: 80, soy: 0, toy: 0, c: 'indigo' },
    { s: 'eq', t: 'ene', h: 50, soy: 0, toy: 0, c: 'ink-3' },
    { s: 'eq', t: 'other', h: 50, soy: 0, toy: 0, c: 'ink-3' },
    { s: 'debt', t: 'debtcat', h: 60, soy: 0, toy: 0, c: 'rose' },
  ];

  const path = (sx, sy, sh, tx, ty, th) => {
    const mid = (sx + tx) / 2;
    return `M${sx},${sy} C${mid},${sy} ${mid},${ty} ${tx},${ty} L${tx},${ty + th} C${mid},${ty + th} ${mid},${sy + sh} ${sx},${sy + sh} Z`;
  };

  // accumulate per-source per-target offsets
  const srcOff = {};
  const tgtOff = {};

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} style={{ display: 'block' }}>
      {/* links first (under nodes) */}
      {linkPaths.map((l, i) => {
        const ns = nodes[l.s], nt = nodes[l.t];
        const sx = ns.x + NW;
        const tx = nt.x;
        const sy = ns.y + (srcOff[l.s] || 0);
        const ty = nt.y + (tgtOff[l.t] || 0);
        srcOff[l.s] = (srcOff[l.s] || 0) + l.h;
        tgtOff[l.t] = (tgtOff[l.t] || 0) + l.h;
        return (
          <path key={i}
            d={path(sx, sy, l.h, tx, ty, l.h)}
            fill={`var(--${l.c})`}
            fillOpacity={l.c === 'amber' ? 0.32 : 0.16}
            stroke="none"
          />
        );
      })}
      {/* nodes */}
      {Object.entries(nodes).map(([k, n]) => (
        <g key={k}>
          <rect x={n.x} y={n.y} width={NW} height={n.h} fill={`var(--${n.c})`} rx="2" />
          <text x={n.col === 2 ? n.x + NW + 8 : n.x - 8} y={n.y + 14} textAnchor={n.col === 2 ? 'start' : 'end'} fontFamily="var(--sans)" fontSize={12 * s} fontWeight="500" fill="var(--ink)">{n.l}</text>
          <text x={n.col === 2 ? n.x + NW + 8 : n.x - 8} y={n.y + 28} textAnchor={n.col === 2 ? 'start' : 'end'} fontFamily="var(--mono)" fontSize={10 * s} fill="var(--ink-3)">{n.sub}</text>
        </g>
      ))}

      {/* column labels */}
      <text x={0} y={H - 4} fontFamily="var(--mono)" fontSize={9 * s} fill="var(--ink-4)" letterSpacing="1">VEHICLE</text>
      <text x={290 * s} y={H - 4} fontFamily="var(--mono)" fontSize={9 * s} fill="var(--ink-4)" letterSpacing="1">ASSET CLASS</text>
      <text x={580 * s + 80} y={H - 4} fontFamily="var(--mono)" fontSize={9 * s} fill="var(--ink-4)" letterSpacing="1">EXPOSURE</text>
    </svg>
  );
}

function NVInstrumentAllocationDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVSidebar active="overview" />
      <main style={{ flex: 1, padding: '24px 32px 32px', overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 18 }}>
          <div>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Workspace · instrument flow</div>
            <h1 className="nv-serif" style={{ fontSize: 36, letterSpacing: '-0.025em', margin: '4px 0 0', lineHeight: 1.05 }}>From vehicles to exposure.</h1>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button className="nv-btn" style={{ padding: '8px 13px', fontSize: 12 }}>↓ Export CSV</button>
            <button className="nv-btn nv-btn-primary" style={{ padding: '8px 13px', fontSize: 12 }}>Group by sector ▾</button>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 18 }}>
          <div className="nv-card" style={{ padding: 22 }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Instrument → asset class → exposure</div>
              <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--ink-3)' }}>47 holdings · ₹24.8 L</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <NVSankey scale={1} />
            </div>
          </div>

          <aside className="nv-card-2" style={{ padding: 18 }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--mint)', textTransform: 'uppercase' }}>● Selected flow</div>
            <div className="nv-serif" style={{ fontSize: 22, letterSpacing: '-0.02em', marginTop: 6 }}>Direct → Financials</div>
            <div className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>14 stocks · ₹8.0 L (32%)</div>

            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[
                { n: 'HDFC Bank', v: '₹1.98L', p: '8.0%' },
                { n: 'ICICI Bank', v: '₹1.61L', p: '6.5%' },
                { n: 'Axis Bank', v: '₹1.36L', p: '5.5%' },
                { n: 'Bajaj Finance', v: '₹1.12L', p: '4.5%' },
                { n: 'SBI', v: '₹0.99L', p: '4.0%' },
                { n: 'HDFC Life', v: '₹0.87L', p: '3.5%' },
              ].map((r) => (
                <div key={r.n} style={{ display: 'grid', gridTemplateColumns: '1fr 60px 36px', alignItems: 'center', gap: 8, padding: '8px 0', borderTop: '1px solid var(--line)' }}>
                  <span style={{ fontSize: 12.5 }}>{r.n}</span>
                  <span className="nv-mono nv-num" style={{ fontSize: 11.5, color: 'var(--ink-2)', textAlign: 'right' }}>{r.v}</span>
                  <span className="nv-mono nv-num" style={{ fontSize: 11, color: 'var(--amber)', textAlign: 'right' }}>{r.p}</span>
                </div>
              ))}
            </div>

            <button className="nv-btn nv-btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '10px', marginTop: 16, fontSize: 12 }}>Plan exposure cut →</button>
          </aside>
        </div>
      </main>
    </div>
  );
}

function NVInstrumentAllocationMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>
      <div style={{ padding: '6px 18px 10px', display: 'flex', alignItems: 'center' }}>
        <span style={{ color: 'var(--ink-2)', fontSize: 18 }}>‹</span>
        <div style={{ marginLeft: 8 }}>
          <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Flow</div>
          <div className="nv-serif" style={{ fontSize: 18 }}>Instrument map</div>
        </div>
        <span className="nv-pill nv-pill-indigo" style={{ marginLeft: 'auto', fontSize: 9 }}>47 HOLD</span>
      </div>

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        <div className="nv-card" style={{ padding: 10, marginBottom: 12 }}>
          <div style={{ overflow: 'auto' }}>
            <NVSankey scale={0.46} />
          </div>
        </div>

        <div className="nv-card-2" style={{ padding: 13 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--mint)', textTransform: 'uppercase', marginBottom: 6 }}>Top exposures</div>
          {[
            { n: 'Financials', v: '32%' },
            { n: 'Technology', v: '22%' },
            { n: 'Energy', v: '14%' },
            { n: 'Bonds / FD', v: '20%' },
          ].map((r) => (
            <div key={r.n} style={{ display: 'flex', padding: '7px 0', borderTop: '1px solid var(--line)' }}>
              <span style={{ fontSize: 12 }}>{r.n}</span>
              <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--ink-2)' }}>{r.v}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="nv-homebar"></div>
    </div>
  );
}

Object.assign(window, {
  NVPlanBoardDesktop, NVPlanBoardMobile,
  NVPortfolioBuilderDesktop, NVPortfolioBuilderMobile,
  NVInstrumentAllocationDesktop, NVInstrumentAllocationMobile,
});
