/**
 * Smart trading desk — Options & futures lab · NIFTY & BANKNIFTY workspace: the By expiry panel and the research note.
 * Design: the "F&O Lab Candidates" canvas, artboard IndexWorkspace. Analysis only.
 *
 *   GET /api/fno/{symbol}/futures   one row per listed future: its own close, change, open interest, change in open interest and
 *                                   build-up label (useFnoFutures, trading/fno.ts). End of day.
 *
 * Each expiry is read on its own contract: open interest is never added across expiries, and a drop in the near month with a rise
 * in the next may be rollover rather than a view. The OI change % is the contract's change in OI over its own previous OI; a
 * missing figure is "—", never 0.
 */
import { Pill, TONE_COLOR, fmtPct, signTone, type Tone } from "../../components/ui";
import { QueryProblem, fmtDay } from "../trading/parts";
import { useFnoFutures, type FnoFuture, type OiBuildup } from "../trading/fno";
import { BUILDUP_META, type BuildupLabel } from "./fno-buildup";

const BUCKETS = ["Near", "Next", "Far"] as const;
const LABEL: Record<OiBuildup, BuildupLabel> = {
  "long build-up": "long_buildup", "short build-up": "short_buildup", "short covering": "short_covering", "long unwinding": "long_unwinding",
};
const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;

/** Change in open interest over the contract's own previous open interest, in percent; null when either figure is missing. */
export function oiChangePct(f: Pick<FnoFuture, "oi" | "change_in_oi">): number | null {
  if (f.oi == null || f.change_in_oi == null) return null;
  const prev = f.oi - f.change_in_oi;
  return prev > 0 ? (f.change_in_oi / prev) * 100 : null;
}

export function ExpiryPanel({ symbol }: { symbol: string }) {
  const fq = useFnoFutures(symbol);
  const id = `desk-fno-expiries-${symbol}`;
  return (
    <section data-testid={id} className="cp-card flex flex-col" style={{ gap: 14, padding: 18, minWidth: 0 }}>
      <span style={{ fontSize: 15, fontWeight: 600 }}>By expiry</span>
      {fq.isPending && <span style={quiet}>Loading the futures</span>}
      {fq.isError && <QueryProblem what={`${symbol} futures`} error={fq.error} onRetry={() => fq.refetch()} />}
      {fq.data?.kind === "none" && <span style={quiet}>{fq.data.message}</span>}
      {fq.data?.kind === "ok" && (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10 }}>
          {fq.data.data.futures.slice(0, 3).map((f, i) => {
            const meta = f.oi_buildup ? BUILDUP_META[LABEL[f.oi_buildup]] : null;
            const oi = oiChangePct(f);
            const tone: Tone = meta?.tone ?? "ink";
            return (
              <div key={f.expiry} data-testid={`${id}-${BUCKETS[i].toLowerCase()}`} className="flex flex-col" style={{ gap: 8, padding: 12, borderRadius: 12, background: "var(--bg-1)", border: "1px solid var(--line-2)", minWidth: 0 }}>
                <span style={quiet}>{BUCKETS[i]}</span>
                <span className="cp-mono-note">{fmtDay(f.expiry)}</span>
                <span data-testid={`${id}-${BUCKETS[i].toLowerCase()}-state`}><Pill tone={tone}>{meta ? meta.label : "No state"}</Pill></span>
                <span data-testid={`${id}-${BUCKETS[i].toLowerCase()}-price`} style={{ fontFamily: "var(--mono)", fontSize: 12, color: TONE_COLOR[signTone(f.change_pct)] }}>Price {fmtPct(f.change_pct, { signed: true, digits: 2 })}</span>
                <span data-testid={`${id}-${BUCKETS[i].toLowerCase()}-oi`} style={{ fontFamily: "var(--mono)", fontSize: 12, color: TONE_COLOR[signTone(oi)] }}>OI {fmtPct(oi, { signed: true, digits: 2 })}</span>
              </div>
            );
          })}
        </div>
      )}
      <span data-testid={`${id}-note`} style={quiet}>
        Each expiry is read on its own contract. Open interest is never added across expiries, and a drop in the near month with a rise in the next may just be rollover.
      </span>
    </section>
  );
}

export function IndexResearchNote() {
  return (
    <div role="note" data-testid="desk-fno-index-research" className="flex flex-wrap" style={{ gap: "6px 12px", padding: "14px 18px", borderRadius: 12, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
      <span className="cp-eyebrow" style={{ color: "var(--amber)" }}>Research setting · not validated</span>
      <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", flex: "1 1 360px", minWidth: 0 }}>
        An index has no delivery or fundamentals, so this is the futures build-up, the cash check and the option chain only. With two series, tests here are descriptive: no ranking and no claim of skill.
      </span>
    </div>
  );
}
