/**
 * Market Desk › Scan Builder (docs/scan_builder/DESIGN.md §5). The owner's Chartink-inspired widget editor, on our own data:
 *
 *   left   the user's saved scans, + New scan, and templates to start from
 *   right  "Edit <name>": a rail Columns · Filters · Group/Sort, a Design · Result switch, and Run · Save · Copy … Cancel
 *
 * Result re-runs the scan every `market.refresh_seconds` (10 s) while the market is open, the Result view is shown and the tab
 * is visible; it pauses otherwise, never overlaps two runs, and after a 429 waits the server's retry_after_s. The URL keeps the
 * open scan (?scan=<id>). Behind the `scan_builder` feature flag: with it off nothing is asked of the server.
 *
 * Reads: GET /api/scan-builder/catalog, /scans, /scans/{id}; POST /run. Writes: POST/PUT /scans, POST /scans/{id}/copy,
 * DELETE /scans/{id}. Wording: scans and stocks that pass them; never buy / sell / target / stop loss / picks.
 */
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Columns3, Filter, ListFilter, Trash2 } from "lucide-react";
import { useMe } from "@/hooks/use-auth";
import { Btn, EmptyBlock, ErrorBlock, LoadingBlock, relTime } from "../../../../../components/ui";
import { useCopilotShell } from "../../../../../lib/shell-context";
import { useDesk } from "../../../context";
import { canonical } from "../../../desk-nav";
import { ColumnsPane, FiltersPane, GroupSortPane } from "./panes";
import { ResultView, type LiveState } from "./ResultView";
import {
  scanProblem, useCopyScan, useDeleteScan, useSaveScan, useSavedScan, useSavedScans, useScanCatalog, useScanRun, type RunResult,
} from "./scan-builder-data";
import { clone, draftProblems, localDefaultSpec, sameSpec, type Catalog, type ScanSpec } from "./scan-model";

type Rail = "columns" | "filters" | "groupsort";
type Pane = "design" | "result";

function useVisible(): boolean {
  const [v, setV] = useState(() => typeof document === "undefined" || document.visibilityState === "visible");
  useEffect(() => {
    const f = () => setV(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", f);
    return () => document.removeEventListener("visibilitychange", f);
  }, []);
  return v;
}

export default function ScanBuilder() {
  const me = useMe();
  const enabled = me.data?.features?.scan_builder === true;
  if (me.isPending) return <LoadingBlock label="Loading" rows={2} />;
  if (!enabled) {
    return (
      <div data-testid="sb-off">
        <EmptyBlock title="The Scan Builder is not enabled for your account" body="It is being rolled out in stages. Nothing on this screen was calculated." />
      </div>
    );
  }
  return <ScanBuilderOn />;
}

function ScanBuilderOn() {
  const catalog = useScanCatalog();
  if (catalog.isPending) return <LoadingBlock label="Loading the scan builder" rows={4} />;
  if (catalog.isError || !catalog.data) {
    return <div data-testid="sb-catalog-error"><ErrorBlock title="The scan builder did not load" error={catalog.error} onRetry={() => { void catalog.refetch(); }} /></div>;
  }
  return <Workspace cat={catalog.data} />;
}

function Workspace({ cat }: { cat: Catalog }) {
  const { mobile } = useCopilotShell();
  const desk = useDesk();
  const [params, setParams] = useSearchParams();
  const scanId = params.get("scan");
  const setScanParam = useCallback((id: string | null) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (id) p.set("scan", id); else p.delete("scan");
      return canonical(p);
    }, { replace: true });
  }, [setParams]);

  const fresh = useCallback((): ScanSpec => clone(cat.default_spec ?? localDefaultSpec()), [cat]);
  const [draft, setDraft] = useState<ScanSpec>(fresh);
  const [baseline, setBaseline] = useState<ScanSpec>(draft);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [rail, setRail] = useState<Rail>("filters");
  const [pane, setPane] = useState<Pane>("design");
  const [note, setNote] = useState<string | null>(null);

  const [runSpec, setRunSpec] = useState<ScanSpec | null>(null);
  const [runNo, setRunNo] = useState(0);

  // ── open a saved scan from the URL ──
  const saved = useSavedScan(scanId);
  useEffect(() => {
    if (scanId && saved.data && saved.data.id === scanId && savedId !== scanId) {
      setDraft(clone(saved.data.spec));
      setBaseline(clone(saved.data.spec));
      setSavedId(scanId);
      setRunSpec(null);
      setPane("design");
    }
  }, [scanId, saved.data, savedId]);

  // ── runs ──
  const run = useScanRun(runSpec, runNo);
  const [lastGood, setLastGood] = useState<RunResult | null>(null);
  useEffect(() => { if (run.data && !run.isPlaceholderData) setLastGood(run.data); }, [run.data, run.isPlaceholderData]);
  const problem = run.isError ? scanProblem(run.error) : null;
  const visible = useVisible();
  const marketOpen = lastGood?.market.open === true;
  const seconds = lastGood?.market.refresh_seconds ?? cat.refresh_seconds ?? 10;

  const runNow = () => {
    const issues = draftProblems(draft);
    if (issues.length) { setNote(issues[0]); return; }
    setNote(null);
    setRunSpec(clone(draft));
    setLastGood(null);
    setRunNo((n) => n + 1);
    setPane("result");
  };

  // The 10-second refresh: only on the Result view, after a good run, while the market is open and the tab is visible; one
  // run at a time; after a 429 it waits the server's retry_after_s.
  useEffect(() => {
    if (pane !== "result" || !runSpec || run.isFetching || !visible) return;
    let delay: number | null = null;
    if (problem?.code === "run_too_soon") delay = Math.max(1, problem.retryAfter ?? seconds) * 1000;
    else if (!problem && lastGood && marketOpen) delay = seconds * 1000;
    if (delay == null) return;
    const t = window.setTimeout(() => setRunNo((n) => n + 1), delay);
    return () => window.clearTimeout(t);
  }, [pane, runSpec, run.isFetching, visible, problem?.code, problem?.retryAfter, lastGood, marketOpen, seconds, run.dataUpdatedAt, run.errorUpdatedAt]);

  const live: LiveState = !lastGood ? "off" : !marketOpen ? "closed" : !visible ? "paused_hidden" : problem?.code === "run_too_soon" ? "waiting" : problem ? "off" : "live";
  const counts = runSpec && lastGood && JSON.stringify(runSpec.filters) === JSON.stringify(draft.filters) ? lastGood.nodes : null;

  // ── save / copy / cancel / new ──
  const save = useSaveScan();
  const copy = useCopyScan();
  const del = useDeleteScan();
  const dirty = !sameSpec(draft, baseline);
  const open = (id: string, spec: ScanSpec) => {
    setDraft(clone(spec));
    setBaseline(clone(spec));
    setSavedId(id);
    setScanParam(id);
  };
  const onSave = () => {
    const issues = draftProblems(draft);
    if (issues.length) { setNote(issues[0]); return; }
    setNote(null);
    save.mutate({ id: savedId, spec: draft }, { onSuccess: (s) => { open(s.id, s.spec); setNote("Saved."); } });
  };
  const onCopy = () => {
    setNote(null);
    if (savedId && !dirty) copy.mutate(savedId, { onSuccess: (s) => { open(s.id, s.spec); setNote(`Copied as “${s.spec.name}”.`); } });
    else save.mutate({ id: null, spec: { ...draft, name: `Copy of ${draft.name}`.slice(0, 80) } }, { onSuccess: (s) => { open(s.id, s.spec); setNote(`Copied as “${s.spec.name}”.`); } });
  };
  const onCancel = () => { setDraft(clone(baseline)); setNote(null); };
  const startFrom = (spec: ScanSpec) => {
    setDraft(clone(spec));
    setBaseline(clone(spec));
    setSavedId(null);
    setScanParam(null);
    setRunSpec(null);
    setLastGood(null);
    setPane("design");
    setRail("filters");
    setNote(null);
  };
  const loadingSaved = !!scanId && savedId !== scanId && saved.isPending;
  const mutError = save.error ?? copy.error;
  const mutProblem = mutError ? scanProblem(mutError) : null;

  return (
    <div data-testid="scan-builder" className="grid min-w-0" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "220px minmax(0,1fr)", gap: 16, alignItems: "start" }}>
      <SavedList
        cat={cat} currentId={savedId}
        onNew={() => startFrom(fresh())}
        onTemplate={(spec) => startFrom(spec)}
        onOpen={(id) => { if (id !== savedId) { setSavedId(null); setScanParam(id); } }}
        onDelete={(id) => del.mutate(id, { onSuccess: () => { if (id === savedId) startFrom(fresh()); } })}
        deleting={del.isPending ? del.variables ?? null : null}
      />
      <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
        <header className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <div className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "4px 10px" }}>
            <span style={{ fontFamily: "var(--display)", fontSize: 22, color: "var(--cp-ink)" }}>Edit</span>
            <input aria-label="Scan name" data-testid="sb-name" value={draft.name} maxLength={80} onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              style={{ flex: "1 1 220px", minWidth: 0, fontFamily: "var(--display)", fontSize: 22, color: "var(--cp-ink)", background: "transparent", border: 0, borderBottom: "1px dashed var(--line-2)", padding: "0 2px" }} />
            {dirty && <span data-testid="sb-dirty" className="cp-mono-note" style={{ color: "var(--amber)" }}>unsaved changes</span>}
          </div>
          <input aria-label="Scan description" data-testid="sb-description" value={draft.description} maxLength={400} placeholder="What this scan looks for (optional)"
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            style={{ fontSize: 13, color: "var(--cp-ink-2)", background: "transparent", border: 0, padding: "0 2px" }} />
          {scanId && saved.isError && <ErrorBlock title="This saved scan did not load" error={saved.error} onRetry={() => { void saved.refetch(); }} />}
        </header>

        {loadingSaved ? <LoadingBlock label="Opening the saved scan" rows={4} /> : (
        <div className="cp-card flex min-w-0" style={{ flexDirection: mobile ? "column" : "row", padding: 0 }}>
          <nav aria-label="Scan parts" className="flex flex-none" style={{ flexDirection: mobile ? "row" : "column", gap: 4, padding: 10, borderRight: mobile ? undefined : "1px solid var(--cp-line)", borderBottom: mobile ? "1px solid var(--cp-line)" : undefined, minWidth: mobile ? undefined : 150 }}>
            <RailBtn on={rail === "columns" && pane === "design"} testId="sb-rail-columns" icon={<Columns3 size={15} />} label="Columns" onClick={() => { setRail("columns"); setPane("design"); }} />
            <RailBtn on={rail === "filters" && pane === "design"} testId="sb-rail-filters" icon={<Filter size={15} />} label="Filters" onClick={() => { setRail("filters"); setPane("design"); }} />
            <RailBtn on={rail === "groupsort" && pane === "design"} testId="sb-rail-groupsort" icon={<ListFilter size={15} />} label="Group/Sort" onClick={() => { setRail("groupsort"); setPane("design"); }} />
          </nav>
          <div className="flex min-w-0 flex-1 flex-col" style={{ padding: "12px 16px", gap: 12 }}>
            <div role="tablist" aria-label="Design or result" className="inline-flex self-start" style={{ padding: 3, gap: 2, borderRadius: 10, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}>
              <Tab on={pane === "design"} testId="sb-tab-design" onClick={() => setPane("design")}>Design</Tab>
              <Tab on={pane === "result"} testId="sb-tab-result" onClick={() => { setPane("result"); if (!runSpec) runNow(); }}>Result</Tab>
            </div>
            <div className="min-w-0" style={{ minHeight: 220, paddingTop: 4, borderTop: "1px solid var(--cp-line)" }}>
              {pane === "design" ? (
                rail === "filters" ? <FiltersPane spec={draft} cat={cat} onChange={setDraft} counts={counts} />
                  : rail === "columns" ? <ColumnsPane spec={draft} cat={cat} onChange={setDraft} />
                    : <GroupSortPane spec={draft} onChange={setDraft} />
              ) : (
                <div style={{ paddingTop: 10 }}>
                  {runSpec && !sameSpec(runSpec, draft) && (
                    <p data-testid="sb-stale-design" className="m-0" style={{ paddingBottom: 8, fontSize: 12.5, color: "var(--amber)" }}>The design has changed since this run. Press Run to apply it.</p>
                  )}
                  <ResultView
                    result={lastGood} problem={problem} pending={run.isFetching} firstRun={runNo <= 1} live={live}
                    onRetry={() => setRunNo((n) => n + 1)} onOpenSymbol={(s) => desk.openChart(s)}
                  />
                </div>
              )}
            </div>
            <footer className="flex flex-wrap items-center" style={{ gap: 8, paddingTop: 12, borderTop: "1px solid var(--cp-line)" }}>
              <Btn variant="primary" data-testid="sb-run" onClick={runNow} disabled={run.isFetching}>{run.isFetching ? "Running…" : "Run"}</Btn>
              <Btn data-testid="sb-save" onClick={onSave} disabled={save.isPending || (!dirty && !!savedId)} title={savedId ? "Save the changes to this scan" : "Save this scan to your list"}>{save.isPending ? "Saving…" : "Save"}</Btn>
              <Btn data-testid="sb-copy" onClick={onCopy} disabled={copy.isPending || save.isPending} title="Save a copy as a new scan">Copy</Btn>
              {(note || mutProblem) && (
                <span data-testid="sb-note" role="status" style={{ fontSize: 12.5, color: mutProblem ? "var(--cp-danger)" : "var(--cp-ink-2)" }}>
                  {mutProblem ? (mutProblem.code === "too_many_scans" ? mutProblem.message : `Not saved — ${mutProblem.message}`) : note}
                </span>
              )}
              <span style={{ flex: "1 1 0" }} />
              <Btn variant="ghost" data-testid="sb-cancel" onClick={onCancel} disabled={!dirty} title="Discard the changes since the last save">Cancel</Btn>
            </footer>
          </div>
        </div>
        )}
      </div>
    </div>
  );
}

function RailBtn({ on, testId, icon, label, onClick }: { on: boolean; testId: string; icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <button type="button" data-testid={testId} aria-pressed={on} onClick={onClick}
      style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderRadius: 9, border: 0, cursor: "pointer", textAlign: "left", fontSize: 13.5, fontWeight: on ? 600 : 500, fontFamily: "var(--sans)", background: on ? "var(--bg-3)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-2)" }}>
      {icon}{label}
    </button>
  );
}

function Tab({ on, testId, onClick, children }: { on: boolean; testId: string; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" role="tab" aria-selected={on} data-testid={testId} onClick={onClick}
      style={{ padding: "6px 16px", borderRadius: 8, border: 0, cursor: "pointer", fontSize: 13, fontWeight: on ? 600 : 500, fontFamily: "var(--sans)", background: on ? "var(--bg-0)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>
      {children}
    </button>
  );
}

const listBtn = (on: boolean): CSSProperties => ({
  display: "block", width: "100%", textAlign: "left", padding: "7px 10px", borderRadius: 8, border: 0, cursor: "pointer", fontSize: 13, fontFamily: "var(--sans)",
  background: on ? "var(--bg-3)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
});

function SavedList({ cat, currentId, onNew, onTemplate, onOpen, onDelete, deleting }: {
  cat: Catalog; currentId: string | null; onNew: () => void; onTemplate: (spec: ScanSpec) => void; onOpen: (id: string) => void; onDelete: (id: string) => void; deleting: string | null;
}) {
  const scans = useSavedScans();
  const [confirm, setConfirm] = useState<string | null>(null);
  const templates = useMemo(() => cat.templates ?? [], [cat]);
  return (
    <aside data-testid="sb-list" aria-label="Your scans" className="cp-card flex min-w-0 flex-col" style={{ padding: 10, gap: 10 }}>
      <Btn variant="primary" data-testid="sb-new" onClick={onNew}>+ New scan</Btn>
      <div className="flex flex-col" style={{ gap: 2 }}>
        <span className="cp-eyebrow" style={{ padding: "4px 4px 2px" }}>Your scans</span>
        {scans.isPending && <span style={{ padding: "4px", fontSize: 12.5, color: "var(--cp-ink-3)" }}>Loading…</span>}
        {scans.isError && <span data-testid="sb-list-error" style={{ padding: "4px", fontSize: 12.5, color: "var(--cp-danger)" }}>Your scans did not load. <button type="button" onClick={() => { void scans.refetch(); }} style={{ border: 0, background: "none", color: "var(--cp-ink)", cursor: "pointer", padding: 0 }}>Retry ›</button></span>}
        {scans.data && scans.data.length === 0 && <span data-testid="sb-list-empty" style={{ padding: "4px", fontSize: 12.5, color: "var(--cp-ink-3)" }}>None saved yet.</span>}
        {scans.data?.map((s) => (
          <div key={s.id} className="flex items-center" style={{ gap: 2 }}>
            <button type="button" data-testid={`sb-scan-${s.id}`} aria-current={s.id === currentId ? "true" : undefined} onClick={() => onOpen(s.id)} style={listBtn(s.id === currentId)}
              title={s.updated_at ? `${s.name} · saved ${relTime(s.updated_at)}` : s.name}>
              {s.name}
            </button>
            {confirm === s.id ? (
              <span className="flex flex-none items-center" style={{ gap: 4, fontSize: 12 }}>
                <button type="button" data-testid={`sb-delete-confirm-${s.id}`} disabled={deleting === s.id} onClick={() => { onDelete(s.id); setConfirm(null); }} style={{ border: 0, background: "none", color: "var(--cp-danger)", cursor: "pointer", padding: 0 }}>Delete</button>
                <button type="button" onClick={() => setConfirm(null)} style={{ border: 0, background: "none", color: "var(--cp-ink-3)", cursor: "pointer", padding: 0 }}>Keep</button>
              </span>
            ) : (
              <button type="button" aria-label={`Delete ${s.name}`} title={`Delete ${s.name}`} data-testid={`sb-delete-${s.id}`} onClick={() => setConfirm(s.id)}
                style={{ flex: "none", width: 26, height: 26, border: 0, background: "transparent", color: "var(--cp-ink-3)", cursor: "pointer", borderRadius: 7 }}>
                <Trash2 size={13} />
              </button>
            )}
          </div>
        ))}
      </div>
      {templates.length > 0 && (
        <div className="flex flex-col" style={{ gap: 2 }}>
          <span className="cp-eyebrow" style={{ padding: "4px 4px 2px" }}>Start from a template</span>
          {templates.map((t) => (
            <button key={t.key} type="button" data-testid={`sb-template-${t.key}`} onClick={() => onTemplate(t.spec)} style={listBtn(false)} title={t.description ?? t.name}>{t.name}</button>
          ))}
        </div>
      )}
    </aside>
  );
}
