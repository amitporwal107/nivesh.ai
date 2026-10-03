/**
 * "Which flags really add information" card. Volume and gap flags mostly fire because a stock is volatile, and the
 * odds model already uses volatility, so a flag's raw lift flatters it. Each flag is shown twice: its lift across
 * all stocks (struck through: the misleading figure) and its lift within stocks of similar volatility (the honest
 * one), plus a verdict. Every number comes from the backend; a null is never turned into 0 or 1 and this file
 * supplies no fallback value. Class names only (mv-lift-*); the stylesheet is owned elsewhere.
 */
import type { MoversFlagLift as FlagLiftData } from "@/services/adapters/movers.adapter";

type Flag = FlagLiftData["flags"][number];
type Verdict = NonNullable<Flag["verdict"]>;

const REASONS: Record<string, string> = {
  NIDP_INSIDER_SAST_NOT_BACKFILLED: "The insider / SAST source is not loaded yet.",
  NO_BULK_DEAL_TABLE: "There is no bulk / block deal table to measure this from.",
  TOO_FEW_FIRINGS: "It fired too rarely to measure.",
  POPULATION_TOO_SMALL: "Too few stocks in this window to measure it.",
  NO_FINAL_RUN_IN_WINDOW: "No finished odds run in this window to measure against.",
  NO_ESTIMATES_FOR_HEAD: "No odds estimates exist for this question in this window.",
};

const VERDICTS: Record<Verdict, { word: string; note: string }> = {
  SURVIVES: { word: "SURVIVES", note: "Still adds information after allowing for volatility." },
  WEAK: { word: "WEAK", note: "Adds only a little once volatility is allowed for." },
  DECORATION: { word: "DECORATION", note: "Adds nothing beyond volatility. Ignore it." },
  "PRE-PRICED": { word: "PRE-PRICED", note: "Real signal, but already in the price before you could act." },
};

const x = (v: number) => `${v.toFixed(2)}x`;
const count = (n: number) => n.toLocaleString("en-IN");

function reasonText(f: Flag): string {
  const code = f.reason ?? "";
  const text = REASONS[code] ?? (code ? `Not available (${code}).` : "Not available.");
  return code === "TOO_FEW_FIRINGS" ? `${text} Fired ${count(f.n)} time${f.n === 1 ? "" : "s"}.` : text;
}

function Row({ f }: { f: Flag }) {
  if (!f.available) {
    return (
      <tr className="mv-lift-row mv-lift-row-na" data-testid={`mv-lift-${f.key}`}>
        <th scope="row" className="mv-lift-label">{f.label}</th>
        <td className="mv-lift-na" colSpan={4} data-testid={`mv-lift-na-${f.key}`}>
          <span className="mv-lift-na-tag">Not measured</span> {reasonText(f)}
        </td>
      </tr>
    );
  }
  const v = f.verdict ? VERDICTS[f.verdict] : null;
  const cls = f.verdict ? `mv-lift-row mv-lift-v-${f.verdict.toLowerCase()}` : "mv-lift-row";
  return (
    <tr className={cls} data-testid={`mv-lift-${f.key}`}>
      <th scope="row" className="mv-lift-label">{f.label}</th>
      <td className="mv-lift-uncond">
        {f.lift_uncond == null ? (
          <span className="mv-lift-missing">not reported</span>
        ) : (
          <>
            <span className="mv-lift-sr">Uncontrolled figure, across all stocks: </span>
            <s className="mv-lift-struck" title="Across all stocks: misleading, because volatile stocks fire more flags">
              {x(f.lift_uncond)}
            </s>
          </>
        )}
      </td>
      <td className="mv-lift-within">
        {f.lift_within == null ? (
          <span className="mv-lift-missing">not reported</span>
        ) : (
          <>
            <span className="mv-lift-sr">Within stocks of similar volatility: </span>
            <strong className="mv-lift-num">{x(f.lift_within)}</strong>
          </>
        )}
      </td>
      <td className="mv-lift-verdict">
        {v ? (
          <span className={`mv-lift-chip mv-lift-chip-${f.verdict?.toLowerCase()}`} title={v.note}>
            {v.word}
            <span className="mv-lift-sr">. {v.note}</span>
          </span>
        ) : (
          <span className="mv-lift-missing">no verdict</span>
        )}
      </td>
      <td className="mv-lift-n">{count(f.n)}<span className="mv-lift-sr"> firings</span></td>
    </tr>
  );
}

export function MoversFlagLift(props: {
  data: FlagLiftData | null;
  error?: string | null;
  onRetry?: () => void;
}) {
  const { data, error, onRetry } = props;
  if (error) {
    return (
      <section className="mv-lift mv-lift-error" data-testid="mv-lift" role="alert">
        <p>Could not load the flag comparison: {error}</p>
        {onRetry && <button type="button" className="mv-lift-retry" onClick={onRetry}>Try again</button>}
      </section>
    );
  }
  if (!data) {
    return <section className="mv-lift mv-lift-loading" data-testid="mv-lift" aria-busy="true">Loading flag comparison…</section>;
  }
  return (
    <section className="mv-lift" data-testid="mv-lift" aria-label="Which flags really add information">
      <h3 className="mv-lift-title">Which flags really add information</h3>
      <p className="mv-lift-explain">
        Volume and gap flags mostly fire because a stock is volatile. So each flag is compared with stocks of
        similar volatility, in {data.deciles} groups. The struck-through figure is the lift across all stocks,
        which flatters the flag. Measured over {count(data.population)} stocks, {data.from} to {data.to}.
      </p>
      <table className="mv-lift-table">
        <caption className="mv-lift-sr">Lift of each flag, across all stocks and within similar volatility</caption>
        <thead>
          <tr>
            <th scope="col">Flag</th>
            <th scope="col">All stocks <span className="mv-lift-sr">(uncontrolled)</span></th>
            <th scope="col">Similar volatility</th>
            <th scope="col">Verdict</th>
            <th scope="col">Firings</th>
          </tr>
        </thead>
        <tbody>{data.flags.map((f) => <Row key={f.key} f={f} />)}</tbody>
      </table>
    </section>
  );
}
