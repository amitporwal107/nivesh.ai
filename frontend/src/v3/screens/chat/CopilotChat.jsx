import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useOutletContext } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import CompactCard from "../../components/CompactCard";
import Composer from "../../components/Composer";
import TinyChip from "../../components/TinyChip";
import SectionHead from "../../components/SectionHead";
import CategoryBadge from "../../components/CategoryBadge";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { OverlapDonut, FundCountHistogram } from "../../components/viz";
import { usePersona, usePortfolioSummary, getCatalogFor, askCopilot } from "../../adapters";

export default function CopilotChat() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const location = useLocation();
  const { persona } = usePersona();
  const { data: portfolio } = usePortfolioSummary();
  const catalog = getCatalogFor(persona.id);

  const initialQuery = useMemo(() => new URLSearchParams(location.search).get("q") || "", [location.search]);
  const [messages, setMessages] = useState([]);
  const [pending, setPending] = useState(false);
  const submittedInitial = useRef(false);

  // Send a question to the backend and append both the question and the answer.
  const handleSubmit = async ({ text, model }) => {
    if (!text) return;
    const next = [...messages, makeQuestion(text)];
    setMessages(next);
    setPending(true);
    const res = await askCopilot({
      question: text,
      history: next,
      model: model || "gpt-4o",
    });
    setPending(false);
    if (res.ok && res.text) {
      setMessages((cur) => [...cur, makeAnswer(text, res.text, portfolio, catalog)]);
    } else {
      // Backend unreachable — fall back to a local stub so the UX never dead-ends.
      setMessages((cur) => [...cur, makeFallbackAnswer(text, portfolio, catalog, res.error)]);
    }
  };

  // Fire the URL-query question once on mount.
  useEffect(() => {
    if (!initialQuery || submittedInitial.current) return;
    submittedInitial.current = true;
    handleSubmit({ text: initialQuery });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery]);

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
          <>
            {messages.map((m, i) => <MessageRow key={i} message={m} isDesktop={isDesktop} onPick={handleSubmit} />)}
            {pending && <TypingRow />}
          </>
        )}
      </div>

      <Composer onSubmit={handleSubmit} pickerMode={isDesktop ? "popover" : "sheet"} personaId={persona.id} sticky />
    </ScreenContainer>
  );
}

function makeQuestion(text) {
  return { kind: "q", role: "user", text, content: text };
}

function categoryFor(text) {
  const lower = (text || "").toLowerCase();
  if (lower.includes("overlap") || lower.includes("risk") || lower.includes("diversif")) return "risk";
  if (lower.includes("perform") || lower.includes("return") || lower.includes("benchmark")) return "performance";
  if (lower.includes("tax") || lower.includes("harvest") || lower.includes("ltcg")) return "tax";
  if (lower.includes("goal") || lower.includes("sip") || lower.includes("retirement")) return "goal";
  return "health";
}

function makeAnswer(text, responseText, portfolio, catalog) {
  const category = categoryFor(text);
  return {
    kind: "a",
    role: "assistant",
    category,
    title: text,
    summary: responseText,
    content: responseText,
    viz: category === "risk"
      ? <OverlapDonut value={portfolio.overlap.maxPct ?? 0} color="var(--v3-crimson)" size={64} />
      : category === "health"
      ? <FundCountHistogram count={portfolio.funds.count ?? 0} height={64} />
      : null,
    followups: catalog.advanced.slice(0, 4).map((p) => p.label),
  };
}

// Used only if the backend call fails — keeps the UI alive with a local stub.
function makeFallbackAnswer(text, portfolio, catalog, error) {
  const category = categoryFor(text);
  const summary = pickAnswerSummary(category, portfolio);
  return {
    kind: "a",
    role: "assistant",
    category,
    title: text,
    summary: error
      ? `${summary}\n\n(showing demo response — backend unreachable${error.status ? ` · ${error.status}` : ""})`
      : summary,
    content: summary,
    viz: category === "risk"
      ? <OverlapDonut value={portfolio.overlap.maxPct ?? 0} color="var(--v3-crimson)" size={64} />
      : category === "health"
      ? <FundCountHistogram count={portfolio.funds.count ?? 0} height={64} />
      : null,
    followups: catalog.advanced.slice(0, 4).map((p) => p.label),
  };
}

function TypingRow() {
  return (
    <div
      style={{
        background: "var(--v3-bg-2)",
        border: "1px solid var(--v3-line)",
        borderRadius: 18,
        padding: 14,
        display: "inline-flex",
        gap: 6,
        alignItems: "center",
        alignSelf: "flex-start",
      }}
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          aria-hidden
          style={{
            width: 6,
            height: 6,
            borderRadius: 999,
            background: "var(--v3-ink-3)",
            animation: `v3-typing 1s ${i * 0.15}s infinite`,
          }}
        />
      ))}
      <span className="v3-eyebrow" style={{ marginLeft: 6, color: "var(--v3-ink-3)" }}>thinking…</span>
      <style>{`@keyframes v3-typing { 0%, 80%, 100% { opacity: 0.3; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-2px); } }`}</style>
    </div>
  );
}

function pickAnswerSummary(category, p) {
  switch (category) {
    case "risk":
      return p.overlap.maxPct != null
        ? `Your portfolio shows ${p.overlap.pairs} fund pairs with overlap above 65%. The highest overlapping pair shares ${p.overlap.maxPct}% of the same underlying stocks — that's real concentration risk dressed up as diversification.`
        : "Ask Copilot to analyse your fund overlap — connect your portfolio first.";
    case "performance":
      return p.performance.ytd != null
        ? `YTD return is ${p.performance.ytd}% against a benchmark of ${p.performance.benchmarkYtd}%.`
        : "YTD performance data is loading — ask Copilot for a detailed breakdown.";
    case "tax":
      return p.tax.unrealizedLtcg != null
        ? `You have ₹${p.tax.unrealizedLtcg.toLocaleString("en-IN")} of unrealized LTCG. ${p.tax.ltcgFree != null ? `₹${p.tax.ltcgFree.toLocaleString("en-IN")} of your ₹1.25L FY exemption is still unused.` : ""}`
        : "Ask Copilot for your LTCG breakdown and harvest opportunities.";
    case "goal":
      return p.goals.length
        ? `Your retirement goal is ${p.goals[0].progress}% funded. Closing the gap needs an extra ₹${p.sip.gap ? (p.sip.gap / 1000).toFixed(0) + "k" : "—"} / month.`
        : "No goals linked yet — ask Copilot to set up a goal-based plan.";
    default:
      return p.funds.count != null
        ? `Your portfolio holds ${p.funds.count} funds across ${p.funds.amcCount} AMCs — the ideal range is ${p.funds.idealMin}–${p.funds.idealMax}.`
        : "Connect your portfolio to get a personalised analysis.";
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
