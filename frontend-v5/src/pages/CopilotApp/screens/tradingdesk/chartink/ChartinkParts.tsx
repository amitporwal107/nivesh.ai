/**
 * Chartink scans on the desk - the pieces the Overview, Scanner and Strategy Builder share.
 *
 *   <ChartinkTag hit>        "Also on Chartink: <scan> (+n)" beside an AI row whose stock is in the hits
 *   <ChartinkOnlyList>       "From your Chartink scans (not in the AI scan)": the Overview card's sub-list (desktop and phone)
 *   <ChartinkTrust hits>     the trust line: source, mode as returned, "Chartink fetched <time IST>", not validated
 *
 * Every figure is the hits route's (close, % change, scan names, F&O flag); nothing is scanned or scored here. A stock the
 * AI scanner does not list has no AI score, and the row says so instead of showing a number.
 */
import type { CSSProperties } from "react";
import { StockIcon } from "../../../components/EntityIcon";
import { Pill, fmtNum, fmtPct, TONE_COLOR } from "../../../components/ui";
import { fmtPrice } from "../../markets/format";
import { stampIst } from "../overview-data";
import { useDesk } from "../context";
import { TrustLine, type DataMode } from "../trust";
import { alsoOnChartinkText, useChartink } from "./chartink-data";
import type { ChartinkHits, ChartinkHitSymbol } from "./chartink-contract";

const line = "1px solid var(--cp-line)";
const linkBtn: CSSProperties = { padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--mint)", fontFamily: "var(--sans)", textAlign: "left" };
export const CHARTINK_SOURCE_LABEL = "Chartink scans (your dashboard)";

/** The hits' mode as the route sent it: "end_of_day_snapshot" is end of day; "fetched_at" is only as fresh as the last fetch. */
export function hitsMode(h: ChartinkHits): DataMode | null {
  return h.mode === "end_of_day_snapshot" ? "eod" : null;
}

export function ChartinkTrust({ hits, testId, pad }: { hits: ChartinkHits; testId: string; pad?: string }) {
  const fetched = stampIst(hits.fetched_at);
  const day = dayOnly(hits.as_of_date);
  const asOf = [fetched ? `Chartink fetched ${fetched}` : null, day && hitsMode(hits) === "eod" ? `snapshot of ${day}` : null].filter(Boolean).join(" · ") || null;
  return (
    <div style={{ padding: pad }}>
      <TrustLine testId={testId} source={CHARTINK_SOURCE_LABEL} mode={hitsMode(hits)} asOf={asOf} method={`${hits.mode === "fetched_at" ? "as of the fetch time · " : ""}your scan rules, not validated signals`} />
    </div>
  );
}
function dayOnly(d: string | null): string | null {
  if (!d || !/^\d{4}-\d{2}-\d{2}$/.test(d)) return null;
  return new Date(`${d}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** "Also on Chartink: Scan A (+2)"; the title lists every scan. Nothing when the stock is not in the hits. */
export function ChartinkTag({ hit, testId = "ck-tag" }: { hit: ChartinkHitSymbol | null | undefined; testId?: string }) {
  const text = alsoOnChartinkText(hit);
  if (!hit || !text) return null;
  return (
    <span data-testid={testId} data-count={hit.scans.length} title={hit.scans.map((s) => s.name).join("; ")} style={{ display: "inline-flex", maxWidth: "100%" }}>
      <Pill tone="indigo"><span style={{ overflowWrap: "anywhere" }}>{text}</span></Pill>
    </span>
  );
}

/** A Switch: role=switch, a visible label, keyboard-operable (a real button). */
export function Switch({ on, onChange, label, disabled, testId }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean; testId: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} data-testid={testId} disabled={disabled} onClick={() => onChange(!on)}
      className="inline-flex items-center" style={{ gap: 8, padding: 0, border: 0, background: "none", cursor: disabled ? "not-allowed" : "pointer", fontFamily: "var(--sans)", fontSize: 12, color: "var(--cp-ink-2)", opacity: disabled ? 0.55 : 1 }}>
      <span aria-hidden style={{ position: "relative", width: 30, height: 18, flex: "none", borderRadius: 999, border: "1px solid var(--line-2)", background: on ? "var(--mint-soft)" : "var(--bg-3)" }}>
        <span style={{ position: "absolute", top: 2, left: on ? 14 : 2, width: 12, height: 12, borderRadius: 999, background: on ? "var(--mint)" : "var(--cp-ink-3)", transition: "left .15s ease" }} />
      </span>
      <span data-testid={`${testId}-state`}>{on ? "On" : "Off"}</span>
    </button>
  );
}

function Fno({ v }: { v: boolean | null }) {
  if (v !== true) return null;
  return <span data-testid="ck-fno"><Pill tone="ink" title="In the NSE futures and options list">F&amp;O</Pill></span>;
}

function OnlyRow({ s, compact, onOpen }: { s: ChartinkHitSymbol; compact: boolean; onOpen: () => void }) {
  const tone = s.pct_change == null ? "var(--cp-ink-3)" : s.pct_change > 0 ? TONE_COLOR.mint : s.pct_change < 0 ? TONE_COLOR.danger : "var(--cp-ink-2)";
  const scans = s.scans.map((x) => x.name).join(", ");
  return (
    <li style={{ borderTop: line }}>
      <button type="button" data-testid="ck-only" data-symbol={s.symbol} onClick={onOpen} aria-label={`${s.symbol}: open its chart analysis`} className="cp-row-link grid w-full"
        style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: "4px 12px", padding: compact ? "10px 14px" : "10px 18px", border: 0, background: "transparent", color: "inherit", textAlign: "left", fontFamily: "var(--sans)" }}>
        <span className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px" }}>
            <StockIcon symbol={s.symbol} name={s.name} size={compact ? 20 : 22} />
            <span data-testid="ck-only-symbol" className="cp-num" style={{ fontSize: 13, fontWeight: 500 }}>{s.symbol}</span>
            {s.name && <span data-testid="ck-only-name" style={{ fontSize: 12, color: "var(--cp-ink-3)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>}
            <Fno v={s.fno_eligible} />
          </span>
          <span data-testid="ck-only-scans" title={scans} style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
            Chartink: {scans || "—"}
          </span>
        </span>
        <span className="flex flex-col items-end" style={{ gap: 3, textAlign: "right" }}>
          <span data-testid="ck-only-price" className="cp-num" style={{ fontSize: 13 }}>{s.close != null ? fmtPrice(s.close) : "—"}</span>
          <span data-testid="ck-only-change" className="cp-num" style={{ fontSize: 11.5, color: tone }}>{fmtPct(s.pct_change, { signed: true, digits: 1 })}</span>
          <span data-testid="ck-only-score" className="cp-num" title="The AI scanner does not list this stock, so it has no AI score" style={{ fontSize: 10.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>No AI score</span>
        </span>
      </button>
    </li>
  );
}

export const CK_ONLY_ROWS = 4;

/** The sub-list under the AI rows, or the one line that says why there is none. Renders nothing while the first load runs. */
export function ChartinkOnlyList({ compact = false, testId }: { compact?: boolean; testId: string }) {
  const { openChart, openChartink } = useDesk();
  const ck = useChartink();
  const pad = compact ? "10px 14px" : "10px 18px";
  const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
  if (ck.kind === "loading" || ck.kind === "hits_loading") return null;
  if (ck.kind === "not_connected") {
    return (
      <div data-testid={`${testId}-connect`} style={{ padding: pad, borderTop: line }}>
        <button type="button" data-testid="ck-connect-link" onClick={openChartink} style={linkBtn}>Connect your Chartink dashboard to add your scans here ›</button>
      </div>
    );
  }
  if (ck.kind === "source_error" || ck.kind === "hits_error") {
    return (
      <div data-testid={`${testId}-degraded`} role="status" className="flex flex-wrap items-center" style={{ padding: pad, borderTop: line, gap: "2px 10px", ...quiet }}>
        <span>Your Chartink scans didn’t load, so only the AI scanner is shown.</span>
        <button type="button" data-testid="ck-retry" onClick={ck.retry} style={linkBtn}>Retry ›</button>
      </div>
    );
  }
  const only = ck.hits.symbols.filter((s) => !s.in_ai_scanner);
  const shown = only.slice(0, CK_ONLY_ROWS);
  const failed = ck.hits.scans.filter((s) => !s.ok);
  const total = ck.hits.symbols.length;
  return (
    <div data-testid={testId} style={{ borderTop: line, background: "var(--bg-0)" }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "4px 12px", padding: pad }}>
        <span data-testid={`${testId}-title`} className="cp-eyebrow">From your Chartink scans (not in the AI scan)</span>
        <button type="button" data-testid="ck-settings-link" onClick={openChartink} style={linkBtn}>Chartink scans ›</button>
      </div>
      {failed.length > 0 && (
        <p role="note" data-testid={`${testId}-failed`} className="m-0" style={{ padding: `0 ${compact ? 14 : 18}px 8px`, ...quiet, color: "var(--amber)" }}>
          {failed.length} of {ck.hits.scans.length} {ck.hits.scans.length === 1 ? "scan" : "scans"} didn’t run: {failed.map((f) => `${f.name}${f.error ? ` (${f.error})` : ""}`).join("; ")}. The rest are shown.
        </p>
      )}
      {shown.length === 0 ? (
        <p data-testid={`${testId}-empty`} className="m-0" style={{ padding: `0 ${compact ? 14 : 18}px 10px`, ...quiet }}>
          {total === 0 ? "No hits in your enabled Chartink scans on the latest fetch." : "Every stock your Chartink scans hit is also in the AI scan (tagged above)."}
        </p>
      ) : (
        <ol className="m-0 flex flex-col p-0" style={{ listStyle: "none" }}>
          {shown.map((s) => <OnlyRow key={s.symbol} s={s} compact={compact} onOpen={() => openChart(s.symbol)} />)}
        </ol>
      )}
      {only.length > shown.length && (
        <p data-testid={`${testId}-more`} className="m-0" style={{ padding: `6px ${compact ? 14 : 18}px 0`, ...quiet }}>
          {fmtNum(only.length - shown.length)} more in AI Scanner · Chartink scans.
        </p>
      )}
      <ChartinkTrust hits={ck.hits} testId={`${testId}-trust`} pad={`8px ${compact ? 14 : 18}px 12px`} />
    </div>
  );
}
