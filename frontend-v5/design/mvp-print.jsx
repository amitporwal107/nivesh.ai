// ─── Nivesh MVP · PRINT layout ───
// Renders each artboard on its own page. Auto-fits via CSS transform.
// Used by Nivesh MVP-print.html — not the live canvas.

const PRINT_FRAMES = [
  { kind: 'desktop', label: '01 · Upload',         w: 1440, h: 900, Comp: () => <NVMUploadDesktop /> },
  { kind: 'mobile',  label: '01 · Upload',         w: 390,  h: 844, Comp: () => <NVMUploadMobile /> },
  { kind: 'desktop', label: '02 · Dashboard',      w: 1440, h: 900, Comp: () => <NVMDashboardDesktop /> },
  { kind: 'mobile',  label: '02 · Dashboard',      w: 390,  h: 844, Comp: () => <NVMDashboardMobile /> },
  { kind: 'desktop', label: '03 · Breakdown',      w: 1440, h: 900, Comp: () => <NVMBreakdownDesktop /> },
  { kind: 'mobile',  label: '03 · Breakdown',      w: 390,  h: 844, Comp: () => <NVMBreakdownMobile /> },
  { kind: 'desktop', label: '04 · Recommendations',w: 1440, h: 900, Comp: () => <NVMRecsDesktop /> },
  { kind: 'mobile',  label: '04 · Recommendations',w: 390,  h: 844, Comp: () => <NVMRecsMobile /> },
  { kind: 'desktop', label: '05 · AI Chat',        w: 1440, h: 900, Comp: () => <NVMChatDesktop /> },
  { kind: 'mobile',  label: '05 · AI Chat',        w: 390,  h: 844, Comp: () => <NVMChatMobile /> },
];

function PrintPage({ frame, last }) {
  // Landscape A4 minus margins ~ 277mm × 190mm ~ 1047 × 718px @ 96dpi.
  // Desktop frame is 1440×900 → fits with scale ~0.72.
  // Mobile frame is 390×844 → fits portrait of the same page, centered.
  const PAGE_W = 1047, PAGE_H = 718;
  const sx = PAGE_W / frame.w;
  const sy = PAGE_H / frame.h;
  const s = Math.min(sx, sy);
  const scaledW = frame.w * s;
  const scaledH = frame.h * s;

  return (
    <div className="print-page" style={{ pageBreakAfter: last ? 'auto' : 'always', breakAfter: last ? 'auto' : 'page' }}>
      <div className="print-header">
        <span className="print-mark">न</span>
        <span className="print-title">Nivesh MVP</span>
        <span className="print-divider">·</span>
        <span className="print-label">{frame.label}</span>
        <span className="print-platform">{frame.kind.toUpperCase()}</span>
      </div>
      <div className="print-stage">
        <div className="print-frame-wrap" style={{ width: scaledW, height: scaledH }}>
          <div className="print-frame" style={{
            width: frame.w, height: frame.h,
            transform: `scale(${s})`,
            transformOrigin: 'top left',
          }}>
            <frame.Comp />
          </div>
        </div>
      </div>
    </div>
  );
}

function NVMPrintApp() {
  React.useEffect(() => {
    // wait for fonts + paint, then auto-print
    let cancelled = false;
    const trigger = async () => {
      try { await document.fonts.ready; } catch {}
      // 2 paint frames + 500ms safety
      requestAnimationFrame(() => requestAnimationFrame(() => {
        setTimeout(() => { if (!cancelled) window.print(); }, 500);
      }));
    };
    trigger();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="print-root">
      {PRINT_FRAMES.map((f, i) => (
        <PrintPage key={i} frame={f} last={i === PRINT_FRAMES.length - 1} />
      ))}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<NVMPrintApp />);
