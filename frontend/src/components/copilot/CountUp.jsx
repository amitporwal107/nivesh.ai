import React, { useEffect, useState } from "react";

/**
 * Smooth number count-up animation. No extra deps — pure React + requestAnimationFrame.
 *
 * Props:
 *   value      → target numeric value (the "after")
 *   from       → starting value (the "before")
 *   duration   → ms, default 800
 *   format     → optional (n) => string formatter
 *   className
 */
const CountUp = ({ value, from = 0, duration = 800, format, className = "" }) => {
  const [current, setCurrent] = useState(from);

  useEffect(() => {
    if (typeof value !== "number" || typeof from !== "number") {
      setCurrent(value);
      return;
    }
    let raf;
    const start = performance.now();
    const delta = value - from;
    const tick = (t) => {
      const elapsed = t - start;
      const p = Math.min(elapsed / duration, 1);
      // easeOutCubic
      const eased = 1 - Math.pow(1 - p, 3);
      setCurrent(from + delta * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => raf && cancelAnimationFrame(raf);
  }, [value, from, duration]);

  const display = typeof current === "number" ? (format ? format(current) : current.toFixed(2)) : current;
  return <span className={className}>{display}</span>;
};

export default CountUp;
