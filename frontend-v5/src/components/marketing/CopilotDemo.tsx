/**
 * CopilotDemo — the floating "ask the copilot" widget on the Login page.
 *
 * It's a self-contained, front-end-only demo: a small scripted brain that
 * answers questions about a fixed sample portfolio so a first-time visitor
 * can feel the product before signing in. No network, no real holdings.
 *
 * Bot answer bodies are static, hand-authored HTML (bold / coloured spans),
 * so they're injected via dangerouslySetInnerHTML — there is no user content
 * in them. The user's own typed text is always rendered as plain text.
 */
import { useEffect, useRef, useState } from "react";
import "./nvx-theme.css";
import "./CopilotDemo.css";

type Msg = { role: "user"; text: string } | { role: "bot"; html: string } | { role: "typing" };

// scripted brain — answers tied to the sample portfolio described on the page
const BRAIN: Array<{ k: string[]; a: string }> = [
  {
    k: ["overlap", "61", "same", "diversif", "duplicate"],
    a: `Your <b>HDFC Flexi Cap</b> and <b>Parag Parikh Flexi</b> hold many of the same large-caps — about <b>61%</b> of their top positions are identical. You're paying two funds to do one job, so you get the cost of diversification without the benefit. <span class="good">Keeping one</span> and redirecting the SIP would tidy this up.`,
  },
  {
    k: ["fix", "first", "what should", "do next", "priority", "improve"],
    a: `Start with the <b>ICICI Pru Technology</b> position. It's a narrow sector bet, and your monthly <b>SWP</b> is triggering a <span class="flag">1% exit load</span> each time — roughly <span class="flag">1.4%/yr</span> lost. Pause the SWP or move to the direct plan and you recover most of it. That one change lifts health from <b>62</b> toward the <span class="good">mid-70s</span>.`,
  },
  {
    k: ["62", "health", "score", "low", "only"],
    a: `<b>62</b> is "fine, not optimal." Three things hold it down: the <b>61% overlap</b> between two funds, the <span class="flag">exit-load drag</span> on the tech fund, and an idle IDCW reinvestment creating small TDS friction. None are urgent — but the first two are worth fixing.`,
  },
  {
    k: ["exit", "load", "swp", "withdraw", "redeem", "redemption"],
    a: `A <b>1% exit load</b> inside the first year is standard — that's not the problem. The problem is you're hitting it <b>every month</b> via the SWP on ICICI Pru Tech. Move the SWP to a holding that's past its exit-load window and the bleed stops.`,
  },
  {
    k: ["cas", "statement", "how", "read", "inbox", "gmail", "work"],
    a: `A <b>CAS</b> (Consolidated Account Statement) lists every mutual-fund transaction across your folios. Nivesh reads it straight from your inbox — <b>no uploads</b>, read-only — and turns it into the plain-language score you see on the left.`,
  },
  {
    k: ["safe", "secure", "privacy", "store", "data", "trust"],
    a: `Access is <b>read-only</b> and revocable anytime. Statements are encrypted in transit and <span class="good">never stored</span> — Nivesh reads, scores, and forgets.`,
  },
  {
    k: ["hdfc", "flexi cap"],
    a: `<b>HDFC Flexi Cap</b> is your largest holding and the healthier of the overlapping pair — broad mandate, steady. If you consolidate the overlap, this is the one most worth keeping.`,
  },
  {
    k: ["parag", "ppfas"],
    a: `<b>Parag Parikh Flexi</b> overlaps ~61% with your HDFC fund on large-caps. Solid fund on its own — it's the duplication that costs you, not the fund.`,
  },
  {
    k: ["sip", "invest more", "add", "buy"],
    a: `Before adding, fix the overlap — otherwise new SIP money compounds the duplication. Once consolidated, redirecting the SIP into a single flexi-cap keeps things clean.`,
  },
];

const FALLBACK = `I can break down the sample portfolio on the left — try <b>overlap</b>, <b>exit loads</b>, or <b>what to fix first</b>. Sign in to point me at your own holdings.`;
const GREETING = `Hi — I'm reading the sample portfolio on the left. Ask me why the health score is <b>62</b>, or what's worth fixing first.`;

const CHIPS = [
  { q: "Why is my health only 62?", label: "Why only 62?" },
  { q: "What should I fix first?", label: "What to fix first" },
  { q: "Explain the 61% overlap", label: "The 61% overlap" },
  { q: "Are my exit loads normal?", label: "Exit loads" },
];

function match(q: string): string {
  const t = q.toLowerCase();
  for (const e of BRAIN) {
    if (e.k.some((w) => t.includes(w))) return e.a;
  }
  return FALLBACK;
}

export default function CopilotDemo() {
  const [open, setOpen] = useState(false);
  const [greeted, setGreeted] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [field, setField] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const fieldRef = useRef<HTMLInputElement>(null);
  const launchRef = useRef<HTMLButtonElement>(null);
  const reduce = useRef(
    typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion:reduce)").matches,
  );

  // keep the transcript pinned to the latest message
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages]);

  // close on Escape while open
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") shut();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const addBot = (html: string) => {
    setMessages((m) => [...m, { role: "typing" }]);
    const delay = reduce.current ? 250 : 700;
    setTimeout(() => {
      setMessages((m) => {
        const out = m.filter((x) => x.role !== "typing");
        return [...out, { role: "bot", html }];
      });
    }, delay);
  };

  const ask = (q: string) => {
    if (!q.trim()) return;
    setMessages((m) => [...m, { role: "user", text: q }]);
    addBot(match(q));
  };

  const openPanel = () => {
    setOpen(true);
    if (!greeted) {
      setGreeted(true);
      addBot(GREETING);
    }
    setTimeout(() => fieldRef.current?.focus(), reduce.current ? 0 : 250);
  };

  const shut = () => {
    setOpen(false);
    launchRef.current?.focus();
  };

  const submit = () => {
    const v = field;
    setField("");
    ask(v);
  };

  return (
    <>
      <button
        ref={launchRef}
        type="button"
        className={`cp-launch${open ? " hidden" : ""}`}
        aria-label="Open the Nivesh copilot"
        onClick={openPanel}
      >
        <span className="sparkle">✦</span> Ask the copilot
      </button>

      <aside
        className={`cp-panel${open ? " open" : ""}`}
        role="dialog"
        aria-label="Nivesh copilot"
        aria-modal="false"
      >
        <header className="cp-head">
          <span className="nvx-mark">न</span>
          <div className="t">
            <div className="n">Nivesh copilot</div>
            <div className="s">Reading the sample portfolio</div>
          </div>
          <button type="button" className="cp-x" aria-label="Close copilot" onClick={shut}>
            ×
          </button>
        </header>

        <div className="cp-log" ref={logRef} aria-live="polite">
          {messages.map((m, i) => {
            if (m.role === "typing") {
              return (
                <div key={i} className="cp-typing">
                  <span />
                  <span />
                  <span />
                </div>
              );
            }
            if (m.role === "user") {
              return (
                <div key={i} className="cp-msg user">
                  {m.text}
                </div>
              );
            }
            return (
              <div key={i} className="cp-msg bot" dangerouslySetInnerHTML={{ __html: m.html }} />
            );
          })}
        </div>

        <div className="cp-chips">
          {CHIPS.map((c) => (
            <button key={c.q} type="button" className="cp-chip" onClick={() => ask(c.q)}>
              {c.label}
            </button>
          ))}
        </div>

        <div className="cp-input">
          <input
            ref={fieldRef}
            type="text"
            value={field}
            onChange={(e) => setField(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            placeholder="Ask about the sample portfolio…"
            autoComplete="off"
            aria-label="Message the copilot"
          />
          <button type="button" className="cp-send" aria-label="Send" onClick={submit}>
            <svg
              width="17"
              height="17"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M5 12h13M13 6l6 6-6 6" />
            </svg>
          </button>
        </div>
        <div className="cp-foot">Demo · sign in to ask about your own holdings</div>
      </aside>
    </>
  );
}
