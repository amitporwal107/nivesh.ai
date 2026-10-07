/**
 * Unit tests for the W1a workspace pure-logic modules (docs/charting.md §38, task item 8):
 * drawingHistory.ts, magnet.ts, ranges.ts, keyboard.ts (matchShortcut/isTypingTarget — the pure half of
 * useChartShortcuts; the hook itself needs a live DOM/React render and is exercised by the components that use it,
 * not here).
 *
 * frontend-v5 has no vitest/jest — package.json's only test runner is @playwright/test (see package.json
 * devDependencies) — so per the task instructions these run as plain Node-context Playwright tests: no `page`
 * fixture is used anywhere below, so no browser is launched for this file, and it imports nothing from the app
 * build (only the four source modules under test, by relative path — `magnet.ts`/`ranges.ts` only take a
 * type-only `import type { Bar }` from contract.ts, which is erased at compile time, so contract.ts's runtime code
 * — and the fetch/store machinery it pulls in — is never evaluated here).
 */
import { test, expect } from "@playwright/test";
import { nearestBar, magnetSnapToBar, magnetSnap, type OhlcField } from "../../src/pages/Research/charts/workspace/magnet";
import { resolveRange, RANGE_PRESETS, type RangePreset } from "../../src/pages/Research/charts/workspace/ranges";
import { DrawingHistory, type DrawingCommand } from "../../src/pages/Research/charts/workspace/drawingHistory";
import { matchShortcut, isTypingTarget } from "../../src/pages/Research/charts/workspace/keyboard";
import type { Bar } from "../../src/pages/Research/charts/contract";

/* ══════════════════════════════════════════════════════════════════════════
   magnet.ts — TC-80..TC-84
   ══════════════════════════════════════════════════════════════════════════ */
const BARS: Bar[] = [
  ["2026-01-05", 100, 110, 95, 105, 1000],
  ["2026-01-06", 105, 108, 100, 102, 1100],
  ["2026-01-07", 102, 120, 101, 118, 1200],
];

test.describe("magnet.ts", () => {
  test("TC-80 nearestBar: exact match returns that bar", () => {
    expect(nearestBar(BARS, "2026-01-06")?.[0]).toBe("2026-01-06");
  });

  test("TC-81 nearestBar: before the series clamps to the first bar; after clamps to the last", () => {
    expect(nearestBar(BARS, "2025-01-01")?.[0]).toBe("2026-01-05");
    expect(nearestBar(BARS, "2027-01-01")?.[0]).toBe("2026-01-07");
    expect(nearestBar([], "2026-01-06")).toBeNull();
  });

  test("TC-82 nearestBar: a gap date resolves to the nearer neighbour", () => {
    // 01-06 04:00 UTC is 4h after 01-06's midnight and 20h before 01-07's — nearer to 01-06.
    expect(nearestBar(BARS, "2026-01-06T04:00:00Z")?.[0]).toBe("2026-01-06");
    // 01-06 18:00 UTC is 6h before 01-07's midnight and 18h after 01-06's — nearer to 01-07.
    expect(nearestBar(BARS, "2026-01-06T18:00:00Z")?.[0]).toBe("2026-01-07");
  });

  test("TC-83 magnetSnapToBar: snaps to whichever of O/H/L/C is closest", () => {
    const bar = BARS[0]; // O 100, H 110, L 95, C 105
    expect(magnetSnapToBar(bar, 109)).toMatchObject({ field: "high" satisfies OhlcField, price: 110 });
    expect(magnetSnapToBar(bar, 96)).toMatchObject({ field: "low", price: 95 });
    expect(magnetSnapToBar(bar, 106)).toMatchObject({ field: "close", price: 105 });
    expect(magnetSnapToBar(bar, 101)).toMatchObject({ field: "open", price: 100 });
  });

  test("TC-84 magnetSnap: resolves the bar by date first, then snaps; empty series is a no-op", () => {
    const r = magnetSnap(BARS, "2026-01-07", 119); // bar 3: O102 H120 L101 C118
    expect(r).toMatchObject({ field: "high", price: 120 });
    expect(magnetSnap([], "2026-01-07", 100)).toBeNull();
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   ranges.ts — TC-85..TC-90
   ══════════════════════════════════════════════════════════════════════════ */
function dailyBars(fromISO: string, toISO: string): Bar[] {
  const out: Bar[] = [];
  const d = new Date(`${fromISO}T00:00:00Z`);
  const end = new Date(`${toISO}T00:00:00Z`);
  while (d.getTime() <= end.getTime()) {
    out.push([d.toISOString().slice(0, 10), 100, 101, 99, 100, 1000]);
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return out;
}

test.describe("ranges.ts", () => {
  test("TC-85 1D and 5D are disabled with the intraday reason; 1M..All are enabled", () => {
    const byId = Object.fromEntries(RANGE_PRESETS.map((r) => [r.id, r]));
    expect(byId["1D"].enabled).toBe(false);
    expect(byId["1D"].disabledReason).toBe("needs intraday data");
    expect(byId["5D"].enabled).toBe(false);
    for (const id of ["1M", "3M", "6M", "YTD", "1Y", "5Y", "ALL"] as RangePreset[]) {
      expect(byId[id].enabled).toBe(true);
      expect(byId[id].disabledReason).toBeUndefined();
    }
  });

  test("TC-86 resolveRange: a disabled preset or an empty series returns null", () => {
    const bars = dailyBars("2025-01-01", "2026-01-01");
    expect(resolveRange("1D", bars)).toBeNull();
    expect(resolveRange("5D", bars)).toBeNull();
    expect(resolveRange("1M", [])).toBeNull();
  });

  test("TC-87 resolveRange ALL: the full series span", () => {
    const bars = dailyBars("2024-03-01", "2026-01-01");
    expect(resolveRange("ALL", bars)).toEqual({ from: "2024-03-01", to: "2026-01-01" });
  });

  test("TC-88 resolveRange 1M/3M/1Y: N months back from the last bar, on a real bar date", () => {
    const bars = dailyBars("2020-01-01", "2026-01-15");
    const oneMonth = resolveRange("1M", bars)!;
    expect(oneMonth.to).toBe("2026-01-15");
    expect(oneMonth.from).toBe("2025-12-15");

    const threeMonth = resolveRange("3M", bars)!;
    expect(threeMonth.from).toBe("2025-10-15");

    const oneYear = resolveRange("1Y", bars)!;
    expect(oneYear.from).toBe("2025-01-15");
  });

  test("TC-89 resolveRange YTD: 1 January of the last bar's year, across a year boundary", () => {
    const bars = dailyBars("2024-01-01", "2026-01-10");
    expect(resolveRange("YTD", bars)).toEqual({ from: "2026-01-01", to: "2026-01-10" });
  });

  test("TC-90 resolveRange clamps `from` to the first bar when the preset is wider than the history", () => {
    const bars = dailyBars("2025-11-01", "2025-11-10"); // 10 days of data only
    const oneYear = resolveRange("1Y", bars)!;
    expect(oneYear.from).toBe("2025-11-01"); // clamped, not a date before the series
    expect(oneYear.to).toBe("2025-11-10");
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   drawingHistory.ts — TC-91..TC-98
   ══════════════════════════════════════════════════════════════════════════ */
function cmd<T>(doFn: () => Promise<T>, undoFn: () => Promise<T>): DrawingCommand<T> {
  return { label: "test-command", do: doFn, undo: undoFn };
}

test.describe("drawingHistory.ts", () => {
  test("TC-91 run(): a successful do() is pushed onto undo and clears redo", async () => {
    const h = new DrawingHistory();
    const errors: string[] = [];
    const result = await h.run(cmd(async () => "created", async () => "deleted"), (msg) => errors.push(msg));
    expect(result).toBe("created");
    expect(h.canUndo).toBe(true);
    expect(h.canRedo).toBe(false);
    expect(errors).toEqual([]);
  });

  test("TC-92 run(): a failing do() reports the error and leaves the stack untouched", async () => {
    const h = new DrawingHistory();
    const errors: Array<{ msg: string; label: string }> = [];
    const result = await h.run(
      cmd(async () => { throw new Error("422 anchor points"); }, async () => "undone"),
      (msg, c) => errors.push({ msg, label: c.label }),
    );
    expect(result).toBeNull();
    expect(h.canUndo).toBe(false);
    expect(errors).toEqual([{ msg: "422 anchor points", label: "test-command" }]);
  });

  test("TC-93 undo(): pops the undo stack onto redo, and calls command.undo()", async () => {
    const h = new DrawingHistory();
    let undone = false;
    await h.run(cmd(async () => "created", async () => { undone = true; return "reverted"; }), () => {});
    const result = await h.undo(() => {});
    expect(result).toBe("reverted");
    expect(undone).toBe(true);
    expect(h.canUndo).toBe(false);
    expect(h.canRedo).toBe(true);
  });

  test("TC-94 undo(): a failing undo() reports the error and leaves the command on the undo stack", async () => {
    const h = new DrawingHistory();
    await h.run(cmd(async () => "created", async () => { throw new Error("network error"); }), () => {});
    const errors: string[] = [];
    const result = await h.undo((msg) => errors.push(msg));
    expect(result).toBeNull();
    expect(errors).toEqual(["network error"]);
    expect(h.canUndo).toBe(true); // still there — a failed rollback must not silently drop history
    expect(h.canRedo).toBe(false);
  });

  test("TC-95 redo(): replays do() and moves the command back to the undo stack", async () => {
    const h = new DrawingHistory();
    let doCalls = 0;
    await h.run(cmd(async () => { doCalls++; return "created"; }, async () => "reverted"), () => {});
    await h.undo(() => {});
    const result = await h.redo(() => {});
    expect(result).toBe("created");
    expect(doCalls).toBe(2);
    expect(h.canUndo).toBe(true);
    expect(h.canRedo).toBe(false);
  });

  test("TC-96 redo(): a failing do() reports the error and leaves the command on the redo stack", async () => {
    const h = new DrawingHistory();
    let attempt = 0;
    await h.run(cmd(async () => { attempt++; if (attempt === 2) throw new Error("save failed"); return "created"; }, async () => "reverted"), () => {});
    await h.undo(() => {});
    const errors: string[] = [];
    const result = await h.redo((msg) => errors.push(msg));
    expect(result).toBeNull();
    expect(errors).toEqual(["save failed"]);
    expect(h.canRedo).toBe(true);
    expect(h.canUndo).toBe(false);
  });

  test("TC-97 a new run() after an undo() clears the stale redo branch", async () => {
    const h = new DrawingHistory();
    await h.run(cmd(async () => "a", async () => "undo-a"), () => {});
    await h.undo(() => {});
    expect(h.canRedo).toBe(true);
    await h.run(cmd(async () => "b", async () => "undo-b"), () => {});
    expect(h.canRedo).toBe(false); // "a" is no longer reachable via redo
    expect(h.canUndo).toBe(true);
  });

  test("TC-98 undo()/redo() on an empty stack no-op without calling onError; clear() empties both stacks", async () => {
    const h = new DrawingHistory();
    const errors: string[] = [];
    expect(await h.undo((msg) => errors.push(msg))).toBeNull();
    expect(await h.redo((msg) => errors.push(msg))).toBeNull();
    expect(errors).toEqual([]);

    await h.run(cmd(async () => "a", async () => "undo-a"), () => {});
    h.clear();
    expect(h.canUndo).toBe(false);
    expect(h.canRedo).toBe(false);
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   keyboard.ts (pure half) — TC-99..TC-103
   ══════════════════════════════════════════════════════════════════════════ */
test.describe("keyboard.ts", () => {
  test("TC-99 isTypingTarget: form controls and contentEditable are typing targets", () => {
    expect(isTypingTarget(null)).toBe(false);
    expect(isTypingTarget({ tagName: "INPUT" } as unknown as EventTarget)).toBe(true);
    expect(isTypingTarget({ tagName: "TEXTAREA" } as unknown as EventTarget)).toBe(true);
    expect(isTypingTarget({ tagName: "SELECT" } as unknown as EventTarget)).toBe(true);
    expect(isTypingTarget({ tagName: "DIV", isContentEditable: true } as unknown as EventTarget)).toBe(true);
    expect(isTypingTarget({ tagName: "DIV", isContentEditable: false } as unknown as EventTarget)).toBe(false);
    expect(isTypingTarget({ tagName: "BUTTON" } as unknown as EventTarget)).toBe(false);
  });

  test("TC-100 matchShortcut: Ctrl+Z / Ctrl+Shift+Z / Cmd+Z resolve to undo/redo", () => {
    expect(matchShortcut({ key: "z", ctrlKey: true })).toBe("undo");
    expect(matchShortcut({ key: "Z", ctrlKey: true, shiftKey: true })).toBe("redo");
    expect(matchShortcut({ key: "z", metaKey: true })).toBe("undo"); // Cmd treated the same as Ctrl
  });

  test("TC-101 matchShortcut: Alt+T/H/F resolve to the three reserved drawing tools", () => {
    expect(matchShortcut({ key: "t", altKey: true })).toBe("trendline");
    expect(matchShortcut({ key: "h", altKey: true })).toBe("horizontal_line");
    expect(matchShortcut({ key: "f", altKey: true })).toBe("fibonacci");
  });

  test("TC-102 matchShortcut: Escape, Delete/Backspace, and the four arrow keys", () => {
    expect(matchShortcut({ key: "Escape" })).toBe("cancel");
    expect(matchShortcut({ key: "Delete" })).toBe("delete");
    expect(matchShortcut({ key: "Backspace" })).toBe("delete");
    expect(matchShortcut({ key: "ArrowLeft" })).toBe("pan_left");
    expect(matchShortcut({ key: "ArrowRight" })).toBe("pan_right");
    expect(matchShortcut({ key: "ArrowUp" })).toBe("pan_up");
    expect(matchShortcut({ key: "ArrowDown" })).toBe("pan_down");
  });

  test("TC-103 matchShortcut: an unrelated key, or a Ctrl+Alt combination, matches nothing", () => {
    expect(matchShortcut({ key: "a" })).toBeNull();
    expect(matchShortcut({ key: "z", ctrlKey: true, altKey: true })).toBeNull();
    expect(matchShortcut({ key: "ArrowLeft", ctrlKey: true })).toBeNull();
  });
});
