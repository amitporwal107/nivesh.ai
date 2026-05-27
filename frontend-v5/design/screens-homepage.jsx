// ─── Nivesh · Homepage — desktop + mobile ───
// Premium fintech dark, generous whitespace, novel product preview inline.

function NVHomepageDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 920 }}>
      {/* nav */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '20px 56px', borderBottom: '1px solid var(--line)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="nv-mark" style={{ width: 32, height: 32, fontSize: 19 }}>न</span>
          <span className="nv-serif" style={{ fontSize: 22 }}>Nivesh</span>
          <span className="nv-mono" style={{ fontSize: 10, letterSpacing: '.18em', color: 'var(--ink-3)', textTransform: 'uppercase', marginLeft: 6 }}>COPILOT</span>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 36 }}>
          <span style={{ fontSize: 14, color: 'var(--ink-2)' }}>Product</span>
          <span style={{ fontSize: 14, color: 'var(--ink-2)' }}>For advisors</span>
          <span style={{ fontSize: 14, color: 'var(--ink-2)' }}>Pricing</span>
          <span style={{ fontSize: 14, color: 'var(--ink-2)' }}>Sign in</span>
          <button className="nv-btn nv-btn-primary" style={{ padding: '9px 16px', fontSize: 13 }}>Check my portfolio →</button>
        </div>
      </div>

      {/* hero */}
      <div style={{ padding: '88px 56px 60px', maxWidth: 1280, margin: '0 auto', display: 'grid', gridTemplateColumns: '1.05fr 1fr', gap: 80, alignItems: 'center' }}>
        <div>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, padding: '6px 14px 6px 8px', borderRadius: 999, border: '1px solid var(--line-2)', background: 'var(--bg-1)', marginBottom: 28 }}>
            <span style={{ background: 'var(--mint-soft)', color: 'var(--mint)', fontSize: 10, fontFamily: 'var(--mono)', letterSpacing: '.1em', padding: '3px 8px', borderRadius: 999, textTransform: 'uppercase' }}>NEW</span>
            <span style={{ fontSize: 13, color: 'var(--ink-2)' }}>Goal-aware rebalancing, live</span>
            <span style={{ color: 'var(--ink-3)' }}>›</span>
          </div>
          <h1 className="nv-serif" style={{ fontSize: 84, lineHeight: 0.96, letterSpacing: '-0.035em', color: 'var(--ink)', margin: 0 }}>
            Your portfolio,<br />
            <span style={{ fontStyle: 'italic' }}>finally</span> legible<span style={{ color: 'var(--mint)' }}>.</span>
          </h1>
          <p style={{ fontSize: 19, lineHeight: 1.55, color: 'var(--ink-2)', marginTop: 28, maxWidth: 480, fontWeight: 400 }}>
            Nivesh reads every holding, scores its health and rewrites the report in plain language —
            so you know exactly what to fix and why.
          </p>
          <div style={{ display: 'flex', gap: 12, marginTop: 40 }}>
            <button className="nv-btn nv-btn-primary" style={{ padding: '14px 22px', fontSize: 15 }}>Check my portfolio free</button>
            <button className="nv-btn" style={{ padding: '14px 22px', fontSize: 15 }}>Watch 90-second tour</button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 24, marginTop: 36 }}>
            {['SEBI-aligned', 'Read-only access', 'No card needed'].map((t) => (
              <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--ink-3)', fontFamily: 'var(--mono)', letterSpacing: '.04em' }}>
                <span style={{ width: 4, height: 4, borderRadius: '50%', background: 'var(--mint)' }} />
                {t}
              </div>
            ))}
          </div>
        </div>

        {/* live demo card */}
        <div className="nv-card" style={{ padding: 0, overflow: 'hidden', position: 'relative' }}>
          <div style={{ padding: '18px 22px', borderBottom: '1px solid var(--line)', display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ display: 'flex', gap: 5 }}>
              <span style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--ink-5)' }} />
              <span style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--ink-5)' }} />
              <span style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--ink-5)' }} />
            </span>
            <span className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '.08em' }}>nivesh.app/health</span>
            <span className="nv-pill nv-pill-mint" style={{ marginLeft: 'auto' }}><span className="nv-dot" style={{ background: 'var(--mint)' }} />LIVE</span>
          </div>
          <div style={{ padding: '28px 24px 24px' }}>
            <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 18 }}>
              <div>
                <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.16em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Portfolio health</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 6 }}>
                  <span className="nv-serif" style={{ fontSize: 78, lineHeight: 0.9, letterSpacing: '-0.04em' }}>86</span>
                  <span className="nv-mono" style={{ fontSize: 14, color: 'var(--ink-3)' }}>/ 100</span>
                  <span className="nv-pill nv-pill-mint" style={{ marginLeft: 8 }}>GRADE A</span>
                </div>
              </div>
              <span className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>updated · 2m ago</span>
            </div>

            {/* segmented bar */}
            <div style={{ display: 'flex', gap: 3, marginBottom: 22 }}>
              {[
                { k: 'risk', v: 92, c: 'var(--mint)' },
                { k: 'concen', v: 58, c: 'var(--amber)' },
                { k: 'diverse', v: 78, c: 'var(--mint)' },
                { k: 'cost', v: 88, c: 'var(--mint)' },
                { k: 'tax', v: 81, c: 'var(--mint)' },
                { k: 'goals', v: 74, c: 'var(--indigo)' },
              ].map(({ k, v, c }) => (
                <div key={k} style={{ flex: 1 }}>
                  <div style={{ height: 36, background: 'var(--bg-2)', borderRadius: 6, position: 'relative', overflow: 'hidden' }}>
                    <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: `${v}%`, background: c, opacity: .9 }} />
                  </div>
                  <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', marginTop: 6, textAlign: 'center', textTransform: 'uppercase', letterSpacing: '.06em' }}>{k}</div>
                </div>
              ))}
            </div>

            {/* insight rows */}
            <div style={{ borderTop: '1px solid var(--line)' }}>
              {[
                { sev: 'amber', t: '32% of your money is in financials', s: 'Concentration · 6 holdings' },
                { sev: 'indigo', t: '3 funds hold near-identical stocks', s: 'Diversification · ₹4.2L overlap' },
                { sev: 'mint', t: 'You can harvest ₹38,400 in tax losses', s: 'Tax · before March 31' },
              ].map((r, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 2px', borderBottom: i < 2 ? '1px solid var(--line)' : 'none' }}>
                  <span style={{ width: 3, alignSelf: 'stretch', background: `var(--${r.sev})`, borderRadius: 2 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 500, letterSpacing: '-0.005em' }}>{r.t}</div>
                    <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '.06em', marginTop: 3, textTransform: 'uppercase' }}>{r.s}</div>
                  </div>
                  <span style={{ color: 'var(--ink-3)', fontSize: 18 }}>›</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* feature trio */}
      <div style={{ padding: '20px 56px 80px', maxWidth: 1280, margin: '0 auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1, background: 'var(--line)', border: '1px solid var(--line)', borderRadius: 18, overflow: 'hidden' }}>
          {[
            { n: '01', t: 'Read every holding', d: 'Gmail CAS, statement PDF, or live broker. Equities, mutual funds, FDs, NPS — all reconciled in a single ledger.' },
            { n: '02', t: 'Score it across 20 checks', d: 'Concentration, overlap, risk, cost, tax, goals. Each scored individually, then weighted into one A-to-D grade.' },
            { n: '03', t: 'Show you what to do', d: 'Ranked actions with the exact fund or stock, the trade-off, and a one-tap simulation before you commit.' },
          ].map((f) => (
            <div key={f.n} style={{ padding: 32, background: 'var(--bg-1)' }}>
              <div className="nv-mono" style={{ fontSize: 11, color: 'var(--mint)', letterSpacing: '.1em' }}>{f.n}</div>
              <div className="nv-serif" style={{ fontSize: 26, marginTop: 18, letterSpacing: '-0.02em' }}>{f.t}</div>
              <p style={{ fontSize: 14, color: 'var(--ink-2)', lineHeight: 1.55, marginTop: 12, maxWidth: 320 }}>{f.d}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function NVHomepageMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '8px 22px 12px', display: 'flex', alignItems: 'center' }}>
        <span className="nv-mark" style={{ width: 30, height: 30, fontSize: 18 }}>न</span>
        <span className="nv-serif" style={{ fontSize: 19, marginLeft: 10 }}>Nivesh</span>
        <button className="nv-btn" style={{ marginLeft: 'auto', padding: '7px 12px', fontSize: 12 }}>Sign in</button>
      </div>

      {/* hero */}
      <div style={{ padding: '24px 22px 22px' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '4px 11px 4px 5px', borderRadius: 999, border: '1px solid var(--line-2)', background: 'var(--bg-1)', marginBottom: 20 }}>
          <span style={{ background: 'var(--mint-soft)', color: 'var(--mint)', fontSize: 9, fontFamily: 'var(--mono)', letterSpacing: '.1em', padding: '2px 7px', borderRadius: 999, textTransform: 'uppercase' }}>NEW</span>
          <span style={{ fontSize: 11.5, color: 'var(--ink-2)' }}>Goal-aware rebalancing</span>
        </div>
        <h1 className="nv-serif" style={{ fontSize: 46, lineHeight: 0.98, letterSpacing: '-0.035em', margin: 0 }}>
          Your portfolio, <span style={{ fontStyle: 'italic' }}>finally</span> legible<span style={{ color: 'var(--mint)' }}>.</span>
        </h1>
        <p style={{ fontSize: 14.5, lineHeight: 1.5, color: 'var(--ink-2)', marginTop: 16 }}>
          Read every holding. Score it. Get one ranked list of what to fix — in plain language.
        </p>
        <button className="nv-btn nv-btn-primary" style={{ width: '100%', marginTop: 22, padding: '14px', fontSize: 14, justifyContent: 'center' }}>
          Check my portfolio →
        </button>
        <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-3)', textAlign: 'center', marginTop: 12, textTransform: 'uppercase' }}>
          SEBI-aligned · read-only · no card
        </div>
      </div>

      {/* live preview card */}
      <div style={{ padding: '4px 22px 18px' }}>
        <div className="nv-card" style={{ padding: 18 }}>
          <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 14 }}>
            <div>
              <div className="nv-mono" style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Sample · health</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                <span className="nv-serif" style={{ fontSize: 54, lineHeight: 0.9, letterSpacing: '-0.04em' }}>86</span>
                <span className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>/ 100</span>
              </div>
            </div>
            <span className="nv-pill nv-pill-mint">GRADE A</span>
          </div>
          <div style={{ display: 'flex', gap: 3, marginBottom: 14 }}>
            {[92, 58, 78, 88, 81, 74].map((v, i) => (
              <div key={i} style={{ flex: 1, height: 28, background: 'var(--bg-2)', borderRadius: 4, position: 'relative', overflow: 'hidden' }}>
                <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: `${v}%`, background: v > 70 ? 'var(--mint)' : v > 50 ? 'var(--amber)' : 'var(--danger)' }} />
              </div>
            ))}
          </div>
          {[
            { sev: 'amber', t: '32% in financials' },
            { sev: 'indigo', t: '3 funds with overlapping stocks' },
          ].map((r, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 0', borderTop: '1px solid var(--line)' }}>
              <span style={{ width: 3, alignSelf: 'stretch', height: 28, background: `var(--${r.sev})`, borderRadius: 2 }} />
              <span style={{ fontSize: 13, flex: 1 }}>{r.t}</span>
              <span style={{ color: 'var(--ink-3)' }}>›</span>
            </div>
          ))}
        </div>
      </div>

      {/* feature strip */}
      <div style={{ padding: '4px 22px 30px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {[
          { n: '01', t: 'Read every holding', i: '●' },
          { n: '02', t: '20 health checks · A→D', i: '◐' },
          { n: '03', t: 'Ranked actions, simulated', i: '◑' },
        ].map((f) => (
          <div key={f.n} className="nv-card-2" style={{ padding: 14, display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="nv-mono" style={{ fontSize: 10, color: 'var(--mint)', letterSpacing: '.1em' }}>{f.n}</span>
            <span style={{ fontSize: 13.5, fontWeight: 500 }}>{f.t}</span>
            <span style={{ marginLeft: 'auto', color: 'var(--ink-3)' }}>›</span>
          </div>
        ))}
      </div>

      <div className="nv-homebar"></div>
    </div>
  );
}

Object.assign(window, { NVHomepageDesktop, NVHomepageMobile });
