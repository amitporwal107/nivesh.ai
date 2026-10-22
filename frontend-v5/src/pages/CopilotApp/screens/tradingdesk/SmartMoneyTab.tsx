/**
 * Smart trading desk · 06 Smart Money Movement.
 *
 * Who is building and trimming positions, taken only from what is actually disclosed:
 *   Flows      market-wide FII/DII cash, per period and cumulative (NOT stock-specific)
 *   Sectors    disclosed month-on-month MF holdings change by industry, valued at VWAP
 *   Breadth    how many names carry a disclosed change, and how many rest on a single AMC
 *   Scanner    one row per Nifty 500 stock with the evidence behind it
 *   Feeds      each source's status, and the newest DATA period as distinct from the last ingest run
 *
 * This screen shows EVIDENCE, never a verdict. It has no accumulation score, no ranking by one and
 * no hit rate, because the validation study returned INCONCLUSIVE and no promotion was ever
 * approved — `breadth.validatedStudy` is the live read of that and drives the footer in words
 * rather than being hardcoded. The reasons per omission are in smart-money-data.ts.
 *
 * Reads only. Nothing here places an order or writes anything.
 */
import { useMemo, useState } from "react";
import {
  Column, DataTable, EmptyBlock, ErrorBlock, Eyebrow, Footnote, LoadingBlock, Pill, Screen,
  ScreenHeader, Section, Tiles, fmtDate, fmtNum, signTone,
} from "../../components/ui";
import { useDesk } from "./context";
import { TrustLine } from "./trust";
import {
  EVIDENCE_LABEL, EVIDENCE_NOTE, FLOW_WINDOWS, type EvidenceClass, type FlowWindow,
  type ScannerRow, dataAgeDays, evidenceOf, ingestAheadOfData, useSmartMoney,
} from "./smart-money-data";

/** ₹ crore, signed, with the sign carried in words for screen readers rather than colour alone. */
function Cr({ v }: { v: number | null }) {
  if (v == null) return <span style={{ color: "var(--cp-ink-4)" }}>—</span>;
  const tone = signTone(v);
  return (
    <span style={{ color: `var(--${tone === "ink" ? "cp-ink-2" : tone})` }}>
      {v > 0 ? "+" : v < 0 ? "−" : ""}₹{fmtNum(Math.abs(v))} cr
      <span className="sr-only">{v > 0 ? " net bought" : v < 0 ? " net sold" : " flat"}</span>
    </span>
  );
}

const CLASS_TONE: Record<EvidenceClass, "mint" | "indigo" | "amber" | "ink"> = {
  D: "mint", A: "mint", B: "indigo", C: "amber", none: "ink",
};

export default function SmartMoneyTab() {
  const { persona } = useDesk();
  const [window_, setWindow] = useState<FlowWindow>("3M");
  const [rising, setRising] = useState(true);
  const feed = useSmartMoney(window_, rising);
  const { feeds, flows, sectors, breadth, scanner } = feed;

  const today = useMemo(() => new Date(), []);

  if (feed.status === "loading") return <Screen testId="screen-desk-smart-money"><LoadingBlock label="Reading disclosed holdings" rows={5} /></Screen>;
  if (feed.status === "error") {
    return (
      <Screen testId="screen-desk-smart-money">
        <ErrorBlock title="Smart Money didn’t load" error={feed.error} onRetry={feed.refetch} />
      </Screen>
    );
  }

  const m = breadth?.metrics ?? null;
  // The honest date is the disclosure's, not the compute date: they are weeks apart.
  const disclosureAge = dataAgeDays(breadth?.disclosureAsOf ?? null, today);
  const scannerRows = scanner?.rows ?? [];

  const cols: Column<ScannerRow>[] = [
    {
      key: "symbol", header: "Stock", width: "minmax(0,1.5fr)",
      render: (r) => (
        <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
          <span style={{ fontWeight: 600, color: "var(--cp-ink)" }}>{r.symbol}</span>
          <span style={{ fontSize: 11, color: "var(--cp-ink-4)", overflow: "hidden", textOverflow: "ellipsis" }}>{r.industry ?? "—"}</span>
        </span>
      ),
    },
    {
      key: "evidence", header: "Evidence", width: "minmax(0,1.3fr)",
      render: (r) => {
        const c = evidenceOf(r);
        return <Pill tone={CLASS_TONE[c]} title={EVIDENCE_NOTE[c]}>{EVIDENCE_LABEL[c]}</Pill>;
      },
    },
    {
      key: "mf", header: "Holding change", align: "right", num: true, width: "minmax(0,1fr)",
      render: (r) => (r.mfSharesPctChg == null ? "—" : `${r.mfSharesPctChg > 0 ? "+" : ""}${r.mfSharesPctChg}%`),
    },
    {
      key: "breadth", header: "Schemes · AMCs", align: "right", num: true, width: "minmax(0,1fr)",
      render: (r) => (r.schemesUp == null ? "—" : `${fmtNum(r.schemesUp)}↑ / ${fmtNum(r.schemesDn)}↓ · ${fmtNum(r.amcsUp)}`),
    },
    {
      key: "fii", header: "FII pp (QoQ)", align: "right", num: true, width: "minmax(0,0.9fr)",
      render: (r) => (r.fiiDeltaPp == null
        ? <span style={{ color: "var(--cp-ink-4)" }} title="Not disclosed for this stock in both quarters">n/d</span>
        : `${r.fiiDeltaPp > 0 ? "+" : ""}${r.fiiDeltaPp}`),
    },
    {
      key: "deals", header: "Deals (90d)", align: "right", num: true, width: "minmax(0,1.1fr)",
      render: (r) => {
        if (!r.dealsChecked) return <span style={{ color: "var(--cp-ink-4)" }} title="This stock was never queried for deals — the ingest is deliberately partial">Not checked</span>;
        if (r.dealNetQty == null || r.dealNetQty === 0) {
          return r.transferDays && r.transferDays > 0
            ? <span title="Every leg matched an opposite leg: an ownership transfer, not net demand">Net 0 · transfer</span>
            : <span style={{ color: "var(--cp-ink-3)" }}>No deals</span>;
        }
        return <span>{r.dealNetQty > 0 ? "+" : "−"}{fmtNum(Math.abs(r.dealNetQty))}</span>;
      },
    },
    {
      key: "deliv", header: "Delivery vs base", align: "right", num: true, width: "minmax(0,1fr)",
      render: (r) => (r.delivVsBasePp == null ? "—" : `${r.delivVsBasePp > 0 ? "+" : ""}${r.delivVsBasePp} pp`),
    },
  ];

  return (
    <Screen testId="screen-desk-smart-money">
      <ScreenHeader
        eyebrow={<Eyebrow>06 · Smart Money Movement</Eyebrow>}
        title={persona === "investor" ? "Who is buying and selling" : "Smart Money Movement"}
        pills={
          <>
            <Pill tone="indigo" title="These are the disclosed holdings of the 11 AMCs that report, not all institutional activity">11 disclosing AMCs</Pill>
            {disclosureAge != null && (
              <Pill tone={disclosureAge > 45 ? "amber" : "ink"} title="Monthly portfolio disclosure is published in arrears, so this screen is weeks behind by construction">
                Disclosed {fmtDate(breadth?.disclosureAsOf)} · {disclosureAge}d ago
              </Pill>
            )}
            {!breadth?.validatedStudy && <Pill tone="amber" title="No promotion decision is on record, so nothing here is scored or ranked by a model">Evidence only · not scored</Pill>}
          </>
        }
        sub={persona === "investor"
          ? "What fund houses actually filed they bought or sold, plus the deals the exchanges published. It is a record of who moved, not advice to follow them."
          : "Disclosed holdings change, disclosed deal legs net of transfers, and market proxies — each labelled by what kind of evidence it is."}
      />

      {feed.failed.length > 0 && (
        <div data-testid="desk-smart-money-partial" role="status" style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 10, border: "1px solid var(--amber)", background: "var(--amber-soft)", fontSize: 12.5, color: "var(--cp-ink-2)" }}>
          Partial: {feed.failed.join(", ")} didn’t answer. Everything else below is current.{" "}
          <button type="button" onClick={feed.refetch} style={{ border: 0, background: "transparent", color: "var(--mint)", cursor: "pointer", font: "inherit", textDecoration: "underline" }}>Retry</button>
        </div>
      )}

      {/* ── market-wide flows ── */}
      <Section
        title="Market-wide flows"
        note={
          <span className="flex items-center" style={{ gap: 8 }}>
            <Pill tone="ink" title="This panel is the whole cash market. It says nothing about any single stock.">Market-wide · not stock-specific</Pill>
            <span role="tablist" aria-label="Flow window" className="flex" style={{ gap: 4 }}>
              {FLOW_WINDOWS.map((w) => (
                <button
                  key={w} type="button" role="tab" aria-selected={w === window_}
                  data-testid={`desk-smart-money-window-${w}`}
                  onClick={() => setWindow(w)}
                  className="cp-num"
                  style={{
                    padding: "3px 9px", borderRadius: 999, fontSize: 11, cursor: "pointer",
                    border: `1px solid ${w === window_ ? "var(--mint)" : "var(--cp-line)"}`,
                    background: w === window_ ? "var(--mint-soft)" : "transparent",
                    color: w === window_ ? "var(--cp-ink)" : "var(--cp-ink-3)",
                  }}
                >{w}</button>
              ))}
            </span>
          </span>
        }
      >
        {flows == null || flows.rows.length === 0 ? (
          <EmptyBlock title="No flow rows in this window" body="The feed answered with an empty window rather than an older one." />
        ) : (
          <>
            <Tiles items={[
              { k: `FII net · ${flows.window}`, v: <Cr v={flows.fiiNetCr} /> },
              { k: `DII net · ${flows.window}`, v: <Cr v={flows.diiNetCr} /> },
              { k: flows.grain === "monthly" ? "Months" : "Sessions", v: fmtNum(flows.rows.length) },
              { k: "Window from", v: fmtDate(flows.start) },
            ]} />
            <Footnote>
              {flows.grain === "monthly"
                ? "Monthly grain: the daily series begins 2026-04-01, so a one-year window is served from monthly rows. The two grains are never added together."
                : "Daily grain, cash segment only."}
            </Footnote>
          </>
        )}
        <TrustLine source={flows?.source ?? "nidp.fii_dii_flows"} asOf={fmtDate(flows?.asOf)} mode="eod" maker="reported" testId="desk-smart-money-flows-trust" />
      </Section>

      {/* ── breadth ── */}
      <Section title="Disclosed evidence breadth" note={<span className="cp-mono-note">on the point-in-time series</span>}>
        {m == null ? (
          <EmptyBlock title="No scored names" body="Nothing was evaluated on the latest date." />
        ) : (
          <Tiles items={[
            { k: "Names evaluated", v: fmtNum(m.evaluated) },
            { k: "Holdings rose", v: fmtNum(m.disclosedRising), tone: "mint" },
            { k: "Holdings fell", v: fmtNum(m.disclosedFalling), tone: "danger" },
            { k: "Rose · confirmed by proxy", v: fmtNum(m.risingDirectAndProxy) },
            { k: "Rose · disclosure only", v: fmtNum(m.risingDirectOnly) },
            { k: "One AMC only", v: fmtNum(m.singleAmc), tone: "amber" },
          ]} />
        )}
        <Footnote>
          “One AMC only” counts names whose whole signal rests on a single fund house — a large minority, and
          weaker evidence than the same change across several. A proxy move on its own is never called accumulation:
          delivery and volume do not disclose who bought.
        </Footnote>
        <TrustLine source="nidp.smart_money_scores_daily" asOf={fmtDate(breadth?.disclosureAsOf)} mode="historical" maker="reported" testId="desk-smart-money-breadth-trust" />
      </Section>

      {/* ── sectors ── */}
      <Section
        title="Where the disclosed money moved"
        note={sectors?.previousMonth ? <span className="cp-mono-note">{fmtDate(sectors.previousMonth)} → {fmtDate(sectors.asOf)}</span> : null}
      >
        <DataTable
          rows={sectors?.rows ?? []}
          rowKey={(r) => r.industry}
          empty="No disclosed sector change for this month pair."
          columns={[
            { key: "industry", header: "Industry", width: "minmax(0,1.8fr)", render: (r) => r.industry },
            { key: "net", header: "Net value", align: "right", num: true, render: (r) => <Cr v={r.netValueCr} /> },
            { key: "stocks", header: "Stocks", align: "right", num: true, render: (r) => (r.stocksPriced === r.stocks ? fmtNum(r.stocks) : `${fmtNum(r.stocksPriced)} / ${fmtNum(r.stocks)}`) },
            { key: "schemes", header: "Schemes ↑ / ↓", align: "right", num: true, render: (r) => `${fmtNum(r.schemesUp)} / ${fmtNum(r.schemesDn)}` },
          ]}
        />
        <Footnote>
          Shares bought or sold valued at the disclosure month’s VWAP. The FII/DII shareholding leg is absent on
          purpose: the prior quarter carries no share count, so a two-quarter value-weighted figure cannot be computed
          without inventing one.
        </Footnote>
        <TrustLine source={sectors?.source ?? "nidp.mf_holdings_deltas"} asOf={fmtDate(sectors?.asOf)} mode="historical" maker="reported" testId="desk-smart-money-sectors-trust" />
      </Section>

      {/* ── scanner ── */}
      <Section
        title="Stock by stock"
        note={
          <label className="flex items-center" style={{ gap: 6, fontSize: 12, color: "var(--cp-ink-3)", cursor: "pointer" }}>
            <input type="checkbox" checked={rising} onChange={(e) => setRising(e.target.checked)} data-testid="desk-smart-money-rising-only" />
            Only where holdings rose
          </label>
        }
      >
        <DataTable
          rows={scannerRows}
          rowKey={(r) => r.symbol}
          columns={cols}
          minWidth={900}
          empty="No stock matched."
        />
        <Footnote>
          Ordered by how many fund houses raised the holding — a count of disclosures, not a model score. “Not checked”
          means that stock was never queried for deals, which is different from having no deals. A deal leg carries no
          counterparty classification, so it may be a market maker rather than a long-term buyer, and matched same-day
          legs are already netted out as transfers.
          {scanner?.quarters?.current && <> FII columns compare {fmtDate(scanner.quarters.previous)} with {fmtDate(scanner.quarters.current)} and are disclosed for only a minority of names.</>}
        </Footnote>
        <TrustLine source={scanner?.source ?? "nidp.mf_holdings_deltas"} asOf={fmtDate(scanner?.asOf)} mode="historical" maker="reported" testId="desk-smart-money-scanner-trust" />
      </Section>

      {/* ── feeds ── */}
      <Section title="Where this comes from">
        <DataTable
          rows={feeds?.rows ?? []}
          rowKey={(r) => r.feed}
          empty="No feed status available."
          columns={[
            { key: "feed", header: "Feed", width: "minmax(0,1.6fr)", render: (r) => r.feed },
            {
              key: "data", header: "Data as of", align: "right", num: true,
              render: (r) => (
                <span title={r.ingestedFor && ingestAheadOfData(r) ? `Loader last ran for ${r.ingestedFor} — that is the run date, not the data's date` : undefined}>
                  {fmtDate(r.dataAsOf) || "—"}
                </span>
              ),
            },
            { key: "ran", header: "Loader ran", align: "right", num: true, render: (r) => fmtDate(r.ingestedFor) || "—" },
            {
              key: "status", header: "Status", align: "right",
              render: (r) => (!r.statusRowPresent
                ? <Pill tone="ink" title="This path has no feed-status row; the date comes from the table itself">No status row</Pill>
                : <Pill tone={r.status === "OK" ? "mint" : r.status === "STALE" ? "amber" : "danger"}>{r.status ?? "—"}</Pill>),
            },
          ]}
        />
        <Footnote>
          “Data as of” is the newest period in the table; “Loader ran” is when the job last executed. They are
          different dates, and the first is the one that matters for anything you read above.
        </Footnote>
      </Section>

      {/* ── the two sentences that must always be here ── */}
      <div data-testid="desk-smart-money-disclaimer" style={{ paddingTop: 14, borderTop: "1px solid var(--cp-line)" }}>
        <Footnote>
          <strong style={{ color: "var(--cp-ink-2)" }}>Historical market reaction: no validated study available.</strong>{" "}
          Smart money is evidence, not a buy signal. Institutions can be wrong, they report in arrears, and a
          disclosed change is not a forecast. Educational market intelligence, not investment advice.
        </Footnote>
      </div>
    </Screen>
  );
}
