/**
 * Paper trades. Design: NVPages.dc.html, page === "paper".
 *
 * Data (existing adapter services/adapters/paperTrades.adapter.ts → backend/routes/paper_trades.py):
 *   GET /api/paper-trades/portfolio?sample=&portfolio=&prediction_date=   one frozen session and its positions
 *   GET /api/paper-trades/evaluation?sample=&portfolio=                   the stored evaluation of the sample
 *   GET /api/paper-trades/live?portfolio=                                 delayed status of the latest forward session
 *
 * The API answers 403 to accounts without the move_odds feature; the screen
 * then says so and shows nothing else. Returns are fractions (0.05 = 5%) and
 * are shown as the engine stored them. Forward and replay are separate samples
 * and are never pooled. "Open" and "closed" follow the engine's headline exit.
 */
import { useState, type ReactNode } from "react";
import {
  PORTFOLIOS,
  type PaperEvaluation, type PaperLive, type PaperLivePosition, type PaperPortfolio, type PaperPortfolioData, type PaperPosition, type PaperSample,
} from "@/services/adapters/paperTrades.adapter";
import { MODE_SESSION, clock } from "@/pages/Research/paperMath";
import {
  Btn, DataTable, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Screen, ScreenHeader, Section, Tiles,
  TONE_COLOR, fmtINR, fmtNum, fmtPct, humaniseTag, signTone,
  type Column, type TileItem, type Tone,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { Choices, INPUT_STYLE, Labeled, fmtDay, fmtPrice } from "./trading/parts";
import { usePaperEvaluation, usePaperLive, usePaperPortfolio } from "./trading/queries";

const SAMPLES: Array<{ value: PaperSample; label: string }> = [
  { value: "forward", label: "Forward" },
  { value: "replay", label: "Replay · 2025" },
];

/** What each exit mode means, as the engine defines it. */
const MODE_RULE: Record<string, string> = {
  "EOD-1": "close of the entry day",
  "EOD-3": "close of day 2",
  "EOD-5": "close of day 4",
  FIXED: "close of day 5, no early exit",
  TARGET_STOP: "first level touched, else the day 5 close",
};
const WAITING = new Set(["PENDING_ENTRY", "ENTERED", "MONITORING"]);
const SESSIONS = MODE_SESSION.FIXED;

/** Percent text from a fraction (0.0509 → "+5.09%"). */
const pct = (x: number | null | undefined, opts: { signed?: boolean; digits?: number } = {}) => fmtPct(x == null ? null : x * 100, opts);
const toned = (text: string, tone: Tone): ReactNode => <span style={{ color: TONE_COLOR[tone] }}>{text}</span>;
const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;

const headOf = (ev: PaperEvaluation) => ev.modes.find((m) => m.mode === ev.headline_mode) ?? ev.modes[0];
const baselineOf = (ev: PaperEvaluation) => ev.benchmarks.find((b) => b.benchmark === "A_ALL" && b.mode === ev.headline_mode);

function splitPositions(s: PaperPortfolioData) {
  const mode = s.config.headline_mode;
  const closed = s.positions.filter((p) => p.exits[mode]?.state === "CLOSED");
  const open = s.positions.filter((p) => p.exits[mode]?.state !== "CLOSED" && WAITING.has(p.status));
  const other = s.positions.filter((p) => p.exits[mode]?.state !== "CLOSED" && !WAITING.has(p.status));
  return { open, closed, other };
}

const targetOf = (p: PaperPosition, s: PaperPortfolioData) => (s.config.target_pct === 5 ? p.target_1_price : p.target_2_price);
const positionLabel = (p: PaperPosition) => `${p.symbol}${p.quantity != null ? ` · ${fmtNum(p.quantity, 2)} units` : ""}`;

// ── evaluation: statement + tiles ────────────────────────────────────────

function Statement({ ev }: { ev: PaperEvaluation }) {
  const head = headOf(ev);
  const counted = ev.sessions.counted;
  const closed = head?.closed_trades ?? 0;
  const ok = ev.statement.established;
  return (
    <div data-testid="paper-statement" className="flex items-start" style={{ gap: 12, padding: "12px 16px", borderRadius: 12, border: `1px solid var(${ok ? "--mint-line" : "--amber-line"})`, background: `var(${ok ? "--mint-soft" : "--amber-soft"})` }}>
      <span className="cp-mono-note" style={{ color: `var(${ok ? "--mint" : "--amber"})`, paddingTop: 2, flex: "none" }}>{ok ? "Established" : "Sample"}</span>
      <span className="cp-pretty" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
        {ev.statement.text}{" "}
        {counted < ev.statement.min_sessions
          ? `${plural(counted, "counted session")} and ${plural(closed, "closed paper trade")} are too few to conclude anything; the pre-registered minimum is ${fmtNum(ev.statement.min_sessions)} sessions.`
          : `${plural(counted, "counted session")}, ${plural(closed, "closed headline trade")}.`}
        {ev.sample === "replay" ? " Replay is a retrospective walk-forward of 2025. It is evaluated separately from the forward record and never pooled with it." : ""}
        {ev.sample === "forward" && ev.sessions.not_counted.length > 0 ? ` Recorded but not counted: ${ev.sessions.not_counted.map(fmtDay).join(", ")}.` : ""}
      </span>
    </div>
  );
}

function EvaluationTiles({ ev, session, sessionNote }: { ev: PaperEvaluation; session: PaperPortfolioData | null; sessionNote: string }) {
  const head = headOf(ev);
  const base = baselineOf(ev);
  const edge = head?.edge_vs_a_all ?? null;
  const items: TileItem[] = [
    {
      k: "Open · this session",
      v: <span data-testid="paper-open-count">{session ? fmtNum(splitPositions(session).open.length) : "—"}</span>,
      s: session ? `Predicted ${fmtDay(session.prediction_date)}` : sessionNote,
    },
    {
      k: `Closed · ${ev.headline_mode}`,
      v: <span data-testid="paper-closed-count">{fmtNum(head?.closed_trades ?? 0)}</span>,
      s: `${fmtNum(ev.sessions.counted)} of ${plural(ev.sessions.recorded, "session")} counted`,
    },
    {
      k: "Net P&L",
      v: <span data-testid="paper-net-pnl">{fmtINR(head?.total_net_inr, { signed: true })}</span>,
      s: `After ${ev.costs.base}% costs`,
      tone: signTone(head?.total_net_inr),
    },
    {
      k: "Hit rate",
      v: <span data-testid="paper-hit-rate">{pct(head?.win_rate)}</span>,
      s: base?.positive_rate != null ? `Every eligible stock ${pct(base.positive_rate)}` : "Trades closed above cost",
    },
    {
      k: "vs every eligible stock",
      v: <span data-testid="paper-edge">{pct(edge?.mean, { signed: true, digits: 2 })}</span>,
      s: edge?.lo != null && edge.hi != null ? `Per trade · 95% CI ${pct(edge.lo, { signed: true, digits: 2 })} to ${pct(edge.hi, { signed: true, digits: 2 })}` : "Per trade · needs counted sessions",
      tone: signTone(edge?.mean),
    },
  ];
  return <Tiles items={items} min={140} />;
}

// ── one session: open and closed positions ───────────────────────────────

function LiveNote({ live }: { live: PaperLive }) {
  const e = live.evidence;
  return (
    <div className="flex flex-col" style={{ gap: 10, padding: "10px 16px 14px" }}>
      {e && (
        <div data-testid="paper-live-evidence" className="cp-pretty" style={{ padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          <strong style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{e.headline}</strong>{" "}
          Walk-forward over {fmtNum(e.walk_forward.sessions)} sessions ({e.walk_forward.window}): {fmtPct(e.walk_forward.mean_net_per_trade_pct, { signed: true, digits: 2 })} per trade after costs,
          95% interval {fmtPct(e.walk_forward.ci95[0], { signed: true, digits: 2 })} to {fmtPct(e.walk_forward.ci95[1], { signed: true, digits: 2 })}, verdict {e.walk_forward.verdict}. {e.why}
        </div>
      )}
      <Footnote>Live column: {live.source}, {live.delay_note} · as of {clock(live.fetched_at)}. {live.official_note}</Footnote>
    </div>
  );
}

function SessionTables({ s, live, liveProblem }: { s: PaperPortfolioData; live: PaperLive | null; liveProblem: ReactNode }) {
  const mode = s.config.headline_mode;
  const { open, closed, other } = splitPositions(s);
  const liveBy = new Map<string, PaperLivePosition>((live?.positions ?? []).map((p) => [p.symbol, p]));

  const openCols: Column<PaperPosition>[] = [
    { key: "pos", header: "Position", width: "minmax(0,1.8fr)", render: (p) => <span data-testid="paper-open-row" title={p.company_name ?? undefined} style={{ color: "var(--cp-ink)" }}>{positionLabel(p)}</span> },
    { key: "entry", header: "Entry", num: true, render: (p) => (p.entry_price != null ? fmtPrice(p.entry_price) : `Open of ${fmtDay(p.intended_entry_date)}`) },
    { key: "stop", header: "Stop", num: true, render: (p) => fmtPrice(p.stop_loss_price) },
    { key: "target", header: "Target", num: true, render: (p) => fmtPrice(targetOf(p, s)) },
    {
      key: "unreal", header: "Unrealised", num: true,
      render: (p) => {
        const r = p.observations.length ? p.observations[p.observations.length - 1].return_from_entry : null;
        return toned(pct(r, { signed: true, digits: 2 }), signTone(r));
      },
    },
    { key: "day", header: "Session", num: true, render: (p) => (p.entry_price == null ? "Awaiting entry" : `${fmtNum(p.sessions_observed ?? p.observations.length)} of ${SESSIONS}`) },
  ];
  if (live) {
    openCols.push({
      key: "live", header: "Live", width: "minmax(0,1.3fr)",
      render: (p) => {
        const l = liveBy.get(p.symbol);
        if (!l) return "—";
        return <span data-testid="paper-live-status" title={l.note}>{l.label}{l.return_from_entry != null ? ` · ${pct(l.return_from_entry, { signed: true, digits: 2 })}` : ""}</span>;
      },
    });
  }

  const closedCols: Column<PaperPosition>[] = [
    { key: "pos", header: "Trade", width: "minmax(0,1.8fr)", render: (p) => <span data-testid="paper-closed-row" title={p.company_name ?? undefined} style={{ color: "var(--cp-ink)" }}>{positionLabel(p)}</span> },
    { key: "entry", header: "Entry", num: true, render: (p) => fmtPrice(p.entry_price) },
    { key: "exit", header: "Exit", num: true, render: (p) => fmtPrice(p.exits[mode]?.exit_price) },
    {
      key: "reason", header: "Reason", width: "minmax(0,1.4fr)",
      render: (p) => {
        const e = p.exits[mode];
        return `${e?.exit_reason ?? "Closed"}${e?.exit_date ? ` · ${fmtDay(e.exit_date)}` : ""}`;
      },
    },
    { key: "net", header: "Net", num: true, render: (p) => <span data-testid="paper-closed-net">{toned(pct(p.exits[mode]?.net_return, { signed: true, digits: 2 }), signTone(p.exits[mode]?.net_return))}</span> },
    {
      key: "costs", header: "Costs", num: true,
      render: (p) => {
        const c = p.exits[mode]?.cost_pct;
        return c != null ? `${c}%` : "—";
      },
    },
  ];

  const note = `Predicted ${fmtDay(s.prediction_date)} · entry ${fmtDay(s.provenance.next_trading_session)}`;
  return (
    <>
      <Section title="Open positions" note={note} flush>
        <DataTable columns={openCols} rows={open} rowKey={(p) => String(p.trade_id)} minWidth={live ? 760 : 620} empty="No open positions in this session." />
        {live && <LiveNote live={live} />}
        {liveProblem && <div style={{ padding: "0 16px 14px" }}>{liveProblem}</div>}
      </Section>
      <Section title={`Closed · ${mode}, ${MODE_RULE[mode] ?? "headline exit"}`} note={note} flush>
        <DataTable columns={closedCols} rows={closed} rowKey={(p) => String(p.trade_id)} minWidth={660} empty="Nothing in this session has reached its headline exit yet." />
      </Section>
      {other.length > 0 && (
        <Footnote>
          Selected but not traded: {other.map((p) => `${p.symbol} (${p.status_reason ?? humaniseTag(p.status.toLowerCase())})`).join(", ")}.
        </Footnote>
      )}
    </>
  );
}

// ── fill assumptions ─────────────────────────────────────────────────────

function Assumptions({ s, ev }: { s: PaperPortfolioData; ev: PaperEvaluation | null }) {
  const c = s.config;
  const p = s.provenance;
  const head = ev ? headOf(ev) : undefined;
  const base = ev ? baselineOf(ev) : undefined;
  const rules = p.rules?.rules_id ?? p.rules_id;
  return (
    <Section title={`Fill assumptions · rules ${rules}${p.rules ? ` · ${p.rules.git_sha}` : ""} · frozen`}>
      <div data-testid="paper-assumptions" className="flex flex-col cp-pretty" style={{ gap: 6, fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
        <span>
          Entries at the next session’s official open. Target +{c.target_pct}% from entry. Stop {c.atr_multiplier} × ATR(14) below entry, or the 10-session support when that is lower,
          never more than {c.stop_cap_pct}% below entry. Costs {c.cost_pct}% round trip{c.cost_sensitivity_pct.length ? `, re-run at ${c.cost_sensitivity_pct.map((x) => `${x}%`).join(" and ")}` : ""}.
          Headline exit {c.headline_mode}: {MODE_RULE[c.headline_mode] ?? "pre-registered"}.
        </span>
        <span>
          Engine capital {fmtINR(c.capital_inr)} in {fmtNum(c.positions)} equal positions. Model {p.model_version}, features {p.feature_version}, frozen {fmtDay(p.prediction_timestamp)} {clock(p.prediction_timestamp)};
          {" "}{fmtNum(p.scored)} stocks scored, {fmtNum(p.eligible)} eligible.
        </span>
        {head && head.closed_trades > 0 && (
          <span>
            Observed so far: +{c.target_pct}% touched on {pct(head.target_hit_rate)} of {plural(head.closed_trades, "headline trade")}{base?.hit_rate != null ? `; every eligible stock ${pct(base.hit_rate)}` : ""}.
          </span>
        )}
      </div>
    </Section>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

export default function PaperScreen() {
  const { ask } = useCopilotShell();
  const [sample, setSample] = useState<PaperSample>("forward");
  const [portfolio, setPortfolio] = useState<PaperPortfolio>("P5-NEXT");
  const [date, setDate] = useState<string | null>(null);

  const pq = usePaperPortfolio(sample, portfolio, date);
  const eq = usePaperEvaluation(sample, portfolio);
  const session = pq.data?.kind === "ok" ? pq.data.data : null;
  const ev = eq.data?.kind === "ok" ? eq.data.data : null;
  const latestForward = sample === "forward" && session != null && session.dates[0]?.prediction_date === session.prediction_date;
  const lq = usePaperLive(portfolio, latestForward);
  const live = latestForward && lq.data?.kind === "ok" ? lq.data.data : null;
  const noAccess = pq.data?.kind === "no_access" || eq.data?.kind === "no_access";

  const head = ev ? headOf(ev) : undefined;
  const evaluate = () =>
    ask(
      ev && head
        ? `Evaluate my paper trades: ${ev.sample} ${ev.portfolio}, ${plural(head.closed_trades, "closed trade")} over ${plural(ev.sessions.counted, "counted session")}, net ${pct(head.net_mean, { signed: true, digits: 2 })} per trade after ${ev.costs.base}% costs. ${ev.statement.text}`
        : `Evaluate my paper trades (${sample} ${portfolio})`,
    );

  const liveProblem: ReactNode = !latestForward || !lq.data || lq.data.kind === "ok" || lq.data.kind === "empty"
    ? null
    : lq.data.kind === "error"
      ? <ErrorBlock title="Live status didn’t load. Official values are written after the close" error={lq.data.message} onRetry={() => lq.refetch()} />
      : <Footnote>Live status is not available for this account.</Footnote>;

  return (
    <Screen testId="screen-page-paper">
      <div className="flex flex-wrap items-end justify-between" style={{ gap: 14 }}>
        <div style={{ flex: "1 1 320px", minWidth: 0 }}>
          <ScreenHeader
            eyebrow="Paper trading · no live orders"
            title={<>Simulated <em>trades</em></>}
            sub="Frozen strategy versions, realistic fills and costs. Nothing here touches your broker account."
          />
        </div>
        {!noAccess && (
          <button type="button" data-testid="paper-evaluate" className="cp-chip" onClick={evaluate} style={{ borderColor: "var(--mint-line)", color: "var(--mint)" }}>
            Evaluate my paper trades
          </button>
        )}
      </div>

      {noAccess ? (
        <div data-testid="paper-no-access">
          <EmptyBlock
            title="Paper trades are not enabled for this account"
            body="This research page is limited to invited accounts. An admin can turn on the move-odds research feature for you."
          />
        </div>
      ) : (
        <>
          <div role="note" data-testid="paper-disclaimer" className="flex items-start" style={{ gap: 12, padding: "12px 16px", borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-1)" }}>
            <span className="cp-mono-note" style={{ paddingTop: 2, flex: "none" }}>Disclaimer</span>
            <span className="cp-pretty" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
              Simulated paper trades for research. No orders are placed and no capital is at risk. This analysis is for informational purposes only and does not constitute investment advice.
              Past performance is not indicative of future results. Please consult a SEBI-registered investment advisor before making investment decisions.
            </span>
          </div>

          <div className="flex flex-wrap items-end" style={{ gap: "10px 16px" }}>
            <Choices label="Sample" testId="paper-sample" value={sample} options={SAMPLES} onChange={(v) => { setSample(v); setDate(null); }} />
            <Choices label="Portfolio" testId="paper-portfolio" value={portfolio} options={PORTFOLIOS.map((p) => ({ value: p, label: p }))} onChange={(v) => { setPortfolio(v); setDate(null); }} />
            {session && session.dates.length > 0 && (
              <label className="flex flex-col" style={{ gap: 4, minWidth: 0 }}>
                <span className="cp-mono-note">Session</span>
                <select data-testid="paper-session" value={session.prediction_date} onChange={(e) => setDate(e.target.value)} style={{ ...INPUT_STYLE, width: "auto", maxWidth: "100%" }}>
                  {session.dates.map((d) => (
                    <option key={d.prediction_date} value={d.prediction_date}>
                      {fmtDay(d.prediction_date)} → entry {fmtDay(d.entry_session)}{sample === "forward" && !d.counts ? " · not counted" : ""}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>

          {eq.isPending ? (
            <LoadingBlock label="Loading the evaluation" rows={2} />
          ) : eq.isError || eq.data.kind === "error" ? (
            <ErrorBlock title="The evaluation didn’t load" error={eq.isError ? eq.error : eq.data.kind === "error" ? eq.data.message : undefined} onRetry={() => eq.refetch()} />
          ) : ev ? (
            <>
              <Statement ev={ev} />
              <EvaluationTiles ev={ev} session={session} sessionNote={pq.isPending ? "Loading the session" : "No session loaded"} />
            </>
          ) : (
            <EmptyBlock title="No evaluation yet" body={`The engine stores an evaluation of the ${sample} ${portfolio} sample after each run. None is stored yet.`} />
          )}

          {pq.isPending ? (
            <Labeled title="Positions"><LoadingBlock label="Loading the session" rows={4} /></Labeled>
          ) : pq.isError || pq.data.kind === "error" ? (
            <Labeled title="Positions">
              <ErrorBlock title="The paper portfolio didn’t load" error={pq.isError ? pq.error : pq.data.kind === "error" ? pq.data.message : undefined} onRetry={() => pq.refetch()} />
            </Labeled>
          ) : session ? (
            <>
              <SessionTables s={session} live={live} liveProblem={liveProblem} />
              <Assumptions s={session} ev={ev} />
            </>
          ) : pq.data.kind === "not_found" ? (
            <Labeled title="Positions">
              <EmptyBlock title="That session is not recorded" body="Nothing older is shown in its place." action={<Btn onClick={() => setDate(null)}>Latest session</Btn>} />
            </Labeled>
          ) : (
            <Labeled title="Positions">
              <EmptyBlock title="Nothing recorded yet" body={`No ${sample} ${portfolio} snapshot has been frozen. The engine records each session after the close.`} />
            </Labeled>
          )}
        </>
      )}
    </Screen>
  );
}
