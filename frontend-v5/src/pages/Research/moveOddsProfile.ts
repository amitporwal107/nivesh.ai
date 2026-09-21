/**
 * Move odds · profile helpers (owner's design of 2026-09-18, continuation of the stock-analysis-rankings PRD).
 *
 * Pure functions over the /api/move-odds/profile payload: ratio formatting, filter conditions, grade tones and the six
 * question answers in the stock view. Rules they keep:
 *   · Quality is shown BESIDE movement and never combined with it (PRD: "distinguish movement probability from
 *     investment quality").
 *   · A missing value reads "not on record" — never 0 — and a row without a value for an active condition is
 *     excluded, not waved through.
 *   · No recommendation words (owner decision: scores only; D2 unchanged).
 */
import type { MoveHead, MoveProfile, MoveProfileRow, MoveRatioDef } from "@/services/adapters/moveOdds.adapter";

export type Cap = "All" | "Large" | "Mid" | "Small" | "Micro";
export const CAPS: Cap[] = ["All", "Large", "Mid", "Small", "Micro"];
export type Tone = "mint" | "amber" | "danger" | "ink";
export type Cond = { op: ">" | "<"; val: string };          // val as typed; the condition applies only once it is a number

// Short names for the ratios shown under a stock's symbol.
export const SHORT: Record<string, string> = {
  mcap: "MCap", pe: "P/E", pbv: "P/BV", roce: "ROCE", roe: "ROE", opm: "OPM", npm: "NPM", de: "D/E", divy: "Div yield",
  prom: "Promoter", dprom: "Δ promoter", pledge: "Pledged", cr: "Current", sg: "Sales gr.", pg: "Profit gr.", epsg: "EPS gr.",
  evebitda: "EV/EBITDA", ev: "EV", icr: "Int. cover", cfopat: "CFO/PAT", close: "Close", r1m: "1M", r3m: "3M", r1y: "1Y",
};
// Suggested thresholds shown as placeholders only; nothing filters until a value is typed.
export const SUGGEST: Record<string, [">" | "<", number]> = {
  mcap: [">", 1000], opm: [">", 10], roce: [">", 15], roe: [">", 12], de: ["<", 0.5], pe: ["<", 30], pbv: ["<", 5], divy: [">", 0.5],
  prom: [">", 50], pledge: ["<", 5], sg: [">", 10], pg: [">", 10], r1y: [">", 0], r3m: [">", 0], icr: [">", 3], cr: [">", 1],
};

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const INR2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function fmtRatio(unit: MoveRatioDef["unit"], v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  switch (unit) {
    case "cr": return `₹${INR.format(v)} Cr`;
    case "pct": return `${v.toFixed(1)}%`;
    case "x": return `${v.toFixed(1)}×`;
    case "rs": return `₹${INR2.format(v)}`;
    case "pts": return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)} pts`;
  }
}

export function ratioIndex(p: MoveProfile): Record<string, number> {
  return Object.fromEntries(p.ratio_keys.map((k, i) => [k, i]));
}

export function valueOf(p: MoveProfile, idx: Record<string, number>, sym: string, key: string): number | null {
  const i = idx[key];
  if (i === undefined) return null;
  const v = p.rows[sym]?.ratios[i];
  return v == null ? null : v;
}

export function condActive(c: Cond | undefined): boolean {
  if (!c) return false;
  const t = c.val.trim();
  return t !== "" && isFinite(Number(t));
}

/** "pass" | "fail" | "missing": a stock without a value for an active condition is "missing" and is excluded. */
export function checkConds(p: MoveProfile, idx: Record<string, number>, sym: string, conds: Record<string, Cond>): "pass" | "fail" | "missing" {
  let missing = false;
  for (const [key, c] of Object.entries(conds)) {
    if (!condActive(c)) continue;
    const v = valueOf(p, idx, sym, key);
    if (v == null) { missing = true; continue; }
    const n = Number(c.val);
    if (c.op === ">" ? !(v > n) : !(v < n)) return "fail";
  }
  return missing ? "missing" : "pass";
}

export function gradeTone(g: string | null | undefined): Tone {
  return g === "A" ? "mint" : g === "B" ? "amber" : g === "C" ? "danger" : "ink";
}

// The copilot's stock card bands (backend/services/copilot_tools/instrument_research.py) so both cards read alike.
export function fundBand(s: number): { label: string; tone: Tone } {
  return s >= 75 ? { label: "Strong", tone: "mint" } : s >= 58 ? { label: "Above average", tone: "mint" }
    : s >= 45 ? { label: "Average", tone: "amber" } : { label: "Below average", tone: "danger" };
}
export function techBand(s: number): { label: string; tone: Tone } {
  return s >= 60 ? { label: "Bullish", tone: "mint" } : s >= 45 ? { label: "Neutral", tone: "amber" } : { label: "Bearish", tone: "danger" };
}
export function qualityLabel(s: number): string {
  return s >= 75 ? "Strong" : s >= 60 ? "Good" : s >= 45 ? "Average" : "Weak";
}

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b), m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** Median of a ratio across this run's scored stocks (about 1,000, not just the visible page) that share a sector and
 *  have the value, the stock itself included — stated with n. */
export function peerMedian(p: MoveProfile, idx: Record<string, number>, sector: string | null, key: string): { median: number | null; n: number } {
  if (!sector) return { median: null, n: 0 };
  const vals: number[] = [];
  for (const [sym, r] of Object.entries(p.rows)) {
    if (r.sector !== sector) continue;
    const v = valueOf(p, idx, sym, key);
    if (v != null) vals.push(v);
  }
  return { median: median(vals), n: vals.length };
}

export type Bullet = { tone: Tone; text: string };
export type Answer = { label: string; lead: string; bullets: Bullet[] };

const signedPct = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;
const tone = (v: number | null) => (v == null ? "ink" : v > 0 ? "mint" : v < 0 ? "danger" : "ink") as Tone;
const P = (x: number | null | undefined) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);

export type AnswerCtx = {
  sym: string;
  sector: string | null;
  profile: MoveProfile;
  row: MoveProfileRow | null;
  idx: Record<string, number>;
  estimates: Partial<Record<MoveHead, number>>;
  baseRates: Partial<Record<MoveHead, number>>;
  day: (iso: string | null | undefined) => string;
  eventLabel: (key: string) => string;
};

/** The six question chips. Every sentence is built from served numbers; a missing number says so. */
export function answers(c: AnswerCtx): Answer[] {
  const { profile: p, row, idx, sym } = c;
  const v = (k: string) => valueOf(p, idx, sym, k);
  const unit = (k: string) => p.catalogue.find((d) => d.key === k)?.unit ?? "x";
  const f = (k: string) => fmtRatio(unit(k), v(k));
  const q = row?.quality ?? null;
  const sec = row?.sector ? p.sectors[row.sector] ?? null : null;
  const pe = peerMedian(p, idx, row?.sector ?? c.sector, "pe");
  const roce = peerMedian(p, idx, row?.sector ?? c.sector, "roce");
  const secName = row?.sector ?? c.sector ?? "its sector";
  const out: Answer[] = [];

  // 1 · Quality in brief
  if (!q) {
    out.push({ label: "Quality in brief", lead: `No V3 quality score is on record for ${sym} as of ${c.day(p.scores_as_of)}, so it has no rating.`,
      bullets: [{ tone: "ink", text: "Ratings are shown only where a score exists; a missing one is never filled in." }] });
  } else {
    const fb = q.fundamental != null ? `fundamentals ${fundBand(q.fundamental).label.toLowerCase()} (${Math.round(q.fundamental)}/100)` : "fundamentals not scored";
    const tb = q.technical != null ? `technicals ${techBand(q.technical).label.toLowerCase()} (${Math.round(q.technical)}/100)` : "technicals not scored";
    const sg = v("sg"), opm = v("opm"), de = v("de"), prom = v("prom");
    out.push({
      label: "Quality in brief",
      lead: `Rated ${q.grade} (${q.score.toFixed(1)}/100) as of ${c.day(q.as_of)}${q.partial ? `, from only ${q.coverage ?? "—"}% of its inputs` : ""}: ${fb}, ${tb}.`,
      bullets: [
        { tone: tone(sg), text: sg == null ? `Sales growth over twelve months: not on record. OPM ${f("opm")}.` : `Sales ${sg >= 0 ? "grew" : "fell"} ${Math.abs(sg).toFixed(1)}% over the last twelve months against the twelve before; OPM ${opm == null ? "not on record" : f("opm")}.` },
        { tone: de == null ? "ink" : de < 1 ? "mint" : "amber", text: `Debt to equity ${de == null ? "not on record" : f("de")}; promoter holding ${prom == null ? "not on record" : f("prom")}.` },
      ],
    });
  }

  // 2 · How's it performed?
  const r1y = v("r1y"), r3m = v("r3m"), r1m = v("r1m"), roe = v("roe"), pg = v("pg");
  const win = p.return_1y_window;
  out.push({
    label: "How's it performed?",
    lead: (r1y == null ? "No 1-year return on record (it needs 253 sessions of adjusted prices)." :
      `Over the year to ${c.day(win?.to)} it is ${r1y >= 0 ? "up" : "down"} ${Math.abs(r1y).toFixed(1)}% on adjusted closes (from ${c.day(win?.from)}).`) +
      ` Three months ${r3m == null ? "—" : signedPct(r3m)}, one month ${r1m == null ? "—" : signedPct(r1m)}.`,
    bullets: [
      { tone: tone(r1y), text: `Return on equity ${roe == null ? "not on record" : f("roe")}; return on capital employed ${v("roce") == null ? "not on record" : f("roce")}.` },
      { tone: tone(pg), text: pg == null ? "Profit growth over twelve months: not on record." : `Profit ${pg >= 0 ? "grew" : "fell"} ${Math.abs(pg).toFixed(1)}% over the last twelve months against the twelve before.` },
    ],
  });

  // 3 · Cheap or pricey?
  const peV = v("pe");
  out.push({
    label: "Cheap or pricey?",
    lead: (peV == null ? "No P/E on record (a loss, or no profit figure)." :
      `P/E ${f("pe")}${pe.median != null && pe.n > 1 ? ` against a median of ${pe.median.toFixed(1)}× for the ${pe.n} ${secName} stocks scored in this run with a P/E` : ""}.`) +
      ` Price to book ${f("pbv")}.`,
    bullets: [
      { tone: "ink", text: `EV / EBITDA ${f("evebitda")}; market capitalisation ${f("mcap")}.` },
      { tone: "ink", text: `Dividend yield ${f("divy")}${v("divy") === 0 ? " (a 0 can mean no dividend or no data)" : ""}.` },
    ],
  });

  // 4 · How risky is it?
  const e = c.estimates, b = c.baseRates;
  const pledge = v("pledge");
  out.push({
    label: "How risky is it?",
    lead: `Next session: ${P(e.p_up10_1d)} chance of touching +10% and ${P(e.p_down10_1d)} of −10% (base rates ${P(b.p_up10_1d)} and ${P(b.p_down10_1d)}); for 5%, ${P(e.p_up5_1d)} up and ${P(e.p_down5_1d)} down. These are estimates of a touch, not of the close.`,
    bullets: [
      { tone: v("de") == null ? "ink" : (v("de") as number) < 1 ? "mint" : "amber", text: `Debt to equity ${f("de")}; interest coverage ${f("icr")}.` },
      { tone: pledge != null && pledge > 0 ? "danger" : "ink",
        text: `${row?.cap ? `${row.cap} cap` : "Market-cap bucket not on record"}; promoter shares pledged ${pledge == null ? "not on record" : f("pledge")}${pledge === 0 ? " (a 0 can mean none or no data)" : ""}.` },
    ],
  });

  // 5 · Compare to peers
  const diff = q && sec?.median != null ? q.score - sec.median : null;
  const rc = v("roce");
  out.push({
    label: "Compare to peers",
    lead: sec?.median == null ? `No sector rating for ${secName}: none of its scored stocks has at least ${p.coverage_min}% of its inputs.` :
      `${secName} rates ${sec.grade} (${sec.median.toFixed(1)}/100, the median of ${sec.n} stocks with at least ${p.coverage_min}% of their inputs)` +
      (diff == null ? "; this stock has no score." : `; this stock is ${Math.abs(diff).toFixed(1)} points ${diff >= 0 ? "above" : "below"} it.`),
    bullets: [
      { tone: diff == null ? "ink" : diff >= 0 ? "mint" : "danger", text: pe.median != null && peV != null ? `P/E ${f("pe")} against ${pe.median.toFixed(1)}× for ${pe.n} ${secName} stocks scored in this run.` : "P/E comparison: not on record for this stock or its peers." },
      { tone: "ink", text: roce.median != null && rc != null ? `ROCE ${f("roce")} against a median of ${roce.median.toFixed(1)}% for ${roce.n} ${secName} stocks scored in this run.` : "ROCE comparison: not on record for this stock or its peers." },
    ],
  });

  // 6 · Any events?
  const ev = row?.events;
  out.push({
    label: "Any events?",
    lead: !ev || ev.n === 0 ? "No classified filings or reports on record in the five days to the freeze." :
      `${ev.n} on record — ${ev.categories.map(c.eventLabel).join(", ")}; latest ${ev.latest ? c.day(ev.latest) : "—"}.`,
    bullets: [
      { tone: ev && ev.material > 0 ? "amber" : "ink", text: `${ev?.material ?? 0} classified positive, negative or mixed (material); the rest neutral.` },
      { tone: "ink", text: "Events are listed for context; they are not model inputs. The full list is below." },
    ],
  });
  return out;
}
