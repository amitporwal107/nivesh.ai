/**
 * Filing alerts — which company filings the user wants to hear about, and where.
 *
 *   GET /api/filings/alerts   the saved choices, the list of filing types, and
 *                             whether anything is actually being sent
 *   PUT /api/filings/alerts   replace the choices (filingsService.putAlerts — the
 *                             call the original Research › Alerts screen makes)
 *
 * A switch shows what is stored: it moves only after the save has succeeded,
 * and a failed save says so. Delivery is a separate fact the response reports
 * (`delivery.active`); while it is off the screen says nothing is sent.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { filingsService, type Alerts } from "@/services/adapters/filings.adapter";
import { EmptyBlock, Footnote, LoadingBlock, Pill, TONE_COLOR, fmtNum, humaniseTag, relTime, type Tone } from "../../components/ui";
import { useFilingAlerts } from "../markets/hooks";
import { LoadError } from "../markets/parts";

/** The key useFilingAlerts reads under. */
const ALERTS_KEY = ["filings", "alerts"] as const;

const CHANNEL: Record<string, { label: string; hint: string }> = {
  email: { label: "Email", hint: "To your account address." },
  whatsapp: { label: "WhatsApp", hint: "No WhatsApp sender is connected yet, so this only records your choice." },
};

function Switch({ on, label, disabled, onChange, testId }: { on: boolean; label: string; disabled: boolean; onChange: () => void; testId: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      data-testid={testId}
      disabled={disabled}
      onClick={onChange}
      style={{
        flex: "none", width: 38, height: 22, padding: 2, borderRadius: 999, cursor: disabled ? "not-allowed" : "pointer",
        border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`, background: on ? "var(--mint-soft)" : "var(--bg-2)",
        display: "inline-flex", justifyContent: on ? "flex-end" : "flex-start", alignItems: "center", opacity: disabled ? 0.6 : 1,
      }}
    >
      <span aria-hidden style={{ width: 16, height: 16, borderRadius: 999, background: on ? "var(--mint)" : "var(--cp-ink-3)" }} />
    </button>
  );
}

export function FilingAlertSettings() {
  const q = useFilingAlerts();
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (next: { types: Record<string, boolean>; channels: Record<string, boolean> }) => filingsService.putAlerts(next),
    onSuccess: (stored: Alerts) => qc.setQueryData(ALERTS_KEY, stored),
  });

  if (q.isPending) return <LoadingBlock label="Loading your alerts" />;
  if (q.isError) return <LoadError title="Your alert preferences didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const prefs = q.data;
  // true = alerts are being sent, false = saved but nothing is sent, null = the response did not say.
  const sending = prefs.delivery ? prefs.delivery.active : null;
  const channelKeys = Object.keys(prefs.channels);
  const channelsOn = channelKeys.filter((c) => prefs.channels[c]).map((c) => CHANNEL[c]?.label ?? humaniseTag(c));
  const onCount = prefs.catalog.filter((c) => prefs.types[c.key]).length;

  if (prefs.catalog.length === 0) {
    return (
      <div className="flex flex-col" style={{ gap: 10 }}>
        <span className="cp-eyebrow">Filing alerts</span>
        <EmptyBlock title="No filing-alert types to show" body="The list of filing types did not come back with your preferences." />
      </div>
    );
  }

  const setType = (key: string) => save.mutate({ types: { ...prefs.types, [key]: !prefs.types[key] }, channels: prefs.channels });
  const setChannel = (key: string) => save.mutate({ types: prefs.types, channels: { ...prefs.channels, [key]: !prefs.channels[key] } });

  return (
    <div className="flex flex-col" style={{ gap: 10 }} data-testid="watchlist-alerts">
      <span className="cp-eyebrow">
        Filing alerts · <span data-testid="watchlist-alerts-on">{fmtNum(onCount)}</span> of {fmtNum(prefs.catalog.length)} types on
      </span>

      {sending === false && (
        <div
          data-testid="watchlist-alerts-delivery"
          style={{ padding: "10px 14px", borderRadius: 12, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}
        >
          {prefs.delivery?.note ?? "Preferences are saved, but scheduled delivery is not switched on yet."}
        </div>
      )}

      {prefs.catalog.map((c) => {
        const on = !!prefs.types[c.key];
        const tone: Tone = !on ? "ink" : sending === true ? "mint" : sending === false ? "amber" : "ink";
        const status = !on ? "Off" : sending === true ? "On" : sending === false ? "Saved · not sending" : "Saved";
        return (
          <div key={c.key} data-testid="watchlist-alert" data-key={c.key} className="cp-card flex flex-wrap items-center" style={{ gap: "8px 14px", padding: "12px 16px", borderRadius: 12 }}>
            <span className="nv-dot" style={{ background: on ? TONE_COLOR[tone] : "var(--cp-ink-4)" }} aria-hidden />
            <span style={{ flex: "1 1 200px", fontSize: 14 }}>{c.label}</span>
            <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>
              {on ? (channelsOn.length ? channelsOn.join(" · ") : "No channel chosen") : "—"}
            </span>
            <Pill tone={tone}>{status}</Pill>
            <Switch on={on} label={`${c.label} alerts`} disabled={save.isPending} onChange={() => setType(c.key)} testId="watchlist-alert-switch" />
          </div>
        );
      })}

      {channelKeys.length > 0 && (
        <>
          <span className="cp-eyebrow" style={{ paddingTop: 6 }}>Where to send them</span>
          {channelKeys.map((key) => {
            const on = !!prefs.channels[key];
            const label = CHANNEL[key]?.label ?? humaniseTag(key);
            return (
              <div key={key} data-testid="watchlist-alert-channel" data-key={key} className="cp-card flex flex-wrap items-center" style={{ gap: "8px 14px", padding: "12px 16px", borderRadius: 12 }}>
                <span className="flex min-w-0 flex-col" style={{ flex: "1 1 200px", gap: 2 }}>
                  <span style={{ fontSize: 14 }}>{label}</span>
                  {CHANNEL[key]?.hint && <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{CHANNEL[key].hint}</span>}
                </span>
                <Switch on={on} label={`Send filing alerts by ${label}`} disabled={save.isPending} onChange={() => setChannel(key)} testId="watchlist-channel-switch" />
              </div>
            );
          })}
        </>
      )}

      {save.isError && (
        <div data-testid="watchlist-alerts-save-error">
          <LoadError title="Your alert choice wasn’t saved, so nothing changed" error={save.error} />
        </div>
      )}
      <Footnote>
        {save.isPending ? "Saving…" : prefs.updatedAt ? `Preferences saved ${relTime(prefs.updatedAt)}` : "These are the starting choices; nothing has been saved yet."}
      </Footnote>
    </div>
  );
}
