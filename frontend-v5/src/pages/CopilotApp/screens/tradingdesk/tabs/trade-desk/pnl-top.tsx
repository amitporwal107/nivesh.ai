/**
 * P&L dashboard v2 — the top of the page, in the design's order: header (mark, title, feed pill, account pills, IST clock,
 * Pause / Resume), the filter bar (mode, account, segment, search), the hero (net P&L after estimated charges) with its four
 * KPIs, the Paper and Live mode cards, and the intraday net P&L chart. Every figure is the route's (GET /api/desk/pnl,
 * /timeseries; docs/paper_pnl_dashboard/DESIGN.md "v2"); a null shows "—", never 0.
 */
import type { ReactNode } from "react";
import { LoadingBlock, fmtINR, fmtNum, fmtPct, type Tone } from "../../../../components/ui";
import { QueryProblem } from "../../../trading/parts";
import { quiet } from "./parts";
import {
  usePnlTimeseries, type AccountState, type PnlAccount, type PnlConnection, type PnlFilters, type PnlMode, type PnlModeSummary, type PnlSegment,
  type PnlSnapshot, type PnlSummary,
} from "./pnl-data";
import { Ago, hmIST, rs, timeIST } from "./pnl-parts";
import { MONO, NetCurve, Pill, SERIF, TONES, card, eyebrow, istClock, serifTitle, signColor, useNow } from "./pnl-ui";

export const SEGMENT_LABEL: Record<PnlSegment, string> = { ALL: "All segments", EQUITY: "Equity", FUTURES: "Futures", OPTIONS: "Options" };
export const MODE_LABEL: Record<PnlMode, string> = { ALL: "All", PAPER: "Paper", LIVE: "Live" };

const FEED_WORDS: Record<string, { text: string; tone: Tone }> = {
  live: { text: "Live feed", tone: "mint" },
  delayed: { text: "Feed delayed", tone: "amber" },
  closed: { text: "Market closed", tone: "ink" },
  expired: { text: "Feed expired · Kite login needed", tone: "danger" },
  not_connected: { text: "Feed not connected", tone: "danger" },
  disabled: { text: "Live feed off", tone: "ink" },
};

const ACCOUNT_WORDS: Record<AccountState, { text: string; tone: Tone }> = {
  OK: { text: "OK", tone: "mint" },
  STALE: { text: "STALE", tone: "amber" },
  SIGN_IN: { text: "SIGN IN", tone: "danger" },
  ERROR: { text: "ERROR", tone: "danger" },
  OFF: { text: "OFF", tone: "ink" },
};

export function connectionWords(c: PnlConnection, sessionOpen: boolean, userPaused: boolean): { text: string; tone: Tone } {
  switch (c) {
    case "live": return { text: "Streaming", tone: "mint" };
    case "polling": return { text: `Polling every ${sessionOpen ? "3" : "30"} s`, tone: "indigo" };
    case "reconnecting": return { text: "Reconnecting…", tone: "amber" };
    case "paused": return userPaused ? { text: "Paused", tone: "amber" } : { text: "Paused while the tab is hidden", tone: "ink" };
    case "error": return { text: "Updates failing", tone: "danger" };
    default: return { text: "Connecting…", tone: "ink" };
  }
}

// ── header ───────────────────────────────────────────────────────────────

export function PnlHeader({ d, connection, transport, receivedAt, paused, onPause }: {
  d: PnlSnapshot | null; connection: PnlConnection; transport: string | null; receivedAt: number | null; paused: boolean; onPause: () => void;
}) {
  const now = useNow(1_000);
  const sessionOpen = d?.market.session === "open";
  const fw = paused ? { text: "Feed paused", tone: "amber" as Tone }
    : d?.market.feed ? FEED_WORDS[d.market.feed] ?? { text: d.market.feed, tone: "ink" as Tone } : null;
  const cw = connectionWords(connection, sessionOpen, paused);
  return (
    <section data-testid="pnl-header" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: 16 }}>
        <div aria-hidden data-testid="pnl-mark" style={{ width: 30, height: 30, borderRadius: 8, display: "grid", placeItems: "center", flex: "none",
          background: "linear-gradient(140deg, var(--mint), var(--mint-2, var(--mint)))", color: "#06120B", fontFamily: SERIF, fontSize: 19 }}>न</div>
        <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
          <h2 data-testid="pnl-title" className="m-0" style={{ fontFamily: SERIF, fontSize: 22, lineHeight: 1, fontWeight: 400, color: "var(--cp-ink)" }}>Trading Desk</h2>
          <span data-testid="pnl-subtitle" style={{ ...eyebrow, fontSize: 11, letterSpacing: "0.08em" }}>Overview · Real-time P&amp;L</span>
        </div>
        <div style={{ flex: 1 }} />
        <div className="flex min-w-0 flex-wrap items-center" style={{ gap: 8 }}>
          {fw && <Pill tone={fw.tone} dot testId="pnl-feed" attrs={{ "data-feed": paused ? "paused" : d?.market.feed ?? "" }}>{fw.text}</Pill>}
          {(d?.accounts ?? []).map((a) => {
            const w = ACCOUNT_WORDS[a.state];
            return (
              <span key={a.accountId} data-testid="pnl-account-pill" data-id={a.accountId} data-state={a.state} title={a.stateNote ?? undefined}
                style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "5px 11px", borderRadius: 999, border: "1px solid var(--line-2)", color: "var(--cp-ink-2)",
                  fontFamily: MONO, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", whiteSpace: "nowrap" }}>
                <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: TONES[w.tone].c }} />
                {a.name}
                <span style={{ color: TONES[w.tone].c }}>{w.text}</span>
              </span>
            );
          })}
          <span data-testid="pnl-clock" className="cp-num" style={{ fontFamily: MONO, fontSize: 12, color: "var(--cp-ink-2)", padding: "0 4px" }}>{istClock(now)} IST</span>
          <button type="button" data-testid="pnl-pause" aria-pressed={paused} onClick={onPause}
            style={{ cursor: "pointer", padding: "6px 12px", borderRadius: 999, border: "1px solid var(--line-3)", background: "transparent", color: "var(--cp-ink)",
              fontFamily: MONO, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase" }}>
            {paused ? "Resume" : "Pause"}
          </button>
        </div>
      </div>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 12px" }}>
        <span data-testid="pnl-connection" data-state={connection} data-transport={transport ?? ""} style={{ ...quiet, fontSize: 11.5, color: TONES[cw.tone].c }}>{cw.text}</span>
        <Ago at={receivedAt} testId="pnl-updated" />
        {d?.asOf && <span data-testid="pnl-as-of" className="cp-num" style={{ ...quiet, fontSize: 11.5 }}>as of {timeIST(d.asOf) ?? d.asOf} IST</span>}
        {d?.notes.display_only && <span data-testid="pnl-display-only" style={{ ...quiet, fontSize: 11.5 }}>{d.notes.display_only}</span>}
      </div>
      {d && d.market.notes.length > 0 && (
        <ul data-testid="pnl-market-notes" className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 16, fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>
          {d.market.notes.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      )}
    </section>
  );
}

// ── filter bar ───────────────────────────────────────────────────────────

const selectStyle = { padding: "8px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontSize: 13, minWidth: 0 } as const;

export function FilterBar({ filters, setFilters, accounts, q, setQ }: {
  filters: Required<Pick<PnlFilters, "mode" | "account" | "segment">>; setFilters: (f: Partial<PnlFilters>) => void;
  accounts: PnlAccount[]; q: string; setQ: (q: string) => void;
}) {
  const shown = accounts.filter((a) => filters.mode === "ALL" || a.mode === filters.mode);
  return (
    <section data-testid="pnl-filters" aria-label="Filters" className="flex min-w-0 flex-wrap items-center"
      style={{ gap: 12, padding: "10px 12px", borderRadius: 16, border: "1px solid var(--line-2)", background: "var(--bg-glass)", backdropFilter: "blur(20px) saturate(140%)" }}>
      <div data-testid="pnl-mode" role="group" aria-label="Mode" className="flex" style={{ gap: 2, padding: 3, borderRadius: 999, background: "var(--bg-2)" }}>
        {(["ALL", "PAPER", "LIVE"] as const).map((m) => {
          const on = filters.mode === m;
          return (
            <button key={m} type="button" data-testid={`pnl-mode-${m.toLowerCase()}`} aria-pressed={on}
              onClick={() => setFilters({ mode: m, account: m === "ALL" || accounts.find((a) => a.accountId === filters.account)?.mode === m ? filters.account : "ALL" })}
              style={{ cursor: "pointer", border: 0, padding: "7px 16px", borderRadius: 999, background: on ? "var(--mint)" : "transparent", color: on ? "#06120B" : "var(--cp-ink-2)",
                fontFamily: MONO, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 500 }}>
              {MODE_LABEL[m]}
            </button>
          );
        })}
      </div>
      <select data-testid="pnl-account" aria-label="Account" value={filters.account} onChange={(e) => setFilters({ account: e.target.value })} style={selectStyle}>
        <option value="ALL">All accounts</option>
        {shown.map((a) => <option key={a.accountId} value={a.accountId}>{a.name} · {a.mode}</option>)}
        {filters.account !== "ALL" && !shown.some((a) => a.accountId === filters.account) && <option value={filters.account}>{filters.account}</option>}
      </select>
      <select data-testid="pnl-segment-select" aria-label="Segment" value={filters.segment} onChange={(e) => setFilters({ segment: e.target.value as PnlSegment })} style={selectStyle}>
        {(["ALL", "EQUITY", "FUTURES", "OPTIONS"] as const).map((s) => <option key={s} value={s}>{SEGMENT_LABEL[s]}</option>)}
      </select>
      <input data-testid="pnl-search" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search instrument or strategy" aria-label="Search positions"
        style={{ flex: "1 1 180px", minWidth: 0, padding: "8px 14px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontSize: 13, outline: "none" }} />
    </section>
  );
}

// ── hero + KPIs ──────────────────────────────────────────────────────────

function Kpi({ label, value, color, sub, testId }: { label: string; value: string; color?: string; sub: ReactNode; testId: string }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", padding: "16px 18px", gap: 6 }}>
      <span style={eyebrow}>{label}</span>
      <span data-testid={`${testId}-value`} className="cp-num" style={{ fontFamily: SERIF, fontSize: 30, lineHeight: 1.05, color: color ?? "var(--cp-ink)", overflowWrap: "anywhere" }}>{value}</span>
      <span data-testid={`${testId}-sub`} style={{ fontSize: 12.5, color: "var(--cp-ink-3)", lineHeight: 1.4 }}>{sub}</span>
    </div>
  );
}

const plain = (n: number | null) => (n == null || !Number.isFinite(n) ? "—" : `₹${Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);

export function Hero({ s, label, notes, live, narrow }: { s: PnlSummary; label: string; notes: ReactNode[]; live: boolean; narrow: boolean }) {
  // Booked (closed trades) and estimated (open ones) charges: the total only when both parts are known (never 0 for unknown).
  const charges = s.chargesBooked != null && s.chargesEstimated != null ? s.chargesBooked + s.chargesEstimated : null;
  const tone = (s.net ?? 0) < 0 ? "danger" : (s.net ?? 0) > 0 ? "mint" : "ink";
  const ret = s.returnPct != null && s.allocatedCapital
    ? `${fmtPct(s.returnPct, { signed: true, digits: 3 })} on ${fmtINR(s.allocatedCapital)}`
    : `Return not computed: ${s.capitalBasis ?? "no capital figure for this selection"}`;
  return (
    <section data-testid="pnl-hero-row" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: 20 }}>
      <div data-testid="pnl-hero" className="flex min-w-0 flex-col" style={{ ...card, padding: narrow ? "20px 18px" : "26px 28px", gap: 14 }}>
        <div data-testid="pnl-hero-label" style={{ ...eyebrow, fontSize: 11 }}>{label}</div>
        <div data-testid="pnl-hero-net" className="cp-num" style={{ fontFamily: SERIF, fontSize: narrow ? 48 : 76, lineHeight: 1, letterSpacing: "-0.01em", color: signColor(s.net), overflowWrap: "anywhere" }}>{rs(s.net)}</div>
        <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
          <Pill tone={tone} testId="pnl-hero-return" style={{ whiteSpace: "normal", overflowWrap: "anywhere", borderRadius: 12, maxWidth: "100%" }}>{ret}</Pill>
          <span data-testid="pnl-hero-gross" style={{ fontFamily: MONO, fontSize: 12, color: "var(--cp-ink-2)" }}>
            Gross {rs(s.gross)} − {s.chargesBooked ? "charges" : "est. charges"} {plain(charges)}
            {s.chargesBooked ? <> (est. {plain(s.chargesEstimated)} · booked {plain(s.chargesBooked)})</> : null}
          </span>
        </div>
        {notes.length > 0 && (
          <div data-testid="pnl-hero-notes" className="flex flex-col" style={{ gap: 6 }}>
            {notes.map((n, i) => (
              <div key={i} style={{ padding: "10px 12px", borderRadius: 10, background: "var(--amber-soft)", border: "1px solid var(--amber-line)", color: "var(--amber)", fontSize: 13, lineHeight: 1.45 }}>{n}</div>
            ))}
          </div>
        )}
      </div>
      <div data-testid="pnl-kpis" className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 12 }}>
        <Kpi testId="pnl-kpi-realized" label="Realized P&L" value={rs(s.realized)} color={signColor(s.realized)}
          sub={live ? "Brokers do not split their realised P&L; see each position's broker figure" : `Closed quantity · ${s.closedTrades ?? "—"} closed in the period`} />
        <Kpi testId="pnl-kpi-unrealized" label="Unrealized P&L" value={rs(s.unrealized)} color={signColor(s.unrealized)} sub="Marked to the latest price shown" />
        <Kpi testId="pnl-kpi-charges" label="Est. charges" value={plain(charges)} sub={<>Estimate, not settled{s.chargesBooked ? <> · booked <span data-testid="pnl-kpi-charges-booked">{plain(s.chargesBooked)}</span></> : null} · est. <span data-testid="pnl-kpi-charges-est">{plain(s.chargesEstimated)}</span></>} />
        <Kpi testId="pnl-kpi-positions" label="Open positions" value={s.openPositions == null ? "—" : fmtNum(s.openPositions)}
          sub={`${s.winningPositions ?? "—"} winning · ${s.losingPositions ?? "—"} losing${s.openLegs != null && s.openLegs !== s.openPositions ? ` · ${fmtNum(s.openLegs)} rows with legs` : ""}${s.pendingEntries ? ` · ${s.pendingEntries} waiting to open` : ""}`} />
      </div>
    </section>
  );
}

// ── mode cards ───────────────────────────────────────────────────────────

function ModeCard({ mode, m, selected, accounts }: { mode: "PAPER" | "LIVE"; m: PnlModeSummary | null; selected: boolean; accounts: PnlAccount[] }) {
  const tone: Tone = mode === "LIVE" ? "mint" : "indigo";
  const t = TONES[tone];
  const capital = m?.capital ?? null;
  const unavailable = m != null && m.available === false;
  const meta = m == null ? "No figures in this answer"
    : `${m.openPositions == null ? "—" : fmtNum(m.openPositions)} position${m.openPositions === 1 ? "" : "s"} · ${capital != null ? `${fmtINR(capital)} allocated` : "capital not read"}`;
  const ret = m?.returnPct != null ? fmtPct(m.returnPct, { signed: true, digits: 2 }) : "return —";
  const names = accounts.filter((a) => a.mode === mode).map((a) => a.name).join(" · ");
  return (
    <div data-testid="pnl-mode-card" data-mode={mode} data-selected={selected ? "true" : "false"} data-available={m?.available === false ? "false" : "true"} className="flex min-w-0 flex-col"
      style={{ ...card, boxShadow: "none", padding: "18px 20px", gap: 12, border: `1px solid ${selected ? t.line : "var(--cp-line)"}` }}>
      <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
        <Pill tone={tone}>{mode === "LIVE" ? "Live" : "Paper"}</Pill>
        <span data-testid="pnl-mode-meta" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>{meta}</span>
      </div>
      <div className="flex flex-wrap items-baseline" style={{ gap: 12 }}>
        <div data-testid="pnl-mode-net" className="cp-num" style={{ fontFamily: SERIF, fontSize: 38, lineHeight: 1, color: signColor(m?.net ?? null) }}>{rs(m?.net ?? null)}</div>
        <div className="cp-num" style={{ fontFamily: MONO, fontSize: 12, color: "var(--cp-ink-2)" }}>{ret}</div>
      </div>
      <div className="flex flex-wrap" style={{ gap: 18, fontFamily: MONO, fontSize: 11.5, color: "var(--cp-ink-3)" }}>
        <span>REAL {rs(m?.realized ?? null)}</span><span>UNREAL {rs(m?.unrealized ?? null)}</span>
        {names && <span style={{ textTransform: "uppercase" }}>{names}</span>}
      </div>
      {(unavailable || m?.note) && (
        <span data-testid="pnl-mode-note" style={{ fontSize: 12.5, lineHeight: 1.45, color: unavailable ? "var(--amber)" : "var(--cp-ink-3)" }}>{m?.note ?? "No account of this mode could be read."}</span>
      )}
    </div>
  );
}

export function ModeCards({ d, selected }: { d: PnlSnapshot; selected: PnlMode }) {
  return (
    <section data-testid="pnl-mode-cards" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: 20 }}>
      <ModeCard mode="PAPER" m={d.modes.PAPER} selected={selected === "PAPER"} accounts={d.accounts} />
      <ModeCard mode="LIVE" m={d.modes.LIVE} selected={selected === "LIVE"} accounts={d.accounts} />
    </section>
  );
}

// ── intraday chart ───────────────────────────────────────────────────────

export function IntradayPanel({ mode, sessionOpen, names }: { mode: PnlMode; sessionOpen: boolean; names: Map<string, string> }) {
  const q = usePnlTimeseries("5m", sessionOpen, mode);
  const data = q.data;
  const net = data ? data.points.filter((p) => p.net != null) : [];
  const useGross = !!data && !net.length;
  const pts = useGross ? data.points.filter((p) => p.gross != null) : net;
  const values = pts.map((p) => (useGross ? p.gross : p.net) as number);
  const hi = values.length ? Math.max(...values) : null;
  const lo = values.length ? Math.min(...values) : null;
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Reading today's candles" rows={2} />;
  else if (q.isError) body = <div data-testid="pnl-chart-error"><QueryProblem what="The intraday P&L curve" error={q.error} onRetry={() => q.refetch()} /></div>;
  else if (!values.length) {
    body = <span data-testid="pnl-chart-empty" style={quiet}>No intraday points{data?.date ? ` for ${data.date}` : ""}: {data?.missing.length ? data.missing.map((m) => m.reason).join("; ") : "no open position has candles yet"}.</span>;
  } else {
    body = (
      <>
        <NetCurve values={values} height={240} testId="pnl-chart-plot" label={`${useGross ? "Gross" : "Net"} P&L through the session`} />
        <div className="flex justify-between" style={{ fontFamily: MONO, fontSize: 10.5, color: "var(--cp-ink-4)" }}>
          <span>{hmIST(pts[0].t) ?? ""}</span><span data-testid="pnl-chart-last">{hmIST(pts[pts.length - 1].t) ?? ""} · {rs(values[values.length - 1])}</span>
        </div>
      </>
    );
  }
  const modeText = mode === "ALL" ? "Paper + Live" : mode === "PAPER" ? "Paper only" : "Live only";
  return (
    <section data-testid="pnl-chart" className="flex min-w-0 flex-col" style={{ ...card, padding: "20px 22px 16px", gap: 14 }}>
      <div className="flex flex-wrap items-baseline" style={{ gap: 14 }}>
        <div style={serifTitle}>Intraday {useGross ? "gross" : "net"} P&amp;L</div>
        <div style={eyebrow}>Cumulative from session open · {modeText}{data?.date ? ` · ${data.date}` : ""}</div>
        <div style={{ flex: 1 }} />
        {hi != null && lo != null && (
          <div style={{ fontFamily: MONO, fontSize: 11.5, color: "var(--cp-ink-2)" }}>
            HIGH <span data-testid="pnl-chart-hi">{rs(hi)}</span> · LOW <span data-testid="pnl-chart-lo">{rs(lo)}</span>
          </div>
        )}
      </div>
      {body}
      {data?.partial && values.length > 0 && (
        <span data-testid="pnl-chart-partial" style={{ ...quiet, color: "var(--amber)" }}>
          Partial curve: {data.missing.length} position{data.missing.length === 1 ? "" : "s"} left out ({data.missing.map((m) => `${(m.positionId && names.get(m.positionId)) ?? m.positionId ?? "?"}: ${m.reason}`).join("; ") || "reason not given"}).
        </span>
      )}
      {data && data.notes.length > 0 && <span data-testid="pnl-chart-notes" style={{ ...quiet, fontSize: 11 }}>{data.notes.join(" ")}</span>}
      {data?.basis && <span data-testid="pnl-chart-basis" style={{ ...quiet, fontSize: 11 }}>{data.basis}</span>}
    </section>
  );
}
