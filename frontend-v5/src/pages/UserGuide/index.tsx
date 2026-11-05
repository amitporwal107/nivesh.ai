/**
 * UserGuidePage — /user-guide, ?lang=hi|ta|mr|gu (owner, 5 Nov 2026: "Please provide the links in the homepage. A complete
 * User Guide" and "Where user can choose the preferred language and the video link changes").
 *
 * One 16:43 guided-tour video in five languages, then the complete written guide in the chosen language. The language
 * buttons switch the video, its captions, the direct video link and the share link, and keep the choice in the URL. All
 * five videos share one timeline, so the playback position carries over a switch and a section's time is the same in
 * every language. Public page inside the marketing shell; no backend (guide-data.ts says where the files live).
 */
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import MarketingShell from "@/components/marketing/MarketingShell";
import { useIsMobile } from "@/hooks/use-is-mobile";
import {
  GUIDE_CHAPTERS, GUIDE_DURATION_LABEL, GUIDE_LANGS, GUIDE_POSTER, GUIDE_RECORDED, type GuideLangCode, type GuideSection,
  fmtTime, guideCaptionsUrl, guidePagePath, guideVideoUrl, langOf, useGuideText,
} from "./guide-data";

const mono: React.CSSProperties = { fontFamily: "var(--mono, ui-monospace, monospace)" };

export default function UserGuidePage() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const lang = langOf(params.get("lang"));
  const text = useGuideText(lang.code);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  // Where the last video was when the language changed: the new one starts there (and plays if the old one was playing).
  const carry = useRef<{ t: number; play: boolean } | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => setCopied(false), [lang.code]);

  const choose = (code: GuideLangCode) => {
    if (code === lang.code) return;
    const v = videoRef.current;
    carry.current = v ? { t: v.currentTime, play: !v.paused && !v.ended } : null;
    const next = new URLSearchParams(params);
    if (code === "en") next.delete("lang");
    else next.set("lang", code);
    setParams(next, { replace: true });
  };

  const onLoadedMetadata = () => {
    const v = videoRef.current;
    const c = carry.current;
    if (!v || !c) return;
    carry.current = null;
    if (c.t > 0) v.currentTime = c.t;
    if (c.play) v.play().catch(() => undefined);
  };

  const seek = (t: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = t;
    v.play().catch(() => undefined);
    v.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const shareUrl = `${window.location.origin}${import.meta.env.BASE_URL.replace(/\/$/, "")}${guidePagePath(lang.code)}`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <MarketingShell>
      <article data-testid="user-guide" style={{ maxWidth: 860, margin: "0 auto", padding: isMobile ? "36px 20px 24px" : "64px 56px 32px" }}>
        <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--mint)", textTransform: "uppercase" }}>
          User guide · {GUIDE_DURATION_LABEL} video · 5 languages
        </div>
        <h1 className="nv-serif" style={{ fontSize: isMobile ? 32 : 48, lineHeight: 1.05, letterSpacing: "-0.03em", margin: "12px 0 0" }}>
          Nivesh Copilot, the complete user guide
        </h1>
        <p style={{ fontSize: 17, lineHeight: 1.6, color: "var(--ink-2)", margin: "14px 0 20px" }}>
          The problem every trader, investor, analyst, market researcher and advisor faces, then every screen of the trading desk, the
          Copilot chat, research and risk. Choose your language: the video, its captions and its link change with it.
        </p>

        <div role="group" aria-label="Video language" data-testid="ug-langs" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, margin: "0 0 12px" }}>
          <span className="nv-mono" style={{ fontSize: 10, color: "var(--ink-4)", letterSpacing: ".1em", textTransform: "uppercase", marginRight: 2 }}>
            Language
          </span>
          {GUIDE_LANGS.map((l) => (
            <button
              key={l.code}
              type="button"
              lang={l.code}
              data-testid={`ug-lang-${l.code}`}
              aria-pressed={l.code === lang.code}
              aria-label={`${l.label} (${l.name})`}
              onClick={() => choose(l.code)}
              className={"nv-btn" + (l.code === lang.code ? " nv-btn-primary" : "")}
              style={{ padding: "6px 14px", fontSize: 14 }}
            >
              {l.label}
            </button>
          ))}
        </div>

        <figure style={{ margin: "0 0 12px" }}>
          <div className="nv-card" style={{ padding: 0, overflow: "hidden", borderRadius: 14, background: "#06080F" }}>
            <video
              key={lang.code}
              ref={videoRef}
              data-testid="ug-video"
              data-lang={lang.code}
              aria-label={`Nivesh Copilot user guide, ${lang.name}`}
              src={guideVideoUrl(lang.code)}
              poster={GUIDE_POSTER}
              controls
              playsInline
              preload="metadata"
              onLoadedMetadata={onLoadedMetadata}
              style={{ width: "100%", display: "block", aspectRatio: "16 / 9", background: "#06080F" }}
            >
              <track data-testid="ug-captions" kind="captions" srcLang={lang.code} label={lang.label} src={guideCaptionsUrl(lang.code)} default={lang.code !== "en"} />
              Your browser can’t play embedded video — <a href={guideVideoUrl(lang.code)}>open the video file</a> instead.
            </video>
          </div>
        </figure>

        <div data-testid="ug-share" className="nv-card" style={{ padding: "12px 16px", display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 14px", fontSize: 14 }}>
          <span style={{ color: "var(--ink-3)" }}>Link to the {lang.name} guide:</span>
          <span data-testid="ug-share-url" style={{ ...mono, fontSize: 12.5, color: "var(--ink)", overflowWrap: "anywhere", minWidth: 0, flex: "1 1 260px" }}>{shareUrl}</span>
          <button type="button" data-testid="ug-copy" className="nv-btn" onClick={copy} style={{ padding: "5px 12px", fontSize: 13 }}>
            {copied ? "Copied" : "Copy link"}
          </button>
          <a data-testid="ug-direct" href={guideVideoUrl(lang.code)} target="_blank" rel="noreferrer" style={{ color: "var(--mint)", fontSize: 13 }}>
            Direct video link ({lang.label}) ↗
          </a>
          <span role="status" aria-live="polite" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>
            {copied ? "Link copied" : ""}
          </span>
        </div>

        <div className="nv-card" data-testid="ug-disclaimer" style={{ padding: isMobile ? "14px 16px" : "16px 20px", margin: "14px 0 0", borderLeft: "3px solid var(--gold, #E8B04B)" }}>
          <p lang={lang.code} style={{ margin: 0, fontSize: 15, lineHeight: 1.6, color: "var(--ink)" }}>
            <b>{lang.disclaimer}</b>
          </p>
          <p style={{ margin: "10px 0 0", fontSize: 13, lineHeight: 1.6, color: "var(--ink-3)" }}>
            9 out of 10 individual traders in equity F&amp;O incurred net losses (SEBI study). Paper trades are simulated.
          </p>
        </div>

        <h2 className="nv-serif" style={{ fontSize: 26, letterSpacing: "-0.02em", margin: "30px 0 12px" }}>Chapters</h2>
        <ol data-testid="ug-chapters" style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
          {GUIDE_CHAPTERS.map((c, i) => (
            <li key={c.key}>
              <button
                type="button"
                data-testid={`ug-chapter-${i}`}
                onClick={() => seek(c.t)}
                className="nv-card"
                style={{ width: "100%", display: "grid", gridTemplateColumns: "56px 1fr", gap: 12, alignItems: "baseline", padding: "10px 14px", textAlign: "left", cursor: "pointer", color: "var(--ink)", font: "inherit" }}
              >
                <span style={{ ...mono, fontSize: 13, color: "var(--mint)", fontVariantNumeric: "tabular-nums" }}>{fmtTime(c.t)}</span>
                <span style={{ fontSize: 15, fontWeight: 600 }}>{c.title}</span>
              </button>
            </li>
          ))}
        </ol>

        <h2 className="nv-serif" style={{ fontSize: 26, letterSpacing: "-0.02em", margin: "34px 0 6px" }}>
          The written guide <span style={{ fontSize: 16, color: "var(--ink-3)", letterSpacing: 0 }}>· {lang.label}</span>
        </h2>
        <p style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--ink-3)", margin: "0 0 14px" }}>
          The narration, section by section. Press a time to play that part of the video; “Open in the app” goes to the screen (sign-in needed).
        </p>

        {text.isPending && <p data-testid="ug-guide-loading" style={{ color: "var(--ink-3)" }}>Loading the written guide…</p>}
        {text.isError && (
          <div data-testid="ug-guide-error" role="status" className="nv-card" style={{ padding: "14px 16px", color: "var(--ink-2)", fontSize: 15, lineHeight: 1.6 }}>
            The written guide could not be loaded just now. The video and its captions carry the same text; please try again in a minute.
          </div>
        )}
        {text.data && (
          <div data-testid="ug-guide" lang={lang.code} style={{ display: "flex", flexDirection: "column", gap: 26 }}>
            {GUIDE_CHAPTERS.map((c) => {
              const secs = text.data.sections.filter((s) => s.chapter === c.key);
              if (!secs.length) return null;
              return (
                <section key={c.key} aria-label={c.title}>
                  <h3 lang="en" style={{ margin: "0 0 10px", fontSize: 13, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--mint)" }}>{c.title}</h3>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {secs.map((s) => <SectionCard key={s.id} s={s} onSeek={seek} />)}
                  </div>
                </section>
              );
            })}
          </div>
        )}

        <p data-testid="ug-notes" style={{ fontSize: 13, lineHeight: 1.6, color: "var(--ink-3)", margin: "26px 0 6px" }}>
          {GUIDE_RECORDED} with a real account, so the figures are as of that evening. Some desk views (Scan dashboard, Scan builder, Market
          Recovery, Portfolio hedge) are being switched on account by account and may not appear on yours yet. All five versions are narrated
          by synthetic voices.
        </p>
        <p data-testid="ug-credit" style={{ fontSize: 13, lineHeight: 1.6, color: "var(--ink-3)", margin: 0 }}>
          Music: “The Complex” by Kevin MacLeod (incompetech.com), licensed under{" "}
          <a href="https://creativecommons.org/licenses/by/3.0/" target="_blank" rel="noreferrer" style={{ color: "var(--ink-2)" }}>
            Creative Commons Attribution 3.0
          </a>
          .
        </p>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 30 }}>
          <button className="nv-btn nv-btn-primary" style={{ padding: "12px 20px", fontSize: 15 }} onClick={() => navigate("/login")}>
            Open Nivesh Copilot
          </button>
          <button className="nv-btn" style={{ padding: "12px 20px", fontSize: 15 }} onClick={() => navigate("/")}>
            Back to home
          </button>
        </div>
      </article>
    </MarketingShell>
  );
}

function SectionCard({ s, onSeek }: { s: GuideSection; onSeek: (t: number) => void }) {
  return (
    <div data-testid={`ug-section-${s.id}`} className="nv-card" style={{ padding: "14px 16px" }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "6px 12px" }}>
        <button
          type="button"
          data-testid={`ug-seek-${s.id}`}
          onClick={() => onSeek(s.t)}
          aria-label={`Play from ${fmtTime(s.t)}: ${s.label}`}
          style={{ ...mono, fontSize: 12.5, color: "var(--mint)", background: "none", border: "1px solid var(--mint-line, rgba(106,240,168,.28))", borderRadius: 999, padding: "2px 9px", cursor: "pointer" }}
        >
          ▶ {fmtTime(s.t)}
        </button>
        <h4 lang="en" style={{ margin: 0, fontSize: 15.5, fontWeight: 600, color: "var(--ink)" }}>{s.label}</h4>
        {s.app !== undefined && (
          <Link data-testid={`ug-open-${s.id}`} to={s.app ? `/app/${s.app}` : "/app"} style={{ marginLeft: "auto", fontSize: 13, color: "var(--ink-2)" }}>
            Open in the app ›
          </Link>
        )}
      </div>
      <p data-testid={`ug-text-${s.id}`} style={{ margin: "8px 0 0", fontSize: 15.5, lineHeight: 1.65, color: "var(--ink-2)" }}>{s.text}</p>
    </div>
  );
}
