import React, { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useOutletContext } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import IconButton from "../../components/IconButton";
import CompactCard from "../../components/CompactCard";
import HeroCard from "../../components/HeroCard";
import Composer from "../../components/Composer";
import TinyChip from "../../components/TinyChip";
import SectionHead from "../../components/SectionHead";
import CategoryBadge from "../../components/CategoryBadge";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { OverlapDonut, FundCountHistogram } from "../../components/viz";
import { usePersona, usePortfolioSummary, getCatalogFor } from "../../adapters";

export default function CopilotChat() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const location = useLocation();
  const { persona } = usePersona();
  const { data: portfolio } = usePortfolioSummary();
  const catalog = getCatalogFor(persona.id);

  const initialQuery = useMemo(() => new URLSearchParams(location.search).get("q") || "", [location.search]);

  const [messages, setMessages] = useState(() => (initialQuery ? [makeQuestion(initialQuery), makeAnswer(initialQuery, portfolio, catalog)] : []));

  useEffect(() => {
    if (!initialQuery) return;
    setMessages([makeQuestion(initialQuery), makeAnswer(initialQuery, portfolio, catalog)]);
  }, [initialQuery, portfolio, catalog]);

  const handleSubmit = ({ text }) => {
    setMessages((prev) => [...prev, makeQuestion(text), makeAnswer(text, portfolio, catalog)]);
  };

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      {isDesktop ? (
        <TopBar variant="desktop" eyebrow="Copilot" title="Ask your portfolio anything" />
      ) : (
        <TopBar
          variant="mobile"
          actions={[
            { icon: ArrowLeft, label: "Back", onClick: () => navigate(-1) },
            { icon: undefined, label: "Menu", onClick: () => navigate("/settings") },
          ]}
        />
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 20, paddingBottom: 24 }}>
        {messages.length === 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            <SectionHead title="Suggested" />
            <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(2, 1fr)" : "1fr", gap: 12 }}>
              {catalog.secondary.slice(0, 4).map((p, i) => (
                <CompactCard
                  key={i}
                  category={p.category}
                  label={p.label}
                  meta="Tap to ask"
                  onClick={() => handleSubmit({ text: p.label })}
                />
              ))}
            </div>
          </div>
        ) : (
          messages.map((m, i) => <MessageRow key={i} message={m} isDesktop={isDesktop} onPick={handleSubmit} />)
        )}
      </div>

      <Composer onSubmit={handleSubmit} pickerMode={isDesktop ? "popover" : "sheet"} personaId={persona.id} sticky />
    </ScreenContainer>
  );
}

function makeQuestion(text) {
  return { kind: "q", text };
}

function makeAnswer(text, portfolio, catalog) {
  const lower = text.toLowerCase();
  let category = "health";
  if (lower.includes("overlap") || lower.includes("risk") || lower.includes("diversif")) category = "risk";
  else if (lower.includes("perform") || lower.includes("return") || lower.includes("benchmark")) category = "performance";
  else if (lower.includes("tax") || lower.includes("harvest") || lower.includes("ltcg")) category = "tax";
  else if (lower.includes("goal") || lower.includes("sip") || lower.includes("retirement")) category = "goal";

  return {
    kind: "a",
    category,
    title: text,
    summary: pickAnswerSummary(category, portfolio),
    viz: category === "risk"
      ? <OverlapDonut value={portfolio.overlap.maxPct} color="var(--v3-crimson)" size={64} />
      : category === "health"
      ? <FundCountHistogram count={portfolio.funds.count} height={64} />
      : null,
    followups: catalog.advanced.slice(0, 4).map((p) => p.label),
  };
}

function pickAnswerSummary(category, p) {
  switch (category) {
    case "risk":
      return `Your portfolio shows ${p.overlap.pairs} fund pairs with overlap above 65%. The highest overlapping pair shares ${p.overlap.maxPct}% of the same underlying stocks — that's real concentration risk dressed up as diversification.`;
    case "performance":
      return `YTD return is ${p.performance.ytd}% against a benchmark of ${p.performance.benchmarkYtd}%. 2 of your 11 funds are dragging — a small-cap and a sectoral fund. The other 9 are at or above category median.`;
    case "tax":
      return `You have ₹${p.tax.unrealizedLtcg.toLocaleString("en-IN")} of unrealized LTCG. ₹${p.tax.ltcgFree.toLocaleString("en-IN")} of your ₹1.25L FY exemption is still unused — there's room to harvest before March 31.`;
    case "goal":
      return `Your retirement goal is ${p.goals[0].progress}% funded. At current SIPs you'll reach ${(p.goals[0].progress + 32)}% of target by year 10. Closing the gap needs an extra ₹${(p.sip.gap / 1000).toFixed(0)}k / month.`;
    default:
      return `Your portfolio holds ${p.funds.count} funds across ${p.funds.amcCount} AMCs — the ideal range is ${p.funds.idealMin}–${p.funds.idealMax}. Consolidating to ~7 funds without losing exposure is the single highest-impact action this quarter.`;
  }
}

function MessageRow({ message, isDesktop, onPick }) {
  if (message.kind === "q") {
    return (
      <div
        style={{
          alignSelf: "flex-end",
          maxWidth: "85%",
          background: "var(--v3-saffron-soft)",
          color: "var(--v3-ink-1)",
          padding: "10px 14px",
          borderRadius: 18,
          border: "1px solid var(--v3-line-strong)",
          fontSize: 14,
          fontWeight: 500,
          marginLeft: "auto",
          marginRight: 0,
        }}
      >
        {message.text}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div
        style={{
          background: "var(--v3-bg-2)",
          border: "1px solid var(--v3-line)",
          borderRadius: 18,
          padding: 18,
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <CategoryBadge category={message.category} />
          <span className="v3-eyebrow" style={{ color: "var(--v3-ink-3)" }}>Answer</span>
        </div>
        <div style={{ fontFamily: "var(--v3-font-display)", fontWeight: 600, fontSize: isDesktop ? 22 : 18, color: "var(--v3-ink-1)", letterSpacing: "-0.01em", lineHeight: 1.25 }}>
          {message.title}
        </div>
        <p style={{ color: "var(--v3-ink-2)", fontSize: 14, lineHeight: 1.6 }}>{message.summary}</p>
        {message.viz && (
          <div style={{ background: "#0e0d0b", border: "1px solid var(--v3-line)", borderRadius: 12, padding: 14, display: "flex", justifyContent: "center" }}>
            {message.viz}
          </div>
        )}
      </div>
      {message.followups?.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {message.followups.map((q, i) => (
            <TinyChip key={i} onClick={() => onPick({ text: q })}>{q}</TinyChip>
          ))}
        </div>
      )}
    </div>
  );
}
