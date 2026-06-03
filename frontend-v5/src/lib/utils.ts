import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn-style className combiner: clsx semantics + tailwind dedupe. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
