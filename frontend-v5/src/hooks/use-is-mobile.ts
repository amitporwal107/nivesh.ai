import { useEffect, useState } from "react";

/**
 * useIsMobile — true when the viewport is at or below the mobile breakpoint.
 *
 * The public marketing pages (Homepage, Product, Pricing, MarketingShell) are
 * built with inline `style` objects rather than Tailwind classes, so they can't
 * use responsive `sm:`/`md:` prefixes. This hook lets them switch layout values
 * (grid columns, paddings, font sizes) at a single phone breakpoint instead.
 */
export function useIsMobile(breakpointPx = 768): boolean {
  const query = `(max-width: ${breakpointPx}px)`;
  const [isMobile, setIsMobile] = useState<boolean>(() =>
    typeof window !== "undefined" ? window.matchMedia(query).matches : false,
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setIsMobile(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return isMobile;
}
