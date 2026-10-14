/**
 * Shell context — what every screen inside the Copilot app can rely on.
 *
 *   const { ask, go, mobile, mode } = useCopilotShell();
 *   ask("Which funds overlap most?");   // opens a thread and streams the answer
 *   ask(question, { position });        // the same, about one futures / options position
 *   go("tool/screener");                // moves to another screen in the shell
 */
import { createContext, useContext } from "react";
import type { PositionRef } from "@/services/adapters/chat.adapter";
import type { Mode } from "./views";

/** What may go with a question besides its text. */
export interface AskOptions {
  /** The futures or options position the question is asked from. The answer
   *  then carries a chart of that contract itself. Leave it out for anything else. */
  position?: PositionRef;
}

export interface CopilotShell {
  mode: Mode;
  /** Viewport under 700px — phone layout. */
  mobile: boolean;
  /** Viewport under 980px — the rail is a drawer. */
  compact: boolean;
  /** Ask the Copilot. Starts a new thread, or continues the open one. */
  ask: (question: string, opts?: AskOptions) => void;
  /** Go to a view below the app base ("" = home). See lib/views.ts. */
  go: (view: string) => void;
  isAdmin: boolean;
  /** The signed-in account is an advisor workspace (and not viewing a client). */
  isAdvisorWorkspace: boolean;
  /** First name for greetings; empty when the profile has no name. */
  firstName: string;
}

const Ctx = createContext<CopilotShell | null>(null);

export const CopilotShellProvider = Ctx.Provider;

export function useCopilotShell(): CopilotShell {
  const v = useContext(Ctx);
  if (!v) throw new Error("useCopilotShell must be used inside the Copilot app shell");
  return v;
}
