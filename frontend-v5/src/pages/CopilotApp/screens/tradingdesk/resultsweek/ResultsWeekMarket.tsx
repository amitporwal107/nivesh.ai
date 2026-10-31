/**
 * Smart trading desk · Results week — the market strip and this week's macro releases, composed from the desk's EXISTING
 * reads (no new endpoint; the results-week route does not carry them):
 *
 *   GET /api/markets/home             Nifty 50, Nifty Bank and India VIX closes, FII / DII cash (useMarketOverview —
 *                                     the same hook and cache as the Overview's index cards and flow tiles)
 *   GET /api/markets/sector-returns   NSE sectoral indices, 1-day return: the strongest and weakest (useSectorReturns —
 *                                     the Overview's sector card)
 *   GET /api/markets/macro-calendar   India and US releases in this week's window (useMacroCalendar — the Events
 *                                     calendar's Macro switch; one read per month the week touches)
 *
 * Each block loads and fails on its own; a figure not in its response says "not available", never 0.
 */
import { useMemo, useState, type ReactNode } from "react";
import { LoadingBlock, fmtPct } from "../../../components/ui";
import { fmtCr, fmtLevel } from "../../markets/format";
import { useMarketOverview } from "../../markets/hooks";
import { COUNTRY_NAME, IMPACT_COLOR, IMPACT_LABEL, fmtMacroVal, useMacroCalendar, type MacroEvent } from "../events-data";
import { DESK_INDICES, findIndex, istDay, useSectorReturns } from "../overview-data";
import { NA, eyebrow, fmtD, line, mono, quiet, toneOf } from "./parts";

function Tile({ label, testId, children, sub }: { label: string; testId: string; children: ReactNode; sub?: ReactNode }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 3, padding: "10px 12px", borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-2)" }}>
      <span style={{ ...eyebrow, fontSize: 9 }}>{label}</span>
      <span className="cp-num" style={{ fontSize: 14, minHeight: 20, display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap" }}>{children}</span>
      {sub && <span style={{ ...quiet, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sub}</span>}
    </div>
  );
}

const STRIP_INDICES = DESK_INDICES.filter((i) => i.name !== "Sensex");

export function MarketStrip({ mobile }: { mobile: boolean }) {
  const home = useMarketOverview();
  const sec = useSectorReturns();
  const d = home.data;
  const f = d?.fii_dii ?? null;
  const ranked = useMemo(() => (sec.data?.sectors ?? []).filter((s) => s.ret["1d"] != null).sort((a, b) => (b.ret["1d"] as number) - (a.ret["1d"] as number)), [sec.data]);
  const best = ranked[0] ?? null;
  const worst = ranked.length > 1 ? ranked[ranked.length - 1] : null;
  const homeState = home.isPending ? "loading" : home.isError ? "error" : "ready";
  const homeMiss = (text = "not available") => (homeState === "loading" ? <NA text="loading…" /> : homeState === "error" ? <NA text="didn’t load" /> : <NA text={text} />);
  return (
    <section data-testid="results-week-market" aria-label="Market strip" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <span style={eyebrow}>Market · last close</span>
      <div className="grid" style={{ gridTemplateColumns: mobile ? "repeat(2,minmax(0,1fr))" : "repeat(auto-fit,minmax(150px,1fr))", gap: 8 }}>
        {STRIP_INDICES.map(({ name, vix }) => {
          const ix = d ? findIndex(d, name, vix) : null;
          return (
            <Tile key={name} label={name} testId={`results-week-market-${name.toLowerCase().replace(/\s+/g, "-")}`} sub={ix?.as_of ? `${fmtD(ix.as_of.slice(0, 10))} close` : d ? `as of ${istDay(d.as_of) ?? "—"}` : undefined}>
              {ix?.value != null ? (
                <>
                  <span>{fmtLevel(ix.value)}</span>
                  {ix.change_pct != null && <span style={{ fontSize: 11, color: vix ? "var(--cp-ink-2)" : toneOf(ix.change_pct) }}>{fmtPct(ix.change_pct, { signed: true, digits: 2 })}</span>}
                </>
              ) : homeMiss()}
            </Tile>
          );
        })}
        <Tile label="FII / DII · cash" testId="results-week-market-flows" sub={f?.as_of ? `${fmtD(f.as_of.slice(0, 10))} · provisional` : undefined}>
          {f && (f.fii_net_cr != null || f.dii_net_cr != null) ? (
            <span style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 1 }}>
              <span>FII <span style={{ color: toneOf(f.fii_net_cr) }}>{f.fii_net_cr != null ? fmtCr(f.fii_net_cr, { signed: true }) : "n/a"}</span></span>
              <span>DII <span style={{ color: toneOf(f.dii_net_cr) }}>{f.dii_net_cr != null ? fmtCr(f.dii_net_cr, { signed: true }) : "n/a"}</span></span>
            </span>
          ) : homeMiss()}
        </Tile>
        <Tile label="Sectors · 1 day" testId="results-week-market-sectors" sub={sec.data?.asOf ? `${fmtD(sec.data.asOf.slice(0, 10))} · strongest, weakest` : undefined}>
          {best ? (
            <span style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{best.sector} <span style={{ color: toneOf(best.ret["1d"]) }}>{fmtPct(best.ret["1d"], { signed: true, digits: 1 })}</span></span>
              {worst && <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{worst.sector} <span style={{ color: toneOf(worst.ret["1d"]) }}>{fmtPct(worst.ret["1d"], { signed: true, digits: 1 })}</span></span>}
            </span>
          ) : sec.isPending ? <NA text="loading…" /> : sec.isError ? <NA text="didn’t load" /> : <NA />}
        </Tile>
      </div>
    </section>
  );
}

const IMP_ORDER = { H: 0, M: 1, L: 2 } as const;
const MACRO_SHOWN = 10;

function MacroRow({ e }: { e: MacroEvent }) {
  const fig = e.actual != null ? `actual ${fmtMacroVal(e.actual, e.unit)}` : e.previous != null ? `previous ${fmtMacroVal(e.previous, e.unit)}` : null;
  return (
    <li data-testid={`results-week-macro-${e.id}`} className="grid" style={{ gridTemplateColumns: "92px minmax(0,1fr) auto", gap: 10, alignItems: "center", padding: "7px 0", borderTop: line }}>
      <span className="cp-num" style={{ fontSize: 10.5, color: "var(--cp-ink-2)" }}>{fmtD(e.date)}{e.time ? ` · ${e.time}` : ""}</span>
      <span className="flex min-w-0 flex-col" style={{ gap: 1 }}>
        <span style={{ fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.name}</span>
        <span style={{ ...mono, fontSize: 9.5, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{COUNTRY_NAME[e.country]}{e.period ? ` · ${e.period}` : ""}{fig ? ` · ${fig}` : ""}</span>
      </span>
      <span className="flex items-center" style={{ gap: 5, ...mono, fontSize: 9, letterSpacing: "0.08em", color: IMPACT_COLOR[e.impact] }}>
        <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: IMPACT_COLOR[e.impact] }} />{IMPACT_LABEL[e.impact]}
      </span>
    </li>
  );
}

/** India and US releases between `from` and `to` (inclusive), from the Events calendar's own macro read. */
export function MacroWeek({ from, to }: { from: string; to: string }) {
  const m1 = from.slice(0, 7), m2 = to.slice(0, 7);
  const q1 = useMacroCalendar(m1);
  const q2 = useMacroCalendar(m2);
  const [all, setAll] = useState(false);
  const two = m2 !== m1;
  const evs = useMemo(() => [...(q1.data?.events ?? []), ...(two ? q2.data?.events ?? [] : [])]
    .filter((e) => e.date >= from && e.date <= to)
    .sort((a, b) => a.date.localeCompare(b.date) || (a.time ?? "99:99").localeCompare(b.time ?? "99:99") || IMP_ORDER[a.impact] - IMP_ORDER[b.impact]), [q1.data, q2.data, two, from, to]);
  const loading = q1.isPending || (two && q2.isPending);
  const failed = q1.isError || (two && q2.isError);
  const shown = all ? evs : evs.slice(0, MACRO_SHOWN);
  return (
    <section data-testid="results-week-macro" aria-label="Macro releases this week" className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <span style={eyebrow}>Macro this week · {fmtD(from)} – {fmtD(to)} · India &amp; US</span>
      {loading ? <LoadingBlock label="Loading this week's macro releases" rows={2} />
        : failed ? <span data-testid="results-week-macro-error" style={quiet}>The macro calendar didn’t load, so this week’s releases are not shown.</span>
        : evs.length === 0 ? <span data-testid="results-week-macro-empty" style={quiet}>No India or US releases on the calendar this week.</span>
        : (
          <>
            <ul className="m-0 p-0" style={{ listStyle: "none" }}>{shown.map((e) => <MacroRow key={e.id} e={e} />)}</ul>
            {evs.length > MACRO_SHOWN && (
              <button type="button" className="cp-chip" data-testid="results-week-macro-more" onClick={() => setAll((v) => !v)} style={{ alignSelf: "flex-start", fontSize: 11.5, padding: "4px 10px" }}>
                {all ? "Show fewer" : `Show all ${evs.length}`}
              </button>
            )}
          </>
        )}
      <span style={{ ...quiet, fontSize: 11 }}>Free sources (FRED, RBI, MoSPI …) carry no consensus estimate.</span>
    </section>
  );
}
