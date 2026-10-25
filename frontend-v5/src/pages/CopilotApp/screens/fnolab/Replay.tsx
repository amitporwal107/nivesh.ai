/**
 * F&O lab · 06 Historical Replay Lab (?screen=replay). Design: the "Historical Replay Lab" screen of Nivesh F&O Desk.
 *
 * Not built: the screen needs an event-driven options backtester (PRD v2.1 P2.1) and intraday chain history (P0.1).
 * What exists today is research on futures signals (backend/services/fno_backtest), described here in words with no
 * metric: no run in it is an options replay, and its findings are in docs/FO_STAGE_B2_FINDINGS_20261023.md.
 */
import { Section } from "../../components/ui";
import { GapNote, KvRows, SourceCards, quiet, type SourceItem } from "./parts";

const SOURCES: SourceItem[] = [
  { k: "Intraday chain snapshots", sub: "Not stored · P0.1", tone: "danger" },
  { k: "Options backtester", sub: "Not built · P2.1", tone: "danger" },
  { k: "Futures-signal studies", sub: "services/fno_backtest · research only", tone: "amber" },
  { k: "Instrument master", sub: "Daily lot size per contract · no versioned master", tone: "amber" },
  { k: "Preregistration", sub: "Stage B3 options study preregistered · no code", tone: "amber" },
];

export function Replay() {
  return (
    <div className="flex flex-col" style={{ gap: 14 }}>
      <SourceCards items={SOURCES} />
      <GapNote tag="P2.1" title="No options replay exists yet" testId="fnolab-replay-gap">
        Replaying an options strategy needs point-in-time chain snapshots with bid and ask (P0.1), a versioned instrument master, fills with latency and partial fills, walk-forward folds and a sealed out-of-sample window. None of these is built, so this screen shows no runs and no metrics.
      </GapNote>
      <Section title="What exists today · research on futures signals">
        <div data-testid="fnolab-replay-today" className="flex flex-col" style={{ gap: 10 }}>
          <KvRows rows={[
            { k: "Code", v: "backend/services/fno_backtest (study, expiry study, outcomes, stats)" },
            { k: "What it tests", v: "Futures-signal outcomes: entry at the next session's open, exit at the close of day D+h" },
            { k: "Prices", v: "Split/bonus-adjusted cash prices as a proxy for the near-month future; basis and roll are not modelled" },
            { k: "Costs", v: "An assumed round trip (research-cost-v0), with a stressed variant" },
            { k: "Integrity", v: "A poisoned-future-rows leakage test and a permutation gate on every hypothesis" },
            { k: "Result", v: "Stage B2 supported none of its hypotheses (docs/FO_STAGE_B2_FINDINGS_20261023.md)" },
            { k: "Options", v: "The Stage B3 options and Greeks study is preregistered; no code implements it" },
          ]} />
          <span style={quiet}>None of this is an options replay, so none of it is shown as one. A run appears here only when the options backtester writes it.</span>
        </div>
      </Section>
    </div>
  );
}
