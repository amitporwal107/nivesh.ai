/**
 * Trade Desk › Paper Trading › Opportunities (?tab=trade&view=paper&sub=opportunities) — Scanner-to-Paper Trading (owner,
 * 5 Nov 2026: "plain, functional screens on real data inside today's Trader workspace"; PRD §12.5, §19.3; Workflow §11, §23.1;
 * docs/scanner_paper_trading/DESIGN.md). Test cases SPT-UI-P-02 … P-12 in test_reports/spt_ui_paper_TESTCASES.md.
 *
 * The market-wide consolidated opportunities (GET /api/v1/opportunities) joined by opportunity_id to the caller's own proposals
 * (GET /api/v1/proposals): one row each; a proposal whose opportunity is not in the list is still a row. Both refetch every
 * 30 s. A row opens the drawer: the original signals, the validation, the plan, the proposal, the risk decision and its
 * history — and, in Approval mode for a proposal awaiting the user, Approve (POST …/approve) and Reject with a reason
 * (POST …/reject). The user's own PAPER account: standard words (entry, stop loss, target) are allowed here, as on the P&L
 * dashboard; never recommend / pick / suggested. Nothing here reaches a broker.
 */
import { useMemo, useState, type ReactNode } from "react";
import { LoadingBlock } from "../../../../components/ui";
import { QueryProblem } from "../../../trading/parts";
import { linkBtn, quiet } from "./parts";
import { MONO, card, eyebrow, serifTitle, useNow } from "./pnl-ui";
import {
  MODE_WORDS, OPP_LIMIT, PROPOSAL_LIMIT, capitalOf, plannedRiskOf, qtyOf, sptProblem, useApprove, useOpportunities, useOpportunity, useProposals,
  useReject, useRevalidate, useSptAccount, type OppFilters, type SptMode, type SptOpportunity, type SptProposal,
} from "./spt-api";
import {
  ORDER_STATE, OPP_STATE, ObjectRows, PROP_STATE, ProblemLine, RISK_DECISION, Rows, Section, SptDrawer, StateTag, btn, btnDanger, btnPrimary, count,
  countdown, fixed, input, istTime, mono, price, rupees, useNarrow,
} from "./spt-parts";

export const OPPS_NOTE = "Rule-based levels for your paper account. Not investment advice; no accuracy is claimed.";
const REVALIDATABLE = new Set(["CREATED", "CONDITIONAL", "WATCHLIST", "DATA_INSUFFICIENT"]);
const STATES = ["QUALIFIED", "CONDITIONAL", "WATCHLIST", "DATA_INSUFFICIENT", "CREATED", "VALIDATING", "REJECTED", "EXPIRED"];

interface Row { id: string; opp: SptOpportunity | null; prop: SptProposal | null }

const sources = (o: SptOpportunity | null) => {
  const names = [...new Set((o?.signals ?? []).map((s) => s.scannerName ?? s.scannerId ?? "—"))];
  return { n: o?.signals.length ?? null, names };
};

/** The minutes-and-seconds left of an approval request, ticking. */
function Countdown({ iso, testId }: { iso: string | null; testId: string }) {
  const now = useNow(1_000);
  const c = countdown(iso, now);
  if (!c) return null;
  return <span data-testid={testId} data-expired={c.expired ? "true" : "false"} style={{ ...mono, fontSize: 11, color: c.expired ? "var(--cp-ink-3)" : "var(--amber)" }}>{c.text}</span>;
}

function noProposalWhy(r: Row, mode: SptMode | null): string {
  if (mode === "off") return "No proposal · your mode is Off";
  if (r.opp && r.opp.state !== "QUALIFIED") return "No proposal · only qualified opportunities are proposed";
  return "No proposal yet";
}

// ── the screen ───────────────────────────────────────────────────────────

export default function SptOpportunities({ onSub }: { onSub: (sub: string) => void }) {
  const acct = useSptAccount();
  const [filters, setFilters] = useState<OppFilters>({ state: "", horizon: "", direction: "" });
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const opps = useOpportunities(filters);
  const props = useProposals();
  const [narrow, ref] = useNarrow(640);
  const mode = acct.data?.config?.mode ?? null;

  const rows = useMemo<Row[]>(() => {
    const byOpp = new Map<string, SptProposal>();
    for (const p of props.data ?? []) if (!byOpp.has(p.opportunityId)) byOpp.set(p.opportunityId, p);
    const out: Row[] = (opps.data?.items ?? []).map((o) => ({ id: o.id, opp: o, prop: byOpp.get(o.id) ?? null }));
    const seen = new Set(out.map((r) => r.id));
    // A proposal whose opportunity is not in this list (an older day, or past the list's limit) is still the user's row; it has
    // no market-wide state, so it is left out while a state filter is on.
    if (!filters.state) {
      for (const p of byOpp.values()) {
        if (seen.has(p.opportunityId)) continue;
        if ((filters.horizon && p.horizon !== filters.horizon) || (filters.direction && p.direction !== filters.direction)) continue;
        out.push({ id: p.opportunityId, opp: null, prop: p });
      }
    }
    const needle = q.trim().toUpperCase();
    const shown = needle ? out.filter((r) => (r.opp?.symbol ?? r.prop?.symbol ?? "").toUpperCase().includes(needle)) : out;
    const when = (r: Row) => r.prop?.createdAt ?? r.opp?.firstSeenAt ?? "";
    return shown.sort((a, b) => Number(b.prop?.state === "AWAITING_USER_APPROVAL") - Number(a.prop?.state === "AWAITING_USER_APPROVAL") || when(b).localeCompare(when(a)));
  }, [opps.data, props.data, filters, q]);

  const open = rows.find((r) => r.id === openId) ?? null;
  const set = (p: Partial<OppFilters>) => setFilters((f) => ({ ...f, ...p }));
  const awaiting = rows.filter((r) => r.prop?.state === "AWAITING_USER_APPROVAL").length;

  return (
    <div ref={ref} data-testid="spt-opps" data-narrow={narrow ? "true" : "false"} className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <header className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span style={eyebrow}>Paper Trading · Scanner-to-paper</span>
        <h2 className="m-0" style={serifTitle}>Scanner opportunities</h2>
        <span data-testid="spt-opps-note" style={{ ...quiet, color: "var(--cp-ink-2)" }}>{OPPS_NOTE}</span>
      </header>

      <ModeBanner acct={acct} onSettings={() => onSub("settings")} awaiting={awaiting} />

      <div data-testid="spt-opps-filters" className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <select data-testid="spt-filter-state" aria-label="State" value={filters.state} onChange={(e) => set({ state: e.target.value })} style={input}>
          <option value="">All states</option>
          {STATES.map((s) => <option key={s} value={s}>{OPP_STATE[s]?.label ?? s}</option>)}
        </select>
        <select data-testid="spt-filter-horizon" aria-label="Horizon" value={filters.horizon} onChange={(e) => set({ horizon: e.target.value })} style={input}>
          <option value="">Any horizon</option><option value="positional">Positional</option><option value="intraday">Intraday</option>
        </select>
        <select data-testid="spt-filter-direction" aria-label="Direction" value={filters.direction} onChange={(e) => set({ direction: e.target.value })} style={input}>
          <option value="">Any direction</option><option value="long">Long</option><option value="short">Short</option>
        </select>
        <input data-testid="spt-search" type="search" aria-label="Symbol" placeholder="Symbol" value={q} onChange={(e) => setQ(e.target.value)} style={{ ...input, width: 140 }} />
        <span style={{ ...quiet, fontSize: 11 }}>Refreshes every 30 s · {rows.length} shown</span>
      </div>

      {props.isError && (
        <span data-testid="spt-proposals-error" role="status" style={{ ...quiet, color: "var(--amber)" }}>
          Your proposals could not be read ({sptProblem(props.error).message}), so the proposal columns are empty.{" "}
          <button type="button" style={linkBtn} onClick={() => props.refetch()}>Retry</button>
        </span>
      )}

      {opps.isError ? (
        <div data-testid="spt-opps-error"><QueryProblem what="Opportunities" error={opps.error} onRetry={() => opps.refetch()} /></div>
      ) : opps.isPending ? (
        <LoadingBlock label="Reading opportunities" rows={4} />
      ) : rows.length === 0 ? (
        <div data-testid="spt-opps-empty" style={{ ...card, boxShadow: "none", padding: 18, ...quiet }}>
          No opportunity matches{filters.state || filters.horizon || filters.direction || q ? " these filters" : " yet"}. Opportunities appear as the scanners record signals.
        </div>
      ) : narrow ? (
        <div data-testid="spt-opps-cards" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
          {rows.map((r) => <OppCard key={r.id} r={r} mode={mode} onOpen={() => setOpenId(r.id)} />)}
        </div>
      ) : (
        <OppTable rows={rows} mode={mode} scoreLabel={opps.data?.scoreLabel ?? null} onOpen={setOpenId} />
      )}

      {(opps.data?.items.length ?? 0) >= OPP_LIMIT && (
        <span data-testid="spt-opps-limit" style={{ ...quiet, fontSize: 11 }}>Showing the first {OPP_LIMIT} opportunities the server returned (oldest first). Narrow with a filter.</span>
      )}
      {(props.data?.length ?? 0) >= PROPOSAL_LIMIT && <span style={{ ...quiet, fontSize: 11 }}>Your newest {PROPOSAL_LIMIT} proposals are joined; older ones are not shown.</span>}
      {opps.data?.scoreLabel && <span data-testid="spt-score-label" style={{ ...quiet, fontSize: 11 }}>{opps.data.scoreLabel}</span>}

      {open && <OppDrawer r={open} mode={mode} onClose={() => setOpenId(null)} />}
    </div>
  );
}

function ModeBanner({ acct, onSettings, awaiting }: { acct: ReturnType<typeof useSptAccount>; onSettings: () => void; awaiting: number }) {
  if (acct.isError) {
    return (
      <div data-testid="spt-mode-banner" data-mode="" role="status" style={{ ...card, boxShadow: "none", padding: "12px 16px", ...quiet, color: "var(--amber)" }}>
        Your scanner-to-paper mode could not be read ({sptProblem(acct.error).message}).{" "}
        <button type="button" style={linkBtn} onClick={() => acct.refetch()}>Retry</button>
      </div>
    );
  }
  const mode = acct.data?.config?.mode ?? null;
  return (
    <div data-testid="spt-mode-banner" data-mode={mode ?? ""} className="flex flex-wrap items-center"
      style={{ ...card, boxShadow: "none", gap: "6px 14px", padding: "12px 16px", borderColor: mode === "auto" ? "var(--amber-line)" : mode === "approval" ? "var(--mint-line)" : "var(--cp-line)" }}>
      <span style={eyebrow}>Your mode</span>
      <span data-testid="spt-mode-value" style={{ fontFamily: MONO, fontSize: 13, color: "var(--cp-ink)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{mode ? MODE_WORDS[mode].label : acct.isPending ? "…" : "—"}</span>
      <span style={{ ...quiet, color: "var(--cp-ink-2)", flex: "1 1 260px", minWidth: 0 }}>{mode ? MODE_WORDS[mode].line : acct.isPending ? "Reading your mode…" : "The mode is not recorded."}</span>
      {awaiting > 0 && mode === "approval" && <span data-testid="spt-awaiting-count" style={{ ...mono, color: "var(--amber)" }}>{awaiting} awaiting your approval</span>}
      <button type="button" data-testid="spt-mode-change" onClick={onSettings} style={linkBtn}>Change in Settings ›</button>
    </div>
  );
}

// ── cells shared by the table and the cards ──────────────────────────────

function Levels({ p }: { p: SptProposal | null }) {
  if (!p) return <span style={{ color: "var(--cp-ink-3)" }}>—</span>;
  return (
    <span data-testid="spt-row-levels" style={{ ...mono, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
      {price(p.entry?.price)} / {price(p.stopLoss)} / {price(p.target1)} / {price(p.target2)}
    </span>
  );
}

function ProposalCell({ r, mode }: { r: Row; mode: SptMode | null }) {
  const p = r.prop;
  if (!p) return <span data-testid="spt-row-noproposal" style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>{noProposalWhy(r, mode)}</span>;
  return (
    <span className="flex min-w-0 flex-col items-start" style={{ gap: 3 }}>
      <StateTag map={PROP_STATE} code={p.state} testId="spt-row-proposal" />
      {p.state === "AWAITING_USER_APPROVAL" && <Countdown iso={p.approval?.expiresAt ?? null} testId="spt-row-countdown" />}
      {p.order && <span data-testid="spt-row-order" style={{ ...mono, fontSize: 11 }}>order <StateTag map={ORDER_STATE} code={p.order.state} /></span>}
    </span>
  );
}

function RiskCell({ p }: { p: SptProposal | null }) {
  if (!p?.risk && !(p && p.reasonCodes.length)) return <span style={{ color: "var(--cp-ink-3)" }}>—</span>;
  const codes = p.risk?.reasonCodes.length ? p.risk.reasonCodes : p.reasonCodes;
  return (
    <span className="flex min-w-0 flex-col items-start" style={{ gap: 3 }}>
      {p.risk ? <StateTag map={RISK_DECISION} code={p.risk.decision} testId="spt-row-risk" /> : null}
      {codes.length > 0 && <span data-testid="spt-row-codes" style={{ ...mono, fontSize: 10.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{codes.slice(0, 3).join(" · ")}{codes.length > 3 ? " …" : ""}</span>}
    </span>
  );
}

const rr = (p: SptProposal | null) => (p?.rr ? `${fixed(p.rr.t1)} / ${fixed(p.rr.t2)}` : "—");
const qtyLine = (p: SptProposal | null) => {
  if (!p) return { v: "—", sub: null as string | null };
  const q = qtyOf(p);
  return { v: count(q.qty), sub: q.basis === "approved" ? "approved by the risk engine" : q.basis === "sized" ? "sized by your limits" : null };
};

// ── desktop table ────────────────────────────────────────────────────────

const COLS = [1.15, 0.9, 1.05, 0.6, 1.9, 0.6, 0.75, 0.85, 0.8, 1.05, 1.1].map((f) => `minmax(0,${f}fr)`).join(" ");
const HEADS = ["Symbol", "State", "Scanner sources", "Score", "Entry / stop loss / target 1 / target 2", "R:R (T1 / T2)", "Quantity", "Capital", "Planned risk", "Risk decision", "Proposal"];

function OppTable({ rows, mode, scoreLabel, onOpen }: { rows: Row[]; mode: SptMode | null; scoreLabel: string | null; onOpen: (id: string) => void }) {
  return (
    <div data-testid="spt-opps-table" style={{ ...card, boxShadow: "none", overflowX: "auto" }}>
      <div style={{ minWidth: 1080 }}>
        <div role="row" className="grid" style={{ gridTemplateColumns: COLS, gap: 8, padding: "10px 14px", borderBottom: "1px solid var(--cp-line)" }}>
          {HEADS.map((h) => (
            <span key={h} role="columnheader" title={h === "Score" ? scoreLabel ?? undefined : undefined} style={{ ...eyebrow, fontSize: 9.5 }}>
              {h}{h === "Score" ? <span style={{ display: "block", textTransform: "none", letterSpacing: 0 }}>not a probability</span> : null}
              {h === "Quantity" ? <span style={{ display: "block", textTransform: "none", letterSpacing: 0 }}>sized by your limits</span> : null}
            </span>
          ))}
        </div>
        {rows.map((r) => {
          const o = r.opp, p = r.prop, s = sources(o), ql = qtyLine(p);
          return (
            <div key={r.id} role="row" tabIndex={0} data-testid="spt-row" data-id={r.id} data-symbol={o?.symbol ?? p?.symbol ?? ""}
              onClick={() => onOpen(r.id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(r.id); } }}
              className="grid" style={{ gridTemplateColumns: COLS, gap: 8, padding: "11px 14px", borderBottom: "1px solid var(--cp-line)", cursor: "pointer", alignItems: "start", fontSize: 12.5 }}>
              <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
                <span data-testid="spt-row-symbol" style={{ fontWeight: 600, color: "var(--cp-ink)" }}>{o?.symbol ?? p?.symbol}</span>
                <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{(o?.direction ?? p?.direction) ?? "—"} · {(o?.horizon ?? p?.horizon) ?? "—"}</span>
              </span>
              <span><StateTag map={OPP_STATE} code={o?.state ?? null} testId="spt-row-state" empty="not in list" /></span>
              <span data-testid="spt-row-sources" title={s.names.join(", ")} style={{ minWidth: 0, overflowWrap: "anywhere", color: "var(--cp-ink-2)" }}>
                {s.n == null ? "—" : <><span style={mono}>{s.n}</span> · {s.names.slice(0, 2).join(", ")}{s.names.length > 2 ? ` +${s.names.length - 2}` : ""}</>}
              </span>
              <span data-testid="spt-row-score" style={mono}>{fixed(o?.validation?.score, 0)}</span>
              <Levels p={p} />
              <span data-testid="spt-row-rr" style={mono}>{rr(p)}</span>
              <span data-testid="spt-row-qty" style={mono}>{ql.v}</span>
              <span data-testid="spt-row-capital" style={mono}>{p ? rupees(capitalOf(p)) : "—"}</span>
              <span data-testid="spt-row-planned" style={mono}>{p ? rupees(plannedRiskOf(p)) : "—"}</span>
              <RiskCell p={p} />
              <ProposalCell r={r} mode={mode} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── phone cards ──────────────────────────────────────────────────────────

function OppCard({ r, mode, onOpen }: { r: Row; mode: SptMode | null; onOpen: () => void }) {
  const o = r.opp, p = r.prop, s = sources(o), ql = qtyLine(p);
  const kv = (k: string, v: ReactNode, id: string) => (
    <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <span style={{ ...eyebrow, fontSize: 9 }}>{k}</span>
      <span data-testid={`spt-card-${id}`} style={{ ...mono, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{v}</span>
    </div>
  );
  return (
    <button type="button" data-testid="spt-row" data-id={r.id} data-symbol={o?.symbol ?? p?.symbol ?? ""} onClick={onOpen}
      className="flex min-w-0 flex-col text-left" style={{ ...card, boxShadow: "none", gap: 10, padding: 14, width: "100%", font: "inherit", color: "inherit", cursor: "pointer" }}>
      <div className="flex w-full min-w-0 flex-wrap items-center justify-between" style={{ gap: 6 }}>
        <span data-testid="spt-row-symbol" style={{ fontWeight: 600, fontSize: 15 }}>{o?.symbol ?? p?.symbol}</span>
        <StateTag map={OPP_STATE} code={o?.state ?? null} testId="spt-row-state" empty="not in list" />
      </div>
      <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>
        {(o?.direction ?? p?.direction) ?? "—"} · {(o?.horizon ?? p?.horizon) ?? "—"} · {s.n ?? "—"} signal{s.n === 1 ? "" : "s"}{s.names.length ? ` · ${s.names.join(", ")}` : ""} · score {fixed(o?.validation?.score, 0)} (not a probability)
      </span>
      {p && (
        <div className="grid w-full" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: "8px 12px" }}>
          {kv("Entry / stop loss", `${price(p.entry?.price)} / ${price(p.stopLoss)}`, "entry")}
          {kv("Target 1 / 2", `${price(p.target1)} / ${price(p.target2)}`, "targets")}
          {kv(`Quantity${ql.sub ? ` · ${ql.sub}` : ""}`, ql.v, "qty")}
          {kv("R:R (T1 / T2)", rr(p), "rr")}
          {kv("Capital", rupees(capitalOf(p)), "capital")}
          {kv("Planned risk", rupees(plannedRiskOf(p)), "planned")}
        </div>
      )}
      <div className="flex w-full min-w-0 flex-wrap items-start justify-between" style={{ gap: 8 }}>
        <RiskCell p={p} />
        <ProposalCell r={r} mode={mode} />
      </div>
    </button>
  );
}

// ── the drawer ───────────────────────────────────────────────────────────

function OppDrawer({ r, mode, onClose }: { r: Row; mode: SptMode | null; onClose: () => void }) {
  const fresh = useOpportunity(r.opp ? r.id : r.prop?.opportunityId ?? null);
  const o = fresh.data ?? r.opp;
  const p = r.prop;
  const symbol = o?.symbol ?? p?.symbol ?? "—";
  return (
    <SptDrawer testId="spt-drawer" label={`${symbol} · opportunity`} eyebrow="Opportunity · your paper account" title={symbol} onClose={onClose}
      sub={<>{(o?.direction ?? p?.direction) ?? "—"} · {(o?.horizon ?? p?.horizon) ?? "—"} · first seen {istTime(o?.firstSeenAt)} · <StateTag map={OPP_STATE} code={o?.state ?? null} empty="not in the list" /></>}>
      <span style={{ ...quiet, fontSize: 11.5 }}>{OPPS_NOTE}</span>
      <ActionBlock r={r} mode={mode} />
      <Section title="Scanner signals" testId="spt-drawer-signals" note={o && o.conflicts ? `${o.conflicts} opposite-direction signal${o.conflicts === 1 ? "" : "s"}` : undefined}>
        {fresh.isError && !o ? <span style={quiet}>The opportunity could not be read ({sptProblem(fresh.error).message}).</span>
          : !o?.signals.length ? <span style={quiet}>No signal is recorded on this opportunity.</span> : (
            <ul className="m-0 flex flex-col" style={{ gap: 6, padding: 0, listStyle: "none" }}>
              {o.signals.map((s) => (
                <li key={s.signalId} data-testid="spt-drawer-signal" className="flex flex-wrap items-baseline" style={{ gap: "2px 10px", fontSize: 12.5 }}>
                  <span style={{ color: "var(--cp-ink)" }}>{s.scannerName ?? s.scannerId ?? "—"}</span>
                  <span style={{ ...mono, color: "var(--cp-ink-3)" }}>{istTime(s.detectedAt)}</span>
                  <span style={{ ...mono, color: "var(--cp-ink-3)" }}>at {price(s.detectedPrice)}</span>
                  <span style={{ ...mono, color: "var(--cp-ink-3)" }}>scanner score {fixed(s.score, 0)}</span>
                </li>
              ))}
            </ul>
          )}
      </Section>
      <ValidationBlock o={o} />
      {o?.plan && (
        <Section title={`Plan${o.plan.rules ? ` · ${o.plan.rules}` : ""}`} testId="spt-drawer-plan">
          <Rows testPrefix="spt-plan" rows={[
            ["Entry", price(o.plan.entry), "entry"], ["Stop loss", price(o.plan.stopLoss), "stop"], ["Target 1 / 2", `${price(o.plan.target1)} / ${price(o.plan.target2)}`, "targets"],
            ["ATR · SMA20", `${fixed(o.plan.atr)} · ${fixed(o.plan.sma20)}`, "atr"], ["Plan valid", o.plan.planOk == null ? "—" : o.plan.planOk ? "yes" : `no${o.plan.note ? ` · ${o.plan.note}` : ""}`, "ok"],
          ]} />
        </Section>
      )}
      {p ? <ProposalBlock p={p} /> : <Section title="Your proposal" testId="spt-drawer-proposal"><span style={quiet}>{noProposalWhy(r, mode)}.</span></Section>}
    </SptDrawer>
  );
}

function ValidationBlock({ o }: { o: SptOpportunity | null }) {
  const reval = useRevalidate();
  const v = o?.validation ?? null;
  return (
    <Section title="Validation" testId="spt-drawer-validation" note={v ? `${istTime(v.at)}${v.version ? ` · ${v.version}` : ""}` : undefined}>
      {!v ? <span style={quiet}>Not validated yet.</span> : (
        <>
          <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <StateTag map={OPP_STATE} code={v.decision} testId="spt-validation-decision" />
            <span data-testid="spt-validation-score" style={mono}>score {fixed(v.score, 0)} / 100 · not a probability</span>
          </div>
          {v.reasonCodes.length > 0 && <span data-testid="spt-validation-codes" style={{ ...mono, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{v.reasonCodes.join(" · ")}</span>}
          {v.explanations.length > 0 && (
            <ul data-testid="spt-validation-explanations" className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, fontSize: 12.5, color: "var(--cp-ink-2)" }}>
              {v.explanations.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          )}
          {v.parts.length > 0 && (
            <Rows testPrefix="spt-score-part" rows={v.parts.map((pt) => [pt.name.replace(/_/g, " "), `${fixed(pt.points, 0)} of ${fixed(pt.max, 0)}${pt.note ? ` · ${pt.note}` : ""}`, pt.name])} />
          )}
          <details><summary style={{ ...quiet, cursor: "pointer" }}>Market, stock and liquidity evidence</summary>
            <div className="flex min-w-0 flex-col" style={{ gap: 10, paddingTop: 8 }}>
              <span style={eyebrow}>Market regime</span><ObjectRows obj={v.market} testPrefix="spt-market" />
              <span style={eyebrow}>Stock trend</span><ObjectRows obj={v.stock} testPrefix="spt-stock" />
              <span style={eyebrow}>Liquidity</span><ObjectRows obj={v.liquidity} testPrefix="spt-liquidity" />
              {v.dataAsOf && <><span style={eyebrow}>Data as of</span><ObjectRows obj={v.dataAsOf} testPrefix="spt-asof" /></>}
            </div>
          </details>
        </>
      )}
      {o && REVALIDATABLE.has(o.state ?? "") && (
        <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <button type="button" data-testid="spt-revalidate" style={btn} disabled={reval.isPending} onClick={() => reval.mutate(o.id)}>
            {reval.isPending ? "Revalidating…" : "Revalidate now"}
          </button>
          {reval.isSuccess && <span data-testid="spt-revalidate-result" style={quiet}>Revalidated: {reval.data.state ? OPP_STATE[reval.data.state]?.label ?? reval.data.state : "state not returned"}.</span>}
          {reval.isError && <ProblemLine p={sptProblem(reval.error)} testId="spt-revalidate-error" />}
        </div>
      )}
    </Section>
  );
}

function ProposalBlock({ p }: { p: SptProposal }) {
  const ql = qtyLine(p);
  const ep = p.exitPlan ?? {};
  const trail = (ep.trail && typeof ep.trail === "object") ? `${String((ep.trail as Record<string, unknown>).rule ?? "trail")} · k ${String((ep.trail as Record<string, unknown>).k ?? "—")}` : "none";
  const trend = (ep.trend_exit && typeof ep.trend_exit === "object") ? String((ep.trend_exit as Record<string, unknown>).rule ?? "trend exit") : "none";
  const rk = p.risk;
  return (
    <>
      <Section title="Your proposal" testId="spt-drawer-proposal" note={`made ${istTime(p.createdAt)}`}>
        <Rows testPrefix="spt-prop" rows={[
          ["State", <StateTag key="s" map={PROP_STATE} code={p.state} />, "state"],
          ["Entry", p.entry ? `${p.entry.type ?? "—"} at ${price(p.entry.price)}${p.entry.timeInForce ? ` · ${p.entry.timeInForce}` : ""}${p.entry.expiresAt ? ` until ${istTime(p.entry.expiresAt)}` : ""}` : "—", "entry"],
          ["Entry rule", p.entry?.rule ?? p.entry?.basis ?? "—", "rule"],
          ["Stop loss", price(p.stopLoss), "stop"],
          ["Target 1 / 2", `${price(p.target1)} / ${price(p.target2)}`, "targets"],
          ["R:R (T1 / T2)", `${rr(p)}${p.rr?.minRr != null ? ` · minimum ${fixed(p.rr.minRr)} to target 2` : ""}`, "rr"],
          [`Quantity${ql.sub ? ` (${ql.sub})` : ""}`, ql.v, "qty"],
          ["Capital", rupees(capitalOf(p)), "capital"],
          ["Sized with", p.sizing ? `${fixed(p.sizing.riskPct, 2)}% risk · ${count(p.sizing.quantity)} shares · planned ${rupees(p.sizing.plannedRisk)} · stressed ${rupees(p.sizing.stressedRisk)}` : "not sized", "sizing"],
          ["Exit plan", `${ep.t1_exit_fraction != null ? `${Math.round(Number(ep.t1_exit_fraction) * 100)}% at target 1` : "—"}${ep.move_stop_to_breakeven_at_t1 ? ", then stop loss to breakeven" : ""} · trail ${trail} · trend exit ${trend} · at most ${String(ep.max_hold_sessions ?? "—")} sessions`, "exit"],
          ["Price at proposal", p.price ? `${price(p.price.price)}${p.price.basis ? ` (${p.price.basis})` : ""} · ${istTime(p.price.receivedAt)}` : "—", "price"],
        ]} />
        {p.sizing?.blocked.length ? <span data-testid="spt-prop-blocked" style={{ ...mono, color: "var(--cp-danger)" }}>{p.sizing.blocked.map((b) => `${b.code}${b.message ? `: ${b.message}` : ""}`).join(" · ")}</span> : null}
        {p.reasonCodes.length > 0 && (
          <div data-testid="spt-prop-refusal" className="flex flex-col" style={{ gap: 3 }}>
            <span style={{ ...mono, color: "var(--cp-ink-2)" }}>{p.reasonCodes.join(" · ")}</span>
            {p.explanations.map((e, i) => <span key={i} style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>{e}</span>)}
          </div>
        )}
      </Section>
      <Section title="Risk decision" testId="spt-drawer-risk" note={rk?.at ? istTime(rk.at) : undefined}>
        {!rk ? <span style={quiet}>The risk engine has not decided yet.</span> : (
          <>
            <Rows testPrefix="spt-risk" rows={[
              ["Decision", <StateTag key="d" map={RISK_DECISION} code={rk.decision} testId="spt-risk-decision" />, "decision"],
              ["Quantity", `${count(rk.approvedQty)} approved of ${count(rk.requestedQty)} asked`, "qty"],
              ["Planned / stressed risk", `${rupees(rk.plannedRiskRs)} / ${rupees(rk.stressedRiskRs)}`, "planned"],
              ["Portfolio open risk", `${rupees(rk.portfolioRiskBeforeRs)} → ${rupees(rk.portfolioRiskAfterRs)}`, "portfolio"],
              ["Exposure", `${rupees(rk.exposureBeforeRs)} → ${rupees(rk.exposureAfterRs)}`, "exposure"],
              ...(rk.conditional ? [["Condition", rk.conditional, "condition"] as [string, ReactNode, string]] : []),
            ]} />
            {rk.reasonCodes.length > 0 && <span data-testid="spt-risk-codes" style={{ ...mono, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{rk.reasonCodes.join(" · ")}</span>}
            {rk.explanations.length > 0 && (
              <ul data-testid="spt-risk-explanations" className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, fontSize: 12.5, color: "var(--cp-ink-2)" }}>
                {rk.explanations.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            )}
          </>
        )}
      </Section>
      {p.history.length > 0 && (
        <Section title="History" testId="spt-drawer-history">
          <ol className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18, fontSize: 12, color: "var(--cp-ink-2)" }}>
            {p.history.map((h, i) => <li key={i}><span style={mono}>{istTime(h.at)}</span> · {h.to ? PROP_STATE[h.to]?.label ?? h.to : "—"}{h.reason ? ` · ${h.reason}` : ""}</li>)}
          </ol>
        </Section>
      )}
    </>
  );
}

/** Approve / Reject in Approval mode; otherwise what happened to the proposal. */
function ActionBlock({ r, mode }: { r: Row; mode: SptMode | null }) {
  const approve = useApprove();
  const reject = useReject();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [needReason, setNeedReason] = useState(false);
  const now = useNow(1_000);
  const p = r.prop;
  const oppId = p?.opportunityId ?? r.id;

  const result = approve.data ? (
    <div data-testid="spt-approve-result" data-order-state={approve.data.order?.state ?? ""} role="status"
      style={{ padding: "8px 12px", borderRadius: 10, border: "1px solid var(--mint-line)", background: "var(--mint-soft)", fontSize: 12.5, lineHeight: 1.5 }}>
      {approve.data.order
        ? <>Paper order {approve.data.order.orderType ?? ""} for {count(approve.data.order.quantity)} shares · <StateTag map={ORDER_STATE} code={approve.data.order.state} />
            {approve.data.order.state === "REJECTED" && approve.data.order.rejectReason ? <> · the paper engine refused it: <span style={mono}>{approve.data.order.rejectReason}</span></> : null}</>
        : <>Approved{approve.data.proposal?.state ? ` · ${PROP_STATE[approve.data.proposal.state]?.label ?? approve.data.proposal.state}` : ""}; no order was returned.</>}
      {approve.data.idempotent ? " (it was already approved)" : ""}
    </div>
  ) : null;
  const rejected = reject.data ? (
    <div data-testid="spt-reject-result" role="status" style={{ ...quiet, color: "var(--cp-ink-2)" }}>
      Rejected and recorded{reject.data.idempotent ? " (it was already rejected)" : ""}.
    </div>
  ) : null;

  if (!p) return null;
  if (p.state === "AWAITING_USER_APPROVAL" && !approve.data && !reject.data) {
    const c = countdown(p.approval?.expiresAt ?? null, now);
    const canAct = mode === "approval" || mode === "auto" || mode == null;
    return (
      <Section title="Your decision" testId="spt-actions" note={c ? undefined : "no expiry recorded"}>
        <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>This proposal passed the risk check and waits for you.</span>
          {c && <span data-testid="spt-countdown" data-expired={c.expired ? "true" : "false"} style={{ ...mono, color: c.expired ? "var(--cp-ink-3)" : "var(--amber)" }}>{c.expired ? "The approval window has passed" : `Approval window: ${c.text}`}</span>}
        </div>
        {!canAct && <span style={quiet}>Your mode is {mode ? MODE_WORDS[mode].label : "—"}; approving needs Approval or Auto mode.</span>}
        <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <button type="button" data-testid="spt-approve" style={btnPrimary} disabled={!canAct || approve.isPending || !!c?.expired} onClick={() => approve.mutate(oppId)}>
            {approve.isPending ? "Approving…" : "Approve paper trade"}
          </button>
          <button type="button" data-testid="spt-reject" style={btnDanger} disabled={reject.isPending} onClick={() => setRejecting((v) => !v)}>Reject</button>
        </div>
        {rejecting && (
          <div data-testid="spt-reject-form" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
            <label style={{ ...quiet, color: "var(--cp-ink-2)" }} htmlFor="spt-reject-reason">Why? The reason is recorded with the proposal.</label>
            <textarea id="spt-reject-reason" data-testid="spt-reject-reason" rows={2} maxLength={500} value={reason} onChange={(e) => { setReason(e.target.value); setNeedReason(false); }} style={{ ...input, width: "100%", resize: "vertical" }} />
            {needReason && <span data-testid="spt-reject-need-reason" role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>A reason is required to reject.</span>}
            <div className="flex flex-wrap" style={{ gap: 8 }}>
              <button type="button" data-testid="spt-reject-confirm" style={btnDanger} disabled={reject.isPending}
                onClick={() => { const t = reason.trim(); if (!t) { setNeedReason(true); return; } reject.mutate({ opportunityId: oppId, reason: t }); }}>
                {reject.isPending ? "Rejecting…" : "Confirm reject"}
              </button>
              <button type="button" style={btn} onClick={() => { setRejecting(false); setNeedReason(false); }}>Cancel</button>
            </div>
          </div>
        )}
        {approve.isError && <ProblemLine p={sptProblem(approve.error)} testId="spt-approve-error" lead="Not approved:" />}
        {reject.isError && <ProblemLine p={sptProblem(reject.error)} testId="spt-reject-error" lead="Not rejected:" />}
      </Section>
    );
  }
  // What happened (Auto, Tracking, or after a decision).
  const order = approve.data?.order ?? p.order;
  return (
    <Section title="What happened" testId="spt-outcome">
      {result}{rejected}
      {!approve.data && !reject.data && (
        <div className="flex min-w-0 flex-col" style={{ gap: 4, fontSize: 12.5, color: "var(--cp-ink-2)" }}>
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <StateTag map={PROP_STATE} code={p.state} testId="spt-outcome-state" />
            {p.state === "TRACKING_ONLY" && <span data-testid="spt-outcome-tracked">Tracked only: no paper order was placed (tracking mode).</span>}
            {p.state === "USER_REJECTED" && <span>You rejected it{p.approval?.reason ? `: ${p.approval.reason}` : ""}.</span>}
            {p.state === "APPROVAL_EXPIRED" && <span>The approval window passed before a decision.</span>}
          </span>
          {order && (
            <span data-testid="spt-outcome-order" style={mono}>
              Paper order {order.orderType ?? ""} · {count(order.quantity)} shares · <StateTag map={ORDER_STATE} code={order.state} />
              {order.rejectReason ? ` · ${order.rejectReason}` : ""}
            </span>
          )}
        </div>
      )}
    </Section>
  );
}
