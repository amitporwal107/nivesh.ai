// ─── Nivesh MVP · simplified, white-bg, single-accent ───
// 5 screens × desktop + mobile  ·  Upload · Dashboard · Breakdown · Recs · Chat

// ════════════════════════════════════════════════════════════
// Shared chrome
// ════════════════════════════════════════════════════════════
function NVMSidebar({ active = 'dashboard' }) {
  const items = [
    ['Dashboard',      'dashboard'],
    ['Breakdown',      'breakdown'],
    ['Recommendations','recs'],
    ['Chat',           'chat'],
  ];
  return (
    <aside style={{ width: 232, borderRight: '1px solid var(--m-line)', padding: '28px 18px', display: 'flex', flexDirection: 'column', background: 'var(--m-bg)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '4px 8px 28px' }}>
        <span className="m-mark">न</span>
        <span className="m-serif" style={{ fontSize: 19 }}>Nivesh</span>
      </div>
      {items.map(([t, k]) => {
        const on = k === active;
        return (
          <div key={k} style={{
            padding: '11px 14px', fontSize: 14.5, borderRadius: 10,
            color: on ? 'var(--m-ink)' : 'var(--m-ink-2)',
            background: on ? 'var(--m-bg-1)' : 'transparent',
            border: on ? '1px solid var(--m-line)' : '1px solid transparent',
            fontWeight: on ? 500 : 400, cursor: 'pointer', marginBottom: 4,
          }}>{t}</div>
        );
      })}
      <div style={{ marginTop: 'auto', padding: '14px 10px 4px', borderTop: '1px solid var(--m-line)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ width: 30, height: 30, borderRadius: 9, background: 'var(--m-bg-2)', display: 'grid', placeItems: 'center', fontFamily: 'var(--m-display)', fontSize: 15, color: 'var(--m-ink-2)' }}>A</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 500 }}>Aarav Kumar</div>
          <div className="m-mono" style={{ fontSize: 10, color: 'var(--m-ink-3)' }}>Settings</div>
        </div>
      </div>
    </aside>
  );
}

function NVMBottomTabs({ active = 'dashboard' }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-around', padding: '12px 14px 24px', borderTop: '1px solid var(--m-line)', background: 'var(--m-bg)' }}>
      {[['◐', 'Home', 'dashboard'], ['▢', 'Breakdown', 'breakdown'], ['✓', 'Tips', 'recs'], ['◔', 'Chat', 'chat']].map(([i, l, k]) => {
        const on = k === active;
        return (
          <div key={k} style={{ textAlign: 'center', color: on ? 'var(--m-accent)' : 'var(--m-ink-3)' }}>
            <div style={{ fontSize: 17, fontFamily: 'var(--m-mono)' }}>{i}</div>
            <div style={{ fontSize: 11, marginTop: 2, fontWeight: on ? 500 : 400 }}>{l}</div>
          </div>
        );
      })}
    </div>
  );
}

// ════════════════════════════════════════════════════════════
// 01 · UPLOAD
// ════════════════════════════════════════════════════════════
function NVMUploadDesktop() {
  return (
    <div className="m-frame" style={{ width: '100%', minHeight: 900, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '22px 56px', borderBottom: '1px solid var(--m-line)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="m-mark">न</span>
          <span className="m-serif" style={{ fontSize: 21 }}>Nivesh</span>
        </div>
        <span className="m-mono" style={{ marginLeft: 'auto', fontSize: 10, letterSpacing: '.18em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>STEP 1 OF 1 · UPLOAD</span>
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '72px 56px 48px', maxWidth: 880, margin: '0 auto', width: '100%' }}>
        <span className="m-pill m-pill-accent"><span className="m-dot" style={{ background: 'var(--m-accent)' }} />SECURE · READ-ONLY · NEVER STORED</span>
        <h1 className="m-serif" style={{ fontSize: 52, letterSpacing: '-0.03em', textAlign: 'center', lineHeight: 1.02, marginTop: 22 }}>
          Bring your portfolio in.<br/>
          We'll do the rest.
        </h1>
        <p style={{ fontSize: 17, color: 'var(--m-ink-2)', textAlign: 'center', maxWidth: 540, lineHeight: 1.55, marginTop: 16 }}>
          Upload one of three things. We parse it, check eight aspects of health, and surface what to do next.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, width: '100%', marginTop: 36 }}>
          {[
            { t: 'CAS PDF', s: 'NSDL / CDSL · the most complete picture', tag: 'RECOMMENDED', tagC: 'accent', big: true },
            { t: 'Broker statement', s: 'Zerodha · Groww · Upstox · ICICI Direct · any', tag: 'PDF', tagC: 'default' },
            { t: 'Excel / CSV', s: 'For SIPs or manual ledgers you maintain', tag: 'XLSX · CSV', tagC: 'default' },
          ].map((m) => (
            <div key={m.t} className="m-card" style={{ padding: 28, position: 'relative', border: m.big ? '1px solid var(--m-accent-line)' : '1px solid var(--m-line)', background: m.big ? 'var(--m-accent-soft)' : 'var(--m-bg-1)' }}>
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <span className="m-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: m.big ? 'var(--m-accent)' : 'var(--m-ink-3)', textTransform: 'uppercase' }}>{m.tag}</span>
              </div>
              <div className="m-serif" style={{ fontSize: 24, letterSpacing: '-0.02em', marginTop: 14 }}>{m.t}</div>
              <div style={{ fontSize: 13.5, color: 'var(--m-ink-2)', lineHeight: 1.5, marginTop: 6 }}>{m.s}</div>
              {/* drop zone */}
              <div style={{
                marginTop: 20, padding: '24px 14px', textAlign: 'center',
                borderRadius: 12,
                border: '1.5px dashed var(--m-line-2)',
                background: 'var(--m-bg-1)',
              }}>
                <div style={{ fontSize: 22, color: 'var(--m-ink-3)' }}>↧</div>
                <div className="m-mono" style={{ fontSize: 10.5, color: 'var(--m-ink-3)', letterSpacing: '.04em', marginTop: 6 }}>Drag, or browse</div>
              </div>
              <button className={m.big ? 'm-btn m-btn-accent' : 'm-btn'} style={{ width: '100%', justifyContent: 'center', marginTop: 14, padding: '11px', fontSize: 13.5 }}>Choose file →</button>
            </div>
          ))}
        </div>

        <div className="m-mono" style={{ fontSize: 10, letterSpacing: '.06em', color: 'var(--m-ink-3)', marginTop: 30 }}>
          India-hosted · AES-256 at rest · PDFs deleted after parsing · We never store passwords
        </div>
      </div>
    </div>
  );
}

function NVMUploadMobile() {
  return (
    <div className="m-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="m-notch"></span>
      <div className="m-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '12px 22px 0', display: 'flex', alignItems: 'center', gap: 12 }}>
        <span className="m-mark" style={{ width: 28, height: 28, fontSize: 17 }}>न</span>
        <span className="m-serif" style={{ fontSize: 18 }}>Nivesh</span>
      </div>

      <div style={{ padding: '38px 22px 22px', flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <span className="m-pill m-pill-accent" style={{ alignSelf: 'flex-start' }}><span className="m-dot" style={{ background: 'var(--m-accent)' }} />SECURE · READ-ONLY</span>
        <h1 className="m-serif" style={{ fontSize: 34, letterSpacing: '-0.03em', lineHeight: 1.02, marginTop: 16 }}>
          Bring your portfolio in.
        </h1>
        <p style={{ fontSize: 14, color: 'var(--m-ink-2)', lineHeight: 1.5, marginTop: 10 }}>
          Pick the easiest. We parse, score, and recommend.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 22 }}>
          {[
            { t: 'CAS PDF', s: 'NSDL / CDSL · most complete', tag: 'RECOMMENDED', big: true },
            { t: 'Broker statement', s: 'Zerodha · Groww · others', tag: 'PDF' },
            { t: 'Excel / CSV', s: 'For manual ledgers', tag: 'XLSX' },
          ].map((m) => (
            <div key={m.t} className="m-card" style={{ padding: 16, background: m.big ? 'var(--m-accent-soft)' : 'var(--m-bg-1)', border: m.big ? '1px solid var(--m-accent-line)' : '1px solid var(--m-line)' }}>
              <div className="m-mono" style={{ fontSize: 9.5, letterSpacing: '.14em', color: m.big ? 'var(--m-accent)' : 'var(--m-ink-3)' }}>{m.tag}</div>
              <div className="m-serif" style={{ fontSize: 19, letterSpacing: '-0.02em', marginTop: 4 }}>{m.t}</div>
              <div style={{ fontSize: 12.5, color: 'var(--m-ink-2)', marginTop: 4 }}>{m.s}</div>
              <button className={m.big ? 'm-btn m-btn-accent' : 'm-btn'} style={{ width: '100%', justifyContent: 'center', marginTop: 10, padding: '10px', fontSize: 13 }}>Choose file →</button>
            </div>
          ))}
        </div>

        <div className="m-mono" style={{ fontSize: 9.5, color: 'var(--m-ink-3)', textAlign: 'center', marginTop: 'auto', paddingTop: 22, lineHeight: 1.6 }}>
          INDIA-HOSTED · AES-256 · PDFs DELETED
        </div>
      </div>
      <div className="m-homebar"></div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════
// 02 · DASHBOARD
// ════════════════════════════════════════════════════════════
function NVMScoreRing({ size = 160, score = 74 }) {
  const r = (size - 18) / 2;
  const c = 2 * Math.PI * r;
  const dash = c * (score / 100);
  const cx = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={cx} cy={cx} r={r} fill="none" stroke="var(--m-bg-2)" strokeWidth="10" />
      <circle cx={cx} cy={cx} r={r} fill="none" stroke="var(--m-accent)" strokeWidth="10"
        strokeDasharray={`${dash} ${c - dash}`} strokeLinecap="round" transform={`rotate(-90 ${cx} ${cx})`} />
      <text x={cx} y={cx - 4} textAnchor="middle" dominantBaseline="middle" fill="var(--m-ink)" fontFamily="var(--m-display)" fontSize={size * 0.34} letterSpacing="-0.04em">{score}</text>
      <text x={cx} y={cx + size * 0.18} textAnchor="middle" fill="var(--m-ink-3)" fontFamily="var(--m-mono)" fontSize="10" letterSpacing="2">/ 100</text>
    </svg>
  );
}

function NVMDashboardDesktop() {
  return (
    <div className="m-frame" style={{ width: '100%', minHeight: 900, display: 'flex' }}>
      <NVMSidebar active="dashboard" />
      <main style={{ flex: 1, padding: '40px 56px 40px', maxWidth: 1080, margin: '0 auto' }}>
        <div className="m-mono" style={{ fontSize: 11, letterSpacing: '.18em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Dashboard</div>
        <h1 className="m-serif" style={{ fontSize: 38, letterSpacing: '-0.025em', margin: '6px 0 0', lineHeight: 1.05 }}>
          Your portfolio is <span style={{ color: 'var(--m-accent)' }}>mostly healthy</span>.
        </h1>
        <p style={{ fontSize: 16, color: 'var(--m-ink-2)', marginTop: 12, lineHeight: 1.55, maxWidth: 600 }}>
          The biggest issue: <strong style={{ fontWeight: 500 }}>42% of your equity sits in overlapping flexi-cap funds.</strong> Three of them hold nearly the same stocks.
        </p>

        {/* hero: value + score + risk */}
        <div className="m-card" style={{ marginTop: 28, padding: 32, display: 'grid', gridTemplateColumns: '1.2fr 1px 1fr 1px 1fr', gap: 32, alignItems: 'center' }}>
          <div>
            <div className="m-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Portfolio value</div>
            <div className="m-serif m-num" style={{ fontSize: 52, letterSpacing: '-0.035em', marginTop: 8, lineHeight: 1 }}>₹24,82,400</div>
            <div className="m-mono" style={{ fontSize: 12, color: 'var(--m-pos)', marginTop: 6 }}>+18.7% over the last year</div>
          </div>
          <div style={{ width: 1, height: 100, background: 'var(--m-line)' }} />

          <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
            <NVMScoreRing />
            <div>
              <div className="m-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Health score</div>
              <div style={{ fontSize: 15, marginTop: 4, color: 'var(--m-ink-2)', maxWidth: 180, lineHeight: 1.4 }}>
                Good — with one important fix.
              </div>
            </div>
          </div>

          <div style={{ width: 1, height: 100, background: 'var(--m-line)' }} />

          <div>
            <div className="m-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Risk level</div>
            <div className="m-serif" style={{ fontSize: 26, letterSpacing: '-0.025em', marginTop: 8 }}>Moderate</div>
            {/* simple risk meter */}
            <div style={{ display: 'flex', gap: 4, marginTop: 12 }}>
              {[1,2,3,4,5].map((i) => (
                <div key={i} style={{ flex: 1, height: 8, borderRadius: 4, background: i <= 3 ? 'var(--m-accent)' : 'var(--m-bg-2)' }} />
              ))}
            </div>
            <div className="m-mono" style={{ fontSize: 10, color: 'var(--m-ink-3)', marginTop: 8, letterSpacing: '.04em' }}>3 OF 5 · ALIGNED WITH YOUR PROFILE</div>
          </div>
        </div>

        {/* top 3 insights */}
        <div style={{ display: 'flex', alignItems: 'center', margin: '32px 0 14px' }}>
          <div className="m-mono" style={{ fontSize: 11, letterSpacing: '.18em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Top 3 insights</div>
          <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--m-ink-3)' }}>plain English · from analyzing 47 holdings</span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            { n: '1', t: 'You own 5 funds with similar holdings.', s: 'Axis Bluechip, ICICI Pru Bluechip and Mirae Large hold 71% of the same top stocks — you\u2019re paying 3× the fees for 1× exposure.', tag: 'OVERLAP', tagC: 'reduce' },
            { n: '2', t: 'Your portfolio is tilted toward mid-caps.', s: 'About 38% sits in mid- and small-cap names. Fine in good years, painful in bad ones.', tag: 'CONCENTRATION', tagC: 'add' },
            { n: '3', t: 'Your emergency fund looks low.', s: 'You hold 1.4 months of expenses in safe cash. The usual target is 6 months — about ₹4.6L more.', tag: 'BALANCE', tagC: 'add' },
          ].map((i) => (
            <div key={i.n} className="m-card" style={{ padding: '20px 24px', display: 'flex', gap: 18, alignItems: 'flex-start' }}>
              <div className="m-serif" style={{ fontSize: 26, color: 'var(--m-ink-4)', letterSpacing: '-0.04em', minWidth: 36 }}>{i.n}</div>
              <div style={{ flex: 1 }}>
                <div className="m-serif" style={{ fontSize: 22, letterSpacing: '-0.02em', lineHeight: 1.25 }}>{i.t}</div>
                <div style={{ fontSize: 14.5, color: 'var(--m-ink-2)', marginTop: 8, lineHeight: 1.55 }}>{i.s}</div>
              </div>
              <span className={`m-pill m-pill-${i.tagC}`}>{i.tag}</span>
            </div>
          ))}
        </div>

        {/* CTA */}
        <div style={{ marginTop: 28, padding: 28, borderRadius: 18, background: 'var(--m-ink)', color: 'var(--m-bg-1)', display: 'flex', alignItems: 'center', gap: 24 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.6)', letterSpacing: '.04em' }}>The one thing</div>
            <div className="m-serif" style={{ fontSize: 28, letterSpacing: '-0.025em', marginTop: 4, lineHeight: 1.2 }}>Take your score from 74 → 88 in 3 moves.</div>
          </div>
          <button className="m-btn m-btn-accent" style={{ padding: '14px 22px', fontSize: 14.5 }}>Improve portfolio →</button>
        </div>
      </main>
    </div>
  );
}

function NVMDashboardMobile() {
  return (
    <div className="m-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="m-notch"></span>
      <div className="m-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '10px 22px 14px' }}>
        <div className="m-mono" style={{ fontSize: 10, color: 'var(--m-ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Dashboard</div>
        <div className="m-serif" style={{ fontSize: 24, letterSpacing: '-0.025em', marginTop: 4, lineHeight: 1.1 }}>
          Mostly <span style={{ color: 'var(--m-accent)' }}>healthy</span>.
        </div>
      </div>

      <div style={{ padding: '0 22px 14px', flex: 1, overflow: 'hidden' }}>
        {/* value */}
        <div className="m-card" style={{ padding: 18, marginBottom: 10 }}>
          <div className="m-mono" style={{ fontSize: 10, color: 'var(--m-ink-3)', letterSpacing: '.14em' }}>VALUE</div>
          <div className="m-serif m-num" style={{ fontSize: 32, letterSpacing: '-0.035em', marginTop: 4, lineHeight: 1 }}>₹24,82,400</div>
          <div className="m-mono" style={{ fontSize: 10.5, color: 'var(--m-pos)', marginTop: 6 }}>+18.7% over 1 year</div>
        </div>

        {/* score + risk */}
        <div className="m-card" style={{ padding: 16, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 16 }}>
          <NVMScoreRing size={90} />
          <div style={{ flex: 1 }}>
            <div className="m-mono" style={{ fontSize: 9.5, color: 'var(--m-ink-3)', letterSpacing: '.12em' }}>HEALTH</div>
            <div className="m-serif" style={{ fontSize: 18, marginTop: 2 }}>Good · one fix</div>
            <div className="m-mono" style={{ fontSize: 9.5, color: 'var(--m-ink-3)', letterSpacing: '.12em', marginTop: 10 }}>RISK</div>
            <div style={{ display: 'flex', gap: 3, marginTop: 4 }}>
              {[1,2,3,4,5].map((i) => <div key={i} style={{ flex: 1, height: 5, borderRadius: 3, background: i <= 3 ? 'var(--m-accent)' : 'var(--m-bg-2)' }} />)}
            </div>
            <div className="m-mono" style={{ fontSize: 9, color: 'var(--m-ink-3)', marginTop: 4 }}>MODERATE</div>
          </div>
        </div>

        {/* insights */}
        <div className="m-mono" style={{ fontSize: 9.5, color: 'var(--m-ink-3)', letterSpacing: '.14em', textTransform: 'uppercase', marginBottom: 8 }}>Top 3 insights</div>
        {[
          { n: '1', t: 'You own 5 similar funds.', tag: 'OVERLAP', tagC: 'reduce' },
          { n: '2', t: 'Tilted toward mid-caps.', tag: 'CONC', tagC: 'add' },
          { n: '3', t: 'Emergency fund is low.', tag: 'BALANCE', tagC: 'add' },
        ].map((i) => (
          <div key={i.n} className="m-card" style={{ padding: 14, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="m-serif" style={{ fontSize: 20, color: 'var(--m-ink-4)' }}>{i.n}</span>
            <span style={{ flex: 1, fontSize: 13.5 }}>{i.t}</span>
            <span className={`m-pill m-pill-${i.tagC}`} style={{ fontSize: 9 }}>{i.tag}</span>
          </div>
        ))}

        {/* CTA */}
        <div style={{ marginTop: 4, padding: 16, borderRadius: 14, background: 'var(--m-ink)', color: 'var(--m-bg-1)' }}>
          <div className="m-serif" style={{ fontSize: 17, letterSpacing: '-0.02em', lineHeight: 1.2 }}>
            74 → 88 in 3 moves.
          </div>
          <button className="m-btn m-btn-accent" style={{ width: '100%', justifyContent: 'center', marginTop: 10, padding: '11px', fontSize: 13 }}>Improve portfolio →</button>
        </div>
      </div>

      <NVMBottomTabs active="dashboard" />
      <div className="m-homebar"></div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════
// 03 · PORTFOLIO BREAKDOWN (tabs)
// ════════════════════════════════════════════════════════════
function NVMTreemapSimple({ scale = 1 }) {
  // tiles: financials big, then tech, energy, others
  const W = 600 * scale, H = 320 * scale;
  const tiles = [
    { x: 0, y: 0, w: 290, h: 220, l: 'Financials', v: 32, c: 'var(--m-accent)', warn: true },
    { x: 290, y: 0, w: 200, h: 220, l: 'Technology', v: 22, c: '#5B7DA6' },
    { x: 490, y: 0, w: 110, h: 220, l: 'Energy', v: 14, c: '#7A8298' },
    { x: 0, y: 220, w: 200, h: 100, l: 'Consumer', v: 11, c: '#A6A38E' },
    { x: 200, y: 220, w: 160, h: 100, l: 'Pharma', v: 9, c: '#94A892' },
    { x: 360, y: 220, w: 130, h: 100, l: 'Auto', v: 7, c: '#B5BBC6' },
    { x: 490, y: 220, w: 110, h: 100, l: 'Other', v: 5, c: '#CFCFC2' },
  ];
  const s = scale;
  return (
    <svg viewBox={`0 0 ${600} ${320}`} width={W} height={H} style={{ display: 'block' }}>
      {tiles.map((t) => (
        <g key={t.l}>
          <rect x={t.x} y={t.y} width={t.w} height={t.h} fill={t.c} fillOpacity={t.warn ? .9 : .6} stroke="var(--m-bg)" strokeWidth="3" />
          <text x={t.x + 14} y={t.y + 24} fontFamily="var(--m-sans)" fontSize="13" fontWeight="500" fill={t.warn ? '#FFFFFF' : 'var(--m-ink)'}>{t.l}</text>
          <text x={t.x + 14} y={t.y + 42} fontFamily="var(--m-display)" fontSize="22" fill={t.warn ? '#FFFFFF' : 'var(--m-ink)'} letterSpacing="-0.02em">{t.v}%</text>
          {t.warn && <text x={t.x + 14} y={t.y + t.h - 12} fontFamily="var(--m-mono)" fontSize="9" letterSpacing=".1em" fill="#FFFFFF" opacity=".9">CAP EXCEEDED</text>}
        </g>
      ))}
    </svg>
  );
}

function NVMDonutSimple({ size = 220, segs }) {
  const cx = size / 2, r = (size - 28) / 2;
  const C = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={cx} cy={cx} r={r} fill="none" stroke="var(--m-bg-2)" strokeWidth="22" />
      {segs.map((s, i) => {
        const dash = C * (s.v / 100);
        const el = (
          <circle key={i} cx={cx} cy={cx} r={r} fill="none"
            stroke={s.c} strokeWidth="22"
            strokeDasharray={`${dash} ${C - dash}`}
            strokeDashoffset={-offset}
            transform={`rotate(-90 ${cx} ${cx})`} />
        );
        offset += dash;
        return el;
      })}
    </svg>
  );
}

function NVMBreakdownDesktop() {
  const [tab, setTab] = React.useState('allocation');
  const segs = [
    { l: 'Equity', v: 68, c: 'var(--m-accent)' },
    { l: 'Debt',   v: 18, c: '#A6A38E' },
    { l: 'Gold',   v: 6,  c: '#B5841F' },
    { l: 'Intl',   v: 6,  c: '#7A8298' },
    { l: 'Cash',   v: 2,  c: '#CFCFC2' },
  ];
  return (
    <div className="m-frame" style={{ width: '100%', minHeight: 900, display: 'flex' }}>
      <NVMSidebar active="breakdown" />
      <main style={{ flex: 1, padding: '40px 56px 40px', maxWidth: 1080, margin: '0 auto' }}>
        <div className="m-mono" style={{ fontSize: 11, letterSpacing: '.18em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Breakdown</div>
        <h1 className="m-serif" style={{ fontSize: 38, letterSpacing: '-0.025em', margin: '6px 0 0', lineHeight: 1.05 }}>Where your money lives.</h1>

        {/* tabs */}
        <div style={{ display: 'flex', gap: 4, marginTop: 28, borderBottom: '1px solid var(--m-line)' }}>
          {[
            ['allocation', 'Allocation'],
            ['exposure',   'Exposure'],
            ['overlap',    'Fund overlap'],
            ['risk',       'Risk analysis'],
          ].map(([k, l]) => {
            const on = k === tab;
            return (
              <button key={k} onClick={() => setTab(k)} style={{
                padding: '14px 18px', fontSize: 14, border: 'none',
                background: 'transparent',
                color: on ? 'var(--m-ink)' : 'var(--m-ink-3)',
                fontWeight: on ? 500 : 400,
                borderBottom: on ? '2px solid var(--m-accent)' : '2px solid transparent',
                marginBottom: -1, cursor: 'pointer',
              }}>{l}</button>
            );
          })}
        </div>

        {/* tab content */}
        <div style={{ marginTop: 24 }}>
          {tab === 'allocation' && (
            <div className="m-card" style={{ padding: 32, display: 'grid', gridTemplateColumns: '260px 1fr', gap: 36, alignItems: 'center' }}>
              <NVMDonutSimple size={240} segs={segs} />
              <div>
                <div className="m-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Split across types</div>
                <div className="m-serif" style={{ fontSize: 24, letterSpacing: '-0.02em', marginTop: 8, maxWidth: 380, lineHeight: 1.3 }}>
                  68% in stocks · 18% in safer debt. Slightly equity-heavy.
                </div>
                <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {segs.map((s) => (
                    <div key={s.l} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <span style={{ width: 14, height: 14, borderRadius: 4, background: s.c }} />
                      <span style={{ fontSize: 14 }}>{s.l}</span>
                      <span className="m-num" style={{ marginLeft: 'auto', fontSize: 15, fontWeight: 500 }}>{s.v}%</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {tab === 'exposure' && (
            <div className="m-card" style={{ padding: 28 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
                <div className="m-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Sector exposure</div>
                <span className="m-pill m-pill-reduce" style={{ marginLeft: 'auto' }}>1 sector over cap</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'center', overflow: 'hidden' }}>
                <NVMTreemapSimple scale={1.1} />
              </div>
              <div style={{ display: 'flex', gap: 16, marginTop: 14, fontSize: 11.5, color: 'var(--m-ink-3)' }}>
                <span><span style={{ width: 10, height: 10, background: 'var(--m-accent)', display: 'inline-block', marginRight: 6, verticalAlign: 'middle', borderRadius: 2 }} />Over cap</span>
                <span><span style={{ width: 10, height: 10, background: '#7A8298', display: 'inline-block', marginRight: 6, verticalAlign: 'middle', borderRadius: 2 }} />Within</span>
                <span style={{ marginLeft: 'auto' }}>Cap · 25% per sector</span>
              </div>
            </div>
          )}

          {tab === 'overlap' && (
            <div className="m-card" style={{ padding: 28 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 18 }}>
                <div className="m-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Fund overlap · how much of the top stocks two funds share</div>
                <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--m-ink-3)' }}>5 pairs flagged</span>
              </div>
              {[
                { a: 'Axis Bluechip', b: 'ICICI Pru Bluechip', o: 71 },
                { a: 'Mirae Large', b: 'ICICI Pru Bluechip', o: 68 },
                { a: 'Axis Bluechip', b: 'Mirae Large', o: 64 },
                { a: 'Parag Parikh Flexi', b: 'Mirae Large', o: 41 },
                { a: 'Quant Small Cap', b: 'Nippon Small', o: 28 },
              ].map((r) => (
                <div key={r.a + r.b} style={{ display: 'grid', gridTemplateColumns: '1.4fr 1.4fr 1fr 80px 50px', alignItems: 'center', gap: 14, padding: '14px 0', borderTop: '1px solid var(--m-line)' }}>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{r.a}</div>
                  <div style={{ fontSize: 14, color: 'var(--m-ink-2)' }}>↔ {r.b}</div>
                  <div style={{ height: 8, background: 'var(--m-bg-2)', borderRadius: 4 }}>
                    <div style={{ width: `${r.o}%`, height: '100%', background: r.o > 60 ? 'var(--m-neg)' : r.o > 40 ? 'var(--m-warm)' : 'var(--m-pos)', borderRadius: 4 }} />
                  </div>
                  <div className="m-num" style={{ fontSize: 14, color: r.o > 60 ? 'var(--m-neg)' : 'var(--m-ink-2)', textAlign: 'right' }}>{r.o}%</div>
                  <span style={{ color: 'var(--m-ink-3)', textAlign: 'right' }}>›</span>
                </div>
              ))}
            </div>
          )}

          {tab === 'risk' && (
            <div className="m-card" style={{ padding: 32 }}>
              <div className="m-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Risk meter</div>
              <div className="m-serif" style={{ fontSize: 26, letterSpacing: '-0.025em', marginTop: 8 }}>Moderate · 3 of 5</div>

              <div style={{ display: 'flex', gap: 6, marginTop: 18 }}>
                {[
                  ['Very low', false], ['Low', false], ['Moderate', true], ['High', false], ['Very high', false],
                ].map(([l, on], i) => (
                  <div key={i} style={{ flex: 1, padding: '12px 8px', textAlign: 'center', borderRadius: 10, background: on ? 'var(--m-accent-soft)' : 'var(--m-bg-2)', border: on ? '1px solid var(--m-accent-line)' : '1px solid var(--m-line)' }}>
                    <div style={{ height: 4, background: on ? 'var(--m-accent)' : 'var(--m-bg-3)', borderRadius: 2, marginBottom: 8 }} />
                    <div className="m-mono" style={{ fontSize: 10, color: on ? 'var(--m-accent)' : 'var(--m-ink-3)', letterSpacing: '.06em', textTransform: 'uppercase' }}>{l}</div>
                  </div>
                ))}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginTop: 24 }}>
                {[
                  { l: 'In a bad year, you could lose', v: '~₹3.1L', s: '12% drop' },
                  { l: 'Worst year in history', v: '-18%', s: 'COVID 2020' },
                  { l: 'Time to recover', v: '~14 months', s: 'usually' },
                ].map((m) => (
                  <div key={m.l} style={{ padding: 18, background: 'var(--m-bg-2)', borderRadius: 12 }}>
                    <div className="m-mono" style={{ fontSize: 10, color: 'var(--m-ink-3)', letterSpacing: '.06em', textTransform: 'uppercase' }}>{m.l}</div>
                    <div className="m-serif m-num" style={{ fontSize: 26, letterSpacing: '-0.025em', marginTop: 6 }}>{m.v}</div>
                    <div className="m-mono" style={{ fontSize: 10.5, color: 'var(--m-ink-3)', marginTop: 2 }}>{m.s}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function NVMBreakdownMobile() {
  const [tab, setTab] = React.useState('allocation');
  const segs = [
    { l: 'Equity', v: 68, c: 'var(--m-accent)' },
    { l: 'Debt', v: 18, c: '#A6A38E' },
    { l: 'Gold', v: 6, c: '#B5841F' },
    { l: 'Intl', v: 6, c: '#7A8298' },
    { l: 'Cash', v: 2, c: '#CFCFC2' },
  ];
  return (
    <div className="m-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="m-notch"></span>
      <div className="m-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '10px 22px 8px' }}>
        <div className="m-mono" style={{ fontSize: 10, color: 'var(--m-ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Breakdown</div>
        <div className="m-serif" style={{ fontSize: 22, letterSpacing: '-0.025em', marginTop: 2 }}>Where it lives</div>
      </div>

      <div style={{ display: 'flex', gap: 0, padding: '0 22px', borderBottom: '1px solid var(--m-line)', overflowX: 'auto' }}>
        {[
          ['allocation', 'Allocation'],
          ['exposure', 'Exposure'],
          ['overlap', 'Overlap'],
          ['risk', 'Risk'],
        ].map(([k, l]) => {
          const on = k === tab;
          return (
            <button key={k} onClick={() => setTab(k)} style={{
              padding: '10px 12px', fontSize: 12.5, border: 'none',
              background: 'transparent',
              color: on ? 'var(--m-ink)' : 'var(--m-ink-3)',
              fontWeight: on ? 500 : 400,
              borderBottom: on ? '2px solid var(--m-accent)' : '2px solid transparent',
              marginBottom: -1, cursor: 'pointer',
              whiteSpace: 'nowrap',
            }}>{l}</button>
          );
        })}
      </div>

      <div style={{ padding: '16px 22px 14px', flex: 1, overflow: 'hidden' }}>
        {tab === 'allocation' && (
          <div className="m-card" style={{ padding: 16, textAlign: 'center' }}>
            <NVMDonutSimple size={160} segs={segs} />
            <div className="m-serif" style={{ fontSize: 17, letterSpacing: '-0.02em', marginTop: 8, lineHeight: 1.25 }}>
              68% in stocks · 18% in debt
            </div>
            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 6, textAlign: 'left' }}>
              {segs.map((s) => (
                <div key={s.l} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ width: 11, height: 11, borderRadius: 3, background: s.c }} />
                  <span style={{ fontSize: 13 }}>{s.l}</span>
                  <span className="m-num" style={{ marginLeft: 'auto', fontSize: 13, fontWeight: 500 }}>{s.v}%</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {tab === 'exposure' && (
          <div className="m-card" style={{ padding: 12 }}>
            <div className="m-mono" style={{ fontSize: 9.5, color: 'var(--m-ink-3)', letterSpacing: '.12em', marginBottom: 6 }}>SECTOR MAP</div>
            <div style={{ overflow: 'hidden', display: 'flex', justifyContent: 'center' }}>
              <NVMTreemapSimple scale={0.56} />
            </div>
          </div>
        )}
        {tab === 'overlap' && (
          <div className="m-card" style={{ padding: 14 }}>
            <div className="m-mono" style={{ fontSize: 9.5, color: 'var(--m-ink-3)', letterSpacing: '.12em', marginBottom: 6 }}>FUND OVERLAP</div>
            {[
              { a: 'Axis BC ↔ ICICI BC', o: 71 },
              { a: 'Mirae Lg ↔ ICICI BC', o: 68 },
              { a: 'Axis BC ↔ Mirae Lg', o: 64 },
            ].map((r) => (
              <div key={r.a} style={{ padding: '9px 0', borderTop: '1px solid var(--m-line)' }}>
                <div style={{ display: 'flex' }}>
                  <span style={{ fontSize: 12.5 }}>{r.a}</span>
                  <span className="m-num" style={{ marginLeft: 'auto', fontSize: 12.5, color: r.o > 60 ? 'var(--m-neg)' : 'var(--m-ink-2)' }}>{r.o}%</span>
                </div>
                <div style={{ height: 4, background: 'var(--m-bg-2)', borderRadius: 2, marginTop: 5 }}>
                  <div style={{ width: `${r.o}%`, height: '100%', background: r.o > 60 ? 'var(--m-neg)' : 'var(--m-warm)' }} />
                </div>
              </div>
            ))}
          </div>
        )}
        {tab === 'risk' && (
          <div className="m-card" style={{ padding: 16 }}>
            <div className="m-mono" style={{ fontSize: 9.5, color: 'var(--m-ink-3)', letterSpacing: '.12em' }}>RISK</div>
            <div className="m-serif" style={{ fontSize: 22, marginTop: 4 }}>Moderate</div>
            <div style={{ display: 'flex', gap: 4, marginTop: 12 }}>
              {[1,2,3,4,5].map((i) => <div key={i} style={{ flex: 1, height: 6, borderRadius: 3, background: i <= 3 ? 'var(--m-accent)' : 'var(--m-bg-2)' }} />)}
            </div>
            <div style={{ marginTop: 14 }}>
              {[
                { l: 'Could lose in bad year', v: '~₹3.1L' },
                { l: 'Worst ever', v: '-18%' },
                { l: 'Time to recover', v: '~14 mo' },
              ].map((r) => (
                <div key={r.l} style={{ display: 'flex', padding: '8px 0', borderTop: '1px solid var(--m-line)' }}>
                  <span style={{ fontSize: 12.5 }}>{r.l}</span>
                  <span className="m-num" style={{ marginLeft: 'auto', fontSize: 13, fontWeight: 500 }}>{r.v}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <NVMBottomTabs active="breakdown" />
      <div className="m-homebar"></div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════
// 04 · RECOMMENDATIONS  (Keep · Reduce · Add)
// ════════════════════════════════════════════════════════════
function NVMRecCard({ kind, title, why, benefit, risk, action }) {
  const tagC = kind === 'keep' ? 'keep' : kind === 'reduce' ? 'reduce' : 'add';
  const label = kind === 'keep' ? 'KEEP' : kind === 'reduce' ? 'REDUCE' : 'ADD';
  return (
    <div className="m-card" style={{ padding: 22, marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className={`m-pill m-pill-${tagC}`}>{label}</span>
        <span className="m-mono" style={{ fontSize: 10.5, color: 'var(--m-ink-3)', letterSpacing: '.06em' }}>{action}</span>
      </div>
      <div className="m-serif" style={{ fontSize: 22, letterSpacing: '-0.02em', marginTop: 12, lineHeight: 1.25 }}>{title}</div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 18, marginTop: 18, paddingTop: 14, borderTop: '1px solid var(--m-line)' }}>
        <div>
          <div className="m-mono" style={{ fontSize: 10, letterSpacing: '.12em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Why this matters</div>
          <div style={{ fontSize: 13, color: 'var(--m-ink-2)', marginTop: 6, lineHeight: 1.5 }}>{why}</div>
        </div>
        <div>
          <div className="m-mono" style={{ fontSize: 10, letterSpacing: '.12em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Expected benefit</div>
          <div style={{ fontSize: 13, color: 'var(--m-pos)', marginTop: 6, lineHeight: 1.5, fontWeight: 500 }}>{benefit}</div>
        </div>
        <div>
          <div className="m-mono" style={{ fontSize: 10, letterSpacing: '.12em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Risk impact</div>
          <div style={{ fontSize: 13, color: 'var(--m-ink-2)', marginTop: 6, lineHeight: 1.5 }}>{risk}</div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
        <button className="m-btn m-btn-accent" style={{ padding: '10px 16px', fontSize: 13 }}>Apply →</button>
        <button className="m-btn" style={{ padding: '10px 16px', fontSize: 13 }}>Learn more</button>
      </div>
    </div>
  );
}

function NVMRecsDesktop() {
  return (
    <div className="m-frame" style={{ width: '100%', minHeight: 900, display: 'flex' }}>
      <NVMSidebar active="recs" />
      <main style={{ flex: 1, padding: '40px 56px 40px', maxWidth: 1080, margin: '0 auto' }}>
        <div className="m-mono" style={{ fontSize: 11, letterSpacing: '.18em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Recommendations</div>
        <h1 className="m-serif" style={{ fontSize: 38, letterSpacing: '-0.025em', margin: '6px 0 0', lineHeight: 1.05 }}>3 categories, 8 moves.</h1>
        <p style={{ fontSize: 16, color: 'var(--m-ink-2)', marginTop: 12, lineHeight: 1.55, maxWidth: 600 }}>
          We never push trades. Each card explains the why, the benefit, and the risk impact before you apply.
        </p>

        {/* segmented */}
        <div style={{ display: 'flex', gap: 6, marginTop: 22, padding: 4, background: 'var(--m-bg-2)', borderRadius: 12, width: 'fit-content' }}>
          {[
            { k: 'all', l: 'All · 8', on: true },
            { k: 'keep', l: 'Keep · 3' },
            { k: 'reduce', l: 'Reduce · 3' },
            { k: 'add', l: 'Add · 2' },
          ].map((o) => (
            <button key={o.k} style={{
              padding: '8px 16px', fontSize: 13, borderRadius: 8, border: 'none',
              background: o.on ? 'var(--m-bg-1)' : 'transparent',
              color: o.on ? 'var(--m-ink)' : 'var(--m-ink-2)',
              fontWeight: o.on ? 500 : 400,
              cursor: 'pointer',
              border: o.on ? '1px solid var(--m-line)' : '1px solid transparent',
            }}>{o.l}</button>
          ))}
        </div>

        <div style={{ marginTop: 22 }}>
          <NVMRecCard
            kind="reduce"
            title="Sell Axis Bluechip · 71% overlaps with ICICI Pru Bluechip"
            action="Switch · ₹1.2 L"
            why="You hold three large-cap funds with nearly identical top stocks. You're paying 3× the expense ratio for the same exposure."
            benefit="Saves ₹14,200 / year in hidden fund fees."
            risk="None — you keep the same companies through ICICI Pru."
          />
          <NVMRecCard
            kind="add"
            title="Top up your emergency fund · ₹4.6L to reach 6 months"
            action="Move to liquid fund"
            why="You hold 1.4 months of expenses in safe cash. Six months is the usual target before investing further."
            benefit="Peace of mind in a job loss · earns 6.8% in a liquid fund."
            risk="Lower — emergency money becomes truly safe."
          />
          <NVMRecCard
            kind="reduce"
            title="Trim HDFC Bank from 8.0% to 5.0% of portfolio"
            action="Sell · ₹74,000"
            why="One stock is 8% of your money. The safer maximum for a single name is 5%."
            benefit="Lower risk · ₹3,500/year safer in a bad bank year."
            risk="Slightly less upside if HDFC outperforms."
          />
          <NVMRecCard
            kind="keep"
            title="Keep Parag Parikh Flexi Cap · top quartile, low overlap"
            action="No change"
            why="Outperformed category by 3.4% over 3 years. Holds 30% international stocks — a useful diversifier."
            benefit="Continues to anchor the portfolio."
            risk="Same as today — moderate."
          />
          <NVMRecCard
            kind="add"
            title="Add a gold ETF · ₹70,000 to reach 8% allocation"
            action="Buy · gold ETF"
            why="Gold is currently 0% of your portfolio. A small slice softens equity falls and hedges currency."
            benefit="Lower swings · ₹1.4L less loss in a 2008-style year."
            risk="Lower."
          />
        </div>
      </main>
    </div>
  );
}

function NVMRecsMobile() {
  return (
    <div className="m-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="m-notch"></span>
      <div className="m-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '10px 22px 10px' }}>
        <div className="m-mono" style={{ fontSize: 10, color: 'var(--m-ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Tips</div>
        <div className="m-serif" style={{ fontSize: 22, marginTop: 4 }}>8 moves</div>
      </div>

      <div style={{ display: 'flex', gap: 4, padding: '0 22px 12px' }}>
        {[
          ['All · 8', true], ['Keep · 3'], ['Reduce · 3'], ['Add · 2'],
        ].map(([l, on], i) => (
          <button key={i} style={{
            flex: 1, padding: '8px 4px', fontSize: 11, borderRadius: 8,
            background: on ? 'var(--m-bg-1)' : 'var(--m-bg-2)',
            border: on ? '1px solid var(--m-line)' : '1px solid transparent',
            color: on ? 'var(--m-ink)' : 'var(--m-ink-3)',
            fontWeight: on ? 500 : 400, cursor: 'pointer',
          }}>{l}</button>
        ))}
      </div>

      <div style={{ padding: '0 22px 14px', flex: 1, overflow: 'hidden' }}>
        {[
          { k: 'reduce', t: 'Sell Axis Bluechip', b: '₹14.2k/yr saved', a: 'Switch ₹1.2L' },
          { k: 'add', t: 'Top up emergency', b: 'Peace of mind', a: '₹4.6L' },
          { k: 'reduce', t: 'Trim HDFC Bank', b: 'Lower risk', a: 'Sell ₹74k' },
          { k: 'keep', t: 'Keep PPFAS Flexi', b: 'Anchor fund', a: 'No change' },
        ].map((r, i) => {
          const tagC = r.k === 'keep' ? 'keep' : r.k === 'reduce' ? 'reduce' : 'add';
          const L = r.k.toUpperCase();
          return (
            <div key={i} className="m-card" style={{ padding: 13, marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className={`m-pill m-pill-${tagC}`} style={{ fontSize: 9, padding: '3px 9px' }}>{L}</span>
                <span className="m-mono" style={{ fontSize: 9.5, color: 'var(--m-ink-3)', letterSpacing: '.04em', marginLeft: 'auto' }}>{r.a}</span>
              </div>
              <div className="m-serif" style={{ fontSize: 16, letterSpacing: '-0.02em', marginTop: 6, lineHeight: 1.25 }}>{r.t}</div>
              <div style={{ fontSize: 12, color: 'var(--m-pos)', marginTop: 4 }}>● {r.b}</div>
              <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
                <button className="m-btn m-btn-accent" style={{ flex: 1, justifyContent: 'center', padding: '8px', fontSize: 12 }}>Apply →</button>
                <button className="m-btn" style={{ padding: '8px 12px', fontSize: 12 }}>Why?</button>
              </div>
            </div>
          );
        })}
      </div>

      <NVMBottomTabs active="recs" />
      <div className="m-homebar"></div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════
// 05 · AI CHAT
// ════════════════════════════════════════════════════════════
function NVMChatDesktop() {
  return (
    <div className="m-frame" style={{ width: '100%', minHeight: 900, display: 'flex' }}>
      <NVMSidebar active="chat" />
      <main style={{ flex: 1, padding: '40px 56px 0', maxWidth: 880, margin: '0 auto', display: 'flex', flexDirection: 'column' }}>
        <div className="m-mono" style={{ fontSize: 11, letterSpacing: '.18em', color: 'var(--m-ink-3)', textTransform: 'uppercase' }}>Chat</div>
        <h1 className="m-serif" style={{ fontSize: 36, letterSpacing: '-0.025em', margin: '6px 0 0', lineHeight: 1.05 }}>Ask anything about your portfolio.</h1>

        {/* sample chips */}
        <div style={{ display: 'flex', gap: 8, marginTop: 22, flexWrap: 'wrap' }}>
          {[
            'Why is my score 74?',
            'Which funds overlap most?',
            'How risky is my portfolio?',
            'What should I reduce first?',
            'How am I doing vs the market?',
          ].map((q) => (
            <span key={q} className="m-pill" style={{ padding: '8px 14px', cursor: 'pointer' }}>{q}</span>
          ))}
        </div>

        {/* thread */}
        <div style={{ marginTop: 28, flex: 1 }}>
          {/* user */}
          <div style={{ alignSelf: 'flex-end', marginLeft: 'auto', maxWidth: 520, padding: '12px 18px', background: 'var(--m-bg-2)', border: '1px solid var(--m-line)', borderRadius: '18px 18px 4px 18px', float: 'right', clear: 'both' }}>
            <span style={{ fontSize: 14 }}>Why is my score 74?</span>
          </div>
          <div style={{ clear: 'both' }} />

          {/* assistant */}
          <div style={{ display: 'flex', gap: 14, marginTop: 22 }}>
            <span className="m-mark" style={{ flex: 'none' }}>न</span>
            <div style={{ flex: 1 }}>
              <p style={{ fontSize: 15.5, lineHeight: 1.65, color: 'var(--m-ink)' }}>
                You score 74 mainly because of <strong style={{ fontWeight: 500 }}>fund overlap</strong>. Three of your large-cap funds — Axis Bluechip, ICICI Pru Bluechip, and Mirae Large — hold 64–71% of the same top stocks. That's like buying the same thing three times, while paying three different fees.
              </p>
              <p style={{ fontSize: 15.5, lineHeight: 1.65, color: 'var(--m-ink)', marginTop: 12 }}>
                Two smaller issues drag the score down too:
              </p>
              <ul style={{ marginTop: 8, paddingLeft: 20, color: 'var(--m-ink-2)', lineHeight: 1.7 }}>
                <li style={{ fontSize: 14.5 }}>About 38% of your equity sits in mid- and small-cap stocks (target is 25%).</li>
                <li style={{ fontSize: 14.5 }}>You have 1.4 months of expenses in your emergency fund (target is 6 months).</li>
              </ul>

              {/* inline insight card */}
              <div className="m-card" style={{ padding: 18, marginTop: 16, background: 'var(--m-accent-soft)', borderColor: 'var(--m-accent-line)' }}>
                <div className="m-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--m-accent)' }}>● ONE FIX MOVES YOU TO 82</div>
                <div className="m-serif" style={{ fontSize: 20, letterSpacing: '-0.02em', marginTop: 6, lineHeight: 1.25 }}>
                  Switch Axis Bluechip → into ICICI Pru. Saves ₹14,200/yr, removes the duplication.
                </div>
                <button className="m-btn m-btn-accent" style={{ marginTop: 12, padding: '9px 14px', fontSize: 13 }}>See this move →</button>
              </div>

              <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                <button className="m-btn" style={{ padding: '7px 12px', fontSize: 12 }}>Show me the math</button>
                <button className="m-btn" style={{ padding: '7px 12px', fontSize: 12 }}>What if I do nothing?</button>
              </div>
            </div>
          </div>
        </div>

        {/* composer */}
        <div style={{ padding: '14px 16px', background: 'var(--m-bg-1)', border: '1px solid var(--m-line-2)', borderRadius: 14, display: 'flex', alignItems: 'center', gap: 12, margin: '24px 0 32px' }}>
          <span style={{ color: 'var(--m-ink-3)', fontSize: 18 }}>＋</span>
          <span style={{ flex: 1, fontSize: 14.5, color: 'var(--m-ink-3)' }}>Ask anything…</span>
          <button className="m-btn m-btn-accent" style={{ padding: '8px 14px', fontSize: 13 }}>Send →</button>
        </div>
      </main>
    </div>
  );
}

function NVMChatMobile() {
  return (
    <div className="m-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="m-notch"></span>
      <div className="m-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '10px 22px 10px', display: 'flex', alignItems: 'center' }}>
        <div>
          <div className="m-mono" style={{ fontSize: 10, color: 'var(--m-ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Chat</div>
          <div className="m-serif" style={{ fontSize: 20 }}>Ask Nivesh</div>
        </div>
      </div>

      <div style={{ padding: '0 22px 14px', flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {/* chips */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
          {['Why 74?', 'Which overlap?', 'Reduce first?'].map((q) => (
            <span key={q} className="m-pill" style={{ fontSize: 11, padding: '6px 10px' }}>{q}</span>
          ))}
        </div>

        {/* user */}
        <div style={{ alignSelf: 'flex-end', maxWidth: 240, padding: '10px 14px', background: 'var(--m-bg-2)', border: '1px solid var(--m-line)', borderRadius: '14px 14px 3px 14px', marginBottom: 16 }}>
          <span style={{ fontSize: 13 }}>Why is my score 74?</span>
        </div>

        {/* assistant */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
          <span className="m-mark" style={{ width: 26, height: 26, fontSize: 15, flex: 'none' }}>न</span>
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 13.5, lineHeight: 1.55 }}>
              Your score is 74 mainly because of <strong style={{ fontWeight: 500 }}>fund overlap</strong>. Three of your funds hold 64–71% of the same stocks.
            </p>
          </div>
        </div>

        <div className="m-card" style={{ padding: 13, background: 'var(--m-accent-soft)', borderColor: 'var(--m-accent-line)', marginBottom: 14 }}>
          <div className="m-mono" style={{ fontSize: 9.5, color: 'var(--m-accent)', letterSpacing: '.12em' }}>● ONE FIX → 82</div>
          <div className="m-serif" style={{ fontSize: 15, marginTop: 4, lineHeight: 1.3 }}>Switch Axis Bluechip → ICICI Pru. Saves ₹14.2k/yr.</div>
          <button className="m-btn m-btn-accent" style={{ width: '100%', justifyContent: 'center', marginTop: 10, padding: '9px', fontSize: 12 }}>See move →</button>
        </div>

        <div style={{ marginTop: 'auto', padding: '11px 14px', background: 'var(--m-bg-1)', border: '1px solid var(--m-line-2)', borderRadius: 999, display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ color: 'var(--m-ink-3)' }}>＋</span>
          <span style={{ flex: 1, fontSize: 12.5, color: 'var(--m-ink-3)' }}>Ask anything…</span>
          <button className="m-btn m-btn-accent" style={{ padding: '6px 10px', fontSize: 11, borderRadius: 999 }}>↗</button>
        </div>
      </div>

      <NVMBottomTabs active="chat" />
      <div className="m-homebar"></div>
    </div>
  );
}

Object.assign(window, {
  NVMUploadDesktop, NVMUploadMobile,
  NVMDashboardDesktop, NVMDashboardMobile,
  NVMBreakdownDesktop, NVMBreakdownMobile,
  NVMRecsDesktop, NVMRecsMobile,
  NVMChatDesktop, NVMChatMobile,
});
