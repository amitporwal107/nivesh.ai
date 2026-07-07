/**
 * AdvisoryFlow (#ct-screens) — the Portfolio Health Review built out end to
 * end across six stages: Intake → Analysis → Options → Recommendation →
 * Action → Human handoff, each in the desktop copilot shell.
 */
import { ReactNode } from "react";
import { Mark, ScoreRing, SectionHead } from "../parts";

const STAGES = ["INTAKE", "ANALYSIS", "OPTIONS", "RECOMMEND", "ACTION"];

function StageStrip({ active }: { active: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      {STAGES.map((s, i) => (
        <div key={s} style={{ display: "contents" }}>
          <span className={"ct-step" + (i < active ? " done" : i === active ? " on" : "")}>{s}</span>
          {i < STAGES.length - 1 && <span className={"ct-seg" + (i < active ? " done" : "")} />}
        </div>
      ))}
    </div>
  );
}

function Shell({
  active,
  danger,
  thread,
  workspace,
}: {
  active: number;
  danger?: boolean;
  thread: ReactNode;
  workspace: ReactNode;
}) {
  return (
    <div className="ct-appwrap">
      <div className="nv-card ct-appwin">
        {/* top bar */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 18px", borderBottom: "1px solid rgb(var(--line) / 0.06)", background: "var(--bg-2)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Mark size={22} fontSize={13} />
            <span className="nv-serif" style={{ fontSize: 15 }}>Copilot</span>
            {danger ? (
              <span className="nv-pill nv-pill-danger" style={{ fontSize: 9 }}><span className="nv-dot" style={{ background: "var(--danger-hex)" }} />CONFIDENCE LOW</span>
            ) : (
              <span className="nv-pill nv-pill-mint" style={{ fontSize: 9 }}><span className="nv-dot" style={{ background: "var(--mint)" }} />NIDP CONNECTED</span>
            )}
            <span className="nv-mono" style={{ fontSize: 9, color: "rgb(var(--ink-3))", letterSpacing: ".06em" }}>
              {danger ? "OUT OF SCOPE · TAX LAW" : "47 HOLDINGS"}
            </span>
          </div>
          <span className="nv-btn" style={{ padding: "6px 12px", fontSize: 12, borderColor: "rgb(var(--warm) / 0.30)", color: "var(--amber)", background: "var(--amber-soft)" }}>Talk to an advisor ▸</span>
        </div>
        <div className="ct-appgrid">
          {/* sidebar */}
          <aside style={{ borderRight: "1px solid rgb(var(--line) / 0.06)", padding: "16px 13px", background: "var(--bg-1)" }}>
            <div className="nv-btn nv-btn-primary" style={{ width: "100%", justifyContent: "center", padding: 9, fontSize: 12, marginBottom: 16 }}>＋ New review</div>
            <div className="nv-eyebrow" style={{ fontSize: 9, marginBottom: 9 }}>HISTORY</div>
            {["Reduce my risk", "Tax before Mar 31", "Retirement on track?"].map((h, i) => (
              <div key={h} className={"ct-side-item" + (i === 0 ? " on" : "")}>{h}</div>
            ))}
          </aside>
          {/* thread */}
          <div style={{ padding: "18px 22px", display: "flex", flexDirection: "column", gap: 15 }}>
            {!danger && <StageStrip active={active} />}
            {thread}
          </div>
          {/* workspace */}
          <div style={{ borderLeft: "1px solid rgb(var(--line) / 0.06)", padding: "16px 14px", background: "var(--bg-1)", display: "flex", flexDirection: "column", gap: 11 }}>
            {workspace}
          </div>
        </div>
      </div>
    </div>
  );
}

const AGENT_LINE = (children: ReactNode) => (
  <div style={{ display: "flex", gap: 11 }}>
    <Mark size={24} fontSize={14} />
    <div style={{ minWidth: 0 }}>{children}</div>
  </div>
);

function Composer({ placeholder }: { placeholder: string }) {
  return (
    <div style={{ marginTop: "auto" }}>
      <div className="nv-glass" style={{ display: "flex", alignItems: "center", gap: 10, padding: "11px 14px" }}>
        <span style={{ flex: 1, fontSize: 13, color: "rgb(var(--ink-3))" }}>{placeholder}</span>
        <span className="nv-btn nv-btn-primary" style={{ padding: "7px 14px", fontSize: 12 }}>↑</span>
      </div>
    </div>
  );
}

function Chip({ children, sel }: { children: ReactNode; sel?: boolean }) {
  return <span className={"ct-chip" + (sel ? " sel" : "")}>{children}</span>;
}

const SCREENS = [
  {
    id: "intake",
    n: "01",
    name: "Intake",
    sub: "Guided elicitation — ≤2 questions per turn, tappable where bounded, free text always open.",
    active: 0,
    thread: (
      <>
        {AGENT_LINE(
          <>
            <div className="nv-serif" style={{ fontSize: 20, lineHeight: 1.22 }}>I can see all <span style={{ color: "var(--mint)" }}>47 holdings</span>. Before I dig in — what matters most to you right now?</div>
            <div className="nv-body" style={{ marginTop: 5 }}>Pick one. You can always type instead.</div>
          </>,
        )}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", paddingLeft: 35 }}>
          <Chip>Grow wealth</Chip><Chip sel>Reduce risk ✓</Chip><Chip>Save tax</Chip><Chip>Retire early</Chip>
        </div>
        {AGENT_LINE(<div className="nv-serif" style={{ fontSize: 20, lineHeight: 1.22 }}>Got it. And how do you feel about short-term swings?</div>)}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", paddingLeft: 35 }}>
          <Chip>Conservative</Chip><Chip sel>Moderate ✓</Chip><Chip>Aggressive</Chip>
        </div>
        <Composer placeholder="Type your own answer…" />
      </>
    ),
    workspace: (
      <>
        <div className="nv-eyebrow" style={{ fontSize: 9 }}>WHAT I KNOW SO FAR</div>
        {[["Holdings", "47 · synced ✓"], ["Primary goal", "Reduce risk"], ["Risk comfort", "Moderate"]].map(([k, v]) => (
          <div key={k} className="ct-krow"><span>{k}</span><span style={{ color: "rgb(var(--ink))" }}>{v}</span></div>
        ))}
        <div className="ct-krow" style={{ borderStyle: "dashed", color: "rgb(var(--ink-4))" }}><span>Time horizon</span><span>→ asking next</span></div>
        <div style={{ marginTop: "auto", paddingTop: 8, borderTop: "1px solid rgb(var(--line) / 0.06)" }}>
          <div className="nv-mono" style={{ fontSize: 9, color: "rgb(var(--ink-4))", lineHeight: 1.6, letterSpacing: ".04em" }}>EDUCATIONAL · NOT INVESTMENT ADVICE. YOU CONFIRM EVERY INPUT BEFORE I ANALYZE.</div>
        </div>
      </>
    ),
  },
  {
    id: "analysis",
    n: "02",
    name: "Analysis",
    sub: "The read — visible reasoning steps, synthesis sentence, score ring, and grounded evidence.",
    active: 1,
    thread: (
      <>
        <div style={{ alignSelf: "flex-end", maxWidth: "74%", background: "var(--bg-3)", border: "1px solid var(--line-2)", borderRadius: "14px 14px 4px 14px", padding: "10px 13px", fontSize: 13, color: "rgb(var(--ink))" }}>What's the one thing I should fix first?</div>
        <div className="nv-card-2" style={{ padding: "11px 13px", display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="nv-mono" style={{ fontSize: 9, color: "var(--mint)" }}>● ANALYZING · 3 STEPS</div>
          {["✓ FETCHED 47 HOLDINGS · NIDP", "✓ SCORED QUALITY · HEALTH · RISK", "✓ RANKED FIXES BY ₹ IMPACT"].map((s) => (
            <div key={s} className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-2))", letterSpacing: ".04em" }}>{s}</div>
          ))}
        </div>
        {AGENT_LINE(
          <>
            <div className="nv-serif" style={{ fontSize: 20, lineHeight: 1.22 }}>Your portfolio is <span style={{ color: "var(--mint)" }}>healthy</span> — but financials are eating a third of every rupee you've invested.</div>
            <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginTop: 9 }}>
              <span className="nv-pill" style={{ fontSize: 9 }}>FACT · CONCENTRATION 32%</span>
              <span className="nv-pill nv-pill-indigo" style={{ fontSize: 9 }}>INFERENCE · HIGH FOR MODERATE</span>
            </div>
          </>,
        )}
        <div className="nv-card-2" style={{ padding: 13, display: "flex", gap: 14, alignItems: "center" }}>
          <ScoreRing score={78} size={72} id="flow-analysis" />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 9, flex: 1 }}>
            {[["QUALITY", "A", "rgb(var(--ink))"], ["HEALTH", "82", "var(--mint)"], ["RISK", "6.4", "var(--amber)"], ["OVERLAP", "71%", "var(--indigo-hex)"], ["CONCENTR.", "32%", "var(--amber)"], ["CASH DRAG", "4%", "rgb(var(--ink))"]].map(([k, v, c]) => (
              <div key={k}><div className="nv-eyebrow" style={{ fontSize: 8 }}>{k}</div><div className="nv-serif" style={{ fontSize: 17, color: c }}>{v}</div></div>
            ))}
          </div>
        </div>
        <Composer placeholder="Ask a follow-up…" />
      </>
    ),
    workspace: (
      <>
        <div className="nv-eyebrow" style={{ fontSize: 9 }}>PORTFOLIO SNAPSHOT</div>
        {[["Financials", 32, "var(--amber)"], ["Large cap", 28, "var(--mint)"], ["Debt", 18, "var(--indigo-hex)"], ["Cash", 4, "rgb(var(--ink-3))"]].map(([k, v, c]) => (
          <div key={k as string}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "rgb(var(--ink-2))", marginBottom: 4 }}><span>{k}</span><span className="nv-num">{v}%</span></div>
            <div className="ct-bar"><span style={{ width: `${v}%`, background: c as string }} /></div>
          </div>
        ))}
        <div className="nv-eyebrow" style={{ fontSize: 9, marginTop: 4 }}>FLAGS</div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <span className="nv-pill nv-pill-amber" style={{ fontSize: 9 }}>CONCENTRATION</span>
          <span className="nv-pill nv-pill-indigo" style={{ fontSize: 9 }}>71% OVERLAP</span>
          <span className="nv-pill nv-pill-danger" style={{ fontSize: 9 }}>UNBOOKED LOSS</span>
        </div>
      </>
    ),
  },
  {
    id: "options",
    n: "03",
    name: "Options",
    sub: "Three paths, each with its ₹ impact, risk delta and effort — comparable side by side.",
    active: 2,
    thread: (
      <>
        {AGENT_LINE(<div className="nv-serif" style={{ fontSize: 20, lineHeight: 1.22 }}>Three ways forward. Each trades off <span style={{ color: "var(--mint)" }}>return, risk and effort</span> differently — pick the one that fits.</div>)}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 11 }}>
          {[
            { tag: "PATH A · RECOMMENDED", c: "var(--mint)", t: "Trim & rebalance", v: "+₹0.4L", u: "/yr", rows: [["RISK Δ", "-0.8 PT"], ["EFFORT", "LOW"], ["TIME", "~10 MIN"]], primary: true, border: "rgb(var(--pos) / 0.28)" },
            { tag: "PATH B", c: "var(--indigo-hex)", t: "Tax-first harvest", v: "₹11,520", u: " saved", rows: [["RISK Δ", "0 PT"], ["EFFORT", "LOW"], ["DEADLINE", "MAR 31"]] },
            { tag: "PATH C", c: "var(--amber)", t: "Consolidate funds", v: "-2.3", u: " pt risk", rows: [["FEES SAVED", "₹9K/YR"], ["EFFORT", "MEDIUM"], ["FUNDS", "3 → 1"]] },
          ].map((o) => (
            <div key={o.tag} className="nv-card-2" style={{ padding: 13, display: "flex", flexDirection: "column", gap: 9, borderColor: o.border }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}><span className="nv-eyebrow" style={{ fontSize: 8, color: o.c }}>{o.tag}</span><span className="nv-dot" style={{ background: o.c }} /></div>
              <div className="nv-serif" style={{ fontSize: 17, lineHeight: 1.15 }}>{o.t}</div>
              <div className="nv-serif nv-num" style={{ fontSize: 22, color: "var(--mint)" }}>{o.v}<span style={{ fontSize: 12, color: "rgb(var(--ink-3))" }}>{o.u}</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, fontFamily: "var(--mono)", fontSize: 10, color: "rgb(var(--ink-2))", letterSpacing: ".04em" }}>
                {o.rows.map(([k, v]) => (<div key={k} style={{ display: "flex", justifyContent: "space-between" }}><span>{k}</span><span>{v}</span></div>))}
              </div>
              <div className={"nv-btn" + (o.primary ? " nv-btn-primary" : "")} style={{ justifyContent: "center", padding: 7, fontSize: 11, marginTop: 2 }}>Choose {o.tag.split(" ")[1]}</div>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}><Chip>Compare all three</Chip><Chip>What if I'm more conservative?</Chip><Chip>Combine A + B</Chip></div>
        <Composer placeholder="Ask about any path…" />
      </>
    ),
    workspace: (
      <>
        <div className="nv-eyebrow" style={{ fontSize: 9 }}>COMPARE · A / B / C</div>
        <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr 1fr 1fr", gap: "6px 4px", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: ".03em" }}>
          <span /><span style={{ color: "var(--mint)", textAlign: "center" }}>A</span><span style={{ color: "var(--indigo-hex)", textAlign: "center" }}>B</span><span style={{ color: "var(--amber)", textAlign: "center" }}>C</span>
          {[["₹ / YR", "+0.4L", "11.5K", "9K"], ["RISK Δ", "-0.8", "0", "-2.3"], ["EFFORT", "LOW", "LOW", "MED"], ["TIME", "10M", "15M", "1D"]].map((r) => (
            <div key={r[0]} style={{ display: "contents" }}>
              <span style={{ color: "rgb(var(--ink-3))" }}>{r[0]}</span>
              <span style={{ color: "rgb(var(--ink))", textAlign: "center" }}>{r[1]}</span>
              <span style={{ textAlign: "center" }}>{r[2]}</span>
              <span style={{ textAlign: "center" }}>{r[3]}</span>
            </div>
          ))}
        </div>
        <hr className="nv-hr" />
        <div className="nv-body" style={{ fontSize: 12 }}>Path A gives the biggest per-rupee gain for the least effort — which is why it's ranked first.</div>
        <span className="nv-pill nv-pill-mint" style={{ fontSize: 9, alignSelf: "flex-start" }}>MATCHED TO · MODERATE · REDUCE RISK</span>
      </>
    ),
  },
  {
    id: "recommend",
    n: "04",
    name: "Recommendation",
    sub: "The verdict — top 3 actions ranked by ₹ impact, with a live plan in the workspace.",
    active: 3,
    thread: (
      <>
        {AGENT_LINE(
          <>
            <div className="nv-serif" style={{ fontSize: 20, lineHeight: 1.22 }}>Start with <span style={{ color: "var(--mint)" }}>financials</span> — it's the biggest single lever, about ₹0.4L a year, at low effort.</div>
            <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginTop: 9 }}><span className="nv-pill nv-pill-mint" style={{ fontSize: 9 }}>PATH A · RECOMMENDED</span><span className="nv-pill" style={{ fontSize: 9, color: "rgb(var(--ink))", borderColor: "var(--line-3)" }}>Why this ▸</span></div>
          </>,
        )}
        <div>
          <div className="nv-eyebrow" style={{ marginBottom: 8 }}>TOP 3 ACTIONS · RANKED BY ₹ IMPACT</div>
          {[
            { n: "01", c: "var(--amber)", t: "Trim financials from 32% → 24%", v: "+₹0.4L/yr", cta: true },
            { n: "02", c: "var(--danger-hex)", t: "Harvest losses before Mar 31", v: "₹11,520 saved" },
            { n: "03", c: "var(--indigo-hex)", t: "Consolidate 3 funds · 71% overlap", v: "-2.3 pt risk" },
          ].map((a) => (
            <div key={a.n} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 13px", borderRadius: 10, border: a.cta ? "1px solid rgb(var(--pos) / 0.28)" : "1px solid rgb(var(--line) / 0.06)", background: a.cta ? "var(--mint-soft)" : "var(--bg-2)", marginBottom: 8 }}>
              <span className="nv-mono" style={{ fontSize: 11, color: a.c }}>{a.n}</span><span className="nv-dot" style={{ background: a.c }} />
              <span style={{ flex: 1, fontSize: 13, color: "rgb(var(--ink))" }}>{a.t}</span>
              <span className="nv-serif nv-num" style={{ fontSize: 15, color: "var(--mint)" }}>{a.v}</span>
              {a.cta ? <span className="nv-btn nv-btn-primary" style={{ padding: "5px 11px", fontSize: 11 }}>Do it ↓</span> : <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>QUEUE</span>}
            </div>
          ))}
        </div>
        <Composer placeholder="Ask anything…" />
      </>
    ),
    workspace: (
      <>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}><span className="nv-eyebrow" style={{ fontSize: 9 }}>WORKSPACE · MEMO</span><span className="nv-mono" style={{ fontSize: 9, color: "var(--mint)" }}>● LIVE</span></div>
        <div className="nv-serif" style={{ fontSize: 15 }}>Rebalancing plan</div>
        <div className="nv-eyebrow" style={{ fontSize: 8 }}>ALLOCATION · NOW → TARGET</div>
        {[["Financials", "32 → 24%", 32, "var(--amber)"], ["Large cap", "28 → 34%", 34, "var(--mint)"], ["Debt", "18 → 20%", 20, "var(--indigo-hex)"]].map(([k, v, w, c]) => (
          <div key={k as string}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "rgb(var(--ink-2))", marginBottom: 4 }}><span>{k}</span><span className="nv-num">{v}</span></div>
            <div className="ct-bar"><span style={{ width: `${w}%`, background: c as string }} /></div>
          </div>
        ))}
        <div style={{ marginTop: "auto" }}><div className="nv-btn nv-btn-primary" style={{ justifyContent: "center", padding: 9, fontSize: 12 }}>Review &amp; apply →</div></div>
      </>
    ),
  },
  {
    id: "action",
    n: "05",
    name: "Action",
    sub: "The gate — exact changes shown, explicit consent, nothing executes without approval.",
    active: 4,
    thread: (
      <>
        {AGENT_LINE(<div className="nv-serif" style={{ fontSize: 20, lineHeight: 1.22 }}>Here's <span style={{ color: "var(--mint)" }}>exactly</span> what applying action 01 does. Nothing happens until you approve.</div>)}
        <div className="nv-card-2" style={{ padding: 14, display: "flex", flexDirection: "column", gap: 11 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}><span className="nv-eyebrow" style={{ fontSize: 9, color: "var(--amber)" }}>ACTION 01 · TRIM FINANCIALS 32 → 24%</span><span className="nv-pill nv-pill-amber" style={{ fontSize: 9 }}>PREVIEW</span></div>
          {[["↓ SELL · HDFC Bank", "₹96,000", "var(--danger-hex)"], ["↓ SELL · ICICI Bank", "₹48,000", "var(--danger-hex)"], ["↑ BUY · Nifty 50 Index", "₹1,44,000", "var(--mint)"]].map(([t, v, c]) => (
            <div key={t} className="ct-krow"><span style={{ color: c }}>{t}</span><span className="nv-num" style={{ color: "rgb(var(--ink))" }}>{v}</span></div>
          ))}
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", paddingTop: 2 }}>
            {[["EST. COST", "₹120", "rgb(var(--ink))"], ["EST. TAX", "₹0 · LT", "var(--mint)"], ["RISK AFTER", "5.6", "var(--mint)"]].map(([k, v, c]) => (
              <div key={k}><div className="nv-eyebrow" style={{ fontSize: 8 }}>{k}</div><div className="nv-serif nv-num" style={{ fontSize: 16, color: c }}>{v}</div></div>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ width: 16, height: 16, borderRadius: 4, border: "1px solid var(--mint)", background: "var(--mint-soft)", display: "grid", placeItems: "center", color: "var(--mint)", fontSize: 11 }}>✓</span>
          <span className="nv-body" style={{ fontSize: 12 }}>I understand this is educational, not investment advice.</span>
        </div>
        <div style={{ marginTop: "auto", display: "flex", gap: 9 }}>
          <span className="nv-btn nv-btn-primary" style={{ flex: 1, justifyContent: "center", padding: 11, fontSize: 13 }}>Approve &amp; apply</span>
          <span className="nv-btn" style={{ justifyContent: "center", padding: "11px 16px", fontSize: 13, borderColor: "rgb(var(--warm) / 0.30)", color: "var(--amber)" }}>Review with advisor</span>
        </div>
      </>
    ),
    workspace: (
      <>
        <div className="nv-eyebrow" style={{ fontSize: 9 }}>ORDER PREVIEW · AUDIT</div>
        {[["10:42:01", "PLAN BUILT", "rgb(var(--ink-2))"], ["10:42:18", "ASSUMPTIONS OK", "rgb(var(--ink-2))"], ["10:43:05", "AWAITING APPROVAL", "var(--mint)"]].map(([t, s, c]) => (
          <div key={t} className="ct-krow" style={{ fontFamily: "var(--mono)", fontSize: 10 }}><span style={{ color: "rgb(var(--ink-3))" }}>{t}</span><span style={{ color: c }}>{s}</span></div>
        ))}
        <hr className="nv-hr" />
        <div className="nv-eyebrow" style={{ fontSize: 9 }}>EXECUTES AT</div>
        <div className="nv-body" style={{ fontSize: 12 }}>Orders route to your broker after approval. You can cancel until 3:30pm IST.</div>
        <div style={{ marginTop: "auto" }}>
          <div className="nv-btn" style={{ justifyContent: "center", padding: 8, fontSize: 11 }}>Export summary · PDF</div>
          <div className="nv-mono" style={{ fontSize: 9, color: "rgb(var(--ink-4))", letterSpacing: ".04em", lineHeight: 1.6, marginTop: 8 }}>EVERY STEP IS LOGGED &amp; EXPORTABLE.</div>
        </div>
      </>
    ),
  },
  {
    id: "escalation",
    n: "06",
    name: "Human handoff",
    sub: "The escape hatch — when confidence is low or scope is exceeded, hand off with full context.",
    active: 5,
    danger: true,
    thread: (
      <>
        <div style={{ alignSelf: "flex-end", maxWidth: "74%", background: "var(--bg-3)", border: "1px solid var(--line-2)", borderRadius: "14px 14px 4px 14px", padding: "10px 13px", fontSize: 13, color: "rgb(var(--ink))" }}>Should I move my NPS to the new tax regime this year?</div>
        {AGENT_LINE(
          <>
            <div className="nv-serif" style={{ fontSize: 20, lineHeight: 1.22 }}>This one needs a <span style={{ color: "var(--danger-hex)" }}>human</span>. It turns on tax law I won't guess on — I've flagged it for an advisor.</div>
            <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginTop: 9 }}><span className="nv-pill nv-pill-danger" style={{ fontSize: 9 }}>CONFIDENCE 38%</span><span className="nv-pill" style={{ fontSize: 9 }}>REASON · REGULATED ADVICE</span></div>
          </>,
        )}
        <div className="nv-card-2" style={{ padding: 14, display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ width: 42, height: 42, borderRadius: "50%", background: "var(--indigo-soft)", border: "1px solid rgb(var(--indigo) / 0.30)", display: "grid", placeItems: "center", color: "var(--indigo-hex)", fontFamily: "var(--display)", fontSize: 18 }}>PM</span>
            <div><div className="nv-serif" style={{ fontSize: 16 }}>Priya Menon</div><div className="nv-mono" style={{ fontSize: 9, color: "rgb(var(--ink-3))", letterSpacing: ".06em" }}>SEBI RIA · AVAILABLE TODAY 3–6PM</div></div>
          </div>
          <div>
            <div className="nv-eyebrow" style={{ fontSize: 8, marginBottom: 7 }}>I'LL SHARE WITH PRIYA</div>
            {["Conversation transcript", "Portfolio snapshot · 47 holdings", "Your 3 assumptions"].map((t) => (
              <div key={t} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "rgb(var(--ink-2))" }}><span style={{ color: "var(--mint)" }}>✓</span> {t}</div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 9 }}>
            <span className="nv-btn nv-btn-primary" style={{ flex: 1, justifyContent: "center", padding: 10, fontSize: 12 }}>Schedule a call</span>
            <span className="nv-btn" style={{ justifyContent: "center", padding: "10px 15px", fontSize: 12 }}>Chat now</span>
          </div>
        </div>
        <Composer placeholder="Add a note for the advisor…" />
      </>
    ),
    workspace: (
      <>
        <div className="nv-eyebrow" style={{ fontSize: 9 }}>HANDOFF PACKET</div>
        <div className="nv-body" style={{ fontSize: 12 }}>Priya receives everything the moment you confirm — no re-explaining.</div>
        <div className="nv-eyebrow" style={{ fontSize: 9, marginTop: 2 }}>FLAGGED ITEMS</div>
        {[["↑ NPS regime switch", "TAX", "var(--danger-hex)"], ["↑ 80C headroom", "TAX", "var(--amber)"]].map(([t, tag, c]) => (
          <div key={t} className="ct-krow"><span style={{ color: c }}>{t}</span><span className="nv-mono" style={{ fontSize: 9, color: "rgb(var(--ink-3))" }}>{tag}</span></div>
        ))}
        <div style={{ marginTop: "auto", paddingTop: 8, borderTop: "1px solid rgb(var(--line) / 0.06)" }}>
          <div className="nv-mono" style={{ fontSize: 9, color: "rgb(var(--ink-4))", letterSpacing: ".04em", lineHeight: 1.6 }}>SHARED SECURELY · READ-ONLY · YOU CAN REVOKE ANYTIME.</div>
        </div>
      </>
    ),
  },
];

export default function AdvisoryFlow() {
  return (
    <section id="ct-screens" style={{ padding: "36px clamp(18px,3vw,48px) 60px" }}>
      <div className="ct-wrap" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
        <div>
          <div className="nv-eyebrow" style={{ marginBottom: 9 }}>SCREEN FLOW · DESKTOP · SIX STAGES</div>
          <h2 className="nv-serif" style={{ margin: 0, fontSize: "clamp(28px,3vw,40px)", lineHeight: 1.05 }}>Every screen, <span style={{ color: "var(--mint)" }}>end to end</span>.</h2>
        </div>
        <p className="nv-prose" style={{ maxWidth: "38ch", margin: 0, fontSize: 14 }}>
          One page, one thread — the workflow moves through <em style={{ color: "rgb(var(--ink))", fontStyle: "normal" }}>intake → analysis → options → recommendation → action</em>, with a persistent workspace and an always-present human escape hatch.
        </p>
      </div>

      <hr className="nv-hr" style={{ maxWidth: 1340, margin: "24px auto 34px" }} />

      <div className="ct-wrap" style={{ display: "flex", flexDirection: "column", gap: 52 }}>
        {SCREENS.map((s) => (
          <div key={s.id}>
            <SectionHead n={s.n} title={s.name} sub={s.sub} accent={s.danger ? "var(--danger-hex)" : "var(--mint)"} />
            <Shell active={s.active} danger={s.danger} thread={s.thread} workspace={s.workspace} />
          </div>
        ))}
      </div>
    </section>
  );
}
