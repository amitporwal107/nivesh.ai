import React from "react";
import { Compass, BarChart3, Search, TrendingUp, IndianRupee, Shield, FileText, Check } from "lucide-react";
import Sheet from "./Sheet";

const AGENTS = [
  { id: "auto", name: "Auto-route", desc: "Picks the right specialist automatically based on your question.", icon: Compass, tag: "RECOMMENDED" },
  { id: "portfolio_analyst", name: "Portfolio Analyst", desc: "Health score, drift, rebalance, holdings, allocation.", icon: BarChart3 },
  { id: "mf_analyst", name: "MF Research", desc: "Fund verdicts, overlap, scorecard, screener.", icon: Search, personaTag: "mf_focused" },
  { id: "market_analyst", name: "Market Strategist", desc: "Daily brief, sector rotation, FII / DII flows.", icon: TrendingUp },
  { id: "tax_agent", name: "Tax Agent", desc: "Capital gains, harvesting, FY planning.", icon: IndianRupee },
  { id: "risk_analyst", name: "Risk & Compliance", desc: "Risk profile fit, suitability, SEBI disclosures.", icon: Shield },
  { id: "report_generator", name: "Report Generator", desc: "PDF reports, monthly summaries, portfolio statements.", icon: FileText },
];

export default function AgentPicker({ open, onClose, value = "auto", onChange, mode = "sheet", anchorRef, personaId }) {
  return (
    <Sheet open={open} onClose={onClose} title="Agent picker" subtitle="Opens from Auto-route pill" mode={mode} anchorRef={anchorRef}>
      <div>
        {AGENTS.map((a) => {
          const Icon = a.icon;
          const active = value === a.id;
          const isPersonaTagged = a.personaTag === personaId;
          return (
            <button
              type="button"
              key={a.id}
              onClick={() => {
                onChange && onChange(a.id);
                onClose && onClose();
              }}
              style={{
                width: "100%",
                textAlign: "left",
                display: "flex",
                gap: 14,
                alignItems: "flex-start",
                padding: 14,
                borderRadius: 12,
                background: active ? "var(--v3-bg-2)" : "transparent",
                borderLeft: active ? "3px solid var(--v3-saffron)" : "3px solid transparent",
                cursor: "pointer",
                transition: "background var(--v3-dur) var(--v3-ease)",
                marginBottom: 2,
              }}
              onMouseEnter={(e) => !active && (e.currentTarget.style.background = "var(--v3-bg-2)")}
              onMouseLeave={(e) => !active && (e.currentTarget.style.background = "transparent")}
            >
              <div
                aria-hidden
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: 10,
                  background: active ? "var(--v3-saffron-soft)" : "var(--v3-bg-3)",
                  color: active ? "var(--v3-saffron)" : "var(--v3-ink-2)",
                  display: "grid",
                  placeItems: "center",
                  flexShrink: 0,
                }}
              >
                <Icon size={18} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: "var(--v3-ink-1)" }}>{a.name}</span>
                  {a.tag === "RECOMMENDED" && <Tag label="RECOMMENDED" />}
                  {isPersonaTagged && <Tag label="YOUR PERSONA" tone="saffron" />}
                </div>
                <div style={{ fontSize: 12, color: "var(--v3-ink-3)", lineHeight: 1.45 }}>{a.desc}</div>
              </div>
              {active && <Check size={16} style={{ color: "var(--v3-saffron)", alignSelf: "center", flexShrink: 0 }} />}
            </button>
          );
        })}
      </div>
    </Sheet>
  );
}

function Tag({ label, tone = "default" }) {
  const bg = tone === "saffron" ? "var(--v3-saffron-soft)" : "var(--v3-bg-3)";
  const fg = tone === "saffron" ? "var(--v3-saffron)" : "var(--v3-ink-3)";
  return (
    <span
      style={{
        fontFamily: "var(--v3-font-mono)",
        fontSize: 9,
        background: bg,
        color: fg,
        padding: "2px 6px",
        borderRadius: 4,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
      }}
    >
      {label}
    </span>
  );
}
