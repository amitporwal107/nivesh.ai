/**
 * CopilotTourArticle — body for the blog post
 * "Watch: a 2-minute tour of Nivesh Copilot".
 *
 * Video-first post. The tour MP4 + poster live in /public and are referenced
 * through import.meta.env.BASE_URL so they resolve under the staging sub-path
 * (e.g. "/v5/"), matching the Homepage demo-video convention. Layout mirrors
 * RetailLossesArticle (design tokens, nv-card, nv-serif, theme-aware).
 */
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";

// The five-step engine, straight from the Copilot tour ("How the copilot thinks").
const STEPS = [
  { n: "01", t: "Ground", d: "Reads your real holdings and scores — the facts every answer stands on." },
  { n: "02", t: "Reason", d: "Specialist agents weigh health, quality, exit, tax, goals and allocation." },
  { n: "03", t: "Verdict", d: "One plain-language sentence names the problem — no jargon wall." },
  { n: "04", t: "Rank", d: "Fixes numbered by rupee impact, so you know what to do first." },
  { n: "05", t: "Approve", d: "Nothing executes without your consent; a human advisor is one tap away." },
];

// The stops the tour walks through.
const STOPS = [
  "Ask “what should I fix first?” and watch it show its work",
  "Three ways forward — return, risk and effort, compared side by side",
  "The verdict: top actions ranked by rupee impact, with a live plan",
  "The approval gate — every buy, sell, cost and tax previewed first",
  "A human handoff when a question needs a real advisor",
  "The advisor cockpit, and the whole loop on mobile",
];

export default function CopilotTourArticle() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const assetBase = import.meta.env.BASE_URL; // respects staging base path (e.g. "/v5/")

  return (
    <div style={{ padding: isMobile ? "0 4px" : "0" }}>
      {/* VIDEO */}
      <figure style={{ margin: "0 0 10px" }}>
        <div className="nv-card" style={{ padding: 0, overflow: "hidden", borderRadius: 14, background: "#06080F" }}>
          <video
            data-testid="copilot-tour-video"
            aria-label="Two-minute guided tour of Nivesh Copilot"
            poster={`${assetBase}nivesh-copilot-tour-poster.jpg`}
            controls
            playsInline
            preload="metadata"
            style={{ width: "100%", display: "block", aspectRatio: "16 / 9", background: "#06080F" }}
          >
            <source src={`${assetBase}nivesh-copilot-tour.mp4`} type="video/mp4" />
            <track kind="captions" srcLang="en" label="English" src={`${assetBase}nivesh-copilot-tour.en.vtt`} default />
            Your browser can’t play embedded video —{" "}
            <a href={`${assetBase}nivesh-copilot-tour.mp4`}>download the tour</a> instead.
          </video>
        </div>
        <figcaption className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", letterSpacing: ".04em", marginTop: 10, textAlign: "center" }}>
          A guided walk through the Nivesh Copilot — investor &amp; advisor, desktop &amp; mobile. ~2 minutes.
        </figcaption>
      </figure>

      <p style={pStyle(isMobile)}>
        Most investing tools hand you a dashboard and leave you to figure out what matters.
        <b> Nivesh Copilot does the opposite</b> — it reads your whole portfolio and tells you the
        one thing to fix first, in plain language, ranked by what it’s actually worth in rupees.
        The two-minute tour above walks the full loop, end to end.
      </p>

      {/* HOW IT THINKS */}
      <h2 className="nv-serif" style={h2Style}>How the copilot thinks</h2>
      <p style={pStyle(isMobile)}>
        Every answer follows the same five steps — grounded data in, a ranked, consent-gated action out.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 12, margin: "8px 0 22px" }}>
        {STEPS.map((s, i) => (
          <div
            key={s.n}
            className="nv-card"
            style={{ padding: "16px 18px", borderLeft: "3px solid var(--mint)", gridColumn: !isMobile && i === STEPS.length - 1 && STEPS.length % 2 === 1 ? "1 / -1" : undefined }}
          >
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".1em", color: "var(--mint)" }}>{s.n} · {s.t.toUpperCase()}</div>
            <div style={{ fontSize: 14.5, lineHeight: 1.5, marginTop: 6, color: "var(--ink-2)" }}>{s.d}</div>
          </div>
        ))}
      </div>

      {/* WHAT YOU'LL SEE */}
      <h2 className="nv-serif" style={h2Style}>What you’ll see in the tour</h2>
      <div className="nv-card" style={{ padding: isMobile ? "18px 20px" : "22px 26px", margin: "8px 0 22px" }}>
        <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 12 }}>
          {STOPS.map((s) => (
            <li key={s} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
              <span style={{ color: "var(--mint)", fontWeight: 700, lineHeight: 1.5, flex: "0 0 auto" }}>→</span>
              <span style={{ fontSize: 15, lineHeight: 1.55, color: "var(--ink-2)" }}>{s}</span>
            </li>
          ))}
        </ul>
      </div>

      <p style={{ ...pStyle(isMobile), fontWeight: 500, color: "var(--ink)" }}>
        Same engine, two audiences: the everyday investor self-serving in the app, and the advisor
        triaging a whole book of clients — both grounded in the same live data.
      </p>

      {/* CTA */}
      <div className="nv-card" style={{ padding: isMobile ? "24px 20px" : "30px 32px", margin: "28px 0 8px", textAlign: "center" }}>
        <h3 className="nv-serif" style={{ fontSize: isMobile ? 26 : 32, letterSpacing: "-0.02em", margin: 0 }}>
          See it on your own portfolio
        </h3>
        <p style={{ fontSize: 15, color: "var(--ink-2)", margin: "12px auto 0", maxWidth: 440, lineHeight: 1.6 }}>
          Read-only, SEBI-aligned analysis that grades your holdings and tells you what to fix — in plain language.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap", marginTop: 22 }}>
          <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
            Check my portfolio free
          </button>
          <button className="nv-btn" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/copilot")}>
            Explore the Copilot
          </button>
        </div>
      </div>
    </div>
  );
}

const h2Style: React.CSSProperties = {
  fontSize: 28,
  letterSpacing: "-0.02em",
  margin: "34px 0 12px",
};

function pStyle(isMobile: boolean): React.CSSProperties {
  return {
    fontSize: isMobile ? 16 : 17,
    lineHeight: 1.7,
    color: "var(--ink-2)",
    margin: "0 0 18px",
  };
}
