/**
 * Portfolio ledger — every holding, with the ones that need a look first, and
 * the form that corrects one.
 *
 * It carries what the original holdings table shows (components/shared/
 * HoldingsTable): the instrument-type filter with counts, search by name or
 * ISIN, a choice of order, and for each holding its category, value, weight,
 * gain, XIRR, return against its benchmark and the engine's verdict.
 *
 * Data:
 *   holdings                   GET /api/portfolio/holdings-enriched   (passed in)
 *   where each one came from   GET /api/portfolio/holdings            (useHoldingRecords)
 *   correct a holding          PUT /api/portfolio/holdings/{id}       (useCorrectHolding)
 *
 * A correction changes the average buy price, the purchase date or the number
 * of units of one holding. It is saved to the holdings on record and the
 * figures are worked out again. A newer statement replaces the holdings,
 * corrections included, and no log of corrections is kept (the screen says so).
 */
import { useId, useMemo, useState, type ReactNode } from "react";
import { Btn, ErrorBlock, Pill, Section, TONE_COLOR, errorSentence, fmtDate, fmtINR, fmtNum, fmtPct, signTone, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { holdingBadge, humanise, isStock, isoDay, loadError, str, type EnrichedHolding } from "./data";
import { sourceLabel, useCorrectHolding, useHoldingRecords, type HoldingCorrection } from "./ledger-data";
import { HoldingIcon } from "./names";
import { FIELD_STYLE, ShowAll } from "./parts";

const HOLDING_LIMIT = 10;
const quiet = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;
const caption = { fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--cp-ink-4)" } as const;

// ── what needs a look ────────────────────────────────────────────────────

interface Flag {
  label: string;
  tone: Tone;
  reason: string;
  /** Lower sorts first. */
  rank: number;
}

/** What needs a look: the engine's verdict on the holding, or a gap in its record. */
function flagFor(h: EnrichedHolding): Flag | null {
  const badge = holdingBadge(h);
  if (badge?.action === "EXIT") return { label: "Exit signal", tone: "danger", reason: badge.reason, rank: 0 };
  if (h.invested_rs == null) return { label: "No cost basis", tone: "amber", reason: "No purchase price on record, so gain and XIRR can’t be worked out.", rank: 1 };
  if (badge?.action === "SWITCH") return { label: "Switch signal", tone: "amber", reason: badge.reason, rank: 2 };
  if (badge?.action === "REVIEW") return { label: "Needs review", tone: "amber", reason: badge.reason, rank: 3 };
  return null;
}

// ── instrument types (the original table's tabs) ─────────────────────────

type TypeTab = "all" | "equity" | "mutual_fund" | "etf" | "gold_sgb";

const TYPE_TABS: Array<{ id: TypeTab; label: string }> = [
  { id: "all", label: "All" },
  { id: "equity", label: "Stocks" },
  { id: "mutual_fund", label: "Mutual funds" },
  { id: "etf", label: "ETFs" },
  { id: "gold_sgb", label: "Gold and SGB" },
];

/** A sovereign gold bond arrives as gold or as a bond, so its name decides. Bonds and deposits show under "All" only. */
function typeTabOf(h: EnrichedHolding): Exclude<TypeTab, "all"> | "other" {
  const at = h.asset_type.toLowerCase();
  if (/sovereign gold|\bsgb\b|government of india/.test(h.name.toLowerCase()) || at === "gold") return "gold_sgb";
  if (at === "etf") return "etf";
  if (at === "mutual_fund") return "mutual_fund";
  if (at === "equity" || at === "stock") return "equity";
  return "other";
}

const KIND: Record<string, string> = { mutual_fund: "Mutual fund", etf: "ETF", equity: "Stock", stock: "Stock", gold: "Gold", bond: "Bond", fd: "Fixed deposit" };

type SortId = "flagged" | "value" | "gain" | "xirr" | "weight";

const SORTS: Array<{ id: SortId; label: string }> = [
  { id: "flagged", label: "Needs a look first" },
  { id: "value", label: "Largest value" },
  { id: "gain", label: "Highest gain" },
  { id: "xirr", label: "Highest XIRR" },
  { id: "weight", label: "Largest weight" },
];

const SORT_VALUE: Record<Exclude<SortId, "flagged">, (h: EnrichedHolding) => number> = {
  value: (h) => h.value_rs ?? -Infinity,
  gain: (h) => h.pnl_pct ?? -Infinity,
  xirr: (h) => h.xirr_pct ?? -Infinity,
  weight: (h) => h.weight_pct ?? -Infinity,
};

// ── correct a holding ────────────────────────────────────────────────────

interface Change {
  label: string;
  from: string;
  to: string;
}

/** A typed number, or null when the box is empty or not a number. */
function typed(v: string): number | null {
  const n = Number(v);
  return v.trim() !== "" && Number.isFinite(n) ? n : null;
}

function CorrectionForm({ h, onClose, onSaved }: { h: EnrichedHolding; onClose: () => void; onSaved: () => void }) {
  const save = useCorrectHolding();
  const stock = isStock(h);
  const unit = stock ? "share" : "unit";
  const hadPrice = h.buy_price != null && h.buy_price > 0;
  const hadDate = str(h.buy_date).slice(0, 10);
  const [price, setPrice] = useState(hadPrice ? String(h.buy_price) : "");
  const [date, setDate] = useState(hadDate);
  const [qty, setQty] = useState(String(h.quantity));
  const [review, setReview] = useState(false);
  const priceId = useId();
  const dateId = useId();
  const qtyId = useId();
  const today = isoDay(new Date());

  const priceN = typed(price);
  const qtyN = typed(qty);
  const correction: HoldingCorrection = { holdingId: h.holding_id };
  const changes: Change[] = [];
  const problems: string[] = [];
  if (price.trim() !== "" && (priceN == null || priceN <= 0)) problems.push("The buy price must be a number above zero.");
  if (qtyN == null || qtyN <= 0) problems.push(`The number of ${unit}s must be above zero.`);
  if (date && date > today) problems.push("The purchase date cannot be in the future.");
  if (priceN != null && priceN > 0 && priceN !== (hadPrice ? h.buy_price : null)) {
    correction.buyPrice = priceN;
    changes.push({ label: `Average buy price per ${unit}`, from: hadPrice ? fmtINR(h.buy_price) : "Not on record", to: fmtINR(priceN) });
  }
  if (date && date !== hadDate) {
    correction.buyDate = date;
    changes.push({ label: "Purchase date", from: hadDate ? fmtDate(hadDate) : "Not on record", to: fmtDate(date) });
  }
  if (qtyN != null && qtyN > 0 && qtyN !== h.quantity) {
    correction.quantity = qtyN;
    changes.push({ label: stock ? "Shares" : "Units", from: fmtNum(h.quantity, 3), to: fmtNum(qtyN, 3) });
  }
  const newQty = correction.quantity ?? h.quantity;
  const newPrice = correction.buyPrice ?? (hadPrice ? h.buy_price ?? null : null);
  const investedAfter = newPrice != null ? newQty * newPrice : null;
  const canReview = problems.length === 0 && changes.length > 0;
  const why = errorSentence(loadError(save.error));

  return (
    <div data-testid="ledger-correct-form" className="flex flex-col" style={{ flex: "1 1 100%", gap: 12, padding: 14, borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)" }}>
      <span className="cp-eyebrow">Correct this holding</span>
      {!review ? (
        <>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,180px),1fr))", gap: 12 }}>
            <div className="flex flex-col" style={{ gap: 4 }}>
              <label htmlFor={priceId} style={quiet}>Average buy price per {unit} (₹)</label>
              <input id={priceId} data-testid="ledger-correct-price" type="number" inputMode="decimal" min="0" step="any" value={price} onChange={(e) => setPrice(e.target.value)} style={FIELD_STYLE} />
            </div>
            <div className="flex flex-col" style={{ gap: 4 }}>
              <label htmlFor={dateId} style={quiet}>Purchase date</label>
              <input id={dateId} data-testid="ledger-correct-date" type="date" max={today} value={date} onChange={(e) => setDate(e.target.value)} style={FIELD_STYLE} />
            </div>
            <div className="flex flex-col" style={{ gap: 4 }}>
              <label htmlFor={qtyId} style={quiet}>{stock ? "Shares" : "Units"} held</label>
              <input id={qtyId} data-testid="ledger-correct-quantity" type="number" inputMode="decimal" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)} style={FIELD_STYLE} />
            </div>
          </div>
          {problems.map((p) => <span key={p} role="alert" data-testid="ledger-correct-problem" style={{ fontSize: 12, color: "var(--cp-danger)" }}>{p}</span>)}
          <span style={quiet}>Change only what the statement got wrong. For several purchases, enter the average price paid and the date of the first one.</span>
          <div className="flex flex-wrap" style={{ gap: 8 }}>
            <Btn variant="primary" data-testid="ledger-correct-review" disabled={!canReview} onClick={() => setReview(true)}>Review the change</Btn>
            <Btn variant="ghost" data-testid="ledger-correct-cancel" onClick={onClose}>Cancel</Btn>
          </div>
        </>
      ) : (
        <>
          <div data-testid="ledger-correct-summary" className="flex flex-col" style={{ gap: 6, fontSize: 13, color: "var(--cp-ink-2)" }}>
            {changes.map((c) => (
              <span key={c.label}>{c.label}: <span className="cp-num">{c.from}</span> → <span className="cp-num" style={{ color: "var(--cp-ink)" }}>{c.to}</span></span>
            ))}
            {investedAfter != null && <span>Invested amount becomes <span data-testid="ledger-correct-invested" className="cp-num" style={{ color: "var(--cp-ink)" }}>{fmtINR(investedAfter)}</span></span>}
          </div>
          <span style={quiet}>
            Saving changes this holding on record straight away, and your gain, XIRR and the analyses built on them are worked out again.
            The next statement you import replaces your holdings, this correction included. No log of corrections is kept.
          </span>
          <div className="flex flex-wrap" style={{ gap: 8 }}>
            <Btn variant="primary" data-testid="ledger-correct-save" disabled={save.isPending} onClick={() => save.mutate(correction, { onSuccess: onSaved })}>
              {save.isPending ? "Saving…" : "Save the correction"}
            </Btn>
            <Btn variant="ghost" data-testid="ledger-correct-back" disabled={save.isPending} onClick={() => { save.reset(); setReview(false); }}>Back</Btn>
          </div>
          {save.isError && <span role="alert" data-testid="ledger-correct-error" style={{ fontSize: 12, color: "var(--cp-danger)" }}>The correction didn’t save{why ? ` — ${why}` : ""}. Nothing was changed. Try again.</span>}
        </>
      )}
    </div>
  );
}

// ── the list ─────────────────────────────────────────────────────────────

function Fig({ k, children, testId, width = 64 }: { k: string; children: ReactNode; testId?: string; width?: number }) {
  return (
    <span className="flex flex-col items-end" style={{ gap: 2, minWidth: width }}>
      <span data-testid={testId} className="cp-num" style={{ fontSize: 13 }}>{children}</span>
      <span style={caption}>{k}</span>
    </span>
  );
}

function Signed({ value, text }: { value: number | null | undefined; text: string }) {
  return <span style={{ color: value == null || value === 0 ? undefined : TONE_COLOR[signTone(value)] }}>{text}</span>;
}

export function Holdings({ holdings }: { holdings: EnrichedHolding[] }) {
  const { ask } = useCopilotShell();
  const records = useHoldingRecords();
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<TypeTab>("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortId>("flagged");
  const [editing, setEditing] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const searchId = useId();
  const sortId = useId();

  const counts = useMemo(() => {
    const c: Record<TypeTab | "other", number> = { all: holdings.length, equity: 0, mutual_fund: 0, etf: 0, gold_sgb: 0, other: 0 };
    for (const h of holdings) c[typeTabOf(h)] += 1;
    return c;
  }, [holdings]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = holdings
      .filter((h) => tab === "all" || typeTabOf(h) === tab)
      .filter((h) => !q || h.name.toLowerCase().includes(q) || str(h.isin).toLowerCase().includes(q))
      .map((h) => ({ h, flag: flagFor(h) }));
    return sort === "flagged"
      ? list.sort((a, b) => (a.flag?.rank ?? 9) - (b.flag?.rank ?? 9) || (b.h.value_rs ?? 0) - (a.h.value_rs ?? 0))
      : list.sort((a, b) => {
        // A holding without the figure sorts last; two without it keep their order.
        const va = SORT_VALUE[sort](a.h);
        const vb = SORT_VALUE[sort](b.h);
        return va === vb ? 0 : vb - va;
      });
  }, [holdings, tab, search, sort]);

  const flagged = rows.filter((r) => r.flag).length;
  const visible = expanded ? rows : rows.slice(0, HOLDING_LIMIT);
  const tabs = TYPE_TABS.filter((t) => t.id === "all" || counts[t.id] > 0);

  return (
    <Section
      flush
      title={<>Holdings · {visible.length} of {rows.length}</>}
      note={<span data-testid="ledger-flagged-count">{flagged} flagged</span>}
    >
      <div className="flex flex-col" style={{ gap: 10, padding: "12px 16px", borderBottom: "1px solid var(--cp-line)" }}>
        {tabs.length > 2 && (
          <div role="group" aria-label="Show holdings of one type" className="flex flex-wrap" style={{ gap: 8 }}>
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                className="cp-chip"
                data-testid={`ledger-filter-${t.id}`}
                aria-pressed={tab === t.id}
                onClick={() => { setTab(t.id); setExpanded(false); }}
                style={tab === t.id ? { borderColor: "var(--mint-line)", color: "var(--mint)" } : undefined}
              >
                {t.label} · {counts[t.id]}
              </button>
            ))}
          </div>
        )}
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,220px),1fr))", gap: 10 }}>
          <div className="flex flex-col" style={{ gap: 4 }}>
            <label htmlFor={searchId} style={quiet}>Search by name or ISIN</label>
            <input id={searchId} data-testid="ledger-search" type="search" value={search} onChange={(e) => { setSearch(e.target.value); setExpanded(false); }} style={FIELD_STYLE} />
          </div>
          <div className="flex flex-col" style={{ gap: 4 }}>
            <label htmlFor={sortId} style={quiet}>Order</label>
            <select id={sortId} data-testid="ledger-sort" value={sort} onChange={(e) => setSort(SORTS.find((s) => s.id === e.target.value)?.id ?? "flagged")} style={FIELD_STYLE}>
              {SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </div>
        </div>
        {records.isError && <ErrorBlock title="Where each holding came from didn’t load" error={loadError(records.error)} onRetry={() => records.refetch()} />}
      </div>

      <div data-testid="ledger-holdings">
        {visible.length === 0 && <div data-testid="ledger-holdings-none" style={{ padding: 16, fontSize: 13, color: "var(--cp-ink-3)" }}>No holding matches.</div>}
        {visible.map(({ h, flag }) => {
          const kind = KIND[h.asset_type.toLowerCase()] ?? humanise(h.asset_type);
          const qty = `${fmtNum(h.quantity, Number.isInteger(h.quantity) ? 0 : 3)} ${isStock(h) ? "sh" : "units"}`;
          const source = sourceLabel(records.data?.[h.holding_id]);
          const badge = holdingBadge(h);
          const bench = h.benchmark_delta ?? null;
          const horizon = str(h.benchmark_delta_horizon).toUpperCase();
          return (
            <div key={h.holding_id} data-testid="ledger-holding" className="flex flex-wrap items-center" style={{ gap: "10px 16px", padding: "13px 16px", borderBottom: "1px solid var(--cp-line)" }}>
              <div className="flex min-w-0 items-start" style={{ flex: "1 1 240px", gap: 10 }}>
                <HoldingIcon name={h.name} assetType={h.asset_type} symbol={h.nse_symbol} size={28} reserve />
                <div className="flex min-w-0 flex-col" style={{ gap: 3 }}>
                  <span data-testid="ledger-holding-name" style={{ fontSize: 14, fontWeight: 500, overflowWrap: "anywhere" }}>{h.name}</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>
                    {[kind, qty, str(h.category)].filter(Boolean).join(" · ")}
                  </span>
                  {source && <span data-testid="ledger-holding-source" style={quiet}>From: {source}</span>}
                  {flag?.reason && <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{flag.reason}</span>}
                  {saved === h.holding_id && <span role="status" data-testid="ledger-correct-saved" style={{ fontSize: 12, color: "var(--mint)" }}>Correction saved. The figures have been worked out again.</span>}
                </div>
              </div>
              <Fig k="Value" testId="ledger-holding-value" width={72}>{fmtINR(h.value_rs, { compact: true })}</Fig>
              <Fig k="Weight" width={48}><span style={{ color: "var(--cp-ink-3)" }}>{fmtPct(h.weight_pct)}</span></Fig>
              <Fig k="Gain" testId="ledger-holding-gain"><Signed value={h.pnl_pct} text={fmtPct(h.pnl_pct, { signed: true })} /></Fig>
              <Fig k="XIRR" testId="ledger-holding-xirr">{fmtPct(h.xirr_pct)}</Fig>
              <Fig k={horizon ? `vs index · ${horizon}` : "vs index"} testId="ledger-holding-benchmark" width={76}>
                {bench == null ? "—" : <Signed value={bench} text={`${bench > 0 ? "+" : bench < 0 ? "−" : ""}${Math.abs(bench).toFixed(1)} pts`} />}
              </Fig>
              {flag
                ? <Pill tone={flag.tone} title={flag.reason || undefined}>{flag.label}</Pill>
                : badge && <span data-testid="ledger-holding-verdict"><Pill title={badge.reason || undefined}>{humanise(badge.action)}</Pill></span>}
              <span className="flex items-center" style={{ gap: 12, marginLeft: "auto" }}>
                <button
                  type="button"
                  data-testid="ledger-correct"
                  aria-expanded={editing === h.holding_id}
                  aria-label={`Correct ${h.name}`}
                  onClick={() => { setSaved(null); setEditing((v) => (v === h.holding_id ? null : h.holding_id)); }}
                  style={{ fontSize: 13, color: "var(--cp-ink-2)", background: "none", border: 0, padding: 0, cursor: "pointer" }}
                >
                  {h.invested_rs == null ? "Add cost basis" : "Correct"}
                </button>
                <button
                  type="button"
                  aria-label={`Ask about ${h.name}`}
                  onClick={() => ask(flag
                    ? `${h.name} is flagged “${flag.label}” in my portfolio${flag.reason ? ` (${flag.reason})` : ""}. What should I do about it?`
                    : `Tell me about my holding in ${h.name}: how it has done and whether to keep it.`)}
                  style={{ fontSize: 13, color: "var(--cp-ink-2)", background: "none", border: 0, padding: 0, cursor: "pointer" }}
                >
                  Ask ›
                </button>
              </span>
              {editing === h.holding_id && (
                <CorrectionForm h={h} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); setSaved(h.holding_id); }} />
              )}
            </div>
          );
        })}
      </div>
      <ShowAll total={rows.length} limit={HOLDING_LIMIT} expanded={expanded} onToggle={() => setExpanded((v) => !v)} noun="holdings" />
    </Section>
  );
}
