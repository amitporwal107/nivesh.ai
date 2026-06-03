import React from "react";
import { RefreshCw } from "lucide-react";
import { recordCrash } from "@/lib/crash-fingerprint";
import { reportComponentCrash, reportComponentRecover } from "@/lib/observability";
import { registerComponent, updateComponentHealth } from "@/lib/health-registry";
import { isEnabled, autoDisableIfThresholdExceeded, type WidgetFlagKey } from "@/lib/feature-flags";

const BUILD_VERSION =
  (import.meta as unknown as { env: Record<string, string> }).env?.VITE_APP_VERSION ?? "unknown";
const GIT_SHA =
  (import.meta as unknown as { env: Record<string, string> }).env?.VITE_GIT_SHA ?? "local-dev";

// ── Fallback UI ───────────────────────────────────────────────────────────────

function WidgetFallback({
  name,
  errorMessage,
  fingerprintId,
  countdown,
  onRetry,
}: {
  name: string;
  errorMessage: string;
  fingerprintId: string;
  countdown: number;
  onRetry: () => void;
}) {
  return (
    <div className="rounded-lg bg-surface-1 border border-hairline p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <span className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3">{name}</span>
          <p className="text-[13px] text-neg mt-1 line-clamp-2">{errorMessage}</p>
        </div>
        <span className="font-mono text-[10px] text-ink-4 bg-surface-2 border border-hairline rounded px-1.5 py-0.5 shrink-0">
          {fingerprintId}
        </span>
      </div>
      <div className="flex items-center gap-3 mt-1">
        {countdown > 0 ? (
          <span className="flex items-center gap-1.5 text-[12px] text-ink-3">
            <RefreshCw className="h-3 w-3 animate-spin" />
            Retrying in {countdown}s…
          </span>
        ) : null}
        <button
          onClick={onRetry}
          className="text-[12px] text-accent font-medium hover:underline"
        >
          Retry now
        </button>
      </div>
    </div>
  );
}

// ── SafeWidget ────────────────────────────────────────────────────────────────

interface SafeWidgetProps {
  name: string;
  flagKey?: WidgetFlagKey;
  retryDelayMs?: number;
  version?: string;
  children: React.ReactNode;
}

interface SafeWidgetState {
  hasError: boolean;
  error: Error | null;
  fingerprintId: string;
  countdown: number;
  attempt: number;
}

export class SafeWidget extends React.Component<SafeWidgetProps, SafeWidgetState> {
  private retryTimer: ReturnType<typeof setInterval> | null = null;

  constructor(props: SafeWidgetProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      fingerprintId: "",
      countdown: Math.round((props.retryDelayMs ?? 5000) / 1000),
      attempt: 0,
    };
  }

  componentDidMount() {
    registerComponent(this.props.name, this.props.version ?? "unknown");
    updateComponentHealth(this.props.name, "healthy");
  }

  static getDerivedStateFromError(error: Error): Partial<SafeWidgetState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    const { name, flagKey, retryDelayMs = 5000 } = this.props;
    const fp = recordCrash(error, name, BUILD_VERSION);

    reportComponentCrash({ component: name, error, errorInfo, buildId: BUILD_VERSION, gitSha: GIT_SHA, timestamp: Date.now() });
    updateComponentHealth(name, "dead", fp.id);
    autoDisableIfThresholdExceeded(flagKey, fp.id);

    const totalSeconds = Math.round(retryDelayMs / 1000);
    this.setState({ fingerprintId: fp.id, countdown: totalSeconds });

    this.retryTimer = setInterval(() => {
      this.setState((prev) => {
        if (prev.countdown <= 1) {
          clearInterval(this.retryTimer!);
          this.retryTimer = null;
          return { hasError: false, error: null, fingerprintId: prev.fingerprintId, countdown: totalSeconds, attempt: prev.attempt + 1 };
        }
        return { ...prev, countdown: prev.countdown - 1 };
      });
    }, 1000);
  }

  componentWillUnmount() {
    if (this.retryTimer) {
      clearInterval(this.retryTimer);
      this.retryTimer = null;
    }
  }

  private handleManualRetry = () => {
    if (this.retryTimer) {
      clearInterval(this.retryTimer);
      this.retryTimer = null;
    }
    const { name } = this.props;
    const totalSeconds = Math.round((this.props.retryDelayMs ?? 5000) / 1000);
    reportComponentRecover({ component: name, attemptNumber: this.state.attempt + 1, timestamp: Date.now() });
    updateComponentHealth(name, "healthy");
    this.setState((prev) => ({ hasError: false, error: null, countdown: totalSeconds, attempt: prev.attempt + 1 }));
  };

  render() {
    const { name, flagKey, children } = this.props;
    const { hasError, error, fingerprintId, countdown } = this.state;

    if (flagKey && !isEnabled(flagKey)) {
      return null;
    }

    if (hasError && error) {
      return (
        <WidgetFallback
          name={name}
          errorMessage={error.message}
          fingerprintId={fingerprintId}
          countdown={countdown}
          onRetry={this.handleManualRetry}
        />
      );
    }

    return children;
  }
}
