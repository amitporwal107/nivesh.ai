import React from "react";
import { SafeModeApp } from "./SafeModeApp";
import { recordCrash } from "@/lib/crash-fingerprint";
import { reportComponentCrash } from "@/lib/observability";
import { updateComponentHealth } from "@/lib/health-registry";

const BUILD_VERSION =
  (import.meta as unknown as { env: Record<string, string> }).env?.VITE_APP_VERSION ?? "unknown";
const GIT_SHA =
  (import.meta as unknown as { env: Record<string, string> }).env?.VITE_GIT_SHA ?? "local-dev";

interface State {
  hasError: boolean;
  error?: Error;
  fingerprintId?: string;
}

export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    const fp = recordCrash(error, "root", BUILD_VERSION);
    reportComponentCrash({
      component: "root",
      error,
      errorInfo: info,
      buildId: BUILD_VERSION,
      gitSha: GIT_SHA,
      timestamp: Date.now(),
    });
    updateComponentHealth("root", "dead", fp.id);
    this.setState({ fingerprintId: fp.id });
  }

  render() {
    if (this.state.hasError) {
      return (
        <SafeModeApp
          error={this.state.error}
          onReset={() => this.setState({ hasError: false, error: undefined, fingerprintId: undefined })}
        />
      );
    }
    return this.props.children;
  }
}
