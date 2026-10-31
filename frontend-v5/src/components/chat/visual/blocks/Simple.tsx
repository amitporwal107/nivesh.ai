/**
 * The three text blocks: `trade_plan` (the desk's own compact plan card, read by id, as the chat's trade idea card
 * shows it), `list` (warnings, events, reasons) and `notice` (a callout for stale or missing data; a warning is loud).
 */
import { Link } from "react-router-dom";
import { labTicketPath } from "@/components/chat/TradePlanChatCard";
import { DecisionCardById } from "@/pages/CopilotApp/screens/tradingdesk/decision/DecisionCard";
import type { ListBlock, NoticeBlock, TradePlanBlock } from "../schema";
import { toneColor } from "../format";
import type { BlockProps } from "./common";

export function TradePlanView({ b }: BlockProps<TradePlanBlock>) {
  return (
    <div data-testid="va-trade-plan" data-plan-id={b.plan_id} className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <DecisionCardById planId={b.plan_id} testId="va-plan" variant="row" budgets />
      <Link data-testid="va-plan-open" to={labTicketPath(b.plan_id)} style={{ alignSelf: "flex-start", fontSize: 12.5, fontWeight: 600, color: "var(--mint)", textDecoration: "none" }}>
        Open it on the desk ›
      </Link>
    </div>
  );
}

const MARK: Record<string, string> = { up: "▲", down: "▼", warn: "!", neutral: "›" };

export function ListView({ b }: BlockProps<ListBlock>) {
  return (
    <ul data-testid="va-list" className="m-0 flex list-none flex-col p-0" style={{ gap: 6 }}>
      {b.items.map((it, i) => (
        <li key={i} data-testid="va-list-item" data-tone={it.tone ?? "neutral"} className="flex min-w-0 items-start" style={{ gap: 8, fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          <span aria-hidden style={{ flex: "none", width: 12, textAlign: "center", color: toneColor(it.tone), fontSize: it.tone === "up" || it.tone === "down" ? 9 : 13 }}>{MARK[it.tone ?? "neutral"]}</span>
          <span className="flex min-w-0 flex-col" style={{ overflowWrap: "anywhere" }}>
            <span data-testid="va-list-text">{it.tone === "warn" && <span className="sr-only">Warning: </span>}{it.text}</span>
            {it.sub && <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>{it.sub}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function NoticeView({ b }: BlockProps<NoticeBlock>) {
  const warn = b.tone === "warn";
  return (
    <div data-testid="va-notice" data-tone={b.tone} role={warn ? "alert" : "note"} className="flex min-w-0 items-start"
      style={{ gap: 10, padding: "9px 12px", borderRadius: 10, border: `1px solid ${warn ? "var(--amber-line)" : "var(--line-2)"}`, background: warn ? "var(--amber-soft)" : "var(--bg-2)" }}>
      <span style={{ flex: "none", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", paddingTop: 2, color: warn ? "var(--amber)" : "var(--cp-ink-3)" }}>
        {warn ? "Warning" : "Note"}
      </span>
      <span data-testid="va-notice-text" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{b.text}</span>
    </div>
  );
}
