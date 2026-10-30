/**
 * Home — greeting, live market strip, the statement bar, "for your portfolio
 * today" cards and starter questions. Design: Nivesh Copilot.dc.html, the
 * `isHome` block.
 *
 * It shows the same facts the existing dashboard (/dashboard) shows, from the
 * same endpoints:
 *   market strip        GET /api/markets/home                (useMarketsHome)
 *   statement bar       GET /api/onboarding/state            (useCasState)
 *   health card         GET /api/insights/analysis           (useHealthAnalysis)
 *   plan card           GET /api/plans/active                (useActivePlan)
 *   signal cards        GET /api/insights                    (useInsightsList)
 *   drift card          equity share vs the risk profile's target, derived
 *                       exactly as the dashboard's intelligence feed does
 *   ranked prompts      GET /api/copilot/suggested-prompts   (useCopilotPrompts)
 *   portfolio facts     GET /api/portfolio/holdings-enriched (usePortfolioContext)
 * Nothing is shown for a source that returned nothing.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useActivePlan } from "@/hooks/use-active-plan";
import { useHealthAnalysis, useInsightsList } from "@/hooks/use-insights";
import { useMarketsHome } from "@/hooks/use-markets";
import { targetAllocationFor, useRiskProfile } from "@/hooks/use-risk-profile";
import { GmailSyncModal } from "@/pages/Dashboard/GmailSyncModal";
import { StockIcon } from "../components/EntityIcon";
import { fmtNum, fmtPct, humaniseTag, signTone, TONE_COLOR, type Tone } from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { useCasState } from "../lib/use-cas-state";
import { useCopilotPrompts, type CopilotPrompt } from "../lib/use-copilot-prompts";
import { usePortfolioContext } from "../lib/use-portfolio-context";
import type { Mode } from "../lib/views";
import { StatementImport } from "./StatementImport";

/** Starter questions used only when the backend has no ranked prompts for the
 *  user. Plain questions — no figures. */
const STARTERS: Record<Mode, string[]> = {
  investor: [
    "How is my portfolio doing against the Nifty 50?",
    "Which of my funds overlap the most?",
    "Is my portfolio too concentrated?",
    "What should I review first in my portfolio?",
    "Which sectors are leading the market this month?",
    "Explain large-cap, flexi-cap and mid-cap funds",
  ],
  trader: [
    "Which sectors are leading the market this month?",
    "Screen for stocks near their 52-week high with rising volume",
    "What are FIIs and DIIs doing this week?",
    "Backtest a 20-day breakout on Nifty 500 stocks",
    "Which stocks reported results this week?",
    "Explain how position sizing with 1% risk works",
  ],
  advisor: [
    "Which clients are off their target allocation?",
    "Which clients have missed SIP instalments?",
    "Which clients are most concentrated in one holding?",
    "Who should I review first this week?",
    "Which funds are underperforming their benchmark across my book?",
    "Which sectors are leading the market this month?",
  ],
};

const CATEGORY_TONE: Record<string, Tone> = {
  portfolio_health: "mint",
  risk_diversification: "amber",
  tax: "indigo",
  performance: "mint",
  goals: "indigo",
};

/** Same bands as the existing dashboard headline (pages/Dashboard/Dashboard.tsx, healthLabel). */
function healthPhrase(score: number): { phrase: string; tone: Tone } {
  if (score >= 85) return { phrase: "in great shape", tone: "mint" };
  if (score >= 70) return { phrase: "mostly healthy", tone: "mint" };
  if (score >= 55) return { phrase: "in need of some work", tone: "amber" };
  return { phrase: "in need of attention", tone: "danger" };
}

function MarketStrip() {
  const m = useMarketsHome();
  if (!m.data) return null;
  const d = m.data;
  const items: Array<{ k: string; v: string; tone: Tone }> = [];
  const nifty = d.indices.find((i) => /nifty\s*50\b/i.test(i.name) && !i.is_vix);
  if (nifty?.value != null) {
    items.push({ k: "NIFTY 50", v: `${fmtNum(nifty.value, 0)}${nifty.change_pct != null ? ` ${fmtPct(nifty.change_pct, { signed: true, digits: 2 })}` : ""}`, tone: signTone(nifty.change_pct) });
  }
  const adv = d.breadth.advances, dec = d.breadth.declines;
  if (adv != null && dec != null && adv + dec > 0) {
    items.push({ k: "BREADTH", v: `${Math.round((adv / (adv + dec)) * 100)}% ADVANCING`, tone: "ink" });
  }
  const vix = d.indices.find((i) => i.is_vix);
  if (vix?.value != null) {
    items.push({ k: "INDIA VIX", v: `${fmtNum(vix.value, 2)}${vix.change_pct != null ? ` ${fmtPct(vix.change_pct, { signed: true })}` : ""}`, tone: "amber" });
  }
  const cr = (n: number) => `${n < 0 ? "−" : "+"}₹${fmtNum(Math.abs(n), 0)} CR`;
  if (d.fii_dii?.fii_net_cr != null) items.push({ k: "FII CASH", v: cr(d.fii_dii.fii_net_cr), tone: signTone(d.fii_dii.fii_net_cr) });
  if (d.fii_dii?.dii_net_cr != null) items.push({ k: "DII CASH", v: cr(d.fii_dii.dii_net_cr), tone: signTone(d.fii_dii.dii_net_cr) });
  if (!items.length) return null;
  return (
    <div data-testid="home-market-strip" className="flex flex-wrap" style={{ gap: "6px 18px", fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.04em", color: "var(--cp-ink-3)", paddingTop: 4 }}>
      {items.map((it) => (
        <span key={it.k}>{it.k} <span className="cp-num" style={{ color: it.tone === "ink" ? "var(--cp-ink-2)" : TONE_COLOR[it.tone] }}>{it.v}</span></span>
      ))}
    </div>
  );
}

/**
 * The statement the portfolio was read from, with the two ways to bring in a
 * newer one — the same bar and the same actions as the existing dashboard
 * (CasStatementBanner there). "Sync Gmail" opens the existing import flow,
 * which fetches the latest eCAS and replaces the holdings with it.
 */
function StatementBar() {
  const { go } = useCopilotShell();
  const qc = useQueryClient();
  const cas = useCasState();
  const [syncOpen, setSyncOpen] = useState(false);
  if (!cas.data?.period) return null;

  const refreshAfterImport = () => {
    // What the dashboard refreshes after an import, plus this shell's own reads.
    for (const queryKey of [["onboarding", "state"], ["portfolio"], ["plans"], ["insights"], ["copilot"]]) {
      void qc.invalidateQueries({ queryKey });
    }
  };
  const link = { background: "none", border: 0, padding: 0, cursor: "pointer", fontFamily: "var(--sans)", fontSize: 12 } as const;

  return (
    <>
      <GmailSyncModal
        open={syncOpen}
        onClose={() => setSyncOpen(false)}
        gmailConnected={cas.data.gmailConnected}
        panOnFile={cas.data.panOnFile}
        onImported={refreshAfterImport}
      />
      <div data-testid="home-statement-bar" className="cp-card flex flex-wrap items-center" style={{ gap: "6px 12px", padding: "10px 16px", fontSize: 12.5, color: "var(--cp-ink-2)", marginTop: 8 }}>
        <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>Last CAS</span>
        <span data-testid="home-statement-period" style={{ fontWeight: 500, color: "var(--cp-ink)" }}>{cas.data.period}</span>
        <span style={{ color: "var(--cp-ink-3)" }}>· Update if you have a newer statement</span>
        <span className="flex items-center" style={{ gap: 10, marginLeft: "auto" }}>
          <button type="button" data-testid="home-statement-sync" onClick={() => setSyncOpen(true)} style={{ ...link, color: "var(--mint)", fontWeight: 500 }}>
            {cas.data.gmailConnected ? "Sync Gmail" : "Connect Gmail"}
          </button>
          <span aria-hidden style={{ color: "var(--cp-ink-4)" }}>·</span>
          <button type="button" data-testid="home-statement-upload" onClick={() => go("page/brokers")} style={{ ...link, color: "var(--cp-ink-2)" }}>Upload file</button>
        </span>
        <StatementImport gmailConnected={cas.data.gmailConnected} onImported={refreshAfterImport} />
      </div>
    </>
  );
}

interface Card {
  key: string;
  tag: string;
  tone: Tone;
  title: string;
  fact?: string;
  second?: { k: string; v: string };
  /** The company the card is about, when it is about one: its icon sits in the card's top line. */
  symbol?: string;
  cta: string;
  onOpen: () => void;
}

function TodayCard({ tag, tone, title, fact, second, symbol, cta, onOpen }: Omit<Card, "key">) {
  const row = (k: string, v: string, quiet: boolean) => (
    <div className="grid" style={{ gridTemplateColumns: "62px minmax(0,1fr)", gap: 8 }}>
      <span style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-ink-4)", paddingTop: 3 }}>{k}</span>
      <span style={{ color: quiet ? "var(--cp-ink-3)" : "var(--cp-ink-2)" }}>{v}</span>
    </div>
  );
  return (
    <button
      type="button"
      data-testid="home-today-card"
      onClick={onOpen}
      className="cp-card-raised flex flex-col"
      style={{ gap: 12, padding: 18, cursor: "pointer", textAlign: "left", color: "inherit", fontFamily: "var(--sans)" }}
    >
      <span className="flex items-center" style={{ gap: 8, fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", color: "var(--cp-ink-3)", textTransform: "uppercase" }}>
        <span className="nv-dot" style={{ background: TONE_COLOR[tone] }} />{tag}
        {symbol && <span style={{ marginLeft: "auto" }}><StockIcon symbol={symbol} size={22} /></span>}
      </span>
      <span className="cp-pretty" style={{ fontFamily: "var(--display)", fontSize: 21, lineHeight: 1.2, letterSpacing: "-0.015em" }}>{title}</span>
      {(fact || second) && (
        <span className="flex flex-col" style={{ gap: 6, fontSize: 13, lineHeight: 1.5 }}>
          {fact && row("FACT", fact, false)}
          {second && row(second.k, second.v, true)}
        </span>
      )}
      <span style={{ marginTop: "auto", fontSize: 13, color: "var(--cp-ink)" }}>{cta} ›</span>
    </button>
  );
}

/**
 * Cards about the user's own portfolio, from the dashboard's sources.
 * `settling` is true while any of those sources is still being read.
 */
function usePortfolioCards(enabled: boolean): { cards: Card[]; settling: boolean } {
  const { ask, go } = useCopilotShell();
  const health = useHealthAnalysis();
  const plan = useActivePlan();
  const signals = useInsightsList();
  const risk = useRiskProfile();
  const pf = usePortfolioContext();
  if (!enabled) return { cards: [], settling: false };
  const cards: Card[] = [];

  const h = health.data?.health;
  const score = typeof h?.health_score === "number" ? h.health_score : typeof h?.score === "number" ? h.score : null;
  if (score != null && score > 0) {
    const { phrase, tone } = healthPhrase(score);
    cards.push({
      key: "health",
      tag: "Portfolio health",
      tone,
      title: `Your portfolio is ${phrase}`,
      fact: `Health score ${fmtNum(score, 0)} of 100${h?.grade ? ` · grade ${h.grade}` : ""}`,
      cta: "Open portfolio analysis",
      onOpen: () => go("tool/analysis"),
    });
  }

  const actions = plan.data?.actions ?? [];
  const pending = plan.data?.actions_pending ?? actions.filter((a) => String(a.status ?? "").toLowerCase() === "pending").length;
  if (pending > 0) {
    cards.push({
      key: "plan",
      tag: "Action plan",
      tone: "amber",
      title: `${fmtNum(pending)} ${pending === 1 ? "action" : "actions"} identified`,
      fact: typeof plan.data?.plan_summary === "string" ? plan.data.plan_summary : undefined,
      cta: "See the recommendations",
      onOpen: () => go("tool/recommend"),
    });
  }

  // Allocation drift — the dashboard's synthetic signal (Dashboard.tsx
  // allocationDrift + IntelligenceFeed.tsx): actual equity share against the
  // target for the user's risk category.
  const target = risk.data?.category ? targetAllocationFor(risk.data.category) : null;
  const equity = pf.allocation.find((a) => a.key.toLowerCase() === "equity");
  if (target && equity) {
    cards.push({
      key: "drift",
      tag: Math.abs(equity.pct - target.equity) > 15 ? "Watch" : "Signal",
      tone: "amber",
      title: `Portfolio drift: equity ${equity.pct.toFixed(0)}% vs target ${target.equity}%`,
      fact: "Rebalance to align with your risk profile target allocation.",
      cta: "Ask Nivesh",
      onOpen: () => ask(`My equity allocation is ${equity.pct.toFixed(0)}% against a target of ${target.equity}% for my risk profile. How should I rebalance?`),
    });
  }

  for (const s of (signals.data?.insights ?? []).slice(0, 2)) {
    cards.push({
      key: `signal:${s.id}`,
      tag: s.severity === "fix" ? "Fix" : s.severity === "watch" ? "Watch" : humaniseTag(s.category) || "Signal",
      tone: s.severity === "fix" ? "danger" : "amber",
      title: s.title,
      fact: s.detail || undefined,
      cta: "Ask Nivesh",
      onOpen: () => ask(`${s.title}. What does this mean for my portfolio, and what should I do about it?`),
    });
  }
  return { cards, settling: health.isLoading || plan.isLoading || signals.isLoading || risk.isLoading };
}

export default function Home() {
  const { ask, go, mobile, mode, firstName } = useCopilotShell();
  const markets = useMarketsHome();
  const prompts = useCopilotPrompts();
  const pf = usePortfolioContext();

  const noPf = pf.status === "empty";
  const hasPf = pf.status === "ready" || pf.status === "statement";
  const today = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });
  const marketState = markets.data ? (markets.data.market_state === "open" ? "Market open" : "Market closed") : null;

  // At an advisor root the backend ranks prompts for the client book. They
  // belong on this screen only in Advisor mode; in Investor or Trader mode the
  // screen is about the user's own portfolio, as /dashboard is.
  const forBook = prompts.data?.audience === "advisor";
  const bookView = forBook && mode === "advisor";
  const ranked: CopilotPrompt[] = forBook && !bookView ? [] : prompts.data?.prompts ?? [];
  const portfolio = usePortfolioCards(hasPf && !bookView);
  const portfolioCards = portfolio.cards;
  // The cards come from several requests that finish at different times. They
  // are shown together once all have answered, so a card never moves from
  // under the pointer as another one arrives above it.
  const settling = pf.status === "loading" || portfolio.settling || prompts.isPending;

  const promptCard = (c: CopilotPrompt): Card => ({
    key: `prompt:${c.id}`,
    tag: humaniseTag(c.category) || "For you",
    tone: CATEGORY_TONE[c.category ?? ""] ?? "mint",
    title: c.label,
    fact: c.badge,
    second: c.outcome ? { k: "OUTCOME", v: c.outcome } : undefined,
    cta: "Ask Nivesh",
    onOpen: () => ask(c.query),
  });
  // Cards carry a figure the backend computed for this user; the rest are questions.
  // A figure about the user's own money needs a portfolio: without one it is never
  // shown as a fact (the client book's prompts are about the clients' portfolios).
  const withFact = hasPf || bookView ? ranked.filter((p) => p.badge) : [];
  const promptCards = (withFact.length ? withFact : bookView ? ranked : []).map(promptCard);
  // Two rows at most: the portfolio's own signals first, then ranked prompts.
  const cards = [...portfolioCards, ...promptCards].slice(0, 6);
  const usedPrompts = new Set(cards.map((c) => c.key));
  const rest = ranked.filter((p) => !usedPrompts.has(`prompt:${p.id}`)).slice(0, 6);
  const news = (markets.data?.news ?? []).slice(0, 3);
  const showNews = !settling && cards.length === 0 && news.length > 0;

  const sub = pf.status === "ready"
    ? `Ask in plain English. Nivesh picks the tools, runs the numbers on your ${pf.holdingsCount} holdings and shows you the evidence behind every answer.`
    : noPf
      ? "Ask in plain English. Nivesh picks the tools and shows the evidence behind every answer. Connect a portfolio to make answers about your money."
      : "Ask in plain English. Nivesh picks the tools and shows you the evidence behind every answer.";

  return (
    <div data-testid="copilot-home" className="mx-auto flex flex-col" style={{ maxWidth: 840, padding: `${mobile ? 28 : 80}px 0 40px`, gap: 44 }}>
      <div className="flex flex-col" style={{ gap: 14 }}>
        <span className="cp-eyebrow" data-testid="home-eyebrow">{today}{marketState ? ` · ${marketState}` : ""}</span>
        <h1 className="cp-display m-0" data-testid="home-headline" style={{ fontSize: mobile ? 40 : 60 }}>
          What would you like to <em>know</em>{firstName ? `, ${firstName}` : ""}?
        </h1>
        <p className="m-0 cp-pretty" style={{ fontSize: 16, lineHeight: 1.6, color: "var(--cp-ink-2)", maxWidth: 600 }}>{sub}</p>
        <MarketStrip />
        <StatementBar />
        {noPf && (
          <div data-testid="home-connect-banner" className="flex flex-wrap items-center justify-between" style={{ gap: 12, padding: "16px 18px", borderRadius: 14, border: "1px solid var(--mint-line)", background: "var(--mint-soft)", marginTop: 8 }}>
            <div className="flex flex-col" style={{ gap: 4, flex: "1 1 260px" }}>
              <span style={{ fontSize: 15, fontWeight: 500 }}>Connect a portfolio and every answer is about your money.</span>
              <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>Import your holdings once. Research questions work either way.</span>
            </div>
            <button type="button" className="cp-btn" data-variant="primary" onClick={() => go("onboarding")}>Connect</button>
          </div>
        )}
      </div>

      {(cards.length > 0 || showNews || settling) && (
        <section className="flex flex-col" style={{ gap: 12 }}>
          <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 12px" }}>
            <span className="cp-eyebrow" data-testid="home-today-title" style={{ whiteSpace: "nowrap" }}>
              {showNews || (noPf && !bookView) ? "Worth knowing today" : bookView ? "For your client book today" : "For your portfolio today"}
            </span>
            {!settling && cards.length > 0 && <span className="cp-mono-note">{bookView ? "Ranked for your client book" : "From your holdings"}</span>}
            {showNews && <span className="cp-mono-note">From today’s filings and news</span>}
          </div>
          {settling ? (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 12 }} role="status" aria-label="Loading suggestions">
              {[0, 1, 2].map((i) => <span key={i} className="cp-card cp-running" style={{ height: 150 }} />)}
            </div>
          ) : (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 12 }}>
              {cards.map(({ key, ...c }) => <TodayCard key={key} {...c} />)}
              {showNews && news.map((n) => (
                <TodayCard
                  key={n.title}
                  tag={humaniseTag(n.category) || "News"}
                  tone={n.sentiment === "negative" ? "danger" : n.sentiment === "positive" ? "mint" : "amber"}
                  title={n.title}
                  fact={[n.symbol, n.when].filter(Boolean).join(" · ") || undefined}
                  symbol={n.symbol || undefined}
                  cta="Ask what it means"
                  onOpen={() => ask(`What does this mean for investors: "${n.title}"${n.symbol ? ` (${n.symbol})` : ""}?`)}
                />
              ))}
            </div>
          )}
        </section>
      )}

      <section className="flex flex-col" style={{ gap: 10 }}>
        <span className="cp-eyebrow">Try asking</span>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,280px),1fr))", columnGap: 28 }}>
          {(rest.length ? rest.map((p) => ({ key: p.id, tag: humaniseTag(p.category), text: p.label, query: p.query }))
            : STARTERS[mode].map((t) => ({ key: t, tag: "", text: t, query: t }))
          ).map((s) => (
            <button
              key={s.key}
              type="button"
              data-testid="home-try"
              onClick={() => ask(s.query)}
              className="flex flex-col"
              style={{ gap: 4, padding: "14px 2px", border: 0, borderBottom: "1px solid var(--cp-line)", background: "none", cursor: "pointer", color: "var(--cp-ink-2)", textAlign: "left", fontFamily: "var(--sans)" }}
            >
              {s.tag && <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.12em", color: "var(--cp-ink-3)", textTransform: "uppercase" }}>{s.tag}</span>}
              <span style={{ fontSize: 15, lineHeight: 1.45 }}>{s.text}</span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
