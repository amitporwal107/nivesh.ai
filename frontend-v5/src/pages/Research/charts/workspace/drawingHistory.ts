/**
 * Undo/redo stack over async drawing operations (§38.6): "Undo/redo (Ctrl+Z / Ctrl+Shift+Z) covers create, move,
 * restyle and delete within the session. Each step is an API call. If a call fails, the change is rolled back and
 * an error is shown. The server copy stays the source of truth."
 *
 * This module is deliberately decoupled from `drawingsApi` (contract.ts) and from React: it only sequences a pair
 * of async functions per step (do/undo) and reports success/failure, so it has no fetch/DOM/store dependency and
 * can be unit-tested directly. Building the four `DrawingCommand`s (create/move/restyle/delete) from
 * `drawingsApi.create/update/remove` and applying their resolved server records to on-screen state is the caller's
 * job (W1b, in ChartsScreen.tsx) — see the class doc below for the exact contract.
 */

export interface DrawingCommand<T = unknown> {
  /** Not shown to the user — for logging/debugging only. */
  label: string;
  /** Performs the action against the server (e.g. POST a new drawing, PATCH a moved/restyled one, DELETE one).
   *  Resolves with whatever the caller considers "the resulting server record" for that step (a created/updated
   *  Drawing, or a sentinel for a delete) — that value is what redo() replays and what a caller applies as the
   *  new source of truth on success. */
  do: () => Promise<T>;
  /** Reverses `do()` against the server (delete what was created, PATCH back the prior anchors/style, or
   *  re-create a deleted drawing). Resolves the same way as `do`. */
  undo: () => Promise<T>;
}

export type HistoryErrorHandler = (message: string, command: DrawingCommand) => void;

/**
 * A step's `do()`/`undo()` is only ever pushed onto a stack (and only ever reported as applied) once it resolves.
 * On rejection the stack is left exactly as it was before the attempt — nothing is popped, nothing is pushed —
 * and `onError` is called so the caller can surface the message and, if it applied an optimistic local update
 * before calling in, revert that update itself. The server copy is the only source of truth this class knows
 * about: it never guesses what a failed call changed, and a caller must not update local drawing state from
 * anything other than a resolved `do()`/`undo()`/`redo()` return value.
 */
export class DrawingHistory {
  private undoStack: DrawingCommand[] = [];
  private redoStack: DrawingCommand[] = [];

  get canUndo(): boolean { return this.undoStack.length > 0; }
  get canRedo(): boolean { return this.redoStack.length > 0; }
  /** For tests/inspection only — not part of the operational contract. */
  get sizes(): { undo: number; redo: number } { return { undo: this.undoStack.length, redo: this.redoStack.length }; }

  /**
   * Runs a new command's `do()`. On success, pushes it onto the undo stack and clears the redo stack (a fresh
   * action invalidates whatever branch redo was pointing at — standard undo/redo semantics) and returns the
   * resolved value. On failure, the stack is untouched, `onError` is called, and this resolves to null.
   */
  async run<T>(command: DrawingCommand<T>, onError: HistoryErrorHandler): Promise<T | null> {
    try {
      const result = await command.do();
      this.undoStack.push(command as DrawingCommand);
      this.redoStack = [];
      return result;
    } catch (e) {
      onError(errorMessage(e), command);
      return null;
    }
  }

  /** Runs the top undo-stack command's `undo()`. No-ops (returns null, no `onError` call) when nothing is undoable. */
  async undo(onError: HistoryErrorHandler): Promise<unknown | null> {
    const command = this.undoStack[this.undoStack.length - 1];
    if (!command) return null;
    try {
      const result = await command.undo();
      this.undoStack.pop();
      this.redoStack.push(command);
      return result;
    } catch (e) {
      onError(errorMessage(e), command);
      return null;
    }
  }

  /** Runs the top redo-stack command's `do()` again. No-ops when nothing is redoable. */
  async redo(onError: HistoryErrorHandler): Promise<unknown | null> {
    const command = this.redoStack[this.redoStack.length - 1];
    if (!command) return null;
    try {
      const result = await command.do();
      this.redoStack.pop();
      this.undoStack.push(command);
      return result;
    } catch (e) {
      onError(errorMessage(e), command);
      return null;
    }
  }

  /** Drops all history — e.g. on a symbol/timeframe change, since drawings are saved per symbol+timeframe (§38.6)
   *  and an undo step for one chart should never replay against another. */
  clear(): void { this.undoStack = []; this.redoStack = []; }
}

function errorMessage(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "The change could not be saved.";
}
