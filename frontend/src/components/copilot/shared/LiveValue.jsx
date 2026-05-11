import React, { useEffect, useRef, useState } from "react";

/**
 * LiveValue — number cell with tabular-nums + inline tick fade on change.
 * Doc 06 §6.2.
 *
 * Props:
 *   value: number
 *   format: (v) => string
 *   delta: number (optional micro-arrow)
 *   paused: boolean (disables animation)
 */
const LiveValue = ({
  value,
  format = (v) => (v == null ? "—" : String(v)),
  delta,
  paused = false,
  className = "",
  testId,
}) => {
  const prevRef = useRef(value);
  const [tickClass, setTickClass] = useState("");

  useEffect(() => {
    if (paused) return;
    const prev = prevRef.current;
    if (typeof value === "number" && typeof prev === "number" && value !== prev) {
      setTickClass(value > prev ? "cp-tick-up" : "cp-tick-down");
      const t = setTimeout(() => setTickClass(""), 360);
      prevRef.current = value;
      return () => clearTimeout(t);
    }
    prevRef.current = value;
  }, [value, paused]);

  const deltaColor =
    delta == null ? "" :
    delta > 0 ? "text-[color:var(--cp-state-positive)]" :
    delta < 0 ? "text-[color:var(--cp-state-negative)]" : "text-slate-400";

  const deltaSymbol = delta == null ? "" : delta > 0 ? "▲" : delta < 0 ? "▼" : "·";

  return (
    <span data-testid={testId} className={`inline-flex items-baseline gap-1 cp-num ${className}`}>
      <span className={tickClass}>{format(value)}</span>
      {delta != null && (
        <span className={`text-[10px] ${deltaColor}`}>{deltaSymbol}{Math.abs(delta).toFixed(2)}%</span>
      )}
    </span>
  );
};

export default LiveValue;
