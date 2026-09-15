import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "@/services/api/errors";

interface ErrorStateProps {
  title?: string;
  description?: string;
  error?: Error | unknown;
  onRetry?: () => void;
  className?: string;
}

/**
 * Plain-language message per failure kind. The raw error text (a Zod contract
 * dump, an HTTP detail) never leads: it stays behind "Details" for support and
 * in Sentry, and a correlation id is shown so a user can quote it.
 */
function friendlyMessage(error: unknown): string {
  const kind = error instanceof ApiError ? error.kind : undefined;
  switch (kind) {
    case "network":        return "We couldn't reach the server. Check your connection and try again.";
    case "timeout":        return "This is taking longer than usual. Try again in a moment.";
    case "auth":           return "Your session has expired. Sign in again to continue.";
    case "forbidden":      return "You don't have access to this view.";
    case "not_found":      return "We couldn't find that. It may have been moved or removed.";
    case "rate_limit":     return "Too many requests right now. Wait a few seconds and try again.";
    case "server":         return "Something went wrong on our side. Try again in a moment.";
    case "contract_drift": return "We received data in a shape we didn't expect. Try again; if it keeps happening, share the reference below.";
    default:               return "Please try again.";
  }
}

export function ErrorState({
  title = "Something went wrong",
  description,
  error,
  onRetry,
  className,
}: ErrorStateProps) {
  const msg = description ?? friendlyMessage(error);
  const api = error instanceof ApiError ? error : undefined;
  const raw = error instanceof Error ? error.message : undefined;
  const showRaw = !description && !!raw && raw !== msg;
  return (
    <div className={cn("flex flex-col items-center text-center py-16 px-6", className)} role="alert">
      <div className="grid place-items-center h-14 w-14 rounded-full bg-[rgb(var(--neg)/0.10)] text-neg mb-4">
        <AlertTriangle className="h-6 w-6" aria-hidden />
      </div>
      <h3 className="font-display text-2xl tracking-tightish">{title}</h3>
      <p className="text-ink-2 mt-2 max-w-md leading-relaxed">{msg}</p>
      {api?.correlationId && (
        <p className="font-mono text-[11px] text-ink-3 mt-3 select-all" data-testid="error-ref">
          Reference {api.correlationId}
        </p>
      )}
      {onRetry && (
        <Button variant="outline" onClick={onRetry} className="mt-5">
          Try again
        </Button>
      )}
      {showRaw && (
        <details className="mt-5 w-full max-w-md text-left" data-testid="error-details">
          <summary className="cursor-pointer select-none text-center text-[12px] text-ink-3 hover:text-ink-2">
            Details
          </summary>
          <pre className="mt-2 whitespace-pre-wrap break-words rounded-md border border-hairline bg-surface-2 p-3 font-mono text-[11px] leading-relaxed text-ink-3">
            {raw}
          </pre>
        </details>
      )}
    </div>
  );
}
