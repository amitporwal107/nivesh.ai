/**
 * CopilotReview — the staged Portfolio Health Review, brought from the
 * `/v5/copilot` tour design into the real copilot chat (investor empty-state).
 *
 * Phase 1 ships the two stages that are 100% backed by REAL data:
 *   • ANALYSIS       — score ring (health score) + metric tiles + portfolio
 *                      snapshot + flags, from live hooks. No fabricated numbers:
 *                      any metric without a real source is simply omitted, and
 *                      the mockup's "risk 6.4" is dropped (no real 0–10 score).
 *   • RECOMMENDATION — top actions ranked by ₹ impact, with the exit/retain fund
 *                      names, capital-to-redeploy and annual saving, from
 *                      `useRemediation()` (the SAME compute_remediation builder the
 *                      AI Insights page renders → full parity).
 *
 * INTAKE / OPTIONS / ACTION are labeled "coming" panels — their backends
 * (intake state, scenario simulation, broker order routing) are later phases, so
 * we show what they'll do rather than fake orders/paths.
 *
 * All hooks flow through http() which attaches X-Active-Profile, so when an
 * advisor is viewing a client this renders the CLIENT's live portfolio.
 *
 * Rendered as a scoped `.copilot-tour` dark island (mirrors CopilotWorkflows).
 */
import { useState } from "react";
import { ScoreRing } from "@/pages/Copilot/parts";
import { useHealthAnalysis } from "@/hooks/use-insights";
import { useConcentration, useConcentrationAnalysis, useRemediation } from "@/hooks/use-analytics";
import { usePortfolioSummary, useHoldingsEnriched } from "@/hooks/use-portfolio";
import "@/pages/Copilot/copilot.css";

/* ── defensive local shapes (hooks return loosely-typed / mapped data) ── */
interface Health { health_score?: number; grade?: string; label?: string }
interface Sector { name?: string; pct?: number; capPct?: number; isOverCap?: boolean }
interface OverlapPair { a_name?: string; b_name?: string; overlap_pct?: number }
interface AllocSlice { assetClass?: string; label?: string; pct?: number }
interface EnrichedHolding { name?: string; pnl_pct?: number; pnl_rs?: number }
interface Contributor { name?: string; pct_of_exposure?: number }
interface BeforeAfter { lens_label?: string; before_pct?: number; after_pct?: number }
interface Rec {
  action_kind?: string; title?: string; why?: string; action?: string;
  amount_rs?: number; annual_saving_rs?: number; leverage_score?: number;
  contributors?: Contributor[]; before_after?: BeforeAfter[]; redeploy_to?: string | null;
}

const STAGES = ["INTAKE", "ANALYSIS", "OPTIONS", "RECOMMEND", "ACTION"] as const;
type Stage = (typeof STAGES)[number];
const LIVE: Stage[] = ["ANALYSIS", "RECOMMEND"];

const inr = (n: number) => "₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Math.round(n));
const pct = (n: number) => `${Math.round(n)}%`;
/** Honest qualitative word derived from the real 0–100 health score. */
const healthWord = (s: number) => (s >= 80 ? "healthy" : s >= 60 ? "solid" : s >= 40 ? "mixed" : "under strain");
/** The ₹-impact figure a rec leads with: annual saving if any, else the capital moved. */
function impactOf(r: Rec): string {
  if (r.annual_saving_rs && r.annual_saving_rs > 0) return `${inr(r.annual_saving_rs)} saved/yr`;
  if (r.amount_rs && r.amount_rs > 0) return inr(r.amount_rs);
  return "";
}

const EYEBROW = (t: string, style?: React.CSSProperties) => (
  <div className="nv-eyebrow" style={{ fontSize: 9, ...style }}>{t}</div>
);

function StageStrip({ stage, onPick }: { stage: Stage; onPick: (s: Stage) => void }) {
  const active = STAGES.indexOf(stage);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }} data-testid="review-stagestrip">
      {STAGES.map((s, i) => (
        <div key={s} style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span
            role="button" tabIndex={0}
            data-testid={`stage-${s}`}
            aria-current={i === active ? "step" : undefined}
            onClick={() => onPick(s)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(s); } }}
            className={"ct-step" + (i < active ? " done" : i === active ? " on" : "")}
            style={{ cursor: "pointer" }}
            title={LIVE.includes(s) ? "" : "Coming soon"}
          >
            {s}{!LIVE.includes(s) && <span style={{ marginLeft: 5, opacity: 0.5 }}>·</span>}
          </span>
          {i < STAGES.length - 1 && <span className={"ct-seg" + (i < active ? " done" : "")} />}
        </div>
      ))}
    </div>
  );
}

/** Two-column stage body: main thread + right workspace, wraps on narrow. */
function Body({ main, workspace }: { main: React.ReactNode; workspace: React.ReactNode }) {
  return (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 16 }}>
      <div style={{ flex: "1 1 360px", minWidth: 0, display: "flex", flexDirection: "column", gap: 13 }}>{main}</div>
      <div style={{ flex: "1 1 230px", minWidth: 0, display: "flex", flexDirection: "column", gap: 11,
        borderLeft: "1px solid rgb(var(--line) / 0.10)", paddingLeft: 16 }}>{workspace}</div>
    </div>
  );
}

function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }} aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="nv-card-2" style={{ height: 46, opacity: 0.5 }} />
      ))}
    </div>
  );
}

function ComingPanel({ stage, needs }: { stage: Stage; needs: string }) {
  return (
    <div className="nv-card-2" data-testid="stage-coming" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 8 }}>
      {EYEBROW(`${stage} · COMING`, { color: "var(--amber)" })}
      <div className="nv-serif" style={{ fontSize: 18 }}>Not live yet</div>
      <div className="nv-body" style={{ fontSize: 13, color: "rgb(var(--ink-2))" }}>{needs}</div>
      <div className="nv-mono" style={{ fontSize: 9, color: "rgb(var(--ink-4))", letterSpacing: ".04em", marginTop: 4 }}>
        SHOWN WHEN THE DATA IS REAL — NO PLACEHOLDER NUMBERS.
      </div>
    </div>
  );
}

export default function CopilotReview({ onAsk }: { onAsk: (q: string) => void }) {
  const [stage, setStage] = useState<Stage>("ANALYSIS");

  const healthQ = useHealthAnalysis();
  const concQ = useConcentration();
  const concAnalysisQ = useConcentrationAnalysis();
  const summaryQ = usePortfolioSummary();
  const holdingsQ = useHoldingsEnriched();
  const remQ = useRemediation();

  const health = (healthQ.data as { health?: Health } | undefined)?.health;
  const score = typeof health?.health_score === "number" ? health.health_score : undefined;
  const grade = health?.grade;
  const label = health?.label;

  const sectors = (concQ.data as { sectors?: Sector[] } | undefined)?.sectors;
  const topSector = sectors?.[0];
  const concentrationPct = typeof topSector?.pct === "number" ? topSector.pct : undefined;

  const overlapPairs = (concAnalysisQ.data as { overlap?: { pairs?: OverlapPair[] } } | undefined)?.overlap?.pairs;
  const worstOverlap = overlapPairs?.length
    ? Math.max(...overlapPairs.map((p) => Number(p.overlap_pct ?? 0)))
    : undefined;

  const allocation = (summaryQ.data as { allocation?: AllocSlice[] } | undefined)?.allocation;
  const cashPct = allocation?.find((a) => (a.assetClass || "").toLowerCase() === "cash")?.pct;

  const holdings = (holdingsQ.data as { holdings?: EnrichedHolding[] } | undefined)?.holdings;
  const holdingsCount = holdings?.length;
  const losers = (holdings ?? []).filter((h) => typeof h.pnl_pct === "number" && (h.pnl_pct as number) < 0);

  const recs = ((remQ.data as { recommendations?: Rec[] } | undefined)?.recommendations ?? []) as Rec[];
  const remEmpty = (remQ.data as { empty?: boolean } | undefined)?.empty || recs.length === 0;
  const top3 = recs.slice(0, 3);
  const rebalRec = recs.find((r) => (r.before_after?.length ?? 0) > 0);

  /* ── ANALYSIS ── */
  const metricTiles = [
    grade ? { k: "GRADE", v: String(grade), c: "rgb(var(--ink))", id: "grade" } : null,
    concentrationPct != null ? { k: "CONCENTR.", v: pct(concentrationPct), c: "var(--amber)", id: "concentration" } : null,
    worstOverlap != null ? { k: "MAX OVERLAP", v: pct(worstOverlap), c: "var(--indigo-hex)", id: "overlap" } : null,
    cashPct != null ? { k: "CASH", v: pct(cashPct), c: "rgb(var(--ink))", id: "cash" } : null,
    holdingsCount != null ? { k: "HOLDINGS", v: String(holdingsCount), c: "rgb(var(--ink))", id: "holdings" } : null,
  ].filter(Boolean) as { k: string; v: string; c: string; id: string }[];

  const flags = [
    (topSector?.isOverCap || (concentrationPct != null && concentrationPct >= 25))
      ? { t: topSector?.name ? `${topSector.name.toUpperCase()} ${pct(concentrationPct ?? 0)}` : "CONCENTRATION", cls: "nv-pill-amber" } : null,
    (worstOverlap != null && worstOverlap >= 50) ? { t: `${pct(worstOverlap)} OVERLAP`, cls: "nv-pill-indigo" } : null,
    losers.length ? { t: "UNBOOKED LOSS", cls: "nv-pill-danger" } : null,
  ].filter(Boolean) as { t: string; cls: string }[];

  const analysisLoading = healthQ.isPending && concQ.isPending && summaryQ.isPending;
  const analysisEmpty = !score && !metricTiles.length && !(allocation?.length);

  const analysisMain = analysisLoading ? <Skeleton rows={2} /> : analysisEmpty ? (
    <div className="nv-card-2" style={{ padding: 20 }}>
      <div className="nv-serif" style={{ fontSize: 17 }}>No live portfolio yet</div>
      <div className="nv-body" style={{ fontSize: 13, color: "rgb(var(--ink-2))", marginTop: 4 }}>
        Connect or sync your holdings and I'll score them here.
      </div>
    </div>
  ) : (
    <>
      <div className="nv-card-2" style={{ padding: "11px 13px", display: "flex", flexDirection: "column", gap: 6 }}>
        <div className="nv-mono" style={{ fontSize: 9, color: "var(--mint)" }}>● ANALYZED · LIVE</div>
        {[
          holdingsCount != null ? `✓ FETCHED ${holdingsCount} HOLDINGS · NIDP` : "✓ FETCHED HOLDINGS · NIDP",
          "✓ SCORED HEALTH · CONCENTRATION · OVERLAP",
          "✓ RANKED FIXES BY ₹ IMPACT",
        ].map((s) => (
          <div key={s} className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-2))", letterSpacing: ".04em" }}>{s}</div>
        ))}
      </div>
      {score != null && (
        <div>
          <div className="nv-serif" style={{ fontSize: 19, lineHeight: 1.25 }} data-testid="review-synthesis">
            Your portfolio is <span style={{ color: "var(--mint)" }}>{label || healthWord(score)}</span>
            {topSector?.name && concentrationPct != null && (
              <> — {topSector.name} is <span className="nv-num">{pct(concentrationPct)}</span> of your equity.</>
            )}
          </div>
        </div>
      )}
      <div className="nv-card-2" style={{ padding: 13, display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
        {score != null && <div data-testid="review-health-score"><ScoreRing score={Math.round(score)} size={72} id="review" /></div>}
        {metricTiles.length > 0 && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(78px, 1fr))", gap: 9, flex: 1, minWidth: 160 }}>
            {metricTiles.map((m) => (
              <div key={m.id} data-testid={`metric-${m.id}`}>
                <div className="nv-eyebrow" style={{ fontSize: 8 }}>{m.k}</div>
                <div className="nv-serif nv-num" style={{ fontSize: 17, color: m.c }}>{m.v}</div>
              </div>
            ))}
          </div>
        )}
      </div>
      <button onClick={() => setStage("RECOMMEND")} className="nv-btn nv-btn-primary"
        style={{ alignSelf: "flex-start", padding: "9px 16px", fontSize: 13, cursor: "pointer", border: "none" }}
        data-testid="review-to-recommend">
        See recommendations →
      </button>
    </>
  );

  const analysisWorkspace = (
    <>
      {EYEBROW("PORTFOLIO SNAPSHOT")}
      {allocation?.length ? (
        <div data-testid="review-snapshot" style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {allocation.filter((a) => (a.pct ?? 0) > 0).slice(0, 6).map((a, i) => {
            const c = ["var(--mint)", "var(--amber)", "var(--indigo-hex)", "rgb(var(--ink-3))"][i % 4];
            return (
              <div key={a.assetClass || a.label || i}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "rgb(var(--ink-2))", marginBottom: 4 }}>
                  <span>{a.label || a.assetClass}</span><span className="nv-num">{pct(a.pct ?? 0)}</span>
                </div>
                <div className="ct-bar"><span style={{ width: `${Math.min(100, a.pct ?? 0)}%`, background: c }} /></div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="nv-body" style={{ fontSize: 12, color: "rgb(var(--ink-4))" }}>Allocation unavailable.</div>
      )}
      {flags.length > 0 && (
        <>
          {EYEBROW("FLAGS", { marginTop: 4 })}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }} data-testid="review-flags">
            {flags.map((f) => (<span key={f.t} className={`nv-pill ${f.cls}`} style={{ fontSize: 9 }}>{f.t}</span>))}
          </div>
        </>
      )}
    </>
  );

  /* ── RECOMMEND ── */
  const recommendMain = remQ.isPending ? <Skeleton rows={3} /> : remEmpty ? (
    <div className="nv-card-2" style={{ padding: 20 }}>
      <div className="nv-serif" style={{ fontSize: 17 }}>Nothing urgent to fix</div>
      <div className="nv-body" style={{ fontSize: 13, color: "rgb(var(--ink-2))", marginTop: 4 }}>
        No high-impact actions surfaced on your holdings right now.
      </div>
    </div>
  ) : (
    <>
      <div className="nv-serif" style={{ fontSize: 19, lineHeight: 1.25 }} data-testid="review-recommend-synthesis">
        Start with <span style={{ color: "var(--mint)" }}>{top3[0]?.title}</span> — the biggest lever on your portfolio right now.
      </div>
      <div>
        {EYEBROW("TOP ACTIONS · RANKED BY ₹ IMPACT", { marginBottom: 8 })}
        {top3.map((r, i) => {
          const cta = i === 0;
          const impact = impactOf(r);
          return (
            <div key={i} data-testid={`rec-row-${i}`}
              style={{ padding: "11px 13px", borderRadius: 10, marginBottom: 8,
                border: cta ? "1px solid rgb(var(--pos) / 0.28)" : "1px solid rgb(var(--line) / 0.08)",
                background: cta ? "var(--mint-soft)" : "var(--bg-2)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                <span className="nv-mono" style={{ fontSize: 11, color: "var(--mint)" }}>{String(i + 1).padStart(2, "0")}</span>
                <span style={{ flex: 1, minWidth: 0, fontSize: 13, color: "rgb(var(--ink))" }}>{r.title}</span>
                {impact && <span className="nv-serif nv-num" style={{ fontSize: 14, color: "var(--mint)", whiteSpace: "nowrap" }}>{impact}</span>}
                {cta ? (
                  <button onClick={() => onAsk(r.title || "What should I fix first?")} className="nv-btn nv-btn-primary"
                    data-testid="rec-cta" style={{ padding: "5px 11px", fontSize: 11, cursor: "pointer", border: "none" }}>Do it ↓</button>
                ) : (
                  <span className="nv-mono" style={{ fontSize: 10, color: "rgb(var(--ink-3))" }}>QUEUE</span>
                )}
              </div>
              {r.action && (
                <div className="nv-body" style={{ fontSize: 12, color: "rgb(var(--ink-2))", marginTop: 6, paddingLeft: 22 }}>{r.action}</div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );

  const recommendWorkspace = (
    <>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        {EYEBROW("WORKSPACE · PLAN")}<span className="nv-mono" style={{ fontSize: 9, color: "var(--mint)" }}>● LIVE</span>
      </div>
      {rebalRec?.before_after?.length ? (
        <>
          <div className="nv-serif" style={{ fontSize: 15 }}>{rebalRec.title}</div>
          {EYEBROW("ALLOCATION · NOW → TARGET", { fontSize: 8 })}
          {rebalRec.before_after.slice(0, 4).map((ba, i) => {
            const before = Number(ba.before_pct ?? 0), after = Number(ba.after_pct ?? 0);
            const c = ["var(--amber)", "var(--mint)", "var(--indigo-hex)"][i % 3];
            return (
              <div key={ba.lens_label || i}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "rgb(var(--ink-2))", marginBottom: 4 }}>
                  <span>{ba.lens_label || "Allocation"}</span><span className="nv-num">{pct(before)} → {pct(after)}</span>
                </div>
                <div className="ct-bar"><span style={{ width: `${Math.min(100, after)}%`, background: c }} /></div>
              </div>
            );
          })}
        </>
      ) : top3[0]?.contributors?.length ? (
        <>
          <div className="nv-serif" style={{ fontSize: 15 }}>What's driving it</div>
          {top3[0].contributors!.slice(0, 4).map((cbt, i) => (
            <div key={cbt.name || i} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "rgb(var(--ink-2))" }}>
              <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginRight: 8 }}>{cbt.name}</span>
              <span className="nv-num">{pct(Number(cbt.pct_of_exposure ?? 0))}</span>
            </div>
          ))}
        </>
      ) : (
        <div className="nv-body" style={{ fontSize: 12, color: "rgb(var(--ink-4))" }}>Plan detail appears as actions are chosen.</div>
      )}
      {!remEmpty && (
        <div style={{ marginTop: "auto" }}>
          <button onClick={() => onAsk("Review and apply these recommendations on my portfolio")} className="nv-btn nv-btn-primary"
            style={{ width: "100%", justifyContent: "center", padding: 9, fontSize: 12, cursor: "pointer", border: "none" }}>
            Review &amp; apply →
          </button>
        </div>
      )}
    </>
  );

  /* ── stage router ── */
  let body: React.ReactNode;
  if (stage === "ANALYSIS") body = <Body main={analysisMain} workspace={analysisWorkspace} />;
  else if (stage === "RECOMMEND") body = <Body main={recommendMain} workspace={recommendWorkspace} />;
  else if (stage === "INTAKE") body = <ComingPanel stage="INTAKE" needs="Guided goal & risk intake (tappable chips, 'what I know so far') lands next — for now the review starts from your synced holdings." />;
  else if (stage === "OPTIONS") body = <ComingPanel stage="OPTIONS" needs="Side-by-side paths (trim / harvest / consolidate) with a scenario simulation of each path's ₹ impact and risk delta. Needs the simulation engine." />;
  else body = <ComingPanel stage="ACTION" needs="Exact SELL/BUY order preview with est. cost, tax and broker routing — behind explicit consent. Needs order construction + broker execution." />;

  return (
    <div
      className="copilot-tour"
      data-testid="copilot-review"
      data-role="investor"
      style={{ minHeight: 0, borderRadius: 18, border: "1px solid var(--line-2)", padding: "clamp(16px,3vw,24px)", marginTop: 24, overflowX: "clip" }}
    >
      {/* top bar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span className="nv-serif" style={{ fontSize: 18 }}>Portfolio health review</span>
          <span className="nv-pill nv-pill-mint" style={{ fontSize: 9 }}><span className="nv-dot" style={{ background: "var(--mint)" }} />NIDP CONNECTED</span>
          {holdingsCount != null && (
            <span className="nv-mono" style={{ fontSize: 9, color: "rgb(var(--ink-3))", letterSpacing: ".06em" }}>{holdingsCount} HOLDINGS</span>
          )}
        </div>
        <button onClick={() => onAsk("I'd like to talk to a human advisor")} className="nv-btn"
          style={{ padding: "6px 12px", fontSize: 12, cursor: "pointer", borderColor: "rgb(var(--warm) / 0.30)", color: "var(--amber)" }}>
          Talk to an advisor ▸
        </button>
      </div>

      <hr className="nv-hr" style={{ margin: "16px 0" }} />

      <StageStrip stage={stage} onPick={setStage} />
      {body}
    </div>
  );
}
