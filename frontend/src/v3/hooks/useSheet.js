import { useCallback, useEffect, useState } from "react";

// Picker behaviour from spec §2.7: bottom sheet on mobile, anchored popover on desktop.
export function useSheet(initial = false) {
  const [open, setOpen] = useState(initial);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open]);

  const toggle = useCallback(() => setOpen((v) => !v), []);
  const close = useCallback(() => setOpen(false), []);
  const show = useCallback(() => setOpen(true), []);

  return { open, setOpen, toggle, close, show };
}
