# Functionality Verification Report — Trading desk Copilot: a floating, resizable window that can be locked

- **Branch:** feat/copilot-floating-window (stacked on feat/copilot-stock-autocomplete, PR #404, which also edits
  CopilotDock.tsx), worktree /home/deploy/nivesh-strategy-copilot
- **Date:** 2026-10-29
- **Author:** Claude (DESIGN_ENGINEER + FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** mocked Playwright on a production build; staging after merge
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
Owner, 29 Oct: "The copilot window is a free floating and you can resize it window or you can lock it".

Read as two states of the trading desk's Copilot, where it docks today (from 1400 px wide). No design exists for this;
the desk design only has the "Copilot docked right" chip.
- **Locked (default).** Exactly as today: the right column, 384 px wide.
- **Floating.** The desk content takes the full width. The Copilot is a window over it: drag it by its header, resize it
  from its corner handle (min 340×420, max 90% of the screen), kept inside the screen.
- **Switching.** A Float / Lock button in the Copilot's header. The topbar chip reads "Copilot docked right" or
  "Copilot floating".
- **Memory.** The choice, position and size are remembered per browser (localStorage, guarded). A browser that blocks
  storage just starts locked.
- **Narrower screens.** Below 1400 px nothing changes (the Copilot button opens it full height).

## Test Cases
> Authored UP FRONT (before implementation). Spec: `frontend-v5/e2e/tests/copilot-app-desk-copilot-window.spec.ts`.

| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| FW-1 | Desk at 1440 px, first visit | Locked: the Copilot in the right column (`data-window="locked"`), the button reads "Float", the chip reads "Copilot docked right" || PASS |
| FW-2 | Click Float | The Copilot is a fixed window (`data-window="floating"`) over the desk, which now has the full width (the content column is wider). The chip reads "Copilot floating", the button "Lock" || PASS |
| FW-3 | Drag the header | The window moves by the drag. Dragged far off the screen, it stays reachable (its header stays on screen). Buttons in the header are not drag handles || PASS |
| FW-4 | Drag the corner handle | The window grows and shrinks; it is clamped to its minimum size || PASS |
| FW-5 | Reload while floating | Floating again, at the same position and size || PASS |
| FW-6 | Lock, then reload | Back in the right column, and it stays locked after a reload || PASS |
| FW-7 | Ask from the floating window | The question streams, with `surface: trading_desk`; the answer shows in the window || PASS |
| FW-8 | 1280 px | Unchanged: the Copilot button, no Float button, no floating window || PASS |
| FW-9 | Regression: desk + Copilot specs (copilot-app-desk, desk-shell, trade-idea, stock-complete, desk-market-overview) | No new failure || PASS |
| FW-10 | Staging after merge | The served bundle has the window; a manual Float / drag / resize / Lock pass with a session || PENDING (after merge) |

## Tests run (real output, 2026-10-29)
- `tsc --noEmit` → exit 0.
- `playwright test copilot-app-desk-copilot-window.spec.ts copilot-app-desk.spec.ts copilot-app-desk-shell.spec.ts
  copilot-app-trade-idea.spec.ts copilot-app-stock-complete.spec.ts copilot-app-desk-market-overview.spec.ts` →
  `93 passed (1.3m)`, 0 failed. That is FW-1 … FW-8, and FW-9 (the desk, Copilot and market-overview specs).
- The first run failed FW-7 only, because of a fault in the mock, not the product. The thread is re-read after an answer
  is saved, and the mock answered an empty thread; it now keeps what was asked and answered, as copilot-app-desk.spec.ts
  does.

## Inputs required from user
- Merge #404 first (this branch carries its commit), then this PR.

## Verdict: BLOCKED
