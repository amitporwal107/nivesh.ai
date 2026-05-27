// ─── Nivesh redesign — canvas composition + theme toggle ───

const TWEAKS_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark",
  "accent": "mint"
}/*EDITMODE-END*/;

function NivApp() {
  const [t, setTweak] = useTweaks(TWEAKS_DEFAULTS);

  React.useEffect(() => {
    document.documentElement.setAttribute('data-theme', t.theme);
    document.documentElement.setAttribute('data-accent', t.accent);
  }, [t.theme, t.accent]);

  return (
    <>
      <TweaksPanel title="Nivesh · Tweaks">
        <TweakSection title="Theme">
          <TweakRadio label="Mode" value={t.theme} onChange={(v) => setTweak('theme', v)}
            options={[{ value: 'dark', label: 'Dark' }, { value: 'light', label: 'Light' }]} />
        </TweakSection>
      </TweaksPanel>

      <DesignCanvas>
        <DCSection id="brand" title="01 · Foundation" subtitle="A premium fintech dark with an editorial spine. Type, color, motion follow.">
          <DCArtboard id="tokens" label="Design tokens" width={1100} height={620}>
            <NVTokensSheet />
          </DCArtboard>
        </DCSection>

        <DCSection id="home" title="02 · Homepage" subtitle="One promise, one preview, three reasons. No marketing fluff.">
          <DCArtboard id="home-desktop" label="Desktop · 1440" width={1440} height={920}>
            <NVHomepageDesktop />
          </DCArtboard>
          <DCArtboard id="home-mobile" label="Mobile · 390" width={390} height={844}>
            <NVHomepageMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="login" title="03 · Sign in" subtitle="Editorial split — last-state context on left, one-tap auth on right.">
          <DCArtboard id="login-desktop" label="Desktop · 1440" width={1440} height={920}>
            <NVLoginDesktop />
          </DCArtboard>
          <DCArtboard id="login-mobile" label="Mobile · 390" width={390} height={844}>
            <NVLoginMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="onboard" title="04 · Onboarding · Connect investments" subtitle="Three CAS-Parser methods in one screen: Gmail inbox, eCAS PDF upload, CDSL OTP. User picks the easiest.">
          <DCArtboard id="onboard-desktop" label="Desktop · 1440" width={1440} height={920}>
            <NVOnboardingDesktop />
          </DCArtboard>
          <DCArtboard id="onboard-mobile" label="Mobile · 390" width={390} height={844}>
            <NVOnboardingMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="chat" title="05 · Chat copilot" subtitle="Synthesis surface. Reads your portfolio, opens with a sentence, ends with three ranked moves.">
          <DCArtboard id="chat-desktop" label="Desktop · 1440" width={1440} height={920}>
            <NVChatDesktop />
          </DCArtboard>
          <DCArtboard id="chat-mobile" label="Mobile · 390" width={390} height={844}>
            <NVChatMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="conc" title="06 · Dashboard · Concentration" subtitle="Treemap is the right chart for weights. Click any tile, the right rail tells you why it's flagged.">
          <DCArtboard id="conc-desktop" label="Desktop · 1440" width={1440} height={1020}>
            <NVDashConcentrationDesktop />
          </DCArtboard>
          <DCArtboard id="conc-mobile" label="Mobile · 390" width={390} height={844}>
            <NVDashConcentrationMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="diverse" title="07 · Dashboard · Diversification" subtitle="Correlation matrix surfaces redundant pairs. ICICI ↔ HDFC at 0.86 is one trade in disguise.">
          <DCArtboard id="diverse-desktop" label="Desktop · 1440" width={1440} height={1020}>
            <NVDashDiversificationDesktop />
          </DCArtboard>
          <DCArtboard id="diverse-mobile" label="Mobile · 390" width={390} height={844}>
            <NVDashDiversificationMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="risk" title="08 · Dashboard · Risk" subtitle="VaR fan chart projects 1Y forward with 68/95 bands; 5 stress scenarios in the table below.">
          <DCArtboard id="risk-desktop" label="Desktop · 1440" width={1440} height={1020}>
            <NVDashRiskDesktop />
          </DCArtboard>
          <DCArtboard id="risk-mobile" label="Mobile · 390" width={390} height={844}>
            <NVDashRiskMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="perf" title="09 · Dashboard · Performance" subtitle="Attribution waterfall decomposes the +2.1 pp alpha into 5 sources. Monthly hit-rate grid below.">
          <DCArtboard id="perf-desktop" label="Desktop · 1440" width={1440} height={1020}>
            <NVDashPerformanceDesktop />
          </DCArtboard>
          <DCArtboard id="perf-mobile" label="Mobile · 390" width={390} height={844}>
            <NVDashPerformanceMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="goals" title="10 · Dashboard · Goals" subtitle="Fan trajectory with goal markers; the daughter's MS goal is the one that's behind.">
          <DCArtboard id="goals-desktop" label="Desktop · 1440" width={1440} height={1020}>
            <NVDashGoalsDesktop />
          </DCArtboard>
          <DCArtboard id="goals-mobile" label="Mobile · 390" width={390} height={844}>
            <NVDashGoalsMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="tax" title="11 · Dashboard · Tax" subtitle="FY timeline shows realised gains above the line, harvest opportunities below. March-end window highlighted.">
          <DCArtboard id="tax-desktop" label="Desktop · 1440" width={1440} height={1020}>
            <NVDashTaxDesktop />
          </DCArtboard>
          <DCArtboard id="tax-mobile" label="Mobile · 390" width={390} height={844}>
            <NVDashTaxMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="plan" title="12 · Plan board" subtitle="Kanban for the planning loop — Backlog · This week · In flight · Done.">
          <DCArtboard id="plan-desktop" label="Desktop · 1440" width={1440} height={1020}>
            <NVPlanBoardDesktop />
          </DCArtboard>
          <DCArtboard id="plan-mobile" label="Mobile · 390" width={390} height={844}>
            <NVPlanBoardMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="builder" title="13 · Portfolio builder" subtitle="Direct manipulation: drag sliders, the donut and projection update; the rail shows live impact.">
          <DCArtboard id="builder-desktop" label="Desktop · 1440" width={1440} height={1020}>
            <NVPortfolioBuilderDesktop />
          </DCArtboard>
          <DCArtboard id="builder-mobile" label="Mobile · 390" width={390} height={844}>
            <NVPortfolioBuilderMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="recs" title="14 · Recommendations" subtitle="Six moves take 86 to 94. Each has a one-tap simulation before commitment.">
          <DCArtboard id="recs-desktop" label="Desktop · 1440" width={1440} height={1240}>
            <NVRecommendationsDesktop />
          </DCArtboard>
          <DCArtboard id="recs-mobile" label="Mobile · 390" width={390} height={844}>
            <NVRecommendationsMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="instr" title="15 · Instrument allocation" subtitle="Sankey flows from vehicle → asset class → exposure. Selects propagate to the rail.">
          <DCArtboard id="instr-desktop" label="Desktop · 1440" width={1440} height={1020}>
            <NVInstrumentAllocationDesktop />
          </DCArtboard>
          <DCArtboard id="instr-mobile" label="Mobile · 390" width={390} height={844}>
            <NVInstrumentAllocationMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="adv" title="16 · Advisor · Client 360" subtitle="Advisor's single client surface. AUM, drift, alerts, activity, goals — all on one screen.">
          <DCArtboard id="adv-desktop" label="Desktop · 1440" width={1440} height={1020}>
            <NVAdvisorClient360Desktop />
          </DCArtboard>
          <DCArtboard id="adv-mobile" label="Mobile · 390" width={390} height={844}>
            <NVAdvisorClient360Mobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="advbook" title="17 · Advisor · Book" subtitle="Cohort scatter shows AUM × XIRR with health as bubble size. Outliers drop into the at-risk rail.">
          <DCArtboard id="advbook-desktop" label="Desktop · 1440" width={1440} height={1020}>
            <NVAdvisorBookDesktop />
          </DCArtboard>
          <DCArtboard id="advbook-mobile" label="Mobile · 390" width={390} height={844}>
            <NVAdvisorBookMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="sip" title="18 · Advisor · SIP board" subtitle="Calendar heatmap of SIP runs across the month; failed runs surface as red dots.">
          <DCArtboard id="sip-desktop" label="Desktop · 1440" width={1440} height={1020}>
            <NVSipBoardDesktop />
          </DCArtboard>
          <DCArtboard id="sip-mobile" label="Mobile · 390" width={390} height={844}>
            <NVSipBoardMobile />
          </DCArtboard>
        </DCSection>
      </DesignCanvas>
    </>
  );
}

function NVTokensSheet() {
  const Swatch = ({ name, v, label }) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ width: '100%', height: 56, background: `var(--${v})`, border: '1px solid var(--line)', borderRadius: 10 }} />
      <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '.06em' }}>{label || `--${v}`}</div>
      <div style={{ fontSize: 11.5, fontWeight: 500 }}>{name}</div>
    </div>
  );
  return (
    <div className="nv-frame" style={{ width: '100%', height: '100%', padding: '32px 40px', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 20, marginBottom: 22 }}>
        <span className="nv-mark" style={{ width: 40, height: 40, fontSize: 22 }}>न</span>
        <div className="nv-serif" style={{ fontSize: 32, letterSpacing: '-0.025em' }}>Nivesh design system</div>
        <span className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '.1em', textTransform: 'uppercase' }}>v0.1 · premium fintech dark + light</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 28 }}>
        {/* Type */}
        <div>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 14 }}>Type</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
              <div className="nv-serif" style={{ fontSize: 56, letterSpacing: '-0.035em', lineHeight: 1 }}>Your portfolio, <i>finally</i> legible.</div>
              <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4, letterSpacing: '.04em' }}>Instrument Serif · display · 56–84 / -0.035em</div>
            </div>
            <div>
              <div style={{ fontSize: 24, lineHeight: 1.3 }}>Read every holding. Score it across twenty checks. Show ranked actions with the exact instrument.</div>
              <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4, letterSpacing: '.04em' }}>Inter Tight · body · 14–24</div>
            </div>
            <div>
              <div className="nv-mono" style={{ fontSize: 16, color: 'var(--ink)' }}>NIDP · CONCENTRATION · ₹2,41,000</div>
              <div className="nv-mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4, letterSpacing: '.04em' }}>JetBrains Mono · meta + numerals · tabular</div>
            </div>
          </div>
        </div>

        {/* Color */}
        <div>
          <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 14 }}>Color</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
            <Swatch name="Surface" v="bg-0" label="page" />
            <Swatch name="Card" v="bg-1" label="card" />
            <Swatch name="Raised" v="bg-2" label="raised" />
            <Swatch name="Mint" v="mint" label="growth" />
            <Swatch name="Amber" v="amber" label="warn" />
            <Swatch name="Indigo" v="indigo" label="info" />
            <Swatch name="Rose" v="danger" label="risk" />
            <Swatch name="Ink" v="ink" label="text" />
            <Swatch name="Mute" v="ink-3" label="meta" />
          </div>
        </div>
      </div>

      {/* components */}
      <div className="nv-mono" style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginTop: 24, marginBottom: 12 }}>Primitives</div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <button className="nv-btn nv-btn-primary" style={{ padding: '11px 18px' }}>Primary action</button>
        <button className="nv-btn">Secondary</button>
        <span className="nv-pill nv-pill-mint"><span className="nv-dot" style={{ background: 'var(--mint)' }} />HEALTHY</span>
        <span className="nv-pill nv-pill-amber">ATTENTION</span>
        <span className="nv-pill nv-pill-indigo">INFO</span>
        <span className="nv-pill nv-pill-danger">RISK</span>
        <div className="nv-card" style={{ padding: '10px 14px', display: 'inline-flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13 }}>Card</span>
          <span className="nv-mono nv-num" style={{ fontSize: 12, color: 'var(--mint)' }}>+₹46,300</span>
        </div>
        <div className="nv-glass" style={{ padding: '10px 14px', display: 'inline-flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13 }}>Glass</span>
          <span className="nv-mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>backdrop · 20px</span>
        </div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<NivApp />);
