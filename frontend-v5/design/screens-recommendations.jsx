// ─── Nivesh · Recommendations — desktop + mobile ───
// Ranked actions · each card has a what-if simulator

function NVImpactBar({ before = 86, after = 92, max = 100 }) {
  return (
    <svg viewBox="0 0 200 32" style={{ width: '100%', height: 32 }}>
      <rect x="0" y="14" width="200" height="4" rx="2" fill="var(--bg-3)" />
      <rect x="0" y="14" width={(after / max) * 200} height="4" rx="2" fill="var(--mint)" opacity=".25" />
      <rect x="0" y="14" width={(before / max) * 200} height="4" rx="2" fill="var(--ink-3)" />
      <circle cx={(before / max) * 200} cy="16" r="6" fill="var(--bg-0)" stroke="var(--ink-3)" strokeWidth="2" />
      <circle cx={(after / max) * 200} cy="16" r="7" fill="var(--mint)" stroke="var(--bg-0)" strokeWidth="2" />
      <text x={(before / max) * 200} y="8" textAnchor="middle" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">{before}</text>
      <text x={(after / max) * 200} y="30" textAnchor="middle" fontFamily="var(--mono)" fontSize="10" fill="var(--mint)" fontWeight="600">{after}</text>
    </svg>
  );
}

function NVRecCard({ rank, sev, headline, why, ticker, action, impact, savings, after, large = false }) {
  return (
    <div className="nv-card" style={{ padding: large ? '24px 24px' : '18px 20px', position: 'relative', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
        <div style={{ width: 40, height: 40, borderRadius: 11, background: `var(--${sev}-soft)`, border: `1px solid var(--${sev}-line)`, color: `var(--${sev})`, display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)', fontSize: 13, fontWeight: 500, flex: 'none' }}>
          {rank}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="nv-serif" style={{ fontSize: large ? 24 : 19, letterSpacing: '-0.02em', lineHeight: 1.25 }}>{headline}</div>
          <div style={{ fontSize: 13, color: 'var(--ink-2)', marginTop: 8, lineHeight: 1.5 }}>{why}</div>
        </div>
        <span className="nv-pill" style={{ fontSize: 9, color: 'var(--ink-3)' }}>{ticker}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1fr 1fr', gap: 16, marginTop: 18, padding: '14px 0 4px', borderTop: '1px solid var(--line)' }}>
        <div>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Suggested move</div>
          <div style={{ fontSize: 14, fontWeight: 500, marginTop: 4 }}>{action}</div>
        </div>
        <div>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Health score</div>
          <div style={{ marginTop: 2 }}>
            <NVImpactBar before={86} after={after} />
          </div>
        </div>
        <div>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>₹ impact / yr</div>
          <div className="nv-serif nv-num" style={{ fontSize: 26, color: 'var(--mint)', marginTop: 2, letterSpacing: '-0.025em' }}>{savings}</div>
          <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 2, letterSpacing: '.04em' }}>{impact}</div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
        <button className="nv-btn nv-btn-primary" style={{ padding: '8px 14px', fontSize: 12 }}>Simulate</button>
        <button className="nv-btn" style={{ padding: '8px 14px', fontSize: 12 }}>Add to plan</button>
        <button className="nv-btn" style={{ padding: '8px 14px', fontSize: 12 }}>↗ Why</button>
        <button className="nv-btn" style={{ marginLeft: 'auto', padding: '8px 11px', fontSize: 12, color: 'var(--ink-3)' }}>Dismiss</button>
      </div>
    </div>
  );
}

function NVRecommendationsDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVSidebar active="overview" />
      <main style={{ flex: 1, padding: '24px 36px 32px', maxWidth: 1200, margin: '0 auto', overflow: 'hidden' }}>
        {/* header */}
        <div style={{ display: 'flex', alignItems: 'flex-end', marginBottom: 20 }}>
          <div>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Recommendations · ranked by ₹ impact</div>
            <h1 className="nv-serif" style={{ fontSize: 38, letterSpacing: '-0.025em', margin: '4px 0 0', lineHeight: 1.05 }}>
              Six moves to take you from 86 to <span style={{ color: 'var(--mint)' }}>94</span>.
            </h1>
            <p style={{ fontSize: 14, color: 'var(--ink-2)', marginTop: 10, maxWidth: 520, lineHeight: 1.55 }}>
              Run any move as a simulation first. Add the ones you like to your plan; we'll batch the execution and never trade without your nod.
            </p>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button className="nv-btn" style={{ padding: '9px 14px', fontSize: 13 }}>Filters</button>
            <button className="nv-btn nv-btn-primary" style={{ padding: '9px 14px', fontSize: 13 }}>Add all to plan</button>
          </div>
        </div>

        {/* projection bar */}
        <div className="nv-card" style={{ padding: '18px 22px', marginBottom: 22, display: 'grid', gridTemplateColumns: '1fr 240px 1fr 200px', gap: 18, alignItems: 'center' }}>
          <div>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Today</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
              <span className="nv-serif nv-num" style={{ fontSize: 48, letterSpacing: '-0.035em' }}>86</span>
              <span className="nv-pill nv-pill-mint">GRADE A</span>
            </div>
            <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 2 }}>21 risks open · 6 actionable</div>
          </div>
          <div style={{ position: 'relative' }}>
            <svg viewBox="0 0 220 60" style={{ width: '100%', height: 60 }}>
              <defs>
                <linearGradient id="proj-g" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0" stopColor="var(--ink-3)" />
                  <stop offset="1" stopColor="var(--mint)" />
                </linearGradient>
              </defs>
              <path d="M0,42 Q60,38 110,28 T220,8" fill="none" stroke="url(#proj-g)" strokeWidth="2.5" strokeLinecap="round" />
              {[0, 1, 2, 3, 4, 5, 6].map((i) => (
                <circle key={i} cx={i * 36 + 4} cy={42 - i * 5.5} r="3" fill="var(--mint)" opacity={0.3 + i * 0.1} />
              ))}
              <text x="4" y="58" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">now</text>
              <text x="216" y="58" textAnchor="end" fontFamily="var(--mono)" fontSize="9" fill="var(--mint)">+6 moves</text>
            </svg>
          </div>
          <div>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>If you act</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
              <span className="nv-serif nv-num" style={{ fontSize: 48, color: 'var(--mint)', letterSpacing: '-0.035em' }}>94</span>
              <span className="nv-mono" style={{ fontSize: 12, color: 'var(--mint)' }}>+8 pt</span>
            </div>
            <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 2 }}>est. ₹68,500 / year saved</div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <button className="nv-btn nv-btn-primary" style={{ padding: '10px', justifyContent: 'center', fontSize: 13 }}>Simulate all 6 →</button>
            <button className="nv-btn" style={{ padding: '8px', justifyContent: 'center', fontSize: 11.5 }}>Export PDF</button>
          </div>
        </div>

        {/* filter pills */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 14, alignItems: 'center' }}>
          <span className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginRight: 6 }}>Filter</span>
          {['All · 6', 'Concentration · 2', 'Cost · 1', 'Tax · 1', 'Diversification · 1', 'Goals · 1'].map((t, i) => (
            <span key={t} style={{ fontSize: 11.5, padding: '5px 10px', borderRadius: 999, background: i === 0 ? 'var(--bg-2)' : 'transparent', border: `1px solid var(--${i === 0 ? 'line-2' : 'line'})`, color: i === 0 ? 'var(--ink)' : 'var(--ink-3)', cursor: 'pointer' }}>{t}</span>
          ))}
          <span style={{ marginLeft: 'auto', fontSize: 11.5, color: 'var(--ink-3)' }}>Sort · ₹ impact ↓</span>
        </div>

        {/* recs */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <NVRecCard rank="01" sev="amber" large headline="Trim HDFC Bank from 8.0% to 5.0%"
            why="You're 3pt over the single-stock cap and 7pt over the financials sector cap. ICICI overlaps 0.86 with HDFC — selling one alone meaningfully reduces correlated risk."
            ticker="HDFCBANK" action="Sell ₹74,250 — buy Nifty Next 50" impact="cap·risk·diversification" savings="+₹0.42 L" after={92}
          />
          <NVRecCard rank="02" sev="indigo"
            headline="Consolidate three large-cap funds with 71% stock overlap"
            why="Axis Bluechip, ICICI Pru Bluechip and Mirae Large all hold the same top 25 names. You're paying 3× expense ratio for 1× exposure."
            ticker="3 FUNDS" action="Move Axis + Mirae → Parag Parikh Flexi" impact="cost · ₹14k/yr" savings="+₹14,200" after={89}
          />
          <NVRecCard rank="03" sev="mint"
            headline="Harvest ₹38,400 of short-term loss before March 31"
            why="Three lots are sitting at -₹38k unrealised; selling and rebuying after 31 days lets you offset other gains. We'll set the reminder."
            ticker="3 LOTS" action="Sell · auto rebuy day 31" impact="tax · LTCG offset" savings="+₹11,520" after={88}
          />
          <NVRecCard rank="04" sev="indigo"
            headline="Add ₹3,500 to your retirement SIP — gap closes in 22 years"
            why="At current pace you land ₹1.4Cr short of your 2046 goal. Adding ₹3.5k/mo to the existing PPFAS SIP closes 100% of that gap."
            ticker="GOAL · 2046" action="Increase SIP to ₹18,500/mo" impact="goal · retirement" savings="+₹1.4 Cr by 2046" after={87}
          />
          <NVRecCard rank="05" sev="amber"
            headline="Move ₹1.2L from savings to a money-market fund"
            why="You hold 7 months of expenses in idle savings at 3.5%. Liquid funds yield 6.8% with same-day redemption."
            ticker="CASH" action="Move to Quant Liquid Direct" impact="cash · idle drag" savings="+₹3,960" after={86.5}
          />
        </div>
      </main>
    </div>
  );
}

function NVRecommendationsMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '6px 18px 12px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ color: 'var(--ink-2)', fontSize: 18 }}>‹</span>
        <div>
          <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Plan</div>
          <div className="nv-serif" style={{ fontSize: 18, marginTop: 1 }}>Recommendations</div>
        </div>
        <span className="nv-pill nv-pill-mint" style={{ marginLeft: 'auto', fontSize: 9 }}>6 OPEN</span>
      </div>

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        {/* projection */}
        <div className="nv-card" style={{ padding: 14, marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <div>
              <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>Today</div>
              <div className="nv-serif nv-num" style={{ fontSize: 34, letterSpacing: '-0.035em' }}>86</div>
            </div>
            <svg viewBox="0 0 100 36" style={{ width: 100, height: 36, flex: 'none' }}>
              <path d="M2,30 Q30,26 50,20 T98,4" fill="none" stroke="var(--mint)" strokeWidth="2" strokeLinecap="round" />
              <circle cx="98" cy="4" r="3" fill="var(--mint)" />
            </svg>
            <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
              <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.12em', textTransform: 'uppercase' }}>If you act</div>
              <div className="nv-serif nv-num" style={{ fontSize: 34, color: 'var(--mint)', letterSpacing: '-0.035em' }}>94</div>
            </div>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--line)' }}>
            <span className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '.04em' }}>+8 PT · ₹68,500 / YR</span>
            <span style={{ fontSize: 11, color: 'var(--mint)' }}>Simulate all →</span>
          </div>
        </div>

        {/* rec cards stacked */}
        {[
          { r: '01', s: 'amber', t: 'Trim HDFC Bank · 8.0 → 5.0%', sub: 'cap · risk', v: '+₹0.42 L' },
          { r: '02', s: 'indigo', t: '3 funds · 71% overlap', sub: 'cost · fees', v: '+₹14.2 k' },
          { r: '03', s: 'mint', t: 'Harvest ₹38k loss · Mar 31', sub: 'tax · LTCG', v: '+₹11.5 k' },
          { r: '04', s: 'indigo', t: '↑ Retirement SIP by ₹3.5k', sub: 'goal · 2046', v: '+₹1.4 Cr' },
          { r: '05', s: 'amber', t: 'Move ₹1.2L to liquid fund', sub: 'cash · drag', v: '+₹3,960' },
        ].map((c) => (
          <div key={c.r} className="nv-card-2" style={{ padding: 13, marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 32, height: 32, borderRadius: 9, background: `var(--${c.s}-soft)`, border: `1px solid var(--${c.s}-line)`, color: `var(--${c.s})`, display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)', fontSize: 11, flex: 'none' }}>{c.r}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500, letterSpacing: '-0.005em' }}>{c.t}</div>
                <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.06em', textTransform: 'uppercase', marginTop: 2 }}>{c.sub}</div>
              </div>
              <div className="nv-mono nv-num" style={{ fontSize: 12, color: 'var(--mint)', textAlign: 'right' }}>{c.v}</div>
            </div>
            <div style={{ display: 'flex', gap: 5, marginTop: 10, paddingTop: 9, borderTop: '1px solid var(--line)' }}>
              <button className="nv-btn nv-btn-primary" style={{ flex: 1, justifyContent: 'center', padding: '7px', fontSize: 11.5 }}>Simulate</button>
              <button className="nv-btn" style={{ padding: '7px 10px', fontSize: 11.5 }}>Add</button>
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-around', padding: '10px 18px 22px', borderTop: '1px solid var(--line)', background: 'var(--bg-0)' }}>
        {[['◐', 'Health'], ['▢', 'Holdings'], ['＋', 'Plan', true], ['◔', 'Chat'], ['⚙', 'You']].map(([i, l, on]) => (
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

Object.assign(window, { NVRecommendationsDesktop, NVRecommendationsMobile });
