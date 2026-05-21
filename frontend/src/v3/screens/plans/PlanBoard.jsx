import React, { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { AlertTriangle, RefreshCw, ChevronDown, ChevronRight, Check, X, Sparkles, Trash2 } from "lucide-react";
import HeroCard from "../../components/HeroCard";
import CompactCard from "../../components/CompactCard";
import CategoryChip from "../../components/CategoryChip";
import TinyChip from "../../components/TinyChip";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { usePlans, generatePlan, clearActive, updateActionStatus } from "../../adapters/plans";
import { inrCompact } from "../../lib/format";

const ACTION_COLOR = {
  EXIT:     { bg: "var(--v3-crimson-soft)", color: "var(--v3-crimson)" },
  SELL:     { bg: "var(--v3-crimson-soft)", color: "var(--v3-crimson)" },
  REDUCE:   { bg: "#D4AF3726",              color: "var(--v3-gold)" },
  BUY:      { bg: "var(--v3-moss-soft)",    color: "var(--v3-moss)" },
  INCREASE: { bg: "var(--v3-moss-soft)",    color: "var(--v3-moss)" },
  SWITCH:   { bg: "var(--v3-indigo-soft)",  color: "var(--v3-indigo)" },
  HOLD:     { bg: "var(--v3-bg-3)",         color: "var(--v3-ink-3)" },
};

function ActionPill({ verb }) {
  const cfg = ACTION_COLOR[verb] || ACTION_COLOR.HOLD;
  return (
    <span style={{ padding: "3px 8px", borderRadius: 999, background: cfg.bg, color: cfg.color, fontSize: 10, fontFamily: "var(--v3-font-mono)", fontWeight: 600 }}>
      {verb}
    </span>
  );
}

function StatusBadge({ status }) {
  if (!status || status === "PENDING") return <span style={{ color: "var(--v3-ink-4)", fontSize: 11 }}>Pending</span>;
  if (status === "COMPLETED") return <span style={{ color: "var(--v3-moss)", fontSize: 11, display: "inline-flex", alignItems: "center", gap: 3 }}><Check size={12} /> Done</span>;
  if (status === "SKIPPED") return <span style={{ color: "var(--v3-ink-3)", fontSize: 11 }}>Skipped</span>;
  return null;
}

function ActionRow({ action, planId, onUpdated }) {
  const [updating, setUpdating] = useState(false);
  async function mark(status) {
    setUpdating(true);
    await updateActionStatus(planId, action.id || action.action_id, status);
    setUpdating(false);
    onUpdated();
  }
  const verb = action.verb || action.action_type || "HOLD";
  const fundName = action.fund_name || action.scheme_name || action.security_name || "—";
  const amount = action.amount || action.value || action.amount_rs;
  const taxImpact = action.tax_impact || action.tax_cost;
  const status = action.status || "PENDING";
  const isDone = status === "COMPLETED" || status === "SKIPPED";
  return (
    <div style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 10, padding: "11px 14px", display: "flex", alignItems: "center", gap: 12, opacity: isDone ? 0.5 : 1 }}>
      <ActionPill verb={verb} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: "var(--v3-ink-1)", lineHeight: 1.3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{fundName}</div>
        <div style={{ display: "flex", gap: 8, marginTop: 3, fontSize: 10, color: "var(--v3-ink-4)" }}>
          {amount != null && <span>{inrCompact(amount)}</span>}
          {taxImpact != null && taxImpact > 0 && <span>· Tax {inrCompact(taxImpact)}</span>}
        </div>
      </div>
      <StatusBadge status={status} />
      {!isDone && (
        <div style={{ display: "flex", gap: 4 }}>
          <button onClick={() => mark("COMPLETED")} disabled={updating} title="Mark done" style={{ background: "var(--v3-moss-soft)", border: "1px solid var(--v3-moss)", borderRadius: 6, padding: 4, cursor: updating ? "not-allowed" : "pointer", color: "var(--v3-moss)", display: "grid", placeItems: "center" }}>
            <Check size={12} />
          </button>
          <button onClick={() => mark("SKIPPED")} disabled={updating} title="Skip" style={{ background: "var(--v3-bg-3)", border: "1px solid var(--v3-line)", borderRadius: 6, padding: 4, cursor: updating ? "not-allowed" : "pointer", color: "var(--v3-ink-3)", display: "grid", placeItems: "center" }}>
            <X size={12} />
          </button>
        </div>
      )}
    </div>
  );
}

function RuleGroup({ ruleName, ruleNumber, actions, planId, onUpdated, defaultExpanded = true }) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const totalAmount = actions.reduce((s, a) => s + (a.amount || a.value || a.amount_rs || 0), 0);
  return (
    <div style={{ marginBottom: 12 }}>
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{ width: "100%", textAlign: "left", background: "var(--v3-bg-3)", border: "1px solid var(--v3-line)", borderRadius: 10, padding: "10px 14px", display: "flex", alignItems: "center", gap: 10, cursor: "pointer", marginBottom: 6 }}
      >
        {expanded ? <ChevronDown size={14} color="var(--v3-ink-3)" /> : <ChevronRight size={14} color="var(--v3-ink-3)" />}
        <span className="v3-eyebrow" style={{ fontSize: 10, color: "var(--v3-ink-3)" }}>{ruleNumber ? `RULE ${ruleNumber}` : "RULE"}</span>
        <span style={{ flex: 1, fontSize: 13, color: "var(--v3-ink-1)" }}>{ruleName}</span>
        <span className="v3-data" style={{ fontSize: 11, color: "var(--v3-ink-3)" }}>{actions.length} actions · {inrCompact(totalAmount)}</span>
      </button>
      {expanded && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingLeft: 12 }}>
          {actions.map((a, i) => <ActionRow key={i} action={a} planId={planId} onUpdated={onUpdated} />)}
        </div>
      )}
    </div>
  );
}

function ErrorState({ onRetry }) {
  return (
    <div style={{ textAlign: "center", padding: "60px 24px", display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
      <AlertTriangle size={28} color="var(--v3-ink-4)" />
      <p style={{ color: "var(--v3-ink-3)", fontSize: 14, margin: 0 }}>Couldn't load plans</p>
      <button onClick={onRetry} style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 16px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 999, fontSize: 13, color: "var(--v3-ink-2)", cursor: "pointer" }}>
        <RefreshCw size={13} /> Retry
      </button>
    </div>
  );
}

const FILTERS = [
  { id: "all", label: "All" },
  { id: "pending", label: "Pending" },
  { id: "done", label: "Done" },
];

export default function PlanBoard() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const [filter, setFilter] = useState("all");
  const [generating, setGenerating] = useState(false);
  const { data, loading, error, refetch } = usePlans();
  const active = data?.active;
  const projection = data?.projection;
  const actions = active?.actions || [];

  const filteredActions = actions.filter((a) => {
    if (filter === "pending") return !a.status || a.status === "PENDING";
    if (filter === "done") return a.status === "COMPLETED" || a.status === "SKIPPED";
    return true;
  });

  const grouped = filteredActions.reduce((acc, a) => {
    const key = a.rule_id || a.rule_number || a.rule_name || "Other";
    if (!acc[key]) acc[key] = { name: a.rule_name || key, number: a.rule_number || a.rule_id, items: [] };
    acc[key].items.push(a);
    return acc;
  }, {});

  const completedCount = actions.filter((a) => a.status === "COMPLETED").length;

  async function handleGenerate() {
    setGenerating(true);
    const res = await generatePlan();
    setGenerating(false);
    if (!res.error) { window.dispatchEvent(new CustomEvent("nivesh:plan-saved")); refetch(); }
  }
  async function handleClear() {
    if (!window.confirm("Clear the active plan? You can generate a fresh one later.")) return;
    await clearActive();
    refetch();
  }

  const healthCurrent = projection?.current_score ?? active?.portfolio_score ?? null;
  const healthProjected = projection?.projected_score ?? null;
  const lift = healthCurrent != null && healthProjected != null ? healthProjected - healthCurrent : null;

  const heroTitle = loading
    ? "Loading your action plan…"
    : !active
    ? "Generate your first action plan"
    : `${actions.length} actions${active.gross_shift ? ` · ${inrCompact(active.gross_shift)} gross shift` : ""}`;

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Plan · Action Board" title="Plan Board" />
      {error && !loading ? (
        <ErrorState onRetry={refetch} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 80 }}>
          <HeroCard
            layout={isDesktop ? "desktop" : "mobile"}
            category="health"
            priorityLabel={loading ? "Loading…" : active ? `Active plan${active.created_at ? ` · ${new Date(active.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}` : ""}` : "No active plan"}
            title={heroTitle}
            description={isDesktop && active?.confidence ? `Confidence: ${String(active.confidence).toUpperCase()} · ${active.summary || ""}` : null}
            viz={
              loading ? (
                <div style={{ width: "100%", height: 100, background: "var(--v3-bg-3)", borderRadius: 10 }} />
              ) : healthCurrent != null ? (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 18 }}>
                  <div style={{ textAlign: "center" }}>
                    <p className="v3-eyebrow" style={{ fontSize: 9, color: "var(--v3-ink-4)", margin: "0 0 4px" }}>CURRENT</p>
                    <span style={{ fontFamily: "var(--v3-font-display)", fontSize: isDesktop ? 44 : 36, fontWeight: 600, color: "var(--v3-ink-2)", lineHeight: 1 }}>
                      {healthCurrent}
                    </span>
                  </div>
                  {healthProjected != null && (
                    <>
                      <span style={{ color: "var(--v3-saffron)", fontSize: 16 }}>→</span>
                      <div style={{ textAlign: "center" }}>
                        <p className="v3-eyebrow" style={{ fontSize: 9, color: "var(--v3-ink-4)", margin: "0 0 4px" }}>PROJECTED</p>
                        <span style={{ fontFamily: "var(--v3-font-display)", fontSize: isDesktop ? 44 : 36, fontWeight: 600, color: "var(--v3-moss)", lineHeight: 1 }}>
                          {healthProjected}
                        </span>
                        {lift != null && lift !== 0 && (
                          <p style={{ fontSize: 10, color: "var(--v3-moss)", margin: "3px 0 0", fontFamily: "var(--v3-font-mono)" }}>+{lift.toFixed(0)} pts</p>
                        )}
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <Sparkles size={42} color="var(--v3-saffron)" />
              )
            }
            ctaText={active ? "Show me the projection →" : "Generate a plan →"}
            onClick={() => (active ? navigate("/v3/chat?q=Walk+me+through+my+action+plan") : handleGenerate())}
          />

          {projection?.components && (
            <section>
              <SectionHead title="Component impact" count={`${Object.keys(projection.components).length} dimensions`} />
              <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(4, 1fr)" : "1fr 1fr", gap: 12 }}>
                {Object.entries(projection.components).slice(0, 4).map(([key, value]) => {
                  const delta = value?.delta ?? value?.improvement ?? null;
                  return (
                    <CompactCard
                      key={key}
                      category="health"
                      label={key.charAt(0).toUpperCase() + key.slice(1)}
                      meta={delta != null ? `${delta > 0 ? "↑" : delta < 0 ? "↓" : ""} ${Math.abs(delta).toFixed(1)} pts` : "—"}
                    />
                  );
                })}
              </div>
            </section>
          )}

          {active && actions.length > 0 && (
            <div style={{ padding: "12px 14px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <span style={{ fontSize: 12, color: "var(--v3-ink-2)" }}>Action progress</span>
                <span className="v3-data" style={{ fontSize: 11, color: "var(--v3-ink-3)" }}>{completedCount} of {actions.length} done</span>
              </div>
              <div style={{ height: 6, background: "var(--v3-bg-3)", borderRadius: 3, overflow: "hidden" }}>
                <div style={{ width: `${actions.length ? (completedCount / actions.length) * 100 : 0}%`, height: "100%", background: "var(--v3-saffron)", borderRadius: 3, transition: "width 220ms ease" }} />
              </div>
            </div>
          )}

          {active && actions.length > 0 && (
            <>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                <div style={{ display: "flex", gap: 8 }}>
                  {FILTERS.map((f) => (
                    <CategoryChip
                      key={f.id}
                      category="health"
                      label={f.label}
                      count={f.id === "all" ? actions.length : f.id === "pending" ? actions.filter((a) => !a.status || a.status === "PENDING").length : completedCount + actions.filter((a) => a.status === "SKIPPED").length}
                      active={filter === f.id}
                      onClick={() => setFilter(f.id)}
                    />
                  ))}
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={handleGenerate} disabled={generating} style={{ padding: "7px 12px", background: "var(--v3-saffron)", border: "none", borderRadius: 999, fontSize: 12, fontWeight: 600, color: "#000", cursor: generating ? "not-allowed" : "pointer", display: "flex", alignItems: "center", gap: 5 }}>
                    <Sparkles size={12} /> {generating ? "Generating…" : "Fresh plan"}
                  </button>
                  <button onClick={handleClear} title="Clear active plan" style={{ padding: 7, background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 999, cursor: "pointer", color: "var(--v3-crimson)", display: "grid", placeItems: "center" }}>
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>

              <section>
                <SectionHead title="Action items" count={`${filteredActions.length} ${filter === "all" ? "actions" : filter}`} />
                {Object.values(grouped).map((g, i) => (
                  <RuleGroup key={i} ruleName={g.name} ruleNumber={g.number} actions={g.items} planId={active.id || active._id} onUpdated={refetch} />
                ))}
                {filteredActions.length === 0 && (
                  <p style={{ textAlign: "center", color: "var(--v3-ink-4)", fontSize: 13, padding: "20px 0" }}>No actions match this filter.</p>
                )}
              </section>
            </>
          )}

          {!active && !loading && (
            <div style={{ textAlign: "center", padding: "32px 24px", background: "var(--v3-bg-2)", borderRadius: 14, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
              <Sparkles size={28} color="var(--v3-saffron)" />
              <p style={{ color: "var(--v3-ink-2)", fontSize: 14, margin: 0 }}>No active plan. Generate one to see your action board.</p>
              <button onClick={handleGenerate} disabled={generating} style={{ padding: "10px 20px", background: "var(--v3-saffron)", border: "none", borderRadius: 999, fontSize: 13, fontWeight: 600, color: "#000", cursor: generating ? "not-allowed" : "pointer" }}>
                {generating ? "Generating…" : "Generate plan"}
              </button>
            </div>
          )}

          {data?.history?.length > 0 && (
            <section>
              <SectionHead title="Plan history" count={`${data.history.length} plans`} />
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {data.history.slice(0, 5).map((p, i) => (
                  <div key={i} style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 10, padding: "10px 14px", display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ fontSize: 12, color: "var(--v3-ink-3)" }}>{p.created_at ? new Date(p.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—"}</span>
                    <span style={{ flex: 1, fontSize: 12, color: "var(--v3-ink-1)" }}>{p.action_count ?? p.actions?.length ?? 0} actions</span>
                    <span className="v3-data" style={{ fontSize: 11, color: "var(--v3-ink-4)" }}>{(p.status || "ARCHIVED").toUpperCase()}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <TinyChip onClick={() => navigate("/v3/chat?q=Explain+the+next+action")}>Explain the next action</TinyChip>
            <TinyChip onClick={() => navigate("/v3/chat?q=What+is+the+tax+impact")}>Tax impact</TinyChip>
            <TinyChip onClick={() => navigate("/v3/chat?q=Undo+the+last+action")}>Undo last action</TinyChip>
          </div>
        </div>
      )}
    </ScreenContainer>
  );
}
