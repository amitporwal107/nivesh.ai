import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
/** shadcn-style className combiner: clsx semantics + tailwind dedupe. */
export function cn(...inputs) {
    return twMerge(clsx(inputs));
}
