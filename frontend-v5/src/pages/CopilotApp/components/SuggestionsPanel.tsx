/**
 * Smart query suggestions on the Copilot home (owner brief, 30 Oct: "Good morning! What would you like to explore?",
 * tabs For you / Market / My trades / F&O Lab, a card = a question + one line saying why, "Ask your own question" below).
 *
 * Every card is a rule's finding over real data with its as-of date, in one of three classes — informational ("To
 * explore"), validated signal ("Rule-based signal") and risk alert ("Risk check") — each with its own treatment. A
 * click asks the card's question, which opens the same visual answer as typing it. Dismiss / Useful / Not relevant go
 * to the backend; "Why am I seeing this?" shows the rule, its inputs and their dates. A source that is stale or
 * missing gives no card; the notice above the cards says which (prices stale, broker disconnected, no portfolio).
 * Source: GET /api/suggestions (use-suggestions.ts). Ideas to review, not advice; nothing is sent to a broker.
 */
import { useState } from "react";
import { RefreshCw, X } from "lucide-react";
import { useCopilotShell } from "../lib/shell-context";
import {
  suggestionMode, useSuggestionActions, useSuggestions, useSuggestionWhy, TAB_KEYS,
  type Suggestion, type SuggestionClass, type SuggestionNotice, type SuggestionTab,
} from "../lib/use-suggestions";
import { StockIcon } from "./EntityIcon";
import { fmtDate, TONE_COLOR, type Tone } from "./ui";

const TAB_LABEL: Record<SuggestionTab, string> = { for_you: "For you", market: "Market", my_trades: "My trades", fno_lab: "F&O Lab" };
const CLASS_TONE: Record<SuggestionClass, Tone> = { informational: "mint", validated_signal: "indigo", risk_alert: "amber" };

/** The owner's greeting, by the hour on the user's own clock. */
export function greetingFor(hour: number): string {
  const part = hour < 5 ? "Good evening" : hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  return `${part}! What would you like to explore?`;
}

function WhyPanel({ id }: { id: string }) {
  const q = useSuggestionWhy(id);
  const box = { padding: "10px 12px", borderRadius: 10, border: "1px solid var(--cp-line)", background: "var(--bg-2)", fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-2)" } as const;
  if (q.isLoading) return <div data-testid="sg-why" style={box} role="status" aria-label="Reading the rule">Reading the rule…</div>;
  if (q.isError || !q.data) return <div data-testid="sg-why" style={box}>The reason could not be loaded just now.</div>;
  const w = q.data;
  return (
    <div data-testid="sg-why" style={box} className="flex flex-col">
      <span data-testid="sg-why-rule" style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{w.rule.name ?? w.rule.id}</span>
      {w.rule.description && <span>{w.rule.description}</span>}
      <span className="cp-mono-note" style={{ marginTop: 6 }}>Data used</span>
      {w.inputs.map((i) => (
        <span key={i.name} data-testid="sg-why-input">
          {i.label} · {i.as_of ? `as of ${fmtDate(i.as_of)}` : "not dated"}{i.status ? ` · ${i.status}` : ""}
        </span>
      ))}
      {w.rule.cooldown_hours != null && <span style={{ marginTop: 6 }}>Not shown again for {w.rule.cooldown_hours} hours after you dismiss it.</span>}
    </div>
  );
}

function SuggestionCard({ s, onAsk, onFeedback }: { s: Suggestion; onAsk: (q: string) => void; onFeedback: (a: "dismissed" | "useful" | "not_relevant") => void }) {
  const [whyOpen, setWhyOpen] = useState(false);
  const [thanked, setThanked] = useState(false);
  const tone = CLASS_TONE[s.class];
  const link = { background: "none", border: 0, padding: "2px 0", cursor: "pointer", fontFamily: "var(--sans)", fontSize: 12, color: "var(--cp-ink-3)" } as const;
  return (
    <article data-testid="sg-card" data-class={s.class} data-rule={s.rule_id} aria-label={s.title}
      className="cp-card-raised flex flex-col"
      style={{ gap: 10, padding: 16, borderLeft: s.class === "risk_alert" ? `3px solid ${TONE_COLOR.amber}` : s.class === "validated_signal" ? `3px solid ${TONE_COLOR.indigo}` : undefined }}>
      <div className="flex items-center" style={{ gap: 8, fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>
        <span className="nv-dot" style={{ background: TONE_COLOR[tone] }} />
        <span data-testid="sg-class">{s.class_label}</span>
        {s.symbol && <span style={{ marginLeft: "auto" }}><StockIcon symbol={s.symbol} size={22} /></span>}
        <button type="button" data-testid="sg-dismiss" aria-label={`Dismiss: ${s.title}`} onClick={() => onFeedback("dismissed")}
          style={{ ...link, marginLeft: s.symbol ? 0 : "auto", display: "inline-flex" }}><X aria-hidden size={14} /></button>
      </div>
      <button type="button" data-testid="sg-ask" onClick={() => onAsk(s.query)}
        style={{ background: "none", border: 0, padding: 0, textAlign: "left", cursor: "pointer", color: "inherit", fontFamily: "var(--sans)" }} className="flex flex-col">
        <span data-testid="sg-title" className="cp-pretty" style={{ fontFamily: "var(--display)", fontSize: 19, lineHeight: 1.25, letterSpacing: "-0.01em" }}>{s.title}</span>
        <span data-testid="sg-why-line" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)", marginTop: 6 }}>{s.why}</span>
      </button>
      {s.footer && <span data-testid="sg-footer" style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{s.footer}</span>}
      <div className="flex flex-wrap items-center" style={{ gap: "2px 14px" }}>
        <button type="button" data-testid="sg-why-toggle" aria-expanded={whyOpen} onClick={() => setWhyOpen((v) => !v)} style={{ ...link, color: "var(--cp-ink-2)" }}>
          Why am I seeing this?
        </button>
        {thanked ? <span data-testid="sg-thanks" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>Noted</span> : (
          <button type="button" data-testid="sg-useful" onClick={() => { onFeedback("useful"); setThanked(true); }} style={link}>Useful</button>
        )}
        <button type="button" data-testid="sg-not-relevant" onClick={() => onFeedback("not_relevant")} style={link}>Not relevant</button>
      </div>
      {whyOpen && <WhyPanel id={s.id} />}
    </article>
  );
}

function NoticeBar({ n, go }: { n: SuggestionNotice; go: (v: string) => void }) {
  const action = n.action === "connect" ? { label: "Connect", to: "onboarding" }
    : n.action === "brokers" ? { label: "Reconnect", to: "page/brokers" }
    : n.action === "refresh_holdings" ? { label: "Update holdings", to: "page/brokers" } : null;
  return (
    <div data-testid="sg-notice" data-kind={n.kind} role="note" className="flex flex-wrap items-center"
      style={{ gap: "6px 12px", padding: "10px 14px", borderRadius: 12, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
      <span style={{ flex: "1 1 240px" }}>{n.text}</span>
      {action && <button type="button" className="cp-btn" data-testid="sg-notice-action" onClick={() => go(action.to)}>{action.label}</button>}
    </div>
  );
}

export function SuggestionsPanel() {
  const { ask, go, mode, mobile } = useCopilotShell();
  const m = suggestionMode(mode);
  const [tab, setTab] = useState<SuggestionTab>("for_you");
  const q = useSuggestions(tab, m, mode !== "advisor");
  const { refresh, feedback } = useSuggestionActions(tab, m);
  if (mode === "advisor") return null;

  const view = q.data;
  const greeting = greetingFor(new Date().getHours());
  return (
    <section data-testid="sg-panel" data-tab={tab} aria-label="Suggestions" className="flex flex-col" style={{ gap: 14 }}>
      <div className="flex flex-col" style={{ gap: 4 }}>
        <h2 data-testid="sg-greeting" className="m-0" style={{ fontFamily: "var(--sans)", fontWeight: 600, fontSize: mobile ? 20 : 24, lineHeight: 1.25 }}>{greeting}</h2>
        <p className="m-0" style={{ fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          Your suggestions update based on your connected portfolio and the latest available market data.
        </p>
      </div>

      <div className="flex items-center" style={{ gap: 10 }}>
        <div role="tablist" aria-label="Suggestion categories" className="flex" style={{ gap: 6, overflowX: "auto", flex: "1 1 auto", minWidth: 0 }}>
          {TAB_KEYS.map((k) => {
            const on = k === tab;
            const count = view?.tabs.find((t) => t.key === k)?.count;
            return (
              <button key={k} type="button" role="tab" aria-selected={on} data-testid={`sg-tab-${k}`} onClick={() => setTab(k)}
                style={{ flex: "0 0 auto", padding: "7px 14px", borderRadius: 999, cursor: "pointer", fontFamily: "var(--sans)", fontSize: 13.5, whiteSpace: "nowrap",
                  border: `1px solid ${on ? "var(--mint-line)" : "var(--cp-line)"}`, background: on ? "var(--mint-soft)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-2)" }}>
                {TAB_LABEL[k]}{count ? <span className="cp-num" style={{ marginLeft: 6, color: "var(--cp-ink-3)" }}>{count}</span> : null}
              </button>
            );
          })}
        </div>
        <button type="button" data-testid="sg-refresh" aria-label="Refresh suggestions" aria-busy={refresh.isPending} disabled={refresh.isPending}
          onClick={() => refresh.mutate()} className="cp-btn" style={{ flex: "0 0 auto", display: "inline-flex", alignItems: "center", gap: 6 }}>
          <RefreshCw aria-hidden size={14} className={refresh.isPending ? "cp-running" : undefined} />{mobile ? null : "Refresh"}
        </button>
      </div>

      {refresh.isError && <div data-testid="sg-refresh-error" role="alert" style={{ fontSize: 13, color: "var(--cp-danger)" }}>The suggestions could not be refreshed just now. The earlier ones are still shown.</div>}
      {feedback.isError && <div data-testid="sg-feedback-error" role="alert" style={{ fontSize: 13, color: "var(--cp-danger)" }}>That could not be saved just now. Try again.</div>}

      {q.isLoading ? (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 12 }} role="status" aria-label="Reading today's cards">
          {[0, 1, 2].map((i) => <span key={i} className="cp-card cp-running" style={{ height: 130 }} />)}
        </div>
      ) : q.isError || !view ? (
        <div data-testid="sg-error" role="alert" className="flex flex-wrap items-center" style={{ gap: 10, fontSize: 13, color: "var(--cp-ink-2)" }}>
          <span>Suggestions are not available just now.</span>
          <button type="button" className="cp-btn" data-testid="sg-retry" onClick={() => void q.refetch()}>Try again</button>
        </div>
      ) : (
        <>
          {view.notices.map((n) => <NoticeBar key={`${n.kind}:${n.source}`} n={n} go={go} />)}
          {view.suggestions.length > 0 ? (
            <div className="grid" data-testid="sg-list" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,260px),1fr))", gap: 12 }}>
              {view.suggestions.map((s) => (
                <SuggestionCard key={s.id} s={s} onAsk={(text) => ask(text)} onFeedback={(action) => feedback.mutate({ id: s.id, action })} />
              ))}
            </div>
          ) : (
            <div data-testid="sg-empty" style={{ fontSize: 13.5, color: "var(--cp-ink-3)" }}>
              Nothing to suggest in {TAB_LABEL[tab]} right now{view.notices.length ? ", for the reason above" : ""}. You can still ask your own question below.
            </div>
          )}
          <span data-testid="sg-asof" className="cp-mono-note">
            Latest market data: {fmtDate(view.window.previous_session)} or today ({fmtDate(view.window.today)}) · Ideas to review, not advice.
          </span>
        </>
      )}
    </section>
  );
}
