/**
 * Mobile (#ct-mobile) — the same advisory loop on an iPhone, plus the
 * advisor's book triaged on the go.
 */
import { ReactNode, useState } from "react";
import { Mark, ScoreRing } from "../parts";
import { askText, useAskProps, useEnterCopilot } from "../useEnterCopilot";

/** Mobile "Ask" composer — a real input that opens the copilot with the typed question. */
function MComposer({ placeholder }: { placeholder: string }) {
  const enter = useEnterCopilot();
  const [q, setQ] = useState("");
  return (
    <div style={{ marginTop: "auto" }}>
      <div className="ct-mcomp">
        <input
          className="ct-ask-input"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); enter(q); } }}
          placeholder={placeholder}
          aria-label="Ask the copilot"
          style={{ flex: 1, minWidth: 0, fontSize: 14 }}
        />
        <span
          className="nv-btn nv-btn-primary" role="button" tabIndex={0} aria-label="Ask"
          onClick={() => enter(q)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); enter(q); } }}
          style={{ padding: "8px 13px", borderRadius: 999 }}
        >↑</span>
      </div>
    </div>
  );
}

function Phone({ label, labelColor, children }: { label: string; labelColor?: string; children: ReactNode }) {
  return (
    <div className="ct-cap">
      <span className="nv-eyebrow" style={{ color: labelColor }}>{label}</span>
      <div className="ct-device">
        <div className="ct-island" />
        <div className="ct-status"><span>9:41</span><span style={{ letterSpacing: 1, fontSize: 11 }}>5G ▪▪▪</span></div>
        <div className="ct-home" />
        <div className="ct-scroll">
          <div className="ct-ph">{children}</div>
        </div>
      </div>
    </div>
  );
}

export default function Mobile() {
  const askProps = useAskProps();
  return (
    <section id="ct-mobile" style={{ padding: "38px clamp(18px,3vw,52px) 60px" }}>
      <div className="ct-wrap" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 15 }}>
            <Mark /><span className="nv-serif" style={{ fontSize: 19 }}>Nivesh Copilot</span>
            <span className="nv-pill nv-pill-mint"><span className="nv-dot" style={{ background: "var(--mint)" }} />MOBILE</span>
          </div>
          <div className="nv-eyebrow" style={{ marginBottom: 9 }}>iPHONE · DARK · THE COPILOT IN YOUR POCKET</div>
          <h2 className="nv-serif" style={{ margin: 0, fontSize: "clamp(28px,3vw,40px)", lineHeight: 1.05 }}>Same flow, <span style={{ color: "var(--mint)" }}>one thumb</span>.</h2>
        </div>
        <p className="nv-prose" style={{ maxWidth: "36ch", margin: 0, fontSize: 14 }}>
          The full advisory loop condensed to a phone — ask, read the synthesis, act on the ranked fix, approve. Plus the advisor's book, triaged on the go.
        </p>
      </div>

      <hr className="nv-hr" style={{ maxWidth: 1340, margin: "24px auto 20px" }} />

      <div className="ct-wrap ct-rail">
        {/* 01 ASK */}
        <Phone label="01 · ASK">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Mark size={24} fontSize={14} /><span className="nv-serif" style={{ fontSize: 16 }}>Copilot</span>
            <span className="nv-pill nv-pill-mint" style={{ fontSize: 8, marginLeft: "auto" }}><span className="nv-dot" style={{ background: "var(--mint)" }} />NIDP</span>
          </div>
          <div className="nv-eyebrow" style={{ fontSize: 9 }}>LAST SYNC · JUST NOW · 47 HOLDINGS</div>
          <div className="nv-serif" style={{ fontSize: 22, lineHeight: 1.2 }}>I've read all <span style={{ color: "var(--mint)" }}>47 holdings</span>. What matters most today?</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {["Reduce risk ✓", "Grow wealth", "Save tax", "Retire early"].map((c, i) => (
              <span key={c} className={"ct-mchip" + (i === 0 ? " sel" : "")} {...askProps(askText(c))}>{c}</span>
            ))}
          </div>
          <MComposer placeholder="Ask anything…" />
        </Phone>

        {/* 02 ANSWER */}
        <Phone label="02 · ANSWER">
          <div className="ct-mbubble">What should I fix first?</div>
          <div style={{ display: "flex", gap: 9 }}>
            <Mark size={24} fontSize={14} /><div className="nv-serif" style={{ fontSize: 22, lineHeight: 1.2 }}>Healthy — but <span style={{ color: "var(--mint)" }}>financials</span> eat a third of every rupee.</div>
          </div>
          <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
            <span className="nv-pill" style={{ fontSize: 9 }}>FACT · CONC. 32%</span><span className="nv-pill" style={{ fontSize: 9, color: "rgb(var(--ink))", borderColor: "var(--line-3)" }}>Why this ▸</span>
          </div>
          <div className="ct-mcard" style={{ display: "flex", gap: 14, alignItems: "center" }}>
            <ScoreRing score={78} size={66} id="mob-score" />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 9, flex: 1 }}>
              {[["HEALTH", "82", "var(--mint)"], ["RISK", "6.4", "var(--amber)"], ["CONC.", "32%", "var(--amber)"], ["OVERLAP", "71%", "var(--indigo-hex)"]].map(([k, v, c]) => (
                <div key={k}><div className="nv-eyebrow" style={{ fontSize: 8 }}>{k}</div><div className="nv-serif" style={{ fontSize: 18, color: c }}>{v}</div></div>
              ))}
            </div>
          </div>
          <MComposer placeholder="Follow up…" />
        </Phone>

        {/* 03 RECOMMEND */}
        <Phone label="03 · RECOMMEND">
          <div className="nv-eyebrow" style={{ fontSize: 9 }}>TOP 3 ACTIONS · RANKED BY ₹ IMPACT</div>
          <div className="ct-mcard" style={{ borderColor: "rgb(var(--pos) / 0.28)", background: "var(--mint-soft)", display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}><span className="nv-mono" style={{ fontSize: 12, color: "var(--amber)" }}>01</span><span className="nv-dot" style={{ background: "var(--amber)" }} /><span style={{ fontSize: 14, color: "rgb(var(--ink))" }}>Trim financials 32→24%</span></div>
            <div className="nv-serif nv-num" style={{ fontSize: 20, color: "var(--mint)" }}>+₹0.4L/yr</div>
          </div>
          <div className="ct-mrow"><span><span className="nv-mono" style={{ color: "var(--danger-hex)" }}>02</span> Harvest losses · Mar 31</span><span className="nv-serif nv-num" style={{ color: "var(--mint)" }}>₹11.5k</span></div>
          <div className="ct-mrow"><span><span className="nv-mono" style={{ color: "var(--indigo-hex)" }}>03</span> Consolidate 3 funds</span><span className="nv-serif nv-num" style={{ color: "var(--mint)" }}>-2.3pt</span></div>
          <div style={{ marginTop: "auto" }}><div className="nv-btn nv-btn-primary ct-mbtn" {...askProps("Review and apply my top 3 actions")}>Review &amp; apply →</div></div>
        </Phone>

        {/* 04 APPROVE */}
        <Phone label="04 · APPROVE">
          <div className="nv-serif" style={{ fontSize: 22, lineHeight: 1.2 }}>Here's <span style={{ color: "var(--mint)" }}>exactly</span> what changes.</div>
          <div className="ct-mcard" style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            <div className="nv-eyebrow" style={{ color: "var(--amber)" }}>ACTION 01 · TRIM FINANCIALS</div>
            {[["↓ SELL HDFC Bank", "₹96,000", "var(--danger-hex)"], ["↓ SELL ICICI Bank", "₹48,000", "var(--danger-hex)"], ["↑ BUY Nifty 50", "₹1,44,000", "var(--mint)"]].map(([t, v, c]) => (
              <div key={t} className="ct-mrow" style={{ borderRadius: 10, padding: "8px 11px" }}><span style={{ color: c }}>{t}</span><span className="nv-num">{v}</span></div>
            ))}
            <div style={{ display: "flex", gap: 14, paddingTop: 2 }}>
              <div><div className="nv-eyebrow" style={{ fontSize: 8 }}>EST. TAX</div><div className="nv-serif" style={{ fontSize: 15, color: "var(--mint)" }}>₹0 · LT</div></div>
              <div><div className="nv-eyebrow" style={{ fontSize: 8 }}>RISK AFTER</div><div className="nv-serif" style={{ fontSize: 15, color: "var(--mint)" }}>5.6</div></div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 9 }}><span style={{ width: 18, height: 18, borderRadius: 5, border: "1px solid var(--mint)", background: "var(--mint-soft)", display: "grid", placeItems: "center", color: "var(--mint)", fontSize: 12 }}>✓</span><span style={{ fontSize: 12.5, color: "rgb(var(--ink-2))" }}>I understand this is educational, not advice.</span></div>
          <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 9 }}>
            <div className="nv-btn nv-btn-primary ct-mbtn" {...askProps("Apply action 01 — trim financials from 32% to 24%")}>Approve &amp; apply</div>
            <div className="nv-btn ct-mbtn" {...askProps("I'd like to talk to a human advisor")} style={{ borderColor: "rgb(var(--warm) / 0.30)", color: "var(--amber)" }}>Talk to an advisor</div>
          </div>
        </Phone>

        {/* 05 ADVISOR */}
        <Phone label="ADVISOR · BOOK" labelColor="var(--indigo-hex)">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Mark size={24} fontSize={14} /><span className="nv-serif" style={{ fontSize: 16 }}>Book</span>
            <span className="nv-pill nv-pill-indigo" style={{ fontSize: 8, marginLeft: "auto" }}><span className="nv-dot" style={{ background: "var(--indigo-hex)" }} />MFD</span>
          </div>
          <div className="ct-mcard" style={{ display: "flex", gap: 14, alignItems: "center" }}>
            <div><div className="nv-eyebrow" style={{ fontSize: 8 }}>TOTAL AUM</div><div className="nv-serif" style={{ fontSize: 30 }}>₹42.8<span style={{ fontSize: 14, color: "rgb(var(--ink-3))" }}>Cr</span></div><span className="nv-pill nv-pill-mint" style={{ fontSize: 8, marginTop: 4 }}>↑ +2.1% WoW</span></div>
            <div style={{ marginLeft: "auto" }}><ScoreRing score={72} size={72} id="mob-book" /></div>
          </div>
          <div className="nv-eyebrow" style={{ marginTop: 2 }}>WHO TO CALL FIRST</div>
          <div className="ct-mrow"><span style={{ color: "rgb(var(--ink))" }}>Rohan Shah · churn</span><span className="nv-num" style={{ color: "var(--danger-hex)" }}>₹1.8Cr</span></div>
          <div className="ct-mrow"><span style={{ color: "rgb(var(--ink))" }}>Vikram · idle cash</span><span className="nv-num" style={{ color: "var(--mint)" }}>+₹1.6L</span></div>
          <div className="ct-mrow"><span style={{ color: "rgb(var(--ink))" }}>Priya · review 92d</span><span className="nv-mono" style={{ fontSize: 11, color: "var(--amber)" }}>DUE</span></div>
          <div style={{ marginTop: "auto" }}><div className="nv-btn nv-btn-primary ct-mbtn" {...askProps("Who should I call first in my book?")}>Open call list</div></div>
        </Phone>
      </div>
    </section>
  );
}
