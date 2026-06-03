// ─── Nivesh · Auth + Onboarding — desktop + mobile ───
// LOGIN: Gmail-only (or whitelisted domain); Google OAuth primary.
// ONBOARDING: 3-method connect step, matching CAS Parser SDK
//   1. Gmail CAS Import  ·  2. CAS Upload (NSDL/CDSL)  ·  3. CDSL OTP

// ════════════════════════════════════════════════════════════
// Google "G" mark — colored, no external assets
// ════════════════════════════════════════════════════════════
function NVGoogleMark({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" style={{ flex: 'none' }}>
      <path fill="#4285F4" d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z"/>
      <path fill="#34A853" d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z"/>
      <path fill="#FBBC04" d="M11.69 28.18c-.44-1.32-.69-2.73-.69-4.18s.25-2.86.69-4.18v-5.7H4.34C2.85 17.09 2 20.45 2 24c0 3.55.85 6.91 2.34 9.88l7.35-5.7z"/>
      <path fill="#EA4335" d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.93 4.34 14.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z"/>
    </svg>
  );
}

// ════════════════════════════════════════════════════════════
// LOGIN
// ════════════════════════════════════════════════════════════
function NVLoginDesktop() {
  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 920, display: 'grid', gridTemplateColumns: '1.2fr 1fr' }}>
      {/* left — editorial */}
      <div style={{ padding: '56px 60px 60px', display: 'flex', flexDirection: 'column', position: 'relative' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="nv-mark" style={{ width: 32, height: 32, fontSize: 19 }}>न</span>
          <span className="nv-serif" style={{ fontSize: 22 }}>Nivesh</span>
        </div>

        <div style={{ marginTop: 'auto', maxWidth: 540 }}>
          <div className="nv-mono" style={{ fontSize: 11, letterSpacing: '.2em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 22 }}>★ verified · SEBI-aligned</div>
          <h1 className="nv-serif" style={{ fontSize: 60, lineHeight: 1.02, letterSpacing: '-0.035em', margin: 0 }}>
            Welcome back, <span style={{ fontStyle: 'italic' }}>Aarav</span>.
          </h1>
          <p style={{ fontSize: 17, color: 'var(--ink-2)', lineHeight: 1.55, marginTop: 18 }}>
            Two things happened while you were away. Your health score moved <span style={{ color: 'var(--mint)' }}>+2 pts</span> and we caught a tax-harvest window worth ₹11,500.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginTop: 38 }}>
          {[
            { l: 'HEALTH', v: '86', d: '+2 since Mon', c: 'mint' },
            { l: 'AUM', v: '₹24.8L', d: '+₹14k WoW', c: 'mint' },
            { l: 'OPEN', v: '6', d: '3 actionable', c: 'amber' },
          ].map((m) => (
            <div key={m.l} className="nv-card" style={{ padding: '14px 16px' }}>
              <div className="nv-mono" style={{ fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)' }}>{m.l}</div>
              <div className="nv-serif nv-num" style={{ fontSize: 30, letterSpacing: '-0.03em', color: `var(--${m.c})`, marginTop: 4 }}>{m.v}</div>
              <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 2 }}>{m.d}</div>
            </div>
          ))}
        </div>
      </div>

      {/* right — auth */}
      <div style={{ padding: '56px 60px 60px', display: 'flex', flexDirection: 'column', justifyContent: 'center', background: 'var(--bg-1)', borderLeft: '1px solid var(--line)' }}>
        <div style={{ maxWidth: 400, width: '100%', alignSelf: 'center' }}>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.16em', color: 'var(--mint)', textTransform: 'uppercase' }}>● sign in</div>
          <div className="nv-serif" style={{ fontSize: 32, letterSpacing: '-0.025em', marginTop: 8, lineHeight: 1.1 }}>Sign in with Google.</div>
          <p style={{ fontSize: 13.5, color: 'var(--ink-2)', marginTop: 10, lineHeight: 1.55 }}>
            Nivesh works with your Gmail so we can read CAS statements from your inbox. Read-only — we never send mail or read anything else.
          </p>

          {/* PRIMARY — Google OAuth */}
          <button className="nv-btn" style={{ width: '100%', justifyContent: 'center', padding: '14px', marginTop: 22, fontSize: 14, background: '#FFFFFF', color: '#1F1F1F', border: '1px solid #E5E5E5', fontWeight: 500 }}>
            <NVGoogleMark size={18} />
            Continue with Google
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '24px 0', color: 'var(--ink-4)' }}>
            <div style={{ flex: 1, height: 1, background: 'var(--line)' }} />
            <span className="nv-mono" style={{ fontSize: 10, letterSpacing: '.16em' }}>WHITELISTED EMAIL</span>
            <div style={{ flex: 1, height: 1, background: 'var(--line)' }} />
          </div>

          <label className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Work email</label>
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--mint-line)', borderRadius: 10, padding: '12px 14px', marginTop: 6, fontSize: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: 'var(--ink)', flex: 1 }}>aarav.k@<span style={{ color: 'var(--mint)' }}>gmail.com</span></span>
            <span className="nv-pill nv-pill-mint" style={{ fontSize: 9 }}><span className="nv-dot" style={{ background: 'var(--mint)' }} />ALLOWED</span>
          </div>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.04em', color: 'var(--ink-3)', marginTop: 8 }}>
            Allowed: <span style={{ color: 'var(--ink-2)' }}>@gmail.com</span> · @googlemail.com · 14 whitelisted org domains
          </div>
          <button className="nv-btn nv-btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '13px', marginTop: 14, fontSize: 14 }}>Send magic link →</button>

          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-3)', textAlign: 'center', marginTop: 28, lineHeight: 1.6 }}>
            ENCRYPTED · NEVER STORED · ARN-128459<br />
            <span style={{ color: 'var(--ink-4)' }}>By continuing you agree to the IPS and risk disclosure.</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function NVLoginMobile() {
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '14px 22px 0', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="nv-mark" style={{ width: 30, height: 30, fontSize: 18 }}>न</span>
        <span className="nv-serif" style={{ fontSize: 19 }}>Nivesh</span>
      </div>

      <div style={{ padding: '34px 22px 22px', flex: 1, display: 'flex', flexDirection: 'column' }}>
        <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.16em', color: 'var(--mint)', textTransform: 'uppercase' }}>● sign in</div>
        <div className="nv-serif" style={{ fontSize: 36, letterSpacing: '-0.03em', lineHeight: 1.02, marginTop: 8 }}>
          Sign in with <span style={{ fontStyle: 'italic' }}>Google</span>.
        </div>
        <p style={{ fontSize: 13, color: 'var(--ink-2)', marginTop: 12, lineHeight: 1.5 }}>
          We read CAS emails from your inbox. Read-only, never send.
        </p>

        <button className="nv-btn" style={{ justifyContent: 'center', padding: '14px', marginTop: 24, fontSize: 14, background: '#FFFFFF', color: '#1F1F1F', border: '1px solid #E5E5E5', fontWeight: 500 }}>
          <NVGoogleMark size={18} />
          Continue with Google
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '20px 0', color: 'var(--ink-4)' }}>
          <div style={{ flex: 1, height: 1, background: 'var(--line)' }} />
          <span className="nv-mono" style={{ fontSize: 9, letterSpacing: '.16em' }}>WHITELISTED EMAIL</span>
          <div style={{ flex: 1, height: 1, background: 'var(--line)' }} />
        </div>

        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--mint-line)', borderRadius: 10, padding: '12px 14px', fontSize: 13, display: 'flex', alignItems: 'center' }}>
          <span style={{ flex: 1 }}>aarav.k@<span style={{ color: 'var(--mint)' }}>gmail.com</span></span>
          <span className="nv-pill nv-pill-mint" style={{ fontSize: 8.5 }}>OK</span>
        </div>
        <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', marginTop: 6 }}>@gmail.com · @googlemail.com · 14 orgs</div>
        <button className="nv-btn nv-btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '13px', marginTop: 10, fontSize: 13 }}>Send magic link →</button>

        <div className="nv-mono" style={{ fontSize: 9.5, letterSpacing: '.08em', color: 'var(--ink-3)', textAlign: 'center', marginTop: 'auto', paddingTop: 24, lineHeight: 1.6 }}>
          ENCRYPTED · NEVER STORED<br />
          <span style={{ color: 'var(--ink-4)' }}>ARN-128459 · IPS + risk disclosure</span>
        </div>
      </div>
      <div className="nv-homebar"></div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════
// ONBOARDING · Connect investments  (3 methods, CAS Parser)
// ════════════════════════════════════════════════════════════
function NVMethodCard({ no, icon, title, sub, time, active, onSelect }) {
  return (
    <div onClick={onSelect} style={{
      padding: 16, borderRadius: 12, cursor: 'pointer',
      background: active ? 'var(--mint-soft)' : 'var(--bg-1)',
      border: active ? '1px solid var(--mint-line)' : '1px solid var(--line)',
      display: 'flex', alignItems: 'flex-start', gap: 14,
      transition: 'all .15s ease',
    }}>
      <div style={{
        width: 40, height: 40, borderRadius: 10, flex: 'none',
        background: active ? 'var(--mint)' : 'var(--bg-2)',
        border: active ? 'none' : '1px solid var(--line-2)',
        color: active ? '#06120B' : 'var(--ink-2)',
        display: 'grid', placeItems: 'center',
      }}>{icon}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span className="nv-mono" style={{ fontSize: 10, color: active ? 'var(--mint)' : 'var(--ink-4)', letterSpacing: '.06em' }}>{no}</span>
          <span style={{ fontSize: 14.5, fontWeight: 500, letterSpacing: '-0.005em' }}>{title}</span>
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.5, marginTop: 6 }}>{sub}</div>
        <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.06em', marginTop: 8, textTransform: 'uppercase' }}>● {time}</div>
      </div>
      {active && <span style={{ marginTop: 4, width: 18, height: 18, borderRadius: '50%', background: 'var(--mint)', color: '#06120B', display: 'grid', placeItems: 'center', fontSize: 10, fontFamily: 'var(--mono)' }}>✓</span>}
    </div>
  );
}

function NVMethodGmail() {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <NVGoogleMark size={26} />
        <div>
          <div className="nv-serif" style={{ fontSize: 22, letterSpacing: '-0.02em' }}>Connect Gmail inbox</div>
          <div className="nv-mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '.04em', textTransform: 'uppercase', marginTop: 2 }}>aarav.k@gmail.com · authorize once</div>
        </div>
      </div>

      <p style={{ fontSize: 13.5, color: 'var(--ink-2)', lineHeight: 1.55 }}>
        We scan your inbox for CAMS, KFintech, NSDL and CDSL eCAS emails from the last 12 months and parse them. Nothing else is read or stored.
      </p>

      <div style={{ marginTop: 18, padding: 16, background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 12 }}>
        <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase', marginBottom: 10 }}>What we ask for · 3 scopes</div>
        {[
          { i: '◐', t: 'Read messages with attachments', s: 'subject contains CAS · eCAS · KFintech · CAMS · CDSL · NSDL' },
          { i: '◑', t: 'Download attachments', s: 'PDF only; under 5 MB each' },
          { i: '◒', t: 'Identity', s: 'your email + display name for your account' },
        ].map((r, i) => (
          <div key={i} style={{ display: 'flex', gap: 12, padding: '8px 0', borderTop: i > 0 ? '1px solid var(--line)' : 'none' }}>
            <span style={{ width: 18, color: 'var(--mint)', fontSize: 12, marginTop: 2 }}>{r.i}</span>
            <div>
              <div style={{ fontSize: 13, fontWeight: 500 }}>{r.t}</div>
              <div className="nv-mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', marginTop: 2, letterSpacing: '.02em' }}>{r.s}</div>
            </div>
          </div>
        ))}
      </div>

      <button className="nv-btn" style={{ width: '100%', justifyContent: 'center', padding: '13px', marginTop: 18, fontSize: 14, background: '#FFFFFF', color: '#1F1F1F', border: '1px solid #E5E5E5', fontWeight: 500 }}>
        <NVGoogleMark size={18} />
        Authorize with Google →
      </button>
      <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', textAlign: 'center', marginTop: 10, letterSpacing: '.06em' }}>OAUTH 2.0 · REVOCABLE ANY TIME · INDIA-HOSTED</div>
    </div>
  );
}

function NVMethodUpload() {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--indigo-soft)', border: '1px solid var(--indigo-line)', color: 'var(--indigo)', display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)', fontSize: 14 }}>↥</div>
        <div>
          <div className="nv-serif" style={{ fontSize: 22, letterSpacing: '-0.02em' }}>Upload your eCAS PDF</div>
          <div className="nv-mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '.04em', textTransform: 'uppercase', marginTop: 2 }}>NSDL · CDSL · CAMS · KFintech</div>
        </div>
      </div>

      <p style={{ fontSize: 13.5, color: 'var(--ink-2)', lineHeight: 1.55 }}>
        Drag the CAS PDF you received from NSDL or CDSL. Both depositories include holdings from the other — one statement is enough.
      </p>

      {/* drop zone */}
      <div style={{
        marginTop: 18,
        padding: '32px 24px',
        background: 'var(--bg-1)',
        border: '1.5px dashed var(--line-3)',
        borderRadius: 14,
        textAlign: 'center',
      }}>
        <div style={{ width: 48, height: 48, borderRadius: 12, background: 'var(--bg-2)', border: '1px solid var(--line-2)', display: 'grid', placeItems: 'center', margin: '0 auto 14px', color: 'var(--ink-2)', fontSize: 22 }}>↧</div>
        <div className="nv-serif" style={{ fontSize: 19, letterSpacing: '-0.02em' }}>Drop your eCAS PDF here</div>
        <div className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 6, letterSpacing: '.04em' }}>PDF · up to 10 MB · password-protected accepted</div>
        <button className="nv-btn" style={{ marginTop: 14, padding: '8px 14px', fontSize: 12.5 }}>Browse files</button>
      </div>

      {/* helper — don't have one */}
      <div className="nv-card" style={{ padding: 14, marginTop: 14, background: 'var(--bg-1)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ width: 26, height: 26, borderRadius: 7, background: 'var(--amber-soft)', color: 'var(--amber)', display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)', fontSize: 13, flex: 'none' }}>?</span>
        <div style={{ flex: 1, fontSize: 12.5, color: 'var(--ink-2)' }}>
          Don't have a CAS file? <span style={{ color: 'var(--mint)' }}>Request one from CAMS / KFintech →</span> (delivered in ~10 min)
        </div>
      </div>
    </div>
  );
}

function NVMethodOTP({ step = 'pan' }) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--amber-soft)', border: '1px solid var(--amber-line)', color: 'var(--amber)', display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)', fontSize: 13 }}>⛨</div>
        <div>
          <div className="nv-serif" style={{ fontSize: 22, letterSpacing: '-0.02em' }}>Fetch live holdings · CDSL OTP</div>
          <div className="nv-mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '.04em', textTransform: 'uppercase', marginTop: 2 }}>Real-time · no statement needed</div>
        </div>
      </div>

      <p style={{ fontSize: 13.5, color: 'var(--ink-2)', lineHeight: 1.55 }}>
        CDSL sends an OTP to the mobile linked with your PAN. Enter it and we pull current holdings — both NSDL and CDSL in one go.
      </p>

      <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <label className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>PAN</label>
          <div style={{ background: 'var(--bg-1)', border: '1px solid var(--line-2)', borderRadius: 10, padding: '12px 14px', marginTop: 6, fontFamily: 'var(--mono)', fontSize: 14, letterSpacing: '.06em' }}>ABCDE1234F</div>
        </div>
        <div>
          <label className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Mobile linked to PAN</label>
          <div style={{ background: 'var(--bg-1)', border: '1px solid var(--line-2)', borderRadius: 10, padding: '12px 14px', marginTop: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="nv-mono" style={{ fontSize: 12, color: 'var(--ink-3)' }}>+91</span>
            <span className="nv-mono" style={{ fontSize: 14, letterSpacing: '.04em', flex: 1 }}>98XXX XX482</span>
            <span className="nv-pill nv-pill-mint" style={{ fontSize: 9 }}>VERIFIED</span>
          </div>
        </div>
        <div>
          <label className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>OTP · 6 digits</label>
          <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
            {['7','2','4','3','—','—'].map((d, i) => (
              <div key={i} style={{ flex: 1, height: 52, background: 'var(--bg-1)', border: `1px solid ${i < 4 ? 'var(--mint-line)' : 'var(--line-2)'}`, borderRadius: 10, display: 'grid', placeItems: 'center', fontFamily: 'var(--display)', fontSize: 24, color: i < 4 ? 'var(--ink)' : 'var(--ink-4)' }}>{d}</div>
            ))}
          </div>
          <div style={{ display: 'flex', marginTop: 10 }}>
            <span className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '.04em' }}>OTP sent · expires in <span style={{ color: 'var(--mint)' }}>02:47</span></span>
            <span className="nv-mono" style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--indigo)', letterSpacing: '.04em' }}>RESEND</span>
          </div>
        </div>
      </div>

      <button className="nv-btn nv-btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '13px', marginTop: 18, fontSize: 14 }}>Verify & fetch holdings →</button>
      <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', textAlign: 'center', marginTop: 10, letterSpacing: '.06em' }}>CDSL · NSDL · SEBI-COMPLIANT · NEVER STORE OTP</div>
    </div>
  );
}

function NVOnboardingDesktop() {
  const steps = ['Sign in', 'Connect investments', 'Goals', 'Review'];
  const active = 1;
  const [method, setMethod] = React.useState('gmail');

  return (
    <div className="nv-frame" style={{ width: '100%', minHeight: 920, display: 'flex', flexDirection: 'column' }}>
      {/* top bar with stepper */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '20px 56px', borderBottom: '1px solid var(--line)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="nv-mark" style={{ width: 30, height: 30, fontSize: 18 }}>न</span>
          <span className="nv-serif" style={{ fontSize: 19 }}>Nivesh</span>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
          {steps.map((s, i) => (
            <React.Fragment key={s}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: i === active ? 'var(--ink)' : i < active ? 'var(--ink-2)' : 'var(--ink-4)' }}>
                <span style={{ width: 22, height: 22, borderRadius: '50%', border: `1.5px solid ${i <= active ? 'var(--mint)' : 'var(--line-2)'}`, background: i < active ? 'var(--mint)' : 'transparent', color: i < active ? '#06120B' : i === active ? 'var(--mint)' : 'var(--ink-4)', display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)', fontSize: 10 }}>
                  {i < active ? '✓' : i + 1}
                </span>
                <span style={{ fontSize: 13 }}>{s}</span>
              </div>
              {i < steps.length - 1 && <span style={{ width: 28, height: 1, background: i < active ? 'var(--mint-line)' : 'var(--line)' }} />}
            </React.Fragment>
          ))}
          <span className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginLeft: 16, letterSpacing: '.06em' }}>STEP 2 / 4 · ~60 SEC</span>
        </div>
      </div>

      {/* body */}
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '440px 1fr', maxWidth: 1240, margin: '0 auto', width: '100%', padding: '40px 56px 32px', gap: 40 }}>
        {/* left — intro + method picker */}
        <div>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.18em', color: 'var(--mint)', textTransform: 'uppercase' }}>● connect investments</div>
          <h1 className="nv-serif" style={{ fontSize: 44, lineHeight: 1.02, letterSpacing: '-0.035em', margin: '12px 0 0' }}>
            Bring your investments in.
          </h1>
          <p style={{ fontSize: 14.5, color: 'var(--ink-2)', lineHeight: 1.55, marginTop: 14, maxWidth: 420 }}>
            Three ways. Pick the one that's easiest for you — they all produce the same complete view.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 26 }}>
            <NVMethodCard no="01" icon={<NVGoogleMark size={20} />} title="Gmail CAS Import"
              sub="Authorize once, we read CAS emails from your inbox. Easiest if you receive CAS by email."
              time="30 seconds · fully automatic"
              active={method === 'gmail'} onSelect={() => setMethod('gmail')} />
            <NVMethodCard no="02" icon={<span style={{ fontFamily: 'var(--mono)', fontSize: 16 }}>↥</span>} title="CAS Upload · NSDL / CDSL"
              sub="Drag the eCAS PDF you've already downloaded. Works offline."
              time="2 minutes · most thorough"
              active={method === 'upload'} onSelect={() => setMethod('upload')} />
            <NVMethodCard no="03" icon={<span style={{ fontFamily: 'var(--mono)', fontSize: 16 }}>⛨</span>} title="CDSL OTP"
              sub="Fetch live demat holdings via OTP. Real-time, no statement needed."
              time="60 seconds · real-time"
              active={method === 'otp'} onSelect={() => setMethod('otp')} />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 24, padding: '10px 14px', background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
            <span style={{ color: 'var(--mint)', fontSize: 13 }}>●</span>
            <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>India-hosted (Bangalore) · TLS 1.3 · AES-256 · PDFs deleted after parsing</span>
          </div>
        </div>

        {/* right — active method */}
        <div className="nv-card" style={{ padding: 28, alignSelf: 'flex-start' }}>
          {method === 'gmail' && <NVMethodGmail />}
          {method === 'upload' && <NVMethodUpload />}
          {method === 'otp' && <NVMethodOTP />}
        </div>
      </div>

      {/* footer nav */}
      <div style={{ borderTop: '1px solid var(--line)', padding: '16px 56px', display: 'flex', alignItems: 'center' }}>
        <button className="nv-btn" style={{ padding: '10px 16px', fontSize: 13 }}>‹ Back</button>
        <span className="nv-mono" style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)', marginRight: 14, letterSpacing: '.08em' }}>SKIP FOR NOW · ADD LATER</span>
        <button className="nv-btn nv-btn-primary" style={{ padding: '10px 18px', fontSize: 13 }}>Continue · Goals →</button>
      </div>
    </div>
  );
}

function NVOnboardingMobile() {
  const steps = ['Sign in', 'Connect', 'Goals', 'Review'];
  const [method, setMethod] = React.useState('gmail');

  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <span className="nv-notch"></span>
      <div className="nv-statusbar"><span>9:41</span><span style={{ fontSize: 12 }}>● ● ●</span></div>

      <div style={{ padding: '8px 18px 12px', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="nv-mark" style={{ width: 26, height: 26, fontSize: 15 }}>न</span>
        <span style={{ display: 'flex', flex: 1, marginLeft: 8, gap: 4 }}>
          {steps.map((_, i) => (
            <span key={i} style={{ flex: 1, height: 3, borderRadius: 2, background: i <= 1 ? 'var(--mint)' : 'var(--bg-3)' }} />
          ))}
        </span>
        <span className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.08em' }}>2 / 4</span>
      </div>

      <div style={{ padding: '16px 22px 14px', flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.16em', color: 'var(--mint)', textTransform: 'uppercase' }}>● connect</div>
        <h1 className="nv-serif" style={{ fontSize: 28, lineHeight: 1.05, letterSpacing: '-0.03em', margin: '6px 0 0' }}>
          Bring your investments in.
        </h1>
        <p style={{ fontSize: 12.5, color: 'var(--ink-2)', marginTop: 8, lineHeight: 1.5 }}>
          Pick the easiest for you.
        </p>

        {/* segmented method picker */}
        <div style={{ display: 'flex', gap: 4, marginTop: 16, padding: 3, background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 10 }}>
          {[
            { k: 'gmail', l: 'Gmail' },
            { k: 'upload', l: 'Upload' },
            { k: 'otp', l: 'CDSL OTP' },
          ].map((o) => {
            const on = method === o.k;
            return (
              <button key={o.k} onClick={() => setMethod(o.k)} style={{
                flex: 1, padding: '8px 6px', fontSize: 11.5,
                background: on ? 'var(--bg-1)' : 'transparent',
                border: on ? '1px solid var(--mint-line)' : '1px solid transparent',
                borderRadius: 8,
                color: on ? 'var(--ink)' : 'var(--ink-3)',
                fontWeight: on ? 500 : 400,
                fontFamily: 'var(--sans)',
                cursor: 'pointer',
              }}>{o.l}</button>
            );
          })}
        </div>

        {/* active method */}
        <div style={{ marginTop: 14, flex: 1, overflow: 'hidden' }}>
          {method === 'gmail' && <NVMethodGmailMobile />}
          {method === 'upload' && <NVMethodUploadMobile />}
          {method === 'otp' && <NVMethodOTPMobile />}
        </div>
      </div>

      <div style={{ padding: '12px 18px 22px', borderTop: '1px solid var(--line)', display: 'flex', gap: 8 }}>
        <button className="nv-btn" style={{ padding: '11px 14px', fontSize: 12.5 }}>‹</button>
        <button className="nv-btn nv-btn-primary" style={{ flex: 1, justifyContent: 'center', padding: '11px', fontSize: 13 }}>Continue · Goals →</button>
      </div>
      <div className="nv-homebar"></div>
    </div>
  );
}

// mobile-compact variants of the three methods
function NVMethodGmailMobile() {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <NVGoogleMark size={22} />
        <div className="nv-serif" style={{ fontSize: 18, letterSpacing: '-0.02em' }}>Connect Gmail</div>
      </div>
      <p style={{ fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.5 }}>
        Read-only access to CAMS / KFintech / NSDL / CDSL emails. Nothing else.
      </p>
      <div className="nv-card-2" style={{ padding: 12, marginTop: 12 }}>
        <div className="nv-mono" style={{ fontSize: 9, color: 'var(--ink-3)', letterSpacing: '.14em', textTransform: 'uppercase' }}>3 SCOPES</div>
        {['Read CAS emails only', 'Download PDF attachments', 'Email + display name'].map((t, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, padding: '6px 0', borderTop: i > 0 ? '1px solid var(--line)' : 'none' }}>
            <span style={{ color: 'var(--mint)', fontSize: 11 }}>●</span>
            <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>{t}</span>
          </div>
        ))}
      </div>
      <button className="nv-btn" style={{ width: '100%', justifyContent: 'center', padding: '13px', marginTop: 14, fontSize: 13, background: '#FFFFFF', color: '#1F1F1F', border: '1px solid #E5E5E5', fontWeight: 500 }}>
        <NVGoogleMark size={16} />
        Authorize with Google →
      </button>
    </div>
  );
}

function NVMethodUploadMobile() {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <div style={{ width: 26, height: 26, borderRadius: 7, background: 'var(--indigo-soft)', color: 'var(--indigo)', display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)' }}>↥</div>
        <div className="nv-serif" style={{ fontSize: 18, letterSpacing: '-0.02em' }}>Upload eCAS PDF</div>
      </div>
      <p style={{ fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.5 }}>
        NSDL or CDSL — both cover all your holdings.
      </p>
      <div style={{ marginTop: 14, padding: '24px 16px', background: 'var(--bg-1)', border: '1.5px dashed var(--line-3)', borderRadius: 12, textAlign: 'center' }}>
        <div style={{ width: 40, height: 40, borderRadius: 10, background: 'var(--bg-2)', display: 'grid', placeItems: 'center', margin: '0 auto 10px', color: 'var(--ink-2)', fontSize: 18 }}>↧</div>
        <div className="nv-serif" style={{ fontSize: 15, letterSpacing: '-0.02em' }}>Choose your PDF</div>
        <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4, letterSpacing: '.04em' }}>PDF · up to 10 MB · password OK</div>
        <button className="nv-btn nv-btn-primary" style={{ marginTop: 10, padding: '8px 16px', fontSize: 12 }}>Browse →</button>
      </div>
      <div style={{ marginTop: 10, fontSize: 11.5, color: 'var(--ink-2)', textAlign: 'center' }}>
        Don't have one? <span style={{ color: 'var(--mint)' }}>Request from CAMS →</span>
      </div>
    </div>
  );
}

function NVMethodOTPMobile() {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <div style={{ width: 26, height: 26, borderRadius: 7, background: 'var(--amber-soft)', color: 'var(--amber)', display: 'grid', placeItems: 'center', fontFamily: 'var(--mono)' }}>⛨</div>
        <div className="nv-serif" style={{ fontSize: 18, letterSpacing: '-0.02em' }}>CDSL OTP</div>
      </div>
      <p style={{ fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.5 }}>
        Live holdings · NSDL + CDSL · no statement needed.
      </p>
      <div style={{ marginTop: 12 }}>
        <label className="nv-mono" style={{ fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>PAN</label>
        <div style={{ background: 'var(--bg-1)', border: '1px solid var(--line-2)', borderRadius: 9, padding: '10px 12px', marginTop: 4, fontFamily: 'var(--mono)', fontSize: 13, letterSpacing: '.06em' }}>ABCDE1234F</div>
      </div>
      <div style={{ marginTop: 10 }}>
        <label className="nv-mono" style={{ fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>OTP</label>
        <div style={{ display: 'flex', gap: 5, marginTop: 4 }}>
          {['7','2','4','3','—','—'].map((d, i) => (
            <div key={i} style={{ flex: 1, height: 40, background: 'var(--bg-1)', border: `1px solid ${i < 4 ? 'var(--mint-line)' : 'var(--line-2)'}`, borderRadius: 8, display: 'grid', placeItems: 'center', fontFamily: 'var(--display)', fontSize: 18, color: i < 4 ? 'var(--ink)' : 'var(--ink-4)' }}>{d}</div>
          ))}
        </div>
        <div className="nv-mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', marginTop: 6 }}>Expires in <span style={{ color: 'var(--mint)' }}>02:47</span></div>
      </div>
      <button className="nv-btn nv-btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '12px', marginTop: 14, fontSize: 12.5 }}>Verify & fetch →</button>
    </div>
  );
}

Object.assign(window, { NVLoginDesktop, NVLoginMobile, NVOnboardingDesktop, NVOnboardingMobile });
