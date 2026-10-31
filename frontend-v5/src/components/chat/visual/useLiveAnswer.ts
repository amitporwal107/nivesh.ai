/**
 * An answer that keeps itself current (`refresh` in the payload; the open-trades answer on the user's broker book, owner 31 Oct 2026:
 * "show live data refreshed every 5 seconds").
 *
 * The page asks `refresh.path` every `interval_s` seconds (never faster) and swaps in the blocks the server sends, by id. The server, not
 * this hook, decides what is live: it answers from a cache of the broker book (a broker is read at most once in 15 s however many tabs
 * ask) and the platform's Kite feed, and it says when to stop asking (`refresh.active: false`, e.g. after the close).
 *
 * It asks only while all of these hold, so nothing polls for nothing:
 *   - the tab is visible,
 *   - the answer is on screen (IntersectionObserver),
 *   - the answer was built today (an older answer in the thread stays the record of that day),
 *   - the server has not said to stop.
 * A failed ask keeps the blocks already shown, says the feed was lost with the time of the last good read, backs off (interval × 2, ×4 …,
 * at most a minute) and stops after three failures in a row. Nothing here ever shows a number the server did not send.
 */
import { useEffect, useRef, useState } from "react";
import { http } from "@/services/api/http";
import type { AnswerRefresh } from "./schema";

export type LiveKind = "static" | "live" | "paused" | "closed" | "lost";
export interface LiveAnswer {
  kind: LiveKind;
  /** Server blocks by id (raw: the caller parses them with parseBlock and keeps the original when one does not parse). */
  blocks: Record<string, unknown>;
  mode: string | null;
  /** Seconds since the last good answer (counted from the answer's own build time until the first poll). */
  secondsAgo: number | null;
  lastOkAt: number | null;
  /** Why the server told the page to stop. */
  why: string | null;
}

const MAX_FAILURES = 3;
const MAX_BACKOFF_MS = 60_000;
const IST = "Asia/Kolkata";
const day = (ms: number) => new Date(ms).toLocaleDateString("en-CA", { timeZone: IST });

interface LiveBody { blocks?: unknown; mode?: unknown; refresh?: { active?: unknown; why?: unknown } }

export function useLiveAnswer(refresh: AnswerRefresh | null, generatedAt: string | null, box: HTMLElement | null): LiveAnswer {
  const builtAt = generatedAt ? Date.parse(generatedAt) : NaN;
  const eligible = !!refresh && Number.isFinite(builtAt) && day(builtAt) === day(Date.now());
  const [kind, setKind] = useState<LiveKind>("static");
  const [blocks, setBlocks] = useState<Record<string, unknown>>({});
  const [mode, setMode] = useState<string | null>(null);
  const [why, setWhy] = useState<string | null>(null);
  const [lastOkAt, setLastOkAt] = useState<number | null>(null);
  const [now, setNow] = useState<number>(() => Date.now());
  const inView = useRef(true);

  useEffect(() => {
    if (!eligible || !refresh) { setKind("static"); return; }
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let ctl: AbortController | undefined;
    let failures = 0;
    let last = builtAt;
    setKind("live");
    setLastOkAt(builtAt);
    const visible = () => document.visibilityState === "visible" && inView.current;
    const wait = () => Math.min(MAX_BACKOFF_MS, refresh.interval_s * 1000 * 2 ** failures);
    const schedule = () => { if (!stopped) timer = setTimeout(() => void tick(), wait()); };
    const tick = async () => {
      if (stopped) return;
      if (!visible()) { setKind("paused"); schedule(); return; }
      ctl = new AbortController();
      try {
        const r = await http<LiveBody>({ path: refresh.path, signal: ctl.signal, noRetry: true, timeoutMs: 8_000 });
        if (stopped) return;
        const body = r.data ?? {};
        const list = Array.isArray(body.blocks) ? (body.blocks as Array<Record<string, unknown>>) : [];
        const next: Record<string, unknown> = {};
        for (const b of list) if (b && typeof b.id === "string" && refresh.block_ids.includes(b.id)) next[b.id] = b;
        failures = 0;
        last = Date.now();
        setBlocks((cur) => ({ ...cur, ...next }));
        setMode(typeof body.mode === "string" ? body.mode : null);
        setLastOkAt(last);
        if (body.refresh && body.refresh.active === false) {
          stopped = true;
          setWhy(typeof body.refresh.why === "string" ? body.refresh.why : null);
          setKind("closed");
          return;
        }
        setKind("live");
      } catch {
        if (stopped) return;
        failures += 1;
        setKind("lost");
        if (failures >= MAX_FAILURES) { stopped = true; return; }
      }
      schedule();
    };
    const onVisible = () => {
      if (document.visibilityState !== "visible" || stopped) return;
      clearTimeout(timer);
      // Back on screen after a pause: ask now when the last good answer is older than one interval.
      if (Date.now() - last >= refresh.interval_s * 1000) void tick(); else schedule();
    };
    document.addEventListener("visibilitychange", onVisible);
    let io: IntersectionObserver | undefined;
    if (box && typeof IntersectionObserver !== "undefined") {
      io = new IntersectionObserver((es) => { inView.current = es.some((e) => e.isIntersecting); if (inView.current) onVisible(); });
      io.observe(box);
    }
    schedule();
    return () => { stopped = true; clearTimeout(timer); ctl?.abort(); document.removeEventListener("visibilitychange", onVisible); io?.disconnect(); };
  }, [eligible, refresh?.path, refresh?.interval_s, builtAt, box]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (kind !== "live" && kind !== "paused" && kind !== "lost") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [kind]);

  return { kind, blocks, mode, why, lastOkAt, secondsAgo: lastOkAt == null ? null : Math.max(0, Math.floor((now - lastOkAt) / 1000)) };
}
