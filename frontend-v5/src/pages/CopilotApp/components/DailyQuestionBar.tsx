/**
 * The Daily Trader Copilot's six entry points as a strip that stays with the conversation (owner, 31 Oct: "this screen
 * disappears after asking a question"). DailyTraderPanel is the empty state; once a thread has turns, this bar keeps the
 * same question sets one tap away: a chip per entry point, and the chosen one lists its questions. A question asks at once.
 * The questions are DAILY_TILES', so the panel and the bar can never differ.
 */
import { useState } from "react";
import { DAILY_TILES, type DailyTile } from "./DailyTraderPanel";

export function DailyQuestionBar({ onAsk, busy, mobile }: { onAsk: (question: string) => void; busy: boolean; mobile: boolean }) {
  const [open, setOpen] = useState<DailyTile["key"] | null>(null);
  const tile = DAILY_TILES.find((t) => t.key === open) ?? null;

  return (
    <div data-testid="daily-bar" className="flex min-w-0 flex-col" style={{ gap: 8, padding: mobile ? "8px 0 4px" : "10px 0 6px" }}>
      <div role="toolbar" aria-label="Daily trader questions" className="flex cp-scroll" style={{ gap: 8, overflowX: "auto", paddingBottom: 2 }}>
        {DAILY_TILES.map((t) => {
          const on = t.key === open;
          const Icon = t.icon;
          return (
            <button key={t.key} type="button" data-testid={`daily-bar-${t.key}`} aria-expanded={on} aria-controls="daily-bar-questions"
              onClick={() => setOpen(on ? null : t.key)}
              className="flex items-center"
              style={{ flex: "none", gap: 7, padding: "7px 12px", borderRadius: 999, cursor: "pointer", fontFamily: "var(--sans)", fontSize: 13, whiteSpace: "nowrap",
                border: `1px solid ${on ? "var(--mint-line)" : "var(--cp-line)"}`, background: on ? "var(--mint-soft)" : "var(--bg-2)", color: "var(--cp-ink)" }}>
              <Icon aria-hidden size={14} strokeWidth={1.8} style={{ color: on ? "var(--mint)" : "var(--cp-ink-2)" }} />
              {t.label}
            </button>
          );
        })}
      </div>
      {tile && (
        <div id="daily-bar-questions" data-testid="daily-bar-questions" role="group" aria-label={`${tile.label} questions`} className="flex flex-col"
          style={{ border: "1px solid var(--cp-line)", borderRadius: 12, background: "var(--bg-2)", overflow: "hidden" }}>
          {tile.questions.map((q, i) => (
            <button key={q} type="button" data-testid="daily-bar-q" disabled={busy} onClick={() => { onAsk(q); setOpen(null); }}
              style={{ padding: "10px 14px", border: 0, borderTop: i ? "1px solid var(--cp-line)" : 0, background: "none", textAlign: "left", fontFamily: "var(--sans)",
                fontSize: 14, color: busy ? "var(--cp-ink-3)" : "var(--cp-ink)", cursor: busy ? "default" : "pointer" }}>
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
