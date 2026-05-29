import React from "react";
import { AlertTriangle, ArrowLeft, Home } from "lucide-react";
import { recordCrash } from "@/lib/crash-fingerprint";
import { reportComponentCrash } from "@/lib/observability";
import { updateComponentHealth } from "@/lib/health-registry";

const BUILD_VERSION =
  (import.meta as unknown as { env: Record<string, string> }).env?.VITE_APP_VERSION ?? "unknown";
const GIT_SHA =
  (import.meta as unknown as { env: Record<string, string> }).env?.VITE_GIT_SHA ?? "local-dev";

const REDIRECT_DELAY_S = 10;

interface RouteErrorBoundaryProps {
  pageName: string;
  children: React.ReactNode;
}

interface RouteErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  fingerprintId: string;
  countdown: number;
  cancelRedirect: boolean;
}

export class RouteErrorBoundary extends React.Component<
  RouteErrorBoundaryProps,
  RouteErrorBoundaryState
> {
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(props: RouteErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      fingerprintId: "",
      countdown: REDIRECT_DELAY_S,
      cancelRedirect: false,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<RouteErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    const { pageName } = this.props;
    const fp = recordCrash(error, pageName, BUILD_VERSION);

    reportComponentCrash({
      component: pageName,
      error,
      errorInfo,
      buildId: BUILD_VERSION,
      gitSha: GIT_SHA,
      timestamp: Date.now(),
    });
    updateComponentHealth(pageName, "dead", fp.id);

    this.setState({ fingerprintId: fp.id, countdown: REDIRECT_DELAY_S });

    this.timer = setInterval(() => {
      this.setState((prev) => {
        if (prev.cancelRedirect) {
          clearInterval(this.timer!);
          this.timer = null;
          return prev;
        }
        if (prev.countdown <= 1) {
          clearInterval(this.timer!);
          this.timer = null;
          window.location.replace("/dashboard");
          return prev;
        }
        return { ...prev, countdown: prev.countdown - 1 };
      });
    }, 1000);
  }

  componentWillUnmount() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  render() {
    const { hasError, error, fingerprintId, countdown, cancelRedirect } = this.state;
    const { pageName, children } = this.props;

    if (!hasError) return children;

    return (
      <div className="min-h-[60vh] flex flex-col items-center justify-center p-8 text-center">
        <AlertTriangle className="h-10 w-10 text-warm mb-4" />
        <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3 mb-2">
          Page unavailable
        </div>
        <h2 className="font-display text-2xl tracking-tightish mb-2">
          {pageName} is unavailable
        </h2>
        <p className="text-[13px] text-ink-2 max-w-[380px] leading-relaxed mb-1">
          {error?.message ?? "An unexpected error occurred."}
        </p>
        {fingerprintId && (
          <span className="font-mono text-[10px] text-ink-4 bg-surface-2 border border-hairline rounded px-2 py-1 mb-6">
            {fingerprintId}
          </span>
        )}

        <div className="flex gap-3 mt-2">
          <button
            onClick={() => window.location.replace("/dashboard")}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-accent text-on-accent text-[13px] font-medium hover:opacity-90 transition-opacity"
          >
            <Home className="h-3.5 w-3.5" />
            Back to Dashboard
          </button>
          <button
            onClick={() => window.location.replace("/")}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-surface-1 border border-hairline text-[13px] text-ink-2 hover:text-ink transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Home
          </button>
        </div>

        {!cancelRedirect && (
          <div className="mt-5 flex items-center gap-3 text-[12px] text-ink-3">
            <span>Redirecting to Dashboard in {countdown}s…</span>
            <button
              onClick={() => this.setState({ cancelRedirect: true })}
              className="text-ink-2 hover:text-ink underline"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    );
  }
}
