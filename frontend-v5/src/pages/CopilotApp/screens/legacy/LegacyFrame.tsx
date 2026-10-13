import type { ReactNode } from "react";

/**
 * Mounts a screen of the original v5 app inside the Copilot shell, unchanged:
 * same component, same hooks, same data. The original pages bring their own
 * page padding and max width, so the frame only cancels the shell's side
 * padding and marks the screen for tests.
 */
export function LegacyFrame({ testId, children }: { testId: string; children: ReactNode }) {
  return (
    <div data-testid={testId} className="cp-legacy" style={{ margin: "0 -12px", paddingBottom: 24 }}>
      {children}
    </div>
  );
}
