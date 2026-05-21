import { useEffect, useState } from "react";

// Spec §3: distinct mobile (<768) and desktop (>=1024) layouts; tablet uses desktop shell with collapsed rail.
const QUERIES = {
  mobile: "(max-width: 767.98px)",
  tablet: "(min-width: 768px) and (max-width: 1023.98px)",
  desktop: "(min-width: 1024px)",
};

function pick() {
  if (typeof window === "undefined") return "desktop";
  if (window.matchMedia(QUERIES.mobile).matches) return "mobile";
  if (window.matchMedia(QUERIES.tablet).matches) return "tablet";
  return "desktop";
}

export function useBreakpoint() {
  const [bp, setBp] = useState(pick);

  useEffect(() => {
    const mql = [QUERIES.mobile, QUERIES.tablet, QUERIES.desktop].map((q) => window.matchMedia(q));
    const onChange = () => setBp(pick());
    mql.forEach((m) => m.addEventListener("change", onChange));
    return () => mql.forEach((m) => m.removeEventListener("change", onChange));
  }, []);

  return {
    breakpoint: bp,
    isMobile: bp === "mobile",
    isTablet: bp === "tablet",
    isDesktop: bp === "desktop",
    isMobileOrTablet: bp !== "desktop",
  };
}
