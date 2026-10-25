/**
 * F&O lab · 08 Shadow Mode Monitor (?screen=shadow). Design: the "Shadow Mode Monitor" screen of Nivesh F&O Desk.
 *
 * Not built: F&O shadow mode (PRD v2.1 P2.2) needs an agent deciding on live data, an evidence store and divergence
 * tracking. The nearest thing that exists is the forward test of one futures signal:
 *   GET /api/fno/forward-test   sessions recorded, signals, judged (tradingdesk/FnoForwardTest.tsx useForwardTest)
 * It is shown labelled as what it is, a forward test of a futures signal and not shadow mode. Its loading or error state
 * sits inside its own card, so it never hides the gap note above it.
 */
import { LoadingBlock, Pill, Section, Tiles, fmtNum } from "../../components/ui";
import { QueryProblem, fmtDay } from "../trading/parts";
import { useForwardTest, type ForwardTest } from "../tradingdesk/FnoForwardTest";
import { GapNote, SourceCards, quiet, type SourceItem } from "./parts";

function sources(ft: ForwardTest | undefined, failed: boolean): SourceItem[] {
  return [
    { k: "Shadow decisions", sub: "Not built · P2.2", tone: "danger" },
    { k: "Live option chain", sub: "NIFTY/BANKNIFTY quotes cached · P0.1 for the rest", tone: "amber" },
    { k: "Order adapter", sub: "None · read-only by construction", tone: "mint" },
    {
      k: "Forward test (futures signal)",
      sub: failed ? "Did not load" : !ft ? "Loading" : ft.started ? `${fmtNum(ft.recordedSessions)} sessions · last ${ft.lastRecorded ? fmtDay(ft.lastRecorded) : "—"}` : "Not started · 0 sessions recorded",
      tone: failed ? "danger" : ft?.started ? "mint" : "amber",
    },
  ];
}

function ForwardTestCard() {
  const q = useForwardTest();
  let body;
  if (q.isPending) body = <LoadingBlock label="Loading the forward test" rows={2} />;
  else if (q.isError) body = <QueryProblem what="The forward test" error={q.error} onRetry={() => void q.refetch()} />;
  else {
    const d = q.data;
    const settings = Object.entries(d.settings);
    body = (
      <div data-testid="fnolab-shadow-forward" data-started={String(d.started)} className="flex flex-col" style={{ gap: 12 }}>
        {d.hypothesis && <span style={{ fontSize: 13.5, color: "var(--cp-ink-2)" }}>{d.hypothesis}</span>}
        <Tiles items={[
          { k: "Sessions recorded", v: fmtNum(d.recordedSessions ?? null), s: d.lastRecorded ? `Last ${fmtDay(d.lastRecorded)}` : "None yet" },
          { k: "Settings recorded", v: fmtNum(settings.length), s: "Each judged on its own; signals overlap" },
          { k: "Judging horizon", v: d.horizon != null ? `${fmtNum(d.horizon)} sessions` : "—", s: "After the signal" },
          { k: "Sessions to a result", v: d.minSessions != null ? fmtNum(d.minSessions) : "—", s: "Judged sessions before any pooled result" },
        ]} />
        {settings.length > 0 && (
          <div className="cp-scroll" style={{ overflowX: "auto" }}>
            <table data-testid="fnolab-shadow-settings" style={{ width: "100%", minWidth: 460, borderCollapse: "collapse", fontSize: 12.5 }}>
              <thead>
                <tr style={{ color: "var(--cp-ink-3)", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase" }}>
                  {["Setting", "Signals", "Judged signals", "Judged sessions", "Sessions needed"].map((h) => (
                    <th key={h} style={{ textAlign: "left", padding: "6px 8px", fontWeight: 400, borderBottom: "1px solid var(--cp-line)" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {settings.map(([name, st]) => (
                  <tr key={name}>
                    <td style={{ padding: "8px", borderBottom: "1px solid var(--cp-line)", fontFamily: "var(--mono)", fontSize: 11.5 }}>{name}</td>
                    <td style={{ padding: "8px", borderBottom: "1px solid var(--cp-line)" }}>{fmtNum(st.signalsRecorded)}</td>
                    <td style={{ padding: "8px", borderBottom: "1px solid var(--cp-line)" }}>{fmtNum(st.judgedSignals)}</td>
                    <td style={{ padding: "8px", borderBottom: "1px solid var(--cp-line)" }}>{fmtNum(st.judgedSessions)}</td>
                    <td style={{ padding: "8px", borderBottom: "1px solid var(--cp-line)" }}>{fmtNum(st.sessionsNeeded)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {d.pastResult && <span style={quiet}>Past study: {d.pastResult}</span>}
        {!d.started && <span style={quiet}>Nothing is recorded yet: signals are written only when a session's data is in, never reconstructed.</span>}
      </div>
    );
  }
  return (
    <Section title="Forward test of a futures signal — not shadow mode" note={<Pill tone="indigo">Read only</Pill>}>
      {body}
    </Section>
  );
}

export function Shadow() {
  const q = useForwardTest();
  return (
    <div className="flex flex-col" style={{ gap: 14 }}>
      <SourceCards items={sources(q.data, q.isError)} />
      <GapNote tag="P2.2" title="No shadow mode yet" testId="fnolab-shadow-gap">
        Shadow mode needs an agent that decides on live market data, an evidence store for each decision (thesis, evidence chain, invalidation, modelled fill against the mid) and a comparison with backtest and paper results. None exists, so there is no decision feed and no hypothetical P&L here.
      </GapNote>
      <ForwardTestCard />
    </div>
  );
}
