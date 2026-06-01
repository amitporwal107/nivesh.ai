import { RefreshCw, Loader2, CheckCircle2, XCircle, AlertTriangle, Server, Database, Activity } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { NidpError } from "./NidpError";
import { useQuery } from "@tanstack/react-query";

interface DiagCheck {
  name: string;
  status: "ok" | "warn" | "error";
  detail?: string;
  latency_ms?: number;
}

interface DiagData {
  checks: DiagCheck[];
  environment?: string;
  generated_at?: string;
}

const STATUS_ICON = {
  ok: <CheckCircle2 className="w-4 h-4 text-pos" />,
  warn: <AlertTriangle className="w-4 h-4 text-warm" />,
  error: <XCircle className="w-4 h-4 text-neg" />,
};

const STATUS_TONE: Record<string, "good" | "warm" | "neg"> = { ok: "good", warn: "warm", error: "neg" };

export function DiagnosticsPanel() {
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: ["nidp", "diagnostics"],
    queryFn: () => http<DiagData>({ path: "/api/admin/nidp/diagnostics", timeoutMs: 20_000 }).then((r) => r.data),
    staleTime: 30_000,
  });

  const { data: dumpRunning, refetch: triggerDump } = useQuery({
    queryKey: ["nidp", "dump-status"],
    queryFn: async () => {
      await http({ method: "POST", path: "/api/admin/nidp/dump", body: {} });
      return true;
    },
    enabled: false,
  });

  const allOk = data?.checks.every((c) => c.status === "ok");
  const hasError = data?.checks.some((c) => c.status === "error");

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
                <Activity className="w-5 h-5 text-accent" />
              </div>
              <div>
                <h2 className="text-base font-semibold text-ink">NIDP Diagnostics</h2>
                <p className="text-xs text-ink-3">Connection status, env checks, and one-button debug bundle.</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {data && (
                <Badge tone={allOk ? "good" : hasError ? "neg" : "warm"}>
                  {allOk ? "All healthy" : hasError ? "Errors detected" : "Warnings"}
                </Badge>
              )}
              <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
                {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              </Button>
            </div>
          </div>

          {error && <div className="mb-4"><NidpError err={error} /></div>}

          {data?.environment && (
            <div className="text-xs text-ink-3 mb-4 flex items-center gap-2">
              <Server className="w-3.5 h-3.5" /> Environment: <strong className="text-ink-2">{data.environment}</strong>
            </div>
          )}

          <div className="space-y-2">
            {(data?.checks ?? []).map((check) => (
              <div key={check.name} className="flex items-center gap-3 rounded-lg border border-hairline p-3">
                {STATUS_ICON[check.status]}
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-ink">{check.name}</div>
                  {check.detail && <div className="text-xs text-ink-3 mt-0.5 truncate">{check.detail}</div>}
                </div>
                {check.latency_ms != null && (
                  <span className="text-xs font-mono text-ink-3 shrink-0">{check.latency_ms.toFixed(0)}ms</span>
                )}
                <Badge tone={STATUS_TONE[check.status]}>{check.status}</Badge>
              </div>
            ))}
            {!isFetching && !data && !error && (
              <div className="text-center text-sm text-ink-3 py-6">No diagnostic data returned.</div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Debug dump */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-ink">Debug Bundle</h3>
              <p className="text-xs text-ink-3 mt-0.5">Triggers a full diagnostics dump to the server logs (NIDP VM). Check Grafana or <code>docker logs nidp-api</code> for output.</p>
            </div>
            <Button size="sm" variant="outline" onClick={() => triggerDump()}>
              <Database className="w-3.5 h-3.5" /> Run dump
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
