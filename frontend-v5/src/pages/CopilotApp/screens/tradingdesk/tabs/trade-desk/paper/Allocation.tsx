/**
 * Paper Trading v2 › 03 Capital allocation (?tab=trade&view=paper&sub=allocation) — the owner's design of 5 Nov 2026,
 * docs/scanner_paper_trading/UI_DESIGN_V2.md §2.03 and §3. Capital and risk are allocated separately: F&O capital is margin,
 * F&O risk is strategy max loss.
 *
 *   header      synthesis "₹{deployed} is deployed. {bucket} uses {cap%} of it but carries {risk%} of open risk." (a fixed
 *               template over the figures; never a model) and the prose line
 *   KPIs        Account equity · Deployed · Reserved · pending · Risk budget left           GET /api/v1/risk/account/{id}
 *   policy      "Configure · allocation policy": the buckets, risk per trade, max positions (the shared draft, policy.tsx)
 *   left        "Capital vs risk · by strategy bucket": capital against each bucket's target, risk against its share of max
 *               open risk — both from the DRAFT, so they move before a save
 *   right       "Sector exposure · % equity" (GET /api/v1/risk/exposures/{id}); "F&O allocation · margin vs max loss"
 *               (GET /api/v1/paper/fno-structures); "Allocation changes · ranked by ₹ impact"
 *               (GET /api/v1/allocation/recommendations/{id}). Never "Recommended".
 *
 * Every empty or failed read says what is missing. Paper only; nothing reaches a broker.
 */
import type { ReactNode } from "react";
import { LoadingBlock } from "../../../../../components/ui";
import { QueryProblem } from "../../../../trading/parts";
import { useSptExposures, useSptRanked, useSptRiskAccount, type SptRankedItem, type SptRiskAccount } from "../../risk-desk/spt-risk-api";
import { MONO } from "../pnl-ui";
import { useNarrow } from "../spt-parts";
import { useFnoStructures, type FnoBook } from "./api-b";
import { AccountMissing, DASH, ValueBar, ofPct, pctTxt, rs0, rsC } from "./b-parts";
import { PolicyCard, usePolicyDraft, type PolicyDraft } from "./policy";
import { Card, Eyebrow, Kpi, KpiGrid, Note, Pill, SectionHeader, Split, toneColor, type PillTone, type SynthesisPart } from "./ui";

const PROSE = "Capital and risk are allocated separately. F&O capital is measured by margin and F&O risk by strategy max loss, so a small margin can still carry large risk.";

type BucketKey = "equity_positional" | "equity_intraday" | "fno";
const BUCKETS: Array<{ key: BucketKey; label: string; pct: "bucket_positional_pct" | "bucket_intraday_pct" | "bucket_fno_pct" }> = [
  { key: "equity_positional", label: "Equity positional", pct: "bucket_positional_pct" },
  { key: "equity_intraday", label: "Equity intraday", pct: "bucket_intraday_pct" },
  { key: "fno", label: "F&O strategies", pct: "bucket_fno_pct" },
];

interface BucketFig { key: BucketKey; label: string; capitalRs: number | null; riskRs: number | null; capBasis: string; riskBasis: string }

/** Each bucket's capital in use and open risk. F&O: the desk's paper structures' margin and max loss (§2.03); the equity buckets:
 *  the account route's bucket use (its `risk_rs` when sent — the route has no other per-bucket risk figure). */
function bucketFigs(a: SptRiskAccount | undefined, fno: FnoBook | undefined): BucketFig[] {
  return BUCKETS.map((b) => {
    const u = a?.utilisation.buckets[b.key];
    if (b.key === "fno") {
      return {
        key: b.key, label: b.label,
        capitalRs: fno?.totals.marginRs ?? u?.usedRs ?? null, riskRs: fno?.totals.maxLossRs ?? u?.riskRs ?? null,
        capBasis: fno?.totals.marginRs != null ? "margin of the open paper structures" : "the account's F&O bucket use",
        riskBasis: fno?.totals.maxLossRs != null ? "sum of the structures' max loss" : "the account's F&O bucket risk",
      };
    }
    return { key: b.key, label: b.label, capitalRs: u?.usedRs ?? null, riskRs: u?.riskRs ?? null, capBasis: "the account's bucket use", riskBasis: "the account's bucket risk" };
  });
}

/** The header sentence, a fixed template: the bucket whose share of open risk most exceeds its share of the buckets' capital. */
export function allocationSynthesis(a: SptRiskAccount | undefined, figs: BucketFig[]): SynthesisPart[] {
  if (!a) return ["Capital and risk, allocated separately."];
  if (a.deployedRs == null) return [`Capital deployed is unknown${a.equityUnknownReasons.length ? `: ${a.equityUnknownReasons[0]}` : "."}`];
  const head = `${rs0(a.deployedRs)} is deployed.`;
  const capTotal = figs.every((f) => f.capitalRs != null) ? figs.reduce((s, f) => s + (f.capitalRs as number), 0) : null;
  const riskTotal = figs.every((f) => f.riskRs != null) ? figs.reduce((s, f) => s + (f.riskRs as number), 0) : null;
  if (!capTotal || !riskTotal) return [head];
  let worst: { f: BucketFig; cap: number; risk: number } | null = null;
  for (const f of figs) {
    const cap = ((f.capitalRs as number) / capTotal) * 100;
    const risk = ((f.riskRs as number) / riskTotal) * 100;
    if (risk > cap && (!worst || risk - cap > worst.risk - worst.cap)) worst = { f, cap, risk };
  }
  if (!worst) return [head];
  return [`${head} `, { hi: `${worst.f.label} uses ${pctTxt(worst.cap, 0)} of it but carries ${pctTxt(worst.risk, 0)} of open risk.` }];
}

// ── capital vs risk by bucket ────────────────────────────────────────────

function Legend() {
  const dot = (c: string) => <span aria-hidden style={{ width: 8, height: 8, borderRadius: "50%", background: c, display: "inline-block" }} />;
  return (
    <span className="flex flex-wrap items-center" style={{ gap: 14 }}>
      <span className="flex items-center" style={{ gap: 6 }}>{dot(toneColor("indigo"))}<Eyebrow>Capital used</Eyebrow></span>
      <span className="flex items-center" style={{ gap: 6 }}>{dot(toneColor("amber"))}<Eyebrow>Risk used</Eyebrow></span>
    </span>
  );
}

function BucketsCard({ a, figs, d }: { a: SptRiskAccount | undefined; figs: BucketFig[]; d: PolicyDraft }) {
  const eq = a?.equityRs ?? null;
  const maxOpen = d.eff("max_open_risk_pct");
  const missingRisk = figs.filter((f) => f.riskRs == null).map((f) => f.label);
  return (
    <Card testId="pv2-al-buckets" title="Capital vs risk · by strategy bucket" right={<Legend />}>
      {!a ? <Note>The account could not be read, so bucket use is unknown.</Note> : (
        <div className="flex min-w-0 flex-col" style={{ gap: 14 }}>
          {figs.map((f) => {
            const b = BUCKETS.find((x) => x.key === f.key)!;
            const target = d.eff(b.pct);
            const capTarget = eq != null && target != null ? (eq * target) / 100 : null;
            const riskBudget = eq != null && target != null && maxOpen != null ? (eq * (maxOpen / 100) * target) / 100 : null;
            return (
              <div key={f.key} data-testid={`pv2-al-bucket-${f.key}`} className="flex min-w-0 flex-col" style={{ gap: 6 }}>
                <div className="flex min-w-0 flex-wrap items-baseline justify-between" style={{ gap: 8 }}>
                  <span style={{ fontSize: 13.5, color: "var(--cp-ink)" }}>{f.label}</span>
                  <span data-testid={`pv2-al-bucket-${f.key}-target`} style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>TARGET {pctTxt(target, 1)}</span>
                </div>
                <ValueBar used={f.capitalRs} limit={capTarget} base="indigo" levels={false} testId={`pv2-al-bucket-${f.key}-cap`} label={`${f.label} capital used of its target`} />
                <ValueBar used={f.riskRs} limit={riskBudget} testId={`pv2-al-bucket-${f.key}-risk`} label={`${f.label} risk used of its share of max open risk`} />
                <Note>Capital {rs0(f.capitalRs)} of {rs0(capTarget)} ({f.capBasis}) · risk {rs0(f.riskRs)} of {rs0(riskBudget)}{f.riskRs == null ? " (not sent)" : ` (${f.riskBasis})`}</Note>
              </div>
            );
          })}
          <div data-testid="pv2-al-bucket-reserve" className="flex min-w-0 flex-col" style={{ gap: 4, paddingTop: 10, borderTop: "1px solid var(--cp-line)" }}>
            <div className="flex min-w-0 flex-wrap items-baseline justify-between" style={{ gap: 8 }}>
              <span style={{ fontSize: 13.5, color: "var(--cp-ink)" }}>Unallocated reserve</span>
              <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", color: d.reservePct != null && d.reservePct < 5 ? toneColor("amber") : "var(--cp-ink-3)" }}>TARGET {pctTxt(d.reservePct, 1)}</span>
            </div>
            <Note>{eq != null && d.reservePct != null ? `${rs0((eq * d.reservePct) / 100)} of equity is never allocated to a new position.` : "Equity unknown, so the reserve in rupees is unknown."}</Note>
          </div>
          {missingRisk.length > 0 && (
            <Note testId="pv2-al-risk-missing">Risk used is not sent for {missingRisk.join(", ")}: the account route reports capital per bucket, not open risk per bucket, so those risk bars are empty.</Note>
          )}
          <Note>Bars use the draft targets: they move as you edit the policy, before it is saved.</Note>
        </div>
      )}
    </Card>
  );
}

// ── sector exposure ──────────────────────────────────────────────────────

function SectorsCard({ accountId, d }: { accountId: string; d: PolicyDraft }) {
  const q = useSptExposures(accountId);
  const limit = d.eff("max_sector_pct");
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Reading your sector exposure" rows={2} />;
  else if (q.isError) body = <div data-testid="pv2-al-sectors-error"><QueryProblem what="Your sector exposure" error={q.error} onRetry={() => { void q.refetch(); }} /></div>;
  else if (!q.data.bySector.length) body = <Note testId="pv2-al-sectors-empty">No open sector exposure: no paper position or pending entry has a sector on record.</Note>;
  else {
    body = (
      <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
        {q.data.bySector.map((s) => (
          <div key={s.key} data-testid="pv2-al-sector" data-sector={s.key} className="flex min-w-0 flex-col" style={{ gap: 4 }}>
            <div className="flex min-w-0 justify-between" style={{ gap: 8, fontSize: 12.5 }}>
              <span style={{ color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{s.key}</span>
              <span style={{ fontFamily: MONO, color: "var(--cp-ink-2)" }}>{pctTxt(s.pctOfEquity, 2)} of {pctTxt(limit, 1)}</span>
            </div>
            <ValueBar used={s.pctOfEquity} limit={limit} base="indigo" testId="pv2-al-sector-bar" label={`${s.key} exposure of the sector limit`} />
          </div>
        ))}
        {q.data.unclassifiedRs != null && q.data.unclassifiedRs > 0 && (
          <Note>{rs0(q.data.unclassifiedRs)} has no sector on record and counts against every sector's limit.</Note>
        )}
      </div>
    );
  }
  return (
    <Card testId="pv2-al-sectors" title="Sector exposure · % equity">
      {body}
      <Note>Bars show use of the configured sector limit.</Note>
    </Card>
  );
}

// ── F&O margin vs max loss ───────────────────────────────────────────────

function FnoAllocCard({ q, eq, d }: { q: ReturnType<typeof useFnoStructures>; eq: number | null; d: PolicyDraft }) {
  const lim = d.eff("fno_max_loss_pct");
  const perStrategy = eq != null && lim != null ? (eq * lim) / 100 : null;
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Reading your F&O structures" rows={2} />;
  else if (q.isError) body = <div data-testid="pv2-al-fno-error"><QueryProblem what="Your paper F&O structures" error={q.error} onRetry={() => { void q.refetch(); }} /></div>;
  else if (!q.data.structures.length) body = <Note testId="pv2-al-fno-empty">No open paper F&O structure on the desk, so no margin or max loss is allocated to F&O.</Note>;
  else {
    body = (
      <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
        {q.data.structures.map((s) => (
          <div key={s.id} data-testid="pv2-al-fno-row" data-id={s.id} className="flex min-w-0 flex-col" style={{ gap: 5 }}>
            <div className="flex min-w-0 flex-wrap justify-between" style={{ gap: "2px 10px", fontSize: 12.5 }}>
              <span style={{ color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{s.name}</span>
              <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums" }}>
                <span data-testid="pv2-al-fno-margin" style={{ color: toneColor("indigo") }}>{rs0(s.marginRs)}</span>
                <span style={{ color: "var(--cp-ink-3)" }}> · </span>
                <span data-testid="pv2-al-fno-maxloss" style={{ color: toneColor("amber") }}>{rs0(s.maxLossRs)}</span>
              </span>
            </div>
            <ValueBar used={s.maxLossRs} limit={perStrategy} testId="pv2-al-fno-bar" label={`${s.name} max loss of the per-strategy limit`} />
          </div>
        ))}
        {perStrategy == null && <Note>The per-strategy limit is unknown (equity or the limit is missing), so the bars are empty.</Note>}
      </div>
    );
  }
  return (
    <Card testId="pv2-al-fno" title="F&O allocation · margin vs max loss"
      right={q.data ? <Pill tone="indigo" testId="pv2-al-fno-total">Margin {rs0(q.data.totals.marginRs)}</Pill> : undefined}>
      {body}
      <Note>Indigo is margin (capital). Amber is max loss (risk). Bar shows max loss against the per-strategy limit set in Portfolio risk.</Note>
    </Card>
  );
}

// ── allocation changes, ranked by ₹ impact ───────────────────────────────

interface Change { key: string; text: string; impactRs: number | null; tone: PillTone }

const reasonOf = (r: SptRankedItem) => [...(r.allocation?.reasons.map((x) => x.message) ?? []), ...(r.sizing?.blocked.map((x) => x.message) ?? [])].join(" ") || null;
const shares = (n: number | null) => (n == null ? DASH : `${n.toLocaleString("en-IN")} share${n === 1 ? "" : "s"}`);

/** One change per allocated opportunity, in words, with its rupee effect: a reduction frees capital (mint), a block is danger, a
 *  full fit deploys capital (plain). Not allocated → no rupee figure → left out (the count says so). Largest |₹| first. */
export function changesOf(items: SptRankedItem[]): { rows: Change[]; unsized: number } {
  const rows: Change[] = [];
  let unsized = 0;
  for (const [i, r] of items.entries()) {
    const sym = r.symbol ?? "An opportunity";
    const dec = r.allocation?.decision ?? null;
    const why = reasonOf(r);
    const key = r.opportunityId ?? `${sym}-${i}`;
    if (dec === "ALLOCATION_REDUCED") {
      const freed = r.sizing?.capitalRs != null && r.allocation?.capitalRs != null ? r.sizing.capitalRs - r.allocation.capitalRs : null;
      rows.push({ key, tone: "mint", impactRs: freed,
        text: `${sym} is reduced from ${shares(r.allocation?.requestedQty ?? r.sizing?.quantity ?? null)} to ${shares(r.allocation?.quantity ?? null)} to fit the risk budget${why ? `: ${why}` : "."}` });
    } else if (dec === "ALLOCATION_REJECTED") {
      rows.push({ key, tone: "danger", impactRs: r.sizing?.capitalRs ?? r.allocation?.capitalRs ?? null, text: `${sym} is blocked${why ? `: ${why}` : " by the allocation limits."}` });
    } else if (dec === "ALLOCATION_APPROVED") {
      rows.push({ key, tone: "plain", impactRs: r.allocation?.capitalRs ?? null, text: `${sym} fits in full at ${shares(r.allocation?.quantity ?? null)}.` });
    } else unsized += 1;
  }
  const mag = (c: Change) => (c.impactRs == null ? -1 : Math.abs(c.impactRs));
  rows.sort((x, y) => mag(y) - mag(x));
  return { rows, unsized };
}

function ChangesCard({ accountId }: { accountId: string }) {
  const q = useSptRanked(accountId);
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Reading the allocation of the qualified opportunities" rows={2} />;
  else if (q.isError) body = <div data-testid="pv2-al-changes-error"><QueryProblem what="The allocation changes" error={q.error} onRetry={() => { void q.refetch(); }} /></div>;
  else {
    const { rows, unsized } = changesOf(q.data.items);
    body = rows.length ? (
      <>
        <ol className="m-0 flex min-w-0 flex-col p-0" style={{ listStyle: "none", gap: 10 }}>
          {rows.map((c, i) => (
            <li key={c.key} data-testid="pv2-al-change" data-tone={c.tone} className="grid min-w-0" style={{ gridTemplateColumns: "26px minmax(0,1fr) auto", gap: 10, alignItems: "baseline" }}>
              <span style={{ fontFamily: MONO, fontSize: 11, color: "var(--cp-ink-3)" }}>{String(i + 1).padStart(2, "0")}</span>
              <span data-testid="pv2-al-change-text" style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{c.text}</span>
              <span data-testid="pv2-al-change-impact" style={{ fontFamily: MONO, fontSize: 12, color: toneColor(c.tone), fontVariantNumeric: "tabular-nums" }}>{rsC(c.impactRs)}</span>
            </li>
          ))}
        </ol>
        {unsized > 0 && <Note>{unsized} more {unsized === 1 ? "opportunity was" : "opportunities were"} not allocated, so {unsized === 1 ? "it has" : "they have"} no rupee figure.</Note>}
      </>
    ) : (
      <Note testId="pv2-al-changes-empty">
        No allocated opportunity right now, so there is no allocation change to rank.{unsized ? ` ${unsized} ${unsized === 1 ? "opportunity was" : "opportunities were"} not allocated.` : ""}
      </Note>
    );
  }
  return (
    <Card testId="pv2-al-changes" title="Allocation changes · ranked by ₹ impact">
      {body}
      <Note>Mint frees capital or lowers risk; red is blocked. Nothing here is ordered.</Note>
    </Card>
  );
}

// ── the view ─────────────────────────────────────────────────────────────

export function PaperAllocation({ accountId }: { accountId: string | null }) {
  const [narrow, ref] = useNarrow(900);
  const d = usePolicyDraft(accountId);
  const acc = useSptRiskAccount(accountId);
  const fno = useFnoStructures(!!accountId);
  const a = acc.data;
  const figs = bucketFigs(a, fno.data);
  const eq = a?.equityRs ?? null;
  const maxOpen = d.eff("max_open_risk_pct");
  const riskCap = eq != null && maxOpen != null ? (eq * maxOpen) / 100 : null;
  const left = riskCap != null && a?.openRisk.rs != null ? riskCap - a.openRisk.rs : null;
  const perTrade = d.eff("per_trade_risk_pct");
  const perTradeRs = eq != null && perTrade != null ? (eq * perTrade) / 100 : d.policy?.derived.perTradeRiskRs ?? null;
  const sub = <>Per-trade risk of {rs0(perTradeRs)} per trade on {rsC(eq)} equity. Bucket targets always total 100%.</>;

  if (!accountId) {
    return (
      <div data-testid="pv2-allocation" className="flex min-w-0 flex-col" style={{ gap: 18 }}>
        <SectionHeader testId="pv2-al-head" eyebrow="Capital allocation" synthesis={["Capital and risk, allocated separately."]} prose={PROSE} />
        <AccountMissing what="there is nothing to allocate" />
      </div>
    );
  }
  return (
    <div ref={ref} data-testid="pv2-allocation" className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      <SectionHeader testId="pv2-al-head" eyebrow="Capital allocation" synthesis={allocationSynthesis(a, figs)} prose={PROSE} />
      {acc.isPending && <LoadingBlock label="Reading your account" rows={2} />}
      {acc.isError && <div data-testid="pv2-al-error"><QueryProblem what="Your account's capital and risk" error={acc.error} onRetry={() => { void acc.refetch(); }} /></div>}
      {a && (
        <KpiGrid min={200} testId="pv2-al-kpis">
          <Kpi testId="pv2-al-kpi-equity" label="Account equity" value={rs0(a.equityRs)} sub={`cash ${rs0(a.cashRs)}`} />
          <Kpi testId="pv2-al-kpi-deployed" label="Deployed" value={rs0(a.deployedRs)} sub={`${pctTxt(ofPct(a.deployedRs, a.equityRs), 1)} of equity`} />
          <Kpi testId="pv2-al-kpi-reserved" label="Reserved · pending" value={rs0(a.reservedRs)} sub={`${a.pending.length} order${a.pending.length === 1 ? "" : "s"}`} />
          <Kpi testId="pv2-al-kpi-risk-left" label="Risk budget left" value={rs0(left)} tone={left != null && left < 0 ? "danger" : undefined}
            sub={`of ${pctTxt(maxOpen, 1)} · ${rs0(riskCap)}`} />
        </KpiGrid>
      )}
      <PolicyCard panel="allocation" d={d} sub={sub} narrow={narrow} />
      <Split cols="minmax(0,1.4fr) minmax(0,1fr)" narrow={narrow} testId="pv2-al-grid">
        <BucketsCard a={a} figs={figs} d={d} />
        <div className="flex min-w-0 flex-col" style={{ gap: 16 }}>
          <SectorsCard accountId={accountId} d={d} />
          <FnoAllocCard q={fno} eq={eq} d={d} />
          <ChangesCard accountId={accountId} />
        </div>
      </Split>
      <Note>Paper only: nothing here is sent to a broker. Real holdings are not counted.</Note>
    </div>
  );
}
