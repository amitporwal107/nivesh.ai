// ─── Nivesh · Chat copilot (insight landing) — desktop + mobile ───
// AI conversation surface · synthesizes a portfolio reading

function NVChatRow({ severity, num, title, sub, value, delta }) {
  const c = severity;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '14px 18px', borderRadius: 12, background: 'var(--bg-1)', border: '1px solid var(--line)' }}>
      <div style={{ width: 36, height: 36, borderRadius: 10, background: `var(--${c}-soft)`, border: `1px solid var(--${c}-line)`, display: 'grid', placeItems: 'center', color: `var(--${c})`, fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 600, letterSpacing: '.04em', flex: 'none' }}>{num}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14.5, fontWeight: 500, letterSpacing: '-0.005em' }}>{title}</div>
        <div className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 2, letterSpacing: '.04em', textTransform: 'uppercase' }}>{sub}</div>
      </div>
      {value && <div className="nv-num" style={{ fontSize: 18, color: `var(--${c})`, fontWeight: 500 }}>{value}</div>}
      {delta && <div className="nv-mono nv-num" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '.04em' }}>{delta}</div>}
      <span style={{ color: 'var(--ink-3)', fontSize: 20 }}>›</span>
    </div>
  );
}

function NVScoreRing({ size = 132, score = 86, label = "Grade A" }) {
  const r = (size - 18) / 2;
  const c = 2 * Math.PI * r;
  const dash = c * (score / 100);
  const cx = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <defs>
        <linearGradient id={`ring-${size}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--mint)" />
          <stop offset="1" stopColor="var(--mint-2)" />
        </linearGradient>
      </defs>
      <circle cx={cx} cy={cx} r={r} fill="none" stroke="var(--bg-3)" strokeWidth="10" />
      <circle cx={cx} cy={cx} r={r} fill="none" stroke={`url(#ring-${size})`} strokeWidth="10" strokeDasharray={`${dash} ${c - dash}`} strokeLinecap="round" transform={`rotate(-90 ${cx} ${cx})`} />
      <text x={cx} y={cx - 2} textAnchor="middle" dominantBaseline="middle" fill="var(--ink)" fontFamily="var(--display)" fontSize={size * 0.34} letterSpacing="-0.04em">{score}</text>
      <text x={cx} y={cx + size * 0.2} textAnchor="middle" fill="var(--ink-3)" fontFamily="var(--mono)" fontSize="10" letterSpacing="2">/ 100</text>
    </svg>
  );
}

function NVChatDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 920, display: 'flex' }}>
      {/* sidebar */}
      <aside style={{ width: 240, borderRight: '1px solid var(--line)', padding: '22px 16px', display: 'flex', flexDirection: 'column', gap: 4, background: 'var(--bg-0)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 8px 22px' }}>
          <span className="nv-mark">न</span>
          <span className="nv-serif" style={{ fontSize: 18 }}>Nivesh</span>
        </div>
        <div className="nv-mono" style={{ fontSize: 9.5, letterSpacing: '.16em', color: 'var(--ink-4)', padding: '6px 10px', textTransform: 'uppercase' }}>Today</div>
        {[
          ['Portfolio health · Nov 26', true],
          ['Should I rebalance financials?', false],
          ['Tax loss before March', false],
        ].map(([t, on]) => (
          <div key={t} style={{ padding: '9px 12px', fontSize: 13, borderRadius: 8, background: on ? 'var(--bg-2)' : 'transparent', color: on ? 'var(--ink)' : 'var(--ink-2)', border: on ? '1px solid var(--line)' : '1px solid transparent', cursor: 'pointer' }}>{t}</div>
        ))}
        <div className="nv-mono" style={{ fontSize: 9.5, letterSpacing: '.16em', color: 'var(--ink-4)', padding: '18px 10px 6px', textTransform: 'uppercase' }}>This week</div>
        {['Mid-cap exposure', 'Reading my CAS', 'Goals · Retirement gap'].map((t) => (
          <div key={t} style={{ padding: '9px 12px', fontSize: 13, color: 'var(--ink-2)', borderRadius: 8, cursor: 'pointer' }}>{t}</div>
        ))}
        <div style={{ marginTop: 'auto', padding: '12px 10px', borderTop: '1px solid var(--line)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 30, height: 30, borderRadius: 8, background: 'var(--bg-3)', display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-2)' }}>AK</div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 500 }}>Aarav Kumar</div>
            <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)' }}>₹ 24.8 L · Verified</div>
          </div>
        </div>
      </aside>

      {/* main thread */}
      <main style={{ flex: 1, padding: '36px 56px 24px', maxWidth: 980, margin: '0 auto', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 22 }}>
          <span className="nv-pill nv-pill-mint"><span className="nv-dot" style={{ background: 'var(--mint)' }} />NIDP CONNECTED</span>
          <span className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '.04em' }}>last sync · 2m ago · 47 holdings</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            <button className="nv-btn" style={{ padding: '6px 11px', fontSize: 12 }}>Re-sync</button>
            <button className="nv-btn" style={{ padding: '6px 11px', fontSize: 12 }}>Share</button>
          </span>
        </div>

        {/* user prompt */}
        <div style={{ alignSelf: 'flex-end', maxWidth: 540, padding: '12px 18px', background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: '18px 18px 4px 18px', marginBottom: 28 }}>
          <span style={{ fontSize: 14.5 }}>Read my portfolio. What's the one thing I should fix first?</span>
        </div>

        {/* assistant response — synthesis */}
        <div style={{ display: 'flex', gap: 14, marginBottom: 14 }}>
          <span className="nv-mark" style={{ flex: 'none', marginTop: 4 }}>न</span>
          <div style={{ flex: 1 }}>
            <div className="nv-serif" style={{ fontSize: 32, lineHeight: 1.15, letterSpacing: '-0.02em', color: 'var(--ink)', maxWidth: 720 }}>
              Your portfolio is <span style={{ color: 'var(--mint)' }}>healthy</span> — but financials are eating
              a third of every rupee you've invested.
            </div>
            <p style={{ fontSize: 15, color: 'var(--ink-2)', lineHeight: 1.6, marginTop: 14, maxWidth: 680 }}>
              You score 86. Three issues account for almost all of that 14-point gap — concentration first, then a hidden overlap between funds, then a tax window that closes in March. I've ordered them by ₹ impact.
            </p>
          </div>
        </div>

        {/* score + signals */}
        <div className="nv-card" style={{ display: 'grid', gridTemplateColumns: '180px 1fr', gap: 0, marginBottom: 22, overflow: 'hidden' }}>
          <div style={{ padding: '22px 18px', borderRight: '1px solid var(--line)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-0)' }}>
            <NVScoreRing size={130} />
            <span className="nv-pill nv-pill-mint" style={{ marginTop: 14 }}>GRADE A</span>
          </div>
          <div style={{ padding: 18, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
            {[
              { l: 'Concentration', v: '58', d: 'down 4 wow', c: 'amber' },
              { l: 'Diversification', v: '78', d: 'flat', c: 'mint' },
              { l: 'Risk', v: '92', d: 'up 2', c: 'mint' },
              { l: 'Performance', v: '81', d: 'up 1.4%', c: 'mint' },
              { l: 'Goals', v: '74', d: '2 of 3 on track', c: 'indigo' },
              { l: 'Tax', v: '88', d: '₹38k available', c: 'mint' },
            ].map((m) => (
              <div key={m.l} style={{ padding: '10px 12px', borderRadius: 10, background: 'var(--bg-1)', border: '1px solid var(--line)' }}>
                <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.1em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>{m.l}</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 4 }}>
                  <span className="nv-serif nv-num" style={{ fontSize: 32, letterSpacing: '-0.03em' }}>{m.v}</span>
                  <span className="nv-mono" style={{ fontSize: 10, color: `var(--${m.c})` }}>/100</span>
                </div>
                <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '.02em', marginTop: 2 }}>{m.d}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="nv-mono" style={{ fontSize: 10.5, letterSpacing: '.16em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 10 }}>Top 3 actions · ranked by ₹ impact</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 22 }}>
          <NVChatRow severity="amber" num="01" title="Trim financials from 32% → 24%" sub="Sell HDFC Bank · ₹1.8L" value="-2.3 pt risk" delta="+₹0.4L/yr exp." />
          <NVChatRow severity="indigo" num="02" title="Consolidate 3 large-cap funds with 71% overlap" sub="Move Axis BC → Parag P Flexi" value="₹14k fees/yr" delta="cleaner book" />
          <NVChatRow severity="mint" num="03" title="Harvest losses · ₹38,400 before Mar 31" sub="3 lots flagged · auto-rebuy after 31 days" value="₹11,520 saved" delta="tax · LTCG" />
        </div>

        {/* input bar */}
        <div className="nv-glass" style={{ marginTop: 'auto', padding: '14px 18px', display: 'flex', alignItems: 'center', gap: 12, borderRadius: 16 }}>
          <span style={{ color: 'var(--ink-3)', fontSize: 18 }}>＋</span>
          <span style={{ flex: 1, fontSize: 14, color: 'var(--ink-3)' }}>Ask anything · "what if I sell HDFC Bank?"</span>
          <div style={{ display: 'flex', gap: 6 }}>
            {['Concentration', 'Tax', 'Goals'].map((c) => (
              <span key={c} style={{ fontSize: 11, padding: '4px 9px', borderRadius: 999, border: '1px solid var(--line-2)', color: 'var(--ink-2)' }}>{c}</span>
            ))}
          </div>
          <button className="nv-btn nv-btn-primary" style={{ padding: '8px 12px', fontSize: 12 }}>↗ Send</button>
        </div>
      </main>
    </div>
  );
}

function NVChatMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ display: 'flex', alignItems: 'center', padding: '8px 18px 14px', gap: 10 }}>
        <span style={{ color: 'var(--ink-2)', fontSize: 20 }}>≡</span>
        <span className="nv-serif" style={{ fontSize: 17 }}>Portfolio health</span>
        <span className="nv-pill nv-pill-mint" style={{ marginLeft: 'auto', fontSize: 9 }}><span className="nv-dot" style={{ background: 'var(--mint)' }} />LIVE</span>
      </div>

      <div style={{ padding: '4px 18px 12px', flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div style={{ alignSelf: 'flex-end', maxWidth: 260, padding: '10px 14px', background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: '14px 14px 3px 14px', marginBottom: 18 }}>
          <span style={{ fontSize: 13 }}>What should I fix first?</span>
        </div>

        <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
          <span className="nv-mark" style={{ width: 26, height: 26, fontSize: 15, flex: 'none' }}>न</span>
          <div className="nv-serif" style={{ fontSize: 22, lineHeight: 1.18, letterSpacing: '-0.02em' }}>
            Healthy — but financials are <span style={{ color: 'var(--mint)' }}>32%</span>.
          </div>
        </div>

        <div className="nv-card" style={{ padding: '14px 14px 12px', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 14 }}>
          <NVScoreRing size={84} />
          <div style={{ flex: 1 }}>
            <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Overall</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 2 }}>
              <span className="nv-pill nv-pill-mint" style={{ fontSize: 9 }}>GRADE A</span>
            </div>
            <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6, letterSpacing: '.04em' }}>3 ACTIONS · 14 PT GAP</div>
          </div>
        </div>

        <div className="nv-mono" style={{ fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 8 }}>Ranked by ₹ impact</div>

        {[
          { c: 'amber', n: '01', t: 'Trim financials 32 → 24%', s: 'HDFC Bank · ₹1.8L', v: '+₹0.4L/yr' },
          { c: 'indigo', n: '02', t: '3 funds, 71% overlap', s: 'Axis BC → Parag P', v: '₹14k fees' },
          { c: 'mint', n: '03', t: 'Harvest ₹38k loss', s: 'Before Mar 31', v: '₹11.5k saved' },
        ].map((r) => (
          <div key={r.n} className="nv-card-2" style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '12px 13px', marginBottom: 8 }}>
            <div style={{ width: 30, height: 30, borderRadius: 9, background: `var(--${r.c}-soft)`, border: `1px solid var(--${r.c}-line)`, display: 'grid', placeItems: 'center', color: `var(--${r.c})`, fontFamily: 'var(--mono)', fontSize: 10, flex: 'none' }}>{r.n}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 500 }}>{r.t}</div>
              <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', marginTop: 2, letterSpacing: '.04em', textTransform: 'uppercase' }}>{r.s}</div>
            </div>
            <div className="nv-mono nv-num" style={{ fontSize: 10, color: `var(--${r.c})`, letterSpacing: '.02em' }}>{r.v}</div>
          </div>
        ))}

        <div style={{ marginTop: 'auto' }}>
          <div className="nv-glass" style={{ padding: '11px 14px', display: 'flex', alignItems: 'center', gap: 10, borderRadius: 999 }}>
            <span style={{ color: 'var(--ink-3)' }}>＋</span>
            <span style={{ flex: 1, fontSize: 12.5, color: 'var(--ink-3)' }}>Ask anything…</span>
            <button className="nv-btn nv-btn-primary" style={{ padding: '6px 10px', fontSize: 11, borderRadius: 999 }}>↗</button>
          </div>
        </div>
      </div>

      <div className="nv-homebar"></div>
    </div>
  );
}

Object.assign(window, { NVChatDesktop, NVChatMobile });
