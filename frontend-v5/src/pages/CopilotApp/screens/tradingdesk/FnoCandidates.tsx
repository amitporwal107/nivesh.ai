/**
 * Smart trading desk — Options & futures lab · Candidates: the stocks with the strongest build-up in each category, ORDERED FOR REVIEW.
 * Design: the "F&O Lab Candidates" canvas (Main, Mobile). Analysis only: nothing here places an order.
 *
 *   GET /api/fno/scan/candidates   candidates-data.ts: three separate scores per candidate (signal strength, tradeability, strategy
 *                                  quality), the confirmations, a fundamental context rating, and the research status block.
 *
 * What the screen refuses to do: call anything a recommendation, a pick or a best trade; blend the three scores; spread a missing
 * input's points over the others (it is listed as "not earned"); show strategy quality (it is unavailable); or hide that the ranking is
 * a research setting that back-tests did not validate. The research banner is always the first thing shown.
 */
import { useEffect, useState } from "react";
import { StockIcon } from "../../components/EntityIcon";
import { LoadingBlock, Pill, TONE_COLOR, fmtNum, fmtPct, signTone, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { QueryProblem } from "../trading/parts";
import { BUILDUP_LABELS, BUILDUP_META, type BuildupQuadrant } from "./fno-buildup";
import { useCandidates, type Candidate, type CandidateCategory, type Score } from "./candidates-data";
import { Segmented } from "./fno-parts";
import { TrustLine } from "./trust";

const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;
const mono = { fontFamily: "var(--mono)" } as const;

const CHECK_NAME: Record<string, string> = {
  cash_confirms: "Cash", volume_elevated: "Rel. volume", delivery_rising: "Delivery", trend_aligned: "Trend", momentum_aligned: "Momentum",
};
const FUND_WORD: Record<string, string> = { strong: "Strong", mixed: "Mixed", weak: "Weak", unavailable: "Unavailable" };
const pct0 = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const day = (d: string | null) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : null);

function Bar({ value, color, testId }: { value: number | null; color: string; testId: string }) {
  const w = value == null ? 0 : Math.max(0, Math.min(100, value));
  return (
    <div data-testid={testId} data-points={value ?? ""} style={{ height: 8, borderRadius: 999, background: "var(--bg-4)", overflow: "hidden" }}>
      <div style={{ height: "100%", width: `${w}%`, borderRadius: 999, background: color }} />
    </div>
  );
}

function ScoreRow({ name, s, color, symbol, kind, note }: { name: string; s: Score; color: string; symbol: string; kind: string; note?: string }) {
  return (
    <div className="flex flex-col" style={{ gap: 5 }}>
      <div className="flex items-baseline justify-between">
        <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>{name}</span>
        <span style={{ ...mono, fontSize: 13 }}>{s.points == null ? "—" : fmtNum(s.points, 0)} <span style={{ color: "var(--cp-ink-3)" }}>/ {fmtNum(s.maxPoints ?? 100)}</span></span>
      </div>
      <Bar value={s.points} color={color} testId={`desk-cand-${kind}-${symbol}`} />
      <div className="flex flex-wrap items-center" style={{ gap: "4px 10px" }}>
        {!s.complete && <Pill tone="amber">Incomplete · coverage {pct0(s.coverage)}</Pill>}
        {s.complete && <span style={quiet}>Coverage {pct0(s.coverage)}</span>}
        {s.missing.map((m) => (
          <span key={m.key} style={quiet} data-testid={`desk-cand-missing-${kind}-${symbol}`}>
            Not earned: {m.label.toLowerCase()}, {fmtNum(m.weight)} points{m.reason ? ` (${m.reason.replace(/\.$/, "")})` : ""}
          </span>
        ))}
        {note && <span style={quiet}>{note}</span>}
      </div>
    </div>
  );
}

function Fig({ label, value, tone }: { label: string; value: string; tone?: Tone }) {
  return (
    <div className="flex flex-col" style={{ gap: 2, minWidth: 0 }}>
      <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{label}</span>
      <span style={{ ...mono, fontSize: 14, color: tone ? TONE_COLOR[tone] : undefined, overflowWrap: "anywhere" }}>{value}</span>
    </div>
  );
}

function CandidateCard({ c, rank, of, onOpen }: { c: Candidate; rank: number; of: number; onOpen: (s: string) => void }) {
  const meta = BUILDUP_META[c.label];
  const checks = c.checks.filter((k) => CHECK_NAME[k.key]);
  const word = (s: boolean | null) => (s === true ? "holds" : s === false ? "does not" : "unknown");
  const dot = (s: boolean | null) => (s === true ? "var(--mint)" : s === false ? "var(--danger-hex, #FF8D99)" : "transparent");
  return (
    <article data-testid={`desk-cand-card-${c.symbol}`} data-label={c.label} className="cp-card flex flex-col" style={{ gap: 14, padding: 18, minWidth: 0 }}>
      <div className="flex items-center" style={{ gap: 12 }}>
        <StockIcon symbol={c.symbol} size={38} />
        <div className="flex min-w-0 flex-col" style={{ flex: "1 1 auto" }}>
          <span style={{ fontSize: 17, fontWeight: 600 }}>{c.symbol}</span>
          {c.sector && <span style={quiet}>{c.sector}</span>}
        </div>
        <span data-testid={`desk-cand-rank-${c.symbol}`} style={{ ...mono, fontSize: 12, color: "var(--cp-ink-3)" }}>#{rank} of {of}</span>
        <Pill tone={meta.tone}>{meta.label}</Pill>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 8 }}>
        <Fig label="Futures price" value={fmtPct(c.priceChgPct, { signed: true, digits: 1 })} tone={signTone(c.priceChgPct)} />
        <Fig label="Open interest" value={fmtPct(c.oiChgPct, { signed: true, digits: 1 })} tone={signTone(c.oiChgPct)} />
        <Fig label="Cash price" value={fmtPct(c.cashChgPct, { signed: true, digits: 1 })} tone={signTone(c.cashChgPct)} />
        <Fig label="Expiry" value={c.nearExpiry ? `${day(c.nearExpiry)?.replace(/ \d{4}$/, "")}${c.daysToExpiry != null ? ` ${fmtNum(c.daysToExpiry)}d` : ""}` : "—"} />
      </div>
      <div className="flex flex-col" style={{ gap: 10, paddingTop: 12, borderTop: "1px solid var(--line-2)" }}>
        <ScoreRow name="Signal strength" s={c.signal} color="var(--mint)" symbol={c.symbol} kind="signal" />
        <ScoreRow name="Tradeability" s={c.tradeability} color="var(--cp-indigo, #8E97FF)" symbol={c.symbol} kind="trade"
          note={c.futTurnoverCr != null ? `Futures turnover ₹${fmtNum(c.futTurnoverCr)} cr` : undefined} />
        <div className="flex flex-col" style={{ gap: 5 }}>
          <div className="flex items-baseline justify-between"><span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>Strategy quality</span><span style={quiet} data-testid={`desk-cand-strategy-${c.symbol}`}>Unavailable</span></div>
          <div style={{ height: 8, borderRadius: 999, background: "repeating-linear-gradient(135deg,var(--bg-4) 0 6px,var(--bg-3) 6px 12px)" }} />
          <span style={quiet}>Needs the cost model and a documented probability method. Not scored.</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: "6px 14px", paddingTop: 12, borderTop: "1px solid var(--line-2)" }} data-testid={`desk-cand-checks-${c.symbol}`}>
        <span style={quiet}>Confirmations</span>
        {checks.map((k) => (
          <span key={k.key} title={k.label} data-state={String(k.state)} className="inline-flex items-center" style={{ gap: 5, fontSize: 12, color: "var(--cp-ink-2)" }}>
            <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: "50%", boxSizing: "border-box", background: dot(k.state), border: k.state == null ? "1.5px solid var(--cp-ink-3)" : "none" }} />
            {CHECK_NAME[k.key]} <span style={{ color: "var(--cp-ink-3)" }}>{word(k.state)}</span>
          </span>
        ))}
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 8, padding: "10px 12px", borderRadius: 10, background: "var(--bg-1)", border: "1px solid var(--line-2)" }}>
        <span style={quiet}>Fundamental context · not part of any score</span>
        <Pill>{FUND_WORD[c.fundamentalRating ?? ""] ?? "Unavailable"}</Pill>
      </div>
      <div className="flex flex-wrap" style={{ gap: 8 }}>
        <button type="button" data-testid={`desk-cand-open-${c.symbol}`} onClick={() => onOpen(c.symbol)}
          style={{ padding: "9px 16px", minHeight: 44, borderRadius: 10, border: "1px solid var(--mint-line)", background: "var(--mint-soft)", color: "var(--mint)", fontSize: 14, cursor: "pointer" }}>
          Open {c.symbol} chain ›
        </button>
      </div>
    </article>
  );
}

function ResearchBanner({ r }: { r: NonNullable<ReturnType<typeof useCandidates>["data"]>["research"] }) {
  const win = r.dataWindow?.from && r.dataWindow.to ? `${day(r.dataWindow.from)} – ${day(r.dataWindow.to)}` : null;
  return (
    <div role="note" data-testid="desk-cand-research" data-status={r.status} className="flex flex-col" style={{ gap: 10, padding: "16px 18px", borderRadius: 14, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
      <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
        <span className="cp-eyebrow" style={{ color: "var(--amber)" }}>Research setting · not validated</span>
        <span className="cp-mono-note">{[win && `tests ${win}`, r.lastUpdated && `updated ${day(r.lastUpdated)}`].filter(Boolean).join(" · ")}</span>
      </div>
      <p style={{ margin: 0, fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
        This list orders stocks for you to look at. It is not a recommendation and not a forecast. When the ranking was back-tested over a year it showed no skill beyond picking at random from the same pool, and tests of near, next and far expiries supported none of the hypotheses we set. Nothing here has passed an out-of-sample test.
      </p>
      {r.experiments.length > 0 && (
        <ul className="flex flex-wrap" style={{ gap: "6px 18px", margin: 0, padding: 0, listStyle: "none" }}>
          {r.experiments.map((e) => <li key={e.id} className="cp-mono-note" title={e.finding ?? undefined}>{e.stage} · {e.id}</li>)}
        </ul>
      )}
    </div>
  );
}

export default function CandidatesView({ onOpen }: { onOpen: (symbol: string) => void }) {
  const { mobile } = useCopilotShell();
  const q = useCandidates(true);
  const [picked, setPicked] = useState<BuildupQuadrant | null>(null);
  const first = q.data ? BUILDUP_LABELS.find((l) => q.data.categories[l].candidates.length > 0) ?? BUILDUP_LABELS[0] : null;
  const cat: BuildupQuadrant | null = picked ?? first;
  useEffect(() => { setPicked(null); }, [q.data?.asOf]);

  if (q.isPending) return <LoadingBlock label="Loading the candidates" rows={4} />;
  if (q.isError) return <QueryProblem what="The candidates" error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data;
  const c: CandidateCategory = d.categories[cat ?? BUILDUP_LABELS[0]];
  const meta = BUILDUP_META[c.label];
  const excluded = Object.entries(c.excluded).filter(([, n]) => n > 0);
  return (
    <div data-testid="desk-fno-candidates" className="flex flex-col min-w-0" style={{ gap: 16 }}>
      <ResearchBanner r={d.research} />
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 12, minWidth: 0 }}>
        <div style={{ maxWidth: "100%", overflowX: "auto" }}>
        <Segmented<BuildupQuadrant>
          label="Build-up category" testId="desk-cand-category" value={cat}
          options={BUILDUP_LABELS.map((l) => ({ value: l, label: `${BUILDUP_META[l].label} ${d.categories[l].candidates.length}` }))}
          onChange={setPicked}
        />
        </div>
        <span className="cp-mono-note">{day(d.asOf) ? `Close of ${day(d.asOf)}` : "Latest close"}{d.featuresAsOf ? ` · stock features of ${day(d.featuresAsOf)}` : ""}</span>
      </div>
      <div className="flex flex-col" style={{ gap: 4 }}>
        <span style={{ fontSize: 14, lineHeight: 1.5, color: "var(--cp-ink-2)" }} data-testid="desk-cand-meaning">
          <strong style={{ fontWeight: 500, color: TONE_COLOR[meta.tone] }}>{meta.label}</strong> · {meta.rule}. {c.meaning ? `${c.meaning} ` : ""}A heuristic reading of two figures; it does not prove who is trading or why.
        </span>
        <span className="cp-mono-note" data-testid="desk-cand-pool">
          Pool {fmtNum(c.pool)} liquid stocks{excluded.map(([k, n]) => ` · ${fmtNum(n)} left out (${k.replace(/_/g, " ")})`).join("")}
        </span>
      </div>
      {c.candidates.length === 0
        ? <span data-testid="desk-cand-empty" style={quiet}>No stock in this category had enough of its inputs to be ordered on this day.</span>
        : (
          <div className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "repeat(auto-fit,minmax(380px,1fr))", gap: 16, alignItems: "start" }}>
            {c.candidates.map((x, i) => <CandidateCard key={x.symbol} c={x} rank={i + 1} of={c.candidates.length} onOpen={onOpen} />)}
          </div>
        )}
      {c.unranked.length > 0 && (
        <details data-testid="desk-cand-unranked" className="cp-card" style={{ padding: "12px 16px" }}>
          <summary style={{ cursor: "pointer", fontSize: 14, color: "var(--cp-ink-2)", minHeight: 24 }}>
            Not ordered · {fmtNum(c.unranked.length)} {c.unranked.length === 1 ? "stock" : "stocks"} with too few of their inputs
          </summary>
          <div className="flex flex-col" style={{ gap: 6, paddingTop: 10 }}>
            {c.unranked.map((u) => <span key={u.symbol} className="cp-mono-note">{u.symbol} · signal coverage {pct0(u.signalCoverage)}{u.reason ? ` · ${u.reason}` : ""}</span>)}
          </div>
        </details>
      )}
      <div className="flex flex-col" style={{ gap: 8, padding: "16px 18px", borderRadius: 12, border: "1px solid var(--line-2)" }}>
        <span className="cp-eyebrow">How to read this</span>
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, color: "var(--cp-ink-2)" }}>{d.disclosure}</p>
        {d.gaps.length > 0 && <ul style={{ margin: 0, paddingLeft: 18, ...quiet }}>{d.gaps.map((g) => <li key={g}>{g}</li>)}</ul>}
        <TrustLine testId="desk-cand-trust" source="NSE F&O bhavcopy" asOf={day(d.asOf)} mode="eod" maker="rules" method="Not validated" />
      </div>
    </div>
  );
}
