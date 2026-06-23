import { useState } from "react";
import { Card, CardLabel } from "@/components/ui/card";
import { useUIStore } from "@/stores/ui.store";
import { useMe, useLogout } from "@/hooks/use-auth";
import { useGmailStatus, useGmailAutoImportToggle, useGmailConnect, useGmailDisconnect } from "@/hooks/use-gmail";
import { useRiskProfile } from "@/hooks/use-risk-profile";
import { useGoals, useGoalsSnapshot, useGoalArchive, useSnapshotUpsert } from "@/hooks/use-goals";
import { cn } from "@/lib/utils";
import { Mail, RefreshCw, CheckCircle2, AlertCircle, ShieldCheck, Target, Pencil, Trash2 } from "lucide-react";
import { ProfileWizardModal } from "@/pages/Dashboard/ProfileWizardModal";
import { useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Link } from "react-router-dom";
import { getAdminNav } from "@/components/layout/nav-items";

export default function SettingsPage() {
  const { theme, setTheme } = useUIStore();
  const { data: me } = useMe();
  const logout = useLogout();
  const qc = useQueryClient();

  const { data: gmailStatus, isLoading: gmailLoading } = useGmailStatus();
  const gmailToggle = useGmailAutoImportToggle();
  const gmailConnect = useGmailConnect();
  const gmailDisconnect = useGmailDisconnect();

  const { data: riskProfile } = useRiskProfile();
  const { data: goalsData } = useGoals();
  const { data: snapshot } = useGoalsSnapshot();
  const archiveGoal = useGoalArchive();
  const upsertSnapshot = useSnapshotUpsert();

  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardStep, setWizardStep] = useState<0 | 1 | 2>(0);

  const [snapAge, setSnapAge] = useState("");
  const [snapIncome, setSnapIncome] = useState("");
  const [snapExpenses, setSnapExpenses] = useState("");
  const [snapSaved, setSnapSaved] = useState(false);

  function openWizard(step: 0 | 1 | 2) {
    setWizardStep(step);
    setWizardOpen(true);
  }

  async function saveSnapshot() {
    const body: Record<string, number> = {};
    if (snapAge)      body.age = parseInt(snapAge, 10);
    if (snapIncome)   body.monthly_income_rs = parseFloat(snapIncome);
    if (snapExpenses) body.monthly_expenses_rs = parseFloat(snapExpenses);
    await upsertSnapshot.mutateAsync(body as any);
    setSnapSaved(true);
    setTimeout(() => setSnapSaved(false), 3000);
  }

  const email = me?.email ?? "—";
  const goals = goalsData?.goals ?? [];

  function fmtDate(iso?: string) {
    if (!iso) return null;
    return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  }

  function fmtRs(paise: number) {
    const rs = paise / 100;
    if (rs >= 1_00_00_000) return `₹${(rs / 1_00_00_000).toFixed(1)} Cr`;
    if (rs >= 1_00_000)    return `₹${(rs / 1_00_000).toFixed(1)} L`;
    return `₹${Math.round(rs / 1_000)}k`;
  }

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[820px] mx-auto w-full">
      <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Settings</div>
      <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
        Make it yours.
      </h1>
      <p className="text-[15.5px] text-ink-2 mt-3 max-w-[560px] leading-relaxed">
        Pick a look, control your notifications, manage your data. Changes save automatically.
      </p>

      <ProfileWizardModal
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        completeness={{
          hasRiskProfile: Boolean(riskProfile),
          hasGoal: goals.length > 0,
          hasSnapshot: Boolean(snapshot),
        }}
        existingProfile={riskProfile}
        startStep={wizardStep}
        onComplete={() => {
          setWizardOpen(false);
          qc.invalidateQueries({ queryKey: ["user", "risk-profile"] });
          qc.invalidateQueries({ queryKey: ["goals"] });
          qc.invalidateQueries({ queryKey: ["plans"] });
        }}
      />

      {/* ── Financial Profile ─────────────────────────────────────────────── */}
      <Card className="mt-7 p-6">
        <CardLabel>Financial Profile</CardLabel>
        <p className="text-[13px] text-ink-3 mt-1 mb-5">
          Your risk profile and goals drive all personalised recommendations.
        </p>

        {/* Risk profile */}
        <div className="mb-5 pb-5 border-b border-hairline">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-accent" />
              <span className="text-[13px] font-medium">Risk profile</span>
            </div>
            <button
              onClick={() => openWizard(0)}
              className="flex items-center gap-1 text-[12px] text-accent hover:underline underline-offset-4"
            >
              <Pencil className="h-3 w-3" />
              {riskProfile ? "Retake" : "Set up"}
            </button>
          </div>
          {riskProfile ? (
            <div className="flex items-center gap-3 flex-wrap">
              <Badge tone="accent" className="text-[10px]">{riskProfile.category}</Badge>
              <span className="font-mono text-[11px] text-ink-3">
                Score {riskProfile.score} · assessed {fmtDate(riskProfile.completed_at) ?? "—"}
              </span>
            </div>
          ) : (
            <p className="text-[12.5px] text-ink-3">
              No risk profile yet — take the 6-question assessment to unlock personalised actions.
            </p>
          )}
        </div>

        {/* Goals */}
        <div className="mb-5 pb-5 border-b border-hairline">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Target className="h-4 w-4 text-accent" />
              <span className="text-[13px] font-medium">Goals</span>
            </div>
            <button
              onClick={() => openWizard(1)}
              className="text-[12px] text-accent hover:underline underline-offset-4"
            >
              + Add goal
            </button>
          </div>
          {goals.length === 0 ? (
            <p className="text-[12.5px] text-ink-3">No goals yet. Add one to personalise your action plan.</p>
          ) : (
            <ul className="space-y-1">
              {goals.map(g => {
                const pct = Math.round(g.progress * 100);
                return (
                  <li
                    key={g.id}
                    className="flex items-center gap-3 py-2 px-2 -mx-2 rounded-md hover:bg-surface-2 transition-colors group"
                  >
                    <span className="text-[15px]">{g.icon}</span>
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium truncate">{g.name}</div>
                      <div className="font-mono text-[10px] text-ink-3 mt-0.5">
                        {fmtRs(g.targetAmount)} · by {g.targetDate} · {pct}% funded
                      </div>
                    </div>
                    <button
                      onClick={() => archiveGoal.mutate(g.id)}
                      disabled={archiveGoal.isPending}
                      className="opacity-0 group-hover:opacity-100 transition-opacity text-ink-4 hover:text-neg disabled:opacity-30"
                      aria-label="Archive goal"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Financial snapshot */}
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[13px] font-medium">Financial snapshot</span>
            {snapshot?.updated_at && (
              <span className="font-mono text-[10px] text-ink-4">· last updated {fmtDate(snapshot.updated_at)}</span>
            )}
          </div>
          <p className="text-[12.5px] text-ink-3 mb-4">
            Optional — helps calibrate SIP targets and goal projections.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="font-mono text-[10px] uppercase tracking-[.1em] text-ink-3 block mb-1">Age</label>
              <input
                type="number"
                placeholder={snapshot?.age ? String(snapshot.age) : "e.g. 32"}
                value={snapAge}
                onChange={e => setSnapAge(e.target.value)}
                className="w-full rounded-md border border-hairline bg-surface-2 px-3 py-2 text-[13px] focus:outline-none focus:border-accent transition-colors"
              />
            </div>
            <div>
              <label className="font-mono text-[10px] uppercase tracking-[.1em] text-ink-3 block mb-1">Monthly income (₹)</label>
              <input
                type="number"
                placeholder={snapshot?.monthly_income_rs ? String(snapshot.monthly_income_rs) : "e.g. 1,00,000"}
                value={snapIncome}
                onChange={e => setSnapIncome(e.target.value)}
                className="w-full rounded-md border border-hairline bg-surface-2 px-3 py-2 text-[13px] focus:outline-none focus:border-accent transition-colors"
              />
            </div>
            <div>
              <label className="font-mono text-[10px] uppercase tracking-[.1em] text-ink-3 block mb-1">Monthly expenses (₹)</label>
              <input
                type="number"
                placeholder={snapshot?.monthly_expenses_rs ? String(snapshot.monthly_expenses_rs) : "e.g. 60,000"}
                value={snapExpenses}
                onChange={e => setSnapExpenses(e.target.value)}
                className="w-full rounded-md border border-hairline bg-surface-2 px-3 py-2 text-[13px] focus:outline-none focus:border-accent transition-colors"
              />
            </div>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={saveSnapshot}
              disabled={upsertSnapshot.isPending || (!snapAge && !snapIncome && !snapExpenses)}
              className="px-4 py-2 rounded-md bg-accent text-on-accent text-[12px] font-medium hover:opacity-90 transition-opacity disabled:opacity-40"
            >
              {upsertSnapshot.isPending ? "Saving…" : "Save snapshot"}
            </button>
            {snapSaved && <span className="text-[12px] text-pos">Saved</span>}
            {upsertSnapshot.isError && <span className="text-[12px] text-neg">Save failed — try again</span>}
          </div>
        </div>
      </Card>

      <Card className="mt-4 p-6">
        <CardLabel>Theme</CardLabel>
        <div className="grid grid-cols-2 gap-3 mt-4">
          {[
            { v: "light" as const, l: "Light",  sw: ["#FAFAF7", "#0F172A", "#4338CA"] },
            { v: "dark"  as const, l: "Dark",   sw: ["#0B0E14", "#ECEEF3", "#8177E8"] },
          ].map((t) => {
            const on = theme === t.v;
            return (
              <button
                key={t.v}
                type="button"
                onClick={() => setTheme(t.v)}
                aria-pressed={on}
                className={cn(
                  "rounded-md p-4 text-left transition-colors border",
                  on ? "bg-accent-soft border-accent/30" : "bg-surface-1 border-hairline hover:bg-surface-2",
                )}
              >
                <div className="flex gap-1.5 mb-3">
                  {t.sw.map((c, i) => <span key={i} className="flex-1 h-7 rounded-sm border border-black/5" style={{ background: c }} />)}
                </div>
                <div className="text-[13px] font-medium">{t.l}</div>
              </button>
            );
          })}
        </div>
      </Card>

      <Card className="mt-4 p-6">
        <CardLabel>Notifications</CardLabel>
        <ul className="mt-3 divide-y divide-[rgb(var(--line)/0.10)]">
          {[
            { l: "A goal needs a top-up", on: true },
            { l: "Tax-saving window opens", on: true },
            { l: "My SIP runs each month", on: false },
            { l: "Daily money update", on: false },
          ].map((s) => (
            <li key={s.l} className="flex items-center py-3">
              <span className="text-[14px]">{s.l}</span>
              <span className={cn(
                "ml-auto h-6 w-10 rounded-full relative transition-colors",
                s.on ? "bg-accent" : "bg-surface-3",
              )}>
                <span className={cn(
                  "absolute top-0.5 h-5 w-5 rounded-full bg-surface-1 transition-all shadow",
                  s.on ? "left-[18px]" : "left-0.5",
                )} />
              </span>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="mt-4 p-6">
        <CardLabel>Gmail Sync</CardLabel>
        <p className="text-[13.5px] text-ink-2 mt-2 leading-relaxed max-w-[480px]">
          Connect your Gmail so Nivesh can automatically import your latest CAS statement each day — no manual uploads needed.
        </p>

        {gmailLoading ? (
          <div className="mt-4 h-10 w-48 rounded-md bg-surface-2 animate-pulse" />
        ) : !gmailStatus?.connected ? (
          <button
            onClick={() => gmailConnect.mutate()}
            disabled={gmailConnect.isPending}
            className="mt-4 flex items-center gap-2 px-4 py-2 rounded-md bg-accent text-white text-[13px] font-medium hover:bg-accent/90 transition-colors disabled:opacity-60"
          >
            <Mail className="h-4 w-4" />
            {gmailConnect.isPending ? "Redirecting…" : "Connect Gmail"}
          </button>
        ) : (
          <div className="mt-4 space-y-4">
            <div className="flex items-center gap-2 text-[13px]">
              <CheckCircle2 className="h-4 w-4 text-pos shrink-0" />
              <span className="text-ink-2">
                Gmail connected
                {gmailStatus.connected_at && (
                  <span className="text-ink-4 ml-1">· since {fmtDate(gmailStatus.connected_at)}</span>
                )}
              </span>
            </div>

            {gmailStatus.auto_import_ready ? (
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-[13.5px] font-medium">Auto-sync CAS daily</div>
                  <div className="text-[12px] text-ink-3 mt-0.5">
                    {gmailStatus.auto_import_enabled
                      ? `Syncing automatically${gmailStatus.last_auto_import_at ? ` · last run ${fmtDate(gmailStatus.last_auto_import_at)}` : ""}`
                      : "Automatic sync is off — we won't scan your inbox"}
                  </div>
                </div>
                <button
                  role="switch"
                  aria-checked={gmailStatus.auto_import_enabled}
                  onClick={() => gmailToggle.mutate(!gmailStatus.auto_import_enabled)}
                  disabled={gmailToggle.isPending}
                  className={cn(
                    "ml-6 h-6 w-10 rounded-full relative transition-colors shrink-0 disabled:opacity-60",
                    gmailStatus.auto_import_enabled ? "bg-accent" : "bg-surface-3",
                  )}
                >
                  <span className={cn(
                    "absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all shadow",
                    gmailStatus.auto_import_enabled ? "left-[18px]" : "left-0.5",
                  )} />
                </button>
              </div>
            ) : (
              <div className="flex items-start gap-2 text-[13px] text-ink-3">
                <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>
                  Complete your first manual CAS import to unlock auto-sync. Once done, we'll remember your preferences and sync daily.
                </span>
              </div>
            )}

            {gmailStatus.last_import && (
              <div className="text-[12px] text-ink-3 flex items-center gap-1.5">
                <RefreshCw className="h-3 w-3" />
                Last import: {gmailStatus.last_import.filename} · {fmtDate(gmailStatus.last_import.imported_at)} · {gmailStatus.last_import.count} holdings
              </div>
            )}

            <button
              onClick={() => gmailDisconnect.mutate()}
              disabled={gmailDisconnect.isPending}
              className="text-[12px] text-ink-3 hover:text-neg underline-offset-4 hover:underline transition-colors disabled:opacity-60"
            >
              {gmailDisconnect.isPending ? "Disconnecting…" : "Disconnect Gmail"}
            </button>
          </div>
        )}
      </Card>

      {/* Admin tools — relocated here from the primary sidebar nav. Only
          rendered for admins. */}
      {me?.is_admin && (
        <Card className="mt-4 p-6">
          <CardLabel>Admin</CardLabel>
          <p className="text-[13px] text-ink-3 mt-1 mb-4">
            Platform tooling. Only visible to admins.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {getAdminNav(true).map(({ to, label, icon: Icon }) => (
              <Link
                key={to}
                to={to}
                className="flex items-center gap-2.5 rounded-md border border-hairline bg-surface-1 px-3.5 py-3 text-[13px] text-ink-2 hover:bg-surface-2 transition-colors"
              >
                <Icon className="h-4 w-4 text-accent shrink-0" />
                <span>{label}</span>
              </Link>
            ))}
          </div>
        </Card>
      )}

      <Card className="mt-4 p-6">
        <CardLabel>Account</CardLabel>
        <div className="mt-3 text-[14px]">
          <div>{email}</div>
          <div className="font-mono text-[11px] text-ink-3 mt-1">
            {me ? "Connected · Google OAuth" : "Not signed in"}
          </div>
        </div>
        <div className="mt-5 flex gap-2">
          <button className="text-[13px] text-ink-2 hover:text-ink underline-offset-4 hover:underline">Export my data</button>
          <span className="text-ink-4">·</span>
          <button
            className="text-[13px] text-neg hover:underline underline-offset-4"
            onClick={() => logout.mutate()}
          >
            Sign out
          </button>
        </div>
      </Card>
    </div>
  );
}
