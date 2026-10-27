/**
 * The Idea scorecard (the owner's design: Trade Desk › AI Scanner › Scorecard; the Trade Desk tab mounts it) — how well the AI ideas' ranking has done, from the Phase 4.3
 * pre-registered study as committed (GET /api/desk/idea-scorecard; scorecard-data.ts). Market Overview's Top AI ideas
 * footer links here ("Scorecard →").
 *
 * Shows, in this order: the verdict ("keep B0; the current ranking shows no measurable skill"), RS63's status ("promising,
 * awaiting its pre-registered confirmation"), the study (dates, registration commit, code), each split's table (every
 * arm's rank IC with its Newey-West t, its Δ vs B0 with the permutation p, the top-decile net return and hit rate), each
 * arm's pre-registered checks, the definitions, and the sources with their sha256 and whether the server could read them.
 *
 * Nulls and negatives are shown as they are: B0's Δ and p are "—" (the baseline), a negative return stays negative, and
 * every arm stays in its table. On 503 the route's own reason is shown and nothing is drawn. Nothing here is a
 * prediction, and nothing places an order.
 */
import type { CSSProperties, ReactNode } from "react";
import { Pill } from "../../../components/ui";
import { useCopilotShell } from "../../../lib/shell-context";
import {
  CHECK_LABEL, SPLIT_LABEL, fmtDate, fmtIc, fmtP, fmtRet, fmtShare, fmtT, unavailableOf, useIdeaScorecard, ScorecardContractError,
  type ArmChecks, type IdeaScorecard as Scorecard, type SplitResult,
} from "./scorecard-data";

const MINUS = "−";

const card: CSSProperties = { padding: "16px 18px", gap: 12 };
const th: CSSProperties = {
  padding: "8px 10px", textAlign: "left", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase",
  color: "var(--cp-ink-4)", fontWeight: 500, borderBottom: "1px solid var(--cp-line)", whiteSpace: "nowrap",
};
const td: CSSProperties = { padding: "9px 10px", fontSize: 13, color: "var(--cp-ink-2)", borderBottom: "1px solid var(--cp-line)", verticalAlign: "top" };
const numTd: CSSProperties = { ...td, fontFamily: "var(--mono)", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" };
const note: CSSProperties = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" };

const toneOf = (v: number | null) => (v == null ? "var(--cp-ink-4)" : v < 0 ? "var(--cp-danger)" : "var(--cp-ink)");

function Card({ id, title, right, children }: { id: string; title: ReactNode; right?: ReactNode; children: ReactNode }) {
  return (
    <section data-testid={id} aria-label={typeof title === "string" ? title : undefined} className="cp-card flex min-w-0 flex-col" style={card}>
      <header className="flex flex-wrap items-center" style={{ gap: "6px 10px" }}>
        <h3 className="cp-eyebrow m-0" style={{ flex: "1 1 auto" }}>{title}</h3>
        {right}
      </header>
      {children}
    </section>
  );
}

/** A table that scrolls inside its own box, never the page (390px). */
function Scroll({ children, testId }: { children: ReactNode; testId?: string }) {
  return <div data-testid={testId} className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%" }}>{children}</div>;
}

function SplitTable({ split }: { split: SplitResult }) {
  const label = SPLIT_LABEL[split.name] ?? split.name;
  return (
    <Card
      id={`sc-split-${split.name}`}
      title={`${label} · ${fmtDate(split.from)} – ${fmtDate(split.to)}`}
      right={<span className="cp-mono-note" style={{ textTransform: "none", letterSpacing: "0.02em" }}>{split.dates ?? "—"} signal dates</span>}
    >
      <Scroll>
        <table className="w-full" style={{ borderCollapse: "collapse", minWidth: 640 }}>
          <thead>
            <tr>
              <th style={th} scope="col">Arm</th>
              <th style={th} scope="col">Rank IC · NW t</th>
              <th style={th} scope="col">Δ vs B0 · perm. p</th>
              <th style={th} scope="col">Top decile net</th>
              <th style={th} scope="col">Hit rate</th>
            </tr>
          </thead>
          <tbody>
            {split.arms.map((a) => (
              <tr key={a.arm} data-testid={`sc-row-${split.name}-${a.arm}`} data-baseline={a.isBaseline ? "true" : "false"}>
                <td style={td}>
                  <span className="cp-num" style={{ color: "var(--cp-ink)", marginRight: 8 }}>{a.arm}</span>
                  <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{a.label ?? ""}</span>
                </td>
                <td style={numTd} data-testid="sc-ic">
                  <span style={{ color: toneOf(a.icMean) }}>{fmtIc(a.icMean)}</span>
                  <span style={{ color: "var(--cp-ink-4)" }}> · t {fmtT(a.icT)}</span>
                </td>
                <td style={numTd} data-testid="sc-delta" title={a.isBaseline ? "B0 is the baseline: it is not compared with itself." : undefined}>
                  {a.isBaseline ? (
                    <span style={{ color: "var(--cp-ink-4)" }}>— baseline</span>
                  ) : (
                    <>
                      <span style={{ color: toneOf(a.deltaIc) }}>{fmtIc(a.deltaIc)}</span>
                      <span style={{ color: "var(--cp-ink-4)" }}> · t {fmtT(a.deltaT)} · p {fmtP(a.permutationP)}</span>
                    </>
                  )}
                </td>
                <td style={numTd} data-testid="sc-net"><span style={{ color: toneOf(a.topDecileNet) }}>{fmtRet(a.topDecileNet)}</span></td>
                <td style={numTd} data-testid="sc-hit">{fmtShare(a.hitRate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      <p className="m-0" style={note} data-testid={`sc-split-${split.name}-coverage`}>
        {split.namesPerDate != null ? `About ${Math.round(split.namesPerDate)} names scored per date (median). ` : ""}
        {split.outsideUniverse != null ? `${fmtShare(split.outsideUniverse)} of each day’s top-decile forward movers were outside the scanner’s universe.` : ""}
      </p>
    </Card>
  );
}

function Checks({ rows }: { rows: ArmChecks[] }) {
  if (!rows.length) return <p className="m-0" style={note}>The answer listed no per-arm checks.</p>;
  const keys = [...new Set(rows.flatMap((r) => r.checks.map((c) => c.key)))];
  return (
    <Scroll>
      <table className="w-full" style={{ borderCollapse: "collapse", minWidth: 560 }}>
        <thead>
          <tr>
            <th style={th} scope="col">Arm</th>
            {keys.map((k) => <th key={k} style={{ ...th, whiteSpace: "normal" }} scope="col">{CHECK_LABEL[k] ?? k}</th>)}
            <th style={th} scope="col">Adopted</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.arm} data-testid={`sc-check-${r.arm}`}>
              <td style={{ ...numTd, color: "var(--cp-ink)" }}>{r.arm}</td>
              {keys.map((k) => {
                const p = r.checks.find((c) => c.key === k)?.pass ?? null;
                return (
                  <td key={k} style={numTd} data-check={k} data-pass={p == null ? "unknown" : String(p)}>
                    <span style={{ color: p == null ? "var(--cp-ink-4)" : p ? "var(--mint)" : "var(--cp-danger)" }}>{p == null ? "—" : p ? "pass" : "fail"}</span>
                  </td>
                );
              })}
              <td style={numTd} data-testid="sc-check-adopt">{r.adopt == null ? "—" : r.adopt ? "adopted" : "not adopted"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Scroll>
  );
}

function Fact({ label, children, testId }: { label: string; children: ReactNode; testId?: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 3 }}>
      <span className="cp-mono-note">{label}</span>
      <span data-testid={testId} className="cp-num" style={{ fontSize: 13, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{children}</span>
    </div>
  );
}

function Body({ d }: { d: Scorecard }) {
  const { mobile } = useCopilotShell();
  const s = d.study;
  const variants = new Set(d.splits.flatMap((sp) => sp.arms.filter((a) => !a.isBaseline).map((a) => a.arm))).size;
  return (
    <div data-testid="sc-body" className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
      <header className="flex min-w-0 flex-col" style={{ gap: 10 }}>
        <span className="cp-eyebrow">Idea scorecard · Phase {s.phase ?? "—"} pre-registered study</span>
        <h2 data-testid="sc-headline" className="cp-display m-0" style={{ fontSize: mobile ? 26 : 34, lineHeight: 1.12, fontWeight: 400 }}>
          Verdict: <span data-testid="sc-verdict">{d.verdict}</span>.
          {d.rs63?.status && (
            <> <span style={{ color: "var(--amber)" }}>RS63: {d.rs63.status}.</span></>
          )}
        </h2>
        <p className="m-0" style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--cp-ink-2)", maxWidth: 760 }}>
          The rank on Market Overview orders today’s ideas; it is not a prediction. This study tested whether the current
          ranking (B0) and {variants} variant{variants === 1 ? "" : "s"} of it order the outcome below better than chance,
          on {d.splits.length} time split{d.splits.length === 1 ? "" : "s"}. The numbers are the study’s own, as committed,
          nulls and negatives included.
        </p>
      </header>

      <div className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "repeat(2, minmax(0,1fr))", gap: mobile ? 14 : 18 }}>
        <Card id="sc-decision" title="Decision" right={<Pill tone="ink">{d.adopted ? `${d.adopted} adopted` : "no arm adopted"}</Pill>}>
          <p className="m-0" style={{ fontSize: 15, lineHeight: 1.5, color: "var(--cp-ink)" }}>{d.verdict}</p>
          {d.studyVerdict && <p data-testid="sc-study-verdict" className="m-0" style={note}>The study’s own words: “{d.studyVerdict}”.</p>}
        </Card>
        <Card id="sc-rs63" title={`RS63${d.rs63?.arm ? ` · arm ${d.rs63.arm}` : ""}`} right={<Pill tone="amber">{d.rs63?.adopted ? "adopted" : "not adopted"}</Pill>}>
          {d.rs63 ? (
            <>
              <p className="m-0" style={{ fontSize: 15, lineHeight: 1.5, color: "var(--cp-ink)" }}>
                <span>{d.rs63.label ?? "RS63"}</span>: <span data-testid="sc-rs63-status">{d.rs63.status ?? "—"}</span>
              </p>
              {d.rs63.confirmation && (
                <p className="m-0" style={note}>The confirmation test is registered in <span className="cp-num" style={{ overflowWrap: "anywhere" }}>{d.rs63.confirmation}</span> and has not run yet.</p>
              )}
            </>
          ) : (
            <p className="m-0" style={note}>The answer had no RS63 status.</p>
          )}
        </Card>
      </div>

      <Card id="sc-study" title={s.title ?? s.id}>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "12px 18px" }}>
          <Fact label="Study" testId="sc-study-id">{s.id}</Fact>
          <Fact label="Run date" testId="sc-run-date">{fmtDate(s.runDate)}</Fact>
          <Fact label="Registration commit" testId="sc-registration">{s.registrationCommit ?? "—"}</Fact>
          <Fact label="Code" testId="sc-code">{s.codeSha ?? "—"}</Fact>
          <Fact label="Signal dates" testId="sc-signal-dates">{s.signalDates ?? "—"}</Fact>
          <Fact label="Sessions" testId="sc-sessions">{s.sessions ?? "—"}</Fact>
          <Fact label="Daily bars" testId="sc-bars">{s.barRows != null ? s.barRows.toLocaleString("en-IN") : "—"}</Fact>
          <Fact label="Input hash" testId="sc-input-hash"><span title={s.inputHash ?? undefined}>{s.inputHash ? `${s.inputHash.slice(0, 12)}…` : "—"}</span></Fact>
        </div>
        {s.outcome && <p className="m-0" style={note}>Outcome measured: <span data-testid="sc-outcome">{s.outcome}</span>.</p>}
      </Card>

      <div data-testid="sc-splits" className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
        {d.splits.map((sp) => <SplitTable key={sp.name} split={sp} />)}
      </div>

      <Card id="sc-checks" title="Pre-registered conditions, per arm">
        <p className="m-0" style={note}>An arm replaces B0 only if it meets every condition fixed before the study ran.</p>
        <Checks rows={d.checks} />
      </Card>

      {d.units.length > 0 && (
        <Card id="sc-units" title="How to read the numbers">
          <dl className="m-0 grid" style={{ gridTemplateColumns: "minmax(0,1fr)", gap: 8 }}>
            {d.units.map((u) => (
              <div key={u.key} className="flex min-w-0 flex-wrap" style={{ gap: "2px 10px" }}>
                <dt className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink)" }}>{u.key}</dt>
                <dd className="m-0" style={{ ...note, minWidth: 0, overflowWrap: "anywhere" }}>{u.text.replace(/-(?=\d)/g, MINUS)}</dd>
              </div>
            ))}
          </dl>
        </Card>
      )}

      <Card id="sc-sources" title="Sources">
        {d.sources.length ? (
          <Scroll>
            <table className="w-full" style={{ borderCollapse: "collapse", minWidth: 620 }}>
              <thead>
                <tr>
                  <th style={th} scope="col">File</th>
                  <th style={th} scope="col">sha256</th>
                  <th style={th} scope="col">Present</th>
                </tr>
              </thead>
              <tbody>
                {d.sources.map((x) => (
                  <tr key={x.path} data-testid="sc-source" data-present={x.present == null ? "unknown" : String(x.present)}>
                    <td style={td}>
                      <span className="cp-num" style={{ display: "block", fontSize: 12, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{x.path}</span>
                      {x.role && <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{x.role}</span>}
                    </td>
                    <td style={numTd} title={x.sha256 ?? undefined} data-testid="sc-source-sha">{x.sha256 ? `${x.sha256.slice(0, 12)}…` : "—"}</td>
                    <td style={td} data-testid="sc-source-present">
                      <span style={{ fontFamily: "var(--mono)", color: x.present ? "var(--mint)" : "var(--amber)" }}>{x.present == null ? "—" : x.present ? "yes" : "no"}</span>
                      {x.reason && <span style={{ display: "block", fontSize: 12, color: "var(--cp-ink-3)" }}>{x.reason}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
        ) : (
          <p className="m-0" style={note}>The answer listed no sources.</p>
        )}
        <p className="m-0" style={note}>A document marked “no” could not be read on this server; the numbers come from the first file only.</p>
      </Card>

      {d.disclaimer && <p data-testid="sc-disclaimer" className="m-0" style={{ ...note, fontSize: 12.5 }}>{d.disclaimer}</p>}
    </div>
  );
}

export default function IdeaScorecard() {
  const q = useIdeaScorecard();
  if (q.isPending) {
    return (
      <div data-testid="sc-loading" role="status" aria-label="Loading the idea scorecard" className="cp-card flex flex-col" style={{ gap: 10, padding: 16 }}>
        {[92, 78, 64].map((w) => <span key={w} className="cp-running" style={{ height: 14, borderRadius: 6, background: "var(--bg-2)", width: `${w}%` }} />)}
      </div>
    );
  }
  if (q.isError) {
    const down = unavailableOf(q.error);
    const contract = q.error instanceof ScorecardContractError;
    return (
      <div data-testid="sc-error" data-code={down?.code ?? (contract ? "contract" : "error")} role="alert" className="cp-card flex flex-col items-start" style={{ gap: 8, padding: "18px 18px", borderColor: "var(--danger-line)" }}>
        <span style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.2 }}>
          {down ? "The scorecard is unavailable" : contract ? "The scorecard answer was incomplete" : "The scorecard didn’t load"}
        </span>
        <span data-testid="sc-error-reason" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 680 }}>
          {down ? down.reason : q.error instanceof Error ? q.error.message : "The request failed."}
        </span>
        {down && <span className="cp-mono-note" data-testid="sc-error-code">{down.code}</span>}
        <span style={note}>No figures are shown rather than old or partial ones.</span>
        {!down && !contract && (
          <button type="button" data-testid="sc-retry" className="cp-btn" onClick={() => q.refetch()}>Retry</button>
        )}
      </div>
    );
  }
  return <Body d={q.data} />;
}
