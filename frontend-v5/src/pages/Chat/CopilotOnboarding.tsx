/**
 * CopilotOnboarding — an in-chat guided tour.
 *
 * Instead of a static tour page, the copilot walks a new user through what it
 * can do, conversationally, right in the chat landing: a welcome, a plain-English
 * "how I think", then the catalog of jobs. Picking a job hands off to the REAL
 * copilot (onLaunch → submitMessage), so the guided steps are canned product
 * copy but the answer is live. Mirrors the /copilot tour's content.
 */
import { useState } from "react";
import { cn } from "@/lib/utils";

type Workflow = { title: string; prompt: string };

const WORKFLOWS: Workflow[] = [
  { title: "Portfolio health review", prompt: "What's the one thing I should fix first?" },
  { title: "Fund deep-dive", prompt: "Is HDFC Flexi Cap still worth holding?" },
  { title: "Where to invest new money", prompt: "Where should I put ₹2L this month?" },
  { title: "Should I sell?", prompt: "Should I exit my IT sector fund?" },
  { title: "Tax-loss harvesting", prompt: "Cut my tax before March 31." },
  { title: "Goal on track?", prompt: "Am I on track to retire at 55 with ₹5Cr?" },
  { title: "Rebalance my mix", prompt: "Bring me back to a moderate allocation." },
  { title: "Too many funds?", prompt: "I hold 14 funds — is that too many?" },
  { title: "Optimize my SIPs", prompt: "Are my monthly SIPs set up right?" },
  { title: "What moved today", prompt: "What happened to my portfolio today?" },
];

const INTENTS: Workflow[] = [
  { title: "Grow wealth", prompt: "How can I grow my wealth faster?" },
  { title: "Reduce risk", prompt: "How can I reduce the risk in my portfolio?" },
  { title: "Save tax", prompt: "How can I save tax on my investments?" },
  { title: "Retire early", prompt: "Am I on track to retire early?" },
];

const Mark = () => (
  <span className="grid place-items-center h-9 w-9 rounded-md bg-ink text-on-accent font-display text-base leading-none shrink-0">
    न
  </span>
);

function Bubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3.5">
      <Mark />
      <div className="min-w-0 pt-1 text-[15px] leading-relaxed text-ink">{children}</div>
    </div>
  );
}

const chipCls =
  "px-3.5 py-2 rounded-full bg-surface-2 border border-hairline text-[12.5px] text-ink-2 hover:bg-surface-3 hover:text-ink transition-colors";
const primaryChipCls =
  "inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full border border-accent bg-[rgb(var(--accent)/0.10)] text-[12.5px] text-accent hover:bg-[rgb(var(--accent)/0.16)] transition-colors";

export default function CopilotOnboarding({
  onLaunch,
  onDismiss,
}: {
  onLaunch: (prompt: string) => void;
  onDismiss: () => void;
}) {
  // 0 = welcome, 1 = how I think, 2 = pick a job
  const [step, setStep] = useState(0);

  return (
    <div
      data-testid="copilot-onboarding"
      className="mt-6 rounded-2xl border border-hairline bg-surface-1 p-5 sm:p-6 flex flex-col gap-5"
    >
      <div className="flex items-center justify-between">
        <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Guided tour</div>
        <button
          data-testid="onb-dismiss"
          onClick={onDismiss}
          className="text-[12px] text-ink-3 hover:text-ink transition-colors"
        >
          Skip
        </button>
      </div>

      {/* Step 0 — welcome */}
      <Bubble>
        I read your entire portfolio and tell you the <span className="text-accent">one thing to fix first</span>.
        Want a quick tour of what I can do?
      </Bubble>
      {step === 0 && (
        <div className="flex flex-wrap gap-2 pl-[50px]">
          <button data-testid="onb-start" onClick={() => setStep(1)} className={primaryChipCls}>
            Show me what you can do
          </button>
          <button data-testid="onb-maybe-later" onClick={onDismiss} className={chipCls}>
            Maybe later
          </button>
        </div>
      )}

      {/* Step 1 — how I think */}
      {step >= 1 && (
        <Bubble>
          Here's how I work: I <span className="text-accent">ground every answer</span> in your live NIDP data, let
          specialist agents reason over it (health, quality, tax, risk…), boil it down to one plain-language verdict,
          rank the fixes by ₹ impact, and never act without your approval.
        </Bubble>
      )}
      {step === 1 && (
        <div className="flex flex-wrap gap-2 pl-[50px]">
          <button data-testid="onb-next" onClick={() => setStep(2)} className={primaryChipCls}>
            Show me the jobs you can do →
          </button>
        </div>
      )}

      {/* Step 2 — pick a job → hand off to the real copilot */}
      {step >= 2 && (
        <>
          <Bubble>Pick any job and I'll run it on your real portfolio right now:</Bubble>
          <div className="pl-[50px] flex flex-col gap-3">
            <div className="flex flex-wrap gap-2">
              {WORKFLOWS.map((w) => (
                <button key={w.title} onClick={() => onLaunch(w.prompt)} title={w.prompt} className={chipCls}>
                  {w.title}
                </button>
              ))}
            </div>
            <div className="font-mono text-[10.5px] uppercase tracking-[.18em] text-ink-3 mt-1">Or start from a goal</div>
            <div className="flex flex-wrap gap-2">
              {INTENTS.map((it) => (
                <button
                  key={it.title}
                  onClick={() => onLaunch(it.prompt)}
                  title={it.prompt}
                  className={cn(chipCls, "border-dashed")}
                >
                  {it.title}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
