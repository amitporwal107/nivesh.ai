// Tiny className combiner — keeps V3 free of clsx coupling. Matches lib/utils signature.
export function cn(...args) {
  return args
    .flat(Infinity)
    .filter(Boolean)
    .filter((x) => typeof x === "string")
    .join(" ")
    .trim();
}
