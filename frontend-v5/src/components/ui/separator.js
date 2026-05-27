import { jsx as _jsx } from "react/jsx-runtime";
import * as React from "react";
import * as SeparatorPrimitive from "@radix-ui/react-separator";
import { cn } from "@/lib/utils";
export const Separator = React.forwardRef(({ className, orientation = "horizontal", decorative = true, ...props }, ref) => (_jsx(SeparatorPrimitive.Root, { ref: ref, orientation: orientation, decorative: decorative, className: cn("shrink-0 bg-[rgb(var(--line)/0.10)]", orientation === "horizontal" ? "h-px w-full" : "h-full w-px", className), ...props })));
Separator.displayName = SeparatorPrimitive.Root.displayName;
