import { useEffect, useState, type ReactNode } from "react";
import { usePrefersReducedMotion } from "@/hooks/use-animate";
import { cn } from "@/lib/utils";

interface RevealProps {
  children: ReactNode;
  /** Stagger offset in ms. Increasing it across siblings yields the
   *  orchestrated top-to-bottom entrance. */
  delay?: number;
  className?: string;
}

/**
 * Fades + rises its children in once on mount. Renders fully visible
 * immediately for reduced-motion users. Used to choreograph the dashboard's
 * entrance — wrap each major block with an increasing `delay`.
 */
export function Reveal({ children, delay = 0, className }: RevealProps) {
  const reduced = usePrefersReducedMotion();
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setShown(true), 20);
    return () => window.clearTimeout(t);
  }, []);
  const visible = reduced || shown;
  return (
    <div
      className={cn(
        "transition-[opacity,transform] duration-700 ease-[cubic-bezier(.2,.7,.2,1)] will-change-transform motion-reduce:transition-none",
        visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4",
        className,
      )}
      style={reduced ? undefined : { transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}
