/**
 * Smart trading desk — the trust line every module card carries (PRD §3.2, §16.3):
 * where the figures came from, how fresh they are, whether they are live, delayed, end of day or
 * historical, who made them (exchange-reported, rules, a model or AI), the method or model version,
 * and a confidence where one exists.
 *
 * Pass only what the route returned. A missing field is left out, never guessed; "live" is shown
 * only when the caller knows the feed is live. A stale or failed source is said in words as well as
 * colour (PRD §16.1: colour is never the only signal).
 */
import { TONE_COLOR, type Tone } from "../../components/ui";

export type DataMode = "live" | "delayed" | "eod" | "historical";
export type Maker = "reported" | "rules" | "model" | "ai";
export type SourceStatus = "ok" | "stale" | "failed";

const MODE_LABEL: Record<DataMode, string> = {
  live: "Live",
  delayed: "Delayed",
  eod: "End of day",
  historical: "Historical",
};

const MAKER_LABEL: Record<Maker, string> = {
  reported: "As reported",
  rules: "Rules-based",
  model: "Model output",
  ai: "AI-generated",
};

const STATUS: Record<Exclude<SourceStatus, "ok">, { label: string; tone: Tone }> = {
  stale: { label: "Stale", tone: "amber" },
  failed: { label: "Source failed", tone: "danger" },
};

export interface TrustLineProps {
  /** Who supplied the figures, e.g. "NSE bhavcopy" or "Move-odds model". */
  source: string;
  /** When the figures are as of, already formatted (e.g. "13 Oct 2026" or "11:32 IST"). */
  asOf?: string | null;
  mode?: DataMode | null;
  maker?: Maker | null;
  /** Method or model version, e.g. "Move-odds v4 · out-of-sample Jan–Aug 2025". */
  method?: string | null;
  /** A confidence or uncertainty the source itself gives, e.g. "n 165". */
  confidence?: string | null;
  status?: SourceStatus | null;
  testId?: string;
}

/** One mono line: "NSE bhavcopy · end of day · 13 Oct 2026 · rules-based · scanner v2". */
export function TrustLine({ source, asOf, mode, maker, method, confidence, status, testId }: TrustLineProps) {
  const bad = status && status !== "ok" ? STATUS[status] : null;
  const parts = [
    source,
    mode ? MODE_LABEL[mode] : null,
    asOf || null,
    maker ? MAKER_LABEL[maker] : null,
    method || null,
    confidence || null,
  ].filter((p): p is string => Boolean(p));
  return (
    <span
      className="cp-mono-note"
      data-testid={testId ?? "desk-trust"}
      data-mode={mode ?? ""}
      data-maker={maker ?? ""}
      data-status={status ?? ""}
      style={{ lineHeight: 1.6, overflowWrap: "anywhere" }}
    >
      {bad && <span style={{ color: TONE_COLOR[bad.tone] }}>{bad.label} · </span>}
      {parts.join(" · ")}
    </span>
  );
}
