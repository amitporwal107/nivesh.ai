import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium",
  {
    variants: {
      tone: {
        default: "bg-surface-2 text-ink-2",
        accent: "bg-[rgb(var(--accent)/0.12)] text-accent",
        good: "bg-[rgb(var(--pos)/0.10)] text-pos",
        warm: "bg-[rgb(var(--warm)/0.10)] text-warm",
        neg: "bg-[rgb(var(--neg)/0.10)] text-neg",
        outline: "border border-hairline-2 text-ink-2",
      },
    },
    defaultVariants: { tone: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
