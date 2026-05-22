import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { ChevronLeft, ChevronRight } from "lucide-react";

/**
 * Horizontal scroll-snap card strip with grid fallback.
 *   - mobile  → strip with peek + dots
 *   - desktop → grid if children.length ≤ desktopColumns, else strip with arrows
 * Wraps the existing `.v3-hscroll` class (hides scrollbar); adds snap, fade,
 * dots, and arrow paging on top.
 */
export default function CardStrip({
  children,
  variant = "auto",
  desktopColumns = 3,
  peek = 0.2,
  ariaLabel,
  showDots = true,
  showArrows = true,
  gap = 10,
}) {
  const ctx = useOutletContext();
  const viewport = ctx?.viewport || "mobile";
  const items = useMemo(() => React.Children.toArray(children).filter(Boolean), [children]);
  const count = items.length;

  const mode = useMemo(() => {
    if (variant === "grid") return "grid";
    if (variant === "strip") return "strip";
    if (viewport === "desktop" && count <= desktopColumns) return "grid";
    return "strip";
  }, [variant, viewport, count, desktopColumns]);

  if (count === 0) return null;

  if (mode === "grid") {
    return (
      <div
        role="region"
        aria-label={ariaLabel}
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${desktopColumns}, 1fr)`,
          gap,
        }}
      >
        {items}
      </div>
    );
  }

  return (
    <StripMode
      items={items}
      gap={gap}
      peek={peek}
      ariaLabel={ariaLabel}
      showDots={showDots}
      showArrows={showArrows && viewport === "desktop"}
    />
  );
}

function StripMode({ items, gap, peek, ariaLabel, showDots, showArrows }) {
  const ref = useRef(null);
  const rafRef = useRef(0);
  const [active, setActive] = useState(0);
  const [atStart, setAtStart] = useState(true);
  const [atEnd, setAtEnd] = useState(false);
  const count = items.length;

  const recompute = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const childWidth = el.firstElementChild?.firstElementChild?.offsetWidth ?? el.clientWidth;
    const idx = Math.round(el.scrollLeft / (childWidth + gap));
    setActive(Math.max(0, Math.min(count - 1, idx)));
    setAtStart(el.scrollLeft <= 2);
    setAtEnd(el.scrollLeft + el.clientWidth >= el.scrollWidth - 2);
  }, [count, gap]);

  const onScroll = useCallback(() => {
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      recompute();
    });
  }, [recompute]);

  useEffect(() => {
    recompute();
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [recompute]);

  const scrollByOne = useCallback((dir) => {
    const el = ref.current;
    if (!el) return;
    const childWidth = el.firstElementChild?.firstElementChild?.offsetWidth ?? el.clientWidth;
    el.scrollBy({ left: dir * (childWidth + gap), behavior: "smooth" });
  }, [gap]);

  const scrollToIndex = useCallback((i) => {
    const el = ref.current;
    if (!el) return;
    const childWidth = el.firstElementChild?.firstElementChild?.offsetWidth ?? el.clientWidth;
    el.scrollTo({ left: i * (childWidth + gap), behavior: "smooth" });
  }, [gap]);

  const onKeyDown = useCallback((e) => {
    if (e.key === "ArrowRight") { e.preventDefault(); scrollByOne(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); scrollByOne(-1); }
    else if (e.key === "Home") { e.preventDefault(); scrollToIndex(0); }
    else if (e.key === "End") { e.preventDefault(); scrollToIndex(count - 1); }
  }, [scrollByOne, scrollToIndex, count]);

  const flexBasis = `calc((100% - ${gap}px) / (1 + ${peek}))`;

  return (
    <div
      role="region"
      aria-roledescription="carousel"
      aria-label={ariaLabel}
      style={{ position: "relative" }}
    >
      <div
        ref={ref}
        className="v3-hscroll"
        tabIndex={0}
        onScroll={onScroll}
        onKeyDown={onKeyDown}
        style={{
          display: "flex",
          gap,
          scrollSnapType: "x mandatory",
          paddingBottom: showDots ? 14 : 0,
        }}
      >
        {items.map((child, i) => (
          <div
            key={i}
            role="group"
            aria-roledescription="slide"
            aria-label={`Card ${i + 1} of ${count}`}
            style={{
              flex: `0 0 ${flexBasis}`,
              scrollSnapAlign: "start",
              minWidth: 0,
            }}
          >
            {child}
          </div>
        ))}
      </div>

      {!atEnd && (
        <div
          aria-hidden
          style={{
            position: "absolute",
            top: 0,
            right: 0,
            bottom: showDots ? 14 : 0,
            width: 36,
            pointerEvents: "none",
            background: "linear-gradient(90deg, transparent, var(--v3-bg-1))",
          }}
        />
      )}

      {showArrows && (
        <>
          <ArrowButton dir="left" disabled={atStart} onClick={() => scrollByOne(-1)} />
          <ArrowButton dir="right" disabled={atEnd} onClick={() => scrollByOne(1)} />
        </>
      )}

      {showDots && count > 1 && <Dots count={count} active={active} onJump={scrollToIndex} />}
    </div>
  );
}

function ArrowButton({ dir, disabled, onClick }) {
  const Icon = dir === "left" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      aria-label={dir === "left" ? "Previous card" : "Next card"}
      onClick={onClick}
      disabled={disabled}
      style={{
        position: "absolute",
        top: "50%",
        [dir]: -10,
        transform: "translateY(-50%)",
        width: 28, height: 28, borderRadius: 999,
        background: "var(--v3-bg-3)",
        border: "1px solid var(--v3-line)",
        display: "grid", placeItems: "center",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.35 : 0.95,
        color: "var(--v3-ink-2)",
        boxShadow: "0 2px 6px rgba(0,0,0,0.18)",
      }}
    >
      <Icon size={14} />
    </button>
  );
}

function Dots({ count, active, onJump }) {
  if (count <= 5) {
    return (
      <div style={{ display: "flex", gap: 5, justifyContent: "center", marginTop: -10 }}>
        {Array.from({ length: count }).map((_, i) => (
          <button
            key={i}
            type="button"
            aria-label={`Go to card ${i + 1}`}
            onClick={() => onJump(i)}
            style={{
              width: 6, height: 6, borderRadius: 999,
              border: i === active ? "none" : "1px solid var(--v3-ink-4)",
              background: i === active ? "var(--v3-saffron)" : "transparent",
              padding: 0, cursor: "pointer",
            }}
          />
        ))}
      </div>
    );
  }
  return (
    <div
      className="v3-data"
      style={{
        textAlign: "center", marginTop: -10, fontSize: 10,
        color: "var(--v3-ink-3)",
      }}
    >
      {active + 1} / {count}
    </div>
  );
}
