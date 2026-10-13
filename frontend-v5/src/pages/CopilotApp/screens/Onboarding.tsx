/**
 * Get started — onboarding inside the Copilot shell.
 * Design: frontend-v5/design/nivesh-copilot/NVOnboarding.dc.html.
 *
 * Steps: You (mode) → Goals (goals, risk profile) → Portfolio (statement
 * import) → done. The design's "How should answers read?" step is not here:
 * nothing in the backend stores an answer depth.
 *
 * The shell sends every signed-in user who has not finished onboarding to this
 * screen, so "Skip setup" is on every step. Skipping and finishing both record
 * completion (useCompleteOnboarding — the call pages/Onboarding makes) and go
 * home, whether or not the server accepted the write.
 */
import { useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUpgradeToAdvisory } from "@/hooks/use-advisor";
import { useToastStore } from "@/stores/toast.store";
import type { Goal } from "@/types/goal";
import { Btn, EmptyBlock, ErrorBlock, Eyebrow, LoadingBlock, NotConnected, Pill, Screen, Tiles, fmtINR, fmtNum, type TileItem } from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { useCopilotPrefs } from "../lib/store";
import type { Mode } from "../lib/views";
import { BrokerSignInMissing, ChoiceCard, GmailSource, InlineError, LinkButton, StatementUpload, ToggleChip, errorText, goalHorizonYears, riskAssessed, useProfileWizard } from "./account/parts";
import { useCompleteOnboarding, useOnboardingState } from "./account/queries";

type StepKey = "you" | "goals" | "portfolio" | "done";
const FLOW: StepKey[] = ["you", "goals", "portfolio", "done"];
const PROGRESS: Array<{ key: StepKey; label: string }> = [
  { key: "you", label: "You" },
  { key: "goals", label: "Goals" },
  { key: "portfolio", label: "Portfolio" },
];

/** The two ways in that the design offers. Trader mode is chosen from the rail. */
type StartMode = Extract<Mode, "investor" | "advisor">;
const MODES: Array<{ key: StartMode; title: string; body: string }> = [
  { key: "investor", title: "I invest my own money", body: "Holdings, risk, goals, research and a copilot that knows your portfolio." },
  { key: "advisor", title: "I’m an advisor or MFD", body: "Your clients’ portfolios in one place, with a queue of who needs you today." },
];

type Source = "cas" | "gmail" | "broker" | "csv";
const SOURCES: Array<{ key: Source; label: string }> = [
  { key: "cas", label: "NSDL / CDSL CAS" },
  { key: "gmail", label: "CAS from Gmail" },
  { key: "broker", label: "Broker account" },
  { key: "csv", label: "CSV or Excel" },
];

function StepTitle({ children, size }: { children: ReactNode; size?: number }) {
  const { mobile } = useCopilotShell();
  return <h1 className="cp-display m-0" style={{ fontSize: mobile ? 32 : size ?? 40, lineHeight: 1.08 }}>{children}</h1>;
}

// ── step 1: you ──────────────────────────────────────────────────────────

function StepYou({ picked, onPick }: { picked: StartMode | null; onPick: (m: StartMode) => void }) {
  const { isAdvisorWorkspace } = useCopilotShell();
  const savedMode = useCopilotPrefs((s) => s.mode);
  const qc = useQueryClient();
  const upgrade = useUpgradeToAdvisory();
  const current: Mode = picked ?? savedMode;

  return (
    <section data-testid="onboarding-step-you" className="flex flex-col" style={{ gap: 18 }}>
      <StepTitle>How will you use Nivesh?</StepTitle>
      <div role="group" aria-label="How you will use Nivesh" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,260px),1fr))", gap: 12 }}>
        {MODES.map((m) => (
          <ChoiceCard key={m.key} data-testid={`onboarding-mode-${m.key}`} on={current === m.key} title={m.title} body={m.body} onClick={() => onPick(m.key)} />
        ))}
      </div>

      {current === "advisor" && !isAdvisorWorkspace && (
        <div data-testid="onboarding-advisor-note" className="flex flex-col items-start" style={{ gap: 10, padding: "14px 16px", borderRadius: 14, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
          <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 600 }}>
            Advisor mode needs an advisor workspace, and this account is an individual one. Setting one up changes the account everywhere in Nivesh, not only here. Until then Nivesh opens in Investor mode.
          </span>
          {upgrade.isSuccess ? (
            <Pill tone="mint">Advisor workspace set up</Pill>
          ) : (
            <Btn
              data-testid="onboarding-advisor-upgrade"
              disabled={upgrade.isPending}
              onClick={() => upgrade.mutate(undefined, { onSuccess: () => { void qc.invalidateQueries({ queryKey: ["auth", "me"] }); } })}
            >
              {upgrade.isPending ? "Setting up…" : "Set up advisor workspace"}
            </Btn>
          )}
          {upgrade.isError && <InlineError>Couldn’t set up the advisor workspace. {errorText(upgrade.error, "")}</InlineError>}
        </div>
      )}
    </section>
  );
}

// ── step 2: goals and risk ───────────────────────────────────────────────

function GoalLine({ goal }: { goal: Goal }) {
  const years = goalHorizonYears(goal.targetDate);
  return (
    <div data-testid="onboarding-goal" className="flex flex-wrap justify-between" style={{ gap: "4px 12px", padding: "14px 16px", borderRadius: 12, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
      <span style={{ fontSize: 14, minWidth: 0, overflowWrap: "anywhere" }}>{goal.name}</span>
      <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>
        {fmtINR(goal.targetAmount / 100, { compact: true })}
        {years ? ` · ${years}-year horizon` : ""}
      </span>
    </div>
  );
}

function StepGoals() {
  const wizard = useProfileWizard();
  const { goals, risk } = wizard;
  const list = goals.data?.goals ?? [];

  return (
    <section data-testid="onboarding-step-goals" className="flex flex-col" style={{ gap: 18 }}>
      <StepTitle>What are you investing for?</StepTitle>

      <div className="flex flex-col items-stretch" style={{ gap: 8 }}>
        {goals.isPending ? (
          <LoadingBlock label="Loading goals" rows={2} />
        ) : goals.isError ? (
          <ErrorBlock title="Goals didn’t load" error={goals.error} onRetry={() => goals.refetch()} />
        ) : list.length === 0 ? (
          <EmptyBlock title="No goals yet" body="A goal gives Nivesh an amount and a horizon to plan against. Add one now, or later from Settings." />
        ) : (
          list.map((g) => <GoalLine key={g.id} goal={g} />)
        )}
        <div><LinkButton tone="mint" data-testid="onboarding-add-goal" onClick={wizard.openGoal}>＋ Add a goal</LinkButton></div>
      </div>

      <div className="flex flex-col" style={{ gap: 10 }}>
        <Eyebrow>Risk you’re comfortable with</Eyebrow>
        {risk.state === "loading" ? (
          <LoadingBlock label="Loading risk profile" rows={1} />
        ) : risk.state === "error" ? (
          <ErrorBlock title="Risk profile didn’t load" error={risk.error} onRetry={risk.retry} />
        ) : risk.data ? (
          <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
            <span data-testid="onboarding-risk-category"><Pill tone="mint">{risk.data.category}</Pill></span>
            {riskAssessed(risk.data) && <span className="cp-mono-note">{riskAssessed(risk.data)}</span>}
            <Btn data-testid="onboarding-risk-retake" onClick={wizard.openRisk}>Retake</Btn>
          </div>
        ) : (
          <EmptyBlock
            title="No risk profile yet"
            body="A short questionnaire places you between Conservative and Aggressive. Nivesh uses the result in its recommendations."
            action={<Btn data-testid="onboarding-risk-start" onClick={wizard.openRisk}>Take the assessment</Btn>}
          />
        )}
      </div>

      <div className="flex flex-col" style={{ gap: 10 }}>
        <Eyebrow>Rules Nivesh must respect</Eyebrow>
        <NotConnected
          testId="onboarding-rules-missing"
          title="Portfolio rules can’t be saved yet"
          body="Limits such as the most you want in one stock or one sector, a cash buffer, or things never to suggest."
          needs={[
            "An endpoint that stores a user’s limits (single stock, single sector, cash buffer, exclusions)",
            "Recommendations and answers that read those limits",
          ]}
        />
      </div>

      {wizard.element}
    </section>
  );
}

// ── step 3: portfolio ────────────────────────────────────────────────────

function StepPortfolio({ onImported }: { onImported: (holdings: number | null) => void }) {
  const state = useOnboardingState();
  const [source, setSource] = useState<Source>("cas");

  return (
    <section data-testid="onboarding-step-portfolio" className="flex flex-col" style={{ gap: 18 }}>
      <StepTitle>Bring in your portfolio.</StepTitle>
      <span style={{ fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
        Read-only. A statement, or Gmail access to find one, gives Nivesh no way to place orders or move money.
      </span>
      <div role="group" aria-label="Where to import from" className="flex flex-wrap" style={{ gap: 6 }}>
        {SOURCES.map((s) => (
          <ToggleChip key={s.key} data-testid={`onboarding-source-${s.key}`} on={source === s.key} onClick={() => setSource(s.key)}>{s.label}</ToggleChip>
        ))}
      </div>

      {source === "cas" && <StatementUpload panOnFile={state.data?.pan_on_file ?? false} onImported={(r) => onImported(r.imported_holdings)} />}
      {source === "gmail" && <GmailSource onImported={() => onImported(null)} />}
      {source === "broker" && <BrokerSignInMissing />}
      {source === "csv" && (
        <NotConnected
          testId="onboarding-csv-missing"
          title="CSV and Excel import isn’t available here yet"
          body="The design maps your columns and shows new, matched and duplicate holdings before anything is saved. The server cannot do either."
          needs={[
            "An endpoint that reads a file and returns its columns for mapping, without saving",
            "A preview of new, matched, duplicate and unresolved holdings: POST /api/portfolio/upload saves the file’s rows at once",
            "A screen in this app that uses that upload (none does today)",
          ]}
        />
      )}
    </section>
  );
}

// ── done ─────────────────────────────────────────────────────────────────

function StepDone({ importedHoldings }: { importedHoldings: number | null }) {
  const { firstName } = useCopilotShell();
  const state = useOnboardingState();
  const s = state.data;
  const tiles: TileItem[] = [];
  if (s?.cas_statement_period) tiles.push({ k: "Statement on file", v: <span data-testid="onboarding-statement-period">{s.cas_statement_period}</span> });
  if (s?.cas_portfolio_value_rs != null) tiles.push({ k: "Value on the statement", v: <span data-testid="onboarding-statement-value">{fmtINR(s.cas_portfolio_value_rs)}</span> });
  if (s?.cas_statement_date) tiles.push({ k: "Statement date", v: s.cas_statement_date });

  return (
    <section data-testid="onboarding-step-done" className="flex flex-col" style={{ gap: 14 }}>
      <StepTitle size={44}>You’re set{firstName ? <>, <em>{firstName}</em></> : null}.</StepTitle>
      {importedHoldings != null && importedHoldings > 0 && (
        <span style={{ fontSize: 15, lineHeight: 1.6, color: "var(--cp-ink-2)" }}>
          <span className="cp-num" data-testid="onboarding-imported-count">{fmtNum(importedHoldings)}</span> holdings imported from your statement.
        </span>
      )}
      {state.isPending ? (
        <LoadingBlock label="Checking what is on file" rows={1} />
      ) : state.isError ? (
        <ErrorBlock title="Couldn’t check what is on file" error={state.error} onRetry={() => state.refetch()} />
      ) : tiles.length > 0 ? (
        <Tiles items={tiles} min={180} />
      ) : (
        <EmptyBlock
          title="No portfolio on file"
          body="Nivesh works for research without one. Add a statement any time from Broker connections."
        />
      )}
    </section>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

export default function OnboardingScreen() {
  const { go, mobile } = useCopilotShell();
  const setMode = useCopilotPrefs((s) => s.setMode);
  const pushToast = useToastStore((s) => s.push);
  const complete = useCompleteOnboarding();
  const [step, setStep] = useState<StepKey>("you");
  const [picked, setPicked] = useState<StartMode | null>(null);
  const [importedHoldings, setImportedHoldings] = useState<number | null>(null);

  const idx = FLOW.indexOf(step);
  const leaving = complete.isPending;

  const finish = () => {
    if (leaving) return;
    complete.mutate(undefined, {
      onSettled: (recorded) => {
        if (!recorded) {
          pushToast({ kind: "warn", title: "Setup wasn’t saved", description: "Nivesh couldn’t record that setup is finished, so it may show this again next time." });
        }
        if (picked) setMode(picked);
        go("");
      },
    });
  };

  return (
    <Screen testId="screen-onboarding">
      {/* The design's onboarding column is 720px, narrower than other screens. */}
      <div className="mx-auto flex w-full flex-col" style={{ maxWidth: 720, gap: mobile ? 22 : 28 }}>
        <div className="flex flex-wrap items-start" style={{ gap: "10px 16px" }}>
          <ol data-testid="onboarding-progress" aria-label="Setup steps" className="m-0 flex p-0" style={{ flex: "1 1 240px", gap: 6, listStyle: "none" }}>
            {PROGRESS.map((p, i) => {
              const reached = i <= idx;
              return (
                <li key={p.key} data-reached={reached} aria-current={p.key === step ? "step" : undefined} className="flex flex-col" style={{ flex: 1, gap: 6 }}>
                  <span style={{ height: 3, borderRadius: 2, background: reached ? "var(--mint)" : "var(--bg-3)" }} />
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase", color: reached ? "var(--cp-ink-2)" : "var(--cp-ink-4)" }}>{p.label}</span>
                </li>
              );
            })}
          </ol>
          {step !== "done" && (
            <LinkButton data-testid="onboarding-skip" disabled={leaving} onClick={finish}>{leaving ? "Leaving…" : "Skip setup"}</LinkButton>
          )}
        </div>

        {step === "you" && <StepYou picked={picked} onPick={setPicked} />}
        {step === "goals" && <StepGoals />}
        {step === "portfolio" && <StepPortfolio onImported={setImportedHoldings} />}
        {step === "done" && <StepDone importedHoldings={importedHoldings} />}

        <div className="flex flex-wrap items-center justify-between" style={{ gap: 12, paddingTop: 8 }}>
          {idx > 0 ? (
            <LinkButton data-testid="onboarding-back" disabled={leaving} onClick={() => setStep(FLOW[idx - 1])}>‹ Back</LinkButton>
          ) : (
            <span />
          )}
          <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
            {step === "portfolio" && (
              <LinkButton data-testid="onboarding-skip-import" disabled={leaving} onClick={finish}>Skip, research only</LinkButton>
            )}
            {step === "done" ? (
              <Btn variant="primary" data-testid="onboarding-finish" disabled={leaving} onClick={finish} style={{ padding: "11px 20px", fontSize: 14 }}>
                {leaving ? "Opening Nivesh…" : "Go to Nivesh"}
              </Btn>
            ) : (
              <Btn variant="primary" data-testid="onboarding-next" disabled={leaving} onClick={() => setStep(FLOW[idx + 1])} style={{ padding: "11px 20px", fontSize: 14 }}>
                Continue
              </Btn>
            )}
          </div>
        </div>
      </div>
    </Screen>
  );
}
