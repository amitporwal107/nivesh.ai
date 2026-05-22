import React, { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { AlertTriangle, RefreshCw, TrendingUp, TrendingDown, Minus } from "lucide-react";
import HeroCard from "../../components/HeroCard";
import CompactCard from "../../components/CompactCard";
import CardStrip from "../../components/CardStrip";
import CategoryChip from "../../components/CategoryChip";
import TinyChip from "../../components/TinyChip";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { usePerformance, interpretationText, benchmarkBeatCount } from "../../adapters/performance";
import { pct, inrCompact } from "../../lib/format";

const PERIODS = ["1M", "3M", "6M", "YTD", "1Y", "3Y", "ALL"];

function IndexRow({ name, indexReturn, portfolioReturn }) {
  if (indexReturn == null) return null;
  const delta = portfolioReturn != null ? portfolioReturn - indexReturn : null;
  const beating = delta != null && delta > 0;
  const losing = delta != null && delta < 0;
  return (
    <div style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 10, padding: "12px 16px", display: "flex", alignItems: "center", gap: 10 }}>
      <span style={{ flex: 1, fontSize: 13, color: "var(--v3-ink-1)" }}>{name}</span>
      <span className="v3-data" style={{ fontSize: 12, color: "var(--v3-ink-3)" }}>{pct(indexReturn)}</span>
      {delta != null && (
        <span className="v3-data" style={{ fontSize: 11, padding: "3px 8px", borderRadius: 999, background: beating ? "var(--v3-moss-soft)" : losing ? "var(--v3-crimson-soft)" : "var(--v3-bg-3)", color: beating ? "var(--v3-moss)" : losing ? "var(--v3-crimson)" : "var(--v3-ink-3)" }}>
          {beating ? "+" : ""}{delta.toFixed(1)} pp
        </span>
      )}
      <span style={{ color: beating ? "var(--v3-moss)" : losing ? "var(--v3-crimson)" : "var(--v3-ink-3)", display: "flex" }}>
        {beating ? <TrendingUp size={13} /> : losing ? <TrendingDown size={13} /> : <Minus size={13} />}
      </span>
    </div>
  );
}

function FundRow({ fund, positive }) {
  const name = fund?.scheme_name || fund?.name || fund?.fund_name || "—";
  const ret = fund?.return_1y ?? fund?.returns_1y ?? fund?.xirr ?? null;
  const absReturn = fund?.abs_return ?? fund?.absolute_return ?? null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderBottom: "1px solid var(--v3-line)" }}>
      <div style={{ width: 28, height: 28, borderRadius: 8, background: positive ? "var(--v3-moss-soft)" : "var(--v3-crimson-soft)", display: "grid", placeItems: "center", flexShrink: 0 }}>
        {positive ? <TrendingUp size={13} color="var(--v3-moss)" /> : <TrendingDown size={13} color="var(--v3-crimson)" />}
      </div>
      <span style={{ flex: 1, fontSize: 13, color: "var(--v3-ink-1)", lineHeight: 1.3 }}>{name}</span>
      <div style={{ textAlign: "right" }}>
        {ret != null && <div className="v3-data" style={{ fontSize: 13, color: positive ? "var(--v3-moss)" : "var(--v3-crimson)" }}>{pct(ret)}</div>}
        {absReturn != null && <div style={{ fontSize: 10, color: "var(--v3-ink-4)" }}>{inrCompact(absReturn)}</div>}
      </div>
    </div>
  );
}

function ErrorState({ onRetry }) {
  return (
    <div style={{ textAlign: "center", padding: "60px 24px", display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
      <AlertTriangle size={28} color="var(--v3-ink-4)" />
      <p style={{ color: "var(--v3-ink-3)", fontSize: 14, margin: 0 }}>Couldn't load performance data</p>
      <button onClick={onRetry} style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 16px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 999, fontSize: 13, color: "var(--v3-ink-2)", cursor: "pointer" }}>
        <RefreshCw size={13} /> Retry
      </button>
    </div>
  );
}

export default function Performance() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const [period, setPeriod] = useState("1Y");
  const [showAll, setShowAll] = useState(false);

  const { data, loading, error, refetch } = usePerformance();

  const health = data?.health || {};
  const healthScore = health.score ?? health.health_score ?? null;
  const healthGrade = health.grade ?? null;
  const portfolioReturn = data?.portfolioReturn;
  const benchmarks = data?.benchmarks || {};
  const bb = benchmarkBeatCount(portfolioReturn, benchmarks);
  const interpretation = interpretationText({
    portfolioReturn,
    benchmarks,
    topContrib: data?.topContrib,
    worstDrag: data?.worstDrag,
  });

  const heroTitle = loading
    ? "Loading performance data…"
    : data?.empty
    ? "Upload your portfolio to see performance"
    : portfolioReturn != null
    ? `${pct(portfolioReturn)} return`
    : healthScore != null
    ? `Portfolio health ${healthScore}/100${healthGrade ? ` · Grade ${healthGrade}` : ""}`
    : "Your portfolio performance";

  const heroEyebrow = loading
    ? "Loading…"
    : bb
    ? `Beating ${bb.beat} of ${bb.total} indices`
    : "Portfolio return";

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Portfolio · Performance" title="Performance" />
      {error && !loading ? (
        <ErrorState onRetry={refetch} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 80 }}>
          <HeroCard
            layout={isDesktop ? "desktop" : "mobile"}
            category="performance"
            priorityLabel={heroEyebrow}
            title={heroTitle}
            description={isDesktop ? interpretation : null}
            viz={
              loading ? (
                <div style={{ width: "100%", height: 80, background: "var(--v3-bg-3)", borderRadius: 10 }} />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                  {portfolioReturn != null && (
                    <span style={{ fontFamily: "var(--v3-font-display)", fontSize: isDesktop ? 56 : 44, fontWeight: 600, color: portfolioReturn > 0 ? "var(--v3-moss)" : "var(--v3-crimson)", lineHeight: 1 }}>
                      {pct(portfolioReturn)}
                    </span>
                  )}
                  {healthScore != null && (
                    <span className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", fontSize: 10 }}>
                      HEALTH {healthScore}/100{healthGrade ? ` · ${healthGrade}` : ""}
                    </span>
                  )}
                </div>
              )
            }
            ctaText="See benchmark breakdown →"
            onClick={() => navigate("/v3/chat?q=How+does+my+portfolio+compare+to+benchmarks")}
          />

          <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 2 }}>
            {PERIODS.map((p) => (
              <CategoryChip key={p} category="performance" label={p} active={period === p} onClick={() => setPeriod(p)} />
            ))}
          </div>

          {!data?.empty && data?.cards?.length > 0 && (
            <section>
              <SectionHead title="Snapshot" count="5 metrics" />
              <CardStrip ariaLabel="Performance snapshot" desktopColumns={4}>
                <CompactCard category="performance" label="XIRR" meta={portfolioReturn != null ? pct(portfolioReturn) : "—"} />
                <CompactCard category="performance" label="Positive returns" meta={`${data.cards.filter((c) => (c.return_1y ?? 0) > 0).length} of ${data.cards.length} funds`} />
                <CompactCard category="performance" label="Beating Nifty 50" meta={benchmarks.nifty50 != null ? `Index: ${pct(benchmarks.nifty50)}` : "—"} />
                <CompactCard category="performance" label="Needs review" meta={`${data.bottomPerformers.length} underperforming`} />
                <CompactCard category="performance" label="vs Nifty 50 delta" meta={portfolioReturn != null && benchmarks.nifty50 != null ? `${pct(portfolioReturn - benchmarks.nifty50)} alpha` : "—"} />
              </CardStrip>
            </section>
          )}

          {totalBenchmarks > 0 && (
            <section>
              <SectionHead title="vs Benchmark indices" count={`${totalBenchmarks} indices`} />
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <IndexRow name="Nifty 50" indexReturn={benchmarks.nifty50} portfolioReturn={portfolioReturn} />
                <IndexRow name="Nifty 500" indexReturn={benchmarks.nifty500} portfolioReturn={portfolioReturn} />
                <IndexRow name="Sensex" indexReturn={benchmarks.sensex} portfolioReturn={portfolioReturn} />
                <IndexRow name="Nifty Midcap 100" indexReturn={benchmarks.midcap100} portfolioReturn={portfolioReturn} />
              </div>
            </section>
          )}

          {(data?.topContrib || data?.worstDrag) && (
            <section>
              <SectionHead title="Contributors" count="best & worst" />
              <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "1fr 1fr" : "1fr", gap: 12 }}>
                {data.topContrib && <CompactCard category="performance" label={`Top: ${data.topContrib.scheme_name || data.topContrib.name || "—"}`} meta={`${pct(data.topContrib.return_1y ?? 0)} · ${inrCompact(data.topContrib.abs_return ?? 0)} gain`} />}
                {data.worstDrag && <CompactCard category="risk" label={`Lagging: ${data.worstDrag.scheme_name || data.worstDrag.name || "—"}`} meta={pct(data.worstDrag.return_1y ?? 0)} />}
              </div>
            </section>
          )}

          {(data?.topPerformers?.length > 0 || data?.bottomPerformers?.length > 0) && (
            <section>
              <SectionHead title="Fund performance" count={`${(data.topPerformers?.length ?? 0) + (data.bottomPerformers?.length ?? 0)} funds`} />
              <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "1fr 1fr" : "1fr", gap: 20 }}>
                {data.topPerformers.length > 0 && (
                  <div>
                    <p className="v3-eyebrow" style={{ color: "var(--v3-moss)", fontSize: 10, marginBottom: 8 }}>TOP PERFORMERS</p>
                    {(showAll ? data.topPerformers : data.topPerformers.slice(0, 3)).map((f, i) => <FundRow key={i} fund={f} positive />)}
                  </div>
                )}
                {data.bottomPerformers.length > 0 && (
                  <div>
                    <p className="v3-eyebrow" style={{ color: "var(--v3-crimson)", fontSize: 10, marginBottom: 8 }}>NEEDS REVIEW</p>
                    {(showAll ? data.bottomPerformers : data.bottomPerformers.slice(0, 3)).map((f, i) => <FundRow key={i} fund={f} positive={false} />)}
                  </div>
                )}
              </div>
              {(data.topPerformers.length > 3 || data.bottomPerformers.length > 3) && (
                <button onClick={() => setShowAll((v) => !v)} style={{ marginTop: 10, fontSize: 12, color: "var(--v3-saffron)", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
                  {showAll ? "Show less" : "View all funds →"}
                </button>
              )}
            </section>
          )}

          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <TinyChip onClick={() => navigate("/v3/chat?q=Which+funds+should+I+switch")}>Which funds to switch?</TinyChip>
            <TinyChip onClick={() => navigate("/v3/chat?q=Compare+my+portfolio+to+Nifty+500")}>Compare vs Nifty 500</TinyChip>
            <TinyChip onClick={() => navigate("/v3/chat?q=Show+3Y+annualized+returns")}>3Y returns</TinyChip>
            <TinyChip onClick={() => navigate("/v3/chat?q=Why+is+XIRR+lower+than+YTD")}>Why is XIRR lower than YTD?</TinyChip>
          </div>
        </div>
      )}
    </ScreenContainer>
  );
}
