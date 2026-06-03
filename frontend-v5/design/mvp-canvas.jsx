// ─── Nivesh MVP · canvas mount ───

const MVP_TWEAKS = /*EDITMODE-BEGIN*/{
  "mtheme": "light"
}/*EDITMODE-END*/;

function NVMApp() {
  const [t, setTweak] = useTweaks(MVP_TWEAKS);
  React.useEffect(() => {
    document.documentElement.setAttribute('data-mtheme', t.mtheme);
  }, [t.mtheme]);

  return (
    <>
      <TweaksPanel title="Nivesh MVP">
        <TweakSection title="Theme">
          <TweakRadio label="Mode" value={t.mtheme} onChange={(v) => setTweak('mtheme', v)}
            options={[{ value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }]} />
        </TweakSection>
      </TweaksPanel>

      <DesignCanvas>
        <DCSection id="upload" title="01 · Upload" subtitle="Three inputs: CAS PDF (best), broker statement, Excel. Parses → analyzes → shows health.">
          <DCArtboard id="upload-desktop" label="Desktop · 1440" width={1440} height={900}>
            <NVMUploadDesktop />
          </DCArtboard>
          <DCArtboard id="upload-mobile" label="Mobile · 390" width={390} height={844}>
            <NVMUploadMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="dashboard" title="02 · Dashboard" subtitle="Value · health score · risk · top 3 insights · one CTA. Nothing else.">
          <DCArtboard id="dashboard-desktop" label="Desktop · 1440" width={1440} height={900}>
            <NVMDashboardDesktop />
          </DCArtboard>
          <DCArtboard id="dashboard-mobile" label="Mobile · 390" width={390} height={844}>
            <NVMDashboardMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="breakdown" title="03 · Breakdown" subtitle="Four tabs: Allocation · Exposure · Fund overlap · Risk. One chart per tab, tab-switchable.">
          <DCArtboard id="breakdown-desktop" label="Desktop · 1440" width={1440} height={900}>
            <NVMBreakdownDesktop />
          </DCArtboard>
          <DCArtboard id="breakdown-mobile" label="Mobile · 390" width={390} height={844}>
            <NVMBreakdownMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="recs" title="04 · Recommendations" subtitle="Keep / Reduce / Add. Each card: why · benefit · risk · suggested action.">
          <DCArtboard id="recs-desktop" label="Desktop · 1440" width={1440} height={900}>
            <NVMRecsDesktop />
          </DCArtboard>
          <DCArtboard id="recs-mobile" label="Mobile · 390" width={390} height={844}>
            <NVMRecsMobile />
          </DCArtboard>
        </DCSection>

        <DCSection id="chat" title="05 · AI Chat" subtitle="Conversational assistant. Sample prompts, inline insight card, light composer.">
          <DCArtboard id="chat-desktop" label="Desktop · 1440" width={1440} height={900}>
            <NVMChatDesktop />
          </DCArtboard>
          <DCArtboard id="chat-mobile" label="Mobile · 390" width={390} height={844}>
            <NVMChatMobile />
          </DCArtboard>
        </DCSection>
      </DesignCanvas>
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<NVMApp />);
