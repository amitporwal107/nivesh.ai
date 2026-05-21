import React from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { Calendar, Phone, MessageSquare } from "lucide-react";
import HeroCard from "../../components/HeroCard";
import CompactCard from "../../components/CompactCard";
import SectionHead from "../../components/SectionHead";
import PersonaAvatar from "../../components/PersonaAvatar";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";

export default function Advisor() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Advisor" title="Human advice when it matters" />
      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 40 }}>
        <div
          style={{
            background: "linear-gradient(135deg, var(--v3-bg-2), var(--v3-bg-3))",
            border: "1px solid var(--v3-line-strong)",
            borderRadius: 20,
            padding: 18,
            display: "flex",
            alignItems: "center",
            gap: 14,
          }}
        >
          <PersonaAvatar iconKey="diamond" accent="indigo" size={56} radius={14} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)" }}>Your advisor</div>
            <div style={{ fontFamily: "var(--v3-font-display)", fontWeight: 600, fontSize: 18, color: "var(--v3-ink-1)" }}>Priya Sharma, CFP®</div>
            <div style={{ color: "var(--v3-ink-3)", fontSize: 12, marginTop: 4 }}>SEBI RIA-2025-118 · 12 yrs · 240+ clients</div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <ActionBtn icon={MessageSquare} label="Chat" onClick={() => navigate("/chat")} />
            <ActionBtn icon={Phone} label="Call" />
            <ActionBtn icon={Calendar} label="Book" />
          </div>
        </div>

        <HeroCard
          layout={isDesktop ? "desktop" : "mobile"}
          category="goal"
          priorityLabel="Next session"
          title="Quarterly review · Thursday 4:30 PM"
          description={isDesktop ? "We'll walk through rebalance options, tax harvest plan, and update the retirement projection with last quarter's data. 45 minutes, video." : null}
          viz={
            <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
              <div style={{ flex: 1 }}>
                <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)" }}>Agenda</div>
                <ul style={{ margin: 8, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
                  {["Rebalance options", "Tax harvest plan", "Retirement projection update", "Q&A"].map((t, i) => (
                    <li key={i} style={{ color: "var(--v3-ink-2)", fontSize: 13 }}>· {t}</li>
                  ))}
                </ul>
              </div>
            </div>
          }
          ctaText="Reschedule or join early →"
        />

        <SectionHead title="What we can help with" count="6 areas" />
        <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr 1fr", gap: 12 }}>
          {[
            { c: "goal", l: "Goal planning" },
            { c: "tax", l: "Tax strategy" },
            { c: "risk", l: "Risk profile review" },
            { c: "performance", l: "Performance attribution" },
            { c: "health", l: "Portfolio overhaul" },
            { c: "goal", l: "Estate & insurance" },
          ].map((it, i) => (
            <CompactCard key={i} category={it.c} label={it.l} meta="Book a session" onClick={() => navigate("/chat?q=" + encodeURIComponent(it.l))} />
          ))}
        </div>
      </div>
    </ScreenContainer>
  );
}

function ActionBtn({ icon: Icon, label, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      style={{
        width: 38,
        height: 38,
        borderRadius: 12,
        background: "var(--v3-bg-3)",
        border: "1px solid var(--v3-line)",
        color: "var(--v3-ink-2)",
        display: "grid",
        placeItems: "center",
        cursor: "pointer",
      }}
    >
      <Icon size={16} />
    </button>
  );
}
