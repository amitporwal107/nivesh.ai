/**
 * Simulation studio · Trading day — the run's timeline folded for a view of one trading day.
 *
 * GET /simulations/{sid}/timeline answers the clock rows (one per phase reached) and the run's events after `after_seq`.
 * The events are read incrementally (only those after the last seq held) and folded into:
 *   - buckets: per clock step ("{session date}|{HH:MM} IST"), the count of each event type, the events per agent lane
 *     (with the most severe tone) and the tasks that went to an exception state. Counters, lane dots and end-of-day
 *     counts are sums of the buckets of one session, so they cover every event, not only the listed ones.
 *   - feed: the shown events, oldest first, capped; a run of SIGNAL_EXPIRED / SIGNAL_SUPPRESSED rows from the same
 *     producer is folded into one row with a count (a session close expires hundreds of signals at once).
 * An event without its own sim_time ran in the step of the next CLOCK_ADVANCED (simTimeOf in the desk simulator model);
 * until that clock row arrives it waits in `pending` (the step in progress) and is not counted.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { deskGet } from "../../../api";
import type { EventRow, SimulationRow } from "../../../types";
import { describe, isException, isShown, sessionsOf, type ClockEventRow, type TimelinePage, type Tone } from "../../../screens/simulator/model";

// ── the schedule of one simulated session (contracts.CLOCK_SCHEDULE_IST) ─────────────────────────────────────────────

export const PHASES = ["PREMARKET", "SCAN", "PROPOSALS", "OPEN", "CLOSE", "EOD"] as const;
export type Phase = (typeof PHASES)[number];

export const PHASE_INFO: Record<Phase, { at: string; n: string; chip: string; d: string }> = {
  PREMARKET: { at: "08:30", n: "Pre-market check", chip: "Pre-market", d: "Tech Support checks that the session's end-of-day data is published, and the session cycle opens." },
  SCAN: { at: "08:45", n: "Scan", chip: "Scan", d: "The AI Trader scans the universe on data published up to 08:45 and records signals." },
  PROPOSALS: { at: "09:00", n: "Proposals", chip: "Proposals", d: "For each chosen signal the Trading Assistant drafts a plan, Risk & Operations checks it and Middle Office decides." },
  OPEN: { at: "09:15", n: "Market open", chip: "Open", d: "The session opens on the replay clock. A run with paper execution fills its approved plans here, in simulation, from the session's own row." },
  CLOSE: { at: "15:30", n: "Market close", chip: "Close", d: "The session closes. Orders still waiting are settled or expire, and open positions are marked at the close. Positions are not closed until Phase 3." },
  EOD: { at: "18:00", n: "End of day", chip: "End of day", d: "Unused signals and unanswered approvals of the session expire, and the day is summarised." },
};

export const isPhase = (v: unknown): v is Phase => typeof v === "string" && (PHASES as readonly string[]).includes(v);
export const phaseAt = (hhmm: string): Phase | null => PHASES.find((p) => PHASE_INFO[p].at === hhmm) ?? null;

/** The track's axis: 08:00 → 18:30 IST, in seconds of the day. */
export const D0 = 8 * 3600;
export const D1 = 18.5 * 3600;
export const secOf = (hhmm: string): number => { const [h, m] = hhmm.split(":").map(Number); return h * 3600 + m * 60; };
export const frac = (s: number): number => Math.max(0, Math.min(1, (s - D0) / (D1 - D0)));
export const pctOf = (s: number): string => `${(frac(s) * 100).toFixed(2)}%`;

/**
 * Bands of the market day on the track header (the design's bands; Phase 1 has no entry cutoff rule, so the design's
 * "Entry cutoff" band is part of Intraday). The replay's clock phases fall inside them.
 */
export const BANDS: { a: string; b: string; t: string; c: string }[] = [
  { a: "08:00", b: "09:00", t: "PRE-MARKET", c: "var(--ink-2)" },
  { a: "09:00", b: "09:15", t: "PRE-OPEN", c: "var(--amber)" },
  { a: "09:15", b: "15:30", t: "INTRADAY", c: "var(--mint)" },
  { a: "15:30", b: "18:00", t: "CLOSE AND POST-CLOSE", c: "var(--indigo)" },
  { a: "18:00", b: "18:30", t: "EVENING", c: "var(--ink-2)" },
];

/** IST date and HH:MM of an ISO instant (India has no daylight saving: UTC+05:30). */
export function ist(iso: string | null | undefined): { date: string; hhmm: string; sec: number } | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return null;
  const s = new Date(t + 19_800_000).toISOString();
  const hhmm = s.slice(11, 16);
  return { date: s.slice(0, 10), hhmm, sec: secOf(hhmm) + Number(s.slice(17, 19)) };
}

const keyOf = (iso: string | null | undefined): string | null => { const x = ist(iso); return x ? `${x.date}|${x.hhmm}` : null; };
export const stepKey = (date: string, phase: Phase): string => `${date}|${PHASE_INFO[phase].at}`;

// ── lanes ────────────────────────────────────────────────────────────────────────────────────────────────────────────

export type LaneId = "trader" | "strat" | "risk" | "mo" | "ops" | "tlm" | "exec" | "orch" | "scn";

/** The design's nine lanes, in its order. Lanes whose work the screen does not draw carry why. */
export const LANES: { id: LaneId; n: string; phase?: number; note?: string }[] = [
  { id: "trader", n: "AI Trader" },
  { id: "strat", n: "Trading Assistant" },
  { id: "risk", n: "Risk & Operations" },
  { id: "mo", n: "Middle Office" },
  { id: "ops", n: "Tech Support" },
  { id: "tlm", n: "Lifecycle manager", phase: 3, note: "PHASE 3 · NO POSITIONS TO MANAGE" },
  { id: "exec", n: "Sim exchange", phase: 2, note: "NOT SHOWN YET · FILLS ARE RECORDED" },
  { id: "orch", n: "Orchestrator" },
  { id: "scn", n: "Scenarios", phase: 3, note: "PHASE 3 · NO SCENARIO INJECTION" },
];

const AGENT_LANE: Record<string, LaneId> = { AI_TRADER: "trader", TRADING_ASSISTANT: "strat", RISK_OPS: "risk", MIDDLE_OFFICE: "mo", TECH_SUPPORT: "ops" };

/** The lane of an event: an agent task's agent, else the producing agent; handoffs, the clock, the session close and
 * people are the orchestrator's lane. */
export function laneOf(e: EventRow): LaneId {
  const p = (e.payload ?? {}) as Record<string, unknown>;
  if (e.event_type === "TASK_STATE_CHANGED" && typeof p.agent === "string") return AGENT_LANE[p.agent] ?? "orch";
  if (e.event_type === "HANDOFF_RECORDED") return "orch";
  return AGENT_LANE[String(e.producer ?? "").split("@")[0]] ?? "orch";
}

const RANK: Record<Tone, number> = { ink: 0, indigo: 1, mint: 2, amber: 3, danger: 4 };

// ── fold ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Bucket {
  types: Record<string, number>;
  lanes: Partial<Record<LaneId, { n: number; tone: Tone }>>;
  exc: string[];
}

export interface FeedItem { e: EventRow; count: number }

export interface DayTimeline {
  clock: ClockEventRow[];
  clockSeqs: { seq: number; sim_time: string }[];
  feed: FeedItem[];
  dropped: number;
  buckets: Record<string, Bucket>;
  pending: Bucket;
  completed: string[];
  lastSeq: number;
  total: number;
  more: boolean;
}

export const FEED_CAP = 400;
const emptyBucket = (): Bucket => ({ types: {}, lanes: {}, exc: [] });
export const emptyDay = (): DayTimeline => ({ clock: [], clockSeqs: [], feed: [], dropped: 0, buckets: {}, pending: emptyBucket(), completed: [], lastSeq: 0, total: 0, more: false });

const EXC_STATES = new Set(["FAILED", "REJECTED", "ESCALATED", "RETRY_PENDING", "TIMED_OUT", "BLOCKED"]);
const FOLDED = new Set(["SIGNAL_EXPIRED", "SIGNAL_SUPPRESSED"]);

function addTo(b: Bucket, e: EventRow) {
  b.types[e.event_type] = (b.types[e.event_type] ?? 0) + 1;
  const p = (e.payload ?? {}) as Record<string, unknown>;
  if (e.event_type === "TASK_STATE_CHANGED" && EXC_STATES.has(String(p.to)) && p.task_id) b.exc.push(String(p.task_id));
  if (!isShown(e)) return;
  const lane = laneOf(e);
  const tone: Tone = isException(e) && describe(e).tone === "ink" ? "danger" : describe(e).tone;
  const cur = b.lanes[lane];
  b.lanes[lane] = cur ? { n: cur.n + 1, tone: RANK[tone] > RANK[cur.tone] ? tone : cur.tone } : { n: 1, tone };
}

function mergeInto(dst: Bucket, src: Bucket) {
  for (const [k, n] of Object.entries(src.types)) dst.types[k] = (dst.types[k] ?? 0) + n;
  for (const [k, v] of Object.entries(src.lanes) as [LaneId, { n: number; tone: Tone }][]) {
    const cur = dst.lanes[k];
    dst.lanes[k] = cur ? { n: cur.n + v.n, tone: RANK[v.tone] > RANK[cur.tone] ? v.tone : cur.tone } : { ...v };
  }
  dst.exc.push(...src.exc);
}

const cloneBucket = (b: Bucket): Bucket => ({ types: { ...b.types }, lanes: Object.fromEntries(Object.entries(b.lanes).map(([k, v]) => [k, { ...v! }])), exc: [...b.exc] });

export function foldDay(prev: DayTimeline, events: EventRow[], clock: ClockEventRow[]): DayTimeline {
  const st: DayTimeline = { ...prev, clock, clockSeqs: [...prev.clockSeqs], feed: [...prev.feed], buckets: { ...prev.buckets }, pending: cloneBucket(prev.pending) };
  const touched = new Set<string>();
  const bucket = (k: string): Bucket => {
    if (!touched.has(k)) { st.buckets[k] = st.buckets[k] ? cloneBucket(st.buckets[k]) : emptyBucket(); touched.add(k); }
    return st.buckets[k];
  };
  const done = new Set(prev.completed);
  for (const e of events) {
    if (e.seq <= st.lastSeq) continue;
    st.lastSeq = e.seq;
    st.total += 1;
    const p = (e.payload ?? {}) as Record<string, unknown>;
    if (e.event_type === "TASK_STATE_CHANGED" && String(p.to) === "COMPLETED" && p.task_id) done.add(String(p.task_id));
    const k = keyOf(e.sim_time);
    if (e.event_type === "CLOCK_ADVANCED" && e.sim_time && k) {
      st.clockSeqs.push({ seq: e.seq, sim_time: e.sim_time });
      mergeInto(bucket(k), st.pending);
      st.pending = emptyBucket();
      addTo(bucket(k), e);
    } else if (k) {
      addTo(bucket(k), e);
    } else {
      addTo(st.pending, e);
    }
    if (!isShown(e)) continue;
    const last = st.feed[st.feed.length - 1];
    if (last && FOLDED.has(e.event_type) && last.e.event_type === e.event_type && last.e.producer === e.producer) {
      st.feed[st.feed.length - 1] = { e: last.e, count: last.count + 1 };
    } else {
      st.feed.push({ e, count: 1 });
    }
  }
  if (st.feed.length > FEED_CAP) {
    st.dropped += st.feed.length - FEED_CAP;
    st.feed = st.feed.slice(-FEED_CAP);
  }
  st.completed = Array.from(done);
  return st;
}

const PAGE = 2000;
const MAX_PAGES = 25;

/**
 * The run's timeline for the Trading day view, read incrementally (after_seq = the last seq held). One read takes up to
 * 25 pages of 2,000 events; `more` says the read stopped there (the view offers to read on).
 */
export function useDayTimeline(sid: string | null, enabled: boolean) {
  const qc = useQueryClient();
  const key = ["desk", "studio", "day", sid, "timeline"] as const;
  return useQuery({
    queryKey: key,
    enabled: !!sid && enabled,
    queryFn: async (): Promise<DayTimeline> => {
      let st = qc.getQueryData<DayTimeline>(key) ?? emptyDay();
      let more = false;
      for (let i = 0; ; i++) {
        const r = await deskGet<TimelinePage>(`/simulations/${encodeURIComponent(sid!)}/timeline`, { after_seq: st.lastSeq, limit: PAGE });
        const evs = r.events ?? [];
        st = foldDay(st, evs, r.clock ?? st.clock);
        if (evs.length < PAGE) break;
        if (i + 1 >= MAX_PAGES) { more = true; break; }
      }
      return { ...st, more };
    },
  });
}

// ── one day of the run ───────────────────────────────────────────────────────────────────────────────────────────────

export interface DayView {
  reached: Map<Phase, ClockEventRow>;
  types: Record<string, number>;
  lanes: { lane: LaneId; phase: Phase; n: number; tone: Tone }[];
  recovered: number;
  eod: Record<string, number> | null;
}

/** Sums of the buckets of one session's reached clock steps. */
export function dayView(tl: DayTimeline | undefined, session: string | null): DayView {
  const reached = new Map<Phase, ClockEventRow>();
  const types: Record<string, number> = {};
  const lanes: DayView["lanes"] = [];
  const exc = new Set<string>();
  let eod: Record<string, number> | null = null;
  if (!tl || !session) return { reached, types, lanes, recovered: 0, eod };
  for (const row of tl.clock) {
    if (row.session_date !== session || !isPhase(row.phase)) continue;
    reached.set(row.phase, row);
    const b = tl.buckets[keyOf(row.sim_time) ?? ""];
    if (!b) { if (row.phase === "EOD") eod = {}; continue; }
    for (const [k, n] of Object.entries(b.types)) types[k] = (types[k] ?? 0) + n;
    for (const [lane, v] of Object.entries(b.lanes) as [LaneId, { n: number; tone: Tone }][]) lanes.push({ lane, phase: row.phase, n: v.n, tone: v.tone });
    b.exc.forEach((t) => exc.add(t));
    if (row.phase === "EOD") eod = b.types;
  }
  const done = new Set(tl.completed);
  return { reached, types, lanes, recovered: Array.from(exc).filter((t) => done.has(t)).length, eod };
}

/** Session and phase of the step a run will take next (events without a sim time and no later clock row ran there). */
export function nextStep(sim: SimulationRow | undefined): { session: string | null; phase: Phase | null } {
  const ss = sessionsOf(sim);
  if (!sim || !ss.length) return { session: null, phase: null };
  const i = sim.step_seq ?? 0;
  if (i >= ss.length * PHASES.length) return { session: ss[ss.length - 1], phase: null };
  return { session: ss[Math.floor(i / PHASES.length)] ?? null, phase: PHASES[i % PHASES.length] };
}

/** Session and phase an event belongs to: its own sim time, else the next clock step's, else the step in progress. */
export function placeOf(at: string | null, next: { session: string | null; phase: Phase | null }): { session: string | null; phase: Phase | null; live: boolean } {
  const x = ist(at);
  if (!x) return { session: next.session, phase: next.phase, live: true };
  return { session: x.date, phase: phaseAt(x.hhmm), live: false };
}

export const MODE_NAME: Record<string, string> = { HISTORICAL_REPLAY: "Historical replay", ACCELERATED_REPLAY: "Accelerated replay", SCENARIO: "Scenario simulation", LIVE_SHADOW: "Live shadow" };

export const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;
