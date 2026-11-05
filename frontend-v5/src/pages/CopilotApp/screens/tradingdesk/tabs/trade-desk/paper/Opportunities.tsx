/**
 * Paper Trading v2 › 02 Scanner opportunities (?tab=trade&view=paper&sub=opportunities) — the owner's design of 5 Nov 2026
 * (docs/scanner_paper_trading/UI_DESIGN_V2.md §2 "02 Scanner opportunities", §5). Test cases PV2-A-30 … A-40.
 *
 *   left   the table: Symbol (+ "LONG · EQ") · Signals ("N sources") · Opp score · Entry · R:R · Risk ₹ · Decision pill,
 *          awaiting your approval first, then by opportunity score; the selected row on bg-3
 *   right  the detail (sticky): "{id} · {status}", the symbol, the decision pill, the reason, "Supporting signals · N",
 *          "Strategy plan" (Entry · Stop · T1 · T2), sizing (Quantity / Capital / Planned risk), "Risk engine checks" (every
 *          check of the proposal's risk record), then Approve paper trade · Add to watchlist · Reject and the footnote
 *
 * Reads: GET /api/v1/opportunities joined by opportunity_id to the caller's GET /api/v1/proposals (api-a.ts). Writes:
 * POST …/approve, POST …/reject {reason} (spt-api.ts), POST /api/watchlists/{id}/symbols (the desk's watchlists API, the
 * first list). Allowed words on this paper screen (owner, 5 Nov): Entry, Stop, T1, T2, "Approve paper trade", "Reject",
 * "Add to watchlist"; never recommend / pick / suggest. Cash longs only: F&O ideas are TRACKED with no approve. Nothing here
 * reaches a broker.
 */
import { useMemo, useRef, useState, type ReactNode } from "react";
import { LoadingBlock } from "../../../../../components/ui";
import { QueryProblem } from "../../../../trading/parts";
import { useAddStock, usePersonalLists } from "../../../../workspace/personal-lists";
import { capitalOf, plannedRiskOf, sptProblem, useApprove, useReject, type SptMode, type SptOpportunity, type SptProposal } from "../spt-api";
import { ProblemLine, btn, btnDanger, btnPrimary, input, istTime, price, rupees, useNarrow } from "../spt-parts";
import { AWAITING, usePaperOpportunities, usePaperProposals, type PaperOpp, type PaperProposal, type RiskCheck } from "./api-a";
import { Card, Eyebrow, Glyph, Note, Pill, SectionHeader, Split, Tile, NUM, mono10, type GlyphKind, type PillTone } from "./ui";

// ── the decision ─────────────────────────────────────────────────────────

export type Action = "ORDER CREATED" | "USER REJECTED" | "WATCHLISTED";
export interface Decision { label: string; tone: PillTone; kind: "approve" | "reduced" | "conditional" | "blocked" | "watchlist" | "tracked" | "done" | "other" }

const D = (label: string, tone: PillTone, kind: Decision["kind"]): Decision => ({ label, tone, kind });
const BLOCKING = new Set(["BLOCKED", "REJECT", "HALT_ACCOUNT", "EXIT_REQUIRED"]);
const HIDDEN_OPP_STATES = new Set(["EXPIRED", "REJECTED"]);

export interface Row { id: string; opp: PaperOpp | null; prop: PaperProposal | null }

const isFno = (r: Row) => {
  const i = (r.prop?.instrument ?? r.opp?.instrument ?? "cash").toLowerCase();
  return !["cash", "equity", "eq", ""].includes(i);
};

/** The design's decision pill for a row (§2 02): the user's action wins, then the proposal's risk decision, then the opportunity. */
export function decisionOf(r: Row, action: Action | null): Decision {
  if (action) return D(action, "mint", "done");
  const p = r.prop?.p ?? null;
  if (p) {
    if (p.state === "ORDER_CREATED" || p.state === "READY_FOR_ORDER") return D("ORDER CREATED", "mint", "done");
    if (p.state === "USER_REJECTED") return D("USER REJECTED", "mint", "done");
    if (p.state === "NOT_TRADABLE" || p.state === "TRACKING_ONLY") return D("TRACKED", "plain", "tracked");
    const rd = p.risk?.decision ?? null;
    if (rd === "APPROVE") return D("APPROVE", "mint", "approve");
    if (rd === "APPROVE_REDUCED") return D("APPROVE REDUCED", "amber", "reduced");
    if (rd === "CONDITIONAL_APPROVAL") return D("CONDITIONAL", "indigo", "conditional");
    if ((rd && BLOCKING.has(rd)) || p.state === "BLOCKED_BY_RISK" || p.state === "REJECTED") return D("BLOCKED", "danger", "blocked");
    if (p.state === "APPROVAL_EXPIRED") return D("EXPIRED", "plain", "other");
    return D("AWAITING RISK", "plain", "other");
  }
  if (isFno(r)) return D("TRACKED", "plain", "tracked");
  const st = r.opp?.o.state ?? null;
  if (st === "WATCHLIST") return D("WATCHLIST", "plain", "watchlist");
  if (st === "CONDITIONAL") return D("CONDITIONAL", "indigo", "conditional");
  if (st === "QUALIFIED") return D("NO PROPOSAL", "plain", "other");
  if (st === "DATA_INSUFFICIENT") return D("DATA INSUFFICIENT", "plain", "other");
  return D("VALIDATING", "plain", "other");
}

const symbolOf = (r: Row) => r.opp?.o.symbol ?? r.prop?.p.symbol ?? "—";
const scoreOf = (r: Row) => r.opp?.o.validation?.score ?? null;
const awaiting = (r: Row) => r.prop?.p.state === AWAITING;

/** Opportunities (expired and validation-rejected ones left out) joined to the user's proposals, awaiting first, then by score. */
export function joinRows(opps: PaperOpp[], props: PaperProposal[]): { rows: Row[]; hidden: number } {
  const byOpp = new Map<string, PaperProposal>();
  for (const p of props) if (!byOpp.has(p.p.opportunityId)) byOpp.set(p.p.opportunityId, p);
  let hidden = 0;
  const rows: Row[] = [];
  const seen = new Set<string>();
  for (const o of opps) {
    const prop = byOpp.get(o.o.id) ?? null;
    seen.add(o.o.id);
    if (!prop && HIDDEN_OPP_STATES.has(o.o.state ?? "")) { hidden += 1; continue; }
    rows.push({ id: o.o.id, opp: o, prop });
  }
  for (const p of byOpp.values()) if (!seen.has(p.p.opportunityId)) rows.push({ id: p.p.opportunityId, opp: null, prop: p });
  const when = (r: Row) => r.prop?.p.createdAt ?? r.opp?.o.firstSeenAt ?? "";
  rows.sort((a, b) => Number(awaiting(b)) - Number(awaiting(a)) || (scoreOf(b) ?? -1) - (scoreOf(a) ?? -1) || when(b).localeCompare(when(a)));
  return { rows, hidden };
}

// ── figures ──────────────────────────────────────────────────────────────

const levels = (r: Row) => {
  const p = r.prop?.p, plan = r.opp?.o.plan;
  return { entry: p?.entry?.price ?? plan?.entry ?? null, stop: p?.stopLoss ?? plan?.stopLoss ?? null, t1: p?.target1 ?? plan?.target1 ?? null, t2: p?.target2 ?? plan?.target2 ?? null };
};
/** Reward:risk to T2: the proposal's, else from the plan's own levels (T2 − entry) ÷ (entry − stop), long only. */
export function rrOf(r: Row): number | null {
  if (r.prop?.p.rr?.t2 != null) return r.prop.p.rr.t2;
  const l = levels(r);
  if (l.entry == null || l.stop == null || l.t2 == null || l.entry - l.stop <= 0) return null;
  return (l.t2 - l.entry) / (l.entry - l.stop);
}
const rrText = (v: number | null) => (v == null || !Number.isFinite(v) ? "—" : `${v.toFixed(1)}:1`);
const sourcesOf = (o: SptOpportunity | null) => (o ? new Set(o.signals.map((s) => s.scannerId ?? s.scannerName ?? s.signalId)).size : null);

/** Quantity with its note: "full size" / "reduced from N" / "would be N". */
export function sizingOf(pp: PaperProposal | null, d: Decision): { qty: string; note: string } {
  const p = pp?.p;
  if (!p) return { qty: "—", note: "no proposal" };
  const asked = p.risk?.requestedQty ?? pp?.requestedQty ?? p.sizing?.quantity ?? null;
  const approved = p.risk?.approvedQty ?? null;
  if (d.kind === "blocked") return { qty: "0", note: asked != null ? `would be ${asked.toLocaleString("en-IN")}` : "blocked" };
  if (approved != null && approved > 0) {
    if (asked != null && approved < asked) return { qty: approved.toLocaleString("en-IN"), note: `reduced from ${asked.toLocaleString("en-IN")}` };
    return { qty: approved.toLocaleString("en-IN"), note: "full size" };
  }
  if (p.sizing?.quantity != null) return { qty: p.sizing.quantity.toLocaleString("en-IN"), note: "sized, not yet risk-checked" };
  return { qty: "—", note: "not sized" };
}

/** The reason sentence: the risk engine's own words, else the proposal's, else the validation's, else a fixed sentence. */
export function reasonOf(r: Row, d: Decision, mode: SptMode | null): string {
  const p = r.prop?.p;
  const risk = p?.risk?.explanations ?? [];
  if (risk.length) return risk.join(" ");
  if (p?.explanations.length) return p.explanations.join(" ");
  if (d.kind === "conditional" && p?.risk?.conditional) return p.risk.conditional;
  const v = r.opp?.o.validation?.explanations ?? [];
  if (!p && v.length && d.kind !== "tracked") return v.join(" ");
  switch (d.kind) {
    case "approve": return "Cleared every risk check at full size.";
    case "reduced": return "Cleared the risk checks at a reduced size, to fit the risk budget.";
    case "conditional": return "Cleared on a condition the entry must still meet.";
    case "blocked": return `Blocked by the risk engine${p?.risk?.reasonCodes.length ? `: ${p.risk.reasonCodes.join(", ")}` : ""}.`;
    case "tracked": return p?.state === "TRACKING_ONLY" ? "Tracked only: your mode is Tracking, so no paper order is placed."
      : "Tracked only: scanner-to-paper trades cash longs for now, so no paper order is proposed for an F&O idea.";
    case "watchlist": return "Validation put this on the watchlist: not every entry condition is met yet.";
    case "done": return d.label === "WATCHLISTED" ? "Added to your watchlist." : d.label === "USER REJECTED" ? `You rejected it${p?.approval?.reason ? `: ${p.approval.reason}` : ""}.` : "A paper order was created from this opportunity.";
    default:
      if (!p) return mode === "off" ? "No proposal: your mode is Off." : r.opp?.o.state === "QUALIFIED" ? "No proposal for your account yet." : "Only qualified opportunities are proposed.";
      return "The risk engine has not decided yet.";
  }
}

const statusOf = (r: Row, action: Action | null) =>
  action === "ORDER CREATED" || r.prop?.p.state === "ORDER_CREATED" || r.prop?.p.state === "READY_FOR_ORDER" ? "ORDER CREATED"
    : r.prop?.p.state === AWAITING && !action ? "AWAITING USER APPROVAL" : "NO ORDER";

const CHECK_LABEL: Record<string, string> = {
  controls: "Kill switch and halt", account: "Paper account readable", ladder: "Drawdown ladder", positions: "Open positions under the cap",
  min_rr: "Reward:risk to T2", quantity: "Whole-share quantity", stressed: "Stressed risk within the open-risk room", price: "Fresh live price",
};
export const checkGlyph = (s: string): GlyphKind => (s === "pass" || s === "ok" ? "pass" : s === "fail" || s === "block" || s === "blocked" ? "fail" : "warn");

// ── the screen ───────────────────────────────────────────────────────────

export function PaperOpportunities({ mode }: { mode: SptMode | null }) {
  const opps = usePaperOpportunities();
  const props = usePaperProposals();
  // Two columns (1.5fr / 1fr) only when the table's column keeps its 640 px; stacked below that (beside the docked Copilot).
  const [narrow, ref] = useNarrow(1090);
  const [selected, setSelected] = useState<string | null>(null);
  const [actions, setActions] = useState<Record<string, Action>>({});
  const joined = useMemo(() => joinRows(opps.data ?? [], props.data ?? []), [opps.data, props.data]);
  const rows = joined.rows;
  const cur = rows.find((r) => r.id === selected) ?? rows[0] ?? null;
  const act = (id: string, a: Action) => setActions((m) => ({ ...m, [id]: a }));
  const detailRef = useRef<HTMLDivElement>(null);
  // Stacked (narrow) layout: the detail is under the table, so a row pick brings it into view.
  const pick = (id: string) => {
    setSelected(id);
    if (narrow) requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  let body: ReactNode;
  if (opps.isPending && props.isPending) body = <LoadingBlock label="Reading opportunities" rows={4} />;
  else if (opps.isError && props.isError) {
    body = <div data-testid="pv2-opps-error"><QueryProblem what="Opportunities and your proposals" error={opps.error} onRetry={() => { void opps.refetch(); void props.refetch(); }} /></div>;
  } else if (!rows.length) {
    body = (
      <Card testId="pv2-opps-empty">
        <Note>
          No scanner opportunity is open{opps.isError ? " (the opportunities could not be read)" : ""} and you have no proposal{props.isError ? " (your proposals could not be read)" : ""}.
          Opportunities appear here as the scanners record signals and validation consolidates them.
          {joined.hidden ? ` ${joined.hidden} expired or validation-rejected ${joined.hidden === 1 ? "opportunity is" : "opportunities are"} not listed.` : ""}
        </Note>
      </Card>
    );
  } else {
    body = (
      <Split cols="minmax(0,1.5fr) minmax(0,1fr)" narrow={narrow} testId="pv2-opps-grid">
        <Card testId="pv2-opps-list" pad={0} style={{ gap: 0, overflow: "hidden" }}>
          {(opps.isError || props.isError) && (
            <div data-testid="pv2-opps-partial" role="status" style={{ padding: "10px 14px", fontSize: 12.5, color: "var(--amber)", borderBottom: "1px solid var(--cp-line)" }}>
              {opps.isError ? `The opportunities could not be read (${sptProblem(opps.error).message}); only your proposals are listed.`
                : `Your proposals could not be read (${sptProblem(props.error).message}), so no decision is shown.`}
            </div>
          )}
          <Table rows={rows} actions={actions} selectedId={cur?.id ?? null} onSelect={pick} />
          <div style={{ padding: "12px 16px", borderTop: "1px solid var(--cp-line)" }}>
            <Note testId="pv2-opps-foot">Opportunity score rates setup quality. It is not a probability of profit and scanner scores are never summed.</Note>
            {joined.hidden > 0 && <Note testId="pv2-opps-hidden">{joined.hidden} expired or validation-rejected {joined.hidden === 1 ? "opportunity is" : "opportunities are"} not listed.</Note>}
          </div>
        </Card>
        <div ref={detailRef} className="min-w-0" style={narrow ? { scrollMarginTop: 12 } : { position: "sticky", top: 20 }}>
          {cur && <Detail key={cur.id} r={cur} mode={mode} action={actions[cur.id] ?? null} onAction={(a) => act(cur.id, a)} />}
        </div>
      </Split>
    );
  }

  return (
    <div ref={ref} data-testid="pv2-opps" className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      <SectionHeader testId="pv2-opps-head" eyebrow="Scanner opportunities" title="Consolidated setups, ranked after the risk engine has spoken." />
      {body}
    </div>
  );
}

// ── the table ────────────────────────────────────────────────────────────

const HEADS: Array<[string, boolean]> = [["Symbol", false], ["Signals", false], ["Opp score", true], ["Entry", true], ["R:R", true], ["Risk ₹", true], ["Decision", false]];
// Column minimums sum to 556 + 6 × 8 gap + 28 padding = 632, inside the design's 640 min-width table.
const COLS = "minmax(100px,1.4fr) minmax(70px,0.8fr) minmax(56px,0.6fr) minmax(84px,0.9fr) minmax(48px,0.5fr) minmax(64px,0.7fr) minmax(128px,1.2fr)";

function Table({ rows, actions, selectedId, onSelect }: { rows: Row[]; actions: Record<string, Action>; selectedId: string | null; onSelect: (id: string) => void }) {
  return (
    <div data-testid="pv2-opps-table" className="cp-scroll min-w-0" style={{ overflowX: "auto" }}>
      <div role="table" aria-label="Scanner opportunities" style={{ minWidth: 640 }}>
        <div role="row" className="grid" style={{ gridTemplateColumns: COLS, gap: 8, padding: "12px 14px", borderBottom: "1px solid var(--cp-line)" }}>
          {HEADS.map(([h, right]) => <span key={h} role="columnheader" style={{ ...mono10, color: "var(--cp-ink-3)", textAlign: right ? "right" : "left" }}>{h}</span>)}
        </div>
        {rows.map((r) => {
          const d = decisionOf(r, actions[r.id] ?? null);
          const on = r.id === selectedId;
          const o = r.opp?.o ?? null;
          const n = sourcesOf(o);
          const dir = (o?.direction ?? r.prop?.p.direction ?? "—").toUpperCase();
          const seg = isFno(r) ? "F&O" : "EQ";
          return (
            <div key={r.id} role="row" tabIndex={0} aria-selected={on} data-testid="pv2-opp-row" data-id={r.id} data-decision={d.label} data-selected={on ? "true" : "false"}
              onClick={() => onSelect(r.id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(r.id); } }}
              className="grid items-center" style={{ gridTemplateColumns: COLS, gap: 8, padding: "12px 14px", borderBottom: "1px solid var(--cp-line)", cursor: "pointer",
                background: on ? "var(--bg-3)" : "transparent", fontSize: 13 }}>
              <span role="cell" className="flex min-w-0 flex-col" style={{ gap: 2 }}>
                <span data-testid="pv2-opp-symbol" style={{ fontWeight: 600, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{symbolOf(r)}</span>
                <span style={{ ...mono10, color: "var(--cp-ink-3)" }}>{dir} · {seg}</span>
              </span>
              <span role="cell" data-testid="pv2-opp-signals" style={{ color: "var(--cp-ink-2)" }}>{n == null ? "—" : `${n} ${n === 1 ? "source" : "sources"}`}</span>
              <span role="cell" data-testid="pv2-opp-score" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1, textAlign: "right", color: "var(--cp-ink)", ...NUM }}>
                {scoreOf(r) == null ? "—" : Math.round(scoreOf(r) as number)}
              </span>
              <span role="cell" data-testid="pv2-opp-entry" style={{ textAlign: "right", fontFamily: "var(--mono)", fontSize: 12.5, ...NUM }}>{price(levels(r).entry)}</span>
              <span role="cell" data-testid="pv2-opp-rr" style={{ textAlign: "right", fontFamily: "var(--mono)", fontSize: 12.5, ...NUM }}>{rrText(rrOf(r))}</span>
              <span role="cell" data-testid="pv2-opp-risk" style={{ textAlign: "right", fontFamily: "var(--mono)", fontSize: 12.5, ...NUM }}>{r.prop ? rupees(plannedRiskOf(r.prop.p)) : "—"}</span>
              <span role="cell"><Pill tone={d.tone} testId="pv2-opp-decision">{d.label}</Pill></span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── the detail ───────────────────────────────────────────────────────────

const IST_HM = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
const hm = (iso: string | null) => { if (!iso) return "—"; const t = Date.parse(iso); return Number.isFinite(t) ? IST_HM.format(new Date(t)) : "—"; };

function PlanTile({ label, value, tone, testId }: { label: string; value: string; tone?: PillTone; testId: string }) {
  return (
    <Tile tone={tone} testId={testId}>
      <Eyebrow tone={tone}>{label}</Eyebrow>
      <span data-testid={`${testId}-value`} style={{ fontFamily: "var(--mono)", fontSize: 14, color: "var(--cp-ink)", ...NUM }}>{value}</span>
    </Tile>
  );
}

function Detail({ r, mode, action, onAction }: { r: Row; mode: SptMode | null; action: Action | null; onAction: (a: Action) => void }) {
  const d = decisionOf(r, action);
  const p: SptProposal | null = r.prop?.p ?? null;
  const o = r.opp?.o ?? null;
  const l = levels(r);
  const sz = sizingOf(r.prop, d);
  const signals = o?.signals ?? [];
  const checks: RiskCheck[] = r.prop?.checks ?? [];
  const hard = d.kind === "blocked";
  return (
    <Card testId="pv2-opp-detail" attrs={{ "data-id": r.id, "data-decision": d.label }}>
      <div className="flex min-w-0 items-start justify-between" style={{ gap: 12 }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <Eyebrow testId="pv2-detail-id" style={{ overflowWrap: "anywhere" }}>{r.id} · {statusOf(r, action)}</Eyebrow>
          <span data-testid="pv2-detail-symbol" style={{ fontFamily: "var(--display)", fontSize: 30, lineHeight: 1.05, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{symbolOf(r)}</span>
          <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>
            {[r.opp?.exchange, (o?.direction ?? p?.direction)?.toUpperCase(), o?.horizon ?? p?.horizon, isFno(r) ? "F&O" : "cash"].filter(Boolean).join(" · ")}
          </span>
        </div>
        <Pill tone={d.tone} testId="pv2-detail-decision">{d.label}</Pill>
      </div>
      <p data-testid="pv2-detail-reason" className="m-0" style={{ fontSize: 14.5, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{reasonOf(r, d, mode)}</p>

      <section className="flex min-w-0 flex-col" style={{ gap: 8 }}>
        <Eyebrow as="h3">Supporting signals · {signals.length}</Eyebrow>
        {!signals.length ? <Note>{o ? "No scanner signal is recorded on this opportunity." : "The opportunity is not in today's list, so its signals are not shown."}</Note> : (
          <div className="grid min-w-0" style={{ gap: 8, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,150px),1fr))" }}>
            {signals.map((s) => (
              <Tile key={s.signalId} testId="pv2-detail-signal">
                <span style={{ fontSize: 13, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{s.scannerName ?? s.scannerId ?? "—"}</span>
                <span style={{ ...mono10, color: "var(--cp-ink-3)" }}>{hm(s.detectedAt)} · score {s.score == null ? "—" : Math.round(s.score)}</span>
              </Tile>
            ))}
          </div>
        )}
      </section>

      <section className="flex min-w-0 flex-col" style={{ gap: 8 }}>
        <Eyebrow as="h3">Strategy plan</Eyebrow>
        {l.entry == null && l.stop == null ? <Note>No plan levels are recorded on this opportunity.</Note> : (
          <div className="grid min-w-0" style={{ gap: 8, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,110px),1fr))" }}>
            <PlanTile label="Entry" value={price(l.entry)} testId="pv2-plan-entry" />
            <PlanTile label="Stop" value={price(l.stop)} tone="danger" testId="pv2-plan-stop" />
            <PlanTile label="T1" value={price(l.t1)} tone="mint" testId="pv2-plan-t1" />
            <PlanTile label="T2" value={price(l.t2)} tone="mint" testId="pv2-plan-t2" />
          </div>
        )}
      </section>

      <div data-testid="pv2-detail-sizing" className="grid min-w-0" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 10, padding: "12px 0", borderTop: "1px solid var(--cp-line)", borderBottom: "1px solid var(--cp-line)" }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 3 }}>
          <Eyebrow>Quantity</Eyebrow>
          <span data-testid="pv2-size-qty" style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.05, ...NUM }}>{sz.qty}</span>
          <span data-testid="pv2-size-note" style={{ fontSize: 11.5, color: d.kind === "reduced" ? "var(--amber)" : "var(--cp-ink-3)" }}>{sz.note}</span>
        </div>
        <div className="flex min-w-0 flex-col" style={{ gap: 3 }}>
          <Eyebrow>Capital</Eyebrow>
          <span data-testid="pv2-size-capital" style={{ fontFamily: "var(--mono)", fontSize: 14, ...NUM, overflowWrap: "anywhere" }}>{p ? rupees(capitalOf(p)) : "—"}</span>
        </div>
        <div className="flex min-w-0 flex-col" style={{ gap: 3 }}>
          <Eyebrow>Planned risk</Eyebrow>
          <span data-testid="pv2-size-risk" style={{ fontFamily: "var(--mono)", fontSize: 14, ...NUM, overflowWrap: "anywhere" }}>{p ? rupees(plannedRiskOf(p)) : "—"}</span>
        </div>
      </div>

      <section className="flex min-w-0 flex-col" style={{ gap: 8 }}>
        <Eyebrow as="h3">Risk engine checks</Eyebrow>
        {!checks.length ? (
          <Note testId="pv2-checks-none">{!p ? "No proposal for your account, so the risk engine has not checked this one." : p.risk ? "The risk record lists no individual checks." : "The risk engine has not checked this proposal yet."}</Note>
        ) : (
          <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 7 }}>
            {checks.map((c, i) => (
              <li key={`${c.check}-${i}`} data-testid="pv2-check" data-status={c.status} className="flex min-w-0 items-start" style={{ gap: 9 }}>
                <Glyph kind={checkGlyph(c.status)} />
                <span className="flex min-w-0 flex-1 flex-wrap justify-between" style={{ gap: "2px 10px", fontSize: 13 }}>
                  <span style={{ color: "var(--cp-ink)" }}>{CHECK_LABEL[c.check] ?? c.check.replace(/_/g, " ").replace(/^\w/, (x) => x.toUpperCase())}</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere", textAlign: "right" }}>
                    {c.status !== "pass" && c.message ? c.message : c.detail ?? c.status}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Actions r={r} d={d} action={action} onAction={onAction} />
      <Note testId="pv2-detail-foot">
        {hard ? "The risk engine has the final say. User approval cannot override a hard limit." : "Approval expires if price leaves the entry range, data goes stale or policy changes."}
      </Note>
    </Card>
  );
}

// ── the actions ──────────────────────────────────────────────────────────

const dim = (disabled: boolean) => (disabled ? { opacity: 0.35, cursor: "not-allowed" } : {});

function Actions({ r, d, action, onAction }: { r: Row; d: Decision; action: Action | null; onAction: (a: Action) => void }) {
  const approve = useApprove();
  const reject = useReject();
  const lists = usePersonalLists();
  const addStock = useAddStock();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [needReason, setNeedReason] = useState(false);
  const p = r.prop?.p ?? null;
  const oppId = p?.opportunityId ?? r.id;
  const symbol = symbolOf(r);
  const waiting = p?.state === AWAITING;
  const acted = action != null || d.kind === "done";
  const noApprove = acted || d.kind === "blocked" || d.kind === "watchlist" || d.kind === "tracked" || !waiting;
  const why = acted ? null : d.kind === "blocked" ? "Blocked by the risk engine." : d.kind === "watchlist" ? "On the watchlist: not every entry condition is met."
    : d.kind === "tracked" ? "Tracked only: no paper order for this one." : !p ? "No proposal for your account to approve." : !waiting ? "Nothing awaits your approval here." : null;
  const list = lists.data?.lists[0] ?? null;
  const watchDisabled = action === "WATCHLISTED" || addStock.isPending || !list || symbol === "—";
  const approveLabel = acted && (action === "ORDER CREATED" || d.label === "ORDER CREATED") ? "Done · order created" : approve.isPending ? "Approving…"
    : d.kind === "conditional" ? "Arm conditional order" : "Approve paper trade";

  const doApprove = () => approve.mutate(oppId, {
    onSuccess: (res) => { if (res.order?.state !== "REJECTED") onAction("ORDER CREATED"); },
  });
  const doReject = () => {
    const t = reason.trim();
    if (!t) { setNeedReason(true); return; }
    reject.mutate({ opportunityId: oppId, reason: t }, { onSuccess: () => { setRejecting(false); onAction("USER REJECTED"); } });
  };
  const doWatch = () => list && addStock.mutate({ id: list.watchlist_id, symbol }, { onSuccess: () => onAction("WATCHLISTED") });

  return (
    <div data-testid="pv2-actions" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <button type="button" data-testid="pv2-approve" disabled={noApprove || approve.isPending} aria-disabled={noApprove} onClick={doApprove}
          style={{ ...btnPrimary, ...dim(noApprove), fontWeight: 600 }}>{approveLabel}</button>
        <button type="button" data-testid="pv2-watchlist" disabled={watchDisabled} onClick={doWatch} style={{ ...btn, ...dim(watchDisabled) }}>
          {addStock.isPending ? "Adding…" : action === "WATCHLISTED" ? "On your watchlist" : "Add to watchlist"}
        </button>
        <button type="button" data-testid="pv2-reject" disabled={acted || !waiting || reject.isPending} onClick={() => setRejecting((v) => !v)}
          style={{ ...btnDanger, ...dim(acted || !waiting) }}>Reject</button>
      </div>
      {why && <span data-testid="pv2-approve-why" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{why}</span>}
      {rejecting && (
        <div data-testid="pv2-reject-form" className="flex min-w-0 flex-wrap items-center" style={{ gap: 8 }}>
          <input data-testid="pv2-reject-reason" aria-label="Why reject? One line, recorded with the proposal" placeholder="Why? One line, recorded with the proposal"
            maxLength={200} value={reason} onChange={(e) => { setReason(e.target.value); setNeedReason(false); }} style={{ ...input, flex: "1 1 220px" }} />
          <button type="button" data-testid="pv2-reject-confirm" disabled={reject.isPending} onClick={doReject} style={btnDanger}>{reject.isPending ? "Rejecting…" : "Confirm reject"}</button>
          <button type="button" style={btn} onClick={() => { setRejecting(false); setNeedReason(false); }}>Cancel</button>
          {needReason && <span data-testid="pv2-reject-need" role="alert" style={{ fontSize: 12, color: "var(--cp-danger)", flexBasis: "100%" }}>A one-line reason is needed to reject.</span>}
        </div>
      )}
      {!list && lists.isSuccess && <span data-testid="pv2-watchlist-none" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>You have no watchlist yet: make one in Trade Desk › Watchlists, then add to it here.</span>}
      {lists.isError && <span data-testid="pv2-watchlist-lists-error" style={{ fontSize: 12, color: "var(--amber)" }}>Your watchlists could not be read ({sptProblem(lists.error).message}).</span>}
      {addStock.isSuccess && (
        <span data-testid="pv2-watchlist-done" role="status" style={{ fontSize: 12, color: "var(--mint)" }}>
          {addStock.data.added ? `Added ${addStock.data.stock.symbol} to ${addStock.data.watchlist.name}.` : `${addStock.data.stock.symbol} is already on ${addStock.data.watchlist.name}.`}
        </span>
      )}
      {addStock.isError && <ProblemLine p={sptProblem(addStock.error)} testId="pv2-watchlist-error" lead="Not added:" />}
      {approve.data?.order?.state === "REJECTED" && (
        <span data-testid="pv2-approve-refused" role="alert" style={{ fontSize: 12.5, color: "var(--cp-danger)" }}>
          Approved, but the paper engine refused the order{approve.data.order.rejectReason ? `: ${approve.data.order.rejectReason}` : ""}.
        </span>
      )}
      {approve.data && approve.data.order?.state !== "REJECTED" && (
        <span data-testid="pv2-approve-result" role="status" style={{ fontSize: 12.5, color: "var(--mint)" }}>
          Paper order {approve.data.order ? `${approve.data.order.orderType ?? ""} for ${approve.data.order.quantity ?? "—"} shares · ${approve.data.order.state ?? "state not sent"}` : "requested; no order was returned"}
          {approve.data.idempotent ? " (it was already approved)" : ""}{approve.data.order?.expiresAt ? ` · valid until ${istTime(approve.data.order.expiresAt)}` : ""}.
        </span>
      )}
      {approve.isError && <ProblemLine p={sptProblem(approve.error)} testId="pv2-approve-error" lead="Not approved:" />}
      {reject.isError && <ProblemLine p={sptProblem(reject.error)} testId="pv2-reject-error" lead="Not rejected:" />}
    </div>
  );
}
