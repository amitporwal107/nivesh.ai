import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ErrorStateProps {
  title?: string;
  description?: string;
  error?: Error | unknown;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({
  title = "Something went wrong",
  description,
  error,
  onRetry,
  className,
}: ErrorStateProps) {
  const msg = description ?? (error instanceof Error ? error.message : "Please try again.");
  return (
    <div className={cn("flex flex-col items-center text-center py-16 px-6", className)}>
      <div className="grid place-items-center h-14 w-14 rounded-full bg-[rgb(var(--neg)/0.10)] text-neg mb-4">
        <AlertTriangle className="h-6 w-6" aria-hidden />
      </div>
      <h3 className="font-display text-2xl tracking-tightish">{title}</h3>
      <p className="text-ink-2 mt-2 max-w-md leading-relaxed">{msg}</p>
      {onRetry && (
        <Button variant="outline" onClick={onRetry} className="mt-5">
          Try again
        </Button>
      )}
    </div>
  );
}
