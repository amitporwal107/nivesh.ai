/**
 * F&O lab · 05 Strategy Programs (?screen=prog). Design: the "Strategy Programs" screen of Nivesh F&O Desk.
 *
 * Today the desk has strategy TEMPLATES (services/strategy_plan/templates.py) and the payoff engine (payoff-v1). It has
 * no program compiler, executor or program certification (PRD v2.1 P3.1, P3.2), so:
 *   Library   GET /api/desk/strategy/templates — each template's legs, its own parameters and calculation version,
 *             marked "Template · not a certified program"
 *   Dry run   an option template on NIFTY or BANKNIFTY: strikes around the money from the end-of-day chain
 *             (GET /api/fno/{symbol}/chain), premiums the contracts' closes, priced by POST /api/desk/strategy/payoff.
 *             It lists the legs as the child orders it would produce; nothing is sent anywhere. There is no dry-run
 *             risk check: the fno-risk-v1 gate records real decisions only.
 * The design's AGENT-tagged program code, parameter bounds and version diffs need the program registry (P3.1/P3.2).
 */
import { useState } from "react";
import { Btn, EmptyBlock, LoadingBlock, Pill, Section, Tiles, fmtINR, fmtNum } from "../../components/ui";
import { FNO_INDICES, useOptionChain } from "../trading/fno";
import { Choices, QueryProblem, fmtDay } from "../trading/parts";
import { usePayoff } from "../tradingdesk/strategy/usePayoff";
import type { PayoffRequest } from "../tradingdesk/strategy/strategy-contract";
import { DRY_RUN_OFFSETS, buildDryRun, useStrategyTemplates, type StrategyTemplate } from "./governance-data";
import { GapNote, Mark, SourceCards, quiet, type SourceItem } from "./parts";

const SOURCES: SourceItem[] = [
  { k: "Strategy templates", sub: "strategy_plan/templates.py · exists", tone: "mint" },
  { k: "Payoff engine", sub: "payoff-v1 · exists", tone: "mint" },
  { k: "Program compiler", sub: "Not built · P3.2", tone: "danger" },
  { k: "Executor", sub: "Not built · P3.2", tone: "danger" },
  { k: "Program certification", sub: "Not built · P3.1", tone: "danger" },
];

const legText = (t: StrategyTemplate) =>
  t.legs.map((l) => `${l.side.toUpperCase()} ${l.optionType ?? t.kind}${l.strikeParam ? ` @ ${l.strikeParam}` : ""}`).join(" · ");

function Library({ selected, onSelect }: { selected: string | null; onSelect: (name: string) => void }) {
  const q = useStrategyTemplates();
  if (q.isPending) return <LoadingBlock label="Loading the template library" />;
  if (q.isError) return <QueryProblem what="The template library" error={q.error} onRetry={() => void q.refetch()} />;
  const list = q.data.templates;
  if (!list.length) return <EmptyBlock title="No templates" body="The route returned an empty library." />;
  return (
    <Section title="Library" note={`${list.length} templates · ${q.data.calculationVersion ?? "version not given"}`} flush>
      <div data-testid="fnolab-prog-library" className="flex flex-col">
        {list.map((t) => {
          const dry = DRY_RUN_OFFSETS[t.name] != null;
          const on = t.name === selected;
          return (
            <div key={t.name} data-testid="fnolab-prog-template" data-name={t.name} className="flex flex-col" style={{ gap: 5, padding: "12px 16px", borderBottom: "1px solid var(--cp-line)", background: on ? "var(--bg-2)" : undefined }}>
              <span className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
                <span className="flex flex-wrap items-baseline" style={{ gap: "0 8px", minWidth: 0 }}>
                  <span style={{ fontSize: 14, fontWeight: 500 }}>{t.label}</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-3)" }}>{t.name}</span>
                </span>
                <Pill tone="amber">Template · not a certified program</Pill>
              </span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{legText(t)}</span>
              <span style={quiet}>
                Parameters: {t.params.length ? t.params.join(", ") : "none"} · {t.calculationVersion ?? "version not given"}
              </span>
              {dry && (
                <span>
                  <Btn data-testid={`fnolab-prog-pick-${t.name}`} onClick={() => onSelect(t.name)} aria-pressed={on}>
                    {on ? "Selected for the dry run" : "Dry run this template"}
                  </Btn>
                </span>
              )}
            </div>
          );
        })}
      </div>
    </Section>
  );
}

type Underlying = (typeof FNO_INDICES)[number]["symbol"];

function DryRun({ template }: { template: StrategyTemplate | null }) {
  const [symbol, setSymbol] = useState<Underlying>("NIFTY");
  const [request, setRequest] = useState<PayoffRequest | null>(null);
  const oc = useOptionChain(symbol, null);
  const payoff = usePayoff(request, { debounceMs: 0 });

  if (!template) {
    return <EmptyBlock title="Pick an option template to dry run" body="The dry run builds the template's legs from the end-of-day chain and prices them. Nothing is sent anywhere." />;
  }
  const chain = oc.state.status === "ok" ? oc.state.chain : null;
  const build = chain ? buildDryRun(template, chain) : null;
  const run = () => setRequest(build && build.ok ? build.request : null);
  const res = payoff.data;
  const ex = res?.expiry ?? null;
  const ran = request != null;

  return (
    <Section title={`Dry run · ${template.label}`} note="Compiles nothing, sends nothing">
      <div data-testid="fnolab-prog-dryrun" className="flex flex-col" style={{ gap: 14 }}>
        <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
          <Choices label="Underlying" value={symbol} options={FNO_INDICES.map((i) => ({ value: i.symbol, label: i.symbol }))} onChange={(v) => { setSymbol(v); setRequest(null); }} testId="fnolab-prog-underlying" />
          <Btn variant="primary" data-testid="fnolab-prog-run" disabled={!build || !build.ok} onClick={run}>Dry run</Btn>
        </div>
        {oc.state.status === "loading" && <LoadingBlock label="Loading the end-of-day chain" rows={2} />}
        {oc.state.status === "error" && <QueryProblem what="The option chain" error={oc.state.error} onRetry={oc.state.retry} />}
        {oc.state.status === "none" && <EmptyBlock title="No chain" body={oc.state.message} />}
        {build && !build.ok && <span data-testid="fnolab-prog-build-problem" style={{ fontSize: 13, color: "var(--amber)" }}>{build.problem}</span>}
        {chain && build && build.ok && (
          <span style={quiet}>
            Strikes around the money of the {fmtDay(chain.summary.expiry)} expiry, premiums the contracts' closes on {fmtDay(chain.summary.as_of)} (NSE F&O bhavcopy), lot size {fmtNum(chain.lot_size ?? null)}, 1 lot per leg.
          </span>
        )}

        {ran && (
          <div data-testid="fnolab-prog-checks" className="flex flex-col">
            <Check kind={res ? (res.valid ? "ok" : "fail") : payoff.error ? "fail" : "pend"} k="Structure accepted by the payoff engine"
              v={res ? (res.valid ? `${res.calculation_version ?? "payoff-v1"} · no problems` : res.problems.map((p) => p.message).join("; ")) : payoff.errorText ?? "Pricing…"} />
            <Check kind="ok" k="Contracts resolved from the chain" v={build && build.ok ? build.legs.map((l) => `${l.strike} ${l.optionType === "call" ? "CE" : "PE"}`).join(", ") : "—"} />
            <Check kind={ex ? "ok" : "pend"} k="Priced" v={ex ? `Net premium ${fmtINR(ex.net_premium, { signed: true })} (debit negative)` : "Waiting for the payoff"} />
            <Check kind="pend" k="Risk pre-check" v="No dry-run risk check exists: the fno-risk-v1 gate records real decisions only (P0.4)." />
            <Check kind="fail" k="Executor route" v="No executor and no order path (P3.2). Nothing was sent anywhere." />
          </div>
        )}

        {ran && res && res.valid && ex && (
          <>
            <Tiles items={[
              { k: "Net premium", v: fmtINR(ex.net_premium, { signed: true }), s: "Credit positive, debit negative" },
              { k: "Max profit", v: ex.profit_unbounded ? "Unbounded" : fmtINR(ex.max_profit), tone: "mint" },
              { k: "Max loss", v: ex.loss_unbounded ? "Unbounded" : fmtINR(ex.max_loss), tone: "danger" },
              { k: "Breakevens", v: ex.breakevens.length ? ex.breakevens.map((b) => fmtNum(b, 2)).join(" · ") : "—" },
              { k: "Capital at risk", v: res.capital_at_risk == null ? "—" : fmtINR(res.capital_at_risk), s: "Worst net loss incl. entry and exit costs" },
            ]} />
            <div data-testid="fnolab-prog-children" className="flex flex-col" style={{ gap: 6, padding: "12px 14px", borderRadius: 12, background: "var(--bg-2)", border: "1px solid var(--cp-line)" }}>
              <span className="cp-eyebrow">Child orders it would produce · nothing sent</span>
              {request?.legs.map((l, i) => (
                <span key={i} style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
                  L{i + 1} {l.side.toUpperCase()} {request.underlying} {l.expiry} {l.strike} {l.option_type === "call" ? "CE" : "PE"} qty {fmtNum(l.lot_size * l.quantity)} · price {fmtNum(l.entry_price, 2)} (close)
                </span>
              ))}
              <span data-testid="fnolab-prog-not-sent" style={quiet}>
                {res.sent_to_broker === false ? "The payoff route confirms nothing was sent to a broker." : "The payoff route did not confirm that nothing was sent."} Margin is not part of this dry run.
              </span>
            </div>
          </>
        )}
      </div>
    </Section>
  );
}

function Check({ kind, k, v }: { kind: "ok" | "fail" | "pend" | "warn"; k: string; v: string }) {
  return (
    <div data-testid="fnolab-prog-check" data-kind={kind} className="grid" style={{ gridTemplateColumns: "22px minmax(0,1fr)", gap: 10, padding: "9px 0", borderBottom: "1px solid var(--cp-line)", alignItems: "start" }}>
      <Mark kind={kind} />
      <span className="flex flex-col" style={{ gap: 2 }}>
        <span style={{ fontSize: 13.5 }}>{k}</span>
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{v}</span>
      </span>
    </div>
  );
}

export function Programs() {
  const [picked, setPicked] = useState<string | null>("bear_put_spread");
  const q = useStrategyTemplates();
  const template = q.data?.templates.find((t) => t.name === picked) ?? null;
  return (
    <div className="flex flex-col" style={{ gap: 14 }}>
      <SourceCards items={SOURCES} />
      <div className="flex flex-wrap" style={{ gap: 12, alignItems: "flex-start" }}>
        <div style={{ flex: "1 1 340px", minWidth: 0 }}><Library selected={picked} onSelect={setPicked} /></div>
        <div style={{ flex: "1.4 1 420px", minWidth: 0 }}><DryRun key={picked ?? "none"} template={template} /></div>
      </div>
      <GapNote tag="P3.2" title="No program compiler or executor" testId="fnolab-prog-gap-exec">
        The design's versioned program code, with values the agent may set tagged AGENT and exits on the combined structure value, needs a program compiler and an executor that runs child orders as one strategy. Neither exists: a template here is priced, never compiled or executed.
      </GapNote>
      <GapNote tag="P3.1" title="No program certification" testId="fnolab-prog-gap-cert">
        Programs, their parameter bounds and their version history need the certification service. Until then every template is NOT_CERTIFIED, and no mode may run one.
      </GapNote>
    </div>
  );
}
