/**
 * Research → Move odds. Built to docs/ai_research/designs/Nivesh Move Odds (standalone).html (approved 2026-09-16), the
 * owner's v7 design of 2026-09-18 (ratings, cap/ratio/event filters, a stock view) and its v2 refinement the same day
 * (docs/Move Odds v2 standalone (1).html: a hero, the four questions folded, a five-column table led by the larger
 * estimate, a leaner history).
 *
 * Rules this screen keeps (ten-percent-days-3 spec D1–D3, C4, C7, UX-1; owner decisions 2026-09-18):
 *   · Only rendered for accounts with features.move_odds; the API independently answers 403 to everyone else, and a
 *     403 mid-session clears every cached estimate before the "not enabled" state renders.
 *   · Estimates, not calls: the full scored list sorted by estimate, no rank numbers, neutral colours for both
 *     directions, the base rate beside every number (fixed 0–100% track with a base-rate tick). v2 leads each row with
 *     the larger estimate and names its side; the hero names three stocks by stated rules over the full list — the
 *     owner's design, noted in the v7 report as closer to a short list than D1 allowed.
 *   · The disclaimer sits above the numbers and never collapses.
 *   · Every percentage is the published value at one decimal; nothing is computed from the clock here — the API
 *     decides whether estimates exist for the next session.
 *   · Quality sits BESIDE movement and is never combined with it (PRD: movement probability is not investment
 *     quality). The stock view is the copilot chat's stock card, completely unchanged — its "Worth buying now?"
 *     BUY/HOLD/SELL included (owner, 2026-09-18 12:17 IST, reversing the 11:20 "scores only" choice); D2 still applies
 *     to everything outside that card. Below it the view keeps the four estimates, inputs, events, the five checks and
 *     the paper trade. If the card cannot be loaded, the v7 quality block from the profile stands in.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import {
  MOVE_HEADS, fetchDiagnostics, fetchHistory, fetchLive, fetchProfile, fetchStockCard, moveOddsService,
  type DiagnosticsResult, type HistoryResult, type LiveConditions, type MoveHistorySession, type LivePayload, type LiveQuote, type PaperTrade, type MoveBand, type MoveFinal, type MoveHead, type MoveLatestResult, type MoveRow, type MoveStockResult,
  type MoveProfile, type MoveQuality, type MoveSectorRating, type ProfileResult, type StockCardResult,
} from "@/services/adapters/moveOdds.adapter";
import { ChatWidget } from "@/components/chat/ChatWidget";
import { EventBar, FilterBar, RatioPanel } from "./MoveOddsFilters";
import { SHORT, answers, checkConds, condActive, fmtRatio, fundBand, gradeTone, peerMedian, qualityLabel, ratioIndex, techBand, valueOf, type Cap, type Cond } from "./moveOddsProfile";
import "./moveOdds.css";

const PAGE = 50;
const LIVE_REFRESH_MS = 60_000;
const CHECKS: Array<{ key: keyof Pick<NonNullable<LiveConditions["latest"]>, "above_prev_close" | "above_opening_range" | "above_vwap" | "room_to_level" | "volume_pace">; label: string }> = [
  { key: "above_prev_close", label: "Close above the previous close" },
  { key: "above_opening_range", label: "Close above the first hour's high" },
  { key: "above_vwap", label: "Close above the session VWAP" },
  { key: "room_to_level", label: "The +5% level not yet reached" },
  { key: "volume_pace", label: "Volume ahead of the 20-session pace" },
];

const META: Record<MoveHead, { label: string; long: string; opp: MoveHead; oppLabel: string }> = {
  p_up5_1d:    { label: "High ≥ +5%",  long: "session high at least 5% above the previous close",  opp: "p_down5_1d",  oppLabel: "Low ≤ −5%" },
  p_down5_1d:  { label: "Low ≤ −5%",   long: "session low at least 5% below the previous close",   opp: "p_up5_1d",    oppLabel: "High ≥ +5%" },
  p_up10_1d:   { label: "High ≥ +10%", long: "session high at least 10% above the previous close", opp: "p_down10_1d", oppLabel: "Low ≤ −10%" },
  p_down10_1d: { label: "Low ≤ −10%",  long: "session low at least 10% below the previous close",  opp: "p_up10_1d",   oppLabel: "High ≥ +10%" },
};

// PRD v6: movement and direction are different questions, so the tabs are move SIZES and both directions show as
// equals. A row's "larger" figure is just the bigger of two published estimates — it is not a combined probability and
// no model produces it; the column says so.
const SIZES = [
  { key: "5", label: "5% move", up: "p_up5_1d", down: "p_down5_1d", upLabel: "Up ≥ +5%", downLabel: "Down ≤ −5%" },
  { key: "10", label: "10% move", up: "p_up10_1d", down: "p_down10_1d", upLabel: "Up ≥ +10%", downLabel: "Down ≤ −10%" },
] as const;
type SizeKey = (typeof SIZES)[number]["key"];

// The one place the direction reading is defined. It compares two estimates; it is not a forecast, and the direction
// model does not exist yet (PRD Phase 3). "two-way" is the honest answer for most stocks: in the 2025 test the top
// decile by +5% score touched +5% on 19% of days and −5% on 14.7%.
export const TWO_WAY_RATIO = 0.6;
export function directionReading(up: number | null | undefined, down: number | null | undefined):
  { key: "two-way" | "up-leaning" | "down-leaning" | "unknown"; label: string } {
  if (up == null || down == null || !isFinite(up) || !isFinite(down)) return { key: "unknown", label: "—" };
  const larger = Math.max(up, down), smaller = Math.min(up, down);
  if (larger <= 0) return { key: "unknown", label: "—" };
  if (smaller >= TWO_WAY_RATIO * larger) return { key: "two-way", label: "two-way" };
  return up > down ? { key: "up-leaning", label: "up-leaning" } : { key: "down-leaning", label: "down-leaning" };
}

const INPUTS: Array<{ key: string; label: string; fmt: (v: number) => string; note?: string }> = [
  { key: "close_change_pct", label: "Close vs previous close", fmt: (v) => signed(v, "%") },
  { key: "day_range_pct", label: "Day's range", fmt: (v) => `${v.toFixed(1)}%`, note: "high − low" },
  { key: "volume_vs_20d_median", label: "Volume vs 20-session median", fmt: (v) => `${v.toFixed(1)}×` },
  { key: "delivery_pct", label: "Delivery", fmt: (v) => `${v.toFixed(1)}%`, note: "published a day late" },
  { key: "change_5_sessions_pct", label: "Change over 5 sessions", fmt: (v) => signed(v, "%") },
  { key: "atr14_pct", label: "Average true range, 14 sessions", fmt: (v) => `${v.toFixed(1)}%`, note: "% of close" },
];

export const DISCLAIMER =
  "This analysis is for informational purposes only and does not constitute investment advice. Past performance is not " +
  "indicative of future results. Please consult a SEBI-registered investment advisor before making investment decisions. " +
  "Mutual fund investments are subject to market risks.";

export function pct(p: number | null | undefined): string {
  if (p == null) return "—";
  const v = p * 100;
  return v < 0.1 ? "<0.1%" : `${v.toFixed(1)}%`;
}
function spoken(p: number | null | undefined): string {
  if (p == null) return "not scored";
  const v = p * 100;
  return v < 0.1 ? "under 0.1 percent" : `${v.toFixed(1)} percent`;
}
function money(v: number | null | undefined): string {
  return v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function signed(v: number, unit: string): string {
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}${unit}`;
}
// Fixed formats, not toLocale*: browsers disagree on short month names ("Sep" vs "Sept").
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (isNaN(dt.getTime())) return iso;
  return `${DOW[dt.getUTCDay()]} ${d} ${MON[m - 1]}`;
}
function istTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (isNaN(t)) return iso;
  const ist = new Date(t + 330 * 60_000);                       // IST = UTC+05:30, no DST
  const hh = String(ist.getUTCHours()).padStart(2, "0"), mm = String(ist.getUTCMinutes()).padStart(2, "0");
  return `${ist.getUTCDate()} ${MON[ist.getUTCMonth()]}, ${hh}:${mm}`;
}
function bandLabel(b: MoveBand): string {
  const lo = Math.round(b.band_lo * 100), hi = Math.round(b.band_hi * 100);
  return hi >= 100 ? `${lo}% +` : `${lo}–${hi}%`;
}

type Loaded = Partial<Record<MoveHead, MoveLatestResult>>;
type SortKey = "est" | "sym" | "rating" | "other";
type Sort = { key: SortKey; dir: "asc" | "desc" };
const DEFAULT_PICKED = ["mcap", "roce", "pe"];

// v2 design (owner, 2026-09-18): each row leads with the LARGER of its two estimates and names its side; the smaller sits
// under "Other way". The larger figure is not a combined probability — no model produces one — and the row says which
// side it is. Colour stays ink: direction is a reading of two estimates, never a forecast.
function sides(r: MoveRow): { up: boolean; hi: number; lo: number | null } {
  const up = r.p_opposite == null || r.p >= r.p_opposite;
  return { up, hi: up ? r.p : (r.p_opposite as number), lo: up ? r.p_opposite : r.p };
}
function times(p: number, base: number | null | undefined): string {
  if (!base) return "";
  const x = p / base;
  return `${x.toFixed(x >= 10 ? 0 : 1)}× base`;
}
function oneIn(p: number): string {
  return p > 0 ? `about 1 session in ${Math.max(2, Math.round(1 / p))}` : "";
}

/** Nulls always sort last, whichever the direction. */
function cmpNum(a: number | null | undefined, b: number | null | undefined, dir: "asc" | "desc"): number {
  const an = a == null || !isFinite(a), bn = b == null || !isFinite(b);
  if (an && bn) return 0;
  if (an) return 1;
  if (bn) return -1;
  return dir === "desc" ? (b as number) - (a as number) : (a as number) - (b as number);
}

export default function MoveOddsScreen() {
  const [size, setSize] = useState<SizeKey>("5");
  const [histDir, setHistDir] = useState<"up" | "down">("up");
  const [results, setResults] = useState<Loaded>({});
  const [q, setQ] = useState("");
  const [evOnly, setEvOnly] = useState(false);
  const [sort, setSort] = useState<Sort>({ key: "est", dir: "desc" });
  const [order, setOrder] = useState<"table" | "events">("table");
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [stocks, setStocks] = useState<Record<string, MoveStockResult | "loading">>({});
  const [cards, setCards] = useState<Record<string, StockCardResult | "loading">>({});
  const [noAccess, setNoAccess] = useState(false);
  const [reload, setReload] = useState(0);
  const [live, setLive] = useState<{ at: string; source: string; delay: string; record: LivePayload["signal_record"]; quotes: Record<string, LiveQuote> } | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [diag, setDiag] = useState<DiagnosticsResult | null>(null);
  const [diagReload, setDiagReload] = useState(0);
  const [view, setView] = useState<"estimates" | "history">("estimates");
  const [hist, setHist] = useState<HistoryResult | null>(null);
  const [histSession, setHistSession] = useState<string | null>(null);
  const [histSort, setHistSort] = useState<{ key: "est" | "sym" | "rating" | "move"; dir: "asc" | "desc" }>({ key: "est", dir: "desc" });
  const [honesty, setHonesty] = useState(false);
  const [profile, setProfile] = useState<ProfileResult | null>(null);
  const [profileReload, setProfileReload] = useState(0);
  const [cap, setCap] = useState<Cap>("All");
  const [picked, setPicked] = useState<string[]>([]);
  const [conds, setConds] = useState<Record<string, Cond>>({});
  const [panelOpen, setPanelOpen] = useState(false);
  const [evtOpen, setEvtOpen] = useState(false);
  const [evtCat, setEvtCat] = useState("All");
  const [evtSort, setEvtSort] = useState<"material" | "latest">("material");
  const tabRefs = useRef<Partial<Record<SizeKey, HTMLButtonElement | null>>>({});
  const returnFocus = useRef<HTMLElement | null>(null);

  const sz = SIZES.find((x) => x.key === size) ?? SIZES[0];
  const upHead = sz.up as MoveHead;
  const downHead = sz.down as MoveHead;
  const head: MoveHead = view === "history" ? ((histDir === "up" ? sz.up : sz.down) as MoveHead) : upHead;

  const denyAll = useCallback(() => {          // 403 anywhere: drop every cached estimate before rendering the state
    setResults({}); setStocks({}); setCards({}); setOpen(null); setProfile(null); setNoAccess(true);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setResults({});
    Promise.all(MOVE_HEADS.map((h) => moveOddsService.latest(h).then((r) => [h, r] as const))).then((pairs) => {
      if (cancelled) return;
      if (pairs.some(([, r]) => r.kind === "no_access")) { denyAll(); return; }
      setNoAccess(false);
      setResults(Object.fromEntries(pairs) as Loaded);
    });
    return () => { cancelled = true; };
  }, [reload, denyAll]);

  // The profile (ratings, ratios, event categories) loads alongside the estimates and never holds them up: if it fails,
  // the estimates still render and the rating cells say why they are empty.
  useEffect(() => {
    let cancelled = false;
    setProfile(null);
    fetchProfile().then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      setProfile(r);
      if (r.kind === "ok") setPicked((cur) => (cur.length ? cur : DEFAULT_PICKED).filter((k) => r.data.ratio_keys.includes(k)));
    });
    return () => { cancelled = true; };
  }, [reload, profileReload, denyAll]);

  // History is fetched only when that view is opened, and again whenever the head changes: the ranking it lists is
  // per head, so p_up5_1d's past top 20 is a different list from p_down10_1d's.
  useEffect(() => {
    if (view !== "history") return;
    let cancelled = false;
    setHist(null);
    fetchHistory(head).then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      setHist(r);
      if (r.kind === "ok") setHistSession((cur) => (cur && r.data.sessions.some((x) => x.target_session === cur) ? cur : r.data.sessions[0]?.target_session ?? null));
    });
    return () => { cancelled = true; };
  }, [view, head, denyAll]);

  useEffect(() => {
    let cancelled = false;
    setDiag(null);
    fetchDiagnostics().then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      setDiag(r);
    });
    return () => { cancelled = true; };
  }, [diagReload, denyAll]);

  useEffect(() => {
    if (!open || stocks[open]) return;
    setStocks((s) => ({ ...s, [open]: "loading" }));
    moveOddsService.stock(open).then((r) => {
      if (r.kind === "no_access") { denyAll(); return; }
      setStocks((s) => ({ ...s, [open]: r }));
    });
  }, [open, stocks, denyAll]);

  // The copilot's stock card for the open stock (owner, 2026-09-18: the pop-up is that card, unchanged). Fetched once
  // per stock per visit; a failure leaves the move-odds sections untouched.
  useEffect(() => {
    if (!open || cards[open]) return;
    setCards((c) => ({ ...c, [open]: "loading" }));
    fetchStockCard(open).then((r) => {
      if (r.kind === "no_access") { denyAll(); return; }
      setCards((c) => ({ ...c, [open]: r }));
    });
  }, [open, cards, denyAll]);

  const current = results[upHead];
  const final: MoveFinal | null = current?.kind === "final" ? current.data : null;
  const downFinal: MoveFinal | null = results[downHead]?.kind === "final" ? (results[downHead] as { data: MoveFinal }).data : null;
  const loading = !noAccess && current === undefined;
  const prof: MoveProfile | null = profile?.kind === "ok" ? profile.data : null;
  const idx = useMemo(() => (prof ? ratioIndex(prof) : {}), [prof]);
  const profileOff = profile === null ? null
    : profile.kind === "ok" ? null
    : profile.kind === "not_published" ? "Ratings, ratios and event categories are not published for this session yet."
    : `Ratings, ratios and event categories could not be loaded (${profile.kind === "error" ? profile.message : "not enabled"}). The estimates are unaffected.`;

  // Filters that need the profile. "missing": the stock has no value for an active condition — excluded, and counted.
  const profileFilter = useCallback((sym: string): "pass" | "fail" | "missing" => {
    if (!prof) return "pass";
    const pr = prof.rows[sym];
    if (cap !== "All" && pr?.cap !== cap) return "fail";
    if (evtCat !== "All" && !pr?.events.categories.includes(evtCat)) return "fail";
    return checkConds(prof, idx, sym, conds);
  }, [prof, idx, cap, evtCat, conds]);

  // `p` is the up estimate and `p_opposite` the down one for the selected size; the default sort key is the larger of
  // the two, which is a comparison of two published numbers, not a combined probability.
  const larger = (r: MoveRow) => Math.max(r.p, r.p_opposite ?? Number.NEGATIVE_INFINITY);
  const term = q.trim().toLowerCase();
  const matches = useCallback((sym: string, name: string | null, sector: string | null) =>
    !term || sym.toLowerCase().includes(term) || (name ?? "").toLowerCase().includes(term) || (sector ?? "").toLowerCase().includes(term), [term]);

  const { rows, missingExcluded } = useMemo(() => {
    if (!final) return { rows: [] as MoveRow[], missingExcluded: 0 };
    let missing = 0;
    const list = final.rows.filter((r) => {
      if (evOnly && r.events_on_record === 0) return false;
      if (!matches(r.symbol, r.company_name, r.sector)) return false;
      const k = profileFilter(r.symbol);
      if (k === "missing") { missing++; return false; }
      return k === "pass";
    });
    const pr = (s: string) => prof?.rows[s];
    const evKey = (s: string) => { const e = pr(s)?.events; if (!e || e.n === 0) return null; return evtSort === "material" ? e.material : (e.latest ? Date.parse(e.latest) : null); };
    const val = (r: MoveRow): number | null => {
      switch (sort.key) {
        case "other": return sides(r).lo;
        case "rating": return pr(r.symbol)?.quality?.score ?? null;
        default: return larger(r);
      }
    };
    const sorted = [...list].sort((a, b) => {
      if (order === "events") return cmpNum(evKey(a.symbol), evKey(b.symbol), "desc") || larger(b) - larger(a) || a.symbol.localeCompare(b.symbol);
      if (sort.key === "sym") return sort.dir === "asc" ? a.symbol.localeCompare(b.symbol) : b.symbol.localeCompare(a.symbol);
      return cmpNum(val(a), val(b), sort.dir) || larger(b) - larger(a) || a.symbol.localeCompare(b.symbol);
    });
    return { rows: sorted, missingExcluded: missing };
  }, [final, evOnly, matches, profileFilter, prof, sort, order, evtSort]);

  const capCounts = useMemo(() => {
    const out: Partial<Record<Cap, number>> = {};
    if (!final || !prof) return out;
    for (const r of final.rows) { const c = prof.rows[r.symbol]?.cap; if (c) out[c] = (out[c] ?? 0) + 1; }
    return out;
  }, [final, prof]);
  const evtCounts = useMemo(() => {
    const out: Record<string, number> = { __any: 0 };
    if (!final || !prof) return out;
    for (const r of final.rows) {
      const e = prof.rows[r.symbol]?.events;
      if (!e || e.n === 0) continue;
      out.__any++;
      for (const c of e.categories) out[c] = (out[c] ?? 0) + 1;
    }
    return out;
  }, [final, prof]);

  // Hero (v2 design): three stocks named by a stated rule over the full published list, never by the filters — the
  // highest single estimate, the highest smaller-of-the-two, and the most material filings. Facts with their base rates.
  const hero = useMemo(() => {
    if (!final || !final.rows.length) return null;
    const byLarger = [...final.rows].sort((a, b) => larger(b) - larger(a) || a.symbol.localeCompare(b.symbol));
    const twoSided = final.rows.filter((r) => r.p_opposite != null);
    const both = twoSided.length ? [...twoSided].sort((a, b) => sides(b).lo! - sides(a).lo! || a.symbol.localeCompare(b.symbol))[0] : null;
    const withFilings = prof ? final.rows.filter((r) => (prof.rows[r.symbol]?.events.material ?? 0) > 0) : [];
    const filings = withFilings.length ? [...withFilings].sort((a, b) => {
      const ea = prof!.rows[a.symbol].events, eb = prof!.rows[b.symbol].events;
      return eb.material - ea.material || eb.n - ea.n || larger(b) - larger(a) || a.symbol.localeCompare(b.symbol);
    })[0] : null;
    return { top: byLarger[0], both, filings };
  }, [final, prof]);

  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const safePage = Math.min(page, pages - 1);
  const slice = rows.slice(safePage * PAGE, safePage * PAGE + PAGE);
  const sliceKey = slice.map((r) => r.symbol).join(",");

  // Live prices for the rows on screen: fetched on every change of the visible slice and every 60 s while the tab is
  // visible. Only the symbols shown are requested, and nothing is kept from an earlier session.
  useEffect(() => {
    if (!final || !sliceKey) return;
    let cancelled = false;
    const symbols = sliceKey.split(",");
    const pull = async () => {
      if (document.visibilityState !== "visible") return;
      const r = await fetchLive(symbols);
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      if (r.kind === "error") { setLiveError(r.message); return; }
      setLiveError(null);
      setLive((prev) => ({ at: r.data.fetched_at, source: r.data.source, delay: r.data.delay_note ?? "", record: r.data.signal_record,
                           quotes: { ...(prev?.quotes ?? {}), ...Object.fromEntries(r.data.quotes.map((q) => [q.symbol, q])) } }));
    };
    void pull();
    const id = window.setInterval(() => { void pull(); }, LIVE_REFRESH_MS);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [final, sliceKey, denyAll]);

  const onTabKey = (e: React.KeyboardEvent, k: SizeKey) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const i = (SIZES.findIndex((x) => x.key === k) + (e.key === "ArrowRight" ? 1 : -1) + SIZES.length) % SIZES.length;
    const next = SIZES[i].key;
    setSize(next); setPage(0); tabRefs.current[next]?.focus();
  };
  const toggleSort = (key: SortKey) => {
    setOrder("table");
    setSort((s) => (s.key === key && order === "table" ? { key, dir: s.dir === "desc" ? "asc" : "desc" } : { key, dir: key === "sym" ? "asc" : "desc" }));
    setPage(0);
  };
  const ariaSort = (key: SortKey) => (order === "table" && sort.key === key ? (sort.dir === "asc" ? "ascending" : "descending") : undefined);
  const arrow = (key: SortKey) => (order === "table" && sort.key === key ? (sort.dir === "desc" ? " ↓" : " ↑") : "");
  const openStock = (sym: string, from: HTMLElement | null) => { returnFocus.current = from; setOpen(sym); };
  const closeStock = () => { setOpen(null); window.setTimeout(() => returnFocus.current?.focus(), 0); };
  const setCond = (key: string, c: Cond) => { setConds((m) => ({ ...m, [key]: c })); setPage(0); };
  const removePicked = (key: string) => { setPicked((p) => p.filter((k) => k !== key)); setConds((m) => { const n = { ...m }; delete n[key]; return n; }); setPage(0); };
  const togglePicked = (key: string) => { if (picked.includes(key)) removePicked(key); else setPicked((p) => [...p, key]); };
  const canClear = cap !== "All" || evtCat !== "All" || Object.values(conds).some(condActive) || !!q || evOnly;
  const clearAll = () => { setCap("All"); setEvtCat("All"); setConds({}); setQ(""); setEvOnly(false); setOrder("table"); setPage(0); };

  if (noAccess) {
    return (
      <div className="mo" data-testid="move-odds-screen">
        <div className="mo-titlerow"><h2 className="nv-serif mo-title">Move odds</h2></div>
        <div className="mo-state" role="status" data-testid="mo-state-no_access">
          <h3 className="nv-serif">Move odds is not enabled for your account</h3>
          <p>It is open to invited accounts during the research preview. The filings Feed and Alerts are unaffected.</p>
        </div>
      </div>
    );
  }

  const run = final?.run;
  const openRow = open && final ? final.rows.find((r) => r.symbol === open) ?? null : null;
  const evtLabel = (k: string) => prof?.event_categories.find((e) => e.key === k)?.label ?? k;
  const estimatesFor = (sym: string) => Object.fromEntries(MOVE_HEADS.map((h) => {
    const r = results[h];
    return [h, r?.kind === "final" ? r.data.rows.find((x) => x.symbol === sym)?.p : undefined];
  })) as Partial<Record<MoveHead, number>>;
  const baseRates = Object.fromEntries(MOVE_HEADS.map((h) => { const r = results[h]; return [h, r?.kind === "final" ? r.data.base_rate : undefined]; })) as Partial<Record<MoveHead, number>>;
  const captionOrder = order === "events"
    ? `Stocks ordered by ${evtSort === "material" ? "material events (classified positive, negative or mixed)" : "their latest event"}, then the larger of the two estimates`
    : sort.key === "est" ? "Sorted by the larger of the two estimates" : `Sorted by ${SORT_NAME[sort.key]}`;

  return (
    <div className="mo" data-testid="move-odds-screen">
      <header className="mo-head">
        <div className="mo-head-l">
          <span className="mo-eyebrow">NSE · next session · estimate, not a forecast</span>
          <h2 className="nv-serif mo-title">Move odds</h2>
          <p className="mo-sub">Estimated chance that a stock&apos;s price touches a large move during the next session, for about 1,000 NSE stocks.</p>
        </div>
        <div className="mo-head-r">
          {final && <span className="mo-chip" data-testid="mo-status-final"><span className="mo-dot" />Final · NSE closing file</span>}
          {run && (
            <div className="mo-prov" data-testid="mo-provenance">
              <span>From close of <b>{day(run.data_as_of)}</b> · for session <b>{day(run.target_session)}</b>{run.skipped_holidays.length ? ` (after ${run.skipped_holidays.map(day).join(", ")}: NSE holiday)` : ""}</span>
              <span>Frozen <b>{istTime(run.frozen_at)} IST</b> · model <b>{run.model} · {run.git_sha}</b></span>
              <span><b>{run.scored.toLocaleString("en-IN")}</b> of {run.universe_size.toLocaleString("en-IN")} stocks scored</span>
            </div>
          )}
        </div>
      </header>

      <div className="mo-disc" role="note" data-testid="mo-disclaimer"><b>DISCLAIMER</b>{DISCLAIMER}</div>

      {final && hero && (() => {
        const base = (up: boolean) => (up ? final.base_rate : downFinal?.base_rate);
        const t = sides(hero.top);
        const tb = hero.both ? sides(hero.both) : null;
        const fe = hero.filings && prof ? prof.rows[hero.filings.symbol].events : null;
        return (
          <section className="mo-hero" aria-label="This session at a glance" data-testid="mo-hero">
            <div className="mo-hero-l">
              <p className="nv-serif mo-hero-lead" data-testid="mo-hero-lead">
                {hero.top.symbol} carries the highest estimated chance of a {sz.key}% move on {day(final.run.target_session)} — {pct(t.hi)} on the {t.up ? "upside" : "downside"}
                {base(t.up) ? `, roughly ${Math.round(t.hi / (base(t.up) as number))}× the base rate` : ""}.
              </p>
              <p className="mo-hero-sub">Direction is not predicted, cost and risk are not modelled, and no entry setup has passed its out-of-sample test. Read these as odds of a touch, nothing more.</p>
              <button type="button" className="mo-honesty" aria-expanded={honesty} aria-controls="mo-answers" onClick={() => setHonesty((h) => !h)} data-testid="mo-honesty-toggle">
                {honesty ? "Hide" : "What this does and doesn't tell you"}<span aria-hidden="true">{honesty ? " ▴" : " ▾"}</span>
              </button>
            </div>
            <div className="mo-hero-cards">
              <button type="button" className="mo-hcard mint" aria-haspopup="dialog" onClick={(e) => openStock(hero.top.symbol, e.currentTarget)} data-testid="mo-hero-odds">
                <span className="mo-hcard-l">
                  <span className="mo-hcard-eyebrow">Highest odds</span>
                  <span className="mo-hcard-id"><span className="mo-sym">{hero.top.symbol}</span><span className="mo-co">{hero.top.company_name ?? ""}</span></span>
                  <span className="mo-hcard-sub">{t.up ? "upside" : "downside"} · {times(t.hi, base(t.up))} · {oneIn(t.hi)}</span>
                </span>
                <span className="mo-hcard-v">{pct(t.hi)}</span>
              </button>
              {hero.both && tb && (
                <button type="button" className="mo-hcard amber" aria-haspopup="dialog" onClick={(e) => openStock(hero.both!.symbol, e.currentTarget)} data-testid="mo-hero-both">
                  <span className="mo-hcard-l">
                    <span className="mo-hcard-eyebrow">Cuts both ways</span>
                    <span className="mo-hcard-id"><span className="mo-sym">{hero.both.symbol}</span><span className="mo-co">{hero.both.company_name ?? ""}</span></span>
                    <span className="mo-hcard-sub">up {times(hero.both.p, final.base_rate)} · down {times(hero.both.p_opposite as number, downFinal?.base_rate)}</span>
                  </span>
                  <span className="mo-hcard-v">{pct(hero.both.p)} / {pct(hero.both.p_opposite)}</span>
                </button>
              )}
              {hero.filings && fe && (
                <button type="button" className="mo-hcard indigo" aria-haspopup="dialog" onClick={(e) => openStock(hero.filings!.symbol, e.currentTarget)} data-testid="mo-hero-filings">
                  <span className="mo-hcard-l">
                    <span className="mo-hcard-eyebrow">Most material filings</span>
                    <span className="mo-hcard-id"><span className="mo-sym">{hero.filings.symbol}</span><span className="mo-co">{hero.filings.company_name ?? ""}</span></span>
                    <span className="mo-hcard-sub">{fe.categories.map(evtLabel).join(" · ")} · latest {day(fe.latest)}</span>
                  </span>
                  <span className="mo-hcard-v">{fe.material} material</span>
                </button>
              )}
            </div>
          </section>
        );
      })()}

      {honesty && (
      <section id="mo-answers" className="mo-answers" aria-labelledby="mo-answers-h" data-testid="mo-answers">
        <h3 id="mo-answers-h" className="sr-only">What these numbers answer</h3>
        <ol className="mo-answers-list">
          <li data-testid="mo-answer-1">
            <span className="mo-q">Is it likely to move 5% or 10%?</span>
            <span className="mo-a yes">Yes — that is what the estimate is</span>
            <span className="mo-mini">Measured out of sample on Jan–Aug 2025. How each band actually turned out is in the panel beside the table.</span>
          </li>
          <li data-testid="mo-answer-2">
            <span className="mo-q">Up or down?</span>
            <span className="mo-a warn">Not predicted</span>
            <span className="mo-mini">Both directions are shown together because a stock likely to rise sharply is usually also likely to fall sharply. In that test the highest-scoring tenth touched +5% on 19% of days and −5% on 14.7%.</span>
          </li>
          <li data-testid="mo-answer-3">
            <span className="mo-q">Is the return worth it after costs and risk?</span>
            <span className="mo-a warn">Not modelled yet</span>
            <span className="mo-mini">Buying that highest-scoring tenth at the open and selling at the close averaged −0.23% before costs.</span>
          </li>
          <li data-testid="mo-answer-4">
            <span className="mo-q">Has any of this shown an edge out of sample?</span>
            <span className="mo-a no">No</span>
            <span className="mo-mini">Four entry setups and five mean-reversion variants were tested with their rules fixed in advance; none passed. Research diagnostics are at the foot of this page.</span>
          </li>
        </ol>
      </section>
      )}

      <div className="mo-viewrow mo-controlrow">
        <div className="mo-viewtoggle" role="group" aria-label="View">
          {(["estimates", "history"] as const).map((v) => (
            <button key={v} type="button" className="mo-viewbtn" aria-pressed={view === v} data-testid={`mo-view-${v}`} onClick={() => setView(v)}>
              {v === "estimates" ? "Estimates" : "History"}
            </button>
          ))}
        </div>
        <div className="mo-tabs" role="tablist" aria-label="Move size">
          {SIZES.map((x) => {
            const u = results[x.up as MoveHead], d = results[x.down as MoveHead];
            const sel = size === x.key;
            return (
              <button
                key={x.key} ref={(el) => { tabRefs.current[x.key] = el; }} role="tab" id={`mo-tab-${x.key}`} aria-controls="mo-panel"
                aria-selected={sel} tabIndex={sel ? 0 : -1} className="mo-tab" data-testid={`mo-tab-${x.key}`}
                onClick={() => { setSize(x.key); setPage(0); }} onKeyDown={(e) => onTabKey(e, x.key)}
              >
                <span className="mo-t1">{x.label}</span>
                <span className="mo-t2">
                  {u?.kind === "final" && d?.kind === "final" ? `base rate up ${pct(u.data.base_rate)} · down ${pct(d.data.base_rate)}` : " "}
                </span>
              </button>
            );
          })}
        </div>
        <span className="mo-liveasof">
          {live && <span data-testid="mo-live-asof">Live prices <b>{live.source}</b> · {live.delay} · as of <b>{istTime(live.at)} IST</b></span>}
          {!live && liveError && <span data-testid="mo-live-error">Live prices unavailable ({liveError})</span>}
        </span>
      </div>

      {(final || view === "history") && (
        <div className="mo-filters">
          <div className="mo-toolbar">
            <div className="mo-filter">
              <label className="sr-only" htmlFor="mo-q">Find a stock</label>
              <input id="mo-q" type="search" placeholder="Find a symbol, company or sector" value={q} data-testid="mo-search"
                     onChange={(e) => { setQ(e.target.value); setPage(0); }} />
            </div>
            <label className="mo-toggle" htmlFor="mo-evonly">
              <input id="mo-evonly" type="checkbox" checked={evOnly} data-testid="mo-evonly" onChange={(e) => { setEvOnly(e.target.checked); setPage(0); }} />
              With events on record
            </label>
            {view === "estimates" && (
              <span className="mo-count" aria-live="polite" data-testid="mo-count">
                {rows.length.toLocaleString("en-IN")} stocks
                {missingExcluded > 0 && <span data-testid="mo-missing-excluded"> · {missingExcluded} without a value for an active condition left out</span>}
              </span>
            )}
          </div>
          <FilterBar profile={prof} unavailable={profileOff} cap={cap} setCap={(c) => { setCap(c); setPage(0); }} capCounts={capCounts}
                     picked={picked} conds={conds} setCond={setCond} removePicked={removePicked}
                     panelOpen={panelOpen} setPanelOpen={setPanelOpen} evtOpen={evtOpen} setEvtOpen={setEvtOpen} evtCat={evtCat}
                     clearAll={clearAll} canClear={canClear} />
          {profile === null && <p className="mo-mini" aria-busy="true" data-testid="mo-profile-loading">Loading ratings and ratios…</p>}
          {profile?.kind === "error" && (
            <button type="button" className="mo-btn" onClick={() => setProfileReload((n) => n + 1)} data-testid="mo-profile-retry">Try again</button>
          )}
          {prof && panelOpen && <RatioPanel profile={prof} picked={picked} toggle={togglePicked} close={() => setPanelOpen(false)} />}
          {prof && evtOpen && (
            <EventBar profile={prof} evtCat={evtCat} counts={evtCounts} evtSort={evtSort}
                      setEvtCat={(k) => { setEvtCat(k); setOrder(k === "All" ? "table" : "events"); setPage(0); }}
                      setEvtSort={(s) => { setEvtSort(s); setOrder("events"); setPage(0); }} />
          )}
        </div>
      )}

      <div id="mo-panel" role="tabpanel" aria-labelledby={`mo-tab-${size}`}>
        {view === "history" && (
          <>
            <div className="mo-viewrow mo-histrow">
              <span className="mo-mini">Ranked by the {histDir === "up" ? sz.upLabel : sz.downLabel} estimate for each session.</span>
              <span className="mo-histdir" role="group" aria-label="Direction">
                {(["up", "down"] as const).map((d) => (
                  <button key={d} type="button" aria-pressed={histDir === d} data-testid={`mo-histdir-${d}`}
                          onClick={() => setHistDir(d)}>{d === "up" ? sz.upLabel : sz.downLabel}</button>
                ))}
              </span>
            </div>
            <History result={hist} selected={histSession} onSelect={setHistSession} head={head} profile={prof} keep={(r) => matches(r.symbol, r.company_name, r.sector) && profileFilter(r.symbol) === "pass"}
                     sort={histSort} setSort={setHistSort} onOpen={openStock} />
          </>
        )}

        {view === "estimates" && loading && (
          <div className="mo-tablewrap" aria-busy="true" aria-label="Loading estimates" data-testid="mo-state-loading">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="mo-skelrow"><div className="mo-skel" /><div className="mo-skel" style={{ width: `${80 - i * 6}%` }} /><div className="mo-skel" /></div>
            ))}
          </div>
        )}

        {view === "estimates" && current?.kind === "not_published" && (
          <div className="mo-state" role="status" data-testid="mo-state-not_published">
            <h3 className="nv-serif">Estimates for {day(current.data.expected_session)} are not published yet</h3>
            <p>They are frozen after NSE&apos;s closing file is in and the 15:30–20:30 results window has closed, usually by 21:00 IST.</p>
            <p>Nothing from an earlier session is shown here in the meantime.</p>
          </div>
        )}

        {view === "estimates" && current?.kind === "withheld" && (
          <div className="mo-state" role="alert" data-testid="mo-state-withheld">
            <h3 className="nv-serif">Estimates withheld for the next session</h3>
            <p>The run was refused because its input data was incomplete (reason: {current.reason}). A run on incomplete data is not published.</p>
            <p>Estimates from an earlier session are not shown here because they apply to a different day.</p>
          </div>
        )}

        {view === "estimates" && current?.kind === "error" && (
          <div className="mo-state" role="alert" data-testid="mo-state-error">
            <h3 className="nv-serif">Estimates could not be loaded</h3>
            <p>The service did not answer ({current.message}). No earlier numbers are shown.</p>
            <button type="button" className="mo-btn" onClick={() => setReload((n) => n + 1)} data-testid="mo-retry">Try again</button>
          </div>
        )}

        {view === "estimates" && final && (
          <div className="mo-body">
            <div className="mo-maincol">
              <p className="mo-mini mo-tablenote" data-testid="mo-tablenote">
                The big number is the larger of the two estimates for a {sz.key}% touch on {day(final.run.target_session)}, with its side; the smaller sits under
                Other way. The amber tick is the base rate ({pct(final.base_rate)} up, {downFinal ? pct(downFinal.base_rate) : "—"} down). Direction compares the two:
                two-way when the smaller is at least {Math.round(TWO_WAY_RATIO * 100)}% of the larger. Ratings sit beside the odds and are not part of them. Open any row for the full read.
              </p>
              <div className="mo-tablewrap" tabIndex={0} role="region" aria-label="Estimates table">
                <table className="mo-table">
                  <caption>
                    {captionOrder}, {order === "table" ? (sort.dir === "desc" ? "descending" : "ascending") : "descending"}. Direction is a reading of two estimates. It is not a forecast.
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col" aria-sort={ariaSort("sym") ?? ariaSort("rating")}>
                        <span className="mo-hbtns">
                          <button type="button" onClick={() => toggleSort("sym")} data-testid="mo-sort-sym">Stock{arrow("sym")}</button>
                          <span aria-hidden="true">·</span>
                          <button type="button" onClick={() => toggleSort("rating")} data-testid="mo-sort-rating">rating{arrow("rating")}</button>
                        </span>
                      </th>
                      <th scope="col" aria-sort={ariaSort("est")}><button type="button" onClick={() => toggleSort("est")} data-testid="mo-sort-est">Chance of a {sz.key}% touch{arrow("est")}</button></th>
                      <th scope="col" aria-sort={ariaSort("other")}><button type="button" onClick={() => toggleSort("other")} data-testid="mo-sort-other">Other way{arrow("other")}</button></th>
                      <th scope="col" className="mo-th-live">Live</th>
                      <th scope="col" className="mo-th-chev"><span className="sr-only">Open</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {slice.length === 0 && (
                      <tr><td colSpan={5} className="mo-empty" data-testid="mo-empty">No stock matches{q ? ` "${q}"` : ""}{evOnly ? " with events on record" : ""}{canClear ? " with these filters" : ""}.</td></tr>
                    )}
                    {slice.map((r) => (
                      <Row key={r.symbol} r={r} head={upHead} baseUp={final.base_rate} baseDown={downFinal?.base_rate ?? null} profile={prof} idx={idx} picked={picked}
                           onOpen={(el) => openStock(r.symbol, el)} quote={live?.quotes[r.symbol]} />
                    ))}
                  </tbody>
                </table>
                <div className="mo-pager">
                  <span>{rows.length ? `${safePage * PAGE + 1}–${Math.min(safePage * PAGE + PAGE, rows.length)} of ${rows.length}` : "0 of 0"}</span>
                  <span className="mo-pager-btns">
                    <button type="button" className="mo-btn" disabled={safePage === 0} onClick={() => setPage(safePage - 1)} data-testid="mo-page-prev">Previous</button>
                    <button type="button" className="mo-btn" disabled={safePage >= pages - 1} onClick={() => setPage(safePage + 1)} data-testid="mo-page-next">Next</button>
                  </span>
                </div>
              </div>
            </div>
            <Aside final={final} openRow={openRow} profile={prof} />
          </div>
        )}
      </div>

      <SetupDiagnostics result={diag} onRetry={() => setDiagReload((n) => n + 1)} />

      {open && (
        <StockModal
          symbol={open} row={openRow} name={openRow?.company_name ?? (hist?.kind === "ok" ? hist.data.sessions.flatMap((s) => s.rows).find((x) => x.symbol === open)?.company_name ?? null : null)}
          profile={prof} idx={idx} stock={stocks[open]} card={cards[open]} quote={live?.quotes[open]} record={live?.record ?? null}
          estimates={estimatesFor(open)} baseRates={baseRates} evtLabel={evtLabel} onClose={closeStock}
        />
      )}
    </div>
  );
}

const SORT_NAME: Record<SortKey, string> = { est: "the larger of the two estimates", sym: "symbol", rating: "rating", other: "the smaller estimate (other way)" };

/** Past published sessions: pick a date, see that session's top estimates and what actually happened. Outcomes are the
 *  published run's own — a session whose closing prices are not in yet reads "grades tonight", never a guess. Stocks the
 *  model promoted into the top list that session are marked, so a new name is visible at a glance. The rating columns are
 *  today's ratings (as of the scores date), not the ratings on that past session, and the caption says so. */
type HistSort = { key: "est" | "sym" | "rating" | "move"; dir: "asc" | "desc" };
function History({ result, selected, onSelect, head, profile, keep, sort, setSort, onOpen }: {
  result: HistoryResult | null; selected: string | null; onSelect: (d: string) => void; head: MoveHead;
  profile: MoveProfile | null; keep: (r: { symbol: string; company_name: string | null; sector: string | null }) => boolean;
  sort: HistSort; setSort: (s: HistSort) => void; onOpen: (sym: string, from: HTMLElement | null) => void;
}) {
  if (result === null) return <p className="mo-mini" aria-busy="true" data-testid="mo-hist-loading">Loading history…</p>;
  if (result.kind !== "ok") {
    return (
      <div className="mo-state" role="alert" data-testid="mo-hist-error">
        <h3 className="nv-serif">History could not be loaded</h3>
        <p>The service did not answer ({result.kind === "error" ? result.message : "not enabled"}). No numbers are shown.</p>
      </div>
    );
  }
  const sessions = result.data.sessions;
  if (sessions.length === 0) {
    return (
      <div className="mo-state" role="status" data-testid="mo-hist-empty">
        <h3 className="nv-serif">No sessions published yet</h3>
        <p>Each published session is added here after its estimates are graded, one per trading day.</p>
      </div>
    );
  }
  const s: MoveHistorySession = sessions.find((x) => x.target_session === selected) ?? sessions[0];
  const m = META[head];
  const graded = s.state === "graded";
  const pr = (sym: string) => profile?.rows[sym];
  const secMed = (sym: string) => { const sec = pr(sym)?.sector; return sec ? profile?.sectors[sec] ?? null : null; };
  const shown = s.rows.filter((r) => keep({ symbol: r.symbol, company_name: r.company_name, sector: pr(r.symbol)?.sector ?? null }));
  const val = (r: (typeof s.rows)[number]): number | null =>
    sort.key === "rating" ? pr(r.symbol)?.quality?.score ?? null
    : sort.key === "move" ? r.outcome.move_pct ?? null
    : r.p;
  const rows = [...shown].sort((a, b) =>
    sort.key === "sym" ? (sort.dir === "asc" ? a.symbol.localeCompare(b.symbol) : b.symbol.localeCompare(a.symbol))
      : cmpNum(val(a), val(b), sort.dir) || b.p - a.p || a.symbol.localeCompare(b.symbol));
  const toggle = (key: HistSort["key"]) => setSort(sort.key === key ? { key, dir: sort.dir === "desc" ? "asc" : "desc" } : { key, dir: key === "sym" ? "asc" : "desc" });
  const aria = (key: HistSort["key"]) => (sort.key === key ? (sort.dir === "asc" ? "ascending" : "descending") : undefined);
  const arr = (key: HistSort["key"]) => (sort.key === key ? (sort.dir === "desc" ? " ↓" : " ↑") : "");
  return (
    <div className="mo-hist" data-testid="mo-history">
      <div className="mo-hist-dates" role="group" aria-label="Session">
        {sessions.map((x) => (
          <button key={x.target_session} type="button" className="mo-hist-date" aria-pressed={x.target_session === s.target_session}
                  data-testid={`mo-hist-date-${x.target_session}`} onClick={() => onSelect(x.target_session)}>
            <span className="mo-hist-d1">{day(x.target_session)}</span>
            <span className="mo-hist-d2">{x.state === "graded" ? `${x.summary.top_n_touched ?? 0} of ${x.rows.length}` : "pending"}</span>
          </button>
        ))}
      </div>

      <div className="mo-hist-head" data-testid="mo-hist-summary">
        <h3 className="nv-serif">{day(s.target_session)} · {m.label}</h3>
        {graded ? (
          <p className="mo-mini">
            {s.summary.top_n_touched ?? 0} of the top {s.rows.length} reached it · across all {s.summary.graded_rows?.toLocaleString("en-IN") ?? s.scored?.toLocaleString("en-IN")} scored stocks{" "}
            {s.summary.touched?.toLocaleString("en-IN") ?? "—"} did ({s.summary.touch_rate != null ? pct(s.summary.touch_rate) : "—"}), against a base rate of {s.base_rate != null ? pct(s.base_rate) : "—"}
          </p>
        ) : (
          <p className="mo-mini" data-testid="mo-hist-pending">Estimates published from the close of {day(s.data_as_of)}. This session is graded after its closing file lands, usually by 21:00 IST.</p>
        )}
        <p className="mo-mini mo-hist-legend" data-testid="mo-hist-legend"><span className="mo-newdot" aria-hidden="true" /> new to the top {result.data.top_n} this session</p>
      </div>

      <div className="mo-tablewrap" tabIndex={0} role="region" aria-label={`Top estimates for ${day(s.target_session)}`}>
        <table className="mo-table mo-hist-table">
          <caption>
            Top {s.rows.length} by {m.label} estimate for {day(s.target_session)}, and what the session did
            {shown.length < s.rows.length ? ` (${shown.length} shown with the filters above)` : ""}.
            {profile ? ` Rating and sector rating are as of ${day(profile.scores_as_of)}, not as of that session.` : ""}
          </caption>
          <thead>
            <tr>
              <th scope="col" aria-sort={aria("sym")}><button type="button" onClick={() => toggle("sym")} data-testid="mo-hsort-sym">Stock{arr("sym")}</button></th>
              <th scope="col" aria-sort={aria("rating")}><button type="button" onClick={() => toggle("rating")} data-testid="mo-hsort-rating">Rating now{arr("rating")}</button></th>
              <th scope="col" aria-sort={aria("est")}><button type="button" onClick={() => toggle("est")} data-testid="mo-hsort-est">{m.label} est{arr("est")}</button></th>
              <th scope="col">That session</th>
              <th scope="col" aria-sort={aria("move")}><button type="button" onClick={() => toggle("move")} data-testid="mo-hsort-move">Move{arr("move")}</button></th>
              <th scope="col" className="mo-th-chev"><span className="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={6} className="mo-empty">No stock in this session&apos;s list matches the filters above.</td></tr>}
            {rows.map((r) => {
              const p = pr(r.symbol);
              const sec = secMed(r.symbol);
              return (
                <tr key={r.symbol} data-testid={`mo-hist-row-${r.symbol}`} className={`mo-rowclick${r.is_new ? " mo-hist-new" : ""}`}
                    onClick={(e) => { if (!(e.target as HTMLElement).closest("button,a,input")) onOpen(r.symbol, (e.currentTarget.querySelector(".mo-symbtn") as HTMLElement | null)); }}>
                  <th scope="row">
                    <span className="mo-stockline">
                      <button type="button" className="mo-symbtn" aria-haspopup="dialog" onClick={(e) => onOpen(r.symbol, e.currentTarget)} data-testid={`mo-hist-open-${r.symbol}`}>
                        <span className="mo-sym">{r.symbol}</span>
                      </button>
                      {r.is_new && <span className="mo-newtag" data-testid={`mo-hist-new-${r.symbol}`}>new</span>}
                    </span>
                    <span className="mo-coname">{r.company_name ?? ""}</span>
                    {profile && (
                      <span className="mo-subline" data-testid={`mo-hist-sec-${r.symbol}`}>
                        {p?.cap ? `${p.cap} cap · ` : ""}sector {sec?.grade ?? "—"}
                      </span>
                    )}
                  </th>
                  <td data-testid={`mo-hist-rating-${r.symbol}`}>
                    <span className="mo-hist-grade"><Badge q={p?.quality ?? null} off={!profile} testid={`mo-hist-badge-${r.symbol}`} />
                      {p?.quality && <span className="mo-grade-n">{p.quality.score.toFixed(1)}</span>}</span>
                  </td>
                  <td data-testid={`mo-hist-p-${r.symbol}`} className="mo-hist-est">{pct(r.p)}</td>
                  <td data-testid={`mo-hist-outcome-${r.symbol}`}>
                    {r.outcome.state === "pending" ? <span className="mo-outcome pending">pending</span>
                      : r.outcome.touched ? <span className="mo-outcome yes">reached</span>
                      : <span className="mo-outcome no">did not</span>}
                  </td>
                  <td className="mo-hist-move">
                    <span>{r.outcome.move_pct != null ? signed(r.outcome.move_pct * 100, "%") : "—"}</span>
                    <span className="mo-hist-within" data-testid={`mo-hist-within-${r.symbol}`}>
                      within 3: {r.outcome.within3 == null ? "—" : r.outcome.within3 ? "reached" : "no"} · within 5: {r.outcome.within5 == null ? "—" : r.outcome.within5 ? "reached" : "no"}
                    </span>
                  </td>
                  <td className="mo-chev" aria-hidden="true">›</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mo-mini">&quot;Within 3&quot; and &quot;within 5&quot; ask whether the level was reached at any point in that many sessions, measured from the same close the estimate was made against. A dash means those sessions have not happened yet.</p>
    </div>
  );
}

const SETUP_ORDER = ["A", "B", "C", "D"] as const;
function signedPct2(v: number | null): string {
  if (v == null) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(2)}%`;
}
function dmy(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return m >= 1 && m <= 12 ? `${d} ${MON[m - 1]} ${y}` : iso;
}

/** Research results for the four entry setups the owner rejected on 2026-09-17. Always A, B, C, D; numbers in ink, never
 *  coloured or ranked; no prices, levels or amounts. */
function SetupDiagnostics({ result, onRetry }: { result: DiagnosticsResult | null; onRetry: () => void }) {
  const ok = result?.kind === "ok" ? result.data : null;
  const setups = ok ? SETUP_ORDER.map((id) => ok.setups.find((s) => s.id === id)).filter((s): s is NonNullable<typeof s> => !!s) : [];
  return (
    <section className="mo-diag" aria-labelledby="mo-diag-h" data-testid="mo-diagnostics">
      <div className="mo-diag-head">
        <h3 id="mo-diag-h" className="nv-serif">Research diagnostics · entry setups</h3>
        {ok && (
          <p className="mo-mini" data-testid="mo-diag-summary">
            Tested {dmy(ok.study.first_signal_day)} – {dmy(ok.study.last_signal_day)} · {ok.study.validated} of {ok.study.tested} validated · research only, not trading signals
          </p>
        )}
      </div>
      {!result && <p className="mo-mini" aria-busy="true" data-testid="mo-diag-loading">Loading research diagnostics…</p>}
      {result && result.kind !== "ok" && (
        <div className="mo-state" role="alert" data-testid="mo-diag-error">
          <p>Research diagnostics could not be loaded ({result.kind === "error" ? result.message : "not enabled"}). No numbers are shown.</p>
          <button type="button" className="mo-btn" onClick={onRetry} data-testid="mo-diag-retry">Try again</button>
        </div>
      )}
      {ok && (
        <>
          <div className="mo-diag-grid">
            {setups.map((s) => (
              <article key={s.id} className="mo-diag-card" data-testid={`mo-diag-${s.id}`} aria-labelledby={`mo-diag-${s.id}-h`}>
                <div className="mo-diag-cardhead">
                  <h4 id={`mo-diag-${s.id}-h`}>{s.name}</h4>
                  <span className="mo-chip" data-testid={`mo-diag-status-${s.id}`}>{s.status_label}</span>
                </div>
                <p className="mo-diag-rs" data-testid={`mo-diag-rs-${s.id}`}>{s.research_status}</p>
                {s.headline !== s.status_label && <p className="mo-diag-headline">{s.headline}</p>}
                <div className="mo-diag-tablewrap">
                  <table className="mo-bands mo-diag-table">
                    <thead>
                      <tr><th scope="col">Version</th><th scope="col">Trades</th><th scope="col">Historical net average</th><th scope="col">Baseline</th><th scope="col">Signal status</th></tr>
                    </thead>
                    <tbody>
                      {s.trades.map((t) => (
                        <tr key={t.trade} data-testid={`mo-diag-${s.id}-${t.trade === "5%" ? "5" : "10"}`}>
                          <th scope="row">{t.trade} trade</th>
                          <td>{t.trades.toLocaleString("en-IN")}</td>
                          <td>{signedPct2(t.mean_net)}</td>
                          <td>{signedPct2(t.baseline_mean_net)}</td>
                          <td>Failed validation</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mo-mini">{s.explanation}</p>
              </article>
            ))}
          </div>
          <p className="mo-mini mo-diag-method" data-testid="mo-diag-method">
            {ok.study.universe}. {ok.study.exits}. Costs {(ok.study.cost_round_trip * 100).toFixed(2)}% per round trip. Baseline: {ok.study.baseline.charAt(0).toLowerCase() + ok.study.baseline.slice(1)}. {ok.study.rule}.
          </p>
        </>
      )}
    </section>
  );
}

function rupees(v: number): string {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function PaperIndicator({ p, symbol }: { p: PaperTrade; symbol: string }) {
  const e = p.exits[0];                                     // the +5% exit is the indicator; Details shows +10% too
  const tone = e.net > 0 ? "up" : e.net < 0 ? "down" : "flat";
  const state = e.reached ? `+${e.pct}% at ${e.at}` : e.state === "open" ? "open" : "day close";
  return (
    <span className={`mo-paper ${tone}`} data-testid={`mo-paper-${symbol}`}
          title={`Paper trade: ${p.qty.toLocaleString("en-IN")} shares from ₹${money(p.entry_price)} at ${p.entry_time}, exit at +${e.pct}% or the latest price; after estimated charges`}>
      Paper {rupees(e.net)} · {state}
    </span>
  );
}

function LiveCell({ q, head }: { q: LiveQuote | undefined; head: MoveHead }) {
  if (!q) return <span className="mo-live none" data-testid="mo-live-pending">…</span>;
  if (q.error || q.last == null || q.change_pct == null) return <span className="mo-live none">—</span>;
  const hit = q.touched?.[head] ? META[head].label.replace("High ≥ ", "").replace("Low ≤ ", "") : null;
  return (
    <span className="mo-live">
      <span className="mo-live-last">₹{money(q.last)}</span>
      <span className="mo-live-chg">{signed(q.change_pct, "%")}</span>
      {hit && <span className="mo-live-hit" aria-label={`today's ${head.startsWith("p_up") ? "high" : "low"} reached the ${hit} level`}>{hit} reached</span>}
      {q.conditions?.entry_signal && (
        <span className="mo-signal" data-testid={`mo-signal-${q.symbol}`} title="All five breakout checks are met at the latest completed hourly bar. This rule lost money in its 2025 test; see Details.">
          Entry signal · since {q.conditions.entry_signal_since?.split("-")[0]}
        </span>
      )}
      {q.paper && <PaperIndicator p={q.paper} symbol={q.symbol} />}
    </span>
  );
}

function Row({ r, head, baseUp, baseDown, profile, idx, picked, onOpen, quote }: {
  r: MoveRow; head: MoveHead; baseUp: number; baseDown: number | null;
  profile: MoveProfile | null; idx: Record<string, number>; picked: string[];
  onOpen: (from: HTMLElement | null) => void; quote: LiveQuote | undefined;
}) {
  const dir = directionReading(r.p, r.p_opposite);
  const sd = sides(r);
  const base = sd.up ? baseUp : baseDown;
  const btn = useRef<HTMLButtonElement | null>(null);
  const pr = profile?.rows[r.symbol];
  const q = pr?.quality ?? null;
  const sector = pr?.sector ?? r.sector;
  const sec = sector && profile ? profile.sectors[sector] : null;
  const defs = profile ? Object.fromEntries(profile.catalogue.map((d) => [d.key, d])) : {};
  const fund = profile ? picked.map((k) => {
    const v = valueOf(profile, idx, r.symbol, k);
    return defs[k] && v != null ? `${SHORT[k] ?? defs[k].label} ${fmtRatio(defs[k].unit, v)}` : null;
  }).filter(Boolean).join(" · ") : "";
  const sideWord = sd.up ? "upside" : "downside";
  return (
    <tr data-testid={`mo-row-${r.symbol}`} className="mo-rowclick"
        onClick={(e) => { if (!(e.target as HTMLElement).closest("button,a,input")) onOpen(btn.current); }}>
      <th scope="row">
        <div className="mo-stockcell">
          <Badge q={q} off={!profile} testid={`mo-rating-${r.symbol}`} />
          <div className="mo-stockmeta">
            <div className="mo-stockline">
              <button ref={btn} type="button" className="mo-symbtn" aria-haspopup="dialog" onClick={(e) => onOpen(e.currentTarget)} data-testid={`mo-details-${r.symbol}`}>
                <span className="mo-sym">{r.symbol}</span><span className="sr-only">: open details</span>
              </button>
              <span className="mo-co" title={r.company_name ?? ""}>{r.company_name ?? r.symbol}</span>
            </div>
            <span className="mo-subline" data-testid={`mo-subline-${r.symbol}`}>
              {sector ?? "Sector not on record"}
              {profile && <> · <span data-testid={`mo-secrating-${r.symbol}`} data-grade={sec?.grade ?? undefined}
                title={sec?.median != null ? `Sector rating ${sec.grade}: median ${sec.median.toFixed(1)} of ${sec.n} stocks with enough inputs` : "No sector rating on record"}>sector {sec?.grade ?? "—"}</span></>}
              {pr?.cap ? ` · ${pr.cap} cap` : ""}
            </span>
            {profile && <span className="mo-fundline" title={fund || undefined} data-testid={`mo-fund-${r.symbol}`}>{fund || "no ratios on record for the picked columns"}</span>}
            <span className="mo-pills">
              <span className={`mo-dir ${dir.key}`} data-testid={`mo-dir-${r.symbol}`}>{dir.label}</span>
              <span className={`mo-evc${r.events_on_record ? "" : " none"}`} data-testid={`mo-events-${r.symbol}`}>{r.events_on_record ? `${r.events_on_record} on record` : "no events"}</span>
              {q?.partial && <span className="mo-grade-partial" title={`Rating from only ${q.coverage ?? "—"}% of its inputs`}>partial rating</span>}
            </span>
          </div>
        </div>
      </th>
      <td className="mo-bigcell">
        <div className="mo-bigline">
          <span className="mo-big" data-testid={`mo-big-${r.symbol}`} data-side={sd.up ? "up" : "down"} aria-label={`${sideWord} ${spoken(sd.hi)}`}>{pct(sd.hi)}</span>
          <span className="mo-mult">{times(sd.hi, base)}</span>
        </div>
        <span className="mo-track" aria-hidden="true">
          <span className="mo-fill" style={{ width: `${Math.min(100, sd.hi * 100)}%` }} />
          {base != null && <span className="mo-tick" style={{ left: `calc(${base * 100}% - 1px)` }} />}
        </span>
        <span className="mo-sideword" data-testid={`mo-side-${r.symbol}`}>{sideWord} · {oneIn(sd.hi)}</span>
      </td>
      <td data-testid={`mo-other-${r.symbol}`}>
        <span className="mo-other" aria-label={`${sd.up ? "downside" : "upside"} ${spoken(sd.lo)}`}>{pct(sd.lo)}</span>
      </td>
      <td data-testid={`mo-livecell-${r.symbol}`} className="mo-td-live"><LiveCell q={quote} head={head} /></td>
      <td className="mo-chev" aria-hidden="true">›</td>
    </tr>
  );
}

/** The grade letter as a badge (v2 design); the score is in its label and in the stock view. */
function Badge({ q, off, testid }: { q: MoveQuality | null; off: boolean; testid: string }) {
  if (off) return <span className="mo-badge none" data-testid={testid} title="Ratings could not be loaded">—</span>;
  if (!q) return <span className="mo-badge none" data-testid={testid} title="No V3 quality score on record">—<span className="sr-only"> no rating on record</span></span>;
  const label = `Rated ${q.grade}, ${q.score.toFixed(1)} of 100${q.partial ? `, from only ${q.coverage ?? "—"}% of its inputs` : ""}`;
  return (
    <span className={`mo-badge ${gradeTone(q.grade)}${q.partial ? " partial" : ""}`} data-testid={testid} data-grade={q.grade} data-score={q.score.toFixed(1)} title={label}>
      <span aria-hidden="true">{q.grade}</span><span className="sr-only">{label}</span>
    </span>
  );
}

/** Peer comparisons that stand out: this stock against the median of its sector's stocks scored in this run (the
 *  stock included), stated with n. Ratios without at least 3 peers are listed together, uncompared. */
function standsOut(profile: MoveProfile, idx: Record<string, number>, sym: string, sector: string | null) {
  const out: Array<{ tone: "mint" | "danger" | "ink"; text: string }> = [];
  const alone: string[] = [];
  const unitOf = (k: string) => profile.catalogue.find((d) => d.key === k)?.unit ?? "x";
  for (const [k, name, higherIsBetter] of [["roce", "ROCE", true], ["opm", "Operating margin", true], ["sg", "Sales growth", true], ["de", "Debt to equity", false], ["pe", "P/E", null]] as const) {
    const v = valueOf(profile, idx, sym, k);
    if (v == null) continue;
    const pm = peerMedian(profile, idx, sector, k);
    if (pm.median == null || pm.n < 3) { alone.push(`${name} ${fmtRatio(unitOf(k), v)}`); continue; }
    const above = v > pm.median;
    const tone = higherIsBetter == null || v === pm.median ? "ink" : above === higherIsBetter ? "mint" : "danger";
    out.push({ tone, text: `${name} ${fmtRatio(unitOf(k), v)} against a median of ${fmtRatio(unitOf(k), pm.median)} for the ${pm.n} ${sector} stocks scored in this run.` });
  }
  if (alone.length) out.push({ tone: "ink", text: `${alone.join(", ")}: fewer than 3 ${sector ?? "same-sector"} stocks in this run have these, so they are not compared.` });
  return out.slice(0, 5);
}

function StockModal({ symbol, row, name, profile, idx, stock, card, quote, record, estimates, baseRates, evtLabel, onClose }: {
  symbol: string; row: MoveRow | null; name: string | null; profile: MoveProfile | null; idx: Record<string, number>;
  stock: MoveStockResult | "loading" | undefined; card: StockCardResult | "loading" | undefined;
  quote: LiveQuote | undefined; record: LivePayload["signal_record"];
  estimates: Partial<Record<MoveHead, number>>; baseRates: Partial<Record<MoveHead, number>>;
  evtLabel: (k: string) => string; onClose: () => void;
}) {
  const [chip, setChip] = useState(0);
  const box = useRef<HTMLDivElement | null>(null);
  const closeBtn = useRef<HTMLButtonElement | null>(null);
  useEffect(() => { closeBtn.current?.focus(); }, [symbol]);
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
    if (e.key !== "Tab" || !box.current) return;
    const f = Array.from(box.current.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])'));
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  const pr = profile?.rows[symbol] ?? null;
  const sector = pr?.sector ?? row?.sector ?? null;
  const q = pr?.quality ?? null;
  const ans = profile ? answers({ sym: symbol, sector, profile, row: pr, idx, estimates, baseRates, day, eventLabel: evtLabel }) : [];
  const a = ans[chip];
  const so = profile ? standsOut(profile, idx, symbol, sector) : [];
  const titleId = `mo-modal-h-${symbol}`;
  const cardOk = card !== undefined && card !== "loading" && card.kind === "ok";
  return (
    <div className="mo-modal-back" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }} data-testid="mo-modal-back">
      <div ref={box} className="mo-modal" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKey} data-testid={`mo-detail-${symbol}`}>
        <div className="mo-modal-head">
          <div>
            <h3 id={titleId} className={cardOk ? "sr-only" : "nv-serif"}><span className="mo-sym">{symbol}</span> {name ?? ""}</h3>
            {!cardOk && <p className="mo-mini">{[sector, pr?.cap ? `${pr.cap} cap` : null].filter(Boolean).join(" · ") || "Sector and market-cap bucket not on record"}</p>}
          </div>
          <button ref={closeBtn} type="button" className="mo-modal-x" onClick={onClose} aria-label={`Close details for ${symbol}`} data-testid="mo-modal-close"><X size={16} aria-hidden="true" /></button>
        </div>
        <div className="mo-modal-body">
          <div className="mo-disc mo-disc-sm" role="note" data-testid="mo-modal-disclaimer"><b>DISCLAIMER</b>{DISCLAIMER}</div>

          {(card === undefined || card === "loading") && (
            <div className="mo-card-loading" aria-busy="true" data-testid="mo-card-loading"><div className="mo-skel" /><div className="mo-skel" style={{ width: "70%" }} /><div className="mo-skel" style={{ width: "85%" }} /></div>
          )}
          {cardOk && (
            <div className="mo-card" data-testid="mo-card">
              <ChatWidget widget={(card as { kind: "ok"; widget: { widget_type: string; data: Record<string, unknown> } }).widget} />
            </div>
          )}
          {card !== undefined && card !== "loading" && card.kind !== "ok" && (
            <p className="mo-mini mo-card-off" role="status" data-testid="mo-card-off">
              The copilot stock card could not be loaded ({card.kind === "not_found" ? `no research data for ${symbol}` : card.kind === "error" ? card.message : "not enabled"}). The quality summary below is from this page&apos;s ratings.
            </p>
          )}

          {card !== undefined && card !== "loading" && card.kind !== "ok" && (profile ? (
            <>
              <div className="mo-chips" role="group" aria-label="Questions about this stock">
                {ans.map((x, i) => (
                  <button key={x.label} type="button" aria-pressed={chip === i} className="mo-qchip" data-testid={`mo-chip-${i}`} onClick={() => setChip(i)}>{x.label}</button>
                ))}
              </div>
              {a && (
                <div className="mo-answer" aria-live="polite" data-testid="mo-answer-panel">
                  <p className="mo-answer-lead">{a.lead}</p>
                  <ul>{a.bullets.map((b, i) => <li key={i} className={`mo-bullet ${b.tone}`}>{b.text}</li>)}</ul>
                </div>
              )}

              <div className="mo-quality" data-testid="mo-quality">
                <div className="mo-qscore">
                  <span className="mo-eyebrow">Quality score</span>
                  {q ? (
                    <>
                      <span className="mo-qbig" data-testid="mo-qscore">{q.score.toFixed(1)}<small>/100</small></span>
                      <span className={`mo-grade ${gradeTone(q.grade)}`} data-grade={q.grade}><b>{q.grade}</b><span className="mo-grade-n">{qualityLabel(q.score)}</span></span>
                      <span className="mo-mini">V3 score as of {day(q.as_of)}{q.coverage != null ? ` · ${q.coverage}% of inputs` : ""}{q.partial ? " · partial" : ""}</span>
                    </>
                  ) : <span className="mo-mini" data-testid="mo-qscore-none">No V3 quality score on record as of {day(profile.scores_as_of)}.</span>}
                </div>
                <div className="mo-qbars">
                  {([["Fundamentals", q?.fundamental ?? null, fundBand], ["Technicals", q?.technical ?? null, techBand]] as const).map(([label, v, band]) => (
                    <div key={label} className="mo-qbar" data-testid={`mo-qbar-${label.toLowerCase()}`}>
                      <span className="mo-qbar-l">{label}</span>
                      <span className="mo-qbar-track" aria-hidden="true"><span className={`mo-qbar-fill ${v == null ? "ink" : band(v).tone}`} style={{ width: `${v == null ? 0 : Math.max(0, Math.min(100, v))}%` }} /></span>
                      <span className="mo-qbar-v">{v == null ? "not scored" : `${Math.round(v)} · ${band(v).label}`}</span>
                    </div>
                  ))}
                </div>
                <div className="mo-stands" data-testid="mo-stands">
                  <h4>What stands out</h4>
                  {so.length ? <ul>{so.map((b, i) => <li key={i} className={`mo-bullet ${b.tone}`}>{b.text}</li>)}</ul>
                    : <p className="mo-mini">No ratios on record to compare with its sector.</p>}
                </div>
              </div>
            </>
          ) : (
            <p className="mo-mini" data-testid="mo-modal-noprofile">Ratings, ratios and the question answers could not be loaded. The move odds below are unaffected.</p>
          ))}

          <h4 className="mo-modal-sec">Move odds for the next session</h4>
          <Detail stock={stock} />
          <Checks q={quote} record={record} symbol={symbol} />
          <p className="mo-mini mo-modal-src" data-testid="mo-modal-source">
            {cardOk ? "The card above is the copilot chat's stock card for this stock, as served there. " : ""}Rating: V3 stock score{profile ? ` as of ${day(profile.scores_as_of)}` : ""} (A ≥ 70, B 50–69.9, C below 50). Ratios{profile?.features_as_of ? ` as of ${day(profile.features_as_of)}` : ""}.
            Ratings and the card describe the business and the chart; they are shown beside the move odds and are not part of them.
          </p>
        </div>
        <div className="mo-modal-foot"><button type="button" className="mo-btn" onClick={onClose} data-testid="mo-modal-close-btn">Close</button></div>
      </div>
    </div>
  );
}

function Detail({ stock }: { stock: MoveStockResult | "loading" | undefined }) {
  if (!stock || stock === "loading") return <p className="mo-mini">Loading details…</p>;
  if (stock.kind !== "ok") return <p className="mo-mini">Details could not be loaded{stock.kind === "error" ? ` (${stock.message})` : ""}.</p>;
  const s = stock.data;
  return (
    <div className="mo-dgrid">
      <div>
        <h4>All four estimates</h4>
        <dl className="mo-kv">
          {MOVE_HEADS.map((h) => (<div key={h} className="mo-kvrow"><dt>{META[h].label}</dt><dd>{pct(s.estimates[h])}</dd></div>))}
        </dl>
        <p className="mo-dnote">Estimates for {day(s.run.target_session)}. A stock can carry high odds in both directions.</p>
      </div>
      <div>
        <h4>Inputs on record</h4>
        <dl className="mo-kv" data-testid="mo-inputs">
          {INPUTS.map((x) => {
            const inp = s.inputs[x.key];
            return (
              <div key={x.key} className="mo-kvrow">
                <dt>{x.label}<small>{inp?.date ? `${day(inp.date)}${x.note ? ` · ${x.note}` : ""}` : "not published"}</small></dt>
                <dd>{inp && inp.v != null ? x.fmt(inp.v) : "—"}</dd>
              </div>
            );
          })}
          <div className="mo-kvrow"><dt>Results filed 15:30–20:30<small>{day(s.run.data_as_of)}</small></dt><dd>{s.results_filed ? "yes" : "none"}</dd></div>
        </dl>
        <p className="mo-dnote">The same inputs, in the same order, for every stock. Listed for reference; the model uses {s.run.input_count ?? "more"}.</p>
      </div>
      <div>
        <h4>Events on record</h4>
        {s.events.length ? (
          <ul className="mo-evlist" data-testid="mo-events">
            {s.events.map((e) => (
              <li key={e.ord}>
                <span className="mo-evtype">{e.event_type.toLowerCase()} · {e.event_subtype.replace(/_/g, " ")} · classified {e.direction}</span>
                <span>{e.is_media ? "Media report · headline not shown" : e.title}</span>
                <span className="mo-evmeta">
                  <span>{e.source_label}</span><span>{istTime(e.event_time)} IST</span><span>{e.method}</span>
                  {e.url && <a href={e.url} target="_blank" rel="noopener noreferrer">source<span className="sr-only"> for {s.symbol}</span></a>}
                </span>
              </li>
            ))}
          </ul>
        ) : <p className="mo-mini">No classified filings or reports on record in the five days to the freeze.</p>}
        <p className="mo-dnote">From exchanges, regulators and news sources. Events are not model inputs.</p>
      </div>
    </div>
  );
}

function Checks({ q, record, symbol }: { q: LiveQuote | undefined; record: LivePayload["signal_record"]; symbol: string }) {
  const c = q?.conditions ?? null;
  const latest = c?.latest ?? null;
  return (
    <div className="mo-checks" data-testid={`mo-checks-${symbol}`}>
      <h4>Entry signal · five breakout checks on hourly bars</h4>
      <p className="mo-signal-state" data-testid={`mo-signal-state-${symbol}`}>
        {c?.entry_signal
          ? <>Entry signal <b>ON</b> since the {c.entry_signal_since} bar (close ₹{money(c.close_at_signal_start)}).</>
          : <>Entry signal <b>OFF</b>{latest ? ` · ${latest.met} of 5 checks met` : ""}.</>}
      </p>
      {q && !q.error && q.day_high != null && q.day_low != null && (
        <p className="mo-mini">Today so far: high {signed(q.high_pct ?? 0, "%")}, low {signed(q.low_pct ?? 0, "%")} against the previous close of ₹{money(q.prev_close)}.</p>
      )}
      {!c && <p className="mo-mini">Checks start after the first completed hour of trading (from 10:15 IST) and use completed hourly bars only.</p>}
      {c && latest && (
        <>
          <ul className="mo-checklist">
            {CHECKS.map((k) => (
              <li key={k.key} data-met={latest[k.key] ? "yes" : "no"}><span className="mo-checkmark" aria-hidden="true">{latest[k.key] ? "✓" : "✗"}</span>{k.label}<span className="sr-only">: {latest[k.key] ? "met" : "not met"}</span></li>
            ))}
          </ul>
          <p className="mo-mini">
            {latest.met} of 5 held at the {latest.bar} bar (close ₹{money(latest.close)}, VWAP {latest.vwap == null ? "—" : `₹${money(latest.vwap)}`}).{" "}
            {c.first_met_at ? `All five first held at the ${c.first_met_at} bar, close ₹${money(c.close_at_first_met)}.` : "All five have not held together yet today."}
          </p>
        </>
      )}
      {c && !latest && <p className="mo-mini">Only the first hour has completed; the checks start from the second bar.</p>}
      {q?.paper && (
        <div className="mo-papertrade" data-testid={`mo-papertrade-${symbol}`}>
          <h4>Paper trade · {q.paper.qty.toLocaleString("en-IN")} shares from ₹{money(q.paper.entry_price)} at {q.paper.entry_time} · marked {q.paper.marked_at} IST</h4>
          <table className="mo-bands">
            <thead><tr><th scope="col">Exit rule</th><th scope="col">Status</th><th scope="col">Price</th><th scope="col">Gross</th><th scope="col">Charges</th><th scope="col">Net</th></tr></thead>
            <tbody>
              {q.paper.exits.map((e) => (
                <tr key={e.pct}>
                  <td>+{e.pct}% (₹{money(e.level)})</td>
                  <td>{e.reached ? `reached ${e.at}` : e.state}</td>
                  <td>₹{money(e.price)}</td>
                  <td>{rupees(e.gross)}</td>
                  <td>₹{money(e.charges)}</td>
                  <td className={e.net > 0 ? "mo-up" : e.net < 0 ? "mo-down" : ""}>{rupees(e.net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mo-mini">Hypothetical: entry at the close of the first hourly bar where all five checks held; exit at the first 5-minute high reaching the level after entry, otherwise the latest price (the day&apos;s close after 15:30). Charges are an estimate for a discount broker&apos;s intraday rates.</p>
        </div>
      )}
      {record && (
        <p className="mo-mini mo-record" data-testid="mo-checks-record">
          Tested on {record.window}, {record.candidates}: after all five held, the +5% level was reached {(record.touch_rate_after_checks * 100).toFixed(1)}% of the time
          against {(record.touch_rate_unconditional * 100).toFixed(1)}% without them, but taking the breakout averaged {(record.mean_net_return * 100).toFixed(2)}% per trade after costs
          (95% interval {(record.ci95_mean_net_return[0] * 100).toFixed(2)}% to {(record.ci95_mean_net_return[1] * 100).toFixed(2)}%, {record.trades} trades). This signal failed that test and is shown at the account owner&apos;s request; it is a rule, not advice.
        </p>
      )}
    </div>
  );
}

function Aside({ final, openRow, profile }: { final: MoveFinal; openRow: MoveRow | null; profile: MoveProfile | null }) {
  const rec = final.record;
  const live = final.live_record;
  const here = openRow && rec ? rec.bands.findIndex((b) => openRow.p >= b.band_lo && (openRow.p < b.band_hi || b.band_hi >= 1)) : -1;
  return (
    <aside className="mo-side" aria-label="How these estimates have held up" data-testid="mo-aside">
      {rec && (
        <div className="mo-panel">
          <h3>How each band turned out in testing</h3>
          <table className="mo-bands" data-testid="mo-bands">
            <caption className="sr-only">{rec.window_label} test</caption>
            <thead><tr><th scope="col">Estimate</th><th scope="col">Stock-days</th><th scope="col">Touched</th></tr></thead>
            <tbody>
              {rec.bands.map((b, i) => (
                <tr key={b.band_lo} className={i === here ? "here" : ""}>
                  <td>{bandLabel(b)}</td><td>{b.rows.toLocaleString("en-IN")}</td><td>{b.realised == null ? "—" : `${(b.realised * 100).toFixed(1)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mo-mini">{rec.window_label}, {rec.sessions} sessions, each scored by a model trained only on earlier data.{openRow ? ` Highlighted: the band of ${openRow.symbol}.` : " Open a stock to see its band."}</p>
        </div>
      )}
      <div className="mo-panel" data-testid="mo-aside-ratings">
        <h3>Ratings</h3>
        <ul className="mo-plain">
          <li><span className="mo-grade mint"><b>A</b></span> score 70 or more · <span className="mo-grade amber"><b>B</b></span> 50–69.9 · <span className="mo-grade danger"><b>C</b></span> below 50, on the V3 stock score (0–100){profile ? ` as of ${day(profile.scores_as_of)}` : ""}.</li>
          <li>&quot;Partial&quot;: fewer than {profile?.coverage_min ?? 80}% of the score&apos;s inputs were available.</li>
          <li>Sector rating: the median score of the sector&apos;s stocks with at least {profile?.coverage_min ?? 80}% of their inputs.</li>
          <li>Ratings describe the business and the chart. They are not part of the move odds and say nothing about the next session.</li>
        </ul>
      </div>
      <div className="mo-panel" data-testid="mo-live">
        <h3>Live record</h3>
        <div className="mo-big">{live.sessions} {live.sessions === 1 ? "session" : "sessions"}</div>
        {live.sessions > 0 && live.last_target ? (
          <p>For {day(live.last_target)}: {live.last_top10_hits} of the 10 highest estimates touched, against {live.last_touched} of {live.last_graded_rows} stocks overall.</p>
        ) : (
          <p>Each session is graded after the close. No counted session has been graded yet.</p>
        )}
      </div>
      <div className="mo-panel">
        <h3>Limits</h3>
        <ul className="mo-plain">
          <li>Base rate: {pct(final.base_rate)} of stock-days in training.</li>
          {rec && <li>In testing, the 10 highest estimates each session touched {(rec.top10_hit_rate * 100).toFixed(1)}% of the time.</li>}
          <li>Not used: {final.limits.not_used.join(", ")}.</li>
          <li>A touch can reverse within minutes; the estimate says nothing about the close.</li>
          <li>Live prices come from Yahoo Finance, delayed up to about a minute, and are not part of the estimate.</li>
        </ul>
      </div>
      <div className="mo-panel">
        <h3>Model</h3>
        <p className="mo-mini mo-mono">
          {final.run.model} · {final.run.input_count ?? "—"} inputs · {(final.run.train_rows ?? 0).toLocaleString("en-IN")} stock-days · labels through {day(final.run.train_end)} · refit {final.run.refit ?? "monthly"}
        </p>
        <p className="mo-mini">A nightly refit is under test as a separate model. This screen switches only if it passes its locked test.</p>
      </div>
    </aside>
  );
}
