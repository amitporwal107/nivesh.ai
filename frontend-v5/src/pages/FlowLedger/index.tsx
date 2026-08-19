/**
 * FLOW LEDGER — FII/DII outflow pattern tracker.
 *
 * Visual reference: the NSE NEAT terminal (deep blue screen, amber data).
 *
 * The scoring lives HERE and only here — quarter weights, the consistency bonus,
 * the composite renormalised over filled streams. The API fills the input fields;
 * it never returns a verdict, so there is no second implementation to drift against.
 *
 * Evidence can still be typed by hand. AUTO-FILL replaces the typing, not the
 * judgement: every stream it fills carries its provenance, and every stream it
 * cannot fill carries a sentence saying why. Unfilled streams are excluded from the
 * composite and the weights renormalise, so a gap never reads as neutral evidence.
 */
import { useState, useMemo, useEffect, useCallback } from "react";
import {
  fetchCompanyLedger, fetchSectorLedger,
  type LedgerFill, type LedgerStream,
} from "@/services/flowLedger";

const C = {
  bg: "#081A33", panel: "#0E2547", panelSoft: "#122B52", line: "#1E3A66",
  amber: "#F5C542", text: "#E8EDF6", mut: "#7C92B5",
  sell: "#FF6B5E", buy: "#4FD1A1", neutral: "#8FA6C9",
};
const mono = "'SF Mono', 'Cascadia Mono', Consolas, 'Roboto Mono', ui-monospace, monospace";
const sans = "system-ui, -apple-system, 'Segoe UI', sans-serif";

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const num = (s: string | null): number | null =>
  s === "" || s === null || isNaN(parseFloat(s)) ? null : parseFloat(s);
const fmt = (v: number | null) => (v === null ? "—" : `${v > 0 ? "+" : ""}${v}`);

// ── scoring: every stream returns null (no data) or −100…+100 (− = outflow) ──
function scoreQtr(vals: string[]): number | null {
  const xs = vals.map(num).filter((v): v is number => v !== null);
  if (!xs.length) return null;
  const w = [0.4, 0.3, 0.2, 0.1];
  let s = 0, tw = 0;
  xs.forEach((v, i) => { s += v * (w[i] ?? 0.1); tw += w[i] ?? 0.1; });
  let base = clamp(((s / tw) / 200) * 100, -100, 100);
  const signs = new Set(xs.map((v) => Math.sign(v)).filter((x) => x !== 0));
  if (xs.length >= 2 && signs.size === 1) base = clamp(base * 1.25, -100, 100);
  return Math.round(base);
}
const scoreSelect = (v: string, map: Record<string, number>) =>
  (v === "" ? null : map[v] ?? null);
function scoreDelivery(baseline: string, recent: string): number | null {
  const b = num(baseline), r = num(recent);
  if (b === null || r === null) return null;
  return Math.round(clamp(-(r - b) * 6, -100, 40));
}
function scoreFortnights(dir: string, n: string): number | null {
  const k = num(n);
  if (dir === "" || k === null) return null;
  const m = clamp(k * 18, 0, 100);
  return Math.round(dir === "out" ? -m : m);
}
function scoreAuc(auc: string, idx: string): number | null {
  const a = num(auc), i = num(idx);
  if (a === null || i === null) return null;
  return Math.round(clamp((a - i) * 12, -100, 100));
}
function scoreBreadth(k: string): number | null {
  const v = num(k);
  if (v === null) return null;
  return Math.round(clamp((5 - v) * 20, -100, 100));
}
function scoreRS(pp: string): number | null {
  const v = num(pp);
  if (v === null) return null;
  return Math.round(clamp(v * 8, -100, 100));
}

const SEL_LABELS: Record<string, string> = {
  hs: "Heavy FII selling", s: "Some FII selling", n: "No clear pattern",
  b: "Some FII buying", hb: "Heavy FII buying",
  mt: "Many houses trimming", st: "Some trimming", sa: "Some adding",
  ma: "Many houses adding",
  sb: "Short buildup", lu: "Long unwinding", sc: "Short covering", lb: "Long buildup",
};

// ── UI atoms ────────────────────────────────────────────────────────────────
const Label = ({ children }: { children: React.ReactNode }) => (
  <div style={{ color: C.mut, fontFamily: mono, fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase" }}>{children}</div>
);

const Num = ({ value, onChange, ph, w = 74, suffix, testid }: {
  value: string; onChange: (v: string) => void; ph?: string; w?: number;
  suffix?: string; testid?: string;
}) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
    <input type="number" value={value} placeholder={ph} data-testid={testid}
      onChange={(e) => onChange(e.target.value)}
      style={{ width: w, background: "#081F40", color: C.amber, fontFamily: mono, fontSize: 13,
               border: `1px solid ${C.line}`, borderRadius: 3, padding: "5px 7px", outline: "none" }} />
    {suffix && <span style={{ color: C.mut, fontFamily: mono, fontSize: 11 }}>{suffix}</span>}
  </span>
);

const Sel = ({ value, onChange, opts, testid }: {
  value: string; onChange: (v: string) => void; opts: [string, string][]; testid?: string;
}) => (
  <select value={value} onChange={(e) => onChange(e.target.value)} data-testid={testid}
    style={{ background: "#081F40", color: value === "" ? C.mut : C.amber, fontFamily: mono,
             fontSize: 12, border: `1px solid ${C.line}`, borderRadius: 3, padding: "6px 7px",
             outline: "none", maxWidth: "100%" }}>
    <option value="">— no data yet —</option>
    {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
  </select>
);

function SignalChip({ score }: { score: number | null }) {
  if (score === null)
    return <span style={{ color: C.mut, fontFamily: mono, fontSize: 11 }}>· unfilled</span>;
  const col = score <= -20 ? C.sell : score >= 20 ? C.buy : C.neutral;
  const word = score <= -60 ? "HEAVY OUTFLOW" : score <= -20 ? "OUTFLOW"
    : score < 20 ? "NEUTRAL" : score < 60 ? "INFLOW" : "HEAVY INFLOW";
  return <span style={{ color: col, fontFamily: mono, fontSize: 11, whiteSpace: "nowrap" }}>{fmt(score)} {word}</span>;
}

function DepthBar({ score }: { score: number | null }) {
  const s = score ?? 0;
  return (
    <div style={{ display: "flex", alignItems: "center", width: "100%", height: 6 }}>
      <div style={{ flex: 1, display: "flex", justifyContent: "flex-end", background: "#0A2144", borderRadius: 2 }}>
        <div style={{ width: `${s < 0 ? Math.abs(s) : 0}%`, background: C.sell, height: 6, borderRadius: 2, transition: "width .35s" }} />
      </div>
      <div style={{ width: 1, height: 12, background: C.line, margin: "0 1px" }} />
      <div style={{ flex: 1, background: "#0A2144", borderRadius: 2 }}>
        <div style={{ width: `${s > 0 ? s : 0}%`, background: C.buy, height: 6, borderRadius: 2, transition: "width .35s" }} />
      </div>
    </div>
  );
}

/** A stream row. `fill` is the API's provenance for this stream, when auto-filled. */
function Stream({ tag, title, source, weight, score, fill, children }: {
  tag: string; title: string; source: string; weight: number; score: number | null;
  fill?: LedgerStream; children?: React.ReactNode;
}) {
  return (
    <div style={{ borderTop: `1px solid ${C.line}`, padding: "12px 0" }} data-testid={`stream-${tag}`}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span style={{ color: C.amber, fontFamily: mono, fontSize: 11 }}>{tag}</span>
          <span style={{ color: C.text, fontFamily: sans, fontSize: 13, fontWeight: 600 }}>{title}</span>
          <span style={{ color: C.mut, fontFamily: mono, fontSize: 10 }}>w{weight}</span>
        </div>
        <SignalChip score={score} />
      </div>
      <div style={{ color: C.mut, fontSize: 11, fontFamily: sans, margin: "2px 0 8px" }}>{source}</div>
      {fill?.filled && fill.evidence && (
        <div data-testid={`evidence-${tag}`}
          style={{ fontFamily: mono, fontSize: 10.5, color: C.buy, marginBottom: 8, lineHeight: 1.5 }}>
          ▸ {fill.evidence}
          {fill.source_dataset && <span style={{ color: C.mut }}> · {fill.source_dataset}</span>}
        </div>
      )}
      {fill && !fill.filled && fill.unavailable_reason && (
        <div data-testid={`gap-${tag}`}
          style={{ fontFamily: mono, fontSize: 10.5, color: C.mut, marginBottom: 8,
                   lineHeight: 1.5, borderLeft: `2px solid ${C.line}`, paddingLeft: 8 }}>
          NIDP cannot source this: {fill.unavailable_reason}. Enter it by hand if you have it —
          left blank, it is excluded and the other weights renormalise.
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 16px", marginBottom: 8 }}>{children}</div>
      <DepthBar score={score} />
    </div>
  );
}

function Spark({ points }: { points: { ts: number; score: number }[] }) {
  if (points.length < 2) return null;
  const W = 260, H = 48, pad = 4;
  const xs = points.map((_, i) => pad + (i * (W - 2 * pad)) / (points.length - 1));
  const ys = points.map((p) => pad + ((100 - p.score) / 200) * (H - 2 * pad));
  const path = xs.map((x, i) => `${i ? "L" : "M"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
  const zeroY = pad + (100 / 200) * (H - 2 * pad);
  return (
    <svg width={W} height={H} style={{ maxWidth: "100%" }} role="img" aria-label="Composite score across saved snapshots">
      <line x1={pad} x2={W - pad} y1={zeroY} y2={zeroY} stroke={C.line} strokeDasharray="3 3" />
      <path d={path} fill="none" stroke={C.amber} strokeWidth="1.5" />
      {xs.map((x, i) => (
        <circle key={i} cx={x} cy={ys[i]} r="2.5"
          fill={points[i].score <= -20 ? C.sell : points[i].score >= 20 ? C.buy : C.neutral} />
      ))}
    </svg>
  );
}

const METHOD_COMPANY: [string, string][] = [
  ["S1 / S2 · Quarterly stake", "Weighted average of the QoQ bps changes, recent quarters weighted 0.4 / 0.3 / 0.2 / 0.1. An average of ±200 bps maps to ±100. If every entered quarter has the same sign (min. 2 quarters), the score gets a ×1.25 consistency bonus — a streak is stronger evidence than one big print."],
  ["S3 · Bulk/block deals", "Direction maps to −100 / −50 / 0 / +50 / +100 by net FII value on the exchange deal lists over ~30 sessions. The repeat-seller flag subtracts a further 20 on the sell side, because a staggered exit by one entity is the classic distribution footprint."],
  ["S4 · Delivery on down days", "Score = −6 × (down-day delivery % − 20D baseline), floored at −100 and capped at +40. A +20 pp delivery spike on declines scores −100: real ownership changing hands. The cap is asymmetric because low delivery on declines is only weak positive evidence, never strong."],
  ["S5 · MF monthly portfolios", "Net action across large fund houses' monthly disclosures maps to −100 / −50 / 0 / +50 / +100 — the between-quarters DII proxy."],
  ["S6 · F&O positioning", "Price↓ + OI↑ (short buildup) −100 · price↓ + OI↓ (long unwinding) −40 · price↑ + OI↓ (short covering) +40 · price↑ + OI↑ (long buildup) +100. Unwinding scores milder than buildup because it closes old positions rather than expressing a fresh view."],
];
const METHOD_SECTOR: [string, string][] = [
  ["S1 · NSDL fortnight streak", "±18 points per consecutive fortnight in one direction, capped at 100. One fortnight is rotation noise; five or six is a genuine allocation shift. The streak is counted from the LATEST fortnight, so a sector that sold for six and then bought reads as a 1-fortnight inflow — the current state, not the regime that just ended."],
  ["S2 · AUC vs index gap", "Score = 12 × (sector AUC % change − sector index % change) over the same window. The index move is mark-to-market; the residual gap is active buying or selling."],
  ["S3 · Constituent breadth", "Score = (5 − k) × 20, where k = how many of the sector's top 10 stocks saw FII stake fall QoQ. Breadth separates a sector-level move from one stock's problem."],
  ["S4 · Relative strength", "Score = 8 × (sector 3M return − Nifty 3M return, pp), capped ±100. Price-side confirmation only, hence the lowest weight — flows should lead, price should agree."],
];
const METHOD_COMPOSITE: [string, string][] = [
  ["Composite", "Σ(stream score × weight) ÷ Σ(weights of filled streams). Unfilled streams are excluded and weights renormalised — the verdict never treats missing data as neutral evidence."],
  ["Verdict bands", "≤ −50 Strong Distribution · −49…−20 Distribution · −19…+19 Neutral/Mixed · +20…+49 Accumulation · ≥ +50 Strong Accumulation."],
  ["Coverage", "Share of total stream weight that has data."],
  ["Conviction", "Coverage × agreement, where agreement is the fraction of filled streams whose sign matches the composite (near-neutral streams count half). High conviction needs most streams filled AND pointing the same way."],
];

const STORE_PREFIX = "flowledger:";
type Snapshot = { ts: number; score: number; label: string; conviction: number };

export default function FlowLedgerPage() {
  const [mode, setMode] = useState<"company" | "sector">("company");
  const [view, setView] = useState<"ledger" | "detail">("ledger");
  const [name, setName] = useState("");
  const [saved, setSaved] = useState<string[]>([]);
  const [history, setHistory] = useState<Snapshot[]>([]);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [fillError, setFillError] = useState("");
  const [fill, setFill] = useState<LedgerFill | null>(null);

  const [fiiQ, setFiiQ] = useState(["", "", "", ""]);
  const [diiQ, setDiiQ] = useState(["", "", "", ""]);
  const [deal, setDeal] = useState("");
  const [repeatSeller, setRepeatSeller] = useState(false);
  const [delivBase, setDelivBase] = useState("");
  const [delivDown, setDelivDown] = useState("");
  const [mf, setMf] = useState("");
  const [fo, setFo] = useState("");

  const [ftDir, setFtDir] = useState("");
  const [ftN, setFtN] = useState("");
  const [auc, setAuc] = useState("");
  const [idx, setIdx] = useState("");
  const [breadth, setBreadth] = useState("");
  const [rs, setRs] = useState("");

  const qtrDetail = (vals: string[]) => {
    const parts = vals.map((v, i) => (num(v) === null ? null : `${["Q0", "Q-1", "Q-2", "Q-3"][i]} ${fmt(num(v))}bps`)).filter(Boolean);
    return parts.length ? parts.join(" · ") : "—";
  };

  const streams = useMemo(() => {
    if (mode === "company") {
      let dealScore = scoreSelect(deal, { hs: -100, s: -50, n: 0, b: 50, hb: 100 });
      if (dealScore !== null && dealScore < 0 && repeatSeller) dealScore = clamp(dealScore - 20, -100, 0);
      return [
        { tag: "S1", w: 30, title: "FII stake, quarterly", score: scoreQtr(fiiQ), detail: qtrDetail(fiiQ) },
        { tag: "S2", w: 15, title: "DII stake, quarterly", score: scoreQtr(diiQ), detail: qtrDetail(diiQ) },
        { tag: "S3", w: 20, title: "Bulk / block deals, 30 sessions", score: dealScore, detail: deal === "" ? "—" : `${SEL_LABELS[deal]}${repeatSeller ? " · repeat seller" : ""}` },
        { tag: "S4", w: 15, title: "Delivery % on down days", score: scoreDelivery(delivBase, delivDown), detail: num(delivBase) === null || num(delivDown) === null ? "—" : `${delivDown}% vs ${delivBase}% base` },
        { tag: "S5", w: 10, title: "MF monthly portfolios", score: scoreSelect(mf, { mt: -100, st: -50, n: 0, sa: 50, ma: 100 }), detail: mf === "" ? "—" : SEL_LABELS[mf] },
        { tag: "S6", w: 10, title: "Stock F&O positioning", score: scoreSelect(fo, { sb: -100, lu: -40, n: 0, sc: 40, lb: 100 }), detail: fo === "" ? "—" : SEL_LABELS[fo] },
      ];
    }
    return [
      { tag: "S1", w: 35, title: "NSDL fortnightly FPI flows", score: scoreFortnights(ftDir, ftN), detail: ftDir === "" || num(ftN) === null ? "—" : `${ftN} fortnight ${ftDir === "out" ? "outflow" : "inflow"} streak` },
      { tag: "S2", w: 25, title: "AUC change vs index change", score: scoreAuc(auc, idx), detail: num(auc) === null || num(idx) === null ? "—" : `AUC ${fmt(num(auc))}% vs index ${fmt(num(idx))}%` },
      { tag: "S3", w: 25, title: "Constituent breadth", score: scoreBreadth(breadth), detail: num(breadth) === null ? "—" : `${breadth} of top 10 saw FII stake fall` },
      { tag: "S4", w: 15, title: "Relative strength vs Nifty, 3M", score: scoreRS(rs), detail: num(rs) === null ? "—" : `${fmt(num(rs))}pp vs Nifty over 3M` },
    ];
  }, [mode, fiiQ, diiQ, deal, repeatSeller, delivBase, delivDown, mf, fo, ftDir, ftN, auc, idx, breadth, rs]);

  const verdict = useMemo(() => {
    const filled = streams.filter((s) => s.score !== null);
    if (!filled.length) return { score: 0, label: "AWAITING DATA", col: C.mut, conviction: 0, coverage: 0 };
    const tw = filled.reduce((a, s) => a + s.w, 0);
    const comp = Math.round(filled.reduce((a, s) => a + (s.score as number) * s.w, 0) / tw);
    const coverage = tw / streams.reduce((a, s) => a + s.w, 0);
    const agree = filled.reduce((a, s) => a + (Math.sign(s.score as number) === Math.sign(comp) ? 1 : Math.abs(s.score as number) < 20 ? 0.5 : 0), 0) / filled.length;
    const [label, col] =
      comp <= -50 ? ["STRONG DISTRIBUTION", C.sell] :
      comp <= -20 ? ["DISTRIBUTION", C.sell] :
      comp < 20 ? ["NEUTRAL / MIXED", C.neutral] :
      comp < 50 ? ["ACCUMULATION", C.buy] : ["STRONG ACCUMULATION", C.buy];
    return { score: comp, label, col, conviction: Math.round(coverage * agree * 100), coverage: Math.round(coverage * 100) };
  }, [streams]);

  const explain = useMemo(() => {
    const out: string[] = [];
    streams.forEach((s) => {
      if (s.score === null) return;
      const dir = s.score <= -20 ? "points to outflow" : s.score >= 20 ? "points to inflow" : "is inconclusive";
      out.push(`${s.tag} ${s.title.toLowerCase()} ${dir} (${fmt(s.score)}, weight ${s.w}).`);
    });
    const unfilled = streams.filter((s) => s.score === null).map((s) => s.tag);
    if (unfilled.length) out.push(`Unfilled: ${unfilled.join(", ")} — conviction is capped until these are checked.`);
    return out;
  }, [streams]);

  const contrib = useMemo(() => {
    const filled = streams.filter((s) => s.score !== null);
    const tw = filled.reduce((a, s) => a + s.w, 0) || 1;
    const rows = streams.map((s) => ({ ...s, ws: s.score === null ? null : Math.round(((s.score * s.w) / tw) * 10) / 10 }));
    const totAbs = rows.reduce((a, r) => a + Math.abs(r.ws ?? 0), 0) || 1;
    return rows.map((r) => ({ ...r, share: r.ws === null ? null : Math.round((Math.abs(r.ws) / totAbs) * 100) }));
  }, [streams]);

  // ── persistence: localStorage, private to this browser ────────────────────
  const keyFor = (m: string, n: string) => `${STORE_PREFIX}${m}:${n.trim().toUpperCase().replace(/[\s/\\'"]+/g, "_")}`;
  const refreshSaved = useCallback(() => {
    try {
      const keys: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith(STORE_PREFIX)) keys.push(k);
      }
      setSaved(keys.sort());
    } catch { setSaved([]); }
  }, []);
  useEffect(() => { refreshSaved(); }, [refreshSaved]);
  const flash = (m: string) => { setNotice(m); setTimeout(() => setNotice(""), 3000); };

  const applyInputs = (f: LedgerFill) => {
    const i = f.inputs || {};
    if (f.mode === "company") {
      setFiiQ(i.fiiQ ?? ["", "", "", ""]);
      setDiiQ(i.diiQ ?? ["", "", "", ""]);
      setDeal(i.deal ?? ""); setRepeatSeller(!!i.repeatSeller);
      setDelivBase(i.delivBase ?? ""); setDelivDown(i.delivDown ?? "");
      setMf(i.mf ?? ""); setFo(i.fo ?? "");
    } else {
      setFtDir(i.ftDir ?? ""); setFtN(i.ftN ?? "");
      setAuc(i.auc ?? ""); setIdx(i.idx ?? "");
      setBreadth(i.breadth ?? ""); setRs(i.rs ?? "");
    }
  };

  const autoFill = async () => {
    const target = name.trim();
    if (!target) { flash("Enter a symbol or sector first"); return; }
    setLoading(true); setFillError(""); setFill(null);
    try {
      const f = mode === "company"
        ? await fetchCompanyLedger(target)
        : await fetchSectorLedger(target);
      applyInputs(f);
      setFill(f);
      flash(`Filled ${f.name} — ${f.filled_weight}/${f.total_weight} of stream weight`);
    } catch (e) {
      // Surfaced, not swallowed: a failure to reach NIDP must not look like a
      // company with no data, which is a legitimate and very different answer.
      setFillError(e instanceof Error ? e.message : "Could not reach the data service");
    } finally { setLoading(false); }
  };

  const save = () => {
    if (!name.trim()) { flash("Enter a name to save"); return; }
    const k = keyFor(mode, name);
    let hist: Snapshot[] = [];
    try {
      const prev = localStorage.getItem(k);
      if (prev) hist = JSON.parse(prev).history ?? [];
    } catch { /* first save for this name */ }
    hist = [...hist, { ts: Date.now(), score: verdict.score, label: verdict.label, conviction: verdict.conviction }].slice(-24);
    const state = { mode, name, fiiQ, diiQ, deal, repeatSeller, delivBase, delivDown, mf, fo, ftDir, ftN, auc, idx, breadth, rs };
    try {
      localStorage.setItem(k, JSON.stringify({ state, history: hist }));
      setHistory(hist);
      flash(`Saved ${name.trim().toUpperCase()} · snapshot #${hist.length}`);
      refreshSaved();
    } catch { flash("Save failed — storage unavailable"); }
  };

  const load = (k: string) => {
    try {
      const raw = localStorage.getItem(k);
      if (!raw) return;
      const rec = JSON.parse(raw);
      const s = rec.state ?? rec;
      setMode(s.mode); setName(s.name); setFill(null);
      setFiiQ(s.fiiQ ?? ["", "", "", ""]); setDiiQ(s.diiQ ?? ["", "", "", ""]);
      setDeal(s.deal ?? ""); setRepeatSeller(!!s.repeatSeller);
      setDelivBase(s.delivBase ?? ""); setDelivDown(s.delivDown ?? "");
      setMf(s.mf ?? ""); setFo(s.fo ?? "");
      setFtDir(s.ftDir ?? ""); setFtN(s.ftN ?? ""); setAuc(s.auc ?? ""); setIdx(s.idx ?? "");
      setBreadth(s.breadth ?? ""); setRs(s.rs ?? "");
      setHistory(rec.history ?? []);
      flash(`Loaded ${k.split(":").pop()}`);
    } catch { flash("Load failed"); }
  };

  const del = (k: string) => { try { localStorage.removeItem(k); refreshSaved(); } catch { flash("Delete failed"); } };

  const btn: React.CSSProperties = {
    background: "transparent", color: C.amber, fontFamily: mono, fontSize: 11,
    letterSpacing: "0.08em", border: `1px solid ${C.amber}`, borderRadius: 3,
    padding: "6px 12px", cursor: "pointer",
  };
  const th: React.CSSProperties = { color: C.mut, fontFamily: mono, fontSize: 9, letterSpacing: "0.12em", textAlign: "left", padding: "6px 8px", borderBottom: `1px solid ${C.line}`, whiteSpace: "nowrap" };
  const td: React.CSSProperties = { fontFamily: mono, fontSize: 11, padding: "7px 8px", borderBottom: `1px solid ${C.line}`, verticalAlign: "top" };

  const needle = clamp(verdict.score, -100, 100);
  const methods = mode === "company" ? METHOD_COMPANY : METHOD_SECTOR;
  const streamFill = (tag: string) => fill?.streams?.find((s) => s.tag === tag);

  return (
    <div style={{ background: C.bg, minHeight: "100vh", color: C.text, fontFamily: sans, width: "100%" }}>
      <div style={{ maxWidth: 768, margin: "0 auto", padding: "20px 16px" }}>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8, paddingBottom: 12, borderBottom: `2px solid ${C.amber}` }}>
          <div>
            <div style={{ fontFamily: mono, color: C.amber, fontSize: 16, letterSpacing: "0.18em", fontWeight: 700 }}>FLOW LEDGER</div>
            <div style={{ fontFamily: mono, color: C.mut, fontSize: 10, letterSpacing: "0.14em" }}>FII/DII PATTERN TRACKER · NOT ADVICE</div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <div style={{ display: "flex", borderRadius: 4, overflow: "hidden", border: `1px solid ${C.line}` }}>
              {(["company", "sector"] as const).map((m) => (
                <button key={m} onClick={() => { setMode(m); setFill(null); }} data-testid={`mode-${m}`}
                  style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.1em", padding: "7px 14px", cursor: "pointer", border: "none",
                           background: mode === m ? C.amber : "transparent", color: mode === m ? "#081A33" : C.mut, fontWeight: 700 }}>
                  {m.toUpperCase()}
                </button>
              ))}
            </div>
            <div style={{ display: "flex", borderRadius: 4, overflow: "hidden", border: `1px solid ${C.line}` }}>
              {([["ledger", "LEDGER"], ["detail", "DETAIL"]] as const).map(([v, l]) => (
                <button key={v} onClick={() => setView(v)} data-testid={`view-${v}`}
                  style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.1em", padding: "7px 14px", cursor: "pointer", border: "none",
                           background: view === v ? C.text : "transparent", color: view === v ? "#081A33" : C.mut, fontWeight: 700 }}>
                  {l}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 16 }}>
          <input value={name} onChange={(e) => setName(e.target.value)} data-testid="ledger-name"
            placeholder={mode === "company" ? "SYMBOL · e.g. RELIANCE" : "SECTOR · e.g. Automobile"}
            onKeyDown={(e) => { if (e.key === "Enter") void autoFill(); }}
            style={{ background: "#081F40", color: C.text, fontFamily: mono, fontSize: 13, letterSpacing: "0.06em",
                     border: `1px solid ${C.line}`, borderRadius: 3, padding: "7px 10px", flex: "1 1 180px", outline: "none" }} />
          <button style={{ ...btn, background: C.amber, color: "#081A33", fontWeight: 700 }}
            onClick={() => void autoFill()} disabled={loading} data-testid="autofill">
            {loading ? "FILLING…" : "AUTO-FILL FROM NIDP"}
          </button>
          <button style={btn} onClick={save} data-testid="save-snapshot">SAVE SNAPSHOT</button>
          {notice && <span style={{ color: C.buy, fontFamily: mono, fontSize: 11 }} data-testid="notice">{notice}</span>}
        </div>

        {fillError && (
          <div data-testid="fill-error" style={{ marginTop: 8, padding: 12, background: "#2A1420", border: `1px solid ${C.sell}`, borderRadius: 4, color: C.sell, fontFamily: mono, fontSize: 11.5, lineHeight: 1.6 }}>
            Auto-fill failed: {fillError}. Nothing was changed — the fields below still hold whatever
            was there. This is a data-service problem, not a finding about {name.trim().toUpperCase() || "this name"}.
          </div>
        )}

        {fill && (
          <div data-testid="fill-summary" style={{ marginTop: 8, padding: 12, background: C.panelSoft, border: `1px dashed ${C.line}`, borderRadius: 4 }}>
            <div style={{ fontFamily: mono, fontSize: 10, color: C.amber, letterSpacing: "0.12em" }}>
              AUTO-FILLED FROM NIDP · {fill.filled_weight}/{fill.total_weight} OF STREAM WEIGHT
              {fill.index_used ? ` · BENCHMARK ${fill.index_used}` : ""}
            </div>
            <div style={{ fontSize: 11.5, color: C.mut, lineHeight: 1.65, marginTop: 4 }}>
              Each stream below shows the evidence behind its value, or the reason NIDP cannot
              source it. Unfilled streams are excluded from the composite and the remaining
              weights renormalise — a gap is never scored as neutral.
            </div>
          </div>
        )}

        {saved.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
            {saved.map((k) => (
              <span key={k} style={{ display: "inline-flex", alignItems: "center", gap: 4, border: `1px solid ${C.line}`, borderRadius: 3, padding: "3px 6px" }}>
                <button onClick={() => load(k)} style={{ background: "none", border: "none", color: C.text, fontFamily: mono, fontSize: 11, cursor: "pointer" }}>
                  {k.split(":").slice(1).join(" · ")}
                </button>
                <button onClick={() => del(k)} aria-label={`Delete ${k}`} style={{ background: "none", border: "none", color: C.sell, fontFamily: mono, fontSize: 11, cursor: "pointer" }}>×</button>
              </span>
            ))}
          </div>
        )}

        <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 4, marginTop: 16, padding: 16 }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
            <Label>Composite verdict</Label>
            <span style={{ fontFamily: mono, fontSize: 11, color: C.mut }} data-testid="coverage">
              coverage {verdict.coverage}% · conviction {verdict.conviction}%
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginTop: 4, flexWrap: "wrap" }}>
            <span data-testid="verdict-label" style={{ color: verdict.col, fontFamily: mono, fontSize: 22, fontWeight: 700, letterSpacing: "0.06em" }}>{verdict.label}</span>
            <span style={{ color: C.amber, fontFamily: mono, fontSize: 16 }}>{fmt(verdict.score)}</span>
          </div>
          <div style={{ marginTop: 12, position: "relative", height: 26 }}>
            <div style={{ position: "absolute", inset: "9px 0", background: "linear-gradient(90deg, #FF6B5E 0%, #0A2144 46%, #0A2144 54%, #4FD1A1 100%)", opacity: 0.35, borderRadius: 3 }} />
            <div style={{ position: "absolute", left: "50%", top: 4, bottom: 4, width: 1, background: C.line }} />
            <div style={{ position: "absolute", top: 0, bottom: 0, width: 3, background: C.amber, borderRadius: 2, left: `calc(${(needle + 100) / 2}% - 1px)`, transition: "left .4s", boxShadow: `0 0 8px ${C.amber}` }} />
          </div>
          {view === "ledger" && explain.length > 0 && (
            <div style={{ marginTop: 26 }}>
              {explain.map((l, i) => (<div key={i} style={{ fontFamily: mono, fontSize: 11, color: C.mut, marginTop: 4 }}>› {l}</div>))}
            </div>
          )}
        </div>

        {view === "ledger" ? (
          <>
            <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 4, marginTop: 16, padding: "12px 16px 4px" }}>
              <Label>{mode === "company" ? "Evidence streams — company" : "Evidence streams — sector"}</Label>
              <div style={{ marginTop: 8 }}>
                {mode === "company" ? (
                  <>
                    <Stream tag="S1" weight={30} title="FII stake, quarterly" fill={streamFill("S1")}
                      source="QoQ change in FII holding, basis points (+ rose / − fell). Latest quarter first." score={streams[0].score}>
                      {fiiQ.map((v, i) => (
                        <Num key={i} value={v} ph={["Q0", "Q-1", "Q-2", "Q-3"][i]} suffix="bps" testid={`fiiQ-${i}`}
                          onChange={(x) => setFiiQ(fiiQ.map((o, j) => (j === i ? x : o)))} />
                      ))}
                    </Stream>
                    <Stream tag="S2" weight={15} title="DII stake, quarterly" fill={streamFill("S2")}
                      source="QoQ change in DII holding, basis points. Latest quarter first." score={streams[1].score}>
                      {diiQ.map((v, i) => (
                        <Num key={i} value={v} ph={["Q0", "Q-1", "Q-2", "Q-3"][i]} suffix="bps" testid={`diiQ-${i}`}
                          onChange={(x) => setDiiQ(diiQ.map((o, j) => (j === i ? x : o)))} />
                      ))}
                    </Stream>
                    <Stream tag="S3" weight={20} title="Bulk / block deals, last 30 sessions" fill={streamFill("S3")}
                      source="Net direction of FII/FPI names on the exchange deal lists, by value." score={streams[2].score}>
                      <Sel value={deal} onChange={setDeal} testid="deal"
                        opts={[["hs", "Heavy FII selling"], ["s", "Some FII selling"], ["n", "No meaningful FII deals"], ["b", "Some FII buying"], ["hb", "Heavy FII buying"]]} />
                      <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontFamily: mono, fontSize: 11, color: C.mut, cursor: "pointer" }}>
                        <input type="checkbox" checked={repeatSeller} onChange={(e) => setRepeatSeller(e.target.checked)} />
                        same entity selling repeatedly
                      </label>
                    </Stream>
                    <Stream tag="S4" weight={15} title="Delivery % on down days" fill={streamFill("S4")}
                      source="High delivery on declines = real ownership leaving." score={streams[3].score}>
                      <Num value={delivBase} onChange={setDelivBase} ph="base" suffix="% 20D" testid="delivBase" />
                      <Num value={delivDown} onChange={setDelivDown} ph="down-days" w={92} suffix="% recent" testid="delivDown" />
                    </Stream>
                    <Stream tag="S5" weight={10} title="MF monthly portfolios" fill={streamFill("S5")}
                      source="Across large fund houses' latest monthly disclosures, the net action in this stock." score={streams[4].score}>
                      <Sel value={mf} onChange={setMf} testid="mf"
                        opts={[["mt", "Many houses trimming"], ["st", "Some trimming"], ["n", "No clear change"], ["sa", "Some adding"], ["ma", "Many houses adding"]]} />
                    </Stream>
                    <Stream tag="S6" weight={10} title="Stock F&O positioning" fill={streamFill("S6")}
                      source="Price vs open interest in stock futures (F&O names only)." score={streams[5].score}>
                      <Sel value={fo} onChange={setFo} testid="fo"
                        opts={[["sb", "Price ↓ OI ↑ — short buildup"], ["lu", "Price ↓ OI ↓ — long unwinding"], ["n", "No clear pattern"], ["sc", "Price ↑ OI ↓ — short covering"], ["lb", "Price ↑ OI ↑ — long buildup"]]} />
                    </Stream>
                  </>
                ) : (
                  <>
                    <Stream tag="S1" weight={35} title="NSDL fortnightly FPI flows" fill={streamFill("S1")}
                      source="Direction and how many consecutive fortnights it has run." score={streams[0].score}>
                      <Sel value={ftDir} onChange={setFtDir} testid="ftDir" opts={[["out", "Outflow streak"], ["in", "Inflow streak"]]} />
                      <Num value={ftN} onChange={setFtN} ph="count" suffix="fortnights" testid="ftN" />
                    </Stream>
                    <Stream tag="S2" weight={25} title="AUC change vs index change" fill={streamFill("S2")}
                      source="Sector AUC % change minus sector index % change — the gap is active buying/selling, not mark-to-market." score={streams[1].score}>
                      <Num value={auc} onChange={setAuc} ph="AUC" suffix="% chg" testid="auc" />
                      <Num value={idx} onChange={setIdx} ph="index" suffix="% chg" testid="idx" />
                    </Stream>
                    <Stream tag="S3" weight={25} title="Constituent breadth" fill={streamFill("S3")}
                      source="Of the sector's top 10 stocks, how many saw FII stake fall in the latest quarter (0–10)." score={streams[2].score}>
                      <Num value={breadth} onChange={setBreadth} ph="0–10" suffix="of 10 fell" testid="breadth" />
                    </Stream>
                    <Stream tag="S4" weight={15} title="Relative strength vs Nifty, 3M" fill={streamFill("S4")}
                      source="Sector index 3-month return minus Nifty return, in percentage points." score={streams[3].score}>
                      <Num value={rs} onChange={setRs} ph="±pp" suffix="pp vs Nifty" testid="rs" />
                    </Stream>
                  </>
                )}
              </div>
            </div>

            <div style={{ background: C.panelSoft, border: `1px solid ${C.line}`, borderRadius: 4, marginTop: 16, padding: 16 }}>
              <Label>Reading the ledger</Label>
              <div style={{ fontSize: 12, color: C.mut, lineHeight: 1.7, marginTop: 8 }}>
                A high-conviction outflow pattern is several streams agreeing: falling FII stake across
                consecutive quarters, recurring FPI sellers on the deal lists, elevated delivery on down
                days, and MF trimming. One stream alone — especially a daily flow headline — is noise.
                AUTO-FILL pulls what NIDP holds and names what it cannot; anything left blank you can
                still enter by hand. Saved trackers stay in this browser. Analytics only — not advice.
              </div>
            </div>
          </>
        ) : (
          <>
            <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 4, marginTop: 16, padding: 16 }}>
              <Label>Contribution ledger</Label>
              <div style={{ overflowX: "auto", marginTop: 8 }}>
                <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 560 }}>
                  <thead>
                    <tr>
                      <th style={th}>ID</th><th style={th}>STREAM</th><th style={th}>ENTERED EVIDENCE</th>
                      <th style={{ ...th, textAlign: "right" }}>SCORE</th>
                      <th style={{ ...th, textAlign: "right" }}>WT</th>
                      <th style={{ ...th, textAlign: "right" }}>W×S</th>
                      <th style={{ ...th, textAlign: "right" }}>SHARE</th>
                    </tr>
                  </thead>
                  <tbody>
                    {contrib.map((r) => (
                      <tr key={r.tag}>
                        <td style={{ ...td, color: C.amber }}>{r.tag}</td>
                        <td style={{ ...td, color: C.text, fontFamily: sans, fontSize: 12 }}>{r.title}</td>
                        <td style={{ ...td, color: C.mut }}>{r.detail}</td>
                        <td style={{ ...td, textAlign: "right", color: r.score === null ? C.mut : r.score <= -20 ? C.sell : r.score >= 20 ? C.buy : C.neutral }}>{fmt(r.score)}</td>
                        <td style={{ ...td, textAlign: "right", color: C.mut }}>{r.w}</td>
                        <td style={{ ...td, textAlign: "right", color: r.ws === null ? C.mut : r.ws < 0 ? C.sell : C.buy }}>{r.ws === null ? "—" : fmt(r.ws)}</td>
                        <td style={{ ...td, textAlign: "right", color: C.mut }}>{r.share === null ? "—" : `${r.share}%`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 4, marginTop: 16, padding: 16 }}>
              <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
                <Label>Snapshot history{name.trim() ? ` — ${name.trim().toUpperCase()}` : ""}</Label>
                <span style={{ fontFamily: mono, fontSize: 10, color: C.mut }}>{history.length} snapshot{history.length === 1 ? "" : "s"} · last 24 kept</span>
              </div>
              {history.length === 0 ? (
                <div style={{ color: C.mut, fontSize: 12, marginTop: 8 }}>
                  No snapshots yet for this name. Fill the streams and press SAVE SNAPSHOT — updating the
                  same name each quarter builds the verdict trend here.
                </div>
              ) : (
                <>
                  <div style={{ marginTop: 12 }}><Spark points={history} /></div>
                  <div style={{ marginTop: 8 }}>
                    {[...history].reverse().map((h, i) => (
                      <div key={i} style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8, flexWrap: "wrap", borderTop: `1px solid ${C.line}`, paddingTop: 5 }}>
                        <span style={{ fontFamily: mono, fontSize: 11, color: C.mut }}>
                          {new Date(h.ts).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}
                        </span>
                        <span style={{ fontFamily: mono, fontSize: 11, color: h.score <= -20 ? C.sell : h.score >= 20 ? C.buy : C.neutral }}>{fmt(h.score)} {h.label}</span>
                        <span style={{ fontFamily: mono, fontSize: 11, color: C.mut }}>conv {h.conviction}%</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>

            <div style={{ background: C.panelSoft, border: `1px solid ${C.line}`, borderRadius: 4, marginTop: 16, padding: 16 }}>
              <Label>Method — {mode} streams</Label>
              <div style={{ marginTop: 8 }}>
                {methods.map(([t, body]) => (
                  <div key={t} style={{ marginTop: 12 }}>
                    <div style={{ fontFamily: mono, fontSize: 11, color: C.amber }}>{t}</div>
                    <div style={{ fontSize: 12, color: C.mut, lineHeight: 1.65 }}>{body}</div>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 16 }}><Label>Method — composite</Label></div>
              <div style={{ marginTop: 8 }}>
                {METHOD_COMPOSITE.map(([t, body]) => (
                  <div key={t} style={{ marginTop: 12 }}>
                    <div style={{ fontFamily: mono, fontSize: 11, color: C.amber }}>{t}</div>
                    <div style={{ fontSize: 12, color: C.mut, lineHeight: 1.65 }}>{body}</div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
