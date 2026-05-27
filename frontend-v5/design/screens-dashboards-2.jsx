// ─── Nivesh · 5 more dashboards — desktop + mobile ───
// Diversification · Risk · Performance · Goals · Tax
// Each has a purpose-fit hero chart, drill-down rail, KPI strip, detail table.

// ─── Shared dashboard chrome ───
function NVDashHeader({ kind, title, sev, kpis }) {
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 18, marginBottom: 18 }}>
        <div>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Dashboard · {kind}</div>
          <h1 className="nv-serif" style={{ fontSize: 36, letterSpacing: '-0.025em', margin: '4px 0 0', lineHeight: 1.05 }}>{title}</h1>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <div className={`nv-pill nv-pill-${sev}`}><span className="nv-dot" style={{ background: `var(--${sev})` }} />{sev === 'mint' ? 'HEALTHY' : sev === 'amber' ? 'ATTENTION' : sev === 'indigo' ? 'INFO' : 'WATCH'}</div>
          <button className="nv-btn" style={{ padding: '8px 13px', fontSize: 12 }}>↓ Export</button>
          <button className="nv-btn" style={{ padding: '8px 13px', fontSize: 12 }}>⟳ Resync</button>
          <button className="nv-btn nv-btn-primary" style={{ padding: '8px 13px', fontSize: 12 }}>Plan a move →</button>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${kpis.length}, 1fr)`, gap: 10, marginBottom: 18 }}>
        {kpis.map((m) => (
          <div key={m.l} className="nv-card" style={{ padding: '14px 16px' }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>{m.l}</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 6 }}>
              <span className="nv-serif nv-num" style={{ fontSize: 32, letterSpacing: '-0.03em', color: `var(--${m.c})` }}>{m.v}</span>
              <span style={{ fontSize: 13, color: 'var(--ink-2)' }}>{m.s}</span>
            </div>
            <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4, letterSpacing: '.04em' }}>{m.sub}</div>
          </div>
        ))}
      </div>
    </>
  );
}

function NVMobileDashHead({ tag, title, sev }) {
  return (
    <div style={{ padding: '6px 18px 12px', display: 'flex', alignItems: 'center', gap: 10 }}>
      <span style={{ color: 'var(--ink-2)', fontSize: 18 }}>‹</span>
      <div>
        <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Dashboard</div>
        <div className="nv-serif" style={{ fontSize: 18, marginTop: 1 }}>{title}</div>
      </div>
      <span className={`nv-pill nv-pill-${sev}`} style={{ marginLeft: 'auto', fontSize: 9 }}>{tag}</span>
    </div>
  );
}

function NVMobileTabs({ active = 'health' }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-around', padding: '10px 18px 22px', borderTop: '1px solid var(--line)', background: 'var(--bg-0)' }}>
      {[['◐', 'health'], ['▢', 'holdings'], ['＋', 'plan'], ['◔', 'chat'], ['⚙', 'you']].map(([i, k]) => (
        <div key={k} style={{ textAlign: 'center', color: k === active ? 'var(--mint)' : 'var(--ink-3)' }}>
          <div style={{ fontSize: 16 }}>{i}</div>
          <div className="nv-mono" style={{ fontSize: 8.5, letterSpacing: '.1em', marginTop: 2, textTransform: 'uppercase' }}>{k}</div>
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// DIVERSIFICATION — correlation matrix is the right chart
// ═══════════════════════════════════════════════════════════
function NVCorrMatrix({ scale = 1 }) {
  // 8 holdings — symmetric matrix
  const tickers = ['HDFCBK', 'ICICI', 'SBI', 'INFY', 'TCS', 'RELI', 'HUL', 'NIFTY'];
  const corr = [
    [1.00, 0.86, 0.79, 0.42, 0.38, 0.31, 0.18, 0.74],
    [0.86, 1.00, 0.82, 0.40, 0.36, 0.28, 0.16, 0.71],
    [0.79, 0.82, 1.00, 0.34, 0.31, 0.26, 0.14, 0.65],
    [0.42, 0.40, 0.34, 1.00, 0.91, 0.38, 0.22, 0.62],
    [0.38, 0.36, 0.31, 0.91, 1.00, 0.40, 0.24, 0.61],
    [0.31, 0.28, 0.26, 0.38, 0.40, 1.00, 0.30, 0.48],
    [0.18, 0.16, 0.14, 0.22, 0.24, 0.30, 1.00, 0.34],
    [0.74, 0.71, 0.65, 0.62, 0.61, 0.48, 0.34, 1.00],
  ];
  const S = 44 * scale;
  const off = 70 * scale;
  const W = off + S * 8 + 10, H = off + S * 8 + 10;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} style={{ display: 'block' }}>
      {tickers.map((t, i) => (
        <text key={`col-${t}`} x={off + i * S + S/2} y={off - 8} textAnchor="middle" fontFamily="var(--mono)" fontSize={9 * scale} fill="var(--ink-3)" letterSpacing=".05em">{t}</text>
      ))}
      {tickers.map((t, i) => (
        <text key={`row-${t}`} x={off - 8} y={off + i * S + S/2 + 3} textAnchor="end" fontFamily="var(--mono)" fontSize={9 * scale} fill="var(--ink-3)" letterSpacing=".05em">{t}</text>
      ))}
      {corr.map((row, r) => row.map((v, c) => {
        // color based on correlation magnitude (excluding diagonal)
        const diag = r === c;
        const intensity = Math.abs(v);
        const hot = v >= 0.7 && !diag; // strong positive — risky for diversification
        const fill = diag
          ? 'var(--bg-3)'
          : hot
            ? `rgba(255, 107, 122, ${0.15 + intensity * 0.6})`
            : v >= 0.5
              ? `rgba(255, 181, 71, ${0.10 + intensity * 0.35})`
              : `rgba(106, 240, 168, ${0.06 + (1-intensity) * 0.18})`;
        const stroke = (r === 0 && c === 1) || (r === 1 && c === 0) || (r === 3 && c === 4) || (r === 4 && c === 3) ? 'var(--danger)' : 'transparent';
        return (
          <g key={`${r}-${c}`}>
            <rect x={off + c * S} y={off + r * S} width={S - 2} height={S - 2} fill={fill} stroke={stroke} strokeWidth="1.5" rx="3" />
            <text x={off + c * S + S/2 - 1} y={off + r * S + S/2 + 4} textAnchor="middle" fontFamily="var(--mono)" fontSize={10 * scale}
              fill={diag ? 'var(--ink-3)' : hot ? 'var(--ink)' : 'var(--ink-2)'} fontWeight={hot ? 600 : 400}>
              {v.toFixed(2).replace('0.', '.')}
            </text>
          </g>
        );
      }))}
    </svg>
  );
}

function NVDashDiversificationDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVSidebar active="diversification" />
      <main style={{ flex: 1, padding: '24px 36px 32px', overflow: 'hidden' }}>
        <NVDashHeader kind="diversification" title="Three pairs are nearly the same trade." sev="indigo"
          kpis={[
            { l: 'Effective N', v: '11', s: 'holdings', sub: 'of 47 raw', c: 'amber' },
            { l: 'Overlap', v: '₹4.2 L', s: 'duplicated', sub: '17% of equity', c: 'indigo' },
            { l: 'Pairs > 0.85', v: '3', s: 'redundant', sub: 'target ≤ 1', c: 'amber' },
            { l: 'Avg correlation', v: '0.48', s: 'cross-book', sub: 'target ≤ 0.5', c: 'mint' },
          ]}
        />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18 }}>
          <div className="nv-card" style={{ padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Correlation matrix · 3Y</div>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                {['Stocks', 'Funds', 'Sectors', 'Factors'].map((t, i) => (
                  <span key={t} style={{ fontSize: 11, padding: '4px 9px', borderRadius: 6, background: i === 0 ? 'var(--bg-2)' : 'transparent', border: i === 0 ? '1px solid var(--line-2)' : '1px solid transparent', color: i === 0 ? 'var(--ink)' : 'var(--ink-3)' }}>{t}</span>
                ))}
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <NVCorrMatrix scale={1.05} />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--line)' }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Heat</div>
              {[
                { c: 'rgba(106, 240, 168, 0.5)', l: '< 0.5 · diversifying' },
                { c: 'rgba(255, 181, 71, 0.5)', l: '0.5–0.7 · related' },
                { c: 'rgba(255, 107, 122, 0.6)', l: '> 0.7 · redundant' },
              ].map((g) => (
                <div key={g.l} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 14, height: 14, background: g.c, borderRadius: 3 }} />
                  <span style={{ fontSize: 11.5, color: 'var(--ink-2)' }}>{g.l}</span>
                </div>
              ))}
              <span style={{ marginLeft: 'auto', fontSize: 11.5, color: 'var(--ink-3)' }}>3 pairs flagged ›</span>
            </div>
          </div>

          {/* drill panel */}
          <aside className="nv-card-2" style={{ padding: 18 }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--danger)', textTransform: 'uppercase' }}>● Redundant pair</div>
            <div className="nv-serif" style={{ fontSize: 24, letterSpacing: '-0.02em', marginTop: 6 }}>HDFC Bank ↔ ICICI</div>
            <div className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '.04em' }}>3Y · ρ 0.86 · same factor cluster</div>

            <div className="nv-card" style={{ padding: '12px 14px', marginTop: 14 }}>
              <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Co-movement · 1Y</div>
              <svg viewBox="0 0 320 80" style={{ width: '100%', height: 80, marginTop: 6 }}>
                <path d="M0,42 C30,38 50,46 80,32 C110,40 150,28 180,38 C210,30 240,42 270,32 L320,38" fill="none" stroke="var(--mint)" strokeWidth="1.6" />
                <path d="M0,46 C30,40 50,48 80,34 C110,42 150,30 180,40 C210,32 240,44 270,34 L320,40" fill="none" stroke="var(--rose)" strokeWidth="1.6" strokeDasharray="3 3" />
              </svg>
              <div style={{ display: 'flex', gap: 18, fontSize: 11 }}>
                <span><span style={{ width: 10, height: 2, background: 'var(--mint)', display: 'inline-block', marginRight: 6 }} />HDFC</span>
                <span><span style={{ width: 10, height: 1, background: 'var(--rose)', display: 'inline-block', marginRight: 6, borderBottom: '1px dashed var(--rose)' }} />ICICI</span>
              </div>
            </div>

            <div className="nv-mono" style={{ fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginTop: 16 }}>Why redundant</div>
            <ul style={{ listStyle: 'none', padding: 0, margin: '8px 0 0' }}>
              {[
                'Same sector (private bank), 0.86 corr over 3Y',
                'Move 1σ together · only 14% unique risk',
                'Selling one releases ₹1.8L for diversifying assets',
              ].map((t) => (
                <li key={t} style={{ display: 'flex', gap: 9, padding: '5px 0', fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.5 }}>
                  <span style={{ marginTop: 6, width: 4, height: 4, borderRadius: '50%', background: 'var(--danger)', flex: 'none' }} />
                  <span>{t}</span>
                </li>
              ))}
            </ul>

            <div style={{ display: 'flex', gap: 8, marginTop: 18 }}>
              <button className="nv-btn nv-btn-primary" style={{ flex: 1, justifyContent: 'center', padding: '11px', fontSize: 13 }}>Simulate · sell ICICI</button>
              <button className="nv-btn" style={{ padding: '11px 13px', fontSize: 13 }}>↗</button>
            </div>
          </aside>
        </div>

        {/* fund overlap table */}
        <div className="nv-card" style={{ padding: 18, marginTop: 16 }}>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 12 }}>Fund overlap · top 25 stocks shared</div>
          {[
            { a: 'Axis Bluechip', b: 'ICICI Pru Bluechip', o: 71, s: 'redundant' },
            { a: 'Mirae Large', b: 'ICICI Pru Bluechip', o: 68, s: 'redundant' },
            { a: 'Parag Parikh Flexi', b: 'Mirae Large', o: 41, s: 'related' },
            { a: 'Quant Small Cap', b: 'Nippon India Small', o: 28, s: 'diversifying' },
            { a: 'Mirae Tax Saver', b: 'Axis Bluechip', o: 22, s: 'diversifying' },
          ].map((r) => {
            const c = r.s === 'redundant' ? 'danger' : r.s === 'related' ? 'amber' : 'mint';
            return (
              <div key={r.a + r.b} style={{ display: 'grid', gridTemplateColumns: '1.4fr 1.4fr 1fr 110px 60px', alignItems: 'center', gap: 14, padding: '10px 0', borderTop: '1px solid var(--line)' }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{r.a}</div>
                <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink-2)' }}>↔ {r.b}</div>
                <div style={{ position: 'relative', height: 8, background: 'var(--bg-2)', borderRadius: 3 }}>
                  <div style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width: `${r.o}%`, background: `var(--${c})`, borderRadius: 3 }} />
                </div>
                <div className="nv-mono nv-num" style={{ fontSize: 13, color: `var(--${c})`, textAlign: 'right' }}>{r.o}% shared</div>
                <span style={{ color: 'var(--ink-3)', textAlign: 'right' }}>›</span>
              </div>
            );
          })}
        </div>
      </main>
    </div>
  );
}

function NVDashDiversificationMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>
      <NVMobileDashHead tag="INFO" title="Diversification" sev="indigo" />

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        <div className="nv-card" style={{ padding: 14, marginBottom: 12 }}>
          <div className="nv-serif" style={{ fontSize: 22, lineHeight: 1.15, letterSpacing: '-0.02em' }}>
            <span style={{ color: 'var(--danger)' }}>3 pairs</span> are nearly the same trade.
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <div style={{ flex: 1 }}><div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Eff. N</div><div className="nv-serif nv-num" style={{ fontSize: 22, color: 'var(--amber)' }}>11</div></div>
            <div style={{ flex: 1 }}><div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Overlap</div><div className="nv-serif nv-num" style={{ fontSize: 22, color: 'var(--indigo)' }}>₹4.2L</div></div>
            <div style={{ flex: 1 }}><div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Avg ρ</div><div className="nv-serif nv-num" style={{ fontSize: 22 }}>0.48</div></div>
          </div>
        </div>

        <div className="nv-card" style={{ padding: 10, marginBottom: 12 }}>
          <div style={{ display: 'flex', padding: '0 4px 8px' }}>
            <span className="nv-mono" style={{ fontSize: 9, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Correlation · 3Y</span>
            <span className="nv-mono" style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--danger)', letterSpacing: '.06em' }}>3 hot ●</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'center' }}>
            <NVCorrMatrix scale={0.58} />
          </div>
        </div>

        <div className="nv-card-2" style={{ padding: 12 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--danger)', textTransform: 'uppercase' }}>● Redundant</div>
          <div style={{ display: 'flex', alignItems: 'baseline', marginTop: 4 }}>
            <span className="nv-serif" style={{ fontSize: 17 }}>HDFC ↔ ICICI</span>
            <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--danger)' }}>ρ 0.86</span>
          </div>
          <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
            <button className="nv-btn nv-btn-primary" style={{ flex: 1, justifyContent: 'center', padding: '9px', fontSize: 12 }}>Simulate</button>
            <button className="nv-btn" style={{ padding: '9px 11px', fontSize: 12 }}>↗</button>
          </div>
        </div>
      </div>
      <NVMobileTabs />
      <div className="nv-homebar"></div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// RISK — drawdown + VaR fan
// ═══════════════════════════════════════════════════════════
function NVRiskFanChart() {
  return (
    <svg viewBox="0 0 720 240" style={{ width: '100%', height: 240 }}>
      <defs>
        <linearGradient id="risk-band" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--amber)" stopOpacity=".06" />
          <stop offset="1" stopColor="var(--amber)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[40, 80, 120, 160, 200].map((y) => <line key={y} x1="0" y1={y} x2="720" y2={y} stroke="var(--line)" strokeDasharray="2 4" />)}
      <text x="0" y="36" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">+15%</text>
      <text x="0" y="116" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">0</text>
      <text x="0" y="196" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">-15%</text>
      <line x1="0" y1="120" x2="720" y2="120" stroke="var(--ink-4)" strokeWidth="1" />

      {/* 95th confidence band */}
      <path d="M380,120 C440,110 500,90 560,72 C620,54 680,40 720,30 L720,210 C680,200 620,186 560,168 C500,150 440,130 380,120 Z" fill="url(#risk-band)" stroke="var(--amber)" strokeWidth="0.8" strokeDasharray="3 3" opacity=".7" />
      {/* 68th band */}
      <path d="M380,120 C440,114 500,104 560,90 C620,78 680,68 720,60 L720,180 C680,172 620,162 560,150 C500,138 440,128 380,120 Z" fill="rgba(255,181,71,0.08)" />

      {/* historical line */}
      <path d="M0,130 C40,140 80,118 120,135 C160,145 200,108 240,98 C280,115 320,138 380,120" fill="none" stroke="var(--mint)" strokeWidth="2" />
      {/* projection median */}
      <path d="M380,120 C440,112 500,98 560,82 C620,68 680,54 720,46" fill="none" stroke="var(--mint)" strokeWidth="2" strokeDasharray="4 4" />

      {/* divider */}
      <line x1="380" y1="0" x2="380" y2="220" stroke="var(--ink-4)" strokeWidth="1" strokeDasharray="2 4" />
      <text x="385" y="14" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">PROJECTION · 12M</text>

      {/* drawdown markers */}
      <circle cx="155" cy="148" r="5" fill="var(--bg-0)" stroke="var(--danger)" strokeWidth="2" />
      <text x="164" y="152" fontFamily="var(--mono)" fontSize="9" fill="var(--danger)">-8.4% drawdown · Apr</text>

      {/* worst case marker on right */}
      <circle cx="720" cy="210" r="5" fill="var(--amber)" />
      <text x="716" y="226" textAnchor="end" fontFamily="var(--mono)" fontSize="9" fill="var(--amber)">VaR(95) -12.4%</text>

      {['Nov 25', 'Feb', 'May', 'Aug', 'Nov 26', 'Feb', 'May', 'Nov 27'].map((m, i) => (
        <text key={m + i} x={i * 90 + 16} y="232" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">{m}</text>
      ))}
    </svg>
  );
}

function NVDashRiskDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVSidebar active="risk" />
      <main style={{ flex: 1, padding: '24px 36px 32px', overflow: 'hidden' }}>
        <NVDashHeader kind="risk · 12M forward" title="One bad quarter could cost ₹3.07 L." sev="amber"
          kpis={[
            { l: 'VaR · 95th, 1Y', v: '-12.4%', s: '~₹3.07L', sub: 'target ≤ -10%', c: 'amber' },
            { l: 'Volatility', v: '14.6%', s: 'σ annual', sub: 'NIFTY 13.8%', c: 'mint' },
            { l: 'Max drawdown', v: '-18%', s: 'COVID 20', sub: 'recover 14mo', c: 'indigo' },
            { l: 'Beta', v: '1.08', s: 'vs NIFTY', sub: 'target 0.9-1.1', c: 'mint' },
          ]}
        />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18 }}>
          <div className="nv-card" style={{ padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Return distribution · 1Y historical + 1Y projected</div>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 14, fontSize: 11 }}>
                <span><span style={{ width: 10, height: 2, background: 'var(--mint)', display: 'inline-block', marginRight: 6 }} />actual</span>
                <span><span style={{ width: 10, height: 0, borderBottom: '2px dashed var(--mint)', display: 'inline-block', marginRight: 6, verticalAlign: 'middle' }} />median</span>
                <span><span style={{ width: 10, height: 10, background: 'var(--amber-soft)', border: '1px dashed var(--amber)', display: 'inline-block', marginRight: 6, verticalAlign: 'middle' }} />95% band</span>
              </span>
            </div>
            <NVRiskFanChart />
          </div>

          <aside className="nv-card-2" style={{ padding: 18 }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--amber)', textTransform: 'uppercase' }}>● Top risk contributors</div>
            <div className="nv-serif" style={{ fontSize: 22, letterSpacing: '-0.02em', marginTop: 6 }}>3 sources, 67% of σ</div>

            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
              {[
                { n: 'Financials concentration', p: 38, c: 'amber' },
                { n: 'Mid-cap small-cap tilt', p: 19, c: 'amber' },
                { n: 'INR exposure (96%)', p: 10, c: 'indigo' },
                { n: 'Other (diversified)', p: 33, c: 'mint' },
              ].map((r) => (
                <div key={r.n}>
                  <div style={{ display: 'flex', fontSize: 12 }}>
                    <span>{r.n}</span>
                    <span className="nv-mono nv-num" style={{ marginLeft: 'auto', color: `var(--${r.c})` }}>{r.p}%</span>
                  </div>
                  <div style={{ height: 6, background: 'var(--bg-3)', borderRadius: 3, marginTop: 6, overflow: 'hidden' }}>
                    <div style={{ width: `${r.p}%`, height: '100%', background: `var(--${r.c})` }} />
                  </div>
                </div>
              ))}
            </div>

            <div className="nv-card" style={{ padding: '12px 14px', marginTop: 16, background: 'var(--bg-1)' }}>
              <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Stress test · 2008</div>
              <div className="nv-serif nv-num" style={{ fontSize: 24, color: 'var(--danger)', letterSpacing: '-0.025em', marginTop: 2 }}>-32.4%</div>
              <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>vs NIFTY -38.1% · ~₹8.0L</div>
            </div>

            <div style={{ display: 'flex', gap: 8, marginTop: 18 }}>
              <button className="nv-btn nv-btn-primary" style={{ flex: 1, justifyContent: 'center', padding: '11px', fontSize: 13 }}>Reduce σ → 12%</button>
              <button className="nv-btn" style={{ padding: '11px 13px', fontSize: 13 }}>↗</button>
            </div>
          </aside>
        </div>

        {/* stress scenarios table */}
        <div className="nv-card" style={{ padding: 18, marginTop: 16 }}>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 12 }}>Stress scenarios · simulated</div>
          {[
            { sc: '2008 GFC', port: -32.4, nift: -38.1, days: '14 months', c: 'danger' },
            { sc: 'COVID Mar 2020', port: -28.6, nift: -33.4, days: '8 months', c: 'danger' },
            { sc: 'Rate shock · +200bps', port: -8.2, nift: -6.4, days: '~3 months', c: 'amber' },
            { sc: 'INR -10%', port: -2.4, nift: -1.1, days: '~1 month', c: 'mint' },
            { sc: 'Oil +30%', port: -3.6, nift: -2.8, days: '~2 months', c: 'amber' },
          ].map((r) => (
            <div key={r.sc} style={{ display: 'grid', gridTemplateColumns: '1.4fr 100px 100px 1fr 60px', alignItems: 'center', gap: 14, padding: '10px 0', borderTop: '1px solid var(--line)' }}>
              <div style={{ fontSize: 13, fontWeight: 500 }}>{r.sc}</div>
              <div className="nv-mono nv-num" style={{ fontSize: 13, color: `var(--${r.c})` }}>{r.port}%</div>
              <div className="nv-mono nv-num" style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>NIFTY {r.nift}%</div>
              <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>recovery · {r.days}</div>
              <span style={{ color: 'var(--ink-3)', textAlign: 'right' }}>›</span>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function NVDashRiskMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>
      <NVMobileDashHead tag="WATCH" title="Risk" sev="amber" />

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        <div className="nv-card" style={{ padding: 14, marginBottom: 12 }}>
          <div className="nv-serif" style={{ fontSize: 21, lineHeight: 1.18, letterSpacing: '-0.02em' }}>
            One bad quarter could cost <span style={{ color: 'var(--danger)' }}>₹3.07 L</span>.
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <div style={{ flex: 1 }}>
              <div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>VaR 95</div>
              <div className="nv-serif nv-num" style={{ fontSize: 20, color: 'var(--amber)' }}>-12.4%</div>
            </div>
            <div style={{ flex: 1 }}>
              <div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Vol σ</div>
              <div className="nv-serif nv-num" style={{ fontSize: 20 }}>14.6%</div>
            </div>
            <div style={{ flex: 1 }}>
              <div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Beta</div>
              <div className="nv-serif nv-num" style={{ fontSize: 20 }}>1.08</div>
            </div>
          </div>
        </div>

        <div className="nv-card" style={{ padding: '14px 10px 10px', marginBottom: 12 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase', paddingLeft: 4 }}>Return fan · 1Y projection</div>
          <svg viewBox="0 0 320 110" style={{ width: '100%', marginTop: 4 }}>
            <line x1="0" y1="55" x2="320" y2="55" stroke="var(--ink-4)" strokeWidth="1" />
            <path d="M170,55 C200,50 240,42 280,32 L320,24 L320,86 C280,80 240,72 200,62 L170,55 Z" fill="rgba(255,181,71,.10)" stroke="var(--amber)" strokeWidth=".7" strokeDasharray="3 3" />
            <path d="M0,60 C30,64 60,52 90,58 C120,62 150,46 170,55" fill="none" stroke="var(--mint)" strokeWidth="1.6" />
            <path d="M170,55 C200,48 240,38 280,28 L320,20" fill="none" stroke="var(--mint)" strokeWidth="1.6" strokeDasharray="3 3" />
            <line x1="170" y1="0" x2="170" y2="100" stroke="var(--ink-4)" strokeDasharray="2 3" />
          </svg>
        </div>

        <div className="nv-card-2" style={{ padding: 13 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--amber)', textTransform: 'uppercase' }}>● Top risk drivers</div>
          {[
            { n: 'Financials concentration', p: 38 },
            { n: 'Mid+small cap tilt', p: 19 },
            { n: 'INR exposure', p: 10 },
          ].map((r) => (
            <div key={r.n} style={{ marginTop: 8 }}>
              <div style={{ display: 'flex', fontSize: 12 }}>
                <span>{r.n}</span><span className="nv-mono nv-num" style={{ marginLeft: 'auto', color: 'var(--amber)' }}>{r.p}%</span>
              </div>
              <div style={{ height: 4, background: 'var(--bg-3)', borderRadius: 2, marginTop: 4 }}>
                <div style={{ width: `${r.p}%`, height: '100%', background: 'var(--amber)' }} />
              </div>
            </div>
          ))}
        </div>
      </div>
      <NVMobileTabs />
      <div className="nv-homebar"></div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// PERFORMANCE — attribution waterfall
// ═══════════════════════════════════════════════════════════
function NVAttributionWaterfall() {
  const steps = [
    { l: 'NIFTY', v: 16.6, abs: 16.6, kind: 'start' },
    { l: 'Sector tilt', v: +2.4, abs: 19.0 },
    { l: 'Stock pick', v: +1.8, abs: 20.8 },
    { l: 'Mid-cap', v: +0.6, abs: 21.4 },
    { l: 'Cost drag', v: -1.2, abs: 20.2 },
    { l: 'Cash drag', v: -1.5, abs: 18.7 },
    { l: 'You', v: 18.7, abs: 18.7, kind: 'end' },
  ];
  const W = 720, H = 240, baseY = 200, scale = 8;
  let runningY = baseY - steps[0].abs * scale;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: H }}>
      {[0, 5, 10, 15, 20].map((y) => (
        <g key={y}>
          <line x1="40" y1={baseY - y * scale} x2={W} y2={baseY - y * scale} stroke="var(--line)" strokeDasharray="2 4" />
          <text x="32" y={baseY - y * scale + 4} textAnchor="end" fontFamily="var(--mono)" fontSize="9" fill="var(--ink-3)">{y}%</text>
        </g>
      ))}
      {steps.map((s, i) => {
        const colW = (W - 60) / steps.length;
        const x = 50 + i * colW;
        const isBracket = s.kind === 'start' || s.kind === 'end';
        const barH = isBracket ? s.abs * scale : Math.abs(s.v) * scale;
        const top = isBracket ? baseY - s.abs * scale : (s.v > 0 ? runningY - s.v * scale : runningY);
        const color = isBracket ? 'var(--indigo)' : s.v > 0 ? 'var(--mint)' : 'var(--danger)';
        const out = (
          <g key={s.l}>
            <rect x={x} y={top} width={colW - 24} height={barH} fill={color} fillOpacity="0.18" stroke={color} strokeWidth="1.5" rx="3" />
            <text x={x + (colW - 24) / 2} y={top - 8} textAnchor="middle" fontFamily="var(--mono)" fontSize="11" fill={color} fontWeight="600">
              {isBracket ? s.abs.toFixed(1) : (s.v > 0 ? '+' : '') + s.v.toFixed(1)}
            </text>
            <text x={x + (colW - 24) / 2} y={baseY + 18} textAnchor="middle" fontFamily="var(--sans)" fontSize="11" fill="var(--ink-2)">{s.l}</text>
            {i < steps.length - 1 && !isBracket && (
              <line x1={x + colW - 24} y1={s.v > 0 ? top : top + barH} x2={x + colW} y2={s.v > 0 ? top : top + barH} stroke="var(--ink-3)" strokeWidth="1" strokeDasharray="2 3" />
            )}
          </g>
        );
        if (!isBracket) runningY = s.v > 0 ? runningY - s.v * scale : runningY + Math.abs(s.v) * scale;
        return out;
      })}
      <line x1="40" y1={baseY} x2={W} y2={baseY} stroke="var(--ink-4)" strokeWidth="1.5" />
    </svg>
  );
}

function NVDashPerformanceDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 1020, display: 'flex' }}>
      <NVSidebar active="performance" />
      <main style={{ flex: 1, padding: '24px 36px 32px', overflow: 'hidden' }}>
        <NVDashHeader kind="performance · 1Y" title="You beat the benchmark by 2.1 points." sev="mint"
          kpis={[
            { l: 'XIRR · 1Y', v: '+18.7%', s: '', sub: 'NIFTY +16.6%', c: 'mint' },
            { l: 'Alpha', v: '+2.1', s: 'pp', sub: 'after fees', c: 'mint' },
            { l: 'Sharpe', v: '1.34', s: '', sub: 'above 1.0 ✓', c: 'mint' },
            { l: 'Hit rate', v: '67%', s: 'of months', sub: 'beat NIFTY', c: 'mint' },
          ]}
        />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18 }}>
          <div className="nv-card" style={{ padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
              <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Attribution · where the 2.1 points came from</div>
              <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--ink-3)' }}>vs NIFTY 500</span>
            </div>
            <NVAttributionWaterfall />
            <div className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '.04em', marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--line)' }}>
              <span style={{ color: 'var(--mint)' }}>Stock picking (+1.8)</span> and <span style={{ color: 'var(--mint)' }}>sector tilt (+2.4)</span> contributed most. Cost drag (-1.2) is the biggest leakage.
            </div>
          </div>

          <aside className="nv-card-2" style={{ padding: 18 }}>
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--mint)', textTransform: 'uppercase' }}>● Top contributors</div>
            <div className="nv-serif" style={{ fontSize: 22, letterSpacing: '-0.02em', marginTop: 6 }}>5 names · 71% of alpha</div>

            <div style={{ marginTop: 14 }}>
              {[
                { n: 'Bajaj Finance', r: '+34.2%', a: '+0.78', c: 'mint' },
                { n: 'HCL Tech', r: '+28.4%', a: '+0.42', c: 'mint' },
                { n: 'Tata Motors', r: '+41.6%', a: '+0.38', c: 'mint' },
                { n: 'HDFC Life', r: '+22.1%', a: '+0.21', c: 'mint' },
                { n: 'Sun Pharma', r: '+19.0%', a: '+0.20', c: 'mint' },
                { n: 'Wipro', r: '-12.4%', a: '-0.34', c: 'danger' },
                { n: 'ITC', r: '-4.2%', a: '-0.18', c: 'danger' },
              ].map((r) => (
                <div key={r.n} style={{ display: 'grid', gridTemplateColumns: '1fr 70px 60px', gap: 8, padding: '8px 0', borderTop: '1px solid var(--line)', alignItems: 'center' }}>
                  <span style={{ fontSize: 12.5 }}>{r.n}</span>
                  <span className="nv-mono nv-num" style={{ fontSize: 11.5, color: 'var(--ink-2)', textAlign: 'right' }}>{r.r}</span>
                  <span className="nv-mono nv-num" style={{ fontSize: 11.5, color: `var(--${r.c})`, textAlign: 'right' }}>{r.a}</span>
                </div>
              ))}
            </div>
          </aside>
        </div>

        {/* monthly hit rate */}
        <div className="nv-card" style={{ padding: 18, marginTop: 16 }}>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 12 }}>Monthly returns · vs NIFTY 500</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: 6 }}>
            {[
              { m: 'Dec', p: 2.4, b: 1.8 }, { m: 'Jan', p: -1.2, b: -2.4 }, { m: 'Feb', p: 3.6, b: 3.1 },
              { m: 'Mar', p: -4.2, b: -3.8 }, { m: 'Apr', p: 5.1, b: 4.2 }, { m: 'May', p: 1.4, b: 1.6 },
              { m: 'Jun', p: 2.8, b: 2.2 }, { m: 'Jul', p: 0.4, b: -0.2 }, { m: 'Aug', p: 4.6, b: 3.8 },
              { m: 'Sep', p: -2.1, b: -2.6 }, { m: 'Oct', p: 3.8, b: 3.4 }, { m: 'Nov', p: 1.9, b: 1.6 },
            ].map((d) => {
              const beat = d.p >= d.b;
              return (
                <div key={d.m} style={{ background: 'var(--bg-1)', borderRadius: 8, padding: '8px 6px', border: '1px solid var(--line)', textAlign: 'center' }}>
                  <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.08em' }}>{d.m.toUpperCase()}</div>
                  <div className="nv-mono nv-num" style={{ fontSize: 12, marginTop: 4, color: d.p > 0 ? 'var(--mint)' : 'var(--danger)' }}>{d.p > 0 ? '+' : ''}{d.p}</div>
                  <div className="nv-mono nv-num" style={{ fontSize: 9, color: 'var(--ink-3)', marginTop: 2 }}>b {d.b > 0 ? '+' : ''}{d.b}</div>
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: beat ? 'var(--mint)' : 'var(--danger)', margin: '6px auto 0' }} />
                </div>
              );
            })}
          </div>
        </div>
      </main>
    </div>
  );
}

function NVDashPerformanceMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>
      <NVMobileDashHead tag="HEALTHY" title="Performance" sev="mint" />

      <div style={{ padding: '4px 18px 14px', flex: 1, overflow: 'hidden' }}>
        <div className="nv-card" style={{ padding: 14, marginBottom: 12 }}>
          <div className="nv-serif" style={{ fontSize: 22, lineHeight: 1.15, letterSpacing: '-0.02em' }}>
            You beat NIFTY by <span style={{ color: 'var(--mint)' }}>+2.1 pp</span>.
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <div style={{ flex: 1 }}><div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>XIRR</div><div className="nv-serif nv-num" style={{ fontSize: 20, color: 'var(--mint)' }}>+18.7%</div></div>
            <div style={{ flex: 1 }}><div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Sharpe</div><div className="nv-serif nv-num" style={{ fontSize: 20 }}>1.34</div></div>
            <div style={{ flex: 1 }}><div className="nv-mono" style={{ fontSize: 8.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>Hit</div><div className="nv-serif nv-num" style={{ fontSize: 20 }}>67%</div></div>
          </div>
        </div>

        <div className="nv-card" style={{ padding: 12, marginBottom: 12 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.12em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 8 }}>Attribution</div>
          {[
            { l: 'NIFTY base', v: '+16.6', c: 'indigo', neutral: true },
            { l: 'Stock picking', v: '+1.8', c: 'mint' },
            { l: 'Sector tilt', v: '+2.4', c: 'mint' },
            { l: 'Mid-cap', v: '+0.6', c: 'mint' },
            { l: 'Cost', v: '-1.2', c: 'danger' },
            { l: 'Cash drag', v: '-1.5', c: 'danger' },
          ].map((r) => (
            <div key={r.l} style={{ display: 'grid', gridTemplateColumns: '1fr 60px 40px', alignItems: 'center', gap: 8, padding: '5px 0' }}>
              <span style={{ fontSize: 12 }}>{r.l}</span>
              <span className="nv-mono nv-num" style={{ textAlign: 'right', fontSize: 12, color: `var(--${r.c})` }}>{r.v}</span>
              <span style={{ background: `var(--${r.c}-soft)`, height: 4, borderRadius: 2 }}>
                <span style={{ display: 'block', height: '100%', width: `${Math.min(100, Math.abs(parseFloat(r.v)) * 18)}%`, background: `var(--${r.c})`, borderRadius: 2 }} />
              </span>
            </div>
          ))}
        </div>

        <div className="nv-card-2" style={{ padding: 12 }}>
          <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--mint)', textTransform: 'uppercase', marginBottom: 6 }}>Top contributors</div>
          {[
            { n: 'Bajaj Finance', a: '+0.78' },
            { n: 'HCL Tech', a: '+0.42' },
            { n: 'Tata Motors', a: '+0.38' },
          ].map((r) => (
            <div key={r.n} style={{ display: 'flex', padding: '6px 0', borderTop: '1px solid var(--line)' }}>
              <span style={{ fontSize: 12 }}>{r.n}</span>
              <span className="nv-mono nv-num" style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--mint)' }}>{r.a}</span>
            </div>
          ))}
        </div>
      </div>
      <NVMobileTabs />
      <div className="nv-homebar"></div>
    </div>
  );
}

Object.assign(window, {
  NVDashDiversificationDesktop, NVDashDiversificationMobile,
  NVDashRiskDesktop, NVDashRiskMobile,
  NVDashPerformanceDesktop, NVDashPerformanceMobile,
  NVDashHeader, NVMobileDashHead, NVMobileTabs,
});
