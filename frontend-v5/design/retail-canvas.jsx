// ─── Nivesh Retail · canvas + tweaks ───

const RETAIL_TWEAKS = /*EDITMODE-BEGIN*/{
  "rtheme": "paper",
  "raccent": "sage",
  "rdensity": "comfortable",
  "rsize": "default"
}/*EDITMODE-END*/;

function NVRApp() {
  const [t, setTweak] = useTweaks(RETAIL_TWEAKS);

  React.useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-rtheme', t.rtheme);
    root.setAttribute('data-raccent', t.raccent);
    root.setAttribute('data-rdensity', t.rdensity);
    root.setAttribute('data-rsize', t.rsize);
  }, [t.rtheme, t.raccent, t.rdensity, t.rsize]);

  return (
    <>
      <TweaksPanel title="Make it yours">
        <TweakSection title="Look">
          <TweakRadio label="Theme" value={t.rtheme} onChange={(v) => setTweak('rtheme', v)}
            options={[
              { value: 'paper', label: 'Paper' },
              { value: 'white', label: 'White' },
              { value: 'dusk', label: 'Dusk' },
            ]} />
          <TweakRadio label="Accent" value={t.raccent} onChange={(v) => setTweak('raccent', v)}
            options={[
              { value: 'sage', label: 'Sage' },
              { value: 'coral', label: 'Coral' },
              { value: 'indigo', label: 'Indigo' },
              { value: 'saffron', label: 'Saffron' },
            ]} />
        </TweakSection>
        <TweakSection title="Comfort">
          <TweakRadio label="Density" value={t.rdensity} onChange={(v) => setTweak('rdensity', v)}
            options={[
              { value: 'cozy', label: 'Cozy' },
              { value: 'comfortable', label: 'Comfy' },
              { value: 'spacious', label: 'Roomy' },
            ]} />
          <TweakRadio label="Text size" value={t.rsize} onChange={(v) => setTweak('rsize', v)}
            options={[
              { value: 'default', label: 'Default' },
              { value: 'large', label: 'Large' },
              { value: 'x-large', label: 'XL' },
            ]} />
        </TweakSection>
      </TweaksPanel>

      <DesignCanvas>
        <DCSection id="today" title="01 · Today" subtitle="One number, one sentence, one suggested action.">
          <DCArtboard id="today-desktop" label="Desktop · 1440" width={1440} height={900}>
            <NVRTodayDesktop />
          </DCArtboard>
          <DCArtboard id="today-mobile" label="Mobile · 390" width={390} height={844}>
            <NVRTodayMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="health" title="02 · Money health" subtitle="One big score, four plain-language cards. No jargon.">
          <DCArtboard id="health-desktop" label="Desktop · 1440" width={1440} height={900}>
            <NVRHealthDesktop />
          </DCArtboard>
          <DCArtboard id="health-mobile" label="Mobile · 390" width={390} height={844}>
            <NVRHealthMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="where" title="03 · Where your money sits" subtitle="A donut and a sentence. The flagged slice has a one-tap fix.">
          <DCArtboard id="where-desktop" label="Desktop · 1440" width={1440} height={900}>
            <NVRWhereDesktop />
          </DCArtboard>
          <DCArtboard id="where-mobile" label="Mobile · 390" width={390} height={844}>
            <NVRWhereMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="goals" title="04 · My goals" subtitle="Emoji + progress bar. On-track / behind verdict.">
          <DCArtboard id="goals-desktop" label="Desktop · 1440" width={1440} height={900}>
            <NVRGoalsDesktop />
          </DCArtboard>
          <DCArtboard id="goals-mobile" label="Mobile · 390" width={390} height={844}>
            <NVRGoalsMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="fix" title="05 · Fix this" subtitle="Top 3 ranked by ₹. One big tap each.">
          <DCArtboard id="fix-desktop" label="Desktop · 1440" width={1440} height={900}>
            <NVRFixDesktop />
          </DCArtboard>
          <DCArtboard id="fix-mobile" label="Mobile · 390" width={390} height={844}>
            <NVRFixMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="settings" title="06 · Customize" subtitle="Theme · accent · text size · language · notifications.">
          <DCArtboard id="set-desktop" label="Desktop · 1440" width={1440} height={900}>
            <NVRSettingsDesktop />
          </DCArtboard>
          <DCArtboard id="set-mobile" label="Mobile · 390" width={390} height={844}>
            <NVRSettingsMobile />
          </DCArtboard>
        </DCSection>
      </DesignCanvas>
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<NVRApp />);
