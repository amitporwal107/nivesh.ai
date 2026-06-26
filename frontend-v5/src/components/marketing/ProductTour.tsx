/**
 * ProductTour — a stories-style auto-advancing slideshow of the real
 * product screens, ported from the niveshhome / niveshlogin mockups.
 *
 * Used in two places:
 *   • Homepage — inside a rounded ".tour" browser card under the hero.
 *   • Login    — in the left rail, full-bleed.
 *
 * Screens live in /public/tour/NN.webp and are referenced through
 * import.meta.env.BASE_URL so the staging "/v5/" base path is respected.
 *
 * Behaviour faithfully reproduces the prototype: progress segments fill
 * over DWELL ms, hover pauses, ‹ ›/arrow keys step, and on a fine pointer
 * a magnifier lens lets you inspect any screen (scroll to change zoom).
 * All of it degrades cleanly under prefers-reduced-motion.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import "./nvx-theme.css";
import "./ProductTour.css";

type Slide = { img: string; title: string; sub: string; path: string };

const SLIDES: Slide[] = [
  { img: "01.webp", title: "Onboarding", sub: "Pick your mode — investor or advisor", path: "start" },
  { img: "02.webp", title: "Connect investments", sub: "Gmail CAS, upload, or CDSL OTP", path: "connect" },
  { img: "03.webp", title: "Dashboard", sub: "Health, value and risk at a glance", path: "portfolio" },
  { img: "04.webp", title: "Portfolio X-ray", sub: "115 funds → 1,107 stocks → 81 real bets", path: "x-ray" },
  { img: "05.webp", title: "Concentration", sub: "Diversified by stock, concentrated by house", path: "concentration" },
  { img: "06.webp", title: "Allocation vs cap", sub: "HDFC at 41% — over the 30% house cap", path: "concentration/amc" },
  { img: "07.webp", title: "Fund overlap", sub: "Duplicate plans and redundant pairs", path: "overlap" },
  { img: "08.webp", title: "Remediation plan", sub: "Ranked by rupees saved per move", path: "fix" },
  { img: "09.webp", title: "Recommendations", sub: "6 actions, each with the why and tax", path: "actions" },
  { img: "10.webp", title: "Tax harvesting", sub: "₹105K in losses to harvest this FY", path: "tax" },
  { img: "11.webp", title: "Plan board", sub: "Execute every action, end to end", path: "plan" },
  { img: "12.webp", title: "Copilot", sub: "Ask anything, in plain language", path: "ask" },
  { img: "13.webp", title: "Advisor home", sub: "Your whole client book, triaged", path: "advisor" },
  { img: "14.webp", title: "Client 360", sub: "A full read before you open a portfolio", path: "advisor/clients" },
  { img: "15.webp", title: "Market Pulse", sub: "Indices, breadth and global cues", path: "markets" },
  { img: "16.webp", title: "Earnings tracker", sub: "Q4 FY26 results across sectors", path: "markets/earnings" },
  { img: "17.webp", title: "FII / DII flows", sub: "Who's buying, who's selling", path: "markets/flows" },
  { img: "18.webp", title: "Corporate actions", sub: "Dividends, splits and buybacks", path: "markets/actions" },
];

const DWELL = 4200;
const pad = (n: number) => String(n + 1).padStart(2, "0");

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion:reduce)").matches;
}

export default function ProductTour({
  host = "nivesh.app",
  showLive = false,
}: {
  /** Host shown in the fake browser chrome (e.g. "nivesh.app", "app.nivesh.in"). */
  host?: string;
  /** Show the LIVE pill in the chrome (Homepage) or not (Login). */
  showLive?: boolean;
}) {
  const [idx, setIdx] = useState(0);
  const reduce = useRef(prefersReducedMotion());
  const pausedRef = useRef(false);
  const idxRef = useRef(0);
  idxRef.current = idx;

  const frameRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const segInnerRefs = useRef<Array<HTMLElement | null>>([]);

  const go = useCallback((n: number) => {
    setIdx(((n % SLIDES.length) + SLIDES.length) % SLIDES.length);
  }, []);

  // Paint the stories progress segments whenever the active slide changes.
  // The current segment is reset to 0 then transitions to 100% over DWELL.
  useEffect(() => {
    segInnerRefs.current.forEach((bar, i) => {
      if (!bar) return;
      const seg = bar.parentElement as HTMLElement;
      seg.classList.remove("now", "done");
      if (i < idx) {
        seg.classList.add("done");
      } else if (i === idx) {
        bar.style.transition = "none";
        bar.style.width = "0%";
        void bar.offsetWidth; // force reflow so the fill restarts
        if (!reduce.current) {
          seg.style.setProperty("--dwell", `${DWELL}ms`);
          seg.classList.add("now");
        } else {
          bar.style.width = "100%";
        }
      } else {
        bar.style.transition = "none";
        bar.style.width = "0%";
      }
    });
  }, [idx]);

  // Auto-advance. Re-created on each slide change so the timer always lines
  // up with the progress bar (manual nav restarts the dwell, like the proto).
  useEffect(() => {
    if (reduce.current) return;
    const t = setInterval(() => {
      if (!pausedRef.current) setIdx((i) => (i + 1) % SLIDES.length);
    }, DWELL);
    return () => clearInterval(t);
  }, [idx]);

  // Magnifier lens — only on a fine pointer (mouse). Created once and reads
  // the live slide through idxRef so we don't rebind on every advance.
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp || !window.matchMedia("(pointer:fine)").matches) return;

    const L = 190;
    const MIN_Z = 2.0;
    const MAX_Z = 4.5;
    let Z = 2.4;
    let curSrc = "";
    let lastE: MouseEvent | null = null;

    const lens = document.createElement("div");
    lens.className = "lens";
    lens.setAttribute("aria-hidden", "true");
    const hint = document.createElement("div");
    hint.className = "zoom-hint";
    hint.textContent = "⊕ hover to zoom · scroll to adjust";
    vp.appendChild(lens);
    vp.appendChild(hint);

    const currentImg = () =>
      vp.querySelectorAll<HTMLImageElement>(".slide img")[idxRef.current] ?? null;

    const box = (img: HTMLImageElement) => {
      const cw = vp.clientWidth;
      const ch = vp.clientHeight;
      const nw = img.naturalWidth;
      const nh = img.naturalHeight;
      if (!nw || !nh) return null;
      const s = Math.min(cw / nw, ch / nh);
      const rw = nw * s;
      const rh = nh * s;
      return { rw, rh, ox: (cw - rw) / 2, oy: (ch - rh) / 2 };
    };

    const draw = (e: MouseEvent) => {
      lastE = e;
      const img = currentImg();
      if (!img) return;
      const r = vp.getBoundingClientRect();
      const mx = e.clientX - r.left;
      const my = e.clientY - r.top;
      const b = box(img);
      if (!b || mx < b.ox || mx > b.ox + b.rw || my < b.oy || my > b.oy + b.rh) {
        lens.style.opacity = "0";
        return;
      }
      const ix = (mx - b.ox) / b.rw;
      const iy = (my - b.oy) / b.rh;
      const src = img.currentSrc || img.src;
      if (src !== curSrc) {
        lens.style.backgroundImage = `url("${src}")`;
        curSrc = src;
      }
      const bw = b.rw * Z;
      const bh = b.rh * Z;
      let bx = L / 2 - ix * bw;
      let by = L / 2 - iy * bh;
      bx = Math.min(0, Math.max(L - bw, bx));
      by = Math.min(0, Math.max(L - bh, by));
      lens.style.backgroundSize = `${bw}px ${bh}px`;
      lens.style.backgroundPosition = `${bx}px ${by}px`;
      lens.style.left = `${mx - L / 2}px`;
      lens.style.top = `${my - L / 2}px`;
      lens.style.opacity = "1";
      hint.classList.add("gone");
    };

    const leave = () => {
      lens.style.opacity = "0";
      curSrc = "";
    };
    const wheel = (e: WheelEvent) => {
      if (lens.style.opacity !== "1") return;
      e.preventDefault();
      Z = Math.min(MAX_Z, Math.max(MIN_Z, Z + (e.deltaY < 0 ? 0.3 : -0.3)));
      if (lastE) draw(lastE);
    };

    vp.addEventListener("mousemove", draw);
    vp.addEventListener("mouseleave", leave);
    vp.addEventListener("wheel", wheel, { passive: false });
    return () => {
      vp.removeEventListener("mousemove", draw);
      vp.removeEventListener("mouseleave", leave);
      vp.removeEventListener("wheel", wheel);
      lens.remove();
      hint.remove();
    };
  }, []);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowRight") go(idx + 1);
    else if (e.key === "ArrowLeft") go(idx - 1);
  };

  const base = import.meta.env.BASE_URL; // e.g. "/" locally, "/v5/" on staging
  const cur = SLIDES[idx];

  return (
    <div className="showcase">
      <div
        className="frame"
        ref={frameRef}
        tabIndex={0}
        onMouseEnter={() => (pausedRef.current = true)}
        onMouseLeave={() => (pausedRef.current = false)}
        onKeyDown={onKeyDown}
      >
        <div className="chrome">
          <span className="dotc" style={{ background: "#ED6A5E" }} />
          <span className="dotc" style={{ background: "#E6A552" }} />
          <span className="dotc" style={{ background: "#5FE7A6" }} />
          <span className="url">{`${host}/${cur.path}`}</span>
          {showLive && <span className="live-pill">LIVE</span>}
        </div>

        <div className="stories" role="tablist" aria-label="Product tour">
          {SLIDES.map((s, i) => (
            <button
              key={s.img}
              type="button"
              className="seg"
              role="tab"
              aria-selected={i === idx}
              aria-label={`Go to ${s.title}`}
              onClick={() => go(i)}
            >
              <i ref={(el) => (segInnerRefs.current[i] = el)} />
            </button>
          ))}
        </div>

        <div className="viewport" ref={viewportRef}>
          {SLIDES.map((s, i) => (
            <figure key={s.img} className={`slide${i === idx ? " active" : ""}`}>
              <img
                src={`${base}tour/${s.img}`}
                alt={`${s.title} — ${s.sub}`}
                loading="lazy"
                draggable={false}
              />
            </figure>
          ))}
        </div>

        <button type="button" className="navarrow prev" aria-label="Previous screen" onClick={() => go(idx - 1)}>
          ‹
        </button>
        <button type="button" className="navarrow next" aria-label="Next screen" onClick={() => go(idx + 1)}>
          ›
        </button>
      </div>

      <div className="caption">
        <div className="ctxt">
          <span className="cttl">{cur.title}</span>
          <span className="csub">{cur.sub}</span>
        </div>
        <span className="counter">
          <b>{pad(idx)}</b> / {SLIDES.length}
        </span>
      </div>
    </div>
  );
}
