/**
 * Advisor (#ct-advisor) — the MFD cockpit: AUM & book health, a "who to call
 * first" client-health monitor, and nine client-driven workflows.
 */
import { ReactNode } from "react";
import { Mark, ScoreRing } from "../parts";
import { useAskProps } from "../useEnterCopilot";

const STATS = [
  { k: "CLIENTS", v: "128", sub: "42 ACTIVE THIS WK", c: "rgb(var(--ink))" },
  { k: "AT RISK", v: "7", sub: "₹6.4CR AUM", c: "var(--danger-hex)" },
  { k: "REVIEWS DUE", v: "14", sub: "OLDEST 92 DAYS", c: "var(--amber)" },
  { k: "IDLE CASH", v: "₹1.2Cr", sub: "22 CLIENTS", c: "var(--mint)" },
];

type Hp = { color: string };
const CLIENTS: Array<{ name: string; aum: string; score: number; hp: Hp; flag: string; flagC: string; action: string; stake: string; stakeC: string }> = [
  { name: "Rohan Shah", aum: "₹1.8 Cr", score: 42, hp: { color: "var(--danger-hex)" }, flag: "Churn risk · 2 redemptions", flagC: "var(--danger-hex)", action: "Call this week", stake: "₹1.8 Cr at stake", stakeC: "var(--danger-hex)" },
  { name: "Vikram Sethi", aum: "₹1.2 Cr", score: 38, hp: { color: "var(--danger-hex)" }, flag: "₹40L idle 90+ days", flagC: "var(--amber)", action: "Deploy idle cash", stake: "+₹1.6L/yr", stakeC: "var(--mint)" },
  { name: "Priya Das", aum: "₹56 L", score: 55, hp: { color: "var(--amber)" }, flag: "Review 92 days overdue", flagC: "var(--amber)", action: "Schedule review", stake: "—", stakeC: "rgb(var(--ink-3))" },
  { name: "Meera Nair", aum: "₹94 L", score: 61, hp: { color: "var(--amber)" }, flag: "71% fund overlap", flagC: "var(--indigo-hex)", action: "Propose consolidation", stake: "₹9k/yr fees", stakeC: "var(--mint)" },
  { name: "Kavya Menon", aum: "₹78 L", score: 74, hp: { color: "var(--mint)" }, flag: "SIP step-up eligible", flagC: "var(--mint)", action: "Propose +10% step-up", stake: "+₹4k/mo", stakeC: "var(--mint)" },
  { name: "Arjun Rao", aum: "₹2.4 Cr", score: 88, hp: { color: "var(--mint)" }, flag: "On track", flagC: "rgb(var(--ink-3))", action: "No action", stake: "—", stakeC: "rgb(var(--ink-3))" },
];

function hpStyle(c: string): React.CSSProperties {
  const map: Record<string, [string, string]> = {
    "var(--danger-hex)": ["rgb(var(--neg) / 0.30)", "var(--danger-soft)"],
    "var(--amber)": ["rgb(var(--warm) / 0.30)", "var(--amber-soft)"],
    "var(--mint)": ["rgb(var(--pos) / 0.28)", "var(--mint-soft)"],
  };
  const [border, bg] = map[c] ?? ["var(--line-2)", "transparent"];
  return { color: c, borderColor: border, background: bg };
}

type Wf = { eyebrow: string; badge?: ReactNode; title: string; prompt: string; synth: ReactNode; body: ReactNode; footL: ReactNode; cta: string; ctaMint?: boolean };
const WORKFLOWS: Wf[] = [
  {
    eyebrow: "A · AUM HEALTH AGENT", badge: <span className="nv-pill nv-pill-indigo" style={{ fontSize: 9 }}>BOOK LEVEL</span>,
    title: "AUM & book health", prompt: "How's my book doing this quarter?",
    synth: <>AUM up <span style={{ color: "var(--mint)" }}>2.1%</span>, but 7 clients are dragging book health to 72.</>,
    body: <div style={{ display: "flex", gap: 8 }}><div className="ct-wrow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>AUM</span><span className="nv-num" style={{ color: "rgb(var(--ink))" }}>₹42.8Cr</span></div><div className="ct-wrow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>HEALTH</span><span className="nv-num" style={{ color: "var(--mint)" }}>72</span></div></div>,
    footL: <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>128 CLIENTS</span>, cta: "Open dashboard ▸", ctaMint: true,
  },
  {
    eyebrow: "B · RETENTION AGENT", title: "At-risk & churn", prompt: "Which clients might leave?",
    synth: <><span style={{ color: "var(--danger-hex)" }}>7 clients</span> show churn signals — ₹6.4Cr of AUM in play.</>,
    body: <><div className="ct-wrow"><span style={{ color: "var(--danger-hex)" }}>↑ Rohan Shah · 2 redemptions</span><span className="nv-num" style={{ color: "var(--danger-hex)" }}>₹1.8Cr</span></div><div className="ct-wrow"><span style={{ color: "var(--danger-hex)" }}>↑ Nikhil B · went quiet 60d</span><span className="nv-num" style={{ color: "var(--danger-hex)" }}>₹90L</span></div></>,
    footL: <span className="nv-serif nv-num" style={{ fontSize: 16, color: "var(--danger-hex)" }}>₹6.4Cr at risk</span>, cta: "Call list ▸",
  },
  {
    eyebrow: "C · REVIEW AGENT", title: "Reviews due", prompt: "Who's overdue for a portfolio review?",
    synth: <><span style={{ color: "var(--amber)" }}>14 reviews</span> overdue — I've drafted each agenda.</>,
    body: <><div className="ct-wrow"><span style={{ color: "var(--amber)" }}>Priya Das</span><span className="nv-mono" style={{ fontSize: 10, color: "var(--amber)" }}>92 DAYS</span></div><div className="ct-wrow"><span style={{ color: "var(--amber)" }}>Sanjay K</span><span className="nv-mono" style={{ fontSize: 10, color: "var(--amber)" }}>74 DAYS</span></div></>,
    footL: <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>AGENDAS READY</span>, cta: "Schedule all ▸", ctaMint: true,
  },
  {
    eyebrow: "D · TAX AGENT · MAR 31", title: "Harvest across the book", prompt: "Any tax savings for my clients this FY?",
    synth: <><span style={{ color: "var(--mint)" }}>₹3.1L</span> harvestable across 19 clients before Mar 31.</>,
    body: <div style={{ display: "flex", gap: 8 }}><div className="ct-wrow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>CLIENTS</span><span className="nv-num">19</span></div><div className="ct-wrow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>SAVED</span><span className="nv-num" style={{ color: "var(--mint)" }}>₹3.1L</span></div></div>,
    footL: <span className="nv-pill nv-pill-danger" style={{ fontSize: 9 }}>BEFORE MAR 31</span>, cta: "Bulk propose ▸", ctaMint: true,
  },
  {
    eyebrow: "E · DEPLOY AGENT · SCORE A", title: "Idle cash to deploy", prompt: "Which clients are sitting on cash?",
    synth: <><span style={{ color: "var(--mint)" }}>₹1.2Cr</span> idle across 22 clients — losing to inflation.</>,
    body: <><div className="ct-wrow"><span>Vikram Sethi</span><span className="nv-num">₹40L · 90d</span></div><div className="ct-wrow"><span>Anita R</span><span className="nv-num">₹18L · 60d</span></div></>,
    footL: <span className="nv-serif nv-num" style={{ fontSize: 16, color: "var(--mint)" }}>+₹4.8L/yr</span>, cta: "Deploy plan ▸",
  },
  {
    eyebrow: "F · ALLOCATION AGENT · DRIFT", title: "Off-mandate clients", prompt: "Who's drifted from their mandate?",
    synth: <><span style={{ color: "var(--amber)" }}>11 clients</span> drifted 5%+ from their target mix.</>,
    body: <><div className="ct-wrow"><span style={{ color: "var(--amber)" }}>Meera Nair · +9pt equity</span><span className="nv-num" style={{ color: "var(--amber)" }}>HIGH</span></div><div className="ct-wrow"><span>Deepak V · +6pt equity</span><span className="nv-num">MED</span></div></>,
    footL: <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>11 CLIENTS</span>, cta: "Rebalance batch ▸", ctaMint: true,
  },
  {
    eyebrow: "G · SIP AGENT · GROWTH", title: "SIP step-up opportunities", prompt: "Who can step up their SIP?",
    synth: <><span style={{ color: "var(--mint)" }}>31 clients</span> can absorb a 10% step-up on rising income.</>,
    body: <div style={{ display: "flex", gap: 8 }}><div className="ct-wrow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>CLIENTS</span><span className="nv-num">31</span></div><div className="ct-wrow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>NEW SIP</span><span className="nv-num" style={{ color: "var(--mint)" }}>+₹1.1L/mo</span></div></div>,
    footL: <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>AUM GROWTH</span>, cta: "Propose all ▸",
  },
  {
    eyebrow: "H · ONBOARDING AGENT", title: "Onboarding stuck", prompt: "Any new clients stuck in onboarding?",
    synth: <><span style={{ color: "var(--amber)" }}>5 clients</span> stalled — 3 on KYC, 2 on mandate e-sign.</>,
    body: <><div className="ct-wrow"><span style={{ color: "var(--amber)" }}>KYC pending</span><span className="nv-num">3</span></div><div className="ct-wrow"><span style={{ color: "var(--amber)" }}>Mandate e-sign</span><span className="nv-num">2</span></div></>,
    footL: <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>₹1.4CR WAITING</span>, cta: "Nudge all ▸", ctaMint: true,
  },
  {
    eyebrow: "I · COMPLIANCE AGENT", badge: <span className="nv-pill nv-pill-danger" style={{ fontSize: 9 }}>GUARDRAIL</span>,
    title: "Suitability & disclosures", prompt: "Anything I need to flag for compliance?",
    synth: <><span style={{ color: "var(--danger-hex)" }}>3 flags</span> — one holding looks unsuitable for a conservative client.</>,
    body: <><div className="ct-wrow"><span style={{ color: "var(--danger-hex)" }}>↑ Unsuitable · Vikram S</span><span className="nv-mono" style={{ fontSize: 10, color: "var(--danger-hex)" }}>SMALLCAP</span></div><div className="ct-wrow"><span style={{ color: "var(--amber)" }}>↑ Disclosure due · 2</span><span className="nv-mono" style={{ fontSize: 10, color: "var(--amber)" }}>ANNUAL</span></div></>,
    footL: <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>SEBI · MFD</span>, cta: "Review flags ▸",
  },
];

export default function Advisor() {
  const askProps = useAskProps();
  return (
    <section id="ct-advisor" style={{ padding: "38px clamp(18px,3vw,52px) 60px" }}>
      <div className="ct-wrap" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 15 }}>
            <Mark /><span className="nv-serif" style={{ fontSize: 19 }}>Nivesh Copilot</span>
            <span className="nv-pill nv-pill-indigo"><span className="nv-dot" style={{ background: "var(--indigo-hex)" }} />ADVISOR · MFD</span>
          </div>
          <div className="nv-eyebrow" style={{ marginBottom: 9 }}>ADVISOR COCKPIT · CLIENT-DRIVEN ADVISORY WORKFLOWS</div>
          <h2 className="nv-serif" style={{ margin: 0, fontSize: "clamp(28px,3vw,40px)", lineHeight: 1.05 }}>Your whole book, <span style={{ color: "var(--mint)" }}>triaged</span>.</h2>
        </div>
        <p className="nv-prose" style={{ maxWidth: "38ch", margin: 0, fontSize: 14 }}>
          The copilot reads all 128 clients and tells you who to call first — ranked by AUM at risk and ₹ opportunity, grounded in each portfolio's NIDP health.
        </p>
      </div>

      <hr className="nv-hr" style={{ maxWidth: 1340, margin: "24px auto 28px" }} />

      <div className="ct-wrap" style={{ display: "flex", flexDirection: "column", gap: 26 }}>
        {/* AUM + stats */}
        <div className="ct-2col-adv">
          <div className="nv-card" style={{ padding: "20px 22px", display: "flex", gap: 20, alignItems: "center" }}>
            <div>
              <div className="nv-eyebrow" style={{ marginBottom: 8 }}>TOTAL AUM · LIVE</div>
              <div className="nv-metric" style={{ fontSize: 40, color: "rgb(var(--ink))" }}>₹42.8<span style={{ fontSize: 18, color: "rgb(var(--ink-3))" }}> Cr</span></div>
              <div style={{ display: "flex", gap: 8, marginTop: 11, flexWrap: "wrap" }}>
                <span className="nv-pill nv-pill-mint" style={{ fontSize: 9 }}>↑ +2.1% WoW</span>
                <span className="nv-pill" style={{ fontSize: 9 }}>NET FLOW · +₹64L</span>
              </div>
            </div>
            <div style={{ marginLeft: "auto", textAlign: "center" }}>
              <ScoreRing score={72} size={92} id="adv-book" />
              <div className="nv-eyebrow" style={{ fontSize: 8, marginTop: 4 }}>BOOK HEALTH</div>
            </div>
          </div>
          <div className="nv-card" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)" }}>
            {STATS.map((s, i) => (
              <div key={s.k} className="ct-stat" style={i < 3 ? { borderRight: "1px solid rgb(var(--line) / 0.06)" } : undefined}>
                <div className="nv-eyebrow" style={{ fontSize: 8, color: s.c }}>{s.k}</div>
                <div className="nv-metric" style={{ fontSize: 26, color: s.c }}>{s.v}</div>
                <div className="nv-mono" style={{ fontSize: 9, color: "rgb(var(--ink-3))", letterSpacing: ".05em" }}>{s.sub}</div>
              </div>
            ))}
          </div>
        </div>

        {/* client table */}
        <div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
            <span className="nv-serif" style={{ fontSize: 22 }}>Who to call first</span>
            <span className="nv-body" style={{ color: "rgb(var(--ink-3))", fontSize: 13 }}>Ranked by AUM at risk × urgency · NIDP-grounded</span>
          </div>
          <div className="nv-card" style={{ overflowX: "auto" }}>
            <table className="ct-tbl">
              <thead><tr>{["Client", "AUM", "Health", "Flag", "Suggested action", "₹ at stake / gain"].map((h, i) => (<th key={h} style={i === 5 ? { textAlign: "right" } : undefined}>{h}</th>))}</tr></thead>
              <tbody>
                {CLIENTS.map((c) => (
                  <tr key={c.name} {...askProps(`Brief me on ${c.name} — ${c.action.toLowerCase()}`)} style={{ cursor: "pointer" }}>
                    <td style={{ color: "rgb(var(--ink))" }}>{c.name}</td>
                    <td className="nv-num">{c.aum}</td>
                    <td><span className="ct-hp" style={hpStyle(c.hp.color)}><span className="nv-dot" style={{ background: c.hp.color }} />{c.score}</span></td>
                    <td style={{ color: c.flagC }}>{c.flag}</td>
                    <td style={c.action === "No action" ? { color: "rgb(var(--ink-3))" } : undefined}>{c.action}</td>
                    <td className="nv-num" style={{ textAlign: "right", color: c.stakeC }}>{c.stake}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* advisor workflows */}
        <div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
            <span className="nv-serif" style={{ fontSize: 22 }}>Client-driven workflows</span>
            <span className="nv-body" style={{ color: "rgb(var(--ink-3))", fontSize: 13 }}>Book-level jobs the copilot runs across all 128 clients</span>
          </div>
          <div className="ct-cardgrid" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(380px,1fr))" }}>
            {WORKFLOWS.map((w) => (
              <div key={w.title} className="nv-card ct-wf" {...askProps(w.prompt)}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                  <span className="nv-eyebrow" style={{ fontSize: 9 }}>{w.eyebrow}</span>{w.badge}
                </div>
                <span className="nv-serif" style={{ fontSize: 20 }}>{w.title}</span>
                <div className="ct-prompt">{w.prompt}</div>
                <div className="ct-agentline"><Mark size={22} fontSize={13} /><div className="ct-synth">{w.synth}</div></div>
                {w.body}
                <div className="ct-foot">{w.footL}<span className="ct-cta" style={w.ctaMint ? { borderColor: "rgb(var(--pos) / 0.28)", color: "var(--mint)" } : undefined}>{w.cta}</span></div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
