import React from "react";
import { useOutletContext } from "react-router-dom";
import { Clock } from "lucide-react";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";

export default function Advisor() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Advisor" title="Human advice when it matters" />
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "72px 24px",
          gap: 18,
          textAlign: "center",
        }}
      >
        <span
          style={{
            width: 64,
            height: 64,
            borderRadius: 18,
            background: "var(--v3-bg-2)",
            border: "1px solid var(--v3-line)",
            display: "grid",
            placeItems: "center",
            color: "var(--v3-ink-3)",
          }}
        >
          <Clock size={28} strokeWidth={1.5} />
        </span>
        <div
          style={{
            fontFamily: "var(--v3-font-display)",
            fontWeight: 600,
            fontSize: isDesktop ? 22 : 18,
            color: "var(--v3-ink-1)",
            letterSpacing: "-0.01em",
          }}
        >
          Advisor matching coming soon
        </div>
        <p
          style={{
            fontSize: 14,
            color: "var(--v3-ink-3)",
            lineHeight: 1.55,
            maxWidth: 320,
            margin: 0,
          }}
        >
          We're connecting with SEBI-registered advisors. In the meantime, ask the AI Copilot — it handles most portfolio questions instantly.
        </p>
      </div>
    </ScreenContainer>
  );
}
