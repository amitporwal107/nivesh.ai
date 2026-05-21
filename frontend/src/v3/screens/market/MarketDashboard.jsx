import React from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { AlertTriangle, RefreshCw, Activity, TrendingUp, TrendingDown, Minus } from "lucide-react";
import HeroCard from "../../components/HeroCard";
import HeroVizPanel from "../../components/HeroVizPanel";
import CompactCard from "../../components/CompactCard";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import TinyChip from "../../components/TinyChip";
import { PerformanceLine } from "../../components/viz";
import { useMarketDashboard } from "../../adapters";

const VERDICT_TONE = {
  AGGRESSIVE: { bg: "var(--v3-moss-soft)",    color: "var(--v3-moss)",    label: "Aggressive" },
  NORMAL:     { bg: "var(--v3-indigo-soft)",  color: "var(--v3-indigo)",  label: "Normal" },
  CAUTIOUS:   { bg: "#D4AF3726",              color: "var(--v3-gold)",    label: "Cautious" },
  DEFENSIVE:  { bg: "var(--v3-crimson-soft)", color: "var(--v3-crimson)", label: "Defensive" },
};

function pct(v, dp = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  const s = v >= 0 ? "+" : "";
  return `${s}${Number(v).toFixed(dp)}%`;
}

function inr(v) {
  if (v == null || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function DeltaPill({ value }) {
  if (value == null || Number.isNaN(value)) {
    return <span style={{ fontSize: 11, color: "var(--v3-ink-4)" }}>—</span>;
  }
  const up = value >= 0;
  const Icon = up ? TrendingUp : TrendingDown;
  const color = up ? "var(--v3-moss)" : "var(--v3-crimson)";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color, fontSize: 12, fontFamily: "var(--v3-font-mono)", fontWeight: 600 }}>
      <Icon size={12} /> {pct(value)}
    </span>
  );
}

function ErrorState({ onRetry }) {
  return (
    <div style={{ textAlign: "center", padding: "48px 24px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 14, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
      <AlertTriangle size={28} color="var(--v3-ink-4)" />
      <p style={{ color: "var(--v3-ink-3)", fontSize: 14, margin: 0 }}>Couldn't load market data</p>
      <button onClick={onRetry} style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 16px", background: "var(--v3-bg-3)", border: "1px solid var(--v3-line)", borderRadius: 999, fontSize: 13, color: "var(--v3-ink-2)", cursor: "pointer" }}>
        <RefreshCw size={13} /> Retry
      </button>
    </div>
  );
}

export default function MarketDashboard() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const { data, loading, error, refetch } = useMarketDashboard();

  const nifty = data.indices.find((i) => i.name === "Nifty 50") || data.indices[0] || null;
  const verdict = data.verdict ? (VERDICT_TONE[data.verdict] || null) : null;

  if (error && !loading && !data.loaded) {
    return (
      <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
        <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Market" title="Today's market read" />
        <ErrorState onRetry={refetch} />
      </ScreenContainer>
    );
  }

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Market" title="Today's market read" />
      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 80 }}>
        <HeroCard
          layout={isDesktop ? "desktop" : "mobile"}
          category="performance"
          priorityLabel={loading ? "Loading…" : verdict ? `Deploy: ${verdict.label}` : "Live"}
          title={
            loading ? "Reading the tape…"
            : nifty ? `Nifty 50 · ${inr(nifty.value)}`
            : "Market data unavailable"
          }
          description={
            isDesktop
              ? (data.verdict_reason || data.macro_insight || (verdict ? `${verdict.label} regime — review your positioning before deploying fresh capital.` : null))
              : null
          }
          viz={
            loading ? (
              <div style={{ width: "100%", height: 100, background: "var(--v3-bg-3)", borderRadius: 10 }} />
            ) : nifty ? (
              <HeroVizPanel eyebrow="Today" value={pct(nifty.change_pct)} size={isDesktop ? "desktop" : "mobile"}>
                <PerformanceLine size={isDesktop ? 144 : 96} color={(nifty.change_pct ?? 0) >= 0 ? "var(--v3-moss)" : "var(--v3-crimson)"} />
              </HeroVizPanel>
            ) : (
              <Activity size={36} color="var(--v3-ink-4)" />
            )
          }
          ctaText={null}
        />

        {verdict && (
          <div style={{ padding: "10px 14px", background: verdict.bg, border: `1px solid ${verdict.color}40`, borderRadius: 10, display: "flex", alignItems: "center", gap: 10 }}>
            <Activity size={14} color={verdict.color} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, color: verdict.color, fontWeight: 600 }}>
                Today's deploy verdict: {verdict.label}
              </div>
              {data.verdict_reason && (
                <div style={{ fontSize: 11, color: "var(--v3-ink-2)", marginTop: 2 }}>{data.verdict_reason}</div>
              )}
            </div>
          </div>
        )}

        {data.indices.length > 0 && (
          <section>
            <SectionHead title="Indices" count={`${data.indices.length} indices`} />
            <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(4, 1fr)" : "1fr 1fr", gap: 12 }}>
              {data.indices.map((idx, i) => (
                <CompactCard
                  key={i}
                  category={(idx.change_pct ?? 0) >= 0 ? "performance" : "risk"}
                  label={idx.name}
                  meta={`${inr(idx.value)}`}
                  viz={
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <PerformanceLine size={56} color={(idx.change_pct ?? 0) >= 0 ? "var(--v3-moss)" : "var(--v3-crimson)"} />
                      <DeltaPill value={idx.change_pct} />
                    </div>
                  }
                />
              ))}
            </div>
          </section>
        )}

        {data.breadth && (
          <section>
            <SectionHead title="Market breadth" count="Today" />
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
              <CompactCard category="performance" label="Advances" meta={inr(data.breadth.advances)} viz={<TrendingUp size={24} color="var(--v3-moss)" />} />
              <CompactCard category="risk" label="Declines" meta={inr(data.breadth.declines)} viz={<TrendingDown size={24} color="var(--v3-crimson)" />} />
              <CompactCard category="health" label="Unchanged" meta={inr(data.breadth.unchanged)} viz={<Minus size={24} color="var(--v3-ink-3)" />} />
            </div>
          </section>
        )}

        {data.sectors.length > 0 && (
          <section>
            <SectionHead title="Sectors today" count={`${data.sectors.length} sectors`} />
            <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(4, 1fr)" : "1fr 1fr", gap: 12 }}>
              {data.sectors.slice(0, isDesktop ? 12 : 8).map((s, i) => {
                const change = s.change_pct ?? s.return_pct ?? s.tilt ?? 0;
                return (
                  <CompactCard
                    key={i}
                    category={change >= 0 ? "performance" : "risk"}
                    label={s.name || s.sector}
                    meta={pct(change)}
                    viz={<PerformanceLine color={change >= 0 ? "var(--v3-moss)" : "var(--v3-crimson)"} />}
                  />
                );
              })}
            </div>
          </section>
        )}

        {data.picks.length > 0 && (
          <section>
            <SectionHead title="Portfolio-aware picks" count={`${data.picks.length} ideas`} />
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {data.picks.map((p, i) => (
                <div key={i} style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 10, padding: "10px 14px", display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontFamily: "var(--v3-font-mono)", fontSize: 12, color: "var(--v3-ink-2)", minWidth: 60 }}>{p.symbol || p.ticker}</span>
                  <span style={{ flex: 1, fontSize: 12, color: "var(--v3-ink-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name || p.company_name || ""}</span>
                  {p.stage && <span style={{ padding: "2px 7px", borderRadius: 999, background: "var(--v3-bg-3)", color: "var(--v3-ink-3)", fontSize: 10, fontFamily: "var(--v3-font-mono)" }}>{p.stage}</span>}
                  {p.score != null && <span className="v3-data" style={{ fontSize: 11, color: "var(--v3-moss)" }}>{Number(p.score).toFixed(1)}</span>}
                </div>
              ))}
            </div>
          </section>
        )}

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          <TinyChip onClick={() => navigate("/v3/chat?q=Summarise+today%27s+market")}>Summarise today</TinyChip>
          <TinyChip onClick={() => navigate("/v3/chat?q=Which+sectors+should+I+watch")}>Which sectors to watch</TinyChip>
          <TinyChip onClick={() => navigate("/v3/chat?q=Should+I+deploy+capital+today")}>Deploy capital today?</TinyChip>
        </div>
      </div>
    </ScreenContainer>
  );
}
