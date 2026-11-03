/**
 * Chartink scans on the desk - the pieces the Scanner, the Chartink settings and the Strategy Builder share. The old
 * Overview's sub-list of Chartink-only stocks (ChartinkOnlyList) left with that tab in the desk redesign's step 6.
 *
 *   <ChartinkTag hit>        "Also on Chartink: <scan> (+n)" beside an AI row whose stock is in the hits
 *   <ChartinkTrust hits>     the trust line: source, mode as returned, "Chartink fetched <time IST>", not validated
 *
 * Every figure is the hits route's (close, % change, scan names, F&O flag); nothing is scanned or scored here. A stock the
 * AI scanner does not list has no AI score, and the row says so instead of showing a number.
 */
import { Pill } from "../../../components/ui";
import { stampIst } from "../overview-data";
import { TrustLine, type DataMode } from "../trust";
import { alsoOnChartinkText } from "./chartink-data";
import type { ChartinkHits, ChartinkHitSymbol } from "./chartink-contract";

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
      <TrustLine testId={testId} source={CHARTINK_SOURCE_LABEL} mode={hitsMode(hits)} asOf={asOf} status={hits.stale_note ? "stale" : null} method={`${hits.mode === "fetched_at" ? "as of the fetch time · " : ""}your scan rules, not validated signals`} />
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
