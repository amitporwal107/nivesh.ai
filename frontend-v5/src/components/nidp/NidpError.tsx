import { ApiError } from "@/services/api/errors";

export function nidpErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail ?? err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

export function NidpError({ err }: { err: unknown }) {
  const msg = nidpErrorMessage(err);
  const needsConfig = msg.includes("NIDP_QUERY_API") || msg.includes("not configured");
  return (
    <div className="rounded-lg border border-[rgb(var(--neg)/0.25)] bg-[rgb(var(--neg)/0.06)] p-4 space-y-1">
      <div className="text-sm font-medium text-neg">Request failed</div>
      <div className="text-xs text-ink-2">{msg}</div>
      {needsConfig && (
        <div className="text-xs text-ink-3 pt-1">
          Add the missing secrets in <strong>Admin → Secrets</strong>, then check env state in the{" "}
          <strong>Diagnostics</strong> tab.
        </div>
      )}
    </div>
  );
}
