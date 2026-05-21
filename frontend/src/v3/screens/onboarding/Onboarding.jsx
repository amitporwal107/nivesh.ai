import React, { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { ArrowRight, Check } from "lucide-react";
import BrandMark from "../../components/BrandMark";
import PersonaAvatar from "../../components/PersonaAvatar";
import ScreenContainer from "../../components/layout/ScreenContainer";
import { PERSONAS, usePersona } from "../../adapters";

export default function Onboarding() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const { setPersona } = usePersona();
  const [step, setStep] = useState(0);
  const [selectedId, setSelectedId] = useState(null);

  const confirm = () => {
    if (!selectedId) return;
    setPersona(selectedId);
    navigate("/home", { replace: true });
  };

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <div style={{ paddingTop: 36, display: "flex", flexDirection: "column", gap: 24 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <BrandMark size={48} withWordmark />
          <span className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", marginTop: 12 }}>
            STEP {step + 1} OF 2
          </span>
          <h1
            style={{
              fontFamily: "var(--v3-font-display)",
              fontWeight: 600,
              fontSize: isDesktop ? 32 : 24,
              letterSpacing: "-0.015em",
              color: "var(--v3-ink-1)",
              maxWidth: 580,
            }}
          >
            {step === 0 ? "How do you invest today?" : "All set."}
          </h1>
          <p style={{ color: "var(--v3-ink-2)", fontSize: 14, lineHeight: 1.55, maxWidth: 580 }}>
            {step === 0
              ? "Pick the one that's closest. We'll tune every answer, recommendation, and chart to your context. You can change this any time."
              : "We've tuned the experience to your persona. Tap continue to enter the workspace."}
          </p>
        </div>

        {step === 0 && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr",
              gap: 12,
            }}
          >
            {PERSONAS.filter((p) => p.id !== "universal").map((p) => {
              const active = selectedId === p.id;
              return (
                <button
                  type="button"
                  key={p.id}
                  onClick={() => setSelectedId(p.id)}
                  style={{
                    textAlign: "left",
                    background: active ? "var(--v3-bg-3)" : "var(--v3-bg-2)",
                    border: `1px solid ${active ? "var(--v3-saffron)" : "var(--v3-line)"}`,
                    borderRadius: 16,
                    padding: 16,
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 14,
                    cursor: "pointer",
                    transition: "all var(--v3-dur) var(--v3-ease)",
                  }}
                >
                  <PersonaAvatar iconKey={p.avatarIcon} accent={p.accent} size={40} radius={12} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: "var(--v3-font-display)", fontWeight: 600, fontSize: 16, color: "var(--v3-ink-1)" }}>
                      {p.name}
                    </div>
                    <div style={{ color: "var(--v3-ink-3)", fontSize: 12.5, lineHeight: 1.5, marginTop: 4 }}>{p.tagline}</div>
                  </div>
                  {active && (
                    <div
                      style={{
                        background: "var(--v3-saffron)",
                        color: "var(--v3-saffron-ink)",
                        borderRadius: 999,
                        width: 22,
                        height: 22,
                        display: "grid",
                        placeItems: "center",
                        flexShrink: 0,
                      }}
                    >
                      <Check size={14} strokeWidth={3} />
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        )}

        <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
          <button
            type="button"
            onClick={() => {
              if (step === 0 && selectedId) setStep(1);
              else if (step === 1) confirm();
              else navigate("/home", { replace: true });
            }}
            disabled={step === 0 && !selectedId}
            style={{
              flex: 1,
              padding: "14px 20px",
              background: step === 0 && !selectedId ? "var(--v3-bg-3)" : "var(--v3-saffron)",
              color: step === 0 && !selectedId ? "var(--v3-ink-3)" : "var(--v3-saffron-ink)",
              borderRadius: 14,
              fontWeight: 600,
              cursor: step === 0 && !selectedId ? "not-allowed" : "pointer",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              fontSize: 14,
              transition: "all var(--v3-dur) var(--v3-ease)",
            }}
          >
            {step === 0 ? "Continue" : "Enter workspace"}
            <ArrowRight size={16} />
          </button>
          <button
            type="button"
            onClick={() => navigate("/home", { replace: true })}
            style={{
              padding: "14px 16px",
              color: "var(--v3-ink-2)",
              borderRadius: 14,
              border: "1px solid var(--v3-line)",
              fontSize: 13,
              cursor: "pointer",
              background: "transparent",
            }}
          >
            Skip
          </button>
        </div>
      </div>
    </ScreenContainer>
  );
}
