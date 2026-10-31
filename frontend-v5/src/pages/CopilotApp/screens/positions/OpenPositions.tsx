/**
 * Open Positions — the workspace for what the user holds open today, separate from My Portfolio (the ledger of
 * holdings). Real broker positions and paper positions, each labelled, grouped by underlying.
 *
 * Design: the owner's Trader screen (frontend-v5/design/nivesh-copilot/NVTrader.dc.html): the headline sentence
 * ("Two positions are near their stops."), the tiles, the "Open positions · broker, read-only" table with
 * Position · Qty · Avg · LTP · P&L · Stop · Target · Risk left, and the line "Nivesh reads positions; it cannot place
 * orders". A row opens its group: legs, Greeks, payoff, scenarios, warnings, the user's own stop and target, margin.
 *
 * Data: GET /api/positions (positions-data.ts). Nothing here can place an order. A figure the server could not work
 * out shows "—", and the reason is shown with it.
 */
import { useState, type ReactNode } from "react";
import {
  AskChips, Btn, DataTable, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Pill, Screen, ScreenHeader, Section, Tiles,
  TONE_COLOR, fmtINR, fmtNum, fmtPct, relTime, signTone,
  type Column, type TileItem, type Tone,
} from "../../components/ui";
import { BrokerName, StockName } from "../../components/EntityIcon";
import { useCopilotShell } from "../../lib/shell-context";
import { INPUT_STYLE, SEBI_FNO_NOTE, fmtDay, fmtPrice } from "../trading/parts";
import { PayoffChart } from "./PayoffChart";
import {
  useDeleteLevels, useGroupMargin, usePositions, useSaveLevels, useScenario,
  type PositionGroup, type PositionLeg, type PositionSource, type PositionsBook,
} from "./positions-data";

const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;
const money = (n: number | null | undefined) => fmtINR(n ?? null, { signed: true });
const toned = (text: ReactNode, tone: Tone) => <span style={{ color: TONE_COLOR[tone] }}>{text}</span>;
const warnTone = (t: string): Tone => (t === "danger" || t === "amber" || t === "mint" ? (t as Tone) : "ink");

const PRICE_SOURCE: Record<string, string> = {
  kite_live: "Kite live",
  kite_close: "Kite close",
  nse_bhavcopy: "NSE end of day",
  broker: "broker, live read",
};

function priceLine(g: PositionGroup): string {
  const p = g.price;
  if (p.spot == null) return "No current price";
  const src = p.source ? PRICE_SOURCE[p.source] ?? p.source : "";
  const when = p.as_of ? (p.as_of.length === 10 ? fmtDay(p.as_of) : relTime(p.as_of)) : "";
  const pricing = g.kind === "fno" && p.pricing_as_of ? ` · options and futures priced at the ${fmtDay(p.pricing_as_of)} close` : "";
  return `${fmtPrice(p.spot)} · ${[src, when].filter(Boolean).join(", ")}${pricing}`;
}

// ── headline ─────────────────────────────────────────────────────────────

function headline(book: PositionsBook): { title: ReactNode; sub: string } {
  const s = book.summary;
  if (s.positions === 0) {
    return { title: "No open positions", sub: "Nothing is open at your connected brokers or on the paper desk right now." };
  }
  const risk = s.open_risk_at_stops_rs != null ? `Open risk at your stops is ${fmtINR(s.open_risk_at_stops_rs)}.` : "";
  const noStop = s.without_stop ? ` ${plural(s.without_stop, "group has", "groups have")} no stop set.` : "";
  if (s.stop_breached) {
    return { title: <>{plural(s.stop_breached, "position is", "positions are")} <em style={{ color: "var(--cp-danger)" }}>past their stops</em>.</>, sub: `${risk}${noStop}`.trim() };
  }
  if (s.near_stop) {
    return { title: <>{plural(s.near_stop, "position is", "positions are")} <em style={{ color: "var(--amber)" }}>near their stops</em>.</>, sub: `${risk}${noStop}`.trim() };
  }
  return { title: <>{plural(s.groups, "open position")}, <em>none near a stop</em>.</>, sub: `${risk}${noStop}`.trim() };
}

// ── sources ──────────────────────────────────────────────────────────────

function SourceLine({ s }: { s: PositionSource }) {
  const { go } = useCopilotShell();
  if (s.source === "paper") {
    return (
      <div data-testid="positions-source-paper" className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 13, color: "var(--cp-ink-2)" }}>
        <Pill tone="amber">Paper</Pill>
        {s.ok ? <span>Paper desk · marked at the {s.as_of ? fmtDay(s.as_of) : "last"} close</span> : <span>{s.error?.message}</span>}
      </div>
    );
  }
  const ended = s.error?.code === "BROKER_SESSION_EXPIRED";
  return (
    <div data-testid="positions-source-broker" data-ok={s.ok} className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 13, color: "var(--cp-ink-2)" }}>
      <Pill tone="indigo">Broker</Pill>
      {s.broker_display ? <BrokerName name={s.broker_display} size={20} /> : null}
      {s.ok ? <span>Read {relTime(s.read_at)} · {plural(s.rows ?? 0, "open position")}</span> : <span>{s.error?.message}</span>}
      {ended && <Btn data-testid="positions-reconnect" onClick={() => go("page/brokers")}>Reconnect</Btn>}
    </div>
  );
}

// ── the groups table ─────────────────────────────────────────────────────

function qtyCell(g: PositionGroup): string {
  if (g.legs.length !== 1) return plural(g.legs.length, "leg");
  const l = g.legs[0];
  return l.lots != null ? `${fmtNum(l.lots, Number.isInteger(l.lots) ? 0 : 2)} ${Math.abs(l.lots) === 1 ? "lot" : "lots"}` : fmtNum(l.quantity, 0);
}

function GroupsTable({ groups, open, onOpen, testId }: { groups: PositionGroup[]; open: string | null; onOpen: (k: string) => void; testId: string }) {
  const cols: Column<PositionGroup>[] = [
    {
      key: "pos", header: "Position", width: "minmax(0,1.8fr)",
      render: (g) => (
        <span data-testid="positions-row" data-key={g.key} data-open={open === g.key} className="flex items-center" style={{ gap: 8 }}>
          <StockName symbol={g.underlying} sub={g.label ?? (g.legs.length === 1 ? g.legs[0].label : `${g.kind === "fno" ? "F&O" : "Shares"} · ${plural(g.legs.length, "leg")}`)} size={24} />
          {g.warnings.some((w) => w.code === "stop_breached" || w.code === "near_stop") && (
            <span data-testid="positions-row-flag" style={{ color: "var(--amber)" }} aria-label="near or past its stop">●</span>
          )}
        </span>
      ),
    },
    { key: "qty", header: "Qty", align: "right", num: true, render: qtyCell },
    { key: "avg", header: "Avg", align: "right", num: true, render: (g) => (g.legs.length === 1 ? fmtPrice(g.legs[0].avg_price) : "—") },
    { key: "ltp", header: "LTP", align: "right", num: true, render: (g) => fmtPrice(g.price.spot) },
    { key: "pnl", header: "P&L", align: "right", num: true, render: (g) => toned(money(g.pnl_rs), signTone(g.pnl_rs)) },
    { key: "stop", header: "Stop", align: "right", num: true, render: (g) => fmtPrice(g.levels?.effective_stop ?? null) },
    { key: "target", header: "Target", align: "right", num: true, render: (g) => fmtPrice(g.levels?.target ?? null) },
    { key: "risk", header: "Risk left", align: "right", num: true, render: (g) => fmtINR(g.analytics?.payoff?.risk_to_stop_rs ?? null) },
  ];
  return (
    <div data-testid={testId}>
      <DataTable columns={cols} rows={groups} rowKey={(g) => g.key} onRowClick={(g) => onOpen(g.key)} minWidth={820} />
    </div>
  );
}

// ── one group ────────────────────────────────────────────────────────────

function LegsTable({ g }: { g: PositionGroup }) {
  const fno = g.kind === "fno";
  const cols: Column<PositionLeg>[] = [
    { key: "c", header: "Contract", width: "minmax(0,1.8fr)", render: (l) => <span data-testid="positions-leg">{l.label ?? "—"}</span> },
    { key: "q", header: fno ? "Lots" : "Qty", align: "right", num: true, render: (l) => (fno && l.lots != null ? fmtNum(l.lots, Number.isInteger(l.lots) ? 0 : 2) : fmtNum(l.quantity, 0)) },
    { key: "a", header: "Avg", align: "right", num: true, render: (l) => fmtPrice(l.avg_price) },
    { key: "m", header: fno ? "Settle" : "Mark", align: "right", num: true, render: (l) => fmtPrice(l.mark) },
    ...(fno ? [
      { key: "iv", header: "IV", align: "right", num: true, render: (l: PositionLeg) => (l.iv_pct != null ? `${fmtNum(l.iv_pct, 2)}%` : "—") },
      { key: "d", header: "Delta", align: "right", num: true, render: (l: PositionLeg) => (l.greeks ? fmtNum(l.greeks.delta, 2) : "—") },
    ] as Column<PositionLeg>[] : []),
    { key: "p", header: g.source === "broker" ? "P&L (broker)" : "P&L", align: "right", num: true, render: (l) => toned(money(l.pnl_rs ?? null), signTone(l.pnl_rs ?? null)) },
  ];
  return <DataTable columns={cols} rows={g.legs} rowKey={(l, i) => `${l.key ?? l.label}-${i}`} minWidth={fno ? 720 : 520} />;
}

function RiskLine({ g }: { g: PositionGroup }) {
  const p = g.analytics?.payoff;
  if (!p) return null;
  const stop = g.levels?.effective_stop;
  let risk: ReactNode;
  if (p.risk_basis === "stop") {
    risk = p.loss_at_stop_rs != null
      ? <>Loss at your stop: <strong data-testid="positions-loss-at-stop">{fmtINR(p.loss_at_stop_rs)}</strong> (stop {fmtPrice(stop)})</>
      : <span data-testid="positions-loss-at-stop-none">Set a stop to see the loss at the stop. A to-zero figure is not shown for shares or a long future.</span>;
  } else {
    risk = <>Max loss at expiry: <strong data-testid="positions-max-loss">{fmtINR(p.max_loss != null ? -p.max_loss : null)}</strong>{p.loss_at_stop_rs != null ? <> · at your stop {fmtINR(p.loss_at_stop_rs)}</> : null}</>;
  }
  const be = p.breakevens.filter((b): b is number => b != null);
  return (
    <div className="flex flex-col" style={{ gap: 4, fontSize: 13, color: "var(--cp-ink-2)" }} data-testid="positions-risk">
      <span>{risk}</span>
      <span className="cp-mono-note">
        Max profit {p.profit_unbounded ? "not capped" : fmtINR(p.max_profit)} · breakeven {be.length ? be.map((b) => fmtNum(b, 2)).join(", ") : "—"}
        {g.analytics?.distance_to_stop_pct != null ? ` · ${fmtPct(g.analytics.distance_to_stop_pct)} from the stop` : ""}
      </span>
    </div>
  );
}

function GreeksTiles({ g }: { g: PositionGroup }) {
  const gr = g.analytics?.greeks;
  if (g.kind !== "fno") return null;
  if (!gr) return <p className="m-0" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>Greeks are not shown: an option leg has no implied volatility on the pricing day.</p>;
  return (
    <div data-testid="positions-greeks">
      <Tiles min={120} items={[
        { k: "Delta", v: fmtNum(gr.delta, 2), s: g.analytics?.delta_exposure_rs != null ? `${fmtINR(g.analytics.delta_exposure_rs, { compact: true, signed: true })} exposure` : "shares of the underlying" },
        { k: "Gamma", v: fmtNum(gr.gamma, 4), s: "delta change per ₹1" },
        { k: "Theta", v: toned(money(gr.theta), signTone(gr.theta)), s: "a day" },
        { k: "Vega", v: money(gr.vega), s: "per volatility point" },
      ]} />
    </div>
  );
}

function ScenarioTable({ g }: { g: PositionGroup }) {
  const [iv, setIv] = useState(0);
  const [days, setDays] = useState(0);
  const custom = iv !== 0 || days !== 0;
  const q = useScenario(custom ? { key: g.key, ivShift: iv, daysForward: days } : null);
  const rows = custom ? q.data?.rows ?? [] : g.analytics?.scenario ?? [];
  const cols: Column<(typeof rows)[number]>[] = [
    { key: "m", header: "Move", align: "right", num: true, render: (r) => fmtPct(r.move_pct, { signed: true, digits: 0 }) },
    { key: "p", header: "Price", align: "right", num: true, render: (r) => fmtPrice(r.price) },
    { key: "t", header: custom ? "P&L then" : "P&L today", align: "right", num: true, render: (r) => toned(money(r.today_pnl_rs), signTone(r.today_pnl_rs)) },
    { key: "e", header: "P&L at expiry", align: "right", num: true, render: (r) => toned(money(r.expiry_pnl_rs), signTone(r.expiry_pnl_rs)) },
  ];
  return (
    <div className="flex flex-col" style={{ gap: 8 }} data-testid="positions-scenario">
      {g.kind === "fno" && (
        <div className="flex flex-wrap items-center" style={{ gap: 12, fontSize: 13, color: "var(--cp-ink-2)" }}>
          <label className="flex items-center" style={{ gap: 6 }}>Volatility
            <select data-testid="positions-iv-shift" value={iv} onChange={(e) => setIv(Number(e.target.value))} style={{ ...INPUT_STYLE, width: 96 }}>
              {[-5, -3, 0, 3, 5].map((v) => <option key={v} value={v}>{v > 0 ? `+${v}` : v} pts</option>)}
            </select>
          </label>
          <label className="flex items-center" style={{ gap: 6 }}>Days ahead
            <select data-testid="positions-days" value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ ...INPUT_STYLE, width: 80 }}>
              {[0, 1, 2, 3, 5].map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </label>
        </div>
      )}
      {custom && q.isPending ? <LoadingBlock label="Working out the scenario" rows={2} /> :
        custom && q.isError ? <ErrorBlock title="The scenario didn’t load" error={q.error} onRetry={() => q.refetch()} /> : (
          <>
            {custom && q.data?.why && <p className="m-0 cp-mono-note">{q.data.why}</p>}
            <DataTable columns={cols} rows={rows} rowKey={(r) => String(r.move_pct)} minWidth={420} empty="No scenario: this group has no current price." />
          </>
        )}
    </div>
  );
}

function LevelsForm({ g }: { g: PositionGroup }) {
  const save = useSaveLevels();
  const del = useDeleteLevels();
  const lv = g.levels;
  const [stop, setStop] = useState(lv?.stop != null ? String(lv.stop) : "");
  const [target, setTarget] = useState(lv?.target != null ? String(lv.target) : "");
  const [trail, setTrail] = useState(lv?.trail_pct != null ? String(lv.trail_pct) : "");
  if (g.source === "paper") {
    return <p className="m-0" style={{ fontSize: 13, color: "var(--cp-ink-3)" }} data-testid="positions-levels-paper">The stop and target are the paper trade’s own. Change them on the desk’s Paper trades.</p>;
  }
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const body = { underlying: g.underlying, stop: num(stop), target: num(target), trail_pct: num(trail) };
  const bad = [body.stop, body.target, body.trail_pct].some((v) => v != null && !(Number.isFinite(v) && v > 0));
  const err = (save.error ?? del.error) as { message?: string } | null;
  return (
    <form
      data-testid="positions-levels"
      className="flex flex-wrap items-end"
      style={{ gap: 10 }}
      onSubmit={(e) => { e.preventDefault(); if (!bad) save.mutate(body); }}
    >
      <label className="flex flex-col" style={{ gap: 4, fontSize: 12, color: "var(--cp-ink-3)" }}>Stop (underlying)
        <input data-testid="positions-stop-input" inputMode="decimal" value={stop} onChange={(e) => setStop(e.target.value)} style={{ ...INPUT_STYLE, width: 120 }} />
      </label>
      <label className="flex flex-col" style={{ gap: 4, fontSize: 12, color: "var(--cp-ink-3)" }}>Target
        <input data-testid="positions-target-input" inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} style={{ ...INPUT_STYLE, width: 120 }} />
      </label>
      <label className="flex flex-col" style={{ gap: 4, fontSize: 12, color: "var(--cp-ink-3)" }}>Trail %
        <input data-testid="positions-trail-input" inputMode="decimal" value={trail} onChange={(e) => setTrail(e.target.value)} style={{ ...INPUT_STYLE, width: 80 }} />
      </label>
      <Btn type="submit" variant="primary" disabled={bad || save.isPending} data-testid="positions-levels-save">Save levels</Btn>
      {lv && <Btn data-testid="positions-levels-remove" disabled={del.isPending} onClick={() => del.mutate(g.underlying)}>Remove</Btn>}
      <span className="cp-mono-note" style={{ flexBasis: "100%" }}>
        Your own levels, kept by Nivesh: brokers send none, and nothing is sent to the broker.
        {lv?.trail_pct ? ` Trailing ${fmtNum(lv.trail_pct, 1)}%: the stop in force is ${fmtPrice(lv.effective_stop)}.` : ""}
      </span>
      {bad && <span role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>Each level must be a number above zero.</span>}
      {err && <span role="alert" data-testid="positions-levels-error" style={{ fontSize: 12, color: "var(--cp-danger)" }}>{err.message ?? "The levels were not saved."}</span>}
    </form>
  );
}

function MarginLine({ g }: { g: PositionGroup }) {
  const m = useGroupMargin();
  if (!g.margin_request) return null;
  const status = (m.error as { status?: number } | null)?.status;
  return (
    <div className="flex flex-wrap items-center" style={{ gap: 10, fontSize: 13, color: "var(--cp-ink-2)" }} data-testid="positions-margin">
      <Btn data-testid="positions-margin-btn" disabled={m.isPending} onClick={() => m.mutate(g.margin_request!)}>Margin · Zerodha</Btn>
      {m.data && <span data-testid="positions-margin-value">Required {fmtINR(m.data.required_margin)} · initial {fmtINR(m.data.initial_margin)} (Zerodha’s calculator; nothing is placed)</span>}
      {m.isError && <span role="alert" data-testid="positions-margin-error">{status === 503 ? "Needs today’s Kite login on the platform, so no figure is shown." : "The margin could not be worked out."}</span>}
    </div>
  );
}

function GroupDetail({ g }: { g: PositionGroup }) {
  const { ask } = useCopilotShell();
  const label = g.legs.length === 1 ? g.legs[0].label ?? g.underlying : `${g.underlying} position`;
  return (
    <Section
      title={<span className="flex flex-wrap items-center" style={{ gap: 8 }}><StockName symbol={g.underlying} size={22} />
        <Pill tone={g.source === "broker" ? "indigo" : "amber"}>{g.source === "broker" ? "Broker" : "Paper"}</Pill>
        {g.kind === "fno" && <Pill>F&O</Pill>}</span>}
      note={priceLine(g)}
    >
      <div className="flex flex-col" style={{ gap: 16 }} data-testid="positions-detail" data-key={g.key}>
        {g.accounts.length > 0 && (
          <span className="flex flex-wrap items-center" style={{ gap: 10 }}>{g.accounts.map((a) => <BrokerName key={a.account_id} name={a.broker_display ?? "Broker"} size={20} />)}</span>
        )}
        {g.warnings.length > 0 && (
          <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18 }} data-testid="positions-warnings">
            {g.warnings.map((w, i) => <li key={`${w.code}-${i}`} data-code={w.code} style={{ fontSize: 13, color: TONE_COLOR[warnTone(w.tone)] }}>{w.text}</li>)}
          </ul>
        )}
        <LegsTable g={g} />
        <RiskLine g={g} />
        <GreeksTiles g={g} />
        {g.analytics?.curve && g.analytics.curve.length > 1 && (
          <PayoffChart curve={g.analytics.curve} spot={g.price.spot} stop={g.levels?.effective_stop} target={g.levels?.target}
            breakevens={g.analytics.payoff?.breakevens ?? []} />
        )}
        {g.analytics?.payoff && <ScenarioTable g={g} />}
        <LevelsForm key={`${g.key}-${g.levels?.updated_at ?? "none"}`} g={g} />
        <MarginLine g={g} />
        <AskChips items={[
          `Should I trail the stop on my ${label}?`,
          ...(g.kind === "fno" ? [`Show the effect of IV rising 3 points on my ${label}`] : []),
        ]} />
      </div>
    </Section>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

function Body({ book }: { book: PositionsBook }) {
  const [open, setOpen] = useState<string | null>(null);
  const s = book.summary;
  const broker = book.groups.filter((g) => g.source === "broker" && g.kind !== "unmapped");
  const paper = book.groups.filter((g) => g.source === "paper");
  const unmapped = book.groups.find((g) => g.kind === "unmapped");
  const openGroup = book.groups.find((g) => g.key === open) ?? null;
  const toggle = (k: string) => setOpen((cur) => (cur === k ? null : k));
  const brokerSources = book.sources.filter((x) => x.source === "broker");
  const tiles: TileItem[] = [
    { k: "Unrealised P&L", v: <span data-testid="positions-unrealised">{toned(money(s.unrealised_pnl_rs), signTone(s.unrealised_pnl_rs))}</span>,
      s: s.unrealised_partial ? "Not every position has a P&L" : "Broker’s figures, paper marks" },
    { k: "Open risk at stops", v: <span data-testid="positions-open-risk">{fmtINR(s.open_risk_at_stops_rs)}</span>,
      s: s.without_stop ? `${plural(s.without_stop, "group")} without a stop` : "Loss if every stop is hit" },
    { k: "Exposure", v: fmtINR(s.exposure_rs, { compact: true }), s: "Shares and futures, at their prices" },
    { k: "Near a stop", v: <span data-testid="positions-near">{fmtNum(s.near_stop + s.stop_breached)}</span>,
      s: `within ${fmtNum(book.method.near_stop_pct, 0)}% or past it`, tone: s.near_stop + s.stop_breached ? "amber" : "ink" },
    { k: "Day realised", v: <span data-testid="positions-day-realised">—</span>, s: <span title={s.day_realised_note}>Brokers don’t separate it</span> },
  ];
  return (
    <>
      <div className="flex flex-col" style={{ gap: 8 }} data-testid="positions-sources">
        {book.sources.map((src, i) => <SourceLine key={`${src.source}-${src.account_id ?? i}`} s={src} />)}
        {brokerSources.length === 0 && (
          <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }} data-testid="positions-no-broker">No broker is connected: only paper positions are shown.</span>
        )}
      </div>
      <Tiles items={tiles} min={150} />
      <Section title="Open positions · broker, read-only" note={`${plural(s.broker_positions, "position")}`} flush>
        {broker.length ? <GroupsTable groups={broker} open={open} onOpen={toggle} testId="positions-broker-table" /> :
          <div style={{ padding: 16, fontSize: 13, color: "var(--cp-ink-3)" }} data-testid="positions-broker-empty">
            {brokerSources.some((x) => !x.ok) ? "No broker positions could be read: see the accounts above." : "No open positions at your brokers."}
          </div>}
      </Section>
      {openGroup && openGroup.source === "broker" && <GroupDetail key={openGroup.key} g={openGroup} />}
      <Section title="Paper positions · desk" note={s.paper_waiting_entry ? `${plural(s.paper_waiting_entry, "trade")} still waiting for its entry` : undefined} flush>
        {paper.length ? <GroupsTable groups={paper} open={open} onOpen={toggle} testId="positions-paper-table" /> :
          <div style={{ padding: 16, fontSize: 13, color: "var(--cp-ink-3)" }} data-testid="positions-paper-empty">No open paper positions.</div>}
      </Section>
      {openGroup && openGroup.source === "paper" && <GroupDetail key={openGroup.key} g={openGroup} />}
      {unmapped && (
        <Section title="Not mapped to an NSE contract" note={plural(unmapped.unmapped.length, "row")}>
          <ul className="m-0 flex flex-col" style={{ gap: 6, paddingLeft: 18, fontSize: 13, color: "var(--cp-ink-2)" }} data-testid="positions-unmapped">
            {unmapped.unmapped.map((u, i) => <li key={`${u.broker_code}-${i}`}>{u.broker_code} at {u.broker_display}: {u.problem}</li>)}
          </ul>
        </Section>
      )}
    </>
  );
}

export default function OpenPositionsScreen() {
  const q = usePositions();
  const head = q.data ? headline(q.data) : null;
  return (
    <Screen testId="screen-page-positions" width={1040}>
      <ScreenHeader
        eyebrow="Open positions · read-only"
        pills={<><Pill tone="indigo">Broker</Pill><Pill tone="amber">Paper</Pill><Pill>Live orders off</Pill></>}
        title={head ? <span data-testid="positions-headline">{head.title}</span> : "Open positions"}
        sub={head?.sub || "What you hold open today at your brokers and on the paper desk, grouped by underlying."}
      />
      {q.isPending ? <LoadingBlock label="Reading your positions" rows={4} /> :
        q.isError ? <ErrorBlock title="Your positions didn’t load" error={q.error} onRetry={() => q.refetch()} /> :
          q.data.summary.positions === 0 && q.data.sources.every((x) => x.ok) ? (
            <>
              <EmptyBlock title="No open positions" body="Positions you open at a connected broker, or on the paper desk, show up here." />
              <div className="flex flex-col" style={{ gap: 8 }}>{q.data.sources.map((src, i) => <SourceLine key={i} s={src} />)}</div>
            </>
          ) : <Body book={q.data} />}
      <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
        <Btn data-testid="positions-refresh" disabled={q.isFetching} onClick={() => q.refetch()}>{q.isFetching ? "Reading…" : "Refresh"}</Btn>
      </div>
      <Footnote>
        <span data-testid="positions-read-only">{q.data?.note ?? "Nivesh reads positions; it cannot place orders."}</span>{" "}
        Payoff, scenarios and the loss at a stop are gross, before brokerage, taxes and slippage. {SEBI_FNO_NOTE}
      </Footnote>
    </Screen>
  );
}
