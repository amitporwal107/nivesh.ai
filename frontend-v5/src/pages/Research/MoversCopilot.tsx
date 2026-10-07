/**
 * MoversCopilot — the Top Movers v4 "Copilot · Event analysis" card (design lines 284-352), driven by real data.
 *
 * Props (MoversCopilotProps):
 *   detail         MoverDetail   GET /api/movers/{symbol}: bars, events (metrics + exec + flags), model, horizon.
 *   analysis       MoverAnalysis | null   GET /api/movers/{symbol}/analysis for the SAME anchor (pinned event, or the move day when
 *                                  nothing is pinned). null / undefined = not available: the share bars render the design's dash + reason.
 *   pinnedEventId  string | null  id of the pinned event (MoverEvent.id). null/undefined = analyse the move day, like the design.
 *   analysisLoading boolean       true while the analysis is being fetched (reason text only).
 *
 * Honesty: this card is ATTRIBUTION of what happened (E-1 -> E+1), never a forecast and never a causal claim. Our research found
 * event direction is not predictable, so the design's "X explains N%" is worded as "stock-specific movement, which includes X, was N%".
 * The design's event-vs-flow split of the stock-specific part used invented constants (0.18 per deal); we have no data to separate
 * them, so that row is shown as not separable instead.
 */
import type { MoverAnalysis, MoverDetail, MoverEvent, MoverExec, MoverEventMetrics } from "@/services/adapters/movers.adapter";
import "./moversV4Copilot.css";

export type MoversCopilotProps = {
  detail: MoverDetail;
  analysis?: MoverAnalysis | null;
  pinnedEventId?: string | null;
  analysisLoading?: boolean;
};

const DEFAULT_DISCLAIMER = "Attribution of realised return, not a causal claim: direction around events is not predictable in this dataset.";
const COST_FALLBACK = 0.00628; // routers/movers.py COST; used only when no event on the page carries exec.cost

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fdy = (iso: string) => {
  const d = new Date(iso + "T00:00:00Z");
  if (isNaN(d.getTime())) return iso;
  return `${String(d.getUTCDate()).padStart(2, "0")} ${MON[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`;
};
const pct = (v: number | null | undefined) => {
  if (v == null || isNaN(v)) return "—";
  if (Math.abs(v) < 0.0005) v = 0;
  return (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%";
};
const inr = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const off = (n: number) => (n === 0 ? "T" : (n > 0 ? "T+" : "T") + n);
const clip = (s: string, n = 150) => (s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s);

const TONES = ["mint", "amber", "indigo", "danger"];
const tv = (c: string) => `var(--${c})`;
const tline = (c: string) => (TONES.includes(c) ? `var(--${c}-line)` : `color-mix(in srgb, var(--${c}) 30%, transparent)`);
const tsoft = (c: string) => (TONES.includes(c) ? `var(--${c}-soft)` : `color-mix(in srgb, var(--${c}) 12%, transparent)`);
const KNOWN = ["mint", "amber", "indigo", "danger", "rose", "ink", "ink-2", "ink-3", "ink-4"];
const tone = (c: string) => (KNOWN.includes(c) ? c : "ink-3");
const sc = (v: number | null | undefined) => (v == null ? "ink-4" : v >= 0 ? "mint" : "danger");
const OUTC: Record<string, string> = { UP: "mint", DOWN: "danger", BOTH: "amber", NONE: "ink-3", PENDING: "ink-4" };
const TYPE: Record<string, { label: string; c: string }> = {
  res: { label: "RESULTS", c: "indigo" }, news: { label: "FILING", c: "indigo" }, ca: { label: "CORP ACTION", c: "amber" },
  dealB: { label: "DEAL · BOUGHT", c: "mint" }, dealS: { label: "DEAL · SOLD", c: "danger" }, ins: { label: "INSIDER", c: "rose" },
};

type Focus = {
  isDay: boolean; ev: MoverEvent | null; idx: number; title: string; sub: string; kind: string; desc: string; typeKey: string;
  typeLabel: string; color: string; date: string; flags: { label: string; tone: string; dim: boolean }[];
  exec: MoverExec | null; execNote: string | null; m: MoverEventMetrics | null; metricsNote: string;
  drift: number | null; leak: boolean | null;
};

type Bar = MoverDetail["bars"][number];
const avg = (bars: Bar[], a: number, b: number) => {
  const xs = bars.slice(Math.max(0, a), Math.min(bars.length, b + 1)).map((x) => x.v);
  return xs.length ? xs.reduce((p, q) => p + q, 0) / xs.length : null;
};

/** Same rules as routers/movers.py (_exec_of / _leak / _event_metrics), applied to the bars loaded in the page. Used for the move day only,
 *  and only where the window contains the bars the rule needs; anything else stays null. */
function deriveFromBars(bars: Bar[], i: number, H: number, cost: number) {
  const n = bars.length - 1;
  let exec: MoverExec | null = null;
  let execNote: string | null = null;
  const m: MoverEventMetrics = { re: null, gap: null, vol_pre: null, vol_post: null, flip: false };
  const d = bars[i];
  if (i < 1 || i + 1 > n || !d) {
    execNote = "the next session is not in the loaded price window (not traded yet, or outside the chart range)";
  } else {
    const nb = bars[i + 1];
    const o = nb.o, prevC = bars[i - 1].c;
    const gap = o && d.c ? o / d.c - 1 : null;
    const intra = o && nb.c ? nb.c / o - 1 : null;
    const re = prevC && nb.c ? nb.c / prevC - 1 : null;
    m.re = re; m.gap = gap;
    let out: MoverExec["out"] | null = null, el = Math.min(n, i + H) - i;
    if (o && i + H <= n) {
      let up = false, dn = false;
      for (let k = i + 1; k <= i + H; k++) {
        if (bars[k].h && bars[k].h! / o - 1 >= 0.05 - 1e-9) up = true;
        if (bars[k].l && bars[k].l! / o - 1 <= -0.05 + 1e-9) dn = true;
      }
      out = up && dn ? "BOTH" : up ? "UP" : dn ? "DOWN" : "NONE";
    }
    exec = { gap, intra, re, net: intra != null ? intra - cost : null, out: out ?? "PENDING", el, H, cost };
    if (out == null) execNote = `outcome needs ${H} sessions after the move day and the loaded window has ${el}`;
    if (i - 25 >= 0) { // the 20-day base needs its full window loaded; a partial base would overstate/understate the multiple
      const base = avg(bars, i - 25, i - 5);
      const pre = avg(bars, i - 3, i), post = i + 3 <= n ? avg(bars, i, i + 3) : null;
      if (base) { m.vol_pre = pre ? pre / base : null; m.vol_post = post ? post / base : null; }
    }
    const rng = (d.h ?? 0) - (d.l ?? 0);
    if (rng > 0 && d.o && d.c && prevC) {
      const body = d.c - d.o, g = d.o - prevC;
      if (body > 0 !== g > 0 && Math.abs(body) / rng > 0.3 && Math.abs(g) / prevC > 0.01) m.flip = true;
    }
  }
  return { exec, execNote, m };
}

function resolveFocus(detail: MoverDetail, pinnedId: string | null | undefined, analysis: MoverAnalysis | null | undefined): Focus {
  const bars = detail.bars;
  const T = detail.bar_index_of_session;
  const H = detail.horizon ?? 3;
  const cost = detail.events.find((e) => e.exec)?.exec?.cost ?? COST_FALLBACK;
  const pinned = pinnedId ? detail.events.find((e) => e.id === pinnedId) ?? (analysis?.pinned_event?.id === pinnedId ? analysis.pinned_event : null) : null;
  const idxOf = (date: string) => bars.findIndex((b) => b.t >= date);
  const onDay = !pinned ? detail.events.find((e) => idxOf(e.date) === T) ?? null : null;
  const ev = pinned ?? onDay;
  const idx = ev ? idxOf(ev.date) : T;
  const base = { idx, drift: null as number | null, leak: null as boolean | null };
  const drift = idx >= 5 && bars[idx - 1]?.c && bars[idx - 5]?.c ? bars[idx - 1].c! / bars[idx - 5].c! - 1 : null;
  if (ev) {
    const ty = TYPE[ev.type] ?? { label: ev.type_label || ev.type.toUpperCase(), c: "indigo" };
    const flags = ev.flags.map((f) => ({ label: f.label, tone: tone(f.tone), dim: f.verdict === "DECORATION" }));
    const md = !pinned ? detail.move_day : undefined; // API move-day figures (full history) win over the event's own when nothing is pinned
    const leak = (md?.flags ?? ev.flags).some((f) => /^(LEAK|PRE-DRIFT)/i.test(f.label));
    if (md) {
      return {
        ...base, isDay: false, ev, title: ev.title, sub: ev.sub, kind: ev.kind, desc: ev.kind_note, typeKey: ev.type, typeLabel: ty.label, color: ty.c,
        date: ev.date, flags, exec: md.exec ?? ev.exec ?? null, execNote: md.exec ?? ev.exec ? null : "no execution figures for the move day", m: md.metrics ?? ev.metrics,
        metricsNote: "the API returned no value for this metric", drift, leak,
      };
    }
    return {
      ...base, isDay: false, ev, title: ev.title, sub: ev.sub, kind: ev.kind, desc: ev.kind_note, typeKey: ev.type, typeLabel: ty.label, color: ty.c,
      date: ev.date, flags, exec: ev.exec ?? null, execNote: ev.exec ? null : "no execution figures for this event", m: ev.metrics,
      metricsNote: "not available for this event", drift, leak,
    };
  }
  const md = detail.move_day;
  if (md) {
    const flags = (md.flags ?? []).map((x) => ({ label: x.label, tone: tone(x.tone), dim: x.verdict === "DECORATION" }));
    const leak = (md.flags ?? []).some((x) => /^(LEAK|PRE-DRIFT)/i.test(x.label));
    return {
      ...base, isDay: true, ev: null, title: "Move day", sub: "No filing is logged on this session", kind: "NO FILING LOGGED", desc: "No exchange disclosure is logged on the move day.",
      typeKey: "day", typeLabel: "MOVE DAY", color: "ink-2", date: bars[idx]?.t ?? detail.session, flags, exec: md.exec ?? null,
      execNote: md.exec ? null : "the API returned no execution figures for the move day (next session not traded yet)", m: md.metrics ?? null,
      metricsNote: "the API returned no value for this metric", drift, leak,
    };
  }
  const d = idx >= 0 ? deriveFromBars(bars, idx, H, cost) : { exec: null, execNote: "move day not in the price window", m: null as MoverEventMetrics | null };
  const flags: Focus["flags"] = [];
  if (d.m?.gap != null && Math.abs(d.m.gap) >= 0.02) flags.push({ label: `GAP ${d.m.gap > 0 ? "UP" : "DN"} ${(Math.abs(d.m.gap) * 100).toFixed(1)}%`, tone: d.m.gap > 0 ? "mint" : "danger", dim: false });
  const vx = Math.max(d.m?.vol_pre ?? 0, d.m?.vol_post ?? 0);
  if (vx >= 2) flags.push({ label: `VOL ${vx >= 3 ? "3×+" : "2×+"} ${(d.m?.vol_pre ?? 0) >= 2 && (d.m?.vol_post ?? 0) >= 2 ? "PRE+POST" : (d.m?.vol_pre ?? 0) >= 2 ? "PRE" : "POST"}`, tone: "amber", dim: false });
  if (d.m?.flip) flags.push({ label: "COIN FLIP", tone: "indigo", dim: false });
  let leak: boolean | null = null;
  if (idx > 5 && bars[idx].c && bars[idx].prev_c && drift != null) {
    const move = bars[idx].c! / bars[idx].prev_c! - 1;
    leak = Math.abs(drift) >= 0.015 && drift > 0 === move > 0;
    if (leak) flags.push({ label: "LEAK", tone: "amber", dim: false });
  }
  return {
    ...base, isDay: true, ev: null, title: "Move day", sub: "No filing is logged on this session", kind: "NO FILING LOGGED", desc: "No exchange disclosure is logged on the move day.",
    typeKey: "day", typeLabel: "MOVE DAY", color: "ink-2", date: bars[idx]?.t ?? detail.session, flags, exec: d.exec, execNote: d.execNote,
    m: d.m, metricsNote: "needs 25 prior sessions of volume, which the loaded price window does not contain", drift, leak,
  };
}

const S_MONO = "var(--mono)";
const secTitle = { fontFamily: S_MONO, fontSize: "10.5px", letterSpacing: ".12em", color: "var(--ink-3)" } as const;

export function MoversCopilot({ detail, analysis, pinnedEventId, analysisLoading }: MoversCopilotProps) {
  const f = resolveFocus(detail, pinnedEventId, analysis);
  const bars = detail.bars;
  const T = detail.bar_index_of_session;
  const H = detail.horizon ?? 3;
  const sym = detail.symbol;
  const fOff = f.idx >= 0 ? f.idx - T : 0;
  const when = `${fdy(f.date)} · ${f.idx >= 0 ? off(fOff) : "—"}`;
  const pinned = !!f.ev && !!pinnedEventId && f.ev.id === pinnedEventId;
  const hint = pinned ? "PINNED EVENT · CLICK AGAIN TO RETURN TO T" : "SHOWING MOVE DAY · PIN A MARKER TO ANALYSE IT";
  const cost = f.exec?.cost ?? detail.events.find((e) => e.exec)?.exec?.cost ?? COST_FALLBACK;
  const costTxt = (cost * 100).toFixed(3).replace(/0+$/, "").replace(/\.$/, "") + "%";

  // ── attribution (analysis EVENT window, E-1 → E+1 around the same anchor) ─────────────────────────────────────────────
  const anchorOk = !!analysis && (pinned ? analysis.pinned_event?.id === pinnedEventId : !analysis.anchor.is_pinned_event);
  const dec = anchorOk ? analysis!.windows.find((w) => w.key === "EVENT")?.decomp ?? null : null;
  const attrReason = !analysis ? (analysisLoading ? "attribution is loading" : "attribution was not returned for this session")
    : !anchorOk ? "attribution on screen belongs to a different anchor; waiting for this one"
    : !dec ? "no event-window decomposition returned" : !dec.available ? dec.reason ?? "decomposition unavailable" : null;
  const ok = !!dec && dec.available && dec.R != null && dec.m_part != null && dec.spec != null;
  const sectorLeg = ok && dec!.s_part != null && dec!.sector_leg !== false;
  const mPart = ok ? dec!.m_part! : 0, sPart = sectorLeg ? dec!.s_part! : 0, spec = ok ? dec!.spec! : 0;
  const tot = Math.abs(mPart) + Math.abs(sPart) + Math.abs(spec) || 1;
  const dirR = ok ? Math.sign(dec!.R!) || 1 : 1;
  const withM = (v: number) => Math.abs(v) < 1e-9 || Math.sign(v) === dirR;
  const secName = detail.sector.name ?? analysis?.sector_index ?? "SECTOR";
  const mktName = (analysis?.market_index ?? detail.market.name ?? "Nifty 50").toUpperCase();
  type Attr = { k: string; v: string; w: string; color: string };
  const attr: Attr[] = [];
  {
    const na = (k: string, why: string): Attr => ({ k, v: `— · ${why}`, w: "0%", color: "var(--ink-4)" });
    const row = (k: string, v: number, c: string): Attr => {
      const w = (Math.abs(v) / tot) * 100;
      return { k, v: `${w.toFixed(0)}% · ${withM(v) ? "WITH" : "AGAINST"}`, w: `${w.toFixed(0)}%`, color: withM(v) ? tv(c) : "var(--ink-4)" };
    };
    const why = attrReason ?? "";
    attr.push(ok ? row(`STOCK-SPECIFIC · ${f.typeLabel}`, spec, f.color === "ink-2" ? "mint" : f.color) : na(`STOCK-SPECIFIC · ${f.typeLabel}`, why.toUpperCase()));
    attr.push(na("BULK / BLOCK FLOW", "NOT SEPARABLE FROM THE EVENT"));
    attr.push(ok ? (sectorLeg ? row(`SECTOR · ${secName.toUpperCase()}`, sPart, "amber") : na(`SECTOR · ${secName.toUpperCase()}`, "NO SECTOR LEG")) : na(`SECTOR · ${secName.toUpperCase()}`, why.toUpperCase()));
    attr.push(ok ? row(`MARKET · ${mktName}`, mPart, "indigo") : na(`MARKET · ${mktName}`, why.toUpperCase()));
  }

  // ── signals ─────────────────────────────────────────────────────────────────────────────────────────────────────────
  const m = f.m;
  const gap = f.exec?.gap ?? m?.gap ?? null;
  const volNote = (x: number | null) => (x == null ? f.metricsNote : x >= 3 ? "3×+ expansion" : x >= 2 ? "2×+ expansion" : "vs 20d base");
  type Sig = { k: string; v: string; on: boolean; color: string; note: string };
  const sig: Sig[] = [
    f.drift == null
      ? { k: "PRE-DRIFT 5D · LEAK CHECK", v: "—", on: false, color: "ink-2", note: "needs 5 sessions before the event in the loaded window" }
      : { k: "PRE-DRIFT 5D · LEAK CHECK", v: pct(f.drift), on: !!f.leak, color: f.leak ? "amber" : "ink-2", note: f.leak ? "drift in the reaction direction before disclosure: may be priced in" : Math.abs(f.drift) >= 0.015 ? "drift into the event, but not in the reaction direction" : "no meaningful drift into the event" },
    gap == null
      ? { k: "NEXT-DAY GAP", v: "—", on: false, color: "ink-2", note: f.execNote ?? "next session not traded yet" }
      : { k: "NEXT-DAY GAP", v: pct(gap), on: Math.abs(gap) >= 0.02, color: Math.abs(gap) < 0.02 ? "ink-2" : gap > 0 ? "mint" : "danger", note: Math.abs(gap) >= 0.03 ? "≥3% threshold" : Math.abs(gap) >= 0.02 ? "≥2% threshold" : "below 2%" },
    { k: "VOL PRE (T-3…T-1)", v: m?.vol_pre != null ? m.vol_pre.toFixed(1) + "×" : "—", on: (m?.vol_pre ?? 0) >= 2, color: (m?.vol_pre ?? 0) >= 2 ? "amber" : "ink-2", note: volNote(m?.vol_pre ?? null) },
    { k: "VOL POST (T…T+2)", v: m?.vol_post != null ? m.vol_post.toFixed(1) + "×" : "—", on: (m?.vol_post ?? 0) >= 2, color: (m?.vol_post ?? 0) >= 2 ? "amber" : "ink-2", note: volNote(m?.vol_post ?? null) },
    m == null
      ? { k: "SAME-DAY COIN FLIP", v: "—", on: false, color: "ink-2", note: "not available for this event" }
      : { k: "SAME-DAY COIN FLIP", v: m.flip ? "Yes" : "No", on: m.flip, color: m.flip ? "indigo" : "ink-2", note: m.flip ? "opened one way, closed the other" : "open & close agreed" },
  ];

  // ── numbers used in the headline / prose ─────────────────────────────────────────────────────────────────────────────
  const re = f.exec?.re ?? m?.re ?? (ok ? dec!.R : null);
  const net = f.exec?.net ?? null;
  const intra = f.exec?.intra ?? null;
  const out = f.exec?.out ?? null;
  const pendingExec = out === "PENDING";
  const dir = re != null && re < 0 ? "down" : "up";
  const near = detail.events.filter((e) => e !== f.ev && e.id !== f.ev?.id && f.idx >= 0 && Math.abs(bars.findIndex((b) => b.t >= e.date) - f.idx) <= 3 && bars.findIndex((b) => b.t >= e.date) >= 0);
  const deals = near.filter((e) => e.type.startsWith("deal"));
  const ins = near.filter((e) => e.type === "ins");
  const cat = f.typeKey.startsWith("deal") ? "flow" : f.typeKey === "ins" ? "insider disclosure" : f.typeKey === "ca" ? "corporate action" : "disclosure";
  const specPct = ok ? ((Math.abs(spec) / tot) * 100).toFixed(0) + "%" : null;
  const netTxt = net != null ? `executable net ${pct(net)}` : pendingExec ? "executable net not measurable yet (next session not traded)" : "executable net unavailable";
  let headA: string, headB: string, headC: string;
  const lead = f.isDay ? "No filing is logged on the move day; " : `${f.title}: `;
  if (ok && specPct) {
    if (!withM(spec)) { headA = `${lead}the stock-specific part pulled the other way, `; headB = `about ${specPct}`; headC = ` of gross movement against the ${pct(re)} close-to-close move; ${netTxt}.`; }
    else { headA = f.isDay ? lead + "stock-specific movement was " : `${f.title} was disclosed in a window where stock-specific movement was `; headB = `about ${specPct}`; headC = ` of gross movement in the ${pct(re)} close-to-close move; ${netTxt}.`; }
  } else {
    headA = lead; headB = "share of movement unavailable"; headC = ` (${attrReason}); close-to-close ${pct(re)}; ${netTxt}.`;
  }

  const model = analysis?.model ?? detail.model;
  const mdl = model.state === "CAUGHT" ? { c: "mint", txt: `The odds model had ${sym} flagged${model.head ? ` (${model.head})` : ""}${model.score != null ? ` at score ${model.score.toFixed(2)}` : ""}${model.run_session ? ` in its run of ${fdy(model.run_session)}` : ""}.` }
    : model.state === "MISSED" ? { c: "danger", txt: `The odds model ran${model.score != null ? ` (score ${model.score.toFixed(2)})` : ""} and did not flag ${sym} for this move.` }
    : { c: "ink-3", txt: `No odds-model run covers this session: a coverage gap, not a miss.` };

  const vx2 = m?.vol_post ?? null;
  const prose = [
    `${sym} went ${dir} ${pct(re)} close-to-close (E-1 → E+1)${vx2 != null ? ` on ${vx2.toFixed(1)}× its 20-day volume over the event window` : ""};`,
    gap == null || re == null ? `the next session ${f.execNote ? "is not in the loaded data" : "has not traded yet"}.`
      : `the overnight gap ${Math.sign(gap) === Math.sign(re) ? "was" : "ran the other way and was"} ${((Math.abs(gap) / Math.max(Math.abs(re), 1e-4)) * 100).toFixed(0)}% the size of that move.`,
    intra != null && net != null ? `Measured from the next open to that session's close, the stock returned ${pct(intra)}, or ${pct(net)} after ${costTxt} costs.` : "",
    out == null ? "" : `Outcome at ${H} sessions: ${out}${out === "NONE" ? `, neither ±5% from the open within ${H} sessions` : out === "PENDING" ? `, only ${f.exec!.el} of ${H} sessions have elapsed` : ""}.`,
    f.drift == null ? "" : f.leak ? `Price drifted ${pct(f.drift)} in the five sessions before, so part of this ${f.isDay ? "move" : cat} may already have been in the price before disclosure.` : Math.abs(f.drift) >= 0.015 ? `Price drifted ${pct(f.drift)} in the five sessions before, against the direction of the reaction.` : "There was no meaningful drift into the event.",
    deals.length ? `${deals.length} bulk/block deal${deals.length > 1 ? "s" : ""} printed within ±3 sessions (see the log); this data cannot say whether ${deals.length > 1 ? "they" : "it"} drove the move${ins.length ? ", and insider or SAST disclosures also sit nearby" : ""}.` : "No bulk/block deals printed within ±3 sessions.",
    mdl.txt,
    ok ? `Over the same sessions ${analysis?.market_index ?? "the market index"} moved ${pct(dec!.M)}${sectorLeg ? ` and ${secName} ${pct(dec!.S)}` : ""}.` : "",
    m?.flip && gap != null ? "Note the same-day coin flip: it opened one way and closed the other." : "",
    gap != null && Math.abs(gap) >= 0.02 ? `The next session gapped ${gap > 0 ? "up" : "down"} ${(Math.abs(gap) * 100).toFixed(1)}%, so part of the move arrived overnight.` : "",
  ].filter(Boolean).join(" ");

  // ── WHAT TO VERIFY: only items our data supports ──────────────────────────────────────────────────────────────────────
  type Act = { txt: string; tag: string; color: string };
  const acts: Act[] = [];
  if (f.ev) {
    if (f.typeKey.startsWith("deal")) acts.push({ txt: `Check the counterparty and size: ${clip(f.sub)}.`, tag: "FLOW", color: tv(f.color) });
    else if (f.typeKey === "ca") acts.push({ txt: `Check the corporate-action terms (${clip(f.sub)}) against the price on the record date.`, tag: "CORP ACTION", color: tv(f.color) });
    else if (f.typeKey === "ins") acts.push({ txt: `Check the disclosure (${clip(f.sub)}) for size and shareholding level.`, tag: "INSIDER", color: tv(f.color) });
    else acts.push({ txt: `Read the filing (${clip(f.sub)}) and compare what it discloses with the price reaction.`, tag: "FILING", color: tv(f.color) });
  }
  if (f.leak && f.drift != null) acts.push({ txt: `Pre-event drift of ${pct(f.drift)}: check what was already public in the five sessions before.`, tag: "LEAK CHECK", color: "var(--amber)" });
  else if (f.idx >= 0 && bars[f.idx + 1]?.l != null && bars[f.idx + 1]?.h != null) {
    const nb = bars[f.idx + 1], e3 = bars[f.idx + 3];
    const rel = e3?.c != null ? (e3.c > nb.h! ? "above" : e3.c < nb.l! ? "below" : "inside") : null;
    acts.push({ txt: rel ? `Follow-through: the E+3 close (${inr(e3.c!)}) sat ${rel} the E+1 range (${inr(nb.l!)} – ${inr(nb.h!)}).` : `Follow-through: the E+1 range was ${inr(nb.l!)} – ${inr(nb.h!)}; the E+3 close is not in the loaded window yet.`, tag: "FOLLOW-THRU", color: "var(--ink-2)" });
  }
  if (deals.length && !f.typeKey.startsWith("deal")) acts.push({ txt: `Check the ${deals.length} bulk/block deal${deals.length > 1 ? "s" : ""} within ±3 sessions: counterparties and sizes.`, tag: "FLOW", color: "var(--mint)" });
  if (model.state !== "NO_MODEL_RUN") acts.push({ txt: mdl.txt, tag: "MODEL", color: tv(mdl.c) });

  const stats = [
    { k: "SPAN C E-1 → C E+1", v: pct(re), color: "ink-3" },
    { k: "GAP · C E → O E+1", v: pct(gap), color: sc(gap) },
    { k: "INTRADAY · O → C E+1", v: pct(intra), color: sc(intra) },
    { k: `NET OF ${costTxt} COST`, v: pct(net), color: sc(net) },
  ];
  const outTxt = out == null ? "UNAVAILABLE" : out === "PENDING" ? `PENDING ${f.exec!.el}/${H}` : `${out} · ${H}S`;
  const outC = out ? OUTC[out] : "ink-4";
  const execMissing = !f.exec ? f.execNote : null;
  const reg = analysis?.regression;
  const regNote = reg?.degraded ? ` · BETA ON ${reg.sessions} OF ${reg.requested_sessions} SESSIONS` : "";
  const modelTag = model.head ? ` · ODDS MODEL ${model.head.toUpperCase()}` : " · ODDS MODEL";

  return (
    <section data-testid="mv-copilot" aria-label="Copilot event analysis" className="mv4-cop" style={{ borderRadius: 14, background: "var(--bg-1)", border: "1px solid var(--line)", boxShadow: "var(--shadow-card)", padding: "18px 20px", display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: "18px 32px" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1, background: "linear-gradient(135deg,var(--mint),var(--indigo))", WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>न</span>
          <span style={{ fontFamily: S_MONO, fontSize: 11, letterSpacing: ".14em", color: "var(--ink-3)" }}>COPILOT · EVENT ANALYSIS</span>
          <span data-testid="mv-copilot-type" style={{ display: "flex", alignItems: "center", gap: 6, padding: "2px 8px", borderRadius: 999, border: `1px solid ${tv(f.color)}`, color: tv(f.color), fontFamily: S_MONO, fontSize: 10, letterSpacing: ".08em" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: tv(f.color) }} />{f.typeLabel}
          </span>
          <span style={{ padding: "2px 8px", borderRadius: 999, background: "var(--bg-3)", color: "var(--ink)", fontFamily: S_MONO, fontSize: 10, letterSpacing: ".08em" }}>{f.kind}</span>
          <span style={{ fontFamily: S_MONO, fontSize: 11, color: "var(--ink-3)" }}>{when}</span>
          <span style={{ flex: 1 }} />
          <span style={{ fontFamily: S_MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-4)" }}>{hint}</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--bg-0)" }}>
          <span style={{ fontSize: 13.5, fontWeight: 500, overflowWrap: "anywhere" }}>{`${f.title} · ${f.isDay ? f.sub : clip(f.sub, 200)}`}</span>
          <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{f.desc}</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
            {f.flags.map((fl, i) => (
              <span key={i} style={{ padding: "2px 8px", borderRadius: 999, border: `1px solid ${fl.dim ? "var(--line-2)" : tline(fl.tone)}`, background: fl.dim ? "transparent" : tsoft(fl.tone), color: fl.dim ? "var(--ink-3)" : tv(fl.tone), fontFamily: S_MONO, fontSize: 10, letterSpacing: ".08em", whiteSpace: "nowrap" }}>{fl.label}</span>
            ))}
          </div>
        </div>
        <span data-testid="mv-copilot-headline" style={{ fontFamily: "var(--display)", fontSize: 28, lineHeight: 1.2, textWrap: "pretty" }}>{headA}<span style={{ color: ok && withM(spec) ? tv(f.color === "ink-2" ? "mint" : f.color) : "var(--ink-3)" }}>{headB}</span>{headC}</span>
        <span data-testid="mv-copilot-prose" style={{ fontSize: 14, lineHeight: 1.55, color: "var(--ink-2)", textWrap: "pretty" }}>{prose}</span>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={secTitle}>WHAT TO VERIFY · RANKED BY RELEVANCE</span>
          {acts.map((a, i) => (
            <div key={i} data-testid="mv-copilot-action" style={{ display: "grid", gridTemplateColumns: "28px minmax(0,1fr) auto", gap: 12, alignItems: "center", padding: "9px 0", borderTop: "1px solid var(--line)" }}>
              <span style={{ fontFamily: S_MONO, fontSize: 11, color: "var(--ink-4)" }}>{String(i + 1).padStart(2, "0")}</span>
              <span style={{ fontSize: 13.5 }}>{a.txt}</span>
              <span style={{ fontFamily: S_MONO, fontSize: 11, letterSpacing: ".06em", color: a.color, textAlign: "right", whiteSpace: "nowrap" }}>{a.tag}</span>
            </div>
          ))}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span style={secTitle}>SHARE OF GROSS MOVEMENT · E-1 → E+1 · GREY = AGAINST THE MOVE</span>
          {attr.map((a, i) => (
            <div key={i} data-testid="mv-copilot-attr" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontFamily: S_MONO, fontSize: 10.5, letterSpacing: ".06em" }}><span style={{ color: "var(--ink-2)" }}>{a.k}</span><span style={{ color: a.color }}>{a.v}</span></div>
              <div style={{ height: 4, borderRadius: 2, background: "var(--bg-3)", overflow: "hidden" }}><div style={{ height: "100%", width: a.w, background: a.color, borderRadius: 2 }} /></div>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={secTitle}>TRADE SIGNALS</span>
          {sig.map((s, i) => (
            <div key={i} data-testid="mv-copilot-signal" style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: "2px 12px", alignItems: "center", padding: "8px 11px", borderRadius: 10, border: `1px solid ${s.on ? tv(s.color) : "var(--line)"}`, background: s.on ? "var(--bg-3)" : "var(--bg-0)" }}>
              <span style={{ fontFamily: S_MONO, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)" }}>{s.k}</span>
              <span style={{ fontFamily: S_MONO, fontSize: 13, fontWeight: 500, color: s.v === "—" ? "var(--ink-4)" : tv(s.color), textAlign: "right" }}>{s.v}</span>
              <span style={{ fontSize: 11.5, color: "var(--ink-3)", gridColumn: "1 / -1" }}>{s.note}</span>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={secTitle}>EXECUTABLE RETURN</span>
          <span style={{ flex: 1 }} />
          <span data-testid="mv-copilot-outcome" style={{ padding: "2px 8px", borderRadius: 999, border: `1px solid ${tv(outC)}`, color: tv(outC), fontFamily: S_MONO, fontSize: 10, letterSpacing: ".1em" }}>OUTCOME · {outTxt}</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
          {stats.map((sx, i) => (
            <div key={i} style={{ padding: "9px 11px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--bg-0)", display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={{ fontFamily: S_MONO, fontSize: 9.5, letterSpacing: ".1em", color: "var(--ink-3)" }}>{sx.k}</span>
              <span style={{ fontFamily: "var(--display)", fontSize: 19, color: tv(sx.v === "—" ? "ink-4" : sx.color) }}>{sx.v}</span>
            </div>
          ))}
        </div>
        {execMissing && <span data-testid="mv-copilot-exec-note" style={{ fontSize: 11.5, color: "var(--ink-3)" }}>Execution figures unavailable: {execMissing}.</span>}
        <span data-testid="mv-copilot-footer" style={{ fontFamily: S_MONO, fontSize: 10, letterSpacing: ".06em", color: "var(--ink-4)", lineHeight: 1.5 }}>
          {`GROUNDED IN · NSE EOD · EXCHANGE FILINGS · BULK/BLOCK TAPE${modelTag}${regNote}`}
          <br />
          <span data-testid="mv-copilot-disclaimer">{(analysis?.disclaimer ?? DEFAULT_DISCLAIMER).toUpperCase()}</span>
        </span>
      </div>
    </section>
  );
}

export default MoversCopilot;
