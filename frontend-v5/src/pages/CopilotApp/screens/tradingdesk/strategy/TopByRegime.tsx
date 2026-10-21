/**
 * Smart trading desk — Strategy Builder, "Top by regime".
 *
 *   POST /api/desk/strategy/top   the best N ideas per asset class; reads only, writes nothing
 *
 * The user's requirement (2026-10-22): "the top 5 best trading strategy for nifty/banknifty options
 * and stock f/o and cash stocks", ranked by fit to the measured market regime.
 *
 * WHAT THIS SCREEN MUST NOT IMPLY. "Best" here is fit to today's conditions, priced from the live
 * end-of-day chain. It is NOT a performance ranking: the platform records no realised strategy
 * performance to rank by, and no option-IV history, so neither a track record nor an IV percentile
 * exists. The route says so in `ranking_note` and `gaps`, and both are rendered on screen rather
 * than hidden behind a tooltip — a caveat nobody reads is the same as no caveat.
 *
 * The cash class is NOT ranked by regime fit: it is the desk's existing "From AI opportunities"
 * answer kept unchanged, so its ideas carry the scanner's evidence rank and have no fit score. That
 * difference is stated above the cash section instead of being smoothed over.
 *
 * Every figure shown is what the route returned. Nothing is recomputed here and nothing is sent to
 * a broker.
 */
import { useMemo, useState } from "react";
import { EmptyBlock, ErrorBlock, LoadingBlock, Section, fmtINR, fmtNum, fmtPct } from "../../../components/ui";
import { fmtDay } from "../../trading/parts";
import { DASH, noteStyle } from "./plan-format";
import { TOP_LIMIT, useStrategyTop, type TopRun } from "./top-data";
import type { FitFactor, OptionClass, OptionIdea, Regime } from "./top-contract";

const STATE_TONE: Record<string, { glyph: string; color: string }> = {
  supports: { glyph: "+", color: "var(--good, #3fbf87)" },
  conflicts: { glyph: "−", color: "var(--neg, #e06c75)" },
  neutral: { glyph: "·", color: "var(--cp-ink-3)" },
};

function Why({ items }: { items: FitFactor[] }) {
  if (!items.length) return null;
  return (
    <ul data-testid="idea-why" className="flex flex-col" style={{ gap: 4, margin: 0, padding: 0, listStyle: "none" }}>
      {items.map((f, i) => {
        const tone = STATE_TONE[f.state] ?? STATE_TONE.neutral;
        return (
          <li key={`${f.factor}-${i}`} className="flex" style={{ gap: 6, ...noteStyle }}>
            <span aria-hidden style={{ color: tone.color, fontWeight: 600, width: 10 }}>{tone.glyph}</span>
            <span><span className="sr-only">{f.state}: </span>{f.text}</span>
          </li>
        );
      })}
    </ul>
  );
}

function Fig({ k, v, title }: { k: string; v: string; title?: string }) {
  return (
    <div className="flex min-w-0 flex-col" title={title} style={{ gap: 2 }}>
      <span style={{ fontSize: 11, letterSpacing: 0.3, textTransform: "uppercase", color: "var(--cp-ink-3)" }}>{k}</span>
      <span style={{ fontSize: 13, fontVariantNumeric: "tabular-nums" }}>{v}</span>
    </div>
  );
}

function IdeaCard({ idea }: { idea: OptionIdea }) {
  const rr = idea.reward_risk;
  const be = idea.breakevens.length ? idea.breakevens.map((b) => fmtNum(b, 2)).join(", ") : DASH;
  const maxProfit = idea.profit_unbounded ? "No upper limit" : fmtINR(idea.max_profit);
  const maxLoss = idea.loss_unbounded ? "No lower limit" : fmtINR(idea.max_loss);
  const g = idea.net_greeks ?? {};
  return (
    <article data-testid={`top-idea-${idea.underlying}-${idea.structure}`} className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: 12 }}>
      <header className="flex flex-wrap items-baseline" style={{ gap: 8 }}>
        <span data-testid="idea-rank" style={{ fontSize: 12, color: "var(--cp-ink-3)", fontVariantNumeric: "tabular-nums" }}>
          {idea.rank != null ? String(idea.rank).padStart(2, "0") : DASH}
        </span>
        <h4 data-testid="idea-name" style={{ margin: 0, fontSize: 15 }}>{idea.name}</h4>
        <span className="cp-chip" style={{ fontSize: 11 }}>{idea.underlying}</span>
        {idea.expiry ? <span style={noteStyle}>exp {fmtDay(idea.expiry)}{idea.days_to_expiry != null ? ` · ${idea.days_to_expiry}d` : ""}</span> : null}
        <span
          data-testid="idea-fit"
          className="cp-chip"
          style={{ marginLeft: "auto", fontSize: 11, borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" }}
          title="How well this structure fits the measured regime. Not a probability and not a track record."
        >
          fit {fmtNum(idea.fit.score, 1)}
        </span>
      </header>

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: 10 }}>
        <Fig k="Max loss" v={maxLoss} />
        <Fig k="Max gain" v={maxProfit} />
        <Fig k="Capital at risk" v={fmtINR(idea.capital_at_risk)} title={idea.capital_at_risk_basis ?? undefined} />
        <Fig k="Breakeven" v={be} />
        <Fig
          k="Reward : risk"
          v={rr == null ? DASH : `${fmtNum(rr, 2)} : 1`}
          title={idea.reward_risk_basis ?? undefined}
        />
      </div>

      {(g.delta != null || g.theta != null || g.vega != null) ? (
        <div data-testid="idea-greeks" style={noteStyle}>
          net delta {g.delta != null ? fmtNum(g.delta, 2) : DASH} · theta {g.theta != null ? fmtNum(g.theta, 2) : DASH} · vega {g.vega != null ? fmtNum(g.vega, 2) : DASH}
        </div>
      ) : null}

      <Why items={idea.fit.because} />

      <footer style={{ ...noteStyle, borderTop: "1px solid var(--cp-line)", paddingTop: 8 }}>
        {idea.price_source ?? "end-of-day prices"}
        {idea.reward_risk_theoretical != null ? (
          <> · theoretical reward : risk {fmtNum(idea.reward_risk_theoretical, 2)} measures the payoff at a price of zero and is not what this is ranked on</>
        ) : null}
        {idea.margin == null && idea.margin_reason ? <> · {idea.margin_reason}</> : null}
      </footer>
    </article>
  );
}

function Unavailable({ rows }: { rows: OptionClass["unavailable"] }) {
  if (!rows.length) return null;
  return (
    <details data-testid="top-unavailable" style={{ ...noteStyle, marginTop: 8 }}>
      <summary style={{ cursor: "pointer" }}>{rows.length} underlying{rows.length === 1 ? "" : "s"} could not be read</summary>
      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
        {rows.map((r, i) => <li key={`${r.underlying}-${i}`}>{r.underlying ?? "—"}: {r.reason ?? "no reason given"}</li>)}
      </ul>
    </details>
  );
}

function OptionSection({ title, note, cls, testId }: { title: string; note: string; cls?: OptionClass; testId: string }) {
  if (!cls) return null;
  return (
    <Section title={title} note={note}>
      <div data-testid={testId} className="flex flex-col" style={{ gap: 10 }}>
        {cls.ideas.length === 0 ? (
          <EmptyBlock
            title="No idea fits here"
            body={
              cls.unavailable.length
                ? "Every underlying tried was unreadable or offered no structure that priced — see below."
                : "No structure in this class passed its own gates against the current chain."
            }
          />
        ) : (
          cls.ideas.map((idea) => <IdeaCard key={`${idea.underlying}-${idea.structure}-${idea.rank}`} idea={idea} />)
        )}
        {cls.considered != null ? (
          <p style={noteStyle} data-testid="top-considered">
            {cls.ideas.length} shown of {cls.considered} priced{cls.as_of ? ` · chain as of ${fmtDay(cls.as_of)}` : ""}
          </p>
        ) : null}
        <Unavailable rows={cls.unavailable} />
      </div>
    </Section>
  );
}

function RegimeStrip({ regime, staleness }: { regime: Regime; staleness?: string | null }) {
  if (!regime.available) {
    return (
      <div data-testid="top-regime" className="cp-card" style={{ padding: 12 }}>
        <p style={noteStyle}>
          The market regime is unavailable{regime.reason ? `: ${regime.reason}` : ""}, so nothing can be scored for fit.
        </p>
      </div>
    );
  }
  const vix = regime.india_vix;
  const thr = regime.vix_high_threshold;
  return (
    <div data-testid="top-regime" className="cp-card flex flex-wrap items-center" style={{ gap: 14, padding: 12 }}>
      <Fig k="Regime" v={regime.label ?? regime.key ?? DASH} />
      <Fig k="Trend" v={regime.trend ?? DASH} title={regime.nifty_vs_average_pct != null ? `Nifty ${fmtPct(regime.nifty_vs_average_pct, { signed: true, digits: 2 })} against its 50-session average` : undefined} />
      <Fig
        k="India VIX"
        v={vix != null ? `${fmtNum(vix, 2)}${thr != null ? ` (${vix < thr ? "below" : "at or above"} ${fmtNum(thr, 1)})` : ""}` : DASH}
        title="Volatility is judged against the desk regime's own threshold. No option-IV history is stored, so this is not an IV percentile."
      />
      <Fig k="Breadth" v={regime.breadth ? `${regime.breadth}${regime.advancing_share_pct != null ? ` · ${fmtNum(regime.advancing_share_pct, 1)}% advancing` : ""}` : DASH} />
      <div className="flex min-w-0 flex-col" style={{ gap: 2, marginLeft: "auto" }}>
        <span style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.3, color: "var(--cp-ink-3)" }}>Measured</span>
        <span style={{ fontSize: 13 }}>{regime.as_of ? fmtDay(regime.as_of) : DASH}</span>
      </div>
      {staleness ? <p data-testid="top-staleness" style={{ ...noteStyle, flexBasis: "100%", margin: 0 }}>{staleness}</p> : null}
    </div>
  );
}

export function TopByRegime() {
  const [run, setRun] = useState<TopRun>({ body: { limit: TOP_LIMIT }, runId: 1 });
  const q = useStrategyTop(run);
  const board = q.data;
  const again = () => setRun((r) => ({ body: r.body, runId: r.runId + 1 }));

  const cash = board?.classes.cash;
  const cashRows = useMemo(() => cash?.ideas ?? [], [cash]);

  if (q.isPending && !board) return <LoadingBlock label="Ranking strategies against the current regime" rows={4} />;
  if (q.isError && !board) return <ErrorBlock error={q.error} onRetry={again} />;
  if (!board) return null;

  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 14 }} data-testid="top-by-regime">
      <RegimeStrip regime={board.regime} staleness={board.staleness_note} />

      <p data-testid="top-ranking-note" style={noteStyle}>{board.ranking_note}</p>

      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <button type="button" className="cp-chip" data-testid="top-rebuild" onClick={again} disabled={q.isFetching}>
          {q.isFetching ? "Ranking…" : "Rank again"}
        </button>
        <span style={noteStyle}>{board.rules_version}{board.generated_at ? ` · built ${fmtDay(board.generated_at)}` : ""}</span>
      </div>

      {q.isError ? <ErrorBlock error={q.error} onRetry={again} /> : null}

      <OptionSection
        testId="top-class-index_options"
        title="Index options — NIFTY and BANKNIFTY"
        note="Defined-risk structures only: an index cannot be held, so there is no covered call, protective put or collar here."
        cls={board.classes.index_options}
      />

      <OptionSection
        testId="top-class-stock_fno"
        title="Stock F&O"
        note={board.classes.stock_fno?.universe?.source ?? "From the AI scanner's own ranked names."}
        cls={board.classes.stock_fno}
      />

      {cash ? (
        <Section title="Cash stocks" note={board.ranking_note_cash ?? cash.ranking ?? undefined}>
          <div data-testid="top-class-cash" className="flex flex-col" style={{ gap: 8 }}>
            {cashRows.length === 0 ? (
              <EmptyBlock title="No cash idea" body="The scanner returned nothing that passed its gates." />
            ) : (
              <ol style={{ margin: 0, paddingLeft: 20 }}>
                {cashRows.map((c, i) => (
                  <li key={`${c.symbol ?? c.name ?? i}`} style={{ marginBottom: 4 }}>
                    <span style={{ fontSize: 14 }}>{c.name ?? c.symbol ?? DASH}</span>
                    {c.symbol && c.name ? <span style={{ ...noteStyle, marginLeft: 6 }}>{c.symbol}</span> : null}
                    {c.plan_status ? <span style={{ ...noteStyle, marginLeft: 6 }}>· {c.plan_status}</span> : null}
                  </li>
                ))}
              </ol>
            )}
            {cash.as_of ? <p style={noteStyle}>Scanner data as of {fmtDay(cash.as_of)}</p> : null}
          </div>
        </Section>
      ) : null}

      {board.gaps.length ? (
        <Section title="What this cannot tell you">
          <ul data-testid="top-gaps" style={{ ...noteStyle, margin: 0, paddingLeft: 18 }}>
            {board.gaps.map((g, i) => <li key={i} style={{ marginBottom: 4 }}>{g}</li>)}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}

export default TopByRegime;
