/**
 * Workflows — the full catalog of investor jobs, each as a card with its
 * plain-language trigger, one synthesis sentence, a signature widget, and a
 * ₹-impact next step.
 */
import { ReactNode } from "react";
import { Mark, ScoreRing } from "../parts";
import { useAskProps } from "../useEnterCopilot";

function Row({ left, right, lc, rc }: { left: ReactNode; right: ReactNode; lc?: string; rc?: string }) {
  return (
    <div className="ct-wrow">
      <span style={{ color: lc }}>{left}</span>
      <span style={{ color: rc, fontFamily: rc ? "var(--mono)" : undefined, fontSize: rc ? 10 : undefined }}>{right}</span>
    </div>
  );
}
function Bar({ pct, color, label, val, valColor }: { pct: number; color: string; label: string; val: string; valColor?: string }) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "rgb(var(--ink-2))", marginBottom: 5 }}>
        <span>{label}</span><span className="nv-num" style={{ color: valColor }}>{val}</span>
      </div>
      <div className="ct-bar" style={{ height: 8 }}><span style={{ width: `${pct}%`, background: color }} /></div>
    </div>
  );
}

type Card = {
  eyebrow: string;
  flagship?: boolean;
  title: string;
  prompt: string;
  synth: ReactNode;
  widget: ReactNode;
  footL: ReactNode;
  cta: string;
  ctaMint?: boolean;
};

const CARDS: Card[] = [
  {
    eyebrow: "01 · HEALTH AGENT · SCORE H",
    flagship: true,
    title: "Portfolio health review",
    prompt: "What's the one thing I should fix first?",
    synth: <>Healthy overall — but <span style={{ color: "var(--mint)" }}>financials</span> are eating a third of every rupee.</>,
    widget: (
      <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
        <ScoreRing score={78} size={62} id="wf-health" />
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
          <Row left="↓ Trim financials 32→24%" right="+₹0.4L/yr" lc="var(--amber)" rc="var(--mint)" />
          <Row left="＋ 2 more ranked actions" right="₹ IMPACT" lc="rgb(var(--ink-3))" rc="rgb(var(--ink-3))" />
        </div>
      </div>
    ),
    footL: <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>STAGES · ALL 6</span>,
    cta: "Open full flow ▸",
    ctaMint: true,
  },
  {
    eyebrow: "02 · QUALITY AGENT · SCORE Q",
    title: "Fund deep-dive",
    prompt: "Is HDFC Flexi Cap still worth holding?",
    synth: <>Still a <span style={{ color: "var(--mint)" }}>keeper</span> — top-quartile quality, but watch the rising expense ratio.</>,
    widget: (
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8, textAlign: "center" }}>
        {[["A", "QUALITY", "var(--mint)", "rgb(var(--pos) / 0.28)", "var(--mint-soft)"], ["82", "HEALTH", "var(--mint)"], ["—", "EXIT", "rgb(var(--ink-3))"], ["B", "ADD", "var(--amber)", "rgb(var(--warm) / 0.30)", "var(--amber-soft)"]].map(([g, k, c, bc, bg]) => (
          <div key={k}><div className="ct-grade" style={{ color: c, borderColor: bc, background: bg, margin: "0 auto 4px" }}>{g}</div><div className="nv-eyebrow" style={{ fontSize: 8 }}>{k}</div></div>
        ))}
      </div>
    ),
    footL: <span className="nv-pill nv-pill-mint" style={{ fontSize: 9 }}>VERDICT · HOLD</span>,
    cta: "See the reasoning ▸",
  },
  {
    eyebrow: "03 · ADD AGENT · SCORE A",
    title: "Where to invest new money",
    prompt: "Where should I put ₹2L this month?",
    synth: <>Fill your <span style={{ color: "var(--mint)" }}>large-cap gap</span> — three funds fit your moderate, 12-year plan.</>,
    widget: (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Row left="Nifty 50 Index" right="MATCH 94%" rc="var(--mint)" />
        <Row left="Parag Parikh Flexi" right="MATCH 88%" rc="var(--mint)" />
        <Row left="ICICI Balanced Adv" right="MATCH 79%" rc="rgb(var(--ink-2))" />
      </div>
    ),
    footL: <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>₹2L · SPLIT SUGGESTED</span>,
    cta: "Allocate ▸",
    ctaMint: true,
  },
  {
    eyebrow: "04 · EXIT AGENT · SCORE E",
    title: "Should I sell?",
    prompt: "Should I exit my IT sector fund?",
    synth: <>Yes — <span style={{ color: "var(--danger-hex)" }}>exit signal is high</span>, and you can book it tax-free this year.</>,
    widget: (
      <>
        <Bar pct={81} color="var(--danger-hex)" label="Exit signal" val="8.1 / 10" valColor="var(--danger-hex)" />
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <div className="ct-wrow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>TAX ON EXIT</span><span className="nv-num" style={{ color: "var(--mint)" }}>₹0 · LT</span></div>
          <div className="ct-wrow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>REDEPLOY</span><span className="nv-num">₹1.4L</span></div>
        </div>
      </>
    ),
    footL: <span className="nv-pill nv-pill-danger" style={{ fontSize: 9 }}>VERDICT · EXIT</span>,
    cta: "Preview redemption ▸",
  },
  {
    eyebrow: "05 · TAX AGENT · DEADLINE MAR 31",
    title: "Tax-loss harvesting",
    prompt: "Cut my tax before March 31.",
    synth: <>Book <span style={{ color: "var(--mint)" }}>₹11,520</span> in savings by harvesting two losers — no change to your plan.</>,
    widget: (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Row left="↓ Harvest · Smallcap Fund" right="₹7,200" lc="var(--danger-hex)" rc="var(--mint)" />
        <Row left="↓ Harvest · Pharma Fund" right="₹4,320" lc="var(--danger-hex)" rc="var(--mint)" />
      </div>
    ),
    footL: <span className="nv-serif nv-num" style={{ fontSize: 17, color: "var(--mint)" }}>₹11,520 saved</span>,
    cta: "Build plan ▸",
    ctaMint: true,
  },
  {
    eyebrow: "06 · GOALS AGENT · PROJECTION",
    title: "Goal on track?",
    prompt: "Am I on track to retire at 55 with ₹5Cr?",
    synth: <><span style={{ color: "var(--amber)" }}>Almost</span> — you'll reach ₹4.3Cr. A ₹6k/mo step-up closes the gap.</>,
    widget: (
      <>
        <Bar pct={86} color="linear-gradient(90deg,var(--mint),var(--amber))" label="Projected · ₹4.3Cr" val="86% of goal" valColor="var(--amber)" />
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <div className="ct-wrow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>GAP</span><span className="nv-num" style={{ color: "var(--amber)" }}>₹0.7Cr</span></div>
          <div className="ct-wrow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>STEP-UP</span><span className="nv-num" style={{ color: "var(--mint)" }}>+₹6k/mo</span></div>
        </div>
      </>
    ),
    footL: <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>HORIZON · 19 YRS</span>,
    cta: "Adjust plan ▸",
  },
  {
    eyebrow: "07 · ALLOCATION AGENT · DRIFT",
    title: "Rebalance my mix",
    prompt: "Bring me back to a moderate allocation.",
    synth: <>You've drifted <span style={{ color: "var(--amber)" }}>8 points equity-heavy</span>. Three moves reset it.</>,
    widget: (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <Bar pct={73} color="var(--amber)" label="Equity" val="73 → 65%" />
        <Bar pct={30} color="var(--indigo-hex)" label="Debt" val="22 → 30%" />
      </div>
    ),
    footL: <span className="nv-pill nv-pill-amber" style={{ fontSize: 9 }}>DRIFT · 8 PT</span>,
    cta: "Rebalance ▸",
    ctaMint: true,
  },
  {
    eyebrow: "08 · OVERLAP AGENT · SCORE Q",
    title: "Too many funds?",
    prompt: "I hold 14 funds — is that too many?",
    synth: <>Three of them are <span style={{ color: "var(--indigo-hex)" }}>71% the same</span>. Merge to one, cut fees and clutter.</>,
    widget: (
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{ position: "relative", width: 58, height: 40, flex: "0 0 auto" }}>
          <span style={{ position: "absolute", left: 0, top: 4, width: 34, height: 34, borderRadius: "50%", background: "var(--indigo-soft)", border: "1px solid rgb(var(--indigo) / 0.30)" }} />
          <span style={{ position: "absolute", left: 16, top: 4, width: 34, height: 34, borderRadius: "50%", background: "var(--mint-soft)", border: "1px solid rgb(var(--pos) / 0.28)" }} />
        </div>
        <div style={{ flex: 1, display: "flex", gap: 8 }}>
          <div className="ct-wrow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>OVERLAP</span><span className="nv-num" style={{ color: "var(--indigo-hex)" }}>71%</span></div>
          <div className="ct-wrow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>FUNDS</span><span className="nv-num">3 → 1</span></div>
        </div>
      </div>
    ),
    footL: <span className="nv-serif nv-num" style={{ fontSize: 17, color: "var(--mint)" }}>₹9k/yr fees</span>,
    cta: "See overlap map ▸",
  },
  {
    eyebrow: "09 · SIP AGENT · CASHFLOW",
    title: "Optimize my SIPs",
    prompt: "Are my monthly SIPs set up right?",
    synth: <>Solid — one SIP overlaps another. A <span style={{ color: "var(--mint)" }}>10% step-up</span> keeps pace with inflation.</>,
    widget: (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Row left="4 active SIPs" right="₹42k/mo" />
        <Row left="↑ 1 overlaps · pause" right="REVIEW" lc="var(--amber)" rc="var(--amber)" />
        <Row left="↑ Step-up 10%" right="+₹4.2k" lc="var(--mint)" rc="var(--mint)" />
      </div>
    ),
    footL: <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>NEXT · 5TH</span>,
    cta: "Tune SIPs ▸",
    ctaMint: true,
  },
  {
    eyebrow: "10 · MARKET AGENT · DAILY BRIEF",
    title: "What moved today",
    prompt: "What happened to my portfolio today?",
    synth: <><span style={{ color: "var(--danger-hex)" }}>Down ₹18,400</span> — banks dragged, but nothing that changes your plan.</>,
    widget: (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Row left="↓ HDFC Bank" right="-2.4%" lc="var(--danger-hex)" rc="var(--danger-hex)" />
        <Row left="↓ ICICI Bank" right="-1.9%" lc="var(--danger-hex)" rc="var(--danger-hex)" />
        <Row left="↑ Infosys" right="+1.1%" lc="var(--mint)" rc="var(--mint)" />
      </div>
    ),
    footL: <span className="nv-serif nv-num" style={{ fontSize: 17, color: "var(--danger-hex)" }}>-₹18,400 · DAY</span>,
    cta: "Full brief ▸",
  },
];

export default function Workflows() {
  const askProps = useAskProps();
  return (
    <section id="ct-workflows" style={{ padding: "38px clamp(18px,3vw,52px) 60px" }}>
      <div className="ct-wrap" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
        <div>
          <div className="nv-eyebrow" style={{ marginBottom: 9 }}>ADVISORY WORKFLOWS · GROUNDED IN NIDP · Q / H / E / A</div>
          <h2 className="nv-serif" style={{ margin: 0, fontSize: "clamp(28px,3vw,40px)", lineHeight: 1.05 }}>Every job the copilot <span style={{ color: "var(--mint)" }}>does</span>.</h2>
        </div>
        <p className="nv-prose" style={{ maxWidth: "40ch", margin: 0, fontSize: 14 }}>
          Ten advisory workflows, each triggered by a plain-language ask and answered with one synthesis sentence, a signature widget, and a ₹-impact next step.
        </p>
      </div>

      <hr className="nv-hr" style={{ maxWidth: 1340, margin: "24px auto 30px" }} />

      <div className="ct-wrap ct-cardgrid" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(400px,1fr))", gap: 20 }}>
        {CARDS.map((c) => (
          <div key={c.title} className="nv-card ct-wf" {...askProps(c.prompt)}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <span className="nv-eyebrow" style={{ fontSize: 9 }}>{c.eyebrow}</span>
              {c.flagship && <span className="nv-pill nv-pill-mint" style={{ fontSize: 9 }}>FLAGSHIP</span>}
            </div>
            <span className="nv-serif" style={{ fontSize: 21 }}>{c.title}</span>
            <div className="ct-prompt">{c.prompt}</div>
            <div className="ct-agentline"><Mark size={22} fontSize={13} /><div className="ct-synth">{c.synth}</div></div>
            {c.widget}
            <div className="ct-foot">{c.footL}<span className="ct-cta" style={c.ctaMint ? { borderColor: "rgb(var(--pos) / 0.28)", color: "var(--mint)" } : undefined}>{c.cta}</span></div>
          </div>
        ))}
      </div>

      {/* anatomy footer */}
      <div className="ct-wrap" style={{ marginTop: 38 }}>
        <div className="nv-card-2" style={{ padding: "20px 22px", display: "flex", gap: 30, flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ minWidth: 180 }}>
            <div className="nv-eyebrow" style={{ marginBottom: 6 }}>EVERY WORKFLOW · SAME SHAPE</div>
            <div className="nv-serif" style={{ fontSize: 19 }}>Ask → synthesis → widget → ₹ next step.</div>
          </div>
          <div style={{ display: "flex", gap: 9, flexWrap: "wrap", flex: 1 }}>
            <span className="nv-pill" style={{ fontSize: 9 }}>PLAIN-LANGUAGE TRIGGER</span>
            <span className="nv-pill" style={{ fontSize: 9 }}>ONE SERIF SYNTHESIS SENTENCE</span>
            <span className="nv-pill nv-pill-mint" style={{ fontSize: 9 }}>NIDP-GROUNDED WIDGET</span>
            <span className="nv-pill" style={{ fontSize: 9 }}>RANKED BY ₹ IMPACT</span>
            <span className="nv-pill nv-pill-amber" style={{ fontSize: 9 }}>APPROVAL BEFORE ACTION</span>
            <span className="nv-pill nv-pill-danger" style={{ fontSize: 9 }}>HUMAN ESCALATION ALWAYS ON</span>
          </div>
        </div>
      </div>
    </section>
  );
}
