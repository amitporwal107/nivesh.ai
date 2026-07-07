/**
 * Principles — the five advisory-AI design paradigms, annotated beside a
 * live app mockup with numbered pins.
 */
import { Mark } from "../parts";

const PARADIGMS = [
  {
    key: "1·2",
    t: "Conversation + workspace, not chat alone",
    d: "The dialogue drives the interaction; its outputs — a portfolio read, a plan, a memo — live in a persistent panel that updates as the conversation progresses. A workspace makes advice a durable object, not scrollback.",
    gl: ["Refer-back content lives in the panel; one-off results can be inline cards.", "The artifact updates live as the dialogue advances."],
  },
  {
    key: "6",
    t: "Guided freedom over open prompting",
    d: "Advisory users rarely know what to ask. Lead with clarifying questions, suggested replies and quick-select chips — an intelligent intake disguised as conversation — but always leave a free-text exit.",
    gl: ["≤ 2 questions per turn.", "Tappable options when the answer space is bounded (risk, horizon, budget).", "Free text always available."],
  },
  {
    key: "3",
    t: "Trust & evidence architecture",
    d: "What separates advisory design from casual chat. Every substantive claim needs visible grounding — citations, expandable “why this”, confidence, disclosed assumptions. Wrong assumptions silently propagating is the biggest failure mode.",
    gl: ["Distinguish fact vs opinion vs AI inference visually.", "Surface the inputs advice rests on (“based on income ₹X, horizon Y”).", "One click to see or correct any relied-on input."],
  },
  {
    key: "4",
    t: "State visibility & progress",
    d: "Workflows have stages: intake → analysis → options → recommendation → action. Even on one page, users should know where they are. Stages create checkpoints to confirm the AI's understanding before it proceeds.",
    gl: ["Slim stage indicator + a “what I know so far” summary.", "Confirm understanding before advancing."],
  },
  {
    key: "5",
    t: "Human-in-the-loop & escalation",
    d: "Regulated, high-stakes contexts need visible escape hatches — talk to a human, flag for review, an approval gate before anything executes. Persistently available; the AI suggests it when confidence is low.",
    gl: ["Escalation persistent, not buried.", "Approval gate before execution; contextual disclaimers, not a boilerplate wall."],
  },
];

const GUIDELINES = [
  "Short, scannable answers — summaries with expandable depth, not essays.",
  "Let users edit prior answers without restarting the flow.",
  "Stream responses, but never let streaming text push buttons around.",
  "Persist the session across days; restore state on return.",
  "Every recommendation ends in a clear next step or button.",
  "Log everything: an exportable transcript / summary is trust + compliance.",
  "Reserve color for semantic meaning — risk, confidence, required action.",
];

function Pin({ n, style }: { n: number; style: React.CSSProperties }) {
  return <span className="ct-pin" style={style}>{n}</span>;
}

export default function Principles() {
  return (
    <section id="ct-principles" style={{ padding: "34px clamp(18px,4vw,56px) 60px" }}>
      <div className="ct-wrap" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
        <div>
          <div className="nv-eyebrow" style={{ marginBottom: 9 }}>DESIGN PARADIGMS · CONVERSATIONAL AI · ADVISORY WORKFLOWS</div>
          <h2 className="nv-serif" style={{ margin: 0, fontSize: "clamp(28px,3vw,42px)", lineHeight: 1.05, maxWidth: "16ch" }}>
            Designing conversational AI for <span style={{ color: "var(--mint)" }}>advice</span>.
          </h2>
        </div>
        <p className="nv-prose" style={{ maxWidth: "34ch", margin: 0, fontSize: 14 }}>
          Advisory conversations are high-stakes, multi-step and evidence-driven. The interface must make advice{" "}
          <em style={{ color: "rgb(var(--ink))", fontStyle: "normal" }}>durable, grounded and safe</em> — not just make the AI talk.
        </p>
      </div>

      <hr className="nv-hr" style={{ maxWidth: 1340, margin: "26px auto" }} />

      <div className="ct-wrap ct-2col">
        {/* left · annotated mockup */}
        <div style={{ overflowX: "auto" }}>
          <div className="nv-eyebrow" style={{ marginBottom: 11 }}>THE ADVISORY PAGE — ANNOTATED · ①–⑥</div>
          <div className="nv-card" style={{ overflow: "hidden", position: "relative", minWidth: 620 }}>
            {/* top bar */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1px solid rgb(var(--line) / 0.06)", background: "var(--bg-2)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <Mark size={22} fontSize={13} />
                <span className="nv-serif" style={{ fontSize: 15 }}>Copilot</span>
                <span className="nv-pill nv-pill-mint" style={{ fontSize: 9 }}><span className="nv-dot" style={{ background: "var(--mint)" }} />NIDP CONNECTED</span>
              </div>
              <span style={{ position: "relative" }}>
                <Pin n={5} style={{ top: -11, right: -9 }} />
                <span className="nv-btn" style={{ padding: "6px 12px", fontSize: 12, borderColor: "rgb(var(--warm) / 0.30)", color: "var(--amber)", background: "var(--amber-soft)" }}>Talk to an advisor ▸</span>
              </span>
            </div>
            {/* 3-col body */}
            <div style={{ display: "grid", gridTemplateColumns: "150px minmax(0,1fr) 210px", minHeight: 480 }}>
              {/* history */}
              <div style={{ borderRight: "1px solid rgb(var(--line) / 0.06)", padding: "14px 12px", background: "var(--bg-1)" }}>
                <div className="nv-btn nv-btn-primary" style={{ width: "100%", justifyContent: "center", padding: 8, fontSize: 12, marginBottom: 14 }}>＋ New review</div>
                <div className="nv-eyebrow" style={{ fontSize: 9, margin: "4px 0 8px" }}>HISTORY</div>
                {["Fix my portfolio first", "Tax-harvest before Mar 31", "Retirement on track?"].map((h, i) => (
                  <div key={h} className={"ct-side-item" + (i === 0 ? " on" : "")}>{h}</div>
                ))}
              </div>
              {/* thread */}
              <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 14, position: "relative" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7, position: "relative" }}>
                  <Pin n={4} style={{ top: -11, left: -11 }} />
                  <span className="nv-mono" style={{ fontSize: 9, color: "rgb(var(--ink-3))", letterSpacing: ".1em" }}>INTAKE</span>
                  <span style={{ flex: 1, height: 3, borderRadius: 999, background: "linear-gradient(90deg,var(--mint) 0 72%,var(--bg-3) 72%)" }} />
                  <span className="nv-mono" style={{ fontSize: 9, color: "var(--mint)", letterSpacing: ".1em" }}>ANALYSIS</span>
                  <span className="nv-mono" style={{ fontSize: 9, color: "rgb(var(--ink-4))", letterSpacing: ".1em" }}>OPTIONS</span>
                </div>
                <div style={{ alignSelf: "flex-end", maxWidth: "80%", position: "relative", background: "var(--bg-3)", border: "1px solid var(--line-2)", borderRadius: "14px 14px 4px 14px", padding: "10px 13px", fontSize: 13, color: "rgb(var(--ink))" }}>
                  <Pin n={1} style={{ top: -11, left: -11 }} />
                  What's the one thing I should fix first?
                </div>
                <div style={{ display: "flex", gap: 10 }}>
                  <Mark size={24} fontSize={14} />
                  <div style={{ minWidth: 0 }}>
                    <div className="nv-serif" style={{ fontSize: 19, lineHeight: 1.22 }}>
                      Your portfolio is <span style={{ color: "var(--mint)" }}>healthy</span> — but financials are eating a third of every rupee you've invested.
                    </div>
                    <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginTop: 9, position: "relative" }}>
                      <Pin n={3} style={{ top: -19, right: -9 }} />
                      <span className="nv-pill" style={{ fontSize: 9 }}>BASED ON · INCOME ₹18L · HORIZON 12Y</span>
                      <span className="nv-pill nv-pill-indigo" style={{ fontSize: 9 }}>↳ 47 HOLDINGS · NIDP</span>
                    </div>
                  </div>
                </div>
                <div>
                  <div className="nv-eyebrow" style={{ marginBottom: 8 }}>TOP 3 ACTIONS · RANKED BY ₹ IMPACT</div>
                  {[
                    ["01", "var(--amber)", "Trim financials from 32% → 24%", "+₹0.4L/yr"],
                    ["02", "var(--danger-hex)", "Harvest losses before Mar 31", "₹11,520 saved"],
                    ["03", "var(--indigo-hex)", "Consolidate 3 funds · 71% overlap", "-2.3 pt risk"],
                  ].map(([n, c, t, v]) => (
                    <div key={n} style={{ display: "flex", alignItems: "center", gap: 11, padding: "10px 12px", borderRadius: 10, border: "1px solid rgb(var(--line) / 0.06)", background: "var(--bg-2)", marginBottom: 7 }}>
                      <span className="nv-mono" style={{ fontSize: 11, color: c as string }}>{n}</span>
                      <span className="nv-dot" style={{ background: c as string }} />
                      <span style={{ flex: 1, fontSize: 13, color: "rgb(var(--ink))" }}>{t}</span>
                      <span className="nv-serif nv-num" style={{ fontSize: 15, color: "var(--mint)" }}>{v}</span>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: "auto", position: "relative" }}>
                  <div className="nv-glass" style={{ display: "flex", alignItems: "center", gap: 10, padding: "11px 13px", position: "relative" }}>
                    <Pin n={6} style={{ top: -11, left: -11 }} />
                    <span style={{ flex: 1, fontSize: 13, color: "rgb(var(--ink-3))" }}>Ask about your portfolio…</span>
                    <span className="nv-btn nv-btn-primary" style={{ padding: "7px 14px", fontSize: 12 }}>↑</span>
                  </div>
                </div>
              </div>
              {/* workspace */}
              <div style={{ borderLeft: "1px solid rgb(var(--line) / 0.06)", padding: "14px 13px", background: "var(--bg-1)", display: "flex", flexDirection: "column", gap: 13, position: "relative" }}>
                <Pin n={2} style={{ top: -11, left: -11 }} />
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span className="nv-eyebrow" style={{ fontSize: 9 }}>WORKSPACE · MEMO</span>
                  <span className="nv-mono" style={{ fontSize: 9, color: "var(--mint)" }}>● LIVE</span>
                </div>
                <div className="nv-serif" style={{ fontSize: 15, lineHeight: 1.2 }}>Rebalancing plan</div>
                <div className="nv-eyebrow" style={{ fontSize: 8 }}>ALLOCATION · NOW → TARGET</div>
                {[["Financials", "32 → 24%", 32, "var(--amber)"], ["Large cap", "28 → 34%", 34, "var(--mint)"], ["Debt", "18 → 20%", 20, "var(--indigo-hex)"]].map(([k, v, w, c]) => (
                  <div key={k as string}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "rgb(var(--ink-2))", marginBottom: 4 }}><span>{k}</span><span className="nv-num">{v}</span></div>
                    <div className="ct-bar"><span style={{ width: `${w}%`, background: c as string }} /></div>
                  </div>
                ))}
                <hr className="nv-hr" />
                <div className="nv-eyebrow" style={{ fontSize: 8 }}>ASSUMPTIONS · TAP TO EDIT</div>
                {[["Risk tolerance", "Moderate"], ["Horizon", "12 yrs"], ["Annual income", "₹18L"]].map(([k, v]) => (
                  <div key={k} className="ct-krow"><span>{k}</span><span style={{ color: "rgb(var(--ink))" }}>{v} ↕</span></div>
                ))}
                <div style={{ marginTop: "auto" }}>
                  <div className="nv-btn nv-btn-primary" style={{ justifyContent: "center", padding: 8, fontSize: 12 }}>Approve &amp; apply</div>
                </div>
              </div>
            </div>
          </div>
          <div className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))", letterSpacing: ".06em", marginTop: 11, lineHeight: 1.7 }}>
            DESKTOP · CONVERSATION 55–65% + WORKSPACE 35–45% · MOBILE COLLAPSES THE PANEL TO A TAB / BOTTOM SHEET · NOT A TRADE-EXECUTION ENGINE — OUTPUT IS EDUCATIONAL
          </div>
        </div>

        {/* right · paradigm cards */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="nv-card-2" style={{ padding: "16px 17px" }}>
            <div className="nv-eyebrow" style={{ marginBottom: 8 }}>THE CORE TENSION</div>
            <p className="nv-body" style={{ margin: 0 }}>Chat is linear and ephemeral. Advice must persist and be verifiable. Every paradigm below resolves that tension deliberately.</p>
          </div>
          {PARADIGMS.map((p) => (
            <div key={p.key} className="nv-card" style={{ padding: "16px 17px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 8 }}>
                <span className="ct-keynum">{p.key}</span>
                <span className="nv-serif" style={{ fontSize: 19 }}>{p.t}</span>
              </div>
              <p className="nv-body" style={{ margin: "0 0 10px" }}>{p.d}</p>
              {p.gl.map((g) => (
                <div key={g} className="ct-gl"><span className="tick">✓</span><span className="nv-body">{g}</span></div>
              ))}
            </div>
          ))}
          <div className="nv-card-2" style={{ padding: "16px 17px" }}>
            <div className="nv-eyebrow" style={{ marginBottom: 10 }}>ENFORCEABLE GUIDELINES</div>
            {GUIDELINES.map((g) => (
              <div key={g} className="ct-gl"><span className="tick">▸</span><span className="nv-body">{g}</span></div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
