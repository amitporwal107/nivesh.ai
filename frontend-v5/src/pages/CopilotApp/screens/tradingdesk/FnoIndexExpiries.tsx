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
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { LoadingBlock, Pill, TONE_COLOR, fmtNum, fmtPct, signTone, type Tone } from "../../components/ui";
import { QueryProblem, fmtDay, fmtQty } from "../trading/parts";
import { fmtLevel } from "../trading/PayoffResult";
import { useFnoFutures, useOptionChain, type FnoFuture, type OiBuildup } from "../trading/fno";
import { BUILDUP_LABELS, BUILDUP_META, type BuildupLabel, type BuildupQuadrant } from "./fno-buildup";
import { num } from "./desk-data";
import { wallsOf, shortDay } from "./fno-parts";
import { Widget } from "./widget";

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
    <Widget id="fno.expiries" testId={id} title="By expiry" bodyStyle={{ gap: 14, padding: 18 }}>
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
    </Widget>
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


// ── the last five sessions' state ────────────────────────────────────────

export interface HistorySession { date: string; label: BuildupQuadrant | null; priceChgPct: number | null; oiChgPct: number | null }

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});

/** GET /api/fno/{symbol}/positioning-history: the near-month futures' build-up state per session, oldest first. A missing figure is null, never 0. */
export function parseHistory(body: unknown): HistorySession[] {
  const b = rec(body);
  if (!Array.isArray(b.sessions)) throw ApiError.contractDrift("fno.positioning-history: no sessions list");
  return b.sessions.flatMap((x) => {
    const r = rec(x);
    if (typeof r.date !== "string") return [];
    const label = (BUILDUP_LABELS as readonly string[]).includes(String(r.label)) ? (r.label as BuildupQuadrant) : null;
    return [{ date: r.date.slice(0, 10), label, priceChgPct: num(r.price_chg_pct), oiChgPct: num(r.oi_chg_pct) }];
  });
}

export function useIndexHistory(symbol: string) {
  return useQuery<HistorySession[]>({
    queryKey: ["copilot", "desk", "fno-positioning-history", symbol],
    staleTime: 10 * 60_000,
    retry: false,
    queryFn: async ({ signal }) => parseHistory((await http({ path: `/api/fno/${encodeURIComponent(symbol)}/positioning-history`, query: { sessions: 5 }, timeoutMs: 45_000, signal })).data),
  });
}

export function HistoryPanel({ symbol }: { symbol: string }) {
  const q = useIndexHistory(symbol);
  const id = `desk-fno-history-${symbol}`;
  return (
    <Widget id={`fno.history.${symbol}`} testId={id} title="Last five sessions" bodyStyle={{ gap: 12, padding: 18 }}>
      {q.isPending && <LoadingBlock label={`Loading ${symbol} positioning history`} rows={2} />}
      {q.isError && <QueryProblem what={`${symbol} positioning history`} error={q.error} onRetry={() => q.refetch()} />}
      {q.data && q.data.length === 0 && <span style={quiet}>No sessions came back.</span>}
      {q.data && q.data.length > 0 && (
        <div className="flex flex-wrap items-stretch" style={{ gap: 6 }}>
          {q.data.map((h) => {
            const meta = h.label ? BUILDUP_META[h.label] : null;
            return (
              <span key={h.date} data-testid={`${id}-${h.date}`} data-label={h.label ?? ""} className="flex flex-col" style={{ gap: 3, padding: "6px 10px", borderRadius: 8, background: "var(--bg-1)", border: "1px solid var(--line-2)" }}>
                <span className="cp-mono-note">{shortDay(h.date)}</span>
                <Pill tone={meta?.tone ?? "ink"}>{meta ? meta.label : "No state"}</Pill>
                <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--cp-ink-3)" }}>{fmtPct(h.priceChgPct, { signed: true, digits: 2 })} · OI {fmtPct(h.oiChgPct, { signed: true, digits: 2 })}</span>
              </span>
            );
          })}
        </div>
      )}
      <span data-testid={`${id}-note`} style={quiet}>
        The near-month future's state each session, so you can follow how positioning changes. A change of state is not a signal: tests did not show that transitions add information beyond the state itself.
      </span>
    </Widget>
  );
}

// ── option-chain OI bars ─────────────────────────────────────────────────

const AROUND = 7;

export function OiBarsPanel({ symbol }: { symbol: string }) {
  const { state } = useOptionChain(symbol, null);
  const id = `desk-fno-oibars-${symbol}`;
  const chain = state.status === "ok" ? state.chain : null;
  const rows = chain ? (() => {
    const at = chain.summary.atm_strike;
    const i = Math.max(0, chain.strikes.findIndex((r) => r.strike === at));
    return chain.strikes.slice(Math.max(0, i - AROUND), i + AROUND + 1);
  })() : [];
  const max = Math.max(1, ...rows.flatMap((r) => [r.call?.oi ?? 0, r.put?.oi ?? 0]));
  const w = chain ? wallsOf(chain.summary) : { put: null, call: null };
  return (
    <Widget
      id={`fno.oibars.${symbol}`}
      testId={id}
      title={`Options open interest by strike${chain ? ` · ${fmtDay(chain.summary.expiry)}` : ""}`}
      meta={chain ? `PCR ${chain.summary.pcr == null ? "—" : fmtNum(chain.summary.pcr, 2)} · max pain ${chain.summary.max_pain == null ? "—" : fmtLevel(chain.summary.max_pain)}` : undefined}
      bodyStyle={{ gap: 12, padding: 18 }}
    >
      {state.status === "loading" && <LoadingBlock label={`Loading the ${symbol} chain`} rows={3} />}
      {state.status === "none" && <span style={quiet}>{state.message}</span>}
      {state.status === "error" && <span style={quiet}>The chain didn’t load, so there are no bars.</span>}
      {chain && (
        <div className="flex flex-col" style={{ gap: 3 }}>
          {rows.map((r) => {
            const tags = [chain.summary.atm_strike === r.strike ? "ATM" : null, w.put?.strike === r.strike ? "S" : null, w.call?.strike === r.strike ? "R" : null].filter(Boolean).join(" · ");
            return (
              <div key={r.strike} data-testid="desk-fno-oibar-row" data-strike={r.strike} data-atm={chain.summary.atm_strike === r.strike ? "true" : undefined} className="grid items-center" style={{ gridTemplateColumns: "minmax(0,1fr) 96px minmax(0,1fr)", gap: 10 }}>
                <span className="flex items-center justify-end" style={{ gap: 6 }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-3)" }}>{r.put?.oi != null ? fmtQty(r.put.oi) : "—"}</span>
                  <span data-testid="desk-fno-oibar-put" style={{ height: 12, borderRadius: 3, background: "var(--mint)", opacity: 0.75, width: `${((r.put?.oi ?? 0) / max) * 100}%`, maxWidth: "100%" }} />
                </span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 12, textAlign: "center", color: tags ? "var(--amber)" : "var(--cp-ink-2)", fontWeight: tags ? 600 : 400 }}>{fmtLevel(r.strike)}{tags ? <span style={{ fontSize: 9, display: "block" }}>{tags}</span> : null}</span>
                <span className="flex items-center" style={{ gap: 6 }}>
                  <span data-testid="desk-fno-oibar-call" style={{ height: 12, borderRadius: 3, background: "var(--cp-danger)", opacity: 0.75, width: `${((r.call?.oi ?? 0) / max) * 100}%`, maxWidth: "100%" }} />
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-3)" }}>{r.call?.oi != null ? fmtQty(r.call.oi) : "—"}</span>
                </span>
              </div>
            );
          })}
        </div>
      )}
      <span data-testid={`${id}-note`} style={quiet}>
        Puts left, calls right. Open interest at a strike shows contracts open there, not who holds them or which side; it is not support or resistance. S and R mark the heaviest put OI at or below the price and the heaviest call OI at or above it.
      </span>
    </Widget>
  );
}

export function GreeksNotAvailable() {
  return (
    <section data-testid="desk-fno-greeks-na" className="flex flex-col" style={{ gap: 6, padding: "16px 18px", borderRadius: 14, border: "1px dashed var(--line-3)" }}>
      <span style={{ fontSize: 14, fontWeight: 600, color: "var(--cp-ink-2)" }}>Greek-weighted exposure and IV by expiry · not available yet</span>
      <span style={quiet}>
        Planned for a later release, and only after the research shows it adds anything. Greeks here are model estimates from end-of-day prices, and public open interest cannot tell who is long or short, so no dealer positioning is shown.
      </span>
    </section>
  );
}
