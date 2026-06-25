/**
 * use-animate — tiny, dependency-free motion primitives for entrance polish.
 *
 * All three honour `prefers-reduced-motion`: reduced-motion users get the
 * final value immediately (no animation), so the page is still correct and
 * accessible — the motion is pure decoration layered on real data.
 */
import { useEffect, useState } from "react";

/** True when the OS/browser asks for minimised motion. SSR-safe. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return reduced;
}

const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

/**
 * Drives an eased 0→1 progress value over `duration` ms, starting after
 * `delay` ms. Use it to sweep rings, fill bars and draw sparklines on mount.
 * Snaps straight to 1 under reduced-motion.
 */
export function useMountProgress(duration = 1100, delay = 0): number {
  const reduced = usePrefersReducedMotion();
  const [p, setP] = useState(0);
  useEffect(() => {
    if (reduced) { setP(1); return; }
    let raf = 0;
    let start = 0;
    const begin = window.setTimeout(() => {
      const step = (t: number) => {
        if (!start) start = t;
        const k = Math.min(1, (t - start) / duration);
        setP(easeOutCubic(k));
        if (k < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    }, delay);
    return () => { window.clearTimeout(begin); cancelAnimationFrame(raf); };
  }, [duration, delay, reduced]);
  return p;
}

/**
 * Counts a value up from 0 → `target` on mount and returns the current value.
 * `target` is assumed stable from first render (the dashboard only mounts its
 * cards once data has resolved), so the count runs exactly once.
 */
export function useCountUp(target: number, duration = 1100, delay = 0): number {
  const p = useMountProgress(duration, delay);
  return target * p;
}
