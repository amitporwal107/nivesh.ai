import { Inbox } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  action?: { label: string; onClick: () => void };
  className?: string;
}

export function EmptyState({ title, description, icon, action, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center text-center py-16 px-6", className)}>
      <div className="grid place-items-center h-14 w-14 rounded-full bg-surface-2 text-ink-3 mb-4">
        {icon ?? <Inbox className="h-6 w-6" aria-hidden />}
      </div>
      <h3 className="font-display text-2xl tracking-tightish">{title}</h3>
      {description && <p className="text-ink-2 mt-2 max-w-md leading-relaxed">{description}</p>}
      {action && (
        <Button variant="accent" onClick={action.onClick} className="mt-5">
          {action.label}
        </Button>
      )}
    </div>
  );
}
