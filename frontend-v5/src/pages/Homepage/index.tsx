/**
 * Homepage — public landing, redesigned from the niveshhome mockup.
 *
 * The hero "health card" wires to real API data when a returning visitor is
 * signed in (LIVE pill); otherwise it shows the sample portfolio (PREVIEW).
 * The on-page product tour reuses the shared <ProductTour /> slideshow.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useHealthAnalysis } from "@/hooks/use-insights";
import { usePortfolioSummary } from "@/hooks/use-portfolio";
import ProductTour from "@/components/marketing/ProductTour";
import "@/components/marketing/nvx-theme.css";
import "./homepage.css";

function gradeLabel(score: number) {
  if (score >= 85) return "Grade A";
  if (score >= 70) return "Grade B";
  if (score >= 55) return "Grade C";
  return "Grade D";
}

// tile colour bucket, matching the mockup's c-g / c-a / c-r split
function bucket(v: number): "g" | "a" | "r" {
  if (v >= 70) return "g";
  if (v >= 50) return "a";
  return "r";
}

// Sample portfolio shown when no live data is available (PREVIEW state).
const SAMPLE_SCORE = 67;
const SAMPLE_TILES: Array<{ label: string; v: number }> = [
  { label: "Risk", v: 77 },
  { label: "Concen", v: 58 },
  { label: "Diverse", v: 31 },
  { label: "Cost", v: 78 },
  { label: "Tax", v: 64 },
  { label: "Goals", v: 42 },
];

const STEPS = [
  { n: "01", t: "Read every holding", d: "Gmail CAS, statement PDF, or live broker. Equities, mutual funds, FDs, NPS — all reconciled in a single ledger." },
  { n: "02", t: "Score it across 20 checks", d: "Concentration, overlap, risk, cost, tax, goals. Each scored individually, then weighted into one A-to-D grade." },
  { n: "03", t: "Show you what to do", d: "Ranked actions with the exact fund or stock, the trade-off, and a one-tap simulation before you commit." },
];

const DOMAINS = [
  { t: "Concentration", c: "5 checks", d: "House, group, sector and single-name limits — flagged the moment any one gets too big." },
  { t: "Overlap", c: "3 checks", d: "Duplicate plans and funds that secretly hold the same stocks, so you stop paying twice." },
  { t: "Risk", c: "4 checks", d: "Equity-debt drift, volatility and downside versus your stated risk profile." },
  { t: "Cost", c: "3 checks", d: "Expense ratios, regular-vs-direct leakage and exit-load drag, rupee-quantified." },
  { t: "Tax", c: "3 checks", d: "Harvestable losses, LTCG headroom and the tax cost of every suggested move." },
  { t: "Goals", c: "2 checks", d: "Whether each holding is actually pulling toward a goal and its timeline." },
];

export default function HomepagePage() {
  const navigate = useNavigate();
  const rootRef = useRef<HTMLDivElement>(null);
  const { data: health } = useHealthAnalysis();
  const { data: summary } = usePortfolioSummary();
  const [showDemo, setShowDemo] = useState(false);
  const assetBase = import.meta.env.BASE_URL; // respects the staging "/v5/" base path

  // Real scores when available, otherwise the sample portfolio.
  // useHealthAnalysis() nests the payload under `health: { health_score, breakdown }`,
  // so the score and dimensions live one level under `health` (not on the root).
  const h = health as any;
  const liveScore: number | null =
    h?.health?.health_score ?? h?.health?.score ?? (summary as any)?.healthScore ?? null;
  const isLive = liveScore != null;
  const targetScore = liveScore ?? SAMPLE_SCORE;

  const liveBreakdown = h?.health?.breakdown as Record<string, number> | undefined;
  const liveDims: Array<{ label: string; v: number }> | null = liveBreakdown
    ? Object.entries(liveBreakdown)
        .slice(0, 6)
        .map(([k, v]) => ({ label: k.replace(/_/g, " ").slice(0, 7), v: Math.round(Number(v)) }))
    : null;
  const tiles = liveDims && liveDims.length > 0 ? liveDims : SAMPLE_TILES;

  // Count-up animation for the headline score.
  const [score, setScore] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion:reduce)").matches) {
      setScore(targetScore);
      return;
    }
    const dur = 1200;
    const t0 = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / dur);
      setScore(Math.round(targetScore * (1 - Math.pow(1 - k, 3))));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [targetScore]);

  // Reveal-on-scroll for `.rv` elements within this page.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const els = Array.from(root.querySelectorAll<HTMLElement>(".rv"));
    if (!("IntersectionObserver" in window) || window.matchMedia("(prefers-reduced-motion:reduce)").matches) {
      els.forEach((e) => e.classList.add("in"));
      return;
    }
    const io = new IntersectionObserver(
      (ents) => {
        ents.forEach((en) => {
          if (en.isIntersecting) {
            en.target.classList.add("in");
            io.unobserve(en.target);
          }
        });
      },
      { threshold: 0.14 },
    );
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, []);

  // Close the promo video on Escape.
  useEffect(() => {
    if (!showDemo) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowDemo(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [showDemo]);

  const scrollTo = (id: string) => {
    rootRef.current?.querySelector(`#${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="nvx nvx-home" ref={rootRef} id="top">
      <div className="nvx-topline" />

      <header className="nav">
        <div className="wrap nav-inner">
          <a className="nvx-brand" onClick={() => scrollTo("top")} style={{ cursor: "pointer" }}>
            <span className="nvx-mark">न</span>
            <b>Nivesh</b>
          </a>
          <nav className="nav-links">
            <a onClick={() => scrollTo("tour")}>Product</a>
            <a onClick={() => scrollTo("how")}>How it works</a>
            <a onClick={() => scrollTo("scored")}>What we score</a>
            <a onClick={() => navigate("/security")}>Security</a>
          </nav>
          <div className="nav-right">
            <span className="signin" onClick={() => navigate("/login")}>
              Sign in
            </span>
            <button className="btn-primary" onClick={() => navigate("/login")}>
              Check my portfolio
            </button>
          </div>
        </div>
      </header>

      <main>
        <section className="wrap hero">
          <div className="hero-left">
            <span className="pill h-rv d1">
              <span className="tag">NEW</span> Goal-aware rebalancing, live <span className="chev">›</span>
            </span>
            <h1 className="head h-rv d2">
              Your portfolio,
              <br />
              <em>finally</em> legible<span className="dot">.</span>
            </h1>
            <p className="sub h-rv d2">
              Nivesh reads every holding, scores its health and rewrites the report in plain language —
              so you know exactly what to fix and why.
            </p>
            <div className="cta-row h-rv d3">
              <button className="btn-primary btn-lg" onClick={() => navigate("/login")}>
                Check my portfolio free
              </button>
              <button className="btn-ghost btn-lg" onClick={() => setShowDemo(true)}>
                Watch the 90-second tour
              </button>
            </div>
            <div className="trust h-rv d3">
              <span>SEBI-aligned</span>
              <span>Read-only access</span>
              <span>No card needed</span>
            </div>
          </div>

          {/* health card — real data when signed in, sample otherwise */}
          <div className="hero-right h-rv d4">
            <div className="health">
              <div className="hc-chrome">
                <span className="d" />
                <span className="d" />
                <span className="d" />
                <span className="hc-url">nivesh.app/health</span>
                <span className="hc-live">{isLive ? "LIVE" : "PREVIEW"}</span>
              </div>
              <div className="hc-body">
                <div className="hc-label">Portfolio health</div>
                <div className="hc-score">
                  <span className="hc-num">{score}</span>
                  <span className="hc-den">/ 100</span>
                  <span className="hc-grade">{gradeLabel(targetScore)}</span>
                  <span className="hc-yp">{isLive ? "your portfolio" : "sample portfolio"}</span>
                </div>
                <div className="hc-tiles">
                  {tiles.map((tile) => {
                    const b = bucket(tile.v);
                    return (
                      <div className="hc-tile" key={tile.label}>
                        <b className={`c-${b}`}>{tile.v}</b>
                        <span className="trk">
                          <s className={`f-${b}`} style={{ ["--v" as any]: (tile.v / 100).toFixed(2) }} />
                        </span>
                        <label>{tile.label}</label>
                      </div>
                    );
                  })}
                </div>
                <div className="hc-foot">
                  <span>
                    {isLive ? "Your portfolio, scored live" : "Fair — diversification is the weak spot"}
                  </span>
                  <span className="acts" style={{ cursor: "pointer" }} onClick={() => navigate(isLive ? "/dashboard" : "/login")}>
                    {isLive ? "Open the dashboard →" : "6 actions → Grade A"}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* product tour */}
        <section className="wrap section" id="tour">
          <div className="section-head">
            <h2>
              See every screen <em>before</em> you sign in.
            </h2>
            <p>
              The same workspace your portfolio loads into — dashboard, x-ray, fixes, plan board and
              copilot. Hover any screen to zoom in.
            </p>
          </div>
          <div className="tour rv">
            <ProductTour host="nivesh.app" showLive />
          </div>
        </section>

        {/* how it works */}
        <section className="wrap section" id="how" style={{ paddingTop: 0 }}>
          <div className="steps-card">
            {STEPS.map((s) => (
              <div className="step rv" key={s.n}>
                <div className="num">{s.n}</div>
                <h3>{s.t}</h3>
                <p>{s.d}</p>
              </div>
            ))}
          </div>
        </section>

        {/* what we score */}
        <section className="wrap section" id="scored" style={{ paddingTop: 0 }}>
          <div className="section-head">
            <h2>
              One grade, <em>twenty</em> honest checks.
            </h2>
            <p>
              Nothing hand-wavy. Each domain is scored on its own, then weighted into the number you
              see up top.
            </p>
          </div>
          <div className="scored">
            {DOMAINS.map((d) => (
              <div className="dom rv" key={d.t}>
                <div className="dh">
                  <b>{d.t}</b>
                  <span>{d.c}</span>
                </div>
                <p>{d.d}</p>
              </div>
            ))}
          </div>
        </section>

        {/* CTA band */}
        <section className="wrap section" style={{ paddingTop: 0 }}>
          <div className="cta-band rv">
            <p className="eyebrow" style={{ marginBottom: 16 }}>
              <b>★</b> SEBI-aligned · ARN-128459
            </p>
            <h2>
              Make your portfolio <em>legible</em> today.
            </h2>
            <p>
              Connect read-only in under a minute. No card, no commitment — just a clear grade and the
              exact moves to raise it.
            </p>
            <div className="cta-row">
              <button className="btn-primary btn-lg" onClick={() => navigate("/login")}>
                Check my portfolio free
              </button>
              <button className="btn-ghost btn-lg" onClick={() => setShowDemo(true)}>
                Watch the 90-second tour
              </button>
            </div>
          </div>
        </section>

        <footer className="wrap foot">
          <a className="nvx-brand" onClick={() => scrollTo("top")} style={{ cursor: "pointer" }}>
            <span className="nvx-mark">न</span>
            <b>Nivesh</b>
          </a>
          <span className="meta">SEBI-aligned · ARN-128459 · India-hosted (Bangalore)</span>
          <nav className="flinks">
            <a onClick={() => navigate("/login")}>Sign in</a>
            <a onClick={() => navigate("/security")}>Security</a>
            <a onClick={() => navigate("/privacy")}>Privacy</a>
            <a onClick={() => navigate("/contact")}>Contact</a>
          </nav>
        </footer>
      </main>

      {/* 90-second investor promo video */}
      {showDemo && (
        <div
          className="demo-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="Nivesh 90-second promo"
          onClick={() => setShowDemo(false)}
        >
          <div className="demo-modal" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="demo-close"
              aria-label="Close video"
              onClick={() => setShowDemo(false)}
            >
              ×
            </button>
            <video
              poster={`${assetBase}nivesh-demo-poster.jpg`}
              controls
              autoPlay
              playsInline
              style={{ width: "100%", height: "100%" }}
            >
              <source src={`${assetBase}nivesh-demo-90s.webm`} type="video/webm" />
              <source src={`${assetBase}nivesh-demo-90s.mp4`} type="video/mp4" />
            </video>
          </div>
        </div>
      )}
    </div>
  );
}
