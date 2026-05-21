import React, { useRef, useState } from "react";
import { Send } from "lucide-react";
import Pill from "./Pill";
import AgentPicker from "./pickers/AgentPicker";
import ModelPicker from "./pickers/ModelPicker";
import { useSheet } from "../hooks/useSheet";

const AGENT_LABEL = {
  auto: "Auto-route",
  portfolio_analyst: "Portfolio Analyst",
  mf_analyst: "MF Research",
  market_analyst: "Market Strategist",
  tax_agent: "Tax Agent",
  risk_analyst: "Risk & Compliance",
  report_generator: "Report Generator",
};

const MODEL_LABEL = {
  "haiku-4.5": "Haiku 4.5",
  "gpt-4o-mini": "GPT-4o mini",
  "gpt-4o": "Balanced · GPT-4o",
  "sonnet-4.6": "Balanced · Sonnet",
  "opus-4.7": "Deep · Opus 4.7",
  o3: "Deep · o3",
};

export default function Composer({
  placeholder = "Ask anything · /overlap /sip /tax …",
  onSubmit,
  defaultValue = "",
  pickerMode = "sheet",
  personaId,
  sticky = true,
  hint,
}) {
  const [value, setValue] = useState(defaultValue);
  const [agent, setAgent] = useState("auto");
  const [model, setModel] = useState("gpt-4o");
  const agentSheet = useSheet();
  const modelSheet = useSheet();
  const agentRef = useRef(null);
  const modelRef = useRef(null);

  const submit = () => {
    if (!value.trim()) return;
    onSubmit && onSubmit({ text: value.trim(), agent, model });
    setValue("");
  };

  return (
    <div
      style={{
        ...(sticky
          ? {
              position: "sticky",
              bottom: 0,
              background: "linear-gradient(180deg, transparent, var(--v3-bg-1) 30%)",
              padding: "12px 0 16px 0",
              zIndex: 20,
            }
          : { padding: 0 }),
      }}
    >
      <div
        style={{
          background: "var(--v3-bg-2)",
          border: "1px solid var(--v3-line-strong)",
          borderRadius: "var(--v3-r-xl)",
          padding: "8px 8px 8px 16px",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          style={{
            flex: 1,
            fontSize: 14,
            padding: "8px 0",
            background: "transparent",
            color: "var(--v3-ink-1)",
            border: "none",
            outline: "none",
            fontFamily: "var(--v3-font-sans)",
          }}
          aria-label="Ask the copilot"
        />
        <button
          type="button"
          onClick={submit}
          aria-label="Send"
          style={{
            width: 36,
            height: 36,
            borderRadius: 12,
            background: "var(--v3-saffron)",
            color: "var(--v3-saffron-ink)",
            display: "grid",
            placeItems: "center",
            cursor: "pointer",
            border: "none",
            transition: "transform var(--v3-dur-fast) var(--v3-ease)",
          }}
          onMouseDown={(e) => (e.currentTarget.style.transform = "scale(0.92)")}
          onMouseUp={(e) => (e.currentTarget.style.transform = "scale(1)")}
          onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}
        >
          <Send size={16} />
        </button>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, padding: "0 4px", flexWrap: "wrap" }}>
        <span ref={agentRef}>
          <Pill dotColor="var(--v3-indigo)" active={agentSheet.open} onClick={agentSheet.show}>
            {AGENT_LABEL[agent] || "Auto-route"}
          </Pill>
        </span>
        <span ref={modelRef}>
          <Pill dotColor="var(--v3-gold)" active={modelSheet.open} onClick={modelSheet.show}>
            {MODEL_LABEL[model] || "Balanced"}
          </Pill>
        </span>
        <span style={{ flex: 1 }} />
        <span className="v3-eyebrow" style={{ color: "var(--v3-ink-4)" }}>
          {hint || "SEBI-registered educational"}
        </span>
      </div>

      <AgentPicker
        open={agentSheet.open}
        onClose={agentSheet.close}
        value={agent}
        onChange={setAgent}
        mode={pickerMode}
        anchorRef={agentRef}
        personaId={personaId}
      />
      <ModelPicker
        open={modelSheet.open}
        onClose={modelSheet.close}
        value={model}
        onChange={setModel}
        mode={pickerMode}
        anchorRef={modelRef}
      />
    </div>
  );
}
