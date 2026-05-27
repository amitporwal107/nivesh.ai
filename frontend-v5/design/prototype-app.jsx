// ─── Nivesh · Interactive prototype shell ───
// Top-floating navigator, keyboard prev/next, persona + platform toggle.
// All 17 screens already exist as components; this just routes between them.

const CLIENT_SCREENS = [
  { id: 'home',     label: 'Homepage',         d: () => <NVHomepageDesktop />,            m: () => <NVHomepageMobile /> },
  { id: 'login',    label: 'Sign in',          d: () => <NVLoginDesktop />,                m: () => <NVLoginMobile /> },
  { id: 'onboard',  label: 'Onboarding',       d: () => <NVOnboardingDesktop />,           m: () => <NVOnboardingMobile /> },
  { id: 'chat',     label: 'Chat copilot',     d: () => <NVChatDesktop />,                 m: () => <NVChatMobile /> },
  { id: 'conc',     label: 'Concentration',    d: () => <NVDashConcentrationDesktop />,    m: () => <NVDashConcentrationMobile /> },
  { id: 'diverse',  label: 'Diversification',  d: () => <NVDashDiversificationDesktop />,  m: () => <NVDashDiversificationMobile /> },
  { id: 'risk',     label: 'Risk',             d: () => <NVDashRiskDesktop />,             m: () => <NVDashRiskMobile /> },
  { id: 'perf',     label: 'Performance',      d: () => <NVDashPerformanceDesktop />,      m: () => <NVDashPerformanceMobile /> },
  { id: 'goals',    label: 'Goals',            d: () => <NVDashGoalsDesktop />,            m: () => <NVDashGoalsMobile /> },
  { id: 'tax',      label: 'Tax',              d: () => <NVDashTaxDesktop />,              m: () => <NVDashTaxMobile /> },
  { id: 'plan',     label: 'Plan board',       d: () => <NVPlanBoardDesktop />,            m: () => <NVPlanBoardMobile /> },
  { id: 'builder',  label: 'Builder',          d: () => <NVPortfolioBuilderDesktop />,     m: () => <NVPortfolioBuilderMobile /> },
  { id: 'recs',     label: 'Recommendations',  d: () => <NVRecommendationsDesktop />,      m: () => <NVRecommendationsMobile /> },
  { id: 'instr',    label: 'Instrument flow',  d: () => <NVInstrumentAllocationDesktop />, m: () => <NVInstrumentAllocationMobile /> },
];

const ADVISOR_SCREENS = [
  { id: 'advbook',  label: 'Book',             d: () => <NVAdvisorBookDesktop />,          m: () => <NVAdvisorBookMobile /> },
  { id: 'adv360',   label: 'Client 360',       d: () => <NVAdvisorClient360Desktop />,     m: () => <NVAdvisorClient360Mobile /> },
  { id: 'sip',      label: 'SIP board',        d: () => <NVSipBoardDesktop />,             m: () => <NVSipBoardMobile /> },
];

const PROTO_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark",
  "persona": "client",
  "platform": "desktop",
  "screen": "home"
}/*EDITMODE-END*/;

function readHash() {
  const h = (location.hash || '').replace(/^#/, '');
  const out = {};
  h.split('&').forEach((p) => {
    const [k, v] = p.split('=');
    if (k) out[k] = decodeURIComponent(v || '');
  });
  return out;
}
function writeHash(state) {
  const next = Object.entries(state).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
  if (next !== location.hash.replace(/^#/, '')) history.replaceState(null, '', '#' + next);
}

function ProtoApp() {
  const [t, setTweak] = useTweaks(PROTO_DEFAULTS);
  const [persona, setPersona] = React.useState(() => readHash().persona || t.persona);
  const [platform, setPlatform] = React.useState(() => readHash().platform || t.platform);
  const [screen, setScreen] = React.useState(() => readHash().screen || t.screen);
  const [navOpen, setNavOpen] = React.useState(false);

  // theme on root
  React.useEffect(() => { document.documentElement.setAttribute('data-theme', t.theme); }, [t.theme]);
  // sync hash
  React.useEffect(() => { writeHash({ persona, platform, screen }); }, [persona, platform, screen]);

  const list = persona === 'advisor' ? ADVISOR_SCREENS : CLIENT_SCREENS;
  const idx = Math.max(0, list.findIndex((s) => s.id === screen));
  const current = list[idx] || list[0];

  const go = React.useCallback((delta) => {
    const next = list[(idx + delta + list.length) % list.length];
    if (next) setScreen(next.id);
  }, [idx, list]);

  React.useEffect(() => {
    const onKey = (e) => {
      if (e.target && /input|textarea/i.test(e.target.tagName)) return;
      if (e.key === 'ArrowRight' || e.key === 'j') { e.preventDefault(); go(1); }
      else if (e.key === 'ArrowLeft' || e.key === 'k') { e.preventDefault(); go(-1); }
      else if (e.key === 'd') setPlatform('desktop');
      else if (e.key === 'm') setPlatform('mobile');
      else if (e.key === 'n') setNavOpen((v) => !v);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go]);

  // when switching persona, snap to first screen of that persona
  React.useEffect(() => {
    if (!list.find((s) => s.id === screen)) setScreen(list[0].id);
  }, [persona]);

  return (
    <>
      <ProtoStage current={current} platform={platform} />
      <ProtoTopBar
        persona={persona} setPersona={setPersona}
        platform={platform} setPlatform={setPlatform}
        screen={screen} setScreen={setScreen}
        idx={idx} total={list.length} go={go}
        list={list}
        navOpen={navOpen} setNavOpen={setNavOpen}
        theme={t.theme} setTheme={(v) => setTweak('theme', v)}
      />
      <ProtoArrows go={go} />
    </>
  );
}

function ProtoStage({ current, platform }) {
  const ref = React.useRef(null);
  const [scale, setScale] = React.useState(1);
  const [vp, setVp] = React.useState({ w: window.innerWidth, h: window.innerHeight });

  React.useEffect(() => {
    const r = () => setVp({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener('resize', r);
    return () => window.removeEventListener('resize', r);
  }, []);

  // scale-to-fit
  React.useLayoutEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const desiredW = platform === 'mobile' ? 390 : 1440;
    const desiredH = platform === 'mobile' ? 844 : Math.max(900, el.scrollHeight);
    const availW = vp.w - 80;
    const availH = vp.h - 160;
    const s = Math.min(availW / desiredW, availH / desiredH, 1);
    setScale(s);
  }, [vp, platform, current]);

  const isMobile = platform === 'mobile';
  const Comp = isMobile ? current.m : current.d;

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'var(--bg-0)',
      display: 'grid', placeItems: 'center', overflow: 'hidden',
    }}>
      {/* radial spot */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        background: 'radial-gradient(900px 700px at 80% 0%, rgba(106,240,168,0.05), transparent 60%), radial-gradient(900px 800px at 10% 100%, rgba(255,181,71,0.04), transparent 60%)',
      }} />
      <div style={{
        transform: `scale(${scale})`, transformOrigin: 'center center',
        boxShadow: '0 60px 120px -40px rgba(0,0,0,0.6), 0 0 0 1px var(--line-2)',
        borderRadius: isMobile ? 44 : 20,
        overflow: 'hidden',
        background: 'var(--bg-0)',
        transition: 'transform .2s ease',
      }}>
        <div ref={ref} style={{
          width: isMobile ? 390 : 1440,
          height: isMobile ? 844 : undefined,
          minHeight: isMobile ? 844 : 900,
          position: 'relative', overflow: 'hidden',
        }}>
          <Comp />
        </div>
      </div>
    </div>
  );
}

function ProtoTopBar({ persona, setPersona, platform, setPlatform, screen, setScreen, idx, total, go, list, navOpen, setNavOpen, theme, setTheme }) {
  return (
    <>
      <div style={{
        position: 'fixed', top: 16, left: '50%', transform: 'translateX(-50%)', zIndex: 50,
        display: 'flex', alignItems: 'center', gap: 8,
        background: 'rgba(10, 14, 26, 0.7)',
        backdropFilter: 'blur(20px) saturate(140%)',
        WebkitBackdropFilter: 'blur(20px) saturate(140%)',
        border: '1px solid rgba(255,255,255,0.12)',
        borderRadius: 14,
        padding: 6,
        boxShadow: '0 20px 40px -12px rgba(0,0,0,0.5)',
        fontFamily: 'var(--sans)', color: 'var(--ink)',
      }}>
        {/* brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px 4px 6px' }}>
          <span className="nv-mark" style={{ width: 22, height: 22, fontSize: 14 }}>न</span>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 9.5, letterSpacing: '.16em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>PROTOTYPE</span>
        </div>

        <div style={{ width: 1, height: 20, background: 'rgba(255,255,255,0.1)' }} />

        {/* persona toggle */}
        <Segmented value={persona} onChange={setPersona} options={[
          { v: 'client', l: 'Client' },
          { v: 'advisor', l: 'Advisor' },
        ]} />

        {/* platform toggle */}
        <Segmented value={platform} onChange={setPlatform} options={[
          { v: 'desktop', l: '▭ Desktop' },
          { v: 'mobile', l: '▯ Mobile' },
        ]} />

        <div style={{ width: 1, height: 20, background: 'rgba(255,255,255,0.1)' }} />

        {/* screen selector */}
        <button onClick={() => setNavOpen((v) => !v)} style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px',
          background: 'transparent', border: 'none', color: 'var(--ink)', cursor: 'pointer',
          fontFamily: 'var(--sans)', fontSize: 13, borderRadius: 8,
        }}>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--mint)', letterSpacing: '.06em' }}>{String(idx + 1).padStart(2, '0')} / {String(total).padStart(2, '0')}</span>
          <span style={{ fontWeight: 500 }}>{list[idx]?.label}</span>
          <span style={{ color: 'var(--ink-3)', fontSize: 10 }}>{navOpen ? '▲' : '▼'}</span>
        </button>

        <button onClick={() => go(-1)} style={navBtn}>‹</button>
        <button onClick={() => go(1)} style={navBtn}>›</button>

        <div style={{ width: 1, height: 20, background: 'rgba(255,255,255,0.1)' }} />

        {/* theme */}
        <Segmented value={theme} onChange={setTheme} options={[
          { v: 'dark', l: '◐' },
          { v: 'light', l: '◑' },
        ]} compact />
      </div>

      {/* drop-out screen list */}
      {navOpen && (
        <div onClick={() => setNavOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 49 }}>
          <div onClick={(e) => e.stopPropagation()} style={{
            position: 'fixed', top: 78, left: '50%', transform: 'translateX(-50%)', zIndex: 51,
            background: 'rgba(10, 14, 26, 0.92)',
            backdropFilter: 'blur(24px) saturate(140%)',
            border: '1px solid rgba(255,255,255,0.12)',
            borderRadius: 14,
            padding: 10,
            boxShadow: '0 40px 80px -20px rgba(0,0,0,0.7)',
            width: 720,
            maxHeight: '70vh', overflow: 'auto',
          }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 9.5, letterSpacing: '.16em', color: 'var(--ink-3)', textTransform: 'uppercase', padding: '6px 10px 10px' }}>
              Jump to screen · {persona}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 4 }}>
              {list.map((s, i) => {
                const on = s.id === screen;
                return (
                  <button key={s.id} onClick={() => { setScreen(s.id); setNavOpen(false); }} style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '10px 12px',
                    background: on ? 'rgba(106, 240, 168, 0.12)' : 'transparent',
                    border: on ? '1px solid rgba(106, 240, 168, 0.30)' : '1px solid transparent',
                    borderRadius: 9,
                    color: 'var(--ink)', cursor: 'pointer',
                    fontFamily: 'var(--sans)', textAlign: 'left',
                  }}>
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: on ? 'var(--mint)' : 'var(--ink-4)', letterSpacing: '.06em', width: 24 }}>{String(i + 1).padStart(2, '0')}</span>
                    <span style={{ fontSize: 13.5, fontWeight: on ? 500 : 400, color: on ? 'var(--ink)' : 'var(--ink-2)' }}>{s.label}</span>
                  </button>
                );
              })}
            </div>
            <div style={{ display: 'flex', gap: 18, padding: '14px 10px 6px', borderTop: '1px solid rgba(255,255,255,0.08)', marginTop: 6, fontFamily: 'var(--mono)', fontSize: 9.5, letterSpacing: '.08em', color: 'var(--ink-3)' }}>
              <span>← → · prev / next</span>
              <span>D · desktop</span>
              <span>M · mobile</span>
              <span>N · this menu</span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function ProtoArrows({ go }) {
  return (
    <>
      <button onClick={() => go(-1)} style={{
        position: 'fixed', left: 16, top: '50%', transform: 'translateY(-50%)', zIndex: 40,
        width: 44, height: 44, borderRadius: 22,
        background: 'rgba(10, 14, 26, 0.6)',
        backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid rgba(255,255,255,0.10)',
        color: 'var(--ink-2)', fontSize: 18, cursor: 'pointer',
      }}>‹</button>
      <button onClick={() => go(1)} style={{
        position: 'fixed', right: 16, top: '50%', transform: 'translateY(-50%)', zIndex: 40,
        width: 44, height: 44, borderRadius: 22,
        background: 'rgba(10, 14, 26, 0.6)',
        backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid rgba(255,255,255,0.10)',
        color: 'var(--ink-2)', fontSize: 18, cursor: 'pointer',
      }}>›</button>
    </>
  );
}

const navBtn = {
  width: 28, height: 28, borderRadius: 7,
  background: 'transparent', border: '1px solid rgba(255,255,255,0.10)',
  color: 'var(--ink-2)', fontSize: 13, cursor: 'pointer',
  display: 'grid', placeItems: 'center',
};

function Segmented({ value, onChange, options, compact }) {
  return (
    <div style={{
      display: 'inline-flex', background: 'rgba(255,255,255,0.04)',
      border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: 2,
    }}>
      {options.map((o) => {
        const on = o.v === value;
        return (
          <button key={o.v} onClick={() => onChange(o.v)} style={{
            padding: compact ? '4px 8px' : '5px 10px',
            background: on ? 'rgba(255,255,255,0.10)' : 'transparent',
            border: 'none',
            color: on ? 'var(--ink)' : 'var(--ink-3)',
            fontSize: 12, fontFamily: 'var(--sans)', fontWeight: on ? 500 : 400,
            borderRadius: 6, cursor: 'pointer',
          }}>{o.l}</button>
        );
      })}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<ProtoApp />);
