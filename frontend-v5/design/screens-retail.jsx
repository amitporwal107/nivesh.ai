// ─── Nivesh Retail · simplified screens — desktop + mobile ───
// Plain language. One big idea per screen. Generous whitespace.
// All copy uses retail-friendly words: "money", "spread", "growth",
// "fix this" — no jargon (no XIRR/Sharpe/HHI/alpha).

// ════════════════════════════════════════════════════════════
// Shared chrome
// ════════════════════════════════════════════════════════════
function NVRSidebar({ active = 'today' }) {
  const items = [
    ['Today',          'today',  '◐'],
    ['Money health',   'health', '♡'],
    ['Where it sits',  'where',  '◔'],
    ['My goals',       'goals',  '◇'],
    ['Fix this',       'fix',    '✓'],
  ];
  return (
    <aside style={{ width: 240, borderRight: '1px solid var(--r-line)', padding: '28px 18px', display: 'flex', flexDirection: 'column', background: 'var(--r-bg)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '4px 10px 26px' }}>
        <span className="r-mark">न</span>
        <div>
          <div className="r-serif" style={{ fontSize: 19 }}>Nivesh</div>
          <div className="r-mono" style={{ fontSize: 9.5, color: 'var(--r-ink-3)', letterSpacing: '.16em', textTransform: 'uppercase', marginTop: 1 }}>FOR YOU</div>
        </div>
      </div>
      {items.map(([t, k, i]) => {
        const on = k === active;
        return (
          <div key={k} style={{
            display: 'flex', alignItems: 'center', gap: 12,
            padding: '12px 14px', fontSize: 14.5, borderRadius: 12,
            color: on ? 'var(--r-ink)' : 'var(--r-ink-2)',
            background: on ? 'var(--r-bg-1)' : 'transparent',
            border: on ? '1px solid var(--r-line-2)' : '1px solid transparent',
            fontWeight: on ? 500 : 400,
            cursor: 'pointer',
            marginBottom: 4,
          }}>
            <span style={{ color: on ? 'var(--r-good)' : 'var(--r-ink-3)', width: 18, textAlign: 'center', fontFamily: 'var(--r-mono)', fontSize: 14 }}>{i}</span>
            <span>{t}</span>
          </div>
        );
      })}
      <div style={{ marginTop: 'auto', padding: '14px 14px 6px', borderTop: '1px solid var(--r-line)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ width: 34, height: 34, borderRadius: 10, background: 'var(--r-bg-2)', display: 'grid', placeItems: 'center', fontFamily: 'var(--r-display)', fontSize: 16, color: 'var(--r-ink-2)' }}>A</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 500 }}>Aarav</div>
          <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', letterSpacing: '.04em' }}>Settings →</div>
        </div>
      </div>
    </aside>
  );
}

function NVRBottomTabs({ active = 'today' }) {
  const items = [
    ['◐', 'Today', 'today'],
    ['♡', 'Health', 'health'],
    ['◇', 'Goals', 'goals'],
    ['✓', 'Fix this', 'fix'],
    ['☰', 'More', 'more'],
  ];
  return (
    <div style={{ display: 'flex', justifyContent: 'space-around', padding: '10px 12px 22px', borderTop: '1px solid var(--r-line)', background: 'var(--r-bg)' }}>
      {items.map(([i, l, k]) => {
        const on = k === active;
        return (
          <div key={k} style={{ textAlign: 'center', color: on ? 'var(--r-good)' : 'var(--r-ink-3)' }}>
            <div style={{ fontSize: 19, fontFamily: 'var(--r-mono)' }}>{i}</div>
            <div style={{ fontSize: 11, fontWeight: on ? 500 : 400, marginTop: 2 }}>{l}</div>
          </div>
        );
      })}
    </div>
  );
}

function NVRGreeting({ size = 'large' }) {
  const isLarge = size === 'large';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <span style={{ fontSize: isLarge ? 28 : 22 }}>🙏</span>
      <div>
        <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Good morning</div>
        <div className="r-serif" style={{ fontSize: isLarge ? 32 : 22, letterSpacing: '-0.02em', marginTop: 2 }}>Namaste, Aarav</div>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════
// 01 · TODAY / HOME
// ════════════════════════════════════════════════════════════
function NVRTodayDesktop() {
  return (
    <div className="r-frame" style={{ width: '100%', minHeight: 900, display: 'flex' }}>
      <NVRSidebar active="today" />
      <main style={{ flex: 1, padding: '36px 56px 40px', maxWidth: 980, margin: '0 auto' }}>
        <NVRGreeting />

        {/* hero — your money */}
        <div className="r-card" style={{ marginTop: 28, padding: 'var(--r-pad-section)' }}>
          <div className="r-mono" style={{ fontSize: 12, letterSpacing: '.14em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Your money today</div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 24, marginTop: 12, flexWrap: 'wrap' }}>
            <div className="r-serif r-num" style={{ fontSize: 'var(--r-fz-display)', letterSpacing: '-0.035em', lineHeight: 0.95 }}>
              ₹24,82,400
            </div>
            <div style={{ marginBottom: 8 }}>
              <span className="r-pill r-pill-good" style={{ marginBottom: 6 }}>
                <span className="r-dot" style={{ background: 'var(--r-good)' }} />
                Up ₹14,200 this week
              </span>
              <div className="r-mono" style={{ fontSize: 11, color: 'var(--r-ink-3)', marginTop: 6, letterSpacing: '.04em' }}>
                That's 0.6% — about a coffee a day, growing.
              </div>
            </div>
          </div>

          {/* simple 4-week sparkline */}
          <svg viewBox="0 0 600 80" style={{ width: '100%', marginTop: 18, height: 80 }}>
            <defs>
              <linearGradient id="r-today-g" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="var(--r-good)" stopOpacity=".25" />
                <stop offset="1" stopColor="var(--r-good)" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d="M0,60 C60,55 120,50 180,46 C240,40 300,42 360,34 C420,28 480,22 540,16 L600,12 L600,80 L0,80 Z" fill="url(#r-today-g)" />
            <path d="M0,60 C60,55 120,50 180,46 C240,40 300,42 360,34 C420,28 480,22 540,16 L600,12" fill="none" stroke="var(--r-good)" strokeWidth="2.5" strokeLinecap="round" />
            <circle cx="600" cy="12" r="5" fill="var(--r-good)" />
          </svg>
        </div>

        {/* big takeaway */}
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 18, marginTop: 18 }}>
          <div className="r-card" style={{ background: 'var(--r-good-soft)', borderColor: 'var(--r-good-line)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
              <span style={{ width: 32, height: 32, borderRadius: '50%', background: 'var(--r-good)', color: 'var(--r-bg-1)', display: 'grid', placeItems: 'center', fontSize: 16 }}>✓</span>
              <span className="r-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--r-good)', textTransform: 'uppercase' }}>The big picture</span>
            </div>
            <div className="r-serif" style={{ fontSize: 'var(--r-fz-h1)', letterSpacing: '-0.025em', lineHeight: 1.1 }}>
              You're doing fine. Just one thing worth fixing.
            </div>
            <p style={{ fontSize: 15, color: 'var(--r-ink-2)', lineHeight: 1.55, marginTop: 14, maxWidth: 420 }}>
              Too much of your money is in banks (HDFC, ICICI etc.). That's a small risk — and we have one easy fix.
            </p>
            <button className="r-btn r-btn-good" style={{ marginTop: 18 }}>See the fix →</button>
          </div>

          {/* one suggestion */}
          <div className="r-card-2">
            <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Suggested today</div>
            <div className="r-serif" style={{ fontSize: 22, letterSpacing: '-0.02em', marginTop: 8, lineHeight: 1.25 }}>
              Move ₹1,800 from savings to a liquid fund.
            </div>
            <div style={{ fontSize: 14, color: 'var(--r-ink-2)', marginTop: 10, lineHeight: 1.5 }}>
              Your idle savings earn 3.5%. Liquid funds earn ~6.8% — same safety, same one-day access.
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--r-line)' }}>
              <span className="r-mono" style={{ fontSize: 11, color: 'var(--r-ink-3)', letterSpacing: '.04em' }}>EARNS YOU</span>
              <span className="r-serif r-num" style={{ marginLeft: 'auto', fontSize: 28, color: 'var(--r-good)' }}>+₹66 / month</span>
            </div>
            <button className="r-btn" style={{ width: '100%', justifyContent: 'center', marginTop: 14 }}>Tap to learn more</button>
          </div>
        </div>

        {/* quick glances */}
        <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.18em', color: 'var(--r-ink-3)', textTransform: 'uppercase', marginTop: 30, marginBottom: 12 }}>Quick glance</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
          {[
            { i: '♡', l: 'Health', v: '86', sub: 'Out of 100', c: 'good' },
            { i: '◇', l: 'On track', v: '2 of 3', sub: 'Goals doing well', c: 'good' },
            { i: '✓', l: 'To fix', v: '1', sub: 'Easy step', c: 'watch' },
          ].map((m) => (
            <div key={m.l} className="r-card" style={{ padding: 22 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ width: 28, height: 28, borderRadius: 8, background: `var(--r-${m.c}-soft)`, color: `var(--r-${m.c})`, display: 'grid', placeItems: 'center', fontFamily: 'var(--r-mono)', fontSize: 13 }}>{m.i}</span>
                <span className="r-mono" style={{ fontSize: 11, color: 'var(--r-ink-3)', letterSpacing: '.06em', textTransform: 'uppercase' }}>{m.l}</span>
              </div>
              <div className="r-serif r-num" style={{ fontSize: 34, letterSpacing: '-0.03em', marginTop: 10 }}>{m.v}</div>
              <div style={{ fontSize: 13, color: 'var(--r-ink-2)', marginTop: 2 }}>{m.sub}</div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function NVRTodayMobile() {
  return (
    <div className="r-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="r-notch"></span>
      <div className="r-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '12px 22px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <NVRGreeting size="small" />
          <div style={{ marginLeft: 'auto', width: 36, height: 36, borderRadius: 12, background: 'var(--r-bg-1)', border: '1px solid var(--r-line)', display: 'grid', placeItems: 'center', fontSize: 14, color: 'var(--r-ink-2)' }}>⚙</div>
        </div>
      </div>

      <div style={{ padding: '0 22px 14px', flex: 1, overflow: 'hidden' }}>
        {/* hero — money */}
        <div className="r-card" style={{ marginBottom: 12 }}>
          <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Your money</div>
          <div className="r-serif r-num" style={{ fontSize: 38, letterSpacing: '-0.035em', lineHeight: 1, marginTop: 6 }}>₹24,82,400</div>
          <div className="r-pill r-pill-good" style={{ marginTop: 10 }}>
            <span className="r-dot" style={{ background: 'var(--r-good)' }} />Up ₹14,200 this week
          </div>
          <svg viewBox="0 0 320 50" style={{ width: '100%', marginTop: 14 }}>
            <defs><linearGradient id="r-mob" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--r-good)" stopOpacity=".25"/><stop offset="1" stopColor="var(--r-good)" stopOpacity="0"/></linearGradient></defs>
            <path d="M0,40 C40,36 80,32 140,28 C200,22 260,16 320,8 L320,50 L0,50 Z" fill="url(#r-mob)" />
            <path d="M0,40 C40,36 80,32 140,28 C200,22 260,16 320,8" fill="none" stroke="var(--r-good)" strokeWidth="2" />
            <circle cx="320" cy="8" r="4" fill="var(--r-good)" />
          </svg>
        </div>

        {/* the big takeaway */}
        <div className="r-card" style={{ background: 'var(--r-good-soft)', borderColor: 'var(--r-good-line)', marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ width: 24, height: 24, borderRadius: '50%', background: 'var(--r-good)', color: 'var(--r-bg-1)', display: 'grid', placeItems: 'center', fontSize: 13 }}>✓</span>
            <span className="r-mono" style={{ fontSize: 10, color: 'var(--r-good)', letterSpacing: '.12em' }}>BIG PICTURE</span>
          </div>
          <div className="r-serif" style={{ fontSize: 24, letterSpacing: '-0.02em', lineHeight: 1.15 }}>
            You're doing fine.
            <br />One thing to fix.
          </div>
          <p style={{ fontSize: 13, color: 'var(--r-ink-2)', marginTop: 10, lineHeight: 1.5 }}>
            Too much money in bank stocks. Small risk, easy fix.
          </p>
          <button className="r-btn r-btn-good" style={{ marginTop: 14, padding: '12px 16px', fontSize: 14, width: '100%', justifyContent: 'center' }}>See the fix →</button>
        </div>

        {/* glance row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          {[
            { l: 'Health', v: '86', c: 'good' },
            { l: 'Goals', v: '2/3', c: 'good' },
            { l: 'To fix', v: '1', c: 'watch' },
          ].map((m) => (
            <div key={m.l} className="r-card" style={{ padding: 14, textAlign: 'center' }}>
              <div className="r-mono" style={{ fontSize: 9.5, color: 'var(--r-ink-3)', letterSpacing: '.1em', textTransform: 'uppercase' }}>{m.l}</div>
              <div className="r-serif r-num" style={{ fontSize: 24, color: `var(--r-${m.c})`, marginTop: 4 }}>{m.v}</div>
            </div>
          ))}
        </div>
      </div>

      <NVRBottomTabs active="today" />
      <div className="r-homebar"></div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════
// 02 · MONEY HEALTH (simplified score)
// ════════════════════════════════════════════════════════════
function NVRBigScore({ score = 86, size = 220 }) {
  const r = (size - 32) / 2;
  const c = 2 * Math.PI * r;
  const dash = c * (score / 100);
  const cx = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={cx} cy={cx} r={r} fill="none" stroke="var(--r-bg-2)" strokeWidth="14" />
      <circle cx={cx} cy={cx} r={r} fill="none" stroke="var(--r-good)" strokeWidth="14"
        strokeDasharray={`${dash} ${c - dash}`} strokeLinecap="round" transform={`rotate(-90 ${cx} ${cx})`} />
      <text x={cx} y={cx - 2} textAnchor="middle" dominantBaseline="middle" fill="var(--r-ink)" fontFamily="var(--r-display)" fontSize={size * 0.36} letterSpacing="-0.04em">{score}</text>
      <text x={cx} y={cx + size * 0.18} textAnchor="middle" fill="var(--r-ink-3)" fontFamily="var(--r-sans)" fontSize={size * 0.07}>out of 100</text>
    </svg>
  );
}

function NVRHealthDesktop() {
  const cards = [
    { l: 'Spread out', v: 'Mostly good', desc: 'A bit too much in banks. Otherwise nicely mixed across types.', c: 'watch', score: 72 },
    { l: 'Risk level',  v: 'Just right',  desc: 'Your money can wobble, but won\u2019t suddenly drop a lot. Good for your age.', c: 'good',  score: 92 },
    { l: 'Growing',     v: 'Beating average', desc: 'Last year you earned 18.7%. The market did 16.6%. You\u2019re ahead.', c: 'good',  score: 88 },
    { l: 'Cost',        v: 'Could be cheaper', desc: 'You pay ~₹14k a year in hidden fund fees. Switching some can save ₹6k.', c: 'watch', score: 70 },
  ];
  return (
    <div className="r-frame" style={{ width: '100%', minHeight: 900, display: 'flex' }}>
      <NVRSidebar active="health" />
      <main style={{ flex: 1, padding: '36px 56px 40px', maxWidth: 1000, margin: '0 auto' }}>
        <div>
          <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.18em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Money health</div>
          <h1 className="r-serif" style={{ fontSize: 'var(--r-fz-h1)', letterSpacing: '-0.025em', margin: '6px 0 0', lineHeight: 1.05 }}>How your money is doing.</h1>
        </div>

        {/* score hero */}
        <div className="r-card" style={{ marginTop: 22, padding: 32, display: 'grid', gridTemplateColumns: '230px 1fr', gap: 36, alignItems: 'center' }}>
          <NVRBigScore />
          <div>
            <span className="r-pill r-pill-good">Healthy</span>
            <div className="r-serif" style={{ fontSize: 32, letterSpacing: '-0.025em', lineHeight: 1.15, marginTop: 14 }}>
              Your money is healthy.<br />Two small things would make it great.
            </div>
            <p style={{ fontSize: 15, color: 'var(--r-ink-2)', marginTop: 14, lineHeight: 1.55, maxWidth: 480 }}>
              We look at 4 things: how spread out your money is, how risky it is, how well it's growing, and what it costs you. Tap any card to learn more.
            </p>
          </div>
        </div>

        {/* 4 plain cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16, marginTop: 18 }}>
          {cards.map((card) => (
            <div key={card.l} className="r-card" style={{ padding: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>{card.l}</div>
                <span className={`r-pill r-pill-${card.c}`} style={{ marginLeft: 'auto', fontSize: 11 }}>
                  <span className="r-dot" style={{ background: `var(--r-${card.c})` }} />{card.v}
                </span>
              </div>
              <div className="r-serif" style={{ fontSize: 'var(--r-fz-h2)', letterSpacing: '-0.02em', marginTop: 14, lineHeight: 1.3 }}>{card.desc}</div>
              {/* simple bar */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 18 }}>
                <div style={{ flex: 1, height: 8, background: 'var(--r-bg-2)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: `${card.score}%`, height: '100%', background: `var(--r-${card.c})`, borderRadius: 4 }} />
                </div>
                <span className="r-num" style={{ fontSize: 14, fontWeight: 500, color: `var(--r-${card.c})` }}>{card.score}</span>
              </div>
              <button className="r-btn" style={{ marginTop: 16, padding: '10px 14px', fontSize: 13 }}>What does this mean? →</button>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function NVRHealthMobile() {
  return (
    <div className="r-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="r-notch"></span>
      <div className="r-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '8px 22px 14px', display: 'flex', alignItems: 'center' }}>
        <div>
          <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Money health</div>
          <div className="r-serif" style={{ fontSize: 22, marginTop: 1 }}>How you're doing</div>
        </div>
      </div>

      <div style={{ padding: '0 22px 14px', flex: 1, overflow: 'hidden' }}>
        <div className="r-card" style={{ padding: 22, textAlign: 'center', marginBottom: 12 }}>
          <NVRBigScore size={150} />
          <div className="r-pill r-pill-good" style={{ marginTop: 4 }}>Healthy</div>
          <div className="r-serif" style={{ fontSize: 18, letterSpacing: '-0.02em', marginTop: 12, lineHeight: 1.3 }}>
            Healthy! 2 small things would<br/>make it great.
          </div>
        </div>

        {[
          { l: 'Spread', s: 'Mostly good', d: 'A bit too much in banks.', c: 'watch', score: 72 },
          { l: 'Risk', s: 'Just right', d: 'Good for your age.', c: 'good', score: 92 },
          { l: 'Growth', s: 'Beating market', d: 'You earned 18.7%, market 16.6%.', c: 'good', score: 88 },
          { l: 'Cost', s: 'Can be cheaper', d: '₹6k savings available.', c: 'watch', score: 70 },
        ].map((card) => (
          <div key={card.l} className="r-card" style={{ padding: 14, marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <span className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', letterSpacing: '.1em' }}>{card.l.toUpperCase()}</span>
              <span className={`r-pill r-pill-${card.c}`} style={{ marginLeft: 'auto', fontSize: 10, padding: '3px 9px' }}>{card.s}</span>
            </div>
            <div style={{ fontSize: 13.5, marginTop: 6, lineHeight: 1.4 }}>{card.d}</div>
            <div style={{ height: 5, background: 'var(--r-bg-2)', borderRadius: 3, marginTop: 8 }}>
              <div style={{ width: `${card.score}%`, height: '100%', background: `var(--r-${card.c})`, borderRadius: 3 }} />
            </div>
          </div>
        ))}
      </div>

      <NVRBottomTabs active="health" />
      <div className="r-homebar"></div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════
// 03 · WHERE YOUR MONEY SITS (simplified concentration)
// ════════════════════════════════════════════════════════════
function NVRDonut({ size = 200, segs }) {
  const cx = size / 2;
  const r = (size - 20) / 2;
  const C = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={cx} cy={cx} r={r} fill="none" stroke="var(--r-bg-2)" strokeWidth="16" />
      {segs.map((s, i) => {
        const dash = C * (s.v / 100);
        const el = (
          <circle key={i} cx={cx} cy={cx} r={r} fill="none"
            stroke={s.c} strokeWidth="16"
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

function NVRWhereDesktop() {
  const segs = [
    { l: 'Banks', v: 32, c: 'var(--r-fix)', warn: true },
    { l: 'Tech', v: 22, c: 'var(--r-info)' },
    { l: 'Energy', v: 14, c: 'var(--r-watch)' },
    { l: 'Everyday brands', v: 11, c: 'var(--r-good)' },
    { l: 'Medicines', v: 9, c: '#A479C9' },
    { l: 'Cars', v: 7, c: '#7A8298' },
    { l: 'Other', v: 5, c: '#C9C2AB' },
  ];
  return (
    <div className="r-frame" style={{ width: '100%', minHeight: 900, display: 'flex' }}>
      <NVRSidebar active="where" />
      <main style={{ flex: 1, padding: '36px 56px 40px', maxWidth: 1000, margin: '0 auto' }}>
        <div>
          <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.18em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Where your money sits</div>
          <h1 className="r-serif" style={{ fontSize: 'var(--r-fz-h1)', letterSpacing: '-0.025em', margin: '6px 0 0', lineHeight: 1.05 }}>
            One in three rupees is in <span style={{ color: 'var(--r-fix)' }}>bank stocks</span>.
          </h1>
          <p style={{ fontSize: 16, color: 'var(--r-ink-2)', marginTop: 14, lineHeight: 1.55, maxWidth: 560 }}>
            That's a lot. If banks have a rough year, more than a third of your money has a rough year too. The safer maximum is about 25%.
          </p>
        </div>

        <div className="r-card" style={{ marginTop: 28, padding: 32, display: 'grid', gridTemplateColumns: '240px 1fr', gap: 36, alignItems: 'center' }}>
          <NVRDonut size={230} segs={segs} />
          <div>
            <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Breakdown</div>
            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
              {segs.map((s) => (
                <div key={s.l} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ width: 14, height: 14, borderRadius: 4, background: s.c }} />
                  <span style={{ fontSize: 15, color: s.warn ? 'var(--r-fix)' : 'var(--r-ink)' }}>{s.l}</span>
                  {s.warn && <span className="r-pill r-pill-fix" style={{ fontSize: 10, padding: '2px 8px' }}>Too much</span>}
                  <span className="r-num" style={{ marginLeft: 'auto', fontSize: 16, fontWeight: 500 }}>{s.v}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* the fix */}
        <div className="r-card" style={{ marginTop: 18, padding: 28, background: 'var(--r-good-soft)', borderColor: 'var(--r-good-line)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 28, height: 28, borderRadius: '50%', background: 'var(--r-good)', color: 'var(--r-bg-1)', display: 'grid', placeItems: 'center', fontSize: 14 }}>✓</span>
            <span className="r-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--r-good)' }}>EASY FIX</span>
          </div>
          <div className="r-serif" style={{ fontSize: 'var(--r-fz-h2)', letterSpacing: '-0.02em', marginTop: 12, lineHeight: 1.3 }}>
            Sell ₹74,000 of HDFC Bank. Buy something more mixed.
          </div>
          <div style={{ fontSize: 14, color: 'var(--r-ink-2)', marginTop: 8, lineHeight: 1.5, maxWidth: 560 }}>
            HDFC Bank is your biggest single holding. Trimming it brings banks down to a safer 24%. We'll show you exactly what to buy instead.
          </div>
          <button className="r-btn r-btn-good" style={{ marginTop: 18 }}>Try this fix →</button>
        </div>
      </main>
    </div>
  );
}

function NVRWhereMobile() {
  const segs = [
    { l: 'Banks', v: 32, c: 'var(--r-fix)', warn: true },
    { l: 'Tech', v: 22, c: 'var(--r-info)' },
    { l: 'Energy', v: 14, c: 'var(--r-watch)' },
    { l: 'Everyday', v: 11, c: 'var(--r-good)' },
    { l: 'Medicines', v: 9, c: '#A479C9' },
    { l: 'Others', v: 12, c: '#7A8298' },
  ];
  return (
    <div className="r-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="r-notch"></span>
      <div className="r-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '8px 22px 14px' }}>
        <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Where it sits</div>
        <div className="r-serif" style={{ fontSize: 22, marginTop: 4, lineHeight: 1.1 }}>1 in 3 rupees in <span style={{ color: 'var(--r-fix)' }}>banks</span></div>
      </div>

      <div style={{ padding: '0 22px 14px', flex: 1, overflow: 'hidden' }}>
        <div className="r-card" style={{ padding: 20, textAlign: 'center', marginBottom: 12 }}>
          <NVRDonut size={150} segs={segs} />
          <div className="r-pill r-pill-fix" style={{ marginTop: 12 }}>Too much in banks</div>
        </div>

        <div className="r-card" style={{ padding: 14, marginBottom: 12 }}>
          {segs.map((s) => (
            <div key={s.l} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderTop: s !== segs[0] ? '1px solid var(--r-line)' : 'none' }}>
              <span style={{ width: 11, height: 11, borderRadius: 3, background: s.c }} />
              <span style={{ fontSize: 13.5, color: s.warn ? 'var(--r-fix)' : 'var(--r-ink)' }}>{s.l}</span>
              <span className="r-num" style={{ marginLeft: 'auto', fontSize: 13, fontWeight: 500 }}>{s.v}%</span>
            </div>
          ))}
        </div>

        <div className="r-card" style={{ background: 'var(--r-good-soft)', borderColor: 'var(--r-good-line)', padding: 16 }}>
          <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-good)', letterSpacing: '.12em' }}>● EASY FIX</div>
          <div className="r-serif" style={{ fontSize: 17, marginTop: 6, lineHeight: 1.3 }}>Sell ₹74k of HDFC Bank. Buy something more mixed.</div>
          <button className="r-btn r-btn-good" style={{ width: '100%', justifyContent: 'center', marginTop: 12, padding: '12px', fontSize: 13.5 }}>Try this fix →</button>
        </div>
      </div>

      <NVRBottomTabs active="more" />
      <div className="r-homebar"></div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════
// 04 · MY GOALS
// ════════════════════════════════════════════════════════════
function NVRGoalsDesktop() {
  const goals = [
    { icon: '🏠', name: 'Home down payment', when: '2029', need: '40 L', have: '35 L', pct: 88, save: '12,400', c: 'good', msg: 'Almost there!' },
    { icon: '🎓', name: 'Daughter\u2019s college', when: '2034', need: '85 L', have: '34 L', pct: 41, save: '7,200', c: 'watch', msg: 'Add ₹4,000/mo to catch up' },
    { icon: '🌴', name: 'Retirement', when: '2046', need: '4.2 Cr', have: '2.6 Cr', pct: 62, save: '18,500', c: 'good', msg: 'On track for 2046' },
    { icon: '🆘', name: 'Emergency fund', when: 'Ready', need: '6 L', have: '6 L', pct: 100, save: '0', c: 'good', msg: 'Done — 6 months of expenses' },
  ];
  return (
    <div className="r-frame" style={{ width: '100%', minHeight: 900, display: 'flex' }}>
      <NVRSidebar active="goals" />
      <main style={{ flex: 1, padding: '36px 56px 40px', maxWidth: 1000, margin: '0 auto' }}>
        <div>
          <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.18em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>My goals</div>
          <h1 className="r-serif" style={{ fontSize: 'var(--r-fz-h1)', letterSpacing: '-0.025em', margin: '6px 0 0', lineHeight: 1.05 }}>What you're saving for.</h1>
          <p style={{ fontSize: 16, color: 'var(--r-ink-2)', marginTop: 12, lineHeight: 1.55, maxWidth: 560 }}>
            Three of your goals are on track. One needs a little nudge.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16, marginTop: 24 }}>
          {goals.map((g) => (
            <div key={g.name} className="r-card" style={{ padding: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                <span style={{ fontSize: 36, lineHeight: 1 }}>{g.icon}</span>
                <div style={{ flex: 1 }}>
                  <div className="r-serif" style={{ fontSize: 22, letterSpacing: '-0.02em' }}>{g.name}</div>
                  <div className="r-mono" style={{ fontSize: 11, color: 'var(--r-ink-3)', letterSpacing: '.06em', textTransform: 'uppercase', marginTop: 2 }}>
                    By {g.when} · need ₹{g.need}
                  </div>
                </div>
                <span className={`r-pill r-pill-${g.c}`} style={{ fontSize: 11 }}>
                  <span className="r-dot" style={{ background: `var(--r-${g.c})` }} />{g.pct}%
                </span>
              </div>

              <div style={{ marginTop: 18 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span className="r-num" style={{ fontSize: 13, color: 'var(--r-ink-2)' }}>₹{g.have} saved</span>
                  <span className="r-num" style={{ fontSize: 13, color: 'var(--r-ink-3)' }}>of ₹{g.need}</span>
                </div>
                <div style={{ height: 10, background: 'var(--r-bg-2)', borderRadius: 5, overflow: 'hidden' }}>
                  <div style={{ width: `${g.pct}%`, height: '100%', background: `var(--r-${g.c})`, borderRadius: 5 }} />
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--r-line)' }}>
                <span style={{ fontSize: 13.5, color: g.c === 'watch' ? 'var(--r-watch)' : 'var(--r-good)' }}>{g.msg}</span>
                <span className="r-mono r-num" style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--r-ink-3)' }}>
                  {g.save !== '0' ? `₹${g.save}/mo` : '—'}
                </span>
              </div>
            </div>
          ))}
        </div>

        <button className="r-btn" style={{ marginTop: 18 }}>＋ Add a goal</button>
      </main>
    </div>
  );
}

function NVRGoalsMobile() {
  const goals = [
    { icon: '🏠', name: 'Home', pct: 88, c: 'good', msg: 'Almost there!' },
    { icon: '🎓', name: 'College', pct: 41, c: 'watch', msg: 'Add ₹4k/mo' },
    { icon: '🌴', name: 'Retirement', pct: 62, c: 'good', msg: 'On track' },
    { icon: '🆘', name: 'Emergency fund', pct: 100, c: 'good', msg: 'Done' },
  ];
  return (
    <div className="r-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="r-notch"></span>
      <div className="r-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '8px 22px 14px' }}>
        <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>My goals</div>
        <div className="r-serif" style={{ fontSize: 22, marginTop: 4 }}>What you're saving for</div>
      </div>

      <div style={{ padding: '0 22px 14px', flex: 1, overflow: 'hidden' }}>
        {goals.map((g) => (
          <div key={g.name} className="r-card" style={{ padding: 14, marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: 26 }}>{g.icon}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 15, fontWeight: 500 }}>{g.name}</div>
                <div style={{ fontSize: 12.5, color: g.c === 'watch' ? 'var(--r-watch)' : 'var(--r-good)', marginTop: 2 }}>{g.msg}</div>
              </div>
              <div className="r-num" style={{ fontSize: 18, fontWeight: 500, color: `var(--r-${g.c})` }}>{g.pct}%</div>
            </div>
            <div style={{ height: 6, background: 'var(--r-bg-2)', borderRadius: 3, marginTop: 10, overflow: 'hidden' }}>
              <div style={{ width: `${g.pct}%`, height: '100%', background: `var(--r-${g.c})`, borderRadius: 3 }} />
            </div>
          </div>
        ))}
        <button className="r-btn" style={{ width: '100%', justifyContent: 'center', marginTop: 4, padding: '12px', fontSize: 13.5 }}>＋ Add a goal</button>
      </div>

      <NVRBottomTabs active="goals" />
      <div className="r-homebar"></div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════
// 05 · FIX THIS  (one big action at a time)
// ════════════════════════════════════════════════════════════
function NVRFixDesktop() {
  const actions = [
    { n: '1', title: 'Trim bank stocks', desc: 'Sell some HDFC Bank. You\u2019ll bring banks from 32% to 24%.', gain: '₹3,500 / year safer', why: 'Less risk if banks have a bad year.', c: 'fix', big: true },
    { n: '2', title: 'Move idle savings to a liquid fund', desc: 'Earn 6.8% instead of 3.5%. Same one-day access.', gain: '₹800 / month extra', why: 'Idle money earns more.', c: 'watch' },
    { n: '3', title: 'Save tax before March 31', desc: 'We can offset ₹38,400 of losses. You save ₹11,520 in tax.', gain: '₹11,520 saved', why: 'Tax-loss harvesting.', c: 'good' },
  ];
  return (
    <div className="r-frame" style={{ width: '100%', minHeight: 900, display: 'flex' }}>
      <NVRSidebar active="fix" />
      <main style={{ flex: 1, padding: '36px 56px 40px', maxWidth: 1000, margin: '0 auto' }}>
        <div>
          <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.18em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Fix this</div>
          <h1 className="r-serif" style={{ fontSize: 'var(--r-fz-h1)', letterSpacing: '-0.025em', margin: '6px 0 0', lineHeight: 1.05 }}>3 simple things, ranked by ₹.</h1>
          <p style={{ fontSize: 16, color: 'var(--r-ink-2)', marginTop: 12, lineHeight: 1.55, maxWidth: 560 }}>
            Tap any one to start. We'll show you what happens before you commit — nothing moves without your tap.
          </p>
        </div>

        <div style={{ marginTop: 28, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {actions.map((a) => (
            <div key={a.n} className="r-card" style={{ padding: a.big ? 32 : 26, display: 'grid', gridTemplateColumns: a.big ? '50px 1fr 220px' : '40px 1fr 180px', gap: 24, alignItems: 'center', borderColor: a.big ? 'var(--r-fix-line)' : 'var(--r-line)' }}>
              <div style={{
                width: a.big ? 50 : 40, height: a.big ? 50 : 40,
                borderRadius: a.big ? 16 : 12,
                background: `var(--r-${a.c}-soft)`,
                color: `var(--r-${a.c})`,
                display: 'grid', placeItems: 'center',
                fontFamily: 'var(--r-display)', fontSize: a.big ? 26 : 22,
              }}>{a.n}</div>
              <div>
                <div className="r-serif" style={{ fontSize: a.big ? 26 : 22, letterSpacing: '-0.02em', lineHeight: 1.25 }}>{a.title}</div>
                <div style={{ fontSize: 14.5, color: 'var(--r-ink-2)', marginTop: 8, lineHeight: 1.5 }}>{a.desc}</div>
                <div className="r-mono" style={{ fontSize: 11, color: 'var(--r-ink-3)', letterSpacing: '.04em', marginTop: 10, textTransform: 'uppercase' }}>WHY · {a.why}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div className="r-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>You get</div>
                <div className="r-serif r-num" style={{ fontSize: a.big ? 26 : 22, color: 'var(--r-good)', marginTop: 4, letterSpacing: '-0.02em' }}>{a.gain}</div>
                <button className={a.big ? 'r-btn r-btn-good' : 'r-btn'} style={{ marginTop: 12 }}>
                  Try this →
                </button>
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function NVRFixMobile() {
  return (
    <div className="r-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="r-notch"></span>
      <div className="r-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '8px 22px 14px' }}>
        <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Fix this</div>
        <div className="r-serif" style={{ fontSize: 22, marginTop: 4, lineHeight: 1.1 }}>3 simple things</div>
      </div>

      <div style={{ padding: '0 22px 14px', flex: 1, overflow: 'hidden' }}>
        {[
          { n: 1, t: 'Trim bank stocks', d: 'Sell some HDFC Bank.', g: '₹3,500/yr safer', c: 'fix', big: true },
          { n: 2, t: 'Move idle savings', d: 'To a liquid fund.', g: '₹800/mo extra', c: 'watch' },
          { n: 3, t: 'Save tax · Mar 31', d: 'Offset losses.', g: '₹11,520 saved', c: 'good' },
        ].map((a) => (
          <div key={a.n} className="r-card" style={{ padding: 14, marginBottom: 10, borderColor: a.big ? `var(--r-${a.c}-line)` : 'var(--r-line)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ width: 32, height: 32, borderRadius: 10, background: `var(--r-${a.c}-soft)`, color: `var(--r-${a.c})`, display: 'grid', placeItems: 'center', fontFamily: 'var(--r-display)', fontSize: 17 }}>{a.n}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 15, fontWeight: 500 }}>{a.t}</div>
                <div style={{ fontSize: 12, color: 'var(--r-ink-2)', marginTop: 2 }}>{a.d}</div>
              </div>
              <div className="r-num" style={{ fontSize: 12.5, color: 'var(--r-good)', textAlign: 'right' }}>{a.g}</div>
            </div>
            <button className={a.big ? 'r-btn r-btn-good' : 'r-btn'} style={{ width: '100%', justifyContent: 'center', marginTop: 10, padding: '11px', fontSize: 13 }}>Try this →</button>
          </div>
        ))}
      </div>

      <NVRBottomTabs active="fix" />
      <div className="r-homebar"></div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════
// 06 · CUSTOMIZE / PROFILE
// ════════════════════════════════════════════════════════════
function NVRSettingsDesktop() {
  return (
    <div className="r-frame" style={{ width: '100%', minHeight: 900, display: 'flex' }}>
      <NVRSidebar active="" />
      <main style={{ flex: 1, padding: '36px 56px 40px', maxWidth: 1000, margin: '0 auto' }}>
        <div>
          <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.18em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Make it yours</div>
          <h1 className="r-serif" style={{ fontSize: 'var(--r-fz-h1)', letterSpacing: '-0.025em', margin: '6px 0 0', lineHeight: 1.05 }}>Customize how Nivesh feels.</h1>
          <p style={{ fontSize: 16, color: 'var(--r-ink-2)', marginTop: 12, lineHeight: 1.55, maxWidth: 560 }}>
            Pick a look, choose your language, set the text size. It saves automatically.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16, marginTop: 28 }}>
          {/* Theme */}
          <div className="r-card">
            <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Look & feel</div>
            <div className="r-serif" style={{ fontSize: 22, letterSpacing: '-0.02em', marginTop: 8 }}>Theme</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginTop: 16 }}>
              {[
                { k: 'paper', l: 'Paper · warm', sw: ['#F6F1E5', '#1A2540', '#5B8F6E'], active: true },
                { k: 'white', l: 'White · clean', sw: ['#FFFFFF', '#14181E', '#5B8F6E'] },
                { k: 'dusk', l: 'Dusk · dark', sw: ['#14171F', '#F4F1EA', '#5B8F6E'] },
              ].map((t) => (
                <div key={t.k} style={{
                  padding: 12, borderRadius: 12,
                  background: t.active ? 'var(--r-good-soft)' : 'var(--r-bg-2)',
                  border: `1px solid ${t.active ? 'var(--r-good-line)' : 'var(--r-line)'}`,
                  cursor: 'pointer', position: 'relative',
                }}>
                  <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
                    {t.sw.map((c, i) => <span key={i} style={{ flex: 1, height: 32, borderRadius: 6, background: c, border: '1px solid rgba(0,0,0,0.05)' }} />)}
                  </div>
                  <div style={{ fontSize: 12.5, fontWeight: 500 }}>{t.l}</div>
                  {t.active && <span style={{ position: 'absolute', top: 8, right: 8, width: 18, height: 18, borderRadius: '50%', background: 'var(--r-good)', color: 'var(--r-bg-1)', display: 'grid', placeItems: 'center', fontSize: 11 }}>✓</span>}
                </div>
              ))}
            </div>

            <div style={{ marginTop: 22 }}>
              <div className="r-serif" style={{ fontSize: 18, letterSpacing: '-0.02em' }}>Accent color</div>
              <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
                {[
                  { l: 'Sage', c: '#5B8F6E', active: true },
                  { l: 'Coral', c: '#D26952' },
                  { l: 'Indigo', c: '#4A5FB5' },
                  { l: 'Saffron', c: '#D2891A' },
                ].map((a) => (
                  <div key={a.l} style={{ textAlign: 'center', cursor: 'pointer' }}>
                    <div style={{
                      width: 38, height: 38, borderRadius: '50%',
                      background: a.c,
                      border: a.active ? '3px solid var(--r-bg)' : '3px solid transparent',
                      outline: a.active ? `2px solid ${a.c}` : 'none',
                      margin: '0 auto',
                    }} />
                    <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', marginTop: 6, letterSpacing: '.06em' }}>{a.l}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Density */}
          <div className="r-card">
            <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Comfort</div>
            <div className="r-serif" style={{ fontSize: 22, letterSpacing: '-0.02em', marginTop: 8 }}>Text size</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginTop: 16 }}>
              {[
                { k: 'default', l: 'Default', s: 16 },
                { k: 'large', l: 'Large', s: 19, active: true },
                { k: 'x-large', l: 'X-large', s: 22 },
              ].map((s) => (
                <div key={s.k} style={{
                  padding: 14, borderRadius: 12, textAlign: 'center', cursor: 'pointer',
                  background: s.active ? 'var(--r-good-soft)' : 'var(--r-bg-2)',
                  border: `1px solid ${s.active ? 'var(--r-good-line)' : 'var(--r-line)'}`,
                }}>
                  <div style={{ fontFamily: 'var(--r-display)', fontSize: s.s }}>Aa</div>
                  <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', marginTop: 4, letterSpacing: '.06em' }}>{s.l.toUpperCase()}</div>
                </div>
              ))}
            </div>

            <div style={{ marginTop: 22 }}>
              <div className="r-serif" style={{ fontSize: 18, letterSpacing: '-0.02em' }}>Spacing</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginTop: 12 }}>
                {[['Cozy', 'cozy'], ['Comfortable', 'comfortable', true], ['Spacious', 'spacious']].map(([l, k, active]) => (
                  <div key={k} style={{
                    padding: '12px 10px', borderRadius: 10, textAlign: 'center',
                    background: active ? 'var(--r-good-soft)' : 'var(--r-bg-2)',
                    border: `1px solid ${active ? 'var(--r-good-line)' : 'var(--r-line)'}`,
                    fontSize: 12.5, fontWeight: active ? 500 : 400,
                  }}>{l}</div>
                ))}
              </div>
            </div>
          </div>

          {/* Language */}
          <div className="r-card">
            <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Language</div>
            <div className="r-serif" style={{ fontSize: 22, letterSpacing: '-0.02em', marginTop: 8 }}>Speak to me in</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 16 }}>
              {[
                { l: 'English', s: 'How your money is doing.', active: true },
                { l: 'हिन्दी (Hindi)', s: 'आपका पैसा कैसा चल रहा है।' },
                { l: 'Hinglish', s: 'Aapka paisa kaisa chal raha hai.' },
              ].map((lng) => (
                <div key={lng.l} style={{
                  padding: '14px 16px', borderRadius: 12, cursor: 'pointer',
                  background: lng.active ? 'var(--r-good-soft)' : 'var(--r-bg-2)',
                  border: `1px solid ${lng.active ? 'var(--r-good-line)' : 'var(--r-line)'}`,
                  display: 'flex', alignItems: 'center',
                }}>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>{lng.l}</div>
                    <div className="r-serif" style={{ fontSize: 15, color: 'var(--r-ink-2)', marginTop: 2, fontStyle: 'italic' }}>{lng.s}</div>
                  </div>
                  {lng.active && <span style={{ marginLeft: 'auto', width: 18, height: 18, borderRadius: '50%', background: 'var(--r-good)', color: 'var(--r-bg-1)', display: 'grid', placeItems: 'center', fontSize: 11 }}>✓</span>}
                </div>
              ))}
            </div>
          </div>

          {/* Notifications */}
          <div className="r-card">
            <div className="r-mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--r-ink-3)', textTransform: 'uppercase' }}>Reminders</div>
            <div className="r-serif" style={{ fontSize: 22, letterSpacing: '-0.02em', marginTop: 8 }}>Tell me when…</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 14 }}>
              {[
                { l: 'A goal needs a top-up', on: true },
                { l: 'Tax-saving window opens', on: true },
                { l: 'My SIP runs each month', on: false },
                { l: 'Daily money update', on: false },
              ].map((s) => (
                <div key={s.l} style={{ display: 'flex', alignItems: 'center', padding: '10px 4px', borderBottom: '1px solid var(--r-line)' }}>
                  <span style={{ fontSize: 14 }}>{s.l}</span>
                  <span style={{
                    marginLeft: 'auto',
                    width: 36, height: 22, borderRadius: 11,
                    background: s.on ? 'var(--r-good)' : 'var(--r-bg-3)',
                    position: 'relative',
                  }}>
                    <span style={{
                      position: 'absolute', top: 2, [s.on ? 'right' : 'left']: 2,
                      width: 18, height: 18, borderRadius: '50%',
                      background: 'var(--r-bg-1)',
                    }} />
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function NVRSettingsMobile() {
  return (
    <div className="r-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="r-notch"></span>
      <div className="r-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '8px 22px 14px' }}>
        <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Make it yours</div>
        <div className="r-serif" style={{ fontSize: 22, marginTop: 4 }}>Customize</div>
      </div>

      <div style={{ padding: '0 22px 14px', flex: 1, overflow: 'hidden' }}>
        <div className="r-card" style={{ padding: 14, marginBottom: 10 }}>
          <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>Theme</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            {[
              { l: 'Paper', s: ['#F6F1E5', '#1A2540'], on: true },
              { l: 'White', s: ['#FFFFFF', '#14181E'] },
              { l: 'Dusk', s: ['#14171F', '#F4F1EA'] },
            ].map((t) => (
              <div key={t.l} style={{ flex: 1, padding: 10, borderRadius: 10, background: t.on ? 'var(--r-good-soft)' : 'var(--r-bg-2)', border: `1px solid ${t.on ? 'var(--r-good-line)' : 'var(--r-line)'}`, textAlign: 'center' }}>
                <div style={{ display: 'flex', gap: 3, marginBottom: 6 }}>
                  {t.s.map((c, i) => <span key={i} style={{ flex: 1, height: 22, borderRadius: 4, background: c }} />)}
                </div>
                <div style={{ fontSize: 11.5, fontWeight: 500 }}>{t.l}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="r-card" style={{ padding: 14, marginBottom: 10 }}>
          <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>Accent</div>
          <div style={{ display: 'flex', gap: 14, marginTop: 12, justifyContent: 'space-around' }}>
            {['#5B8F6E', '#D26952', '#4A5FB5', '#D2891A'].map((c, i) => (
              <div key={c} style={{ width: 34, height: 34, borderRadius: '50%', background: c, border: i === 0 ? '3px solid var(--r-bg-1)' : 'none', outline: i === 0 ? `2px solid ${c}` : 'none' }} />
            ))}
          </div>
        </div>

        <div className="r-card" style={{ padding: 14, marginBottom: 10 }}>
          <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>Text size</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            {[
              { l: 'A', s: 14 }, { l: 'A', s: 18, on: true }, { l: 'A', s: 24 },
            ].map((s, i) => (
              <div key={i} style={{ flex: 1, padding: '10px 0', borderRadius: 10, background: s.on ? 'var(--r-good-soft)' : 'var(--r-bg-2)', border: `1px solid ${s.on ? 'var(--r-good-line)' : 'var(--r-line)'}`, textAlign: 'center' }}>
                <span style={{ fontFamily: 'var(--r-display)', fontSize: s.s }}>{s.l}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="r-card" style={{ padding: 14 }}>
          <div className="r-mono" style={{ fontSize: 10, color: 'var(--r-ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>Language</div>
          {['English', 'हिन्दी', 'Hinglish'].map((l, i) => (
            <div key={l} style={{ display: 'flex', alignItems: 'center', padding: '11px 0', borderTop: i > 0 ? '1px solid var(--r-line)' : 'none' }}>
              <span style={{ fontSize: 14 }}>{l}</span>
              {i === 0 && <span style={{ marginLeft: 'auto', width: 18, height: 18, borderRadius: '50%', background: 'var(--r-good)', color: 'var(--r-bg-1)', display: 'grid', placeItems: 'center', fontSize: 11 }}>✓</span>}
            </div>
          ))}
        </div>
      </div>

      <NVRBottomTabs active="more" />
      <div className="r-homebar"></div>
    </div>
  );
}

Object.assign(window, {
  NVRTodayDesktop, NVRTodayMobile,
  NVRHealthDesktop, NVRHealthMobile,
  NVRWhereDesktop, NVRWhereMobile,
  NVRGoalsDesktop, NVRGoalsMobile,
  NVRFixDesktop, NVRFixMobile,
  NVRSettingsDesktop, NVRSettingsMobile,
});
