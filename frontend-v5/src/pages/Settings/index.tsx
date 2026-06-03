import { Card, CardLabel } from "@/components/ui/card";
import { useUIStore } from "@/stores/ui.store";
import { useMe, useLogout } from "@/hooks/use-auth";
import { useGmailStatus, useGmailAutoImportToggle, useGmailConnect, useGmailDisconnect } from "@/hooks/use-gmail";
import { cn } from "@/lib/utils";
import { Mail, RefreshCw, CheckCircle2, AlertCircle } from "lucide-react";

export default function SettingsPage() {
  const { theme, setTheme } = useUIStore();
  const { data: me } = useMe();
  const logout = useLogout();

  const { data: gmailStatus, isLoading: gmailLoading } = useGmailStatus();
  const gmailToggle = useGmailAutoImportToggle();
  const gmailConnect = useGmailConnect();
  const gmailDisconnect = useGmailDisconnect();

  const email = me?.email ?? "—";

  function fmtDate(iso?: string) {
    if (!iso) return null;
    return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
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

      <Card className="mt-7 p-6">
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
          /* ── Not connected ── */
          <button
            onClick={() => gmailConnect.mutate()}
            disabled={gmailConnect.isPending}
            className="mt-4 flex items-center gap-2 px-4 py-2 rounded-md bg-accent text-white text-[13px] font-medium hover:bg-accent/90 transition-colors disabled:opacity-60"
          >
            <Mail className="h-4 w-4" />
            {gmailConnect.isPending ? "Redirecting…" : "Connect Gmail"}
          </button>
        ) : (
          /* ── Connected ── */
          <div className="mt-4 space-y-4">
            {/* Connected badge */}
            <div className="flex items-center gap-2 text-[13px]">
              <CheckCircle2 className="h-4 w-4 text-pos shrink-0" />
              <span className="text-ink-2">
                Gmail connected
                {gmailStatus.connected_at && (
                  <span className="text-ink-4 ml-1">· since {fmtDate(gmailStatus.connected_at)}</span>
                )}
              </span>
            </div>

            {/* Auto-sync toggle */}
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
              /* Connected but first manual import not done yet */
              <div className="flex items-start gap-2 text-[13px] text-ink-3">
                <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>
                  Complete your first manual CAS import to unlock auto-sync. Once done, we'll remember your preferences and sync daily.
                </span>
              </div>
            )}

            {/* Last import */}
            {gmailStatus.last_import && (
              <div className="text-[12px] text-ink-3 flex items-center gap-1.5">
                <RefreshCw className="h-3 w-3" />
                Last import: {gmailStatus.last_import.filename} · {fmtDate(gmailStatus.last_import.imported_at)} · {gmailStatus.last_import.count} holdings
              </div>
            )}

            {/* Disconnect */}
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
