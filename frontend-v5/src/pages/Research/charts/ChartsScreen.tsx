/**
 * Research → Charts. Read-only over the committed chart snapshot (research/charting/SNAPSHOT_SCHEMA.md) — nothing
 * on this screen is computed client-side; a field the snapshot doesn't have renders as "—", never a guess (the
 * SimulationLabScreen convention, `./SimulationLabScreen.tsx`). Kite-derived data, owner-only (NI-1): gated by
 * `require_feature("charting")`, same allowlist pattern as Simulation Lab and Move Odds.
 *
 * v1 scope (feasibility.md Part B): daily candles + volume, indicator overlays/panes, pattern overlays once the
 * detector batch lands (renders cleanly on the empty list today), trendline + horizontal-line drawings, one status
 * chip (B3), four independent pattern scores (never summed), a keyboard-reachable data-view table (B7 a11y scope).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ChartCanvas, { type ChartCanvasHandle } from "./ChartCanvas";
import DataView from "./DataView";
import {
  chartApi, drawingsApi, combinedStatus, statusTone, patternVisualCategory, isLevelPattern, statusLabel, patternTypeLabel,
  DASH, txt, price as fmtPrice, num as fmtNum,
  type Result, type RunPayload, type ManifestSymbolEntry, type OhlcvPayload, type IndicatorsPayload,
  type PatternsPayload, type Pattern, type Drawing, type NewDrawing, type DrawingType, type Bar,
} from "./contract";

type Tool = DrawingType | "select";

/** One shared fetch/40x/503 state block, echoing SimulationLabScreen's `Pending`. */
function Pending<T>({ result, label, children }: { result: Result<T> | null; label: string; children: (d: T) => React.ReactNode }) {
  if (result === null) return <p aria-busy="true" style={{ fontSize: 12.5, color: "var(--c-ink-3)", margin: 0 }}>Loading {label}…</p>;
  if (result.kind === "unavailable") return <p role="alert" style={{ fontSize: 12.5, color: "var(--c-ink-2)", margin: 0 }}>{label} unavailable.</p>;
  if (result.kind === "not_found") return <p role="alert" style={{ fontSize: 12.5, color: "var(--c-ink-2)", margin: 0 }}>Not found.</p>;
  if (result.kind === "error") return <p role="alert" style={{ fontSize: 12.5, color: "var(--c-ink-2)", margin: 0 }}>Could not load {label} ({result.message}).</p>;
  if (result.kind === "no_access") return null;
  return <>{children(result.data)}</>;
}

export default function ChartsScreen() {
  const [noAccess, setNoAccess] = useState(false);
  const [reload, setReload] = useState(0);
  const [runRes, setRunRes] = useState<Result<RunPayload> | null>(null);
  const [symbolsRes, setSymbolsRes] = useState<Result<ManifestSymbolEntry[]> | null>(null);
  const [search, setSearch] = useState("");
  const [symbol, setSymbol] = useState<string | null>(null);

  const [ohlcvRes, setOhlcvRes] = useState<Result<OhlcvPayload> | null>(null);
  const [indicatorsRes, setIndicatorsRes] = useState<Result<IndicatorsPayload> | null>(null);
  const [patternsRes, setPatternsRes] = useState<Result<PatternsPayload> | null>(null);
  const [drawingsRes, setDrawingsRes] = useState<Result<Drawing[]> | null>(null);

  const [selectedIndicatorIds, setSelectedIndicatorIds] = useState<string[]>([]);
  const [visiblePatternIds, setVisiblePatternIds] = useState<Set<string>>(new Set());
  // Support & resistance levels are a chart layer, not patterns — shown by default (owner, 2026-09-22).
  const [showLevels, setShowLevels] = useState(true);
  const [selectedPatternId, setSelectedPatternId] = useState<string | null>(null);

  const [tool, setTool] = useState<Tool>("select");
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [drawingError, setDrawingError] = useState<string | null>(null);

  const [showDataView, setShowDataView] = useState(false);
  type DrawerCtx =
    | { kind: "status" }
    | { kind: "bar"; bar: Bar }
    | { kind: "indicator"; id: string }
    | { kind: "rule"; pattern: Pattern; ruleId: string };
  const [drawer, setDrawer] = useState<DrawerCtx | null>(null);

  const canvasRef = useRef<ChartCanvasHandle | null>(null);

  const denyAll = useCallback(() => {
    setRunRes(null); setSymbolsRes(null); setOhlcvRes(null); setIndicatorsRes(null); setPatternsRes(null); setDrawingsRes(null);
    setNoAccess(true);
  }, []);

  // ── run + symbol list ────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setRunRes(null); setSymbolsRes(null); setNoAccess(false);
    chartApi.run().then((r) => { if (!cancelled) { if (r.kind === "no_access") denyAll(); else setRunRes(r); } });
    chartApi.symbols().then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      setSymbolsRes(r);
      if (r.kind === "ok" && r.data.length) setSymbol((cur) => cur ?? r.data[0].symbol);
    });
    return () => { cancelled = true; };
  }, [reload, denyAll]);

  // ── per-symbol payloads ──────────────────────────────────────────────────
  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setOhlcvRes(null); setIndicatorsRes(null); setPatternsRes(null); setDrawingsRes(null);
    setSelectedIndicatorIds([]); setVisiblePatternIds(new Set()); setSelectedPatternId(null); setShowLevels(true);
    setSelectedDrawingId(null); setTool("select"); setDrawer(null);

    chartApi.ohlcv(symbol).then((r) => { if (!cancelled) { if (r.kind === "no_access") denyAll(); else setOhlcvRes(r); } });
    chartApi.indicators(symbol).then((r) => { if (!cancelled) { if (r.kind === "no_access") denyAll(); else setIndicatorsRes(r); } });
    chartApi.patterns(symbol).then((r) => { if (!cancelled) { if (r.kind === "no_access") denyAll(); else setPatternsRes(r); } });
    drawingsApi.list(symbol).then((r) => { if (!cancelled) { if (r.kind === "no_access") denyAll(); else setDrawingsRes(r); } });
    return () => { cancelled = true; };
  }, [symbol, denyAll]);

  const bars = ohlcvRes?.kind === "ok" ? ohlcvRes.data.bars : [];
  const indicators = indicatorsRes?.kind === "ok" ? indicatorsRes.data.indicators : {};
  const patterns = patternsRes?.kind === "ok" ? patternsRes.data.patterns : [];
  const chartPatterns = patterns.filter((p) => !isLevelPattern(p));
  const levelPatterns = patterns.filter(isLevelPattern);
  const drawings = drawingsRes?.kind === "ok" ? drawingsRes.data : [];
  const fixture = runRes?.kind === "ok" ? runRes.data.fixture : false;

  const status = ohlcvRes?.kind === "ok" ? combinedStatus(ohlcvRes.data.data_quality_status, ohlcvRes.data.pit_status) : null;

  // ── drawing create / delete ──────────────────────────────────────────────
  const onCreateDrawing = useCallback(async (d: NewDrawing) => {
    setDrawingError(null);
    const r = await drawingsApi.create(d);
    if (r.kind === "ok") setDrawingsRes((cur) => ({ kind: "ok", data: [...(cur?.kind === "ok" ? cur.data : []), r.data] }));
    else if (r.kind === "no_access") denyAll();
    else setDrawingError(r.kind === "error" ? r.message : "Could not save the drawing.");
  }, [denyAll]);

  // Accepts an explicit id so a row's own delete button can select-and-delete in one click without racing React's
  // async state update — reading `selectedDrawingId` right after `setSelectedDrawingId` in the same handler would
  // still see the PREVIOUS value (a stale closure), so the id is threaded through explicitly instead.
  const deleteSelected = useCallback(async (idOverride?: string) => {
    const id = idOverride ?? selectedDrawingId;
    if (!id) return;
    setDrawingError(null);
    const r = await drawingsApi.remove(id);
    if (r.kind === "ok") {
      setDrawingsRes((cur) => (cur?.kind === "ok" ? { kind: "ok", data: cur.data.filter((x) => x.drawing_id !== id) } : cur));
      setSelectedDrawingId((cur) => (cur === id ? null : cur));
    } else if (r.kind === "no_access") denyAll();
    else setDrawingError(r.kind === "error" ? r.message : "Could not delete the drawing.");
  }, [selectedDrawingId, denyAll]);

  // ── keyboard: Escape cancels a pending drawing / clears selection; Delete removes the selected drawing ──
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(input|textarea|select)$/i.test(target.tagName)) return;
      if (e.key === "Escape") {
        canvasRef.current?.cancelPending();
        if (tool !== "select") setTool("select");
        setSelectedDrawingId(null);
      } else if ((e.key === "Delete" || e.key === "Backspace") && selectedDrawingId) {
        e.preventDefault();
        void deleteSelected();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tool, selectedDrawingId, deleteSelected]);

  const toggleIndicator = (id: string) =>
    setSelectedIndicatorIds((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));

  const togglePatternVisible = (id: string) =>
    setVisiblePatternIds((cur) => { const next = new Set(cur); if (next.has(id)) next.delete(id); else next.add(id); return next; });

  const selectPattern = (p: Pattern) => {
    setSelectedPatternId(p.pattern_id);
    setVisiblePatternIds((cur) => (cur.has(p.pattern_id) ? cur : new Set(cur).add(p.pattern_id)));
  };

  const symbolRows = useMemo(() => {
    const list = symbolsRes?.kind === "ok" ? symbolsRes.data : [];
    const q = search.trim().toUpperCase();
    return q ? list.filter((s) => s.symbol.toUpperCase().includes(q)) : list;
  }, [symbolsRes, search]);

  const selectedPattern = patterns.find((p) => p.pattern_id === selectedPatternId) ?? null;

  /* ── access / top-level states ──────────────────────────────────────────── */
  if (noAccess) {
    return (
      <Shell>
        <div className="nv-card" role="status" data-testid="charts-state-no_access" style={{ padding: 22 }}>
          <h3 className="nv-serif" style={{ fontSize: 20, margin: 0 }}>Charts is not enabled for your account</h3>
          <p style={{ fontSize: 13.5, color: "var(--c-ink-2)", margin: "8px 0 0" }}>
            It is an internal research surface over Kite-derived prices, open to invited accounts only.
          </p>
        </div>
      </Shell>
    );
  }
  if (runRes === null || symbolsRes === null) {
    return (
      <Shell>
        <div className="nv-card" aria-busy="true" data-testid="charts-state-loading" style={{ padding: 22, display: "grid", gap: 10 }}>
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} style={{ height: 14, borderRadius: 6, background: "var(--bg-3)", width: `${90 - i * 8}%` }} />
          ))}
          <span className="sr-only">Loading the chart snapshot…</span>
        </div>
      </Shell>
    );
  }
  if (runRes.kind === "unavailable" || symbolsRes.kind === "unavailable") {
    return (
      <Shell>
        <div className="nv-card" role="alert" data-testid="charts-state-unavailable" style={{ padding: 22 }}>
          <h3 className="nv-serif" style={{ fontSize: 20, margin: 0 }}>Chart snapshot unavailable</h3>
          <p style={{ fontSize: 13.5, color: "var(--c-ink-2)", margin: "8px 0 0" }}>
            The published snapshot is missing or did not match the expected schema, so nothing is shown.
          </p>
          <button type="button" className="nv-btn" data-testid="charts-retry" style={{ marginTop: 14 }} onClick={() => setReload((n) => n + 1)}>
            Try again
          </button>
        </div>
      </Shell>
    );
  }
  if (runRes.kind === "error" || symbolsRes.kind === "error") {
    const msg = runRes.kind === "error" ? runRes.message : symbolsRes.kind === "error" ? symbolsRes.message : "unknown error";
    return (
      <Shell>
        <div className="nv-card" role="alert" data-testid="charts-state-error" style={{ padding: 22 }}>
          <h3 className="nv-serif" style={{ fontSize: 20, margin: 0 }}>The chart snapshot could not be loaded</h3>
          <p style={{ fontSize: 13.5, color: "var(--c-ink-2)", margin: "8px 0 0" }}>The service did not answer ({msg}).</p>
          <button type="button" className="nv-btn" data-testid="charts-retry" style={{ marginTop: 14 }} onClick={() => setReload((n) => n + 1)}>
            Try again
          </button>
        </div>
      </Shell>
    );
  }
  if (runRes.kind !== "ok" || symbolsRes.kind !== "ok") return null;
  const run = runRes.data;
  const allSymbols = symbolsRes.data;

  if (allSymbols.length === 0) {
    return (
      <Shell>
        <div className="nv-card" data-testid="charts-state-empty" style={{ padding: 22 }}>
          <h3 className="nv-serif" style={{ fontSize: 20, margin: 0 }}>No symbols in this snapshot</h3>
          <p style={{ fontSize: 13.5, color: "var(--c-ink-2)", margin: "8px 0 0" }}>The published run carries an empty universe.</p>
        </div>
      </Shell>
    );
  }

  const symEntry = allSymbols.find((s) => s.symbol === symbol) ?? null;
  const ohlcvNotFound = ohlcvRes?.kind === "not_found";

  return (
    <Shell>
      {fixture && (
        <div role="alert" data-testid="chart-banner-fixture" style={{ border: "1px solid var(--danger-line)", background: "var(--danger-soft)", borderRadius: 12, padding: "12px 14px", color: "var(--c-ink)", fontSize: 13, lineHeight: 1.55 }}>
          <b className="nv-mono" style={{ fontSize: 10.5, letterSpacing: ".1em", marginRight: 8, color: "var(--danger-hex)" }}>SYNTHETIC DEVELOPMENT DATA</b>
          This snapshot is placeholder data for building the page — <b>not real market data</b>. No number here may be quoted, reported or acted on.
        </div>
      )}
      <div role="note" style={{ border: "1px solid var(--c-line-strong)", borderRadius: 12, padding: "12px 14px", background: "var(--bg-1)", color: "var(--c-ink-2)", fontSize: 12.5, lineHeight: 1.55 }}>
        <b className="nv-mono" style={{ fontSize: 10.5, letterSpacing: ".1em", color: "var(--c-ink)", marginRight: 6 }}>INTERNAL ONLY</b>
        Kite-derived prices, frozen research run {txt(run.run_id)}. Not for redistribution, and not investment advice.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "240px minmax(0,1fr) 300px", gap: 16, alignItems: "start" }}>
        {/* ── sidebar: symbol list ── */}
        <div className="nv-card" data-testid="chart-symbol-list" style={{ padding: 12, maxHeight: 640, overflowY: "auto" }}>
          <input
            value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filter symbols…"
            aria-label="Filter symbols" data-testid="chart-symbol-search"
            style={{ width: "100%", marginBottom: 10, padding: "7px 10px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--c-ink)", fontSize: 12.5 }}
          />
          {symbolRows.map((s) => (
            <button
              key={s.symbol} type="button" data-testid={`chart-symbol-${s.symbol}`}
              onClick={() => setSymbol(s.symbol)}
              aria-current={symbol === s.symbol ? "true" : undefined}
              style={{
                display: "flex", justifyContent: "space-between", width: "100%", textAlign: "left", padding: "8px 9px",
                borderRadius: 8, border: 0, cursor: "pointer", marginBottom: 2, fontSize: 12.5,
                background: symbol === s.symbol ? "var(--mint-soft)" : "transparent",
                color: symbol === s.symbol ? "var(--mint)" : "var(--c-ink-2)",
              }}
            >
              <span className="nv-mono">{s.symbol}</span>
              {s.n_patterns > 0 && <span className="nv-mono" style={{ fontSize: 10, color: "var(--c-ink-4)" }}>{s.n_patterns}</span>}
            </button>
          ))}
          {symbolRows.length === 0 && <p style={{ fontSize: 12, color: "var(--c-ink-4)", margin: "6px 2px" }}>No symbol matches "{search}".</p>}
        </div>

        {/* ── centre: chart ── */}
        <div style={{ display: "grid", gap: 12, minWidth: 0 }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 }}>
            <h2 className="nv-serif" style={{ fontSize: 22, margin: 0 }}>{symbol ?? DASH}</h2>
            {status && (
              <button
                type="button" data-testid="chart-status-chip" onClick={() => setDrawer({ kind: "status" })}
                className={`nv-pill nv-pill-${statusTone(status)}`} style={{ cursor: "pointer", border: 0 }}
              >
                {status}
              </button>
            )}
            <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
              <button type="button" className="nv-btn" data-testid="chart-fit" onClick={() => canvasRef.current?.fit()}>Fit</button>
              <button type="button" className="nv-btn" data-testid="chart-fullscreen" onClick={() => canvasRef.current?.toggleFullscreen()}>Full screen</button>
              <button type="button" className="nv-btn" data-testid="chart-dataview-toggle" aria-pressed={showDataView} onClick={() => setShowDataView((v) => !v)}>
                Data view
              </button>
            </span>
          </div>

          {/* timeframe */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <button type="button" className="nv-btn" data-testid="chart-timeframe-daily" aria-pressed="true">Daily</button>
            <button type="button" className="nv-btn" data-testid="chart-timeframe-weekly" disabled aria-disabled="true" title="Weekly needs longer history (spec G-6)">Weekly</button>
            <button type="button" className="nv-btn" data-testid="chart-timeframe-monthly" disabled aria-disabled="true" title="Monthly needs longer history (spec G-6)">Monthly</button>
            <span data-testid="chart-timeframe-reason" className="nv-mono" style={{ fontSize: 10.5, color: "var(--c-ink-4)" }}>
              Weekly / Monthly disabled — needs longer history (spec G-6)
            </span>
          </div>

          {/* drawing toolbar */}
          <div role="toolbar" aria-label="Drawing tools" style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            {(["select", "TRENDLINE", "HORIZONTAL_LINE"] as Tool[]).map((t) => (
              <button
                key={t} type="button" data-testid={`chart-tool-${t === "select" ? "select" : t === "TRENDLINE" ? "trendline" : "horizontal"}`}
                aria-pressed={tool === t} onClick={() => { setTool(t); canvasRef.current?.cancelPending(); }}
                className="nv-btn" style={tool === t ? { borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" } : undefined}
              >
                {t === "select" ? "Select" : t === "TRENDLINE" ? "Trendline" : "Horizontal line"}
              </button>
            ))}
            <button type="button" data-testid="chart-tool-delete" className="nv-btn" disabled={!selectedDrawingId} onClick={() => void deleteSelected()}>
              Delete
            </button>
            {drawingError && <span role="alert" style={{ fontSize: 11.5, color: "var(--danger-hex)" }}>{drawingError}</span>}
          </div>

          <Pending result={ohlcvRes} label="OHLCV">
            {() => (
              <ChartCanvas
                ref={canvasRef}
                symbol={symbol ?? ""}
                bars={bars}
                indicators={indicators}
                selectedIndicatorIds={selectedIndicatorIds}
                patterns={chartPatterns}
                visiblePatternIds={visiblePatternIds}
                levels={levelPatterns}
                showLevels={showLevels}
                drawings={drawings}
                activeTool={tool}
                selectedDrawingId={selectedDrawingId}
                onSelectDrawing={setSelectedDrawingId}
                onCreateDrawing={onCreateDrawing}
                onBarClick={(bar) => setDrawer({ kind: "bar", bar })}
              />
            )}
          </Pending>
          {ohlcvNotFound && (
            <div className="nv-card" role="alert" data-testid="charts-state-not_found" style={{ padding: 16 }}>
              <p style={{ margin: 0, fontSize: 13.5, color: "var(--c-ink-2)" }}>Unknown symbol.</p>
            </div>
          )}

          {showDataView && <DataView symbol={symbol ?? ""} bars={bars} patterns={chartPatterns} levels={showLevels ? levelPatterns : []} />}

          {/* drawings list — distinct testid/class from pattern overlays (task item 7) */}
          <div className="nv-card" data-testid="chart-drawings-list" style={{ padding: 14 }}>
            <p className="nv-eyebrow" style={{ margin: "0 0 8px" }}>Your drawings</p>
            {drawings.length === 0 ? (
              <p style={{ margin: 0, fontSize: 12.5, color: "var(--c-ink-3)" }}>No drawings on {symbol} yet — pick a tool above and click the chart.</p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 4 }}>
                {drawings.map((d) => (
                  <li
                    key={d.drawing_id} data-testid={`chart-drawing-row-${d.drawing_id}`}
                    onClick={() => setSelectedDrawingId(d.drawing_id)}
                    style={{
                      display: "flex", alignItems: "center", gap: 8, fontSize: 12, padding: "6px 8px", borderRadius: 8, cursor: "pointer",
                      background: selectedDrawingId === d.drawing_id ? "var(--bg-2)" : "transparent",
                    }}
                  >
                    <span className="nv-mono" style={{ color: "var(--c-ink-3)" }}>{d.drawing_type === "TRENDLINE" ? "Trendline" : "Horizontal line"}</span>
                    <span style={{ flex: 1, minWidth: 0, color: "var(--c-ink-4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {d.anchor_points.map((a) => `${a.date}@${fmtPrice(a.price)}`).join(" → ")}
                    </span>
                    <button
                      type="button" data-testid={`chart-drawing-delete-${d.drawing_id}`}
                      onClick={(e) => { e.stopPropagation(); void deleteSelected(d.drawing_id); }}
                      aria-label="Delete drawing" className="rail-ico" style={{ width: 22, height: 22, borderRadius: 999 }}
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* ── right: indicators + patterns ── */}
        <div style={{ display: "grid", gap: 14 }}>
          <div className="nv-card" data-testid="chart-indicators-panel" style={{ padding: 14 }}>
            <p className="nv-eyebrow" style={{ margin: "0 0 8px" }}>Indicators</p>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "var(--c-ink-2)", cursor: "pointer", marginBottom: 8 }}>
              <input type="checkbox" data-testid="chart-sr-toggle" checked={showLevels} onChange={() => setShowLevels((v) => !v)} />
              <span>Support &amp; resistance</span>
              <span data-testid="chart-sr-count" style={{ color: "var(--c-ink-4)", fontSize: 10.5 }}>
                {patternsRes?.kind === "ok" ? `${levelPatterns.length} level${levelPatterns.length === 1 ? "" : "s"}` : ""}
              </span>
            </label>
            <Pending result={indicatorsRes} label="indicators">
              {(d) => {
                const ids = Object.keys(d.indicators);
                if (!ids.length) return <p style={{ margin: 0, fontSize: 12.5, color: "var(--c-ink-3)" }}>No indicators in this snapshot.</p>;
                return (
                  <div style={{ display: "grid", gap: 6 }}>
                    {ids.map((id) => (
                      <div key={id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <label style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0, fontSize: 12.5, color: "var(--c-ink-2)", cursor: "pointer" }}>
                          <input
                            type="checkbox" data-testid={`chart-indicator-toggle-${id}`}
                            checked={selectedIndicatorIds.includes(id)} onChange={() => toggleIndicator(id)}
                          />
                          <span className="nv-mono">{id}</span>
                          <span style={{ color: "var(--c-ink-4)", fontSize: 10.5 }}>{d.indicators[id].pane === "price" ? "overlay" : `pane · ${d.indicators[id].pane}`}</span>
                        </label>
                        <button
                          type="button" data-testid={`chart-indicator-info-${id}`} aria-label={`${id} provenance`}
                          onClick={() => setDrawer({ kind: "indicator", id })} className="rail-ico" style={{ width: 20, height: 20, borderRadius: 999, fontSize: 10 }}
                        >
                          i
                        </button>
                      </div>
                    ))}
                  </div>
                );
              }}
            </Pending>
          </div>

          <div className="nv-card" data-testid="chart-patterns-panel" style={{ padding: 14 }}>
            <p className="nv-eyebrow" style={{ margin: "0 0 8px" }}>Patterns</p>
            <Pending result={patternsRes} label="patterns">
              {(d) => {
                const rows = d.patterns.filter((p) => !isLevelPattern(p));
                return rows.length === 0 ? (
                  <p data-testid="chart-patterns-empty" style={{ margin: 0, fontSize: 12.5, color: "var(--c-ink-3)" }}>
                    No chart patterns found.
                  </p>
                ) : (
                  <div style={{ display: "grid", gap: 6 }}>
                    {rows.map((p) => {
                      const cat = patternVisualCategory(p);
                      return (
                        <div key={p.pattern_id} data-testid={`chart-pattern-row-${p.pattern_id}`} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 8px", borderRadius: 8, background: selectedPatternId === p.pattern_id ? "var(--bg-2)" : "transparent" }}>
                          <input
                            type="checkbox" data-testid={`chart-pattern-visible-${p.pattern_id}`} aria-label={`Show ${p.pattern_type} overlay`}
                            checked={visiblePatternIds.has(p.pattern_id)} onChange={() => togglePatternVisible(p.pattern_id)}
                          />
                          <button type="button" onClick={() => selectPattern(p)} style={{ flex: 1, minWidth: 0, textAlign: "left", background: "none", border: 0, cursor: "pointer", padding: 0 }}>
                            <span style={{ fontSize: 12.5, color: "var(--c-ink)" }}>{patternTypeLabel(p.pattern_type)}</span>{" "}
                            <span className="nv-mono" data-testid={`chart-pattern-status-${p.pattern_id}`} data-category={cat} style={{ fontSize: 10, color: "var(--c-ink-4)" }}>{statusLabel(p)}</span>
                          </button>
                        </div>
                      );
                    })}
                  </div>
                );
              }}
            </Pending>

            {selectedPattern && (
              <div style={{ marginTop: 12, borderTop: "1px solid var(--c-line)", paddingTop: 12 }}>
                <p className="nv-eyebrow" style={{ margin: "0 0 8px" }}>{selectedPattern.pattern_type} · rules</p>
                <ul style={{ listStyle: "none", margin: "0 0 12px", padding: 0, display: "grid", gap: 4 }}>
                  {(selectedPattern.rules ?? []).map((r) => (
                    <li key={r.rule_id} data-testid={`chart-pattern-rule-${r.rule_id}`}>
                      <button
                        type="button" onClick={() => setDrawer({ kind: "rule", pattern: selectedPattern, ruleId: r.rule_id })}
                        style={{ display: "flex", justifyContent: "space-between", width: "100%", background: "none", border: 0, cursor: "pointer", padding: "3px 0", fontSize: 12, color: "var(--c-ink-2)" }}
                      >
                        <span>{r.rule_id}</span>
                        <span className={`nv-mono ${r.result === "PASS" ? "sig-good" : r.result === "FAIL" ? "sig-risk" : "sig-info"}`}>{r.result}</span>
                      </button>
                    </li>
                  ))}
                  {(!selectedPattern.rules || selectedPattern.rules.length === 0) && <li style={{ fontSize: 12, color: "var(--c-ink-4)" }}>No rules recorded.</li>}
                </ul>

                <p className="nv-eyebrow" style={{ margin: "0 0 6px" }}>Scores</p>
                {selectedPattern.scores ? (
                  <div data-testid="chart-scores" style={{ display: "grid", gap: 8 }}>
                    {(["formation", "readiness", "confirmation", "failure_risk"] as const).map((k) => {
                      const v = selectedPattern.scores![k];
                      const label = k === "failure_risk" ? "Failure risk" : k[0].toUpperCase() + k.slice(1);
                      return (
                        <div key={k} data-testid={`chart-score-${k}`}>
                          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--c-ink-3)" }}>
                            <span>{label}</span><span className="nv-mono">{fmtNum(v, 0)}</span>
                          </div>
                          <div style={{ height: 6, borderRadius: 999, background: "var(--bg-3)", overflow: "hidden" }}>
                            <div style={{ height: "100%", width: `${Math.max(0, Math.min(100, v))}%`, background: "var(--mint)" }} />
                          </div>
                        </div>
                      );
                    })}
                    <p style={{ margin: "2px 0 0", fontSize: 10.5, color: "var(--c-ink-4)" }}>Each is a score, not a probability — never summed into one number.</p>
                  </div>
                ) : (
                  <p style={{ margin: 0, fontSize: 11.5, color: "var(--c-ink-4)" }}>No scores in this snapshot.</p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── provenance drawer (B6) ── */}
      {drawer && symEntry && (
        <ProvenanceDrawer
          ctx={drawer} onClose={() => setDrawer(null)}
          runId={run.run_id} configHash={run.config_hash} generatedAt={run.generated_at}
          source={run.source} symEntry={symEntry}
          provenance={ohlcvRes?.kind === "ok" ? ohlcvRes.data.provenance : null}
          indicators={indicators}
        />
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div data-testid="charts-screen" className="px-4 pt-5 pb-10 lg:px-6" style={{ display: "grid", gap: 16, maxWidth: 1440, margin: "0 auto", minWidth: 0 }}>
      <div>
        <h2 className="nv-serif" style={{ fontSize: 30, lineHeight: 1.1, margin: 0 }}>Charts</h2>
        <p style={{ fontSize: 14, color: "var(--c-ink-2)", margin: "8px 0 0", maxWidth: "70ch" }}>
          Daily candles, indicators and detected patterns from a frozen research snapshot — read-only, with your own
          trendlines and levels on top.
        </p>
      </div>
      {children}
    </div>
  );
}

/* ── provenance drawer ───────────────────────────────────────────────────── */
function ProvenanceDrawer({ ctx, onClose, runId, configHash, generatedAt, source, symEntry, provenance, indicators }: {
  ctx: { kind: "status" } | { kind: "bar"; bar: Bar } | { kind: "indicator"; id: string } | { kind: "rule"; pattern: Pattern; ruleId: string };
  onClose: () => void; runId: string; configHash: string; generatedAt: string;
  source: RunPayload["source"]; symEntry: ManifestSymbolEntry; provenance: Record<string, unknown> | null;
  indicators: Record<string, IndicatorsPayload["indicators"][string]>;
}) {
  const title = ctx.kind === "status" ? "Provenance · data quality & PIT" : ctx.kind === "bar" ? `Provenance · ${ctx.bar[0]}` : ctx.kind === "indicator" ? `Provenance · ${ctx.id}` : `Provenance · rule ${ctx.ruleId}`;
  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.42)", zIndex: 60 }} />
      <aside
        data-testid="chart-provenance-drawer" role="dialog" aria-label={title}
        style={{ position: "fixed", top: 0, right: 0, bottom: 0, width: "min(420px, 94vw)", background: "var(--bg-1)", borderLeft: "1px solid var(--c-line)", boxShadow: "var(--shadow-pop)", zIndex: 61, display: "flex", flexDirection: "column" }}
      >
        <div style={{ padding: "16px 18px", borderBottom: "1px solid var(--c-line)", display: "flex", alignItems: "center", gap: 12 }}>
          <h3 className="nv-serif" style={{ fontSize: 16, margin: 0, flex: 1 }}>{title}</h3>
          <button onClick={onClose} aria-label="Close" className="rail-ico" style={{ width: 28, height: 28, borderRadius: 999 }}>✕</button>
        </div>
        <div style={{ padding: "14px 18px", overflowY: "auto", flex: 1, display: "grid", gap: 10, fontSize: 12.5 }}>
          <Row label="Provider" value={txt(source.provider)} testid="chart-provenance-provider" />
          <Row label="Series" value={txt(source.series)} />
          <Row label="Adjustment status" value={txt(source.adjustment_status)} testid="chart-provenance-adjustment" />
          <Row label="Run ID" value={txt(runId)} testid="chart-provenance-run" />
          <Row label="Config hash" value={txt(configHash)} testid="chart-provenance-confighash" />
          <Row label="Generated at" value={txt(generatedAt)} />
          <Row label="Data quality status" value={txt(symEntry.data_quality_status)} testid="chart-provenance-dq" />
          <Row label="PIT status" value={txt(symEntry.pit_status)} testid="chart-provenance-pit" />
          {provenance && Object.entries(provenance).map(([k, v]) => <Row key={k} label={k} value={txt(v)} />)}
          {ctx.kind === "bar" && (
            <>
              <div className="nv-hr" />
              <Row label="Open" value={fmtPrice(ctx.bar[1])} />
              <Row label="High" value={fmtPrice(ctx.bar[2])} />
              <Row label="Low" value={fmtPrice(ctx.bar[3])} />
              <Row label="Close" value={fmtPrice(ctx.bar[4])} />
              <Row label="Volume" value={String(ctx.bar[5])} />
            </>
          )}
          {ctx.kind === "indicator" && indicators[ctx.id] && (
            <>
              <div className="nv-hr" />
              <Row label="Warmup period" value={txt(indicators[ctx.id].contract.warmup_period)} />
              <Row label="Calculation version" value={txt(indicators[ctx.id].contract.calculation_version)} />
              <Row label="Missing-data policy" value={txt(indicators[ctx.id].contract.missing_data_policy)} />
              <Row label="Pane" value={txt(indicators[ctx.id].pane)} />
            </>
          )}
          {ctx.kind === "rule" && (
            <>
              <div className="nv-hr" />
              {(() => {
                const r = ctx.pattern.rules.find((x) => x.rule_id === ctx.ruleId);
                if (!r) return <p style={{ margin: 0, color: "var(--c-ink-4)" }}>Rule not found.</p>;
                return (
                  <>
                    <Row label="Result" value={txt(r.result)} />
                    <Row label="Observed" value={txt(r.observed)} />
                    <Row label="Threshold" value={txt(r.threshold)} />
                  </>
                );
              })()}
            </>
          )}
        </div>
      </aside>
    </>
  );
}

function Row({ label, value, testid }: { label: string; value: string; testid?: string }) {
  return (
    <div data-testid={testid} style={{ display: "grid", gridTemplateColumns: "minmax(110px, max-content) 1fr", gap: 10 }}>
      <span className="nv-mono" style={{ fontSize: 10, letterSpacing: ".05em", textTransform: "uppercase", color: "var(--c-ink-3)" }}>{label}</span>
      <span style={{ color: "var(--c-ink)", wordBreak: "break-word" }}>{value}</span>
    </div>
  );
}
