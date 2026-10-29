/**
 * MarketCommentaryPage — /market-commentary (latest edition) and /market-commentary/:date.
 *
 * The nightly "Closing Bell" video: an end-of-day wrap of the NSE session read off the Smart Trading Desk,
 * built and checked by tools/closing_bell and published after the close (about 23:15 IST on trading days).
 * Public page inside the marketing shell, like the blog. Data: editions.ts (static files, no backend route).
 */
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import MarketingShell from "@/components/marketing/MarketingShell";
import { useIsMobile } from "@/hooks/use-is-mobile";
import { type Edition, fileUrl, languagesOf, useEditions, useTranscript } from "./editions";

/** The on-page disclaimer in each narration language (the video's own closing line says the same). */
const DISCLAIMER: Record<string, { main: string; fno: string }> = {
  en: {
    main: "Market information and education, not investment advice. The Top 10 ideas are for review, not recommendations, and the desk’s own scorecard shows no measurable ranking skill yet. Do your own research.",
    fno: "9 out of 10 individual traders in equity F&O incurred net losses (SEBI study).",
  },
  hi: {
    main: "यह बाज़ार की जानकारी और शिक्षा है, निवेश सलाह नहीं। टॉप 10 आइडिया समीक्षा के लिए हैं, सिफ़ारिशें नहीं, और डेस्क के अपने स्कोरकार्ड में अभी रैंकिंग की कोई मापने योग्य क्षमता नहीं दिखी है। अपना शोध स्वयं करें।",
    fno: "इक्विटी F&O में 10 में से 9 व्यक्तिगत ट्रेडरों को शुद्ध नुकसान हुआ (SEBI अध्ययन)।",
  },
  ta: {
    main: "இது சந்தைத் தகவலும் கல்வியும் மட்டுமே, முதலீட்டு ஆலோசனை அல்ல. டாப் 10 யோசனைகள் பரிசீலனைக்கானவை, பரிந்துரைகள் அல்ல; டெஸ்கின் சொந்த மதிப்பீட்டில் இன்னும் அளவிடக்கூடிய தரவரிசைத் திறன் தெரியவில்லை. உங்கள் சொந்த ஆய்வைச் செய்யுங்கள்.",
    fno: "ஈக்விட்டி F&O-இல் 10-இல் 9 தனிநபர் வர்த்தகர்கள் நிகர இழப்பைச் சந்தித்தனர் (SEBI ஆய்வு).",
  },
  mr: {
    main: "ही बाजाराची माहिती आणि शिक्षण आहे, गुंतवणूक सल्ला नाही. टॉप 10 कल्पना आढाव्यासाठी आहेत, शिफारसी नाहीत, आणि डेस्कच्या स्वतःच्या स्कोअरकार्डमध्ये अजून मोजता येईल अशी क्रमवारी क्षमता दिसलेली नाही. स्वतः संशोधन करा.",
    fno: "इक्विटी F&O मध्ये 10 पैकी 9 वैयक्तिक ट्रेडर्सना निव्वळ तोटा झाला (SEBI अभ्यास).",
  },
  gu: {
    main: "આ બજારની માહિતી અને શિક્ષણ છે, રોકાણ સલાહ નથી. ટોપ 10 આઇડિયા સમીક્ષા માટે છે, ભલામણો નહીં, અને ડેસ્કના પોતાના સ્કોરકાર્ડમાં હજુ માપી શકાય તેવી રેન્કિંગ ક્ષમતા દેખાઈ નથી. તમારું પોતાનું સંશોધન કરો.",
    fno: "ઇક્વિટી F&Oમાં 10માંથી 9 વ્યક્તિગત ટ્રેડર્સને ચોખ્ખું નુકસાન થયું (SEBI અભ્યાસ).",
  },
};

export default function MarketCommentaryPage() {
  const { date } = useParams();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const idx = useEditions();
  const editions = idx.data?.editions ?? [];
  const edition: Edition | undefined = date ? editions.find((e) => e.date === date) : editions[0];

  return (
    <MarketingShell>
      <article data-testid="market-commentary" style={{ maxWidth: 820, margin: "0 auto", padding: isMobile ? "36px 20px 24px" : "64px 56px 32px" }}>
        <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--mint)", textTransform: "uppercase" }}>
          Market commentary · Closing Bell
        </div>

        {idx.isPending && (
          <div data-testid="mc-loading" aria-busy="true" style={{ marginTop: 18 }}>
            <div style={{ height: 44, width: "70%", borderRadius: 8, background: "var(--line-2)" }} />
            <div style={{ marginTop: 22, aspectRatio: "16 / 9", borderRadius: 14, background: "var(--line-2)" }} />
          </div>
        )}

        {idx.isError && (
          <Notice testId="mc-error" title="The commentary list could not be loaded">
            Please try again in a minute. If it keeps failing, the editions are still being published and will be back shortly.
          </Notice>
        )}

        {idx.isSuccess && editions.length === 0 && (
          <Notice testId="mc-empty" title="The first edition is on its way">
            Closing Bell is published after the market closes on trading days, once the day's data is in — usually around 11:15 PM IST.
          </Notice>
        )}

        {idx.isSuccess && editions.length > 0 && !edition && (
          <Notice testId="mc-not-found" title={`No edition for ${date}`}>
            There was no Closing Bell for that date (a holiday, or it did not pass its checks).{" "}
            <Link to="/market-commentary">Watch the latest edition →</Link>
          </Notice>
        )}

        {edition && <EditionView edition={edition} isMobile={isMobile} />}

        {editions.length > 1 && (
          <section data-testid="mc-archive" style={{ marginTop: 36 }}>
            <h2 className="nv-serif" style={{ fontSize: 26, letterSpacing: "-0.02em", margin: "0 0 12px" }}>Earlier editions</h2>
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
              {editions.filter((e) => e.date !== edition?.date).slice(0, 20).map((e) => (
                <li key={e.date}>
                  <Link
                    to={`/market-commentary/${e.date}`}
                    data-testid={`mc-archive-${e.date}`}
                    className="nv-card"
                    style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "12px 16px", textDecoration: "none", color: "var(--ink)" }}
                  >
                    <span style={{ fontWeight: 600 }}>{e.day_long}</span>
                    <span className="nv-mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>{e.duration_label}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 32 }}>
          <button className="nv-btn nv-btn-primary" style={{ padding: "12px 20px", fontSize: 15 }} onClick={() => navigate("/login")}>
            Open the Smart Trading Desk
          </button>
          <button className="nv-btn" style={{ padding: "12px 20px", fontSize: 15 }} onClick={() => navigate("/")}>
            Back to home
          </button>
        </div>
      </article>
    </MarketingShell>
  );
}

function EditionView({ edition, isMobile }: { edition: Edition; isMobile: boolean }) {
  const [params, setParams] = useSearchParams();
  const langs = languagesOf(edition);
  const lang = langs.find((l) => l.code === params.get("lang")) ?? langs[0];
  const tr = useTranscript(edition, lang);
  const disc = DISCLAIMER[lang.code] ?? DISCLAIMER.en;
  const choose = (code: string) => {
    const next = new URLSearchParams(params);
    if (code === "en") next.delete("lang");
    else next.set("lang", code);
    setParams(next, { replace: true });
  };
  return (
    <>
      <h1 className="nv-serif" style={{ fontSize: isMobile ? 32 : 48, lineHeight: 1.05, letterSpacing: "-0.03em", margin: "12px 0 0" }}>
        Closing Bell — {edition.day_long}
      </h1>
      <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-4)", letterSpacing: ".06em", margin: "14px 0 18px" }}>
        End-of-day NSE wrap · {edition.duration_label} · {langs.length > 1 ? `voiceover in ${langs.length} languages` : "English voiceover"}, captions available
      </div>

      {langs.length > 1 && (
        <div
          role="group"
          aria-label="Commentary language"
          data-testid="mc-langs"
          style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, margin: "0 0 12px" }}
        >
          <span className="nv-mono" style={{ fontSize: 10, color: "var(--ink-4)", letterSpacing: ".1em", textTransform: "uppercase", marginRight: 2 }}>
            Language
          </span>
          {langs.map((l) => (
            <button
              key={l.code}
              type="button"
              lang={l.code}
              data-testid={`mc-lang-${l.code}`}
              aria-pressed={l.code === lang.code}
              onClick={() => choose(l.code)}
              className={"nv-btn" + (l.code === lang.code ? " nv-btn-primary" : "")}
              style={{ padding: "6px 14px", fontSize: 13 }}
            >
              {l.label}
            </button>
          ))}
        </div>
      )}

      <figure style={{ margin: "0 0 14px" }}>
        <div className="nv-card" style={{ padding: 0, overflow: "hidden", borderRadius: 14, background: "#06080F" }}>
          <video
            key={edition.date + lang.code}
            data-testid="mc-video"
            aria-label={`Closing Bell market commentary for ${edition.day_long}`}
            poster={fileUrl(edition.files.poster)}
            controls
            playsInline
            preload="metadata"
            style={{ width: "100%", display: "block", aspectRatio: "16 / 9", background: "#06080F" }}
          >
            <source src={fileUrl(lang.video)} type="video/mp4" />
            <track kind="captions" srcLang={lang.code} label={lang.label} src={fileUrl(lang.captions)} default={lang.code !== "en"} />
            Your browser can’t play embedded video — <a href={fileUrl(lang.video)}>download the bulletin</a> instead.
          </video>
        </div>
      </figure>

      {edition.headlines.length > 0 && (
        <section data-testid="mc-headlines" aria-label="Headlines" style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 10, margin: "18px 0" }}>
          {edition.headlines.map((h) => (
            <div key={h.kicker} className="nv-card" style={{ padding: "14px 16px" }}>
              <div className="nv-mono" style={{ fontSize: 10.5, letterSpacing: ".14em", textTransform: "uppercase", color: "var(--mint)" }}>{h.kicker}</div>
              <div style={{ fontWeight: 700, fontSize: 17, margin: "6px 0 4px" }}>{h.big}</div>
              <div style={{ fontSize: 13.5, lineHeight: 1.5, color: "var(--ink-2)" }}>{h.small}</div>
            </div>
          ))}
        </section>
      )}

      <div
        className="nv-card"
        data-testid="mc-disclaimer"
        style={{ padding: isMobile ? "14px 16px" : "16px 20px", margin: "8px 0 22px", borderLeft: "3px solid var(--gold, #E8B04B)" }}
      >
        <p lang={lang.code} style={{ margin: 0, fontSize: 15, lineHeight: 1.6, color: "var(--ink)" }}>
          <b>{disc.main}</b>
        </p>
        <p lang={lang.code} style={{ margin: "10px 0 0", fontSize: 13, lineHeight: 1.6, color: "var(--ink-3)" }}>
          {disc.fno}
        </p>
      </div>

      <h2 className="nv-serif" style={{ fontSize: 26, letterSpacing: "-0.02em", margin: "28px 0 12px" }}>
        Transcript <span style={{ fontSize: 16, color: "var(--ink-3)", letterSpacing: 0 }}>· {lang.label}</span>
      </h2>
      <div className="nv-card" data-testid="mc-transcript" lang={lang.code} style={{ padding: isMobile ? "14px 16px" : "18px 22px" }}>
        {tr.isPending && <p style={{ margin: 0, color: "var(--ink-3)" }}>Loading the transcript…</p>}
        {tr.isError && <p data-testid="mc-transcript-error" style={{ margin: 0, color: "var(--ink-3)" }}>The transcript could not be loaded. The captions in the player carry the same text.</p>}
        {tr.data?.sections.map((s, i) => (
          <section key={s.tag + i} style={{ marginTop: i === 0 ? 0 : 20 }}>
            <h3 style={{ margin: "0 0 8px", fontSize: 13, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--mint)" }}>
              {s.tag} <span style={{ color: "var(--ink-3)", textTransform: "none", letterSpacing: 0, fontWeight: 500 }}>· {s.title}</span>
            </h3>
            <ol style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 9 }}>
              {s.cues.map((c) => (
                <li key={c.t + c.text.slice(0, 12)} style={{ display: "grid", gridTemplateColumns: "48px 1fr", gap: 12, alignItems: "baseline" }}>
                  <span className="nv-mono" style={{ fontSize: 12, color: "var(--mint)", fontVariantNumeric: "tabular-nums" }}>{c.t}</span>
                  <span style={{ fontSize: 15, lineHeight: 1.6, color: "var(--ink-2)" }}>{c.text}</span>
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>

      <p data-testid="mc-sources" style={{ fontSize: 13, lineHeight: 1.6, color: "var(--ink-3)", margin: "18px 0 6px" }}>
        Data: NSE end-of-day index and stock closes, exchange filings and NSE provisional FII/DII figures (via Sensibull), as shown on the
        Smart Trading Desk. The desk is recorded read-only: nothing is traded or sent to a broker. Every number in the script is checked
        against its source before an edition is published.
      </p>
      <p data-testid="mc-credit" style={{ fontSize: 13, lineHeight: 1.6, color: "var(--ink-3)", margin: 0 }}>
        Music: “The Complex” by Kevin MacLeod (incompetech.com), licensed under{" "}
        <a href="https://creativecommons.org/licenses/by/3.0/" target="_blank" rel="noreferrer" style={{ color: "var(--ink-2)" }}>
          Creative Commons Attribution 3.0
        </a>
        .
      </p>
    </>
  );
}

function Notice({ testId, title, children }: { testId: string; title: string; children: React.ReactNode }) {
  return (
    <div data-testid={testId} role="status" className="nv-card" style={{ padding: "20px 22px", marginTop: 18 }}>
      <h1 className="nv-serif" style={{ fontSize: 28, letterSpacing: "-0.02em", margin: 0 }}>{title}</h1>
      <p style={{ fontSize: 15, lineHeight: 1.6, color: "var(--ink-2)", margin: "10px 0 0" }}>{children}</p>
    </div>
  );
}
