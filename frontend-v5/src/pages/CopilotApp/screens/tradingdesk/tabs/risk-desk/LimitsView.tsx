/**
 * Risk Desk › Limits & budgets (?tab=risk&view=limits).
 *
 *   KPI strip              open risk, daily loss, drawdown, open positions n of 10, entries allowed / halted / killed
 *   Limits · used vs left  the owner's eight limits from GET /api/risk/profile, each with its value, used and left
 *                          (open risk, the largest sector, the day's and the week's loss, drawdown); per-entry limits
 *                          (per trade, position, min R:R) give their rupee budget or rule instead
 *   Open risk reserved     the risk reserved at entry against the open-risk budget; open positions n of 10 (a fixed
 *                          limit, not in the profile)
 *   Market & inputs        the regime / VIX factor and each input's freshness from GET /api/risk/freshness (last close
 *                          and sector for one share: the newest share decision's, or one the user types)
 *   F&O structure caps     the additional F&O checks (GET /api/risk/policy, RiskControls PolicyBody)
 *   Notes                  correlation is not checked; these limits govern paper trades only (→ My portfolio)
 *
 * No slider anywhere: the profile (Controls & profile) is the only risk setting. Unknown figures read "unknown".
 */
import { useId, useState, type FormEvent } from "react";
import { Btn, LoadingBlock, Pill, fmtINR, fmtNum, fmtPct, type Tone } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { INPUT_STYLE, QueryProblem } from "../../../trading/parts";
import { useAuditDecisions } from "../../../fnolab/governance-data";
import { useDesk } from "../../context";
import { Card, PolicyBody } from "../../RiskControls";
import { useRiskPolicy, useRiskStatus } from "../../risk-controls";
import { useRiskProfile, type RiskProfileView } from "../../risk-profile";
import { Kpi, UseBar, ViewHead, quiet } from "./parts";
import {
  MAX_OPEN_POSITIONS, factorText, limitUse, regimeFactor, useRiskFreshness,
  type FreshInput, type FreshStatus, type RiskFreshness,
} from "./risk-desk-data";
import { stampIst } from "../../overview-data";

const UNKNOWN = "unknown";
const plainNum = (v: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 4 }).format(v);
const limitText = (field: string, v: number | null) => (v == null ? UNKNOWN : field === "min_reward_risk" ? `${plainNum(v)} : 1` : `${plainNum(v)}%`);
const pct = (v: number | null) => (v == null ? UNKNOWN : fmtPct(v, { digits: 2 }));
const day = (iso: string | null) => (iso ? stampIst(iso) ?? iso : null);

/** The running limits the headline judges (per-entry limits have no running use). */
const RUNNING = ["max_open_risk_pct", "max_sector_pct", "daily_loss_pct", "weekly_loss_pct", "max_drawdown_pct"];

function entriesOf(st: ReturnType<typeof useRiskStatus>): { text: string; tone: Tone; words: string } {
  const s = st.data;
  if (!s || !s.known) return { text: st.isPending ? "…" : UNKNOWN, tone: "ink", words: "the entry controls are unknown" };
  if (s.killSwitch) return { text: "Blocked", tone: "danger", words: "new entries are blocked by the kill switch" };
  if (s.halted) return { text: "Halted", tone: "danger", words: "new entries are halted" };
  return { text: "Allowed", tone: "mint", words: "new entries are allowed" };
}

function headline(view: RiskProfileView | undefined, entries: string): string {
  if (!view) return `Your paper risk limits; ${entries}.`;
  const l = view.live;
  const openPct = l && l.equityRs ? (l.open.riskRs == null ? null : (l.open.riskRs / l.equityRs) * 100) : null;
  const at = RUNNING.filter((f) => {
    const u = limitUse(f, view.profile.limits[f] ?? null, l, view.liveError);
    return u.leftPct != null && u.leftPct <= 1e-9;
  }).map((f) => view.definitions[f]?.label ?? f);
  const unknown = RUNNING.some((f) => limitUse(f, view.profile.limits[f] ?? null, l, view.liveError).usedPct == null);
  const first = openPct == null ? "Open risk is unknown" : `Open risk is ${fmtPct(openPct, { digits: 1 })} of paper equity`;
  const mid = at.length ? `, ${at.join(" and ")} ${at.length === 1 ? "is" : "are"} at the limit` : unknown ? ", some figures are unknown" : ", inside every limit";
  return `${first}${mid}, and ${entries}.`;
}

// ── limits ───────────────────────────────────────────────────────────────

function LimitRows({ view }: { view: RiskProfileView }) {
  const { mobile } = useCopilotShell();
  return (
    <ol data-testid="rd-limits" className="m-0 flex flex-col p-0" style={{ listStyle: "none" }}>
      {view.fields.map((f, i) => {
        const limit = view.profile.limits[f] ?? null;
        const u = limitUse(f, limit, view.live, view.liveError);
        const label = view.definitions[f]?.label ?? f;
        let used: string;
        let left: string;
        if (u.perEntry) {
          used = "judged per entry";
          left = f === "min_reward_risk"
            ? `each entry needs ${limitText(f, limit)} after costs`
            : u.capRs != null ? `${fmtINR(u.capRs)} ${f === "per_trade_risk_pct" ? "risk per trade" : "per position"}` : `${UNKNOWN} (paper equity unknown)`;
        } else if (u.usedPct == null) {
          used = UNKNOWN;
          left = UNKNOWN;
        } else {
          used = `${pct(u.usedPct)}${u.usedRs != null ? ` · ${fmtINR(u.usedRs)}` : ""}`;
          left = u.leftPct! < 0 ? `over by ${fmtPct(-u.leftPct!, { digits: 2 })}` : `${pct(u.leftPct)} left${u.capRs != null && u.usedRs != null ? ` · ${fmtINR(Math.max(0, u.capRs - u.usedRs))}` : ""}`;
        }
        const over = u.leftPct != null && u.leftPct <= 1e-9;
        return (
          <li key={f} data-testid={`rd-limit-${f}`} data-state={u.perEntry ? "per-entry" : u.usedPct == null ? "unknown" : over ? "at-limit" : "ok"}
            className="flex min-w-0 flex-col" style={{ gap: 6, padding: "11px 0", borderTop: i ? "1px solid var(--cp-line)" : 0 }}>
            <span className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "2px 10px" }}>
              <span data-testid={`rd-limit-${f}-label`} style={{ fontSize: 13.5, color: "var(--cp-ink)", flex: mobile ? "1 1 100%" : "1 1 auto" }}>{label}</span>
              <span data-testid={`rd-limit-${f}-value`} className="cp-num" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>limit {limitText(f, limit)}</span>
            </span>
            {!u.perEntry && <UseBar used={u.usedPct} limit={limit} label={label} />}
            <span className="flex min-w-0 flex-wrap" style={{ gap: "2px 14px", fontSize: 12, lineHeight: 1.5 }}>
              <span data-testid={`rd-limit-${f}-used`} className="cp-num" style={{ color: over ? "var(--cp-danger)" : "var(--cp-ink-2)" }}>
                {u.perEntry ? used : `used ${used}`}{u.note && u.usedPct != null ? ` (${u.note})` : ""}
              </span>
              <span data-testid={`rd-limit-${f}-left`} className="cp-num" style={{ color: "var(--cp-ink-3)" }}>{left}</span>
            </span>
            {u.unknown && !u.perEntry && <span data-testid={`rd-limit-${f}-why`} style={{ ...quiet, overflowWrap: "anywhere" }}>Unknown: {u.unknown}.</span>}
          </li>
        );
      })}
    </ol>
  );
}

function Reserved({ view, maxPositions }: { view: RiskProfileView; maxPositions: number }) {
  const l = view.live;
  const reserved = l?.open.riskRs ?? null;
  const cap = l?.budgetsRs.open_risk ?? null;
  const n = l?.open.positions ?? null;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span data-testid="rd-reserved" style={{ fontSize: 14, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>
          Open risk reserved {reserved == null ? UNKNOWN : fmtINR(reserved)} of {cap == null ? UNKNOWN : fmtINR(cap)} ({limitText("max_open_risk_pct", view.profile.limits.max_open_risk_pct ?? null)})
        </span>
        <UseBar used={reserved} limit={cap} label="Open risk reserved" />
        <span style={quiet}>Each entry reserves its estimated risk when it is allowed: the loss at the stop, plus round-trip costs and a gap stress. Closing the trade releases it.</span>
      </div>
      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span data-testid="rd-positions" style={{ fontSize: 14, color: "var(--cp-ink)" }}>
          Open positions {n == null ? UNKNOWN : fmtNum(n)} of {maxPositions} (fixed limit, not in your profile)
        </span>
        <UseBar used={n} limit={maxPositions} label="Open positions" />
        {l && l.open.legacyPositions ? <span style={quiet}>{fmtNum(l.open.legacyPositions)} of them opened before the risk profile; they count here but reserved no risk.</span> : null}
      </div>
    </div>
  );
}

// ── market state and input freshness ─────────────────────────────────────

const STATUS_TONE: Record<FreshStatus, Tone> = { ok: "mint", stale: "danger", unknown: "amber", not_checked: "ink" };
const STATUS_WORD: Record<FreshStatus, string> = { ok: "ok", stale: "stale", unknown: "unknown", not_checked: "not checked" };

function FreshRow({ id, name, x, value }: { id: string; name: string; x: FreshInput; value?: string | null }) {
  const age = x.ageSessions == null ? null : `${x.ageSessions} ${x.ageSessions === 1 ? "session" : "sessions"} old${x.budget != null ? ` (budget ${x.budget})` : ""}`;
  return (
    <li data-testid={`rd-fresh-${id}`} data-status={x.status} className="flex min-w-0 flex-col" style={{ gap: 3, padding: "9px 0", borderTop: "1px solid var(--cp-line)" }}>
      <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px" }}>
        <span style={{ fontSize: 13, color: "var(--cp-ink)" }}>{name}</span>
        <span data-testid={`rd-fresh-${id}-status`}><Pill tone={STATUS_TONE[x.status]}>{STATUS_WORD[x.status]}</Pill></span>
        {value && <span className="cp-num" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>{value}</span>}
      </span>
      <span data-testid={`rd-fresh-${id}-words`} style={{ ...quiet, overflowWrap: "anywhere" }}>
        {x.status === "not_checked"
          ? "Checked per share: give a symbol below."
          : [x.asOf ? `as of ${day(x.asOf)}` : "no as-of date", age, x.reason].filter(Boolean).join(" · ")}
      </span>
    </li>
  );
}

function RegimeLine({ f }: { f: RiskFreshness }) {
  const m = f.market;
  const r = regimeFactor(m.regime, m.vix);
  const asOf = m.asOf ? ` (as of ${day(m.asOf)})` : " (no as-of date)";
  let text: string;
  let tone: Tone = "ink";
  if (!r.regimeKnown && m.vix == null) {
    text = "Market regime and India VIX are unknown: the regime rule is skipped, and new entries are blocked while the market state is not fresh.";
    tone = "amber";
  } else if (r.deferred) {
    text = `India VIX ${m.vix}${asOf} is at or above 35: new entries are deferred.`;
    tone = "danger";
  } else if (r.factor != null && r.factor < 1) {
    text = `${r.parts.join(" and ")}${asOf}: size limits ${factorText(r.factor)}.`;
    tone = "amber";
  } else {
    text = `${m.regime ? `${m.regime} regime` : "Regime unknown (rule skipped)"}${m.vix != null ? `, India VIX ${m.vix}` : ""}${asOf}: no size cut.`;
  }
  return (
    <div data-testid="rd-regime" data-factor={r.factor ?? "deferred"} className="flex min-w-0 flex-col" style={{ gap: 4, padding: "10px 12px", borderRadius: 10, border: `1px solid ${tone === "amber" ? "var(--amber-line)" : tone === "danger" ? "var(--danger-line)" : "var(--line-2)"}`, background: tone === "amber" ? "var(--amber-soft)" : tone === "danger" ? "var(--cp-danger-soft)" : "transparent" }}>
      <span data-testid="rd-regime-words" style={{ fontSize: 14, lineHeight: 1.45, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{text}</span>
      <span style={quiet}>The cut applies to the size limit, never to what you ask: BEAR halves it, India VIX from 25 halves it again.</span>
    </div>
  );
}

function MarketInputs({ suggested }: { suggested: string | null }) {
  const id = useId();
  const [typed, setTyped] = useState("");
  const [sym, setSym] = useState<string | null>(null);
  const symbol = sym ?? suggested;
  const q = useRiskFreshness(symbol);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const s = typed.trim().toUpperCase();
    setSym(s || null);
  };
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      {q.isPending && <LoadingBlock label="Reading the risk service's inputs" rows={2} />}
      {q.isError && <div data-testid="rd-fresh-error"><QueryProblem what="The input freshness" error={q.error} onRetry={() => { void q.refetch(); }} /></div>}
      {q.data && (
        <>
          <RegimeLine f={q.data} />
          <ul data-testid="rd-fresh" className="m-0 flex flex-col p-0" style={{ listStyle: "none" }}>
            <FreshRow id="market" name="Market state (regime, India VIX)" x={q.data.market} />
            <FreshRow id="last_close" name={`Last close${q.data.symbol ? ` · ${q.data.symbol}` : ""}`} x={q.data.lastClose}
              value={typeof q.data.lastClose.value === "number" ? fmtINR(q.data.lastClose.value) : null} />
            <FreshRow id="sector" name={`Sector${q.data.symbol ? ` · ${q.data.symbol}` : ""}`} x={q.data.sector}
              value={typeof q.data.sector.value === "string" ? q.data.sector.value : null} />
          </ul>
          <span data-testid="rd-fresh-rule" style={quiet}>
            A new paper entry is blocked when any of its inputs is not ok. Age is counted in NSE sessions{q.data.referenceSession ? `, up to the ${day(q.data.referenceSession)} session` : ""}.
            {q.data.symbol && !sym && suggested ? ` ${q.data.symbol} is your newest share decision.` : ""}
          </span>
        </>
      )}
      <form onSubmit={submit} className="flex min-w-0 flex-wrap items-end" style={{ gap: 8 }}>
        <span className="flex min-w-0 flex-col" style={{ gap: 4, flex: "1 1 160px", maxWidth: 260 }}>
          <label htmlFor={`${id}-sym`} style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>Check a share's inputs</label>
          <input id={`${id}-sym`} data-testid="rd-fresh-symbol" value={typed} maxLength={40} placeholder="e.g. INFY" autoCapitalize="characters"
            onChange={(e) => setTyped(e.target.value)} style={INPUT_STYLE} />
        </span>
        <Btn type="submit" data-testid="rd-fresh-check">Check</Btn>
      </form>
    </div>
  );
}

// ── the view ─────────────────────────────────────────────────────────────

export function LimitsView() {
  const { mobile } = useCopilotShell();
  const desk = useDesk();
  const profile = useRiskProfile();
  const status = useRiskStatus();
  const policy = useRiskPolicy();
  const decisions = useAuditDecisions();
  const entries = entriesOf(status);
  const view = profile.data;
  const live = view?.live ?? null;
  const newest = decisions.data ?? [];
  // The positions cap the newest decision was judged against (budget.max_open_positions), else the governor's 10.
  const maxPositions = newest.find((d) => d.budget.max_open_positions != null)?.budget.max_open_positions ?? MAX_OPEN_POSITIONS;
  const suggested = newest.find((d) => d.instrument === "cash" && d.symbol)?.symbol ?? null;
  const gate = status.data?.known ? status.data.gateEnabled : null;
  const use = (f: string) => (view ? limitUse(f, view.profile.limits[f] ?? null, live, view.liveError) : null);
  const kpiPct = (f: string) => {
    const u = use(f);
    return u?.usedPct == null ? (profile.isPending ? "…" : UNKNOWN) : fmtPct(u.usedPct, { digits: 1 });
  };
  const kpiTone = (f: string): Tone => {
    const u = use(f);
    const lim = view?.profile.limits[f] ?? null;
    if (u?.usedPct == null || lim == null) return "ink";
    return u.usedPct >= lim ? "danger" : u.usedPct >= lim * 0.7 ? "amber" : "mint";
  };
  const limitOf = (f: string) => `limit ${limitText(f, view?.profile.limits[f] ?? null)}`;
  const n = live?.open.positions ?? null;

  return (
    <div data-testid="rd-limits-view" className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
      <ViewHead view="Limits & budgets" title={headline(view, entries.words)} />

      <div className="grid" style={{ gap: 10, gridTemplateColumns: `repeat(auto-fit,minmax(min(100%,${mobile ? 140 : 160}px),1fr))` }}>
        <Kpi k="Open risk" testId="rd-kpi-open" value={kpiPct("max_open_risk_pct")} tone={kpiTone("max_open_risk_pct")} note={limitOf("max_open_risk_pct")} />
        <Kpi k="Daily loss" testId="rd-kpi-day" value={kpiPct("daily_loss_pct")} tone={kpiTone("daily_loss_pct")} note={limitOf("daily_loss_pct")} />
        <Kpi k="Drawdown" testId="rd-kpi-drawdown" value={kpiPct("max_drawdown_pct")} tone={kpiTone("max_drawdown_pct")} note={`from peak · ${limitOf("max_drawdown_pct")}`} />
        <Kpi k="Positions" testId="rd-kpi-positions" value={n == null ? (profile.isPending ? "…" : UNKNOWN) : `${fmtNum(n)} / ${maxPositions}`}
          tone={n == null ? "ink" : n >= maxPositions ? "danger" : "ink"} note="fixed limit" />
        <Kpi k="Entries" testId="rd-kpi-entries" value={entries.text} tone={entries.tone} note={status.data?.known ? "kill switch and halt" : "controls unknown"} />
      </div>

      <div className="grid" style={{ gap: mobile ? 14 : 18, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", alignItems: "start" }}>
        <Card id="rd-limits" num="01" title="Limits · used vs allowed" testId="rd-limits-card">
          {profile.isPending && <LoadingBlock label="Loading your risk profile" rows={4} />}
          {profile.isError && <div data-testid="rd-limits-error"><QueryProblem what="Your risk limits" error={profile.error} onRetry={() => { void profile.refetch(); }} /></div>}
          {view && (
            <>
              <LimitRows view={view} />
              {!live && (
                <span data-testid="rd-live-error" role="note" style={{ ...quiet, color: "var(--cp-ink-2)" }}>
                  The live figures could not be read ({view.liveError ?? "no reason given"}), so what is used and left is unknown here.
                </span>
              )}
              <span className="cp-mono-note" data-testid="rd-limits-version">
                {view.profile.name ?? "profile"} · version {view.profile.version ?? UNKNOWN} · {view.profile.limitsVersion ?? "limits version not sent"}
              </span>
            </>
          )}
        </Card>

        <div className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
          <Card id="rd-reserved" num="02" title="Open risk reserved at entry" testId="rd-reserved-card">
            {profile.isPending && <LoadingBlock label="Loading the open book" rows={2} />}
            {profile.isError && <span style={quiet}>Unknown: the risk profile did not load.</span>}
            {view && <Reserved view={view} maxPositions={maxPositions} />}
          </Card>
          <Card id="rd-market" num="03" title="Market regime & input freshness" testId="rd-market-card">
            <MarketInputs suggested={suggested} />
          </Card>
        </div>
      </div>

      <Card
        id="policy" num="04" title="F&O structure caps (additional checks)" testId="risk-policy"
        actions={gate === false
          ? <span data-testid="risk-gate-off"><Pill tone="amber">Gate off for your account</Pill></span>
          : gate === true ? <span data-testid="risk-gate-on"><Pill tone="mint">Gate on</Pill></span> : undefined}
      >
        <PolicyBody q={policy} gateEnabled={gate} />
      </Card>

      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span data-testid="rd-correlation" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>Correlation is not checked; sector exposure is the concentration control.</span>
        <span data-testid="rd-footnote" style={{ ...quiet, overflowWrap: "anywhere" }}>
          These limits govern paper trades only. Your real holdings' risk checks are in{" "}
          <button type="button" data-testid="rd-footnote-portfolio" onClick={() => desk.openTab("portfolio")}
            style={{ background: "none", border: 0, padding: 0, color: "var(--mint)", textDecoration: "underline", cursor: "pointer", font: "inherit" }}>
            My portfolio
          </button>
          . Real holdings are not counted here.
        </span>
      </div>
    </div>
  );
}
