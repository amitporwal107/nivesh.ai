/**
 * Smart trading desk — Portfolio & risk · Paper trading: the forward test of the one F&O hypothesis the research left standing. Design: the "F&O Lab Candidates" canvas, artboard PaperTrading.
 *
 *   GET /api/fno/forward-test   how many sessions have been RECORDED, how many signals, how many are judged (5 sessions on) and, only once 30 sessions are judged, the pooled result
 *                               net of the assumed cost (backend/services/fno_forward). Signals are recorded when a session's data is in and never reconstructed.
 *
 * No performance number is shown before 30 sessions have a judged signal; the screen says how many more are needed and that the past tests were inconclusive. A missing figure is "—", never 0.
 */
import { Widget } from "./widget";
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { LoadingBlock, Pill, fmtNum, fmtPct } from "../../components/ui";
import { QueryProblem, fmtDay } from "../trading/parts";
import { num } from "./desk-data";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

export interface ForwardSetting { recordedSessions: number | null; signalsRecorded: number | null; judgedSessions: number | null; judgedSignals: number | null; openSessions: number | null; sessionsNeeded: number | null; meanPct: number | null; t: number | null }
export interface ForwardTest {
  started: boolean;
  hypothesis: string | null;
  pastResult: string | null;
  notRecorded: string | null;
  horizon: number | null;
  costPct: number | null;
  minSessions: number | null;
  recordedSessions: number | null;
  lastRecorded: string | null;
  pricesAvailable: boolean | null;
  settings: Record<string, ForwardSetting>;
}

export function parseForwardTest(body: unknown): ForwardTest {
  const b = rec(body);
  if (typeof b.started !== "boolean") throw ApiError.contractDrift("fno.forward-test: no `started`");
  const settings: Record<string, ForwardSetting> = {};
  for (const [k, v] of Object.entries(rec(b.settings))) {
    const s = rec(v);
    settings[k] = { recordedSessions: num(s.recorded_sessions), signalsRecorded: num(s.signals_recorded), judgedSessions: num(s.judged_sessions), judgedSignals: num(s.judged_signals), openSessions: num(s.open_sessions), sessionsNeeded: num(s.sessions_needed), meanPct: num(s.mean_pct), t: num(s.t) };
  }
  return {
    started: b.started, hypothesis: str(b.hypothesis), pastResult: str(b.past_result), notRecorded: str(b.not_recorded), horizon: num(b.horizon_sessions), costPct: num(b.cost_pct), minSessions: num(b.min_sessions),
    recordedSessions: num(b.recorded_sessions), lastRecorded: str(b.last_recorded), pricesAvailable: typeof b.prices_available === "boolean" ? b.prices_available : null, settings,
  };
}

export function useForwardTest() {
  return useQuery<ForwardTest>({
    queryKey: ["copilot", "desk", "fno-forward-test"],
    staleTime: 10 * 60_000,
    retry: false,
    queryFn: async ({ signal }) => parseForwardTest((await http({ path: "/api/fno/forward-test", timeoutMs: 45_000, signal })).data),
  });
}

const quiet = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;

function Count({ label, value, note, testId }: { label: string; value: number | null; note: string; testId: string }) {
  return (
    <div className="flex flex-col" style={{ gap: 2, padding: 10, borderRadius: 10, background: "var(--bg-1)", border: "1px solid var(--line-2)", minWidth: 0 }}>
      <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{label}</span>
      <span data-testid={testId} style={{ fontFamily: "var(--mono)", fontSize: 18 }}>{value == null ? "—" : fmtNum(value)}</span>
      <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{note}</span>
    </div>
  );
}

export function ForwardTestPanel() {
  const q = useForwardTest();
  return (
    <Widget id="fno.forwardtest" testId="desk-forward-test" title="Forward test · near-month short build-up" actions={<Pill tone="amber">Inconclusive so far</Pill>} style={{ borderColor: "var(--amber-line)" }} bodyStyle={{ gap: 12, padding: 18 }}>
      {q.isPending && <LoadingBlock label="Loading the forward test" rows={2} />}
      {q.isError && <QueryProblem what="The forward test" error={q.error} onRetry={() => q.refetch()} />}
      {q.data && <ForwardBody d={q.data} />}
    </Widget>
  );
}

function ForwardBody({ d }: { d: ForwardTest }) {
  const primary = d.settings.production_floors;
  const min = d.minSessions ?? 30;
  const judged = primary?.judgedSessions ?? 0;
  return (
    <>
      <p data-testid="desk-forward-hypothesis" style={{ margin: 0, fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{d.hypothesis}</p>
      {!d.started ? (
        <span data-testid="desk-forward-notstarted" style={quiet}>Recording has not started: no session has been recorded yet. Each signal is recorded when a session’s data is in and judged {d.horizon ?? 5} sessions later; nothing is reconstructed afterwards.</span>
      ) : (
        <>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 10 }}>
            <Count label="Sessions recorded" value={d.recordedSessions} note={d.lastRecorded ? `latest ${fmtDay(d.lastRecorded)}` : "—"} testId="desk-forward-sessions" />
            <Count label="Signals recorded" value={primary?.signalsRecorded ?? null} note="production floors" testId="desk-forward-signals" />
            <Count label="Sessions judged" value={primary?.judgedSessions ?? null} note={`${d.horizon ?? 5} sessions on`} testId="desk-forward-judged" />
            <Count label="Still open" value={primary?.openSessions ?? null} note="outcome pending" testId="desk-forward-open" />
          </div>
          <div className="flex flex-col" style={{ gap: 6 }}>
            <div className="flex justify-between"><span style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>Sessions with a judged signal</span><span data-testid="desk-forward-progress-text" style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{judged} of {min} needed</span></div>
            <div style={{ height: 8, borderRadius: 999, background: "var(--bg-4)", overflow: "hidden" }}><div data-testid="desk-forward-progress" style={{ height: "100%", width: `${Math.min(100, (judged / min) * 100)}%`, borderRadius: 999, background: "var(--amber)" }} /></div>
            {primary?.meanPct == null ? (
              <span data-testid="desk-forward-noresult" style={quiet}>
                No result is shown until {min} sessions have a signal judged {d.horizon ?? 5} sessions later, net of an assumed {d.costPct ?? 0.15}% round trip and relative to the F&amp;O universe{d.pricesAvailable === false ? ". Prices could not be read just now, so nothing is judged." : "."}
              </span>
            ) : (
              <span data-testid="desk-forward-result" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
                Pooled over {judged} sessions: {fmtPct(primary.meanPct, { signed: true, digits: 2 })} per signal after the assumed cost (Newey-West t {primary.t == null ? "—" : fmtNum(primary.t, 2)}). Not validated: this is a single hypothesis tested forward, and one result is not a method.
              </span>
            )}
          </div>
        </>
      )}
      <span data-testid="desk-forward-past" style={quiet}>{d.pastResult}</span>
      {d.notRecorded && <span style={quiet}>{d.notRecorded}</span>}
    </>
  );
}
