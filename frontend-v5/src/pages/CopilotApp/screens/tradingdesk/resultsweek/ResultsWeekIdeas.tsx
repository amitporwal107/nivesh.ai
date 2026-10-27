/**
 * Smart trading desk · AI Scanner › "Results week ideas" (docs/EARNINGS_SURPRISE_TRACKER.md §4c, §6), beside the Top 10.
 *
 *   GET /api/desk/results-week?date=   `ideas.fno` / `ideas.all` and `ideas.note` (the same read, and the same cache, as
 *                                      Events › Results week)
 *
 * Two lists: F&O names (with OI build-up) and every results name (technicals and fundamentals only). Each row: rank,
 * symbol, declared / upcoming, the route's early-signal order value, its parts and why. The order is labelled NOT YET
 * TESTED: a pre-registered validation runs alongside it (§7). Chartink hits are shown elsewhere, never scored here.
 *
 * Wording (SEBI): "ideas", "ordered for review"; never picks or advice. Nothing here places an order.
 */
import { useState } from "react";
import { ErrorBlock, LoadingBlock, fmtNum } from "../../../components/ui";
import { useCopilotShell } from "../../../lib/shell-context";
import { SymbolCell } from "../../desk/parts";
import { useDesk, type TrailFrom } from "../context";
import { Segmented } from "../fno-parts";
import { istParts, useNow } from "../overview-data";
import { Widget } from "../widget";
import { useResultsWeek, type RwIdea } from "./results-week-data";
import { Chip, NA, line, mono, quiet } from "./parts";

const ANCHOR = "results-week-ideas";
const FROM: TrailFrom = { label: "Results week ideas", anchor: ANCHOR };
const DEFAULT_NOTE = "Ordered for review, not a prediction. This ordering has not been tested yet.";
const SHOWN = 15;
type List = "fno" | "all";

function IdeaRow({ idea, i }: { idea: RwIdea; i: number }) {
  const desk = useDesk();
  const rank = idea.rank ?? i + 1;
  return (
    <li data-testid={`results-week-idea-${idea.symbol}`} className="flex min-w-0 flex-col" style={{ gap: 6, padding: "11px 0", borderTop: line }}>
      <div className="flex min-w-0 items-center" style={{ gap: 10 }}>
        <span data-testid="results-week-idea-rank" className="cp-num" style={{ flex: "none", width: 22, fontSize: 11, color: "var(--cp-ink-3)" }}>{String(rank).padStart(2, "0")}</span>
        <span className="min-w-0" style={{ flex: "1 1 auto" }}>
          <SymbolCell symbol={idea.symbol} name={idea.name} sub={idea.name ?? undefined} testId="results-week-idea-symbol" size={24} />
        </span>
        <span className="flex flex-none flex-col items-end" style={{ gap: 3 }}>
          <span data-testid="results-week-idea-signal" className="cp-num" style={{ fontSize: 12 }} title="The route's early-signal order value, 0–100. Not a probability; not yet tested.">
            {idea.signal != null ? `Signal ${fmtNum(idea.signal, 0)}` : idea.signalLabel ?? "Signal n/a"}
          </span>
          <span data-testid="results-week-idea-phase" style={{ ...mono, fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase", padding: "2px 7px", borderRadius: 999, border: `1px solid ${idea.phase === "declared" ? "var(--mint-line)" : "var(--line-2)"}`, color: idea.phase === "declared" ? "var(--mint)" : "var(--cp-ink-2)" }}>
            {idea.phase === "declared" ? "Declared" : idea.phase === "upcoming" ? "Upcoming" : "Phase n/a"}
          </span>
        </span>
      </div>
      <div className="flex min-w-0 flex-col" style={{ gap: 4, paddingLeft: 32 }}>
        <span data-testid="results-week-idea-parts" className="flex flex-wrap" style={{ gap: 4 }}>
          {idea.parts.length
            ? idea.parts.map((p) => <Chip key={p.key} tone={p.value == null ? "muted" : "ink"} title={p.value == null ? `${p.label}: not available` : undefined}>{p.label} {p.value != null ? fmtNum(p.value, 0) : "n/a"}</Chip>)
            : <NA text="parts not reported" />}
        </span>
        {idea.why.length > 0 && <span data-testid="results-week-idea-why" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{idea.why.join(" · ")}</span>}
        <span className="flex flex-wrap" style={{ gap: 6, paddingTop: 2 }}>
          <button type="button" className="cp-chip" data-testid="results-week-idea-chart" onClick={() => { desk.noteFrom(FROM); desk.openChart(idea.symbol); }} style={{ fontSize: 12, padding: "5px 11px" }}>Chart ›</button>
        </span>
      </div>
    </li>
  );
}

export function ResultsWeekIdeas() {
  const { mobile } = useCopilotShell();
  const today = istParts(useNow(60_000)).iso;
  const q = useResultsWeek(today);
  const [list, setList] = useState<List>("fno");
  const [all, setAll] = useState(false);
  const d = q.data;
  const ideas = d ? (list === "fno" ? d.ideas.fno : d.ideas.all) : [];
  const shown = all ? ideas : ideas.slice(0, SHOWN);
  return (
    <Widget
      id="scanner.resultsweek"
      testId={ANCHOR}
      title="Results week ideas"
      meta={<span style={{ fontSize: 9.5 }}>Ordered for review · vs historical trend · end of day</span>}
      actions={<span data-testid="results-week-ideas-untested" style={{ ...mono, fontSize: 9, letterSpacing: "0.12em", padding: "3px 8px", borderRadius: 999, border: "1px solid var(--amber-line)", color: "var(--amber)" }}>NOT YET TESTED</span>}
      bodyStyle={{ padding: mobile ? 14 : 18, gap: 10 }}
    >
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
        <Segmented<List> label="Results week list" testId="results-week-ideas-toggle" value={list} onChange={(v) => { setList(v); setAll(false); }}
          options={[{ value: "fno", label: `F&O${d ? ` ${d.ideas.fno.length}` : ""}` }, { value: "all", label: `All${d ? ` ${d.ideas.all.length}` : ""}` }]} />
        <span style={{ ...quiet, fontSize: 11.5 }}>{list === "fno" ? "F&O names: earnings, reaction, OI build-up, technicals" : "Every results name: no OI part, its weight spread pro rata"}</span>
      </div>
      {q.isPending ? (
        <div data-testid="results-week-ideas-loading"><LoadingBlock label="Loading the results week ideas" rows={3} /></div>
      ) : q.isError || !d ? (
        <div data-testid="results-week-ideas-error"><ErrorBlock title="The results week ideas didn’t load" error={q.error} onRetry={() => q.refetch()} /></div>
      ) : ideas.length === 0 ? (
        <p data-testid="results-week-ideas-empty" className="m-0" style={quiet}>No results-week ideas in this list today.</p>
      ) : (
        <ol data-testid="results-week-ideas-list" className="m-0 p-0" style={{ listStyle: "none" }}>
          {shown.map((idea, i) => <IdeaRow key={`${list}-${idea.symbol}`} idea={idea} i={i} />)}
        </ol>
      )}
      {d && ideas.length > SHOWN && (
        <button type="button" className="cp-chip" data-testid="results-week-ideas-more" onClick={() => setAll((v) => !v)} style={{ alignSelf: "flex-start", fontSize: 11.5, padding: "4px 10px" }}>{all ? "Show fewer" : `Show all ${ideas.length}`}</button>
      )}
      <p data-testid="results-week-ideas-note" className="m-0" style={{ ...quiet, fontSize: 11.5 }}>
        {d?.ideas.note ?? DEFAULT_NOTE} Nothing here places an order.
      </p>
    </Widget>
  );
}

export default ResultsWeekIdeas;
