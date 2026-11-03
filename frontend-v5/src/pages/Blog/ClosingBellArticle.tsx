/**
 * ClosingBellArticle — body for the blog post
 * "Watch: Closing Bell — market commentary for Tuesday, 27 October 2026".
 *
 * Video-first post, same pattern as ResearchTourArticle. The bulletin is an end-of-day
 * wrap read off the Smart Trading Desk (screen recording of the desk, recorded read-only,
 * with data cards and an English voiceover). Assets live in /public and resolve through
 * import.meta.env.BASE_URL so they work under the staging sub-path ("/v5/").
 *
 * SECTIONS is the bulletin script with its timestamps, generated from the same script
 * that produced the voiceover and public/closing-bell-27oct2026.en.vtt, so the printed
 * transcript and the captions say the same thing.
 */
import { useNavigate } from "react-router-dom";
import { useIsMobile } from "@/hooks/use-is-mobile";

const MEDIA = {
  mp4: "closing-bell-27oct2026.mp4",
  poster: "closing-bell-27oct2026-poster.jpg",
  vtt: "closing-bell-27oct2026.en.vtt",
};

const SECTIONS: { tag: string; title: string; cues: { t: string; text: string }[] }[] = [
  { tag: "Headlines", title: "Tonight's headlines", cues: [
    { t: "0:03", text: "Calm on the Nifty, fireworks underneath. Good evening, and welcome to Closing Bell on the Nivesh Desk." },
    { t: "0:12", text: "Here are tonight's headlines." },
    { t: "0:17", text: "The Nifty ends flat on expiry day, but smallcaps sprint more than two percent." },
    { t: "0:22", text: "Foreign investors turn buyers, with their biggest day of buying since early September." },
    { t: "0:28", text: "Results-day rallies in OneSource, Sona BLW, Mankind Pharma and Tata Consumer." },
    { t: "0:35", text: "And cement cracks. All of it, straight from the Smart Trading Desk." },
  ] },
  { tag: "Market wrap", title: "How the market closed", cues: [
    { t: "0:43", text: "First, the scoreboard. The Nifty 50 settled at 22,749.75, down just three and a half points, as the October series expired." },
    { t: "0:55", text: "Bank Nifty dragged, down 0.7 percent. But beneath the surface, the Smallcap 250 jumped 2.2 percent, the Next 50 rose 1.3, and the Midcap 150 gained 0.9." },
    { t: "1:09", text: "Breadth was strong. About two and a half stocks rose for every one that fell, and India VIX cooled 4.4 percent, to 16.4." },
    { t: "1:20", text: "Still, the desk's market regime reads Bear, so its new-trade size limits stay halved." },
  ] },
  { tag: "Results", title: "Results and the market's verdict", cues: [
    { t: "1:29", text: "To earnings. The desk's Results Week tracker shows 103 companies have declared so far, with 382 still to come." },
    { t: "1:38", text: "With no analyst consensus in the system, the desk scores each quarter against the company's own trend: 4 above, 31 in line, 5 below." },
    { t: "1:48", text: "OneSource Specialty Pharma rocketed 13.8 percent on 36 times its usual volume, after its profit grew more than five-fold." },
    { t: "1:58", text: "Sona BLW gained 9 percent, Eris 8.4, and Mankind Pharma 8.2. In the Nifty 50, Tata Consumer rose 6.8 percent on five times normal volume." },
    { t: "2:12", text: "On the downside, Aequs fell 9.6 percent, and Dalmia Bharat 6.6, on ten times its usual volume. REC slipped 3.9 percent after a 21 percent drop in profit." },
    { t: "2:25", text: "After the bell, the heavyweights reported. Bajaj Auto's profit rose 62 percent, to 3,436 crore rupees. L and T's rose 32.5 percent, and Radico's jumped 66." },
    { t: "2:41", text: "But Maruti's profit fell 26 percent, Cipla's 35, Mazagon Dock's 54, and ACC's 92. They all react tomorrow." },
  ] },
  { tag: "Sector rotation", title: "Where the money rotated", cues: [
    { t: "2:54", text: "Sector rotation now. Media led the indices, up 3.7 percent, with Capital Goods, Realty, Pharma, Telecom and Power all up around 2 percent." },
    { t: "3:05", text: "Financials lagged, with the bank indices down 0.7 percent. Cement was the weakest, down 2 percent, with 10 of its 12 stocks in the red." },
    { t: "3:16", text: "Over a month, IT leads, up 14 percent, while Metals and Consumer Durables are down more than 9 percent each. The desk's rotation matrix tags IT, Telecom and Consumer Services as leading." },
  ] },
  { tag: "Movers & shakers", title: "Nifty 50 · 100 · 200 · 500", cues: [
    { t: "3:33", text: "Movers and shakers, index by index. The Nifty 50 split 25 to 25. Tata Consumer and Bharti Airtel led, while Asian Paints, Coal India and Grasim fell the most." },
    { t: "3:46", text: "In the Nifty 100, advancers won 61 to 39. Hitachi Energy jumped 5.8 percent and Divi's 5, while Mazagon Dock sank 6.5 percent on six times its usual volume." },
    { t: "4:01", text: "The Nifty 200 went 128 to 72. Mankind topped the board at 8.2 percent, and M and M Financial was the worst, down 6.6." },
    { t: "4:13", text: "And in the Nifty 500, 356 stocks rose. Ola Electric surged 16.2 percent, OneSource 13.8 and Sun TV 10.9, while Aegis Logistics fell 7 percent." },
    { t: "4:28", text: "By sector: every media and realty stock in the 500 rose, and 18 of 19 power names. Construction materials managed just one gainer in eleven." },
  ] },
  { tag: "FII / DII flows", title: "Follow the money", cues: [
    { t: "4:41", text: "Follow the money. Provisional data show FIIs bought a net 4,240 crore rupees in cash today, their biggest buying day since the second of September. DIIs sold 1,250 crore." },
    { t: "4:56", text: "A rare role reversal. For October, FIIs are still net sellers of about 48,700 crore, and DIIs net buyers of 60,500 crore. Over three months, FIIs sold over one lakh crore, while DIIs bought over two lakh crore." },
    { t: "5:14", text: "The desk's flow chart runs to Monday; today's figures join with the next load. One day of buying is a signal, not yet a trend." },
  ] },
  { tag: "Top 10 ideas", title: "The desk's ideas for review", cues: [
    { t: "5:26", text: "Now, the desk's Top 10 ideas. These are ideas for review, not recommendations, and the desk's own scorecard shows no measurable ranking skill yet." },
    { t: "5:37", text: "ICICI Bank and Coforge lead the cash list. Coforge closed just 0.6 percent below resistance at 2,008.80, on 1.6 times average volume." },
    { t: "5:50", text: "Sagility, Anand Rathi, Union Bank, GE Shipping, Persistent, Mankind, Sona BLW and Petronet complete the ten." },
    { t: "6:00", text: "The F and O board reads a mixed regime with a falling trend, so it fits defined-risk bear put spreads, like the Nifty 22,350 to 22,750 spread for 3 November. The desk flags that this conflicts with the bullish cash setups, so those rows are information only." },
  ] },
  { tag: "What to watch", title: "Wednesday, 28 October", cues: [
    { t: "6:23", text: "Tomorrow: India's industrial production data at 4 PM, and the US Fed decision at 11:30 PM India time." },
    { t: "6:31", text: "Plus reactions to Bajaj Auto, Maruti, L and T and Cipla, and results from Hindustan Unilever, Adani Enterprises and Vedanta." },
    { t: "6:41", text: "That's Closing Bell from the Nivesh Desk." },
    { t: "6:44", text: "Market information and education, not investment advice. Good night." },
  ] },
];

export default function ClosingBellArticle() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const assetBase = import.meta.env.BASE_URL; // respects staging base path (e.g. "/v5/")

  return (
    <div style={{ padding: isMobile ? "0 4px" : "0" }}>
      {/* VIDEO */}
      <figure style={{ margin: "0 0 10px" }}>
        <div className="nv-card" style={{ padding: 0, overflow: "hidden", borderRadius: 14, background: "#06080F" }}>
          <video
            data-testid="closing-bell-video"
            aria-label="Closing Bell market commentary video for Tuesday, 27 October 2026"
            poster={`${assetBase}${MEDIA.poster}`}
            controls
            playsInline
            preload="metadata"
            style={{ width: "100%", display: "block", aspectRatio: "16 / 9", background: "#06080F" }}
          >
            <source src={`${assetBase}${MEDIA.mp4}`} type="video/mp4" />
            <track kind="captions" srcLang="en" label="English" src={`${assetBase}${MEDIA.vtt}`} />
            Your browser can’t play embedded video —{" "}
            <a href={`${assetBase}${MEDIA.mp4}`}>download the bulletin</a> instead.
          </video>
        </div>
        <figcaption className="nv-mono" style={{ fontSize: 11, color: "var(--ink-3)", letterSpacing: ".04em", marginTop: 10, textAlign: "center" }}>
          Closing Bell on the Nivesh Desk · Tuesday, 27 October 2026 · 6:51 · English voiceover, captions available.
        </figcaption>
      </figure>

      <p style={pStyle(isMobile)}>
        An end-of-day wrap of <b>Tuesday’s NSE session</b>, read straight off the Nivesh Smart Trading Desk:
        how the indices closed, which results moved stocks, where sectors rotated, the movers and shakers
        across the Nifty 50, 100, 200 and 500, what foreign and domestic institutions did with their money,
        and the desk’s Top 10 ideas for review.
      </p>

      {/* DISCLAIMER */}
      <div
        className="nv-card"
        data-testid="closing-bell-disclaimer"
        style={{ padding: isMobile ? "16px 18px" : "18px 22px", margin: "8px 0 22px", borderLeft: "3px solid var(--gold, #E8B04B)" }}
      >
        <p style={{ margin: 0, fontSize: 15, lineHeight: 1.6, color: "var(--ink)" }}>
          <b>Market information and education, not investment advice.</b> The Top 10 ideas are for review,
          not recommendations, and the desk’s own scorecard shows no measurable ranking skill yet. Do your own
          research.
        </p>
        <p style={{ margin: "10px 0 0", fontSize: 13, lineHeight: 1.6, color: "var(--ink-3)" }}>
          9 out of 10 individual traders in equity F&amp;O incurred net losses (SEBI study).
        </p>
      </div>

      {/* TRANSCRIPT */}
      <h2 className="nv-serif" style={h2Style}>Transcript</h2>
      <div className="nv-card" data-testid="closing-bell-transcript" style={{ padding: isMobile ? "16px 18px" : "20px 24px", margin: "0 0 22px" }}>
        {SECTIONS.map((s, i) => (
          <section key={s.tag} style={{ marginTop: i === 0 ? 0 : 22 }}>
            <h3 style={{ margin: "0 0 10px", fontSize: 13, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--mint)" }}>
              {s.tag} <span style={{ color: "var(--ink-3)", textTransform: "none", letterSpacing: 0, fontWeight: 500 }}>· {s.title}</span>
            </h3>
            <ol style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 10 }}>
              {s.cues.map((c) => (
                <li key={c.t} style={{ display: "grid", gridTemplateColumns: "48px 1fr", gap: 12, alignItems: "baseline" }}>
                  <span className="nv-mono" style={{ fontSize: 12, color: "var(--mint)", fontVariantNumeric: "tabular-nums" }}>{c.t}</span>
                  <span style={{ fontSize: 15, lineHeight: 1.6, color: "var(--ink-2)" }}>{c.text}</span>
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>

      {/* SOURCES + CREDIT */}
      <p data-testid="closing-bell-sources" style={{ fontSize: 13, lineHeight: 1.6, color: "var(--ink-3)", margin: "0 0 8px" }}>
        Data: NSE end-of-day index and stock closes, exchange filings and NSE provisional FII/DII figures (via
        Sensibull), as shown on the Smart Trading Desk on 27 October 2026; year-on-year profit changes from
        Trendlyne. The desk was recorded read-only: nothing was traded or sent to a broker.
      </p>
      <p data-testid="closing-bell-credit" style={{ fontSize: 13, lineHeight: 1.6, color: "var(--ink-3)", margin: "0 0 18px" }}>
        Music: “The Complex” by Kevin MacLeod (incompetech.com), licensed under{" "}
        <a href="https://creativecommons.org/licenses/by/3.0/" target="_blank" rel="noreferrer" style={{ color: "var(--ink-2)" }}>
          Creative Commons Attribution 3.0
        </a>
        .
      </p>

      {/* CTA */}
      <div className="nv-card" style={{ padding: isMobile ? "24px 20px" : "30px 32px", margin: "28px 0 8px", textAlign: "center" }}>
        <h3 className="nv-serif" style={{ fontSize: isMobile ? 26 : 32, letterSpacing: "-0.02em", margin: 0 }}>
          See the desk behind the bulletin
        </h3>
        <p style={{ fontSize: 15, color: "var(--ink-2)", margin: "12px auto 0", maxWidth: 460, lineHeight: 1.6 }}>
          Every number in Closing Bell comes from the Smart Trading Desk: index heatmaps, results week,
          sector rotation and institutional flows, in one place.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap", marginTop: 22 }}>
          <button className="nv-btn nv-btn-primary" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/login")}>
            Start free
          </button>
          <button className="nv-btn" style={{ padding: "14px 22px", fontSize: 15 }} onClick={() => navigate("/blog")}>
            More from the blog
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
