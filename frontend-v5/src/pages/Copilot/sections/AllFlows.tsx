/**
 * AllFlows (#ct-allflows) — every workflow as an Ask → Analyze → Decide → Act
 * filmstrip: the complete journey for each, tailored at every step.
 */
import { ReactNode } from "react";
import { askText, useEnterCopilot } from "../useEnterCopilot";

const STAGES = ["ASK", "ANALYZE", "DECIDE", "ACT"];

function PanelHead({ i }: { i: number }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span className="ct-sc on">{STAGES[i]}</span>
      <div className="ct-dots">{[0, 1, 2, 3].map((d) => (<span key={d} className={"ct-d4" + (d <= i ? " on" : "")} />))}</div>
    </div>
  );
}
function FRow({ l, r, lc, rc }: { l: ReactNode; r: ReactNode; lc?: string; rc?: string }) {
  return <div className="ct-frow"><span style={{ color: lc }}>{l}</span><span className="nv-num" style={{ color: rc }}>{r}</span></div>;
}
function Chips({ items }: { items: [string, boolean][] }) {
  return <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>{items.map(([t, s]) => (<span key={t} className={"ct-chip" + (s ? " sel" : "")} style={{ fontSize: 11 }}>{t}</span>))}</div>;
}
function Bar({ pct, color, l, r, rc }: { pct: number; color: string; l: string; r: string; rc?: string }) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "rgb(var(--ink-2))", marginBottom: 4 }}><span>{l}</span><span className="nv-num" style={{ color: rc }}>{r}</span></div>
      <div className="ct-bar" style={{ height: 6 }}><span style={{ width: `${pct}%`, background: color }} /></div>
    </div>
  );
}

type Flow = { n: string; title: string; sub: string; panels: [ReactNode, ReactNode, ReactNode, ReactNode] };

const FLOWS: Flow[] = [
  {
    n: "01", title: "Portfolio health review", sub: "Health agent · score H",
    panels: [
      <><div className="ct-pb">What's the one thing I should fix first?</div><div className="ct-syn">First — what matters most?</div><Chips items={[["Reduce risk ✓", true], ["Grow", false], ["Save tax", false]]} /></>,
      <><div className="ct-syn">Healthy — but <span style={{ color: "var(--mint)" }}>financials</span> eat a third of every rupee.</div><div style={{ display: "flex", gap: 8 }}><div className="ct-frow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>HEALTH</span><span className="nv-num" style={{ color: "var(--mint)" }}>78</span></div><div className="ct-frow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>CONC.</span><span className="nv-num" style={{ color: "var(--amber)" }}>32%</span></div></div></>,
      <><div className="nv-eyebrow" style={{ fontSize: 8 }}>TOP 3 · BY ₹ IMPACT</div><FRow l="01 Trim financials" r="+₹0.4L" lc="var(--amber)" rc="var(--mint)" /><FRow l="02 Harvest losses" r="₹11.5k" lc="var(--danger-hex)" rc="var(--mint)" /><FRow l="03 Consolidate" r="-2.3pt" lc="var(--indigo-hex)" rc="var(--mint)" /></>,
      <><div className="ct-syn">Trim financials 32 → 24%.</div><FRow l="EST. TAX" r="₹0 · LT" lc="rgb(var(--ink-3))" rc="var(--mint)" /><div className="nv-btn nv-btn-primary ct-pbtn">Approve &amp; apply</div></>,
    ],
  },
  {
    n: "02", title: "Fund deep-dive", sub: "Quality agent · score Q",
    panels: [
      <><div className="ct-pb">Is HDFC Flexi Cap still worth holding?</div><div className="ct-syn">Judge it how?</div><Chips items={[["Vs category ✓", true], ["Vs my goal", false]]} /></>,
      <><div className="ct-syn">Top-quartile <span style={{ color: "var(--mint)" }}>quality</span> — but fees are creeping up.</div><div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 6, textAlign: "center" }}>{[["A", "Q", "var(--mint)"], ["82", "H", "var(--mint)"], ["—", "E", "rgb(var(--ink-3))"], ["B", "A", "var(--amber)"]].map(([g, k, c]) => (<div key={k}><div className="nv-metric" style={{ fontSize: 15, color: c }}>{g}</div><div className="nv-eyebrow" style={{ fontSize: 7 }}>{k}</div></div>))}</div></>,
      <><span className="nv-pill nv-pill-mint" style={{ fontSize: 9, alignSelf: "flex-start" }}>VERDICT · HOLD</span><FRow l="Keep as core" r="28% wt" /><FRow l="Trim slight overweight" r="-2%" lc="var(--amber)" /></>,
      <><div className="ct-syn">Set a quarterly review alert.</div><FRow l="NEXT CHECK" r="Q3 · Sep" lc="rgb(var(--ink-3))" /><div className="nv-btn nv-btn-primary ct-pbtn">Keep &amp; watch</div></>,
    ],
  },
  {
    n: "03", title: "Where to invest new money", sub: "Add agent · score A",
    panels: [
      <><div className="ct-pb">Where should I put ₹2L this month?</div><div className="ct-syn">One-time or recurring?</div><Chips items={[["Lump sum ✓", true], ["Start a SIP", false]]} /></>,
      <><div className="ct-syn">You're light on <span style={{ color: "var(--mint)" }}>large cap</span> — three funds fit.</div><FRow l="Nifty 50 Index" r="94%" rc="var(--mint)" /><FRow l="Parag Parikh Flexi" r="88%" rc="var(--mint)" /></>,
      <><div className="nv-eyebrow" style={{ fontSize: 8 }}>SUGGESTED SPLIT · ₹2L</div><FRow l="Nifty 50 Index" r="₹1.2L" /><FRow l="Parag Parikh Flexi" r="₹0.5L" /><FRow l="ICICI Balanced" r="₹0.3L" /></>,
      <><div className="ct-syn">Place 3 buys · ₹2L total.</div><FRow l="EST. COST" r="₹90" lc="rgb(var(--ink-3))" /><div className="nv-btn nv-btn-primary ct-pbtn">Approve &amp; buy</div></>,
    ],
  },
  {
    n: "04", title: "Should I sell?", sub: "Exit agent · score E",
    panels: [
      <><div className="ct-pb">Should I exit my IT sector fund?</div><div className="ct-syn">Full exit or partial?</div><Chips items={[["Full", false], ["Partial ✓", true]]} /></>,
      <><div className="ct-syn"><span style={{ color: "var(--danger-hex)" }}>Exit signal is high</span> and momentum's fading.</div><Bar pct={81} color="var(--danger-hex)" l="Exit signal" r="8.1" rc="var(--danger-hex)" /></>,
      <><span className="nv-pill nv-pill-danger" style={{ fontSize: 9, alignSelf: "flex-start" }}>VERDICT · EXIT</span><FRow l="Redeem" r="₹1.4L" /><FRow l="TAX" r="₹0 · LT" lc="rgb(var(--ink-3))" rc="var(--mint)" /><FRow l="Redeploy → large cap" r="→" lc="var(--mint)" /></>,
      <><div className="ct-syn">Redeem ₹1.4L, reinvest same day.</div><div className="nv-btn nv-btn-primary ct-pbtn" style={{ marginBottom: 7 }}>Approve redemption</div><div className="nv-btn ct-pbtn" style={{ marginTop: 0, borderColor: "rgb(var(--warm) / 0.30)", color: "var(--amber)" }}>Review with advisor</div></>,
    ],
  },
  {
    n: "05", title: "Tax-loss harvesting", sub: "Tax agent · deadline Mar 31",
    panels: [
      <><div className="ct-pb">Cut my tax before March 31.</div><div className="ct-syn">This financial year?</div><Chips items={[["FY 25-26 ✓", true], ["Plan ahead", false]]} /></>,
      <><div className="ct-syn"><span style={{ color: "var(--mint)" }}>₹11,520</span> harvestable across two losers.</div><FRow l="Smallcap Fund" r="₹7,200" lc="var(--danger-hex)" rc="var(--mint)" /><FRow l="Pharma Fund" r="₹4,320" lc="var(--danger-hex)" rc="var(--mint)" /></>,
      <><div className="ct-syn">Book both, repurchase to stay invested.</div><FRow l="PLAN CHANGE" r="NONE" lc="rgb(var(--ink-3))" rc="var(--mint)" /><FRow l="ALLOCATION" r="UNCHANGED" lc="rgb(var(--ink-3))" /></>,
      <><div className="nv-metric" style={{ fontSize: 22, color: "var(--mint)" }}>₹11,520 <span style={{ fontSize: 12, color: "rgb(var(--ink-3))" }}>saved</span></div><span className="nv-pill nv-pill-danger" style={{ fontSize: 9, alignSelf: "flex-start" }}>BEFORE MAR 31</span><div className="nv-btn nv-btn-primary ct-pbtn">Approve harvest</div></>,
    ],
  },
  {
    n: "06", title: "Goal on track?", sub: "Goals agent · projection",
    panels: [
      <><div className="ct-pb">Am I on track to retire at 55 with ₹5Cr?</div><div className="ct-syn">Retire at what age?</div><Chips items={[["55 ✓", true], ["60", false]]} /></>,
      <><div className="ct-syn"><span style={{ color: "var(--amber)" }}>Almost</span> — you'll land at ₹4.3Cr.</div><Bar pct={86} color="linear-gradient(90deg,var(--mint),var(--amber))" l="₹4.3Cr projected" r="86%" rc="var(--amber)" /></>,
      <><div className="nv-eyebrow" style={{ fontSize: 8 }}>THREE WAYS TO CLOSE ₹0.7Cr</div><FRow l="Step-up SIP" r="+₹6k/mo" lc="var(--mint)" /><FRow l="Retire at 57" r="+2 yrs" /><FRow l="Lower target" r="₹4.3Cr" /></>,
      <><div className="ct-syn">Step up SIP by ₹6k/mo.</div><FRow l="NEW PROJECTION" r="₹5.0Cr" lc="rgb(var(--ink-3))" rc="var(--mint)" /><div className="nv-btn nv-btn-primary ct-pbtn">Approve step-up</div></>,
    ],
  },
  {
    n: "07", title: "Rebalance my mix", sub: "Allocation agent · drift",
    panels: [
      <><div className="ct-pb">Bring me back to a moderate allocation.</div><div className="ct-syn">Mind the tax?</div><Chips items={[["Tax-aware ✓", true], ["Fastest", false]]} /></>,
      <><div className="ct-syn">Drifted <span style={{ color: "var(--amber)" }}>8 points equity-heavy</span>.</div><Bar pct={73} color="var(--amber)" l="Equity" r="73 → 65%" /><Bar pct={30} color="var(--indigo-hex)" l="Debt" r="22 → 30%" /></>,
      <><div className="ct-syn">Shift ₹2.1L equity → debt.</div><FRow l="RISK" r="7.2 → 6.0" lc="rgb(var(--ink-3))" /><FRow l="ORDERS" r="3" lc="rgb(var(--ink-3))" /></>,
      <><div className="ct-syn">Place 3 rebalancing orders.</div><FRow l="EST. TAX" r="₹1,240" lc="rgb(var(--ink-3))" rc="var(--mint)" /><div className="nv-btn nv-btn-primary ct-pbtn">Approve &amp; apply</div></>,
    ],
  },
  {
    n: "08", title: "Too many funds?", sub: "Overlap agent · score Q",
    panels: [
      <><div className="ct-pb">I hold 14 funds — is that too many?</div><div className="ct-syn">Optimise for what?</div><Chips items={[["Cut overlap ✓", true], ["Cut fees", false]]} /></>,
      <><div className="ct-syn">Three funds are <span style={{ color: "var(--indigo-hex)" }}>71% the same</span>.</div><div style={{ display: "flex", alignItems: "center", gap: 12 }}><div style={{ position: "relative", width: 54, height: 38, flex: "0 0 auto" }}><span style={{ position: "absolute", left: 0, top: 4, width: 32, height: 32, borderRadius: "50%", background: "var(--indigo-soft)", border: "1px solid rgb(var(--indigo) / 0.30)" }} /><span style={{ position: "absolute", left: 15, top: 4, width: 32, height: 32, borderRadius: "50%", background: "var(--mint-soft)", border: "1px solid rgb(var(--pos) / 0.28)" }} /></div><div className="ct-frow" style={{ flex: 1 }}><span style={{ color: "rgb(var(--ink-3))" }}>OVERLAP</span><span className="nv-metric" style={{ fontSize: 16, color: "var(--indigo-hex)" }}>71%</span></div></div></>,
      <><div className="ct-syn">Merge the three into one index fund.</div><FRow l="FUNDS" r="3 → 1" lc="rgb(var(--ink-3))" /><FRow l="Fees saved" r="₹9k/yr" lc="var(--mint)" rc="var(--mint)" /></>,
      <><div className="ct-syn">Redeem 3, buy 1.</div><FRow l="EST. TAX" r="₹0 · LT" lc="rgb(var(--ink-3))" rc="var(--mint)" /><div className="nv-btn nv-btn-primary ct-pbtn">Approve merge</div></>,
    ],
  },
  {
    n: "09", title: "Optimize my SIPs", sub: "SIP agent · cashflow",
    panels: [
      <><div className="ct-pb">Are my monthly SIPs set up right?</div><div className="ct-syn">What's the priority?</div><Chips items={[["Optimize ✓", true], ["Free up cash", false]]} /></>,
      <><div className="ct-syn">Solid — but one SIP <span style={{ color: "var(--amber)" }}>overlaps</span> another.</div><FRow l="4 active SIPs" r="₹42k/mo" /><FRow l="1 overlaps" r="₹8k" lc="var(--amber)" rc="var(--amber)" /></>,
      <><FRow l="Pause overlapping SIP" r="-₹8k" lc="var(--amber)" /><FRow l="Step-up 10%" r="+₹4.2k" lc="var(--mint)" rc="var(--mint)" /><FRow l="NET" r="₹38.2k/mo" lc="rgb(var(--ink-3))" /></>,
      <><div className="ct-syn">Update 2 SIPs from next cycle.</div><FRow l="EFFECTIVE" r="5th" lc="rgb(var(--ink-3))" /><div className="nv-btn nv-btn-primary ct-pbtn">Approve changes</div></>,
    ],
  },
  {
    n: "10", title: "What moved today", sub: "Market agent · daily brief",
    panels: [
      <><div className="ct-pb">What happened to my portfolio today?</div><div className="ct-syn">Which window?</div><Chips items={[["Today ✓", true], ["This week", false]]} /></>,
      <><div className="ct-syn"><span style={{ color: "var(--danger-hex)" }}>Down ₹18,400</span> — banks did the damage.</div><FRow l="↓ HDFC Bank" r="-2.4%" lc="var(--danger-hex)" rc="var(--danger-hex)" /><FRow l="↑ Infosys" r="+1.1%" lc="var(--mint)" rc="var(--mint)" /></>,
      <><span className="nv-pill nv-pill-mint" style={{ fontSize: 9, alignSelf: "flex-start" }}>NO ACTION NEEDED</span><div className="ct-syn">Within a normal day's range for your mix.</div><FRow l="30-DAY BAND" r="± ₹40k" lc="rgb(var(--ink-3))" /></>,
      <><div className="ct-syn">Alert me only on big moves.</div><FRow l="THRESHOLD" r="> 5% drop" lc="rgb(var(--ink-3))" /><div className="nv-btn nv-btn-primary ct-pbtn">Set alert</div></>,
    ],
  },
];

export default function AllFlows() {
  const enter = useEnterCopilot();
  return (
    <section id="ct-allflows" style={{ padding: "38px clamp(18px,3vw,52px) 60px" }}>
      <div className="ct-wrap" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
        <div>
          <div className="nv-eyebrow" style={{ marginBottom: 9 }}>EVERY WORKFLOW · END TO END · ASK → ANALYZE → DECIDE → ACT</div>
          <h2 className="nv-serif" style={{ margin: 0, fontSize: "clamp(28px,3vw,40px)", lineHeight: 1.05 }}>Ten workflows, <span style={{ color: "var(--mint)" }}>start to finish</span>.</h2>
        </div>
        <p className="nv-prose" style={{ maxWidth: "38ch", margin: 0, fontSize: 14 }}>
          Each row is one workflow's full journey — the trigger, the grounded read, the ranked decision, and the approval gate. Scroll a row sideways to walk its stages.
        </p>
      </div>

      <hr className="nv-hr" style={{ maxWidth: 1340, margin: "24px auto 30px" }} />

      <div className="ct-wrap" style={{ display: "flex", flexDirection: "column", gap: 40 }}>
        {FLOWS.map((f) => (
          <div key={f.n}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
              <span className="nv-mono" style={{ fontSize: 13, color: "var(--mint)" }}>{f.n}</span>
              <span className="nv-serif" style={{ fontSize: 22 }}>{f.title}</span>
              <span className="nv-body" style={{ color: "rgb(var(--ink-3))", fontSize: 13 }}>{f.sub}</span>
            </div>
            <div
              className="ct-flowrow"
              onClick={(e) => {
                const el = (e.target as HTMLElement).closest(".ct-pb, .ct-pbtn, .ct-chip");
                if (el) enter(askText(el.textContent || ""));
              }}
            >
              {f.panels.map((p, i) => (
                <div key={i} style={{ display: "contents" }}>
                  <div className="nv-card ct-fc"><PanelHead i={i} />{p}</div>
                  {i < 3 && <div className="ct-fcarw">→</div>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
