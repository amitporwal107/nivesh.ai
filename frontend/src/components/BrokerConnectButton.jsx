import React, { useEffect, useState } from "react";
import axios from "axios";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2, Link2, RefreshCw, Trash2, ShieldCheck, ExternalLink, Server } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * BrokerConnectButton — read-only broker-holdings import via OpenAlgo.
 *
 * Nivesh Secure Portfolio Connect treats every broker the same way: the
 * user runs their own self-hosted OpenAlgo instance, generates a
 * read-only API key there, and pastes it here. We store the key
 * AES-256-GCM encrypted and never see broker passwords / TOTP / PIN.
 *
 * Flow:
 *   - GET /api/broker/supported     → broker dropdown
 *   - GET /api/broker/accounts      → list user's existing connections
 *   - POST /api/broker/connect      → handshake + persist
 *   - POST /api/broker/accounts/{id}/sync → fetch holdings now
 *   - DELETE /api/broker/accounts/{id} → disconnect
 */
export default function BrokerConnectButton({
  onSync,
  className = "",
  testId = "broker-connect-btn",
  label = "Connect Broker",
}) {
  const [open, setOpen] = useState(false);
  const [supported, setSupported] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [syncingId, setSyncingId] = useState(null);

  // Hosted-config state — when `auto_provision` is true, the modal drops
  // the URL + API-key fields entirely; user just picks a broker and
  // Nivesh mints an OpenAlgo account using their Google email behind
  // the scenes. When `hosted` is true but `auto_provision` is false,
  // the user still pastes their key (after a manual OpenAlgo signup).
  // When neither is set, fall back to the self-hosted form (URL + key).
  const [hostedConfig, setHostedConfig] = useState({
    hosted: false,
    auto_provision: false,
    dashboard_url: "",
  });
  const [showAdvanced, setShowAdvanced] = useState(false);

  // form
  const [broker, setBroker] = useState("");
  const [openalgoUrl, setOpenalgoUrl] = useState("http://localhost:5000");
  const [apiKey, setApiKey] = useState("");
  const [labelInput, setLabelInput] = useState("");

  const refresh = async () => {
    setLoading(true);
    try {
      const [s, a, c] = await Promise.all([
        axios.get(`${API}/broker/supported`, { withCredentials: true }),
        axios.get(`${API}/broker/accounts`, { withCredentials: true }),
        axios.get(`${API}/broker/openalgo-config`, { withCredentials: true }),
      ]);
      setSupported(s.data?.brokers || []);
      setAccounts(a.data?.accounts || []);
      setHostedConfig({
        hosted: !!c.data?.hosted,
        auto_provision: !!c.data?.auto_provision,
        dashboard_url: c.data?.dashboard_url || "",
      });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load broker accounts");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) refresh();
  }, [open]);

  const resetForm = () => {
    setBroker("");
    setApiKey("");
    setLabelInput("");
  };

  // Three modes derived from hosted config + user toggle:
  //   * autoProvision  → Nivesh mints OpenAlgo creds server-side using
  //                      the user's Google email. Form shows broker
  //                      picker only.
  //   * hostedManual   → Hosted OpenAlgo URL is configured but no
  //                      management token, so user logs in to the
  //                      hosted dashboard, copies their key, pastes it.
  //   * selfHosted     → User runs their own OpenAlgo. Full form (URL + key).
  // Toggling "Advanced" forces selfHosted.
  const autoProvision =
    hostedConfig.hosted && hostedConfig.auto_provision && !showAdvanced;
  const hostedManual =
    hostedConfig.hosted && !hostedConfig.auto_provision && !showAdvanced;
  const selfHosted = !autoProvision && !hostedManual;

  const submitConnect = async () => {
    if (!broker) {
      toast.error("Pick a broker");
      return;
    }
    setSubmitting(true);
    try {
      let r;
      if (autoProvision) {
        // Server-to-server provisioning — no URL or API key from the user.
        r = await axios.post(
          `${API}/broker/connect-hosted`,
          { broker, label: labelInput.trim() || null },
          { withCredentials: true },
        );
      } else {
        if (!apiKey?.trim()) {
          toast.error("API key is required");
          setSubmitting(false);
          return;
        }
        if (selfHosted && !openalgoUrl?.trim()) {
          toast.error("OpenAlgo URL is required for self-hosted mode");
          setSubmitting(false);
          return;
        }
        const payload = {
          broker,
          api_key: apiKey.trim(),
          label: labelInput.trim() || null,
        };
        if (selfHosted) payload.openalgo_url = openalgoUrl.trim();
        r = await axios.post(`${API}/broker/connect`, payload, {
          withCredentials: true,
        });
      }
      toast.success(`Connected to ${r.data?.account?.broker_display || broker}`);
      resetForm();
      await refresh();

      // Auto-provisioned accounts land in `pending` until broker OAuth
      // completes — open the broker login URL in a new tab so the user
      // can finish authentication there.
      if (autoProvision && r.data?.broker_login_url) {
        window.open(r.data.broker_login_url, "_blank", "noopener");
      }
    } catch (e) {
      const msg = e?.response?.data?.detail || "Broker connect failed";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const sync = async (accountId) => {
    setSyncingId(accountId);
    try {
      const r = await axios.post(
        `${API}/broker/accounts/${accountId}/sync`,
        {},
        { withCredentials: true },
      );
      toast.success(`Imported ${r.data?.count || 0} holdings`);
      await refresh();
      onSync?.(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Sync failed");
    } finally {
      setSyncingId(null);
    }
  };

  const disconnect = async (accountId, brokerName) => {
    if (!window.confirm(`Disconnect ${brokerName}? This will remove its holdings.`)) {
      return;
    }
    try {
      await axios.delete(`${API}/broker/accounts/${accountId}`, { withCredentials: true });
      toast.success("Broker disconnected");
      await refresh();
      onSync?.(null);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Disconnect failed");
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button data-testid={testId} className={className}>
          <Link2 className="mr-2 h-4 w-4" />
          {label}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-emerald-600" />
            Secure Portfolio Connect — Brokers
          </DialogTitle>
        </DialogHeader>

        {autoProvision && (
          <p className="text-sm text-muted-foreground">
            Pick your broker. Nivesh signs you into our hosted OpenAlgo using
            your Google account, then takes you to the broker for{" "}
            <strong>read-only</strong> authorization. We never see your broker
            password or TOTP.
          </p>
        )}
        {hostedManual && (
          <p className="text-sm text-muted-foreground">
            Sign in to <strong>Nivesh-hosted OpenAlgo</strong>, connect your broker
            (Zerodha / Angel One / etc.), then copy your <strong>read-only</strong>
            API key here. Nivesh stores it AES-256-GCM encrypted.
          </p>
        )}
        {selfHosted && (
          <p className="text-sm text-muted-foreground">
            Connect a broker via your <strong>self-hosted</strong>{" "}
            <a
              href="https://docs.openalgo.in"
              target="_blank"
              rel="noreferrer"
              className="text-primary underline"
            >
              OpenAlgo
            </a>{" "}
            instance. Generate a read-only API key there and paste it below.
          </p>
        )}

        {/* Hosted dashboard link — only shown in hostedManual mode (when
            user actually needs to visit the dashboard to copy a key). */}
        {hostedManual && hostedConfig.dashboard_url && (
          <a
            href={hostedConfig.dashboard_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100 dark:border-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
            data-testid="broker-openalgo-dashboard-link"
          >
            <Server className="h-4 w-4" />
            Open OpenAlgo dashboard
            <ExternalLink className="h-3 w-3" />
          </a>
        )}

        {/* Connect form */}
        <div className="grid gap-3 rounded-lg border p-4">
          <div className="grid gap-2">
            <Label>Broker</Label>
            <Select value={broker} onValueChange={setBroker}>
              <SelectTrigger>
                <SelectValue placeholder="Select your broker" />
              </SelectTrigger>
              <SelectContent>
                {supported.map((b) => (
                  <SelectItem key={b.slug} value={b.slug}>
                    {b.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {selfHosted && (
            <div className="grid gap-2">
              <Label>OpenAlgo URL</Label>
              <Input
                value={openalgoUrl}
                onChange={(e) => setOpenalgoUrl(e.target.value)}
                placeholder="http://localhost:5000"
                data-testid="broker-openalgo-url"
              />
            </div>
          )}

          {!autoProvision && (
            <div className="grid gap-2">
              <Label>OpenAlgo API key (read-only)</Label>
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="paste read-only key from OpenAlgo dashboard"
                data-testid="broker-api-key"
              />
            </div>
          )}

          <div className="grid gap-2">
            <Label>Label (optional)</Label>
            <Input
              value={labelInput}
              onChange={(e) => setLabelInput(e.target.value)}
              placeholder="e.g. Zerodha-personal"
            />
          </div>

          <Button onClick={submitConnect} disabled={submitting} data-testid="broker-connect-submit">
            {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Verify & Connect
          </Button>

          {/* Advanced / self-hosted toggle — only relevant when hosted is
              configured. Without hosted, the URL field is already shown. */}
          {hostedConfig.hosted && (
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="text-xs text-muted-foreground underline self-start"
              data-testid="broker-advanced-toggle"
            >
              {showAdvanced
                ? "Use Nivesh-hosted OpenAlgo"
                : "Advanced — use my own self-hosted OpenAlgo"}
            </button>
          )}
        </div>

        {/* Existing accounts */}
        <div className="grid gap-2">
          <div className="text-sm font-medium">Connected brokers</div>
          {loading && <div className="text-sm text-muted-foreground">Loading…</div>}
          {!loading && accounts.length === 0 && (
            <div className="text-sm text-muted-foreground">
              No brokers connected yet.
            </div>
          )}
          {accounts.map((acc) => (
            <div
              key={acc.account_id}
              className="flex items-center justify-between rounded-md border p-3"
            >
              <div className="grid">
                <div className="font-medium flex items-center gap-2">
                  {acc.label || acc.broker_display || acc.broker}
                  {acc.openalgo_hosted && (
                    <span className="text-[10px] font-semibold uppercase tracking-wider rounded bg-emerald-100 text-emerald-700 px-1.5 py-0.5 dark:bg-emerald-900/40 dark:text-emerald-300">
                      Hosted
                    </span>
                  )}
                </div>
                <div className="text-xs text-muted-foreground">
                  {acc.openalgo_hosted
                    ? "via Nivesh-hosted OpenAlgo"
                    : acc.openalgo_url}{" "}
                  · key {acc.api_key_masked} ·{" "}
                  {acc.last_sync_at
                    ? `synced ${new Date(acc.last_sync_at).toLocaleString()} (${acc.last_sync_count} rows)`
                    : "never synced"}
                  {acc.last_error ? ` · last error: ${acc.last_error}` : ""}
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => sync(acc.account_id)}
                  disabled={syncingId === acc.account_id}
                  data-testid={`broker-sync-${acc.account_id}`}
                >
                  {syncingId === acc.account_id ? (
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                  ) : (
                    <RefreshCw className="mr-2 h-3 w-3" />
                  )}
                  Sync
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => disconnect(acc.account_id, acc.broker_display || acc.broker)}
                  data-testid={`broker-disconnect-${acc.account_id}`}
                >
                  <Trash2 className="h-4 w-4 text-rose-600" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
