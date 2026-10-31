/**
 * `briefs`: cards of companies or filings — what the Copilot answers to "which companies report results?", "any order wins?",
 * "how were TCS results?" (owner, 31 Oct 2026). Each card: the company, when and what (sub), a badge in words (a result's rating
 * Below / Meets / Above expectation against the company's own baseline, or an AI classifier's reading), the five-line AI commentary
 * with its signal chip (🟢 positive · 🔴 negative · 🟡 mixed · ⚪ informational, impact, confidence; owner, 1 Nov 2026), the STORED
 * AI summary verbatim (or "Not analysed yet"), management-commentary points (shown on request), and the source filings to download.
 *
 * A link is drawn only when schema.ts's safeFilingUrl accepts it (https on an exchange or SEBI host); it opens in a new tab with
 * rel="noopener noreferrer". The block is one column of cards at any width, so a phone never scrolls sideways.
 */
import { useId, useState } from "react";
import type { BriefsBlock } from "../schema";
import { toneColor } from "../format";
import type { BlockProps } from "./common";
import { quiet } from "./common";

type Brief = BriefsBlock["items"][number];
const CLAMP_CHARS = 240;
const MARK: Record<string, string> = { up: "▲", down: "▼", warn: "!", neutral: "›" };
/** The signal chip's colour and its word for a screen reader (colour is never the only cue: the label is printed too). */
const SIGNAL: Record<string, { color: string; word: string }> = {
  up: { color: "var(--mint)", word: "Positive" }, down: { color: "var(--cp-danger)", word: "Negative" },
  warn: { color: "var(--amber)", word: "Mixed" }, neutral: { color: "var(--cp-ink-3)", word: "Informational" },
};

function Commentary({ c }: { c: NonNullable<Brief["commentary"]> }) {
  const sig = SIGNAL[c.signal.tone] ?? SIGNAL.neutral;
  const chip = [c.signal.label, c.signal.impact ? `${c.signal.impact} impact` : null, c.signal.confidence != null ? `confidence ${c.signal.confidence}%` : null].filter(Boolean).join(" · ");
  return (
    <section data-testid="va-brief-commentary" data-tone={c.signal.tone} aria-label={`AI commentary, ${sig.word}`} className="flex min-w-0 flex-col"
      style={{ gap: 5, padding: "8px 10px", borderRadius: 8, background: "var(--bg-2)", border: "1px solid var(--cp-line)" }}>
      <span data-testid="va-brief-signal" className="inline-flex items-center" style={{ gap: 7, fontSize: 11.5, fontWeight: 600, color: sig.color, letterSpacing: "0.04em", textTransform: "uppercase" }}>
        <span aria-hidden style={{ width: 9, height: 9, borderRadius: 999, background: sig.color, flex: "none" }} />
        <span>{chip}</span>
      </span>
      <ol className="m-0 flex list-none flex-col p-0" style={{ gap: 3 }}>
        {c.lines.map((l, i) => (
          <li key={i} data-testid="va-brief-line" data-label={l.label} style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
            <strong style={{ color: "var(--cp-ink)", fontWeight: 600 }}>{l.label}:</strong> {l.text}
          </li>
        ))}
      </ol>
    </section>
  );
}

function BriefCard({ it, ask }: { it: Brief; ask?: (q: string) => void }) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const long = (it.body?.length ?? 0) > CLAMP_CHARS;
  const more = long || it.points.length > 0;
  const color = it.badge ? toneColor(it.tone) : "var(--cp-ink-3)";
  return (
    <li data-testid="va-brief" data-symbol={it.symbol ?? ""} data-expanded={open ? "true" : "false"} className="flex min-w-0 flex-col"
      style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--cp-line)", borderLeft: `3px solid ${it.badge ? color : "var(--line-2)"}`, background: "var(--bg-2)" }}>
      <div className="flex min-w-0 flex-wrap items-baseline justify-between" style={{ gap: "4px 10px" }}>
        <span className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "0 8px" }}>
          <strong data-testid="va-brief-title" style={{ fontSize: 14, lineHeight: 1.35, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{it.title}</strong>
          {it.symbol && <span data-testid="va-brief-symbol" className="cp-num" style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>{it.symbol}</span>}
        </span>
        {it.badge && (
          <span data-testid="va-brief-badge" data-tone={it.tone ?? "neutral"} style={{ fontSize: 11.5, lineHeight: 1.3, padding: "2px 8px", borderRadius: 999, border: `1px solid ${color}`, color, overflowWrap: "anywhere" }}>
            {it.tone === "up" ? "▲ " : it.tone === "down" ? "▼ " : ""}{it.badge}
          </span>
        )}
      </div>
      {it.sub && <span data-testid="va-brief-sub" style={{ ...quiet, overflowWrap: "anywhere" }}>{it.sub}</span>}
      {it.commentary && <Commentary c={it.commentary} />}

      {it.body ? (
        <p id={bodyId} data-testid="va-brief-body" className="m-0"
          style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink)", overflowWrap: "anywhere",
            ...(open || !long ? {} : { display: "-webkit-box", WebkitLineClamp: 4, WebkitBoxOrient: "vertical" as const, overflow: "hidden" }) }}>
          {it.body}
        </p>
      ) : (
        <p data-testid="va-brief-empty" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-ink-3)", padding: "4px 8px", borderRadius: 8, border: "1px dashed var(--line-2)", alignSelf: "flex-start" }}>
          {it.body_note || "Not analysed yet"}
        </p>
      )}
      {it.body && it.body_note && <span data-testid="va-brief-note" style={{ ...quiet, fontSize: 11.5, overflowWrap: "anywhere" }}>{it.body_note}</span>}

      {open && it.points.length > 0 && (
        <section data-testid="va-brief-points-box" className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <h5 className="cp-eyebrow m-0" style={{ fontWeight: 400, fontSize: 9.5, color: "var(--cp-ink-3)" }}>Management commentary and open questions (AI-read of the filings)</h5>
          <ul data-testid="va-brief-points" className="m-0 flex list-none flex-col p-0" style={{ gap: 4 }}>
            {it.points.map((p, i) => (
              <li key={i} data-testid="va-brief-point" data-tone={p.tone ?? "neutral"} className="flex min-w-0 items-start" style={{ gap: 8, fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
                <span aria-hidden style={{ flex: "none", width: 12, textAlign: "center", color: toneColor(p.tone), fontSize: p.tone === "up" || p.tone === "down" ? 9 : 13 }}>{MARK[p.tone ?? "neutral"]}</span>
                <span style={{ overflowWrap: "anywhere" }}>{p.tone === "up" && <span className="sr-only">Positive: </span>}{p.tone === "down" && <span className="sr-only">Negative: </span>}{p.text}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        {more && (
          <button type="button" data-testid="va-brief-more" className="cp-btn" data-variant="ghost" aria-expanded={open} aria-controls={it.body ? bodyId : undefined}
            onClick={() => setOpen(!open)} style={{ padding: "6px 10px", fontSize: 12.5, minHeight: 34 }}>
            {open ? "Show less" : it.points.length ? `Show commentary (${it.points.length}) ›` : "Read more ›"}
          </button>
        )}
        {it.ask && (
          <button type="button" data-testid="va-brief-ask" className="cp-btn" data-variant="ghost" disabled={!ask} title={it.ask} aria-label={`Ask: ${it.ask}`}
            onClick={() => ask?.(it.ask as string)} style={{ padding: "6px 10px", fontSize: 12.5, minHeight: 34 }}>
            Ask ›
          </button>
        )}
      </div>

      {it.links.length > 0 && (
        <ul data-testid="va-brief-links" aria-label={`Source filings of ${it.title}`} className="m-0 flex list-none flex-wrap p-0" style={{ gap: 6 }}>
          {it.links.map((l, i) => (
            <li key={`${l.url}-${i}`} className="min-w-0">
              <a data-testid="va-brief-link" data-kind={l.kind} href={l.url} target="_blank" rel="noopener noreferrer" className="cp-btn" data-variant="ghost"
                style={{ display: "inline-flex", alignItems: "center", padding: "6px 10px", minHeight: 34, fontSize: 12.5, fontWeight: 600, color: "var(--mint)", textDecoration: "none", overflowWrap: "anywhere" }}>
                {l.label} ›<span className="sr-only"> (opens in a new tab)</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function BriefsView({ b, ask }: BlockProps<BriefsBlock>) {
  return (
    <ul data-testid="va-briefs" className="m-0 flex list-none flex-col p-0" style={{ gap: 10 }}>
      {b.items.map((it, i) => <BriefCard key={`${it.symbol ?? it.title}-${i}`} it={it} ask={ask} />)}
    </ul>
  );
}
