/**
 * AD-P2-118: with paper execution wired, an approved TRADE_PROPOSAL ends with result APPROVED (Phase 1's APPROVED_NO_EXECUTION
 * stays for a process with no gateway). The screens' pure label functions must read both the same way. No browser, no mocks of
 * the API: these are the model functions the screens call.
 */
import { expect, test } from "@playwright/test";
import { flowView } from "../../src/autodesk/screens/agents/model";
import { graphNodes } from "../../src/autodesk/screens/simulator/model";
import { resultWords } from "../../src/autodesk/studio/views/runs/model";
import { defaultWorkflow, outcomeText, resultLabel } from "../../src/autodesk/studio/views/trace/model";

// TEST DATA — not real workflows.
const row = (result: string) => ({ workflow_id: `WF-${result}`, kind: "TRADE_PROPOSAL", state: "COMPLETED", input: {}, created_at: "2026-11-05T03:30:00Z",
  outcome: { result, trade_id: "TRD-1", plan_version: 1, approval_id: "APR-1" } }) as never;

for (const result of ["APPROVED", "APPROVED_NO_EXECUTION"]) {
  test(`AD-P2-118 ${result} reads as approved on every screen`, () => {
    expect(resultWords(result)).toBe("approved it");
    expect(resultLabel(row(result))).toBe("approved");
    expect(outcomeText(row(result)).approvalPath).toBe(true);
    expect(defaultWorkflow([row("NO_TRADE"), row(result)])).toBe(`WF-${result}`);
    expect(flowView(row(result)).color).toBe("var(--mint)");
    const auth = graphNodes({ workflow: row(result), tasks: [], handoffs: [], children: [] } as never).find((n) => n.t === "Authorization");
    expect(auth?.st).toBe("APPROVED");
  });
}
