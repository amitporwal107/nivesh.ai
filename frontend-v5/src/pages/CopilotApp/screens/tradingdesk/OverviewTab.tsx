/**
 * Smart trading desk · 01 Overview — the index tape and market breadth, the
 * market pulse (regime, institutional flows, rupee, crude and the rules-based
 * read) and sector strength.
 *
 *   GET /api/markets/home                   index tiles with their daily closes, breadth, FII / DII cash,
 *                                           USD / INR and Brent, the deploy verdict and its reason
 *   GET /api/macro/today                    the regime (Nifty 50 against its 50-day average), macro risk, the engine's read
 *   GET /api/positional/market-dashboard    sector strength: today's sector-index change, or the 5-session mean (end of day)
 *
 * Each block loads and fails on its own: a failed market overview leaves the
 * regime and the sectors on screen. The 1-week / 1-month sector toggle of the
 * design has no endpoint behind it; the tab shows the one period the route
 * serves and says the rest is not connected.
 */
import type { ReactNode } from "react";
import type { MarketIndex, MarketsHome } from "@/services/contracts/markets.contract";
import { StockIcon } from "../../components/EntityIcon";
import {
  EmptyBlock, ErrorBlock, LoadingBlock, NotConnected, Pill, Section, TONE_COLOR, fmtNum, fmtPct, signTone, type Tone,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel, fmtCr, fmtLevel, fmtPoints } from "../markets/format";
import { useMarketOverview } from "../markets/hooks";
import { LoadError, SourceLine, Sparkline } from "../markets/parts";
import { useDesk } from "./context";
import {
  DESK_INDICES, REGIME_LABEL, REGIME_MEANING, findIndex, findQuote, readBreadth, useMacroToday, useSectorStrength,
  type MacroToday, type Regime, type SectorStrength, type SectorTile,
} from "./overview-data";

const REGIME_TONE: Record<Regime, Tone> = { BULL: "mint", NEUTRAL: "ink", BEAR: "danger" };
const REGIME_ORDER: Regime[] = ["BEAR", "NEUTRAL", "BULL"];

/** The /home deploy verdict (market_dashboard._deploy_verdict) and its colour. */
const VERDICT_TONE: Record<string, Tone> = { AGGRESSIVE: "mint", NORMAL: "ink", CAUTIOUS: "amber", DEFENSIVE: "danger" };

const ASK = [
  "Which sectors are leading today and why?",
  "What is driving market breadth today?",
  "How have FII and DII flows looked this week?",
];

type HomeQuery = ReturnType<typeof useMarketOverview>;

export default function OverviewTab() {
  const home = useMarketOverview();
  const macro = useMacroToday();
  const sectors = useSectorStrength();
  const { mobile } = useCopilotShell();
  const { askDesk } = useDesk();

  return (
    <div data-testid="desk-overview" className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <IndexRow home={home} />

      <div className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: 16, alignItems: "start" }}>
        <PulseCard home={home} macro={macro} />
        <SectorCard q={sectors} />
      </div>

      <div className="flex flex-col" style={{ gap: 10 }}>
        <span className="cp-eyebrow">Ask the Copilot</span>
        <div className="flex flex-wrap" style={{ gap: 8 }}>
          {ASK.map((q) => (
            <button key={q} type="button" className="cp-chip" data-testid="desk-overview-ask" onClick={() => askDesk(q)}>{q}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── index tiles + breadth ────────────────────────────────────────────────

function IndexRow({ home }: { home: HomeQuery }) {
  if (home.isPending) return <LoadingBlock label="Loading the index tape" rows={3} />;
  if (home.isError) {
    return (
      <div data-testid="desk-index-error">
        <LoadError title="Index levels and breadth didn’t load" error={home.error} onRetry={() => home.refetch()} />
      </div>
    );
  }
  const d = home.data;
  const sessions = Math.max(0, ...d.indices.map((i) => i.spark.length));
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <div data-testid="desk-index-row" className="flex flex-wrap" style={{ gap: 12 }}>
        {DESK_INDICES.map(({ name, vix }) => <IndexTile key={name} name={name} ix={findIndex(d, name, vix)} />)}
        <BreadthTile home={d} />
      </div>
      <SourceLine
        testId="desk-index-source"
        source="Yahoo Finance index quotes"
        asOf={d.fetched_at ?? d.as_of}
        asOfLabel="updated"
        note={[
          "delayed",
          d.market_state === "closed" ? "market closed" : "",
          sessions > 1 ? `each line is the last ${sessions} daily closes` : "",
        ].filter(Boolean).join(" · ")}
      />
    </div>
  );
}

function IndexTile({ name, ix }: { name: string; ix: MarketIndex | null }) {
  // A rising VIX is not a gain, so its change stays neutral (as on the Markets screen).
  const tone: Tone = !ix || ix.is_vix ? "ink" : signTone(ix.change_pct);
  const color = tone === "ink" ? "var(--cp-ink-2)" : TONE_COLOR[tone];
  return (
    <div
      data-testid="desk-index-tile"
      data-index={ix?.name ?? name}
      className="cp-card flex min-w-0 flex-col"
      style={{ flex: "1 1 150px", gap: 6, padding: "14px 16px" }}
    >
      <div className="flex items-start justify-between" style={{ gap: 8 }}>
        {/* The name may wrap rather than be cut off: a tile can be ~150px wide beside the breadth tile. */}
        <span className="cp-eyebrow" style={{ minWidth: 0, letterSpacing: "0.1em", overflowWrap: "anywhere" }}>{ix?.name ?? name}</span>
        {ix && ix.spark.length > 1 && (
          <span style={{ width: 44, flex: "none" }} title={`Last ${ix.spark.length} daily closes`}>
            <Sparkline values={ix.spark} tone={tone} height={20} testId="desk-index-spark" />
          </span>
        )}
      </div>
      <span data-testid="desk-index-value" style={{ fontFamily: "var(--display)", fontSize: 27, lineHeight: 1.1, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums" }}>
        {fmtLevel(ix?.value)}
      </span>
      <span data-testid="desk-index-change" className="cp-num" style={{ fontSize: 12, color }}>
        {ix ? `${fmtPoints(ix.change)} (${fmtPct(ix.change_pct, { signed: true, digits: 2 })})` : "Not in the response"}
      </span>
    </div>
  );
}

function BreadthTile({ home }: { home: MarketsHome }) {
  const b = readBreadth(home.breadth);
  return (
    <div data-testid="desk-breadth" className="cp-card flex min-w-0 flex-col" style={{ flex: "2 1 300px", gap: 8, padding: "14px 16px" }}>
      <span className="cp-eyebrow">Market breadth</span>
      {!b ? (
        <span data-testid="desk-breadth-empty" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>Advances and declines are not available right now.</span>
      ) : (
        <>
          <span style={{ fontFamily: "var(--display)", fontSize: 27, lineHeight: 1.1, letterSpacing: "-0.02em" }}>
            <span data-testid="desk-breadth-pct" style={{ color: TONE_COLOR[signTone(b.advancingPct - 50)] }}>{fmtPct(b.advancingPct, { digits: 1 })}</span>{" "}
            <span style={{ fontSize: 15, color: "var(--cp-ink-3)" }}>advancing</span>
          </span>
          <div
            data-testid="desk-breadth-bar"
            role="img"
            aria-label={`${fmtNum(b.advances)} advances, ${fmtNum(b.unchanged)} unchanged, ${fmtNum(b.declines)} declines`}
            className="flex overflow-hidden"
            style={{ height: 8, borderRadius: 4, background: "var(--bg-3)", gap: 2 }}
          >
            <span style={{ width: `${(b.advances / b.total) * 100}%`, background: "var(--mint)" }} />
            {b.unchanged != null && b.unchanged > 0 && <span style={{ width: `${(b.unchanged / b.total) * 100}%`, background: "var(--cp-ink-4)" }} />}
            <span style={{ width: `${(b.declines / b.total) * 100}%`, background: "var(--cp-danger)" }} />
          </div>
          <span data-testid="desk-breadth-counts" className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>
            <span style={{ color: "var(--mint)" }}>{fmtNum(b.advances)}</span> advances · <span style={{ color: "var(--cp-danger)" }}>{fmtNum(b.declines)}</span> declines
            {b.unchanged != null && <> · {fmtNum(b.unchanged)} unchanged</>}
          </span>
          <span data-testid="desk-breadth-scope" className="cp-mono-note" style={{ lineHeight: 1.6 }}>
            {b.scope === "eod"
              ? `Across ${fmtNum(b.universe)} NSE stocks · end of day${home.as_of ? ` ${dayLabel(home.as_of, { year: true })}` : ""}`
              : b.scope === "nifty50"
                ? `Across the ${fmtNum(b.universe)} Nifty 50 stocks · delayed quotes`
                : "The response does not say which stocks were counted"}
          </span>
        </>
      )}
    </div>
  );
}

// ── market pulse ─────────────────────────────────────────────────────────

function PulseCard({ home, macro }: { home: HomeQuery; macro: ReturnType<typeof useMacroToday> }) {
  const m = macro.data;
  return (
    <Section
      title="01 · Market pulse"
      note={m?.kind === "ready" && m.date ? `Macro as of ${dayLabel(m.date, { year: true })}` : undefined}
    >
      <div className="flex flex-col" style={{ gap: 16 }} data-testid="desk-pulse">
        {macro.isPending ? (
          <LoadingBlock label="Loading the market regime" rows={2} />
        ) : macro.isError ? (
          <ErrorBlock title="The market regime didn’t load" error={macro.error} onRetry={() => macro.refetch()} />
        ) : (
          <RegimeBlock m={macro.data} />
        )}
        <FlowTiles home={home} />
        <InsightBox home={home.data} macro={m} />
      </div>
    </Section>
  );
}

function RegimeBlock({ m }: { m: MacroToday }) {
  const { isAdmin } = useCopilotShell();
  const regime = m.kind === "ready" ? m.regime : null;
  return (
    <div data-testid="desk-regime" data-regime={regime ?? "unavailable"} className="flex flex-col" style={{ gap: 10 }}>
      <span className="cp-eyebrow">Market regime</span>
      <span data-testid="desk-regime-label" style={{ fontFamily: "var(--display)", fontSize: 40, lineHeight: 1, letterSpacing: "-0.03em", color: regime ? TONE_COLOR[REGIME_TONE[regime]] : "var(--cp-ink-3)" }}>
        {regime ? REGIME_LABEL[regime] : "Not available"}
      </span>
      <div className="flex flex-col" style={{ gap: 4 }}>
        <div className="grid" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 4 }} aria-hidden>
          {REGIME_ORDER.map((r) => (
            <span
              key={r}
              data-testid="desk-regime-segment"
              data-on={r === regime ? "true" : "false"}
              style={{ height: 6, borderRadius: 3, background: r === regime ? TONE_COLOR[REGIME_TONE[r]] : "var(--bg-3)" }}
            />
          ))}
        </div>
        <div className="grid" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 4 }}>
          {REGIME_ORDER.map((r) => (
            <span key={r} className="cp-mono-note" style={{ textAlign: r === "BEAR" ? "left" : r === "BULL" ? "right" : "center", color: r === regime ? "var(--cp-ink)" : undefined }}>
              {REGIME_LABEL[r]}
            </span>
          ))}
        </div>
      </div>
      {m.kind === "ready" ? (
        <>
          <span data-testid="desk-regime-meaning" style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
            {REGIME_MEANING[m.regime]} This is the macro engine’s trend rule, worked out after the close.
          </span>
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            {m.risk && <Pill tone={m.risk === "HIGH" ? "danger" : m.risk === "LOW" ? "mint" : "amber"}>Macro risk {m.risk.toLowerCase()}</Pill>}
            {m.daysStale != null && m.daysStale >= 2 && (
              <span data-testid="desk-regime-stale" className="cp-mono-note">{fmtNum(m.daysStale)} days old</span>
            )}
          </span>
        </>
      ) : (
        <span data-testid="desk-regime-unavailable" style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          The macro engine has not produced a regime yet, so none is shown. It runs after the close each trading day.
          {isAdmin && m.reason && (
            <span className="cp-mono-note" title="Shown to admins only" style={{ display: "block", marginTop: 6, textTransform: "none", letterSpacing: 0 }}>
              Reason from the route: {m.reason}
            </span>
          )}
        </span>
      )}
    </div>
  );
}

function MiniTile({ label, value, sub, tone = "ink", testId }: { label: string; value: string; sub: ReactNode; tone?: Tone; testId: string }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 4, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line-2)" }}>
      <span className="cp-eyebrow">{label}</span>
      <span data-testid={`${testId}-value`} className="cp-num" style={{ fontSize: 17, color: tone === "ink" ? "var(--cp-ink)" : TONE_COLOR[tone] }}>{value}</span>
      <span data-testid={`${testId}-sub`} style={{ fontSize: 11.5, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sub}</span>
    </div>
  );
}

function Change({ pct }: { pct: number | null }) {
  const tone = signTone(pct);
  return <span className="cp-num" style={{ color: tone === "ink" ? "var(--cp-ink-3)" : TONE_COLOR[tone] }}>{fmtPct(pct, { signed: true, digits: 2 })}</span>;
}

/** FII / DII cash, USD / INR and Brent — all from GET /api/markets/home. */
function FlowTiles({ home }: { home: HomeQuery }) {
  if (home.isPending) return <LoadingBlock label="Loading flows and quotes" rows={2} />;
  if (home.isError) {
    return (
      <span data-testid="desk-flows-unavailable" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>
        FII / DII cash, the rupee and crude come from the market overview, which didn’t load.
      </span>
    );
  }
  const d = home.data;
  const f = d.fii_dii ?? null;
  const flowDay = f?.as_of ? `Net · ${dayLabel(f.as_of)}` : "Not available";
  const usd = findQuote(d, "USD / INR");
  const brent = findQuote(d, "Brent Crude");
  return (
    <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}>
      <MiniTile label="FII cash" testId="desk-mini-fii" value={fmtCr(f?.fii_net_cr, { signed: true })} tone={signTone(f?.fii_net_cr)} sub={flowDay} />
      <MiniTile label="DII cash" testId="desk-mini-dii" value={fmtCr(f?.dii_net_cr, { signed: true })} tone={signTone(f?.dii_net_cr)} sub={flowDay} />
      <MiniTile
        label="USD / INR"
        testId="desk-mini-usdinr"
        value={fmtLevel(usd?.value)}
        sub={usd ? <>Spot · <Change pct={usd.change_pct} /></> : "Not available"}
      />
      <MiniTile
        label="Brent crude"
        testId="desk-mini-brent"
        value={brent?.value != null ? `$${fmtLevel(brent.value)}` : "—"}
        sub={brent ? <>{brent.unit ?? "$/bbl"} · <Change pct={brent.change_pct} /></> : "Not available"}
      />
    </div>
  );
}

/** The backend's own words: the macro engine's insight and the deploy verdict's reason. Both are rules-based. */
function InsightBox({ home, macro }: { home: MarketsHome | undefined; macro: MacroToday | undefined }) {
  const insight = macro?.kind === "ready" ? macro.insight : null;
  const verdict = (home?.verdict ?? "").toUpperCase() || null;
  const reason = home?.verdict_reason ?? null;
  return (
    <div data-testid="desk-insight" className="flex flex-col" style={{ gap: 10, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--mint-line)", background: "var(--mint-soft)" }}>
      <span className="cp-eyebrow" style={{ color: "var(--mint)" }}>Rules-based read · not a forecast</span>
      {!insight && !verdict && !reason && (
        <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>No rules-based read is available right now.</span>
      )}
      {insight && macro?.kind === "ready" && (
        <div className="flex flex-col" style={{ gap: 4 }}>
          <span data-testid="desk-insight-macro" className="cp-pretty" style={{ fontFamily: "var(--display)", fontSize: 18, lineHeight: 1.3 }}>{insight}</span>
          <span className="cp-mono-note">Macro engine{macro.date ? ` · ${dayLabel(macro.date, { year: true })}` : ""}</span>
        </div>
      )}
      {(verdict || reason) && (
        <div data-testid="desk-verdict" className="flex flex-col" style={{ gap: 6 }}>
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <span className="cp-mono-note">Deploy stance</span>
            {verdict && <span data-testid="desk-verdict-label"><Pill tone={VERDICT_TONE[verdict] ?? "ink"}>{verdict.toLowerCase()}</Pill></span>}
          </span>
          {reason && <span data-testid="desk-verdict-reason" style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{reason}</span>}
          <span className="cp-mono-note" style={{ lineHeight: 1.6 }}>Rules: macro risk first, then breadth above the 20-day average, then the Nifty trend</span>
        </div>
      )}
    </div>
  );
}

// ── sector strength ──────────────────────────────────────────────────────

const PERIOD_LABEL = { today: "Today · sector indices", "5d": "5 days · end of day", mixed: "Today or 5 days · see each tile" } as const;

function SectorCard({ q }: { q: ReturnType<typeof useSectorStrength> }) {
  const s = q.data;
  return (
    <Section
      title="Sector strength"
      note={s?.kind === "ready" && s.tiles.length > 0 ? <span data-testid="desk-sector-period">{PERIOD_LABEL[s.period]}</span> : undefined}
    >
      <div data-testid="desk-sectors" className="flex flex-col" style={{ gap: 12 }}>
        {q.isPending ? (
          <LoadingBlock label="Loading sector strength" rows={4} />
        ) : q.isError ? (
          <LoadError title="Sector strength didn’t load" error={q.error} onRetry={() => q.refetch()} />
        ) : (
          <SectorBody s={q.data} />
        )}
      </div>
    </Section>
  );
}

function SectorBody({ s }: { s: SectorStrength }) {
  const { isAdmin } = useCopilotShell();
  if (s.kind === "unavailable") {
    return (
      <div data-testid="desk-sectors-unavailable">
        <EmptyBlock
          title="Sector figures are not available"
          body={<>The sector table could not be built right now.{isAdmin && s.reason ? ` Route said: ${s.reason}.` : ""}</>}
        />
      </div>
    );
  }
  if (s.tiles.length === 0) {
    return <div data-testid="desk-sectors-empty"><EmptyBlock title="No sector figures yet" body="The route returned no sectors for the latest session." /></div>;
  }
  const max = Math.max(0.01, ...s.tiles.map((t) => Math.abs(t.pct ?? 0)));
  return (
    <>
      <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}>
        {s.tiles.map((t) => <SectorTileView key={t.sector} t={t} max={max} mixed={s.period === "mixed"} />)}
      </div>
      <SourceLine
        testId="desk-sector-source"
        source={s.period === "5d" ? "end-of-day price bars" : "Yahoo Finance sector indices"}
        asOf={s.period === "5d" ? s.asOf : s.fetchedAt ?? s.asOf}
        asOfLabel={s.period === "5d" ? "end of day" : "updated"}
        note={s.period === "5d"
          ? "Mean 5-session return of each sector’s stocks · leader = best 5-session stock"
          : `Sector-index change, delayed${s.isLive ? "" : " · market closed: the last session’s change"} · leader = best 5-session stock (end of day)`}
      />
      <NotConnected
        testId="desk-sector-periods-gap"
        title={s.period === "today" ? "1-week and 1-month sector views" : "1-day and 1-month sector views"}
        body={s.period === "today"
          ? "Only today’s sector-index change is served while the live index feed answers. No endpoint serves a 1-week or 1-month sector return yet."
          : "These are 5-session figures (about one week) from end-of-day bars. Today’s change appears only while the live sector-index feed answers, and no endpoint serves a 1-month sector return yet."}
        needs={[
          "Sector returns for 1 day, 1 week and 1 month side by side — e.g. add ret_1d_pct and ret_20d_pct to sector_heatmap in GET /api/positional/market-dashboard (positional_engine/market_dashboard.py), computed from the same end-of-day bars",
        ]}
      />
    </>
  );
}

function SectorTileView({ t, max, mixed }: { t: SectorTile; max: number; mixed: boolean }) {
  const { openChart } = useDesk();
  const tone = signTone(t.pct);
  // The tint grows with the size of the move: 6% to 26% of the colour over the card.
  const share = t.pct == null ? 0 : Math.min(1, Math.abs(t.pct) / max);
  const mixIn = Math.round(6 + share * 20);
  const background = tone === "mint"
    ? `color-mix(in oklab, var(--mint) ${mixIn}%, var(--bg-1))`
    : tone === "danger"
      ? `color-mix(in oklab, var(--cp-danger) ${mixIn}%, var(--bg-1))`
      : "var(--bg-1)";
  const leader = t.leader;
  return (
    <div
      data-testid="desk-sector-tile"
      data-sector={t.sector}
      className="flex min-w-0 flex-col"
      style={{ gap: 4, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background }}
    >
      <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.sector}</span>
      <span data-testid="desk-sector-pct" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.1, color: tone === "ink" ? "var(--cp-ink)" : TONE_COLOR[tone] }}>
        {fmtPct(t.pct, { signed: true, digits: 2 })}
      </span>
      <span className="cp-num" style={{ fontSize: 10.5, color: "var(--cp-ink-3)" }}>
        {t.rsPp != null ? `vs Nifty ${t.rsPp > 0 ? "+" : t.rsPp < 0 ? "−" : ""}${Math.abs(t.rsPp).toFixed(2)} pp` : "vs Nifty —"}
        {mixed ? ` · ${t.live ? "today" : "5 days"}` : ""}
      </span>
      {leader && (
        <button
          type="button"
          data-testid="desk-sector-leader"
          onClick={() => openChart(leader.symbol)}
          title={`Open the ${leader.symbol} chart`}
          className="flex min-w-0 items-center"
          style={{ gap: 6, padding: 0, marginTop: 2, border: 0, background: "none", cursor: "pointer", color: "var(--cp-ink-2)", fontFamily: "var(--mono)", fontSize: 10.5, textAlign: "left" }}
        >
          <StockIcon symbol={leader.symbol} size={16} />
          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {leader.symbol}{leader.ret5dPct != null ? ` ${fmtPct(leader.ret5dPct, { signed: true })}` : ""}
          </span>
        </button>
      )}
    </div>
  );
}
