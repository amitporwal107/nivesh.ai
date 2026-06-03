import { RefreshCw, Loader2, CheckCircle2, XCircle, AlertTriangle, Server, Activity } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { NidpError } from "./NidpError";
import { useQuery } from "@tanstack/react-query";

interface DiagData {
  env: {
    NIDP_QUERY_API_URL_set: boolean;
    NIDP_QUERY_API_TOKEN_set: boolean;
    NIDP_QUERY_API_URL: string;
    POSTGRES_URL_set: boolean;
  };
  nidp_query_api: {
    reachable: boolean;
    health: { ok: boolean; db_ok: boolean; db_latency_ms: number | null; error: string | null } | null;
    reach_error: string | null;
    auth_ok: boolean;
    auth_error: string | null;
  };
  app_pool: { ok: boolean; error: string | null };
  hint?: string;
}

type CheckStatus = "ok" | "warn" | "error";

interface Check { name: string; status: CheckStatus; detail?: string; latency?: number }

function buildChecks(d: DiagData): Check[] {
  const checks: Check[] = [];
  checks.push({
    name: "NIDP_QUERY_API_URL configured",
    status: d.env.NIDP_QUERY_API_URL_set ? "ok" : "error",
    detail: d.env.NIDP_QUERY_API_URL_set ? d.env.NIDP_QUERY_API_URL : "Not set — add via Admin → Secrets",
  });
  checks.push({
    name: "NIDP_QUERY_API_TOKEN configured",
    status: d.env.NIDP_QUERY_API_TOKEN_set ? "ok" : "error",
    detail: d.env.NIDP_QUERY_API_TOKEN_set ? "Token present" : "Not set — add via Admin → Secrets",
  });
  checks.push({
    name: "App Postgres pool",
    status: d.app_pool.ok ? "ok" : "error",
    detail: d.app_pool.error ?? "Connected",
  });
  checks.push({
    name: "NIDP Query API reachable",
    status: d.nidp_query_api.reachable ? "ok" : "error",
    detail: d.nidp_query_api.reach_error ?? d.env.NIDP_QUERY_API_URL,
  });
  if (d.nidp_query_api.reachable) {
    const h = d.nidp_query_api.health;
    checks.push({
      name: "NIDP Query API — DB connection",
      status: h?.db_ok ? "ok" : "error",
      detail: h?.error ?? (h?.db_ok ? "NIDP Postgres connected" : "DB error"),
      latency: h?.db_latency_ms ?? undefined,
    });
    checks.push({
      name: "NIDP Query API — bearer auth",
      status: d.nidp_query_api.auth_ok ? "ok" : "error",
      detail: d.nidp_query_api.auth_error ?? "Token accepted",
    });
  }
  return checks;
}

const STATUS_ICON: Record<CheckStatus, React.ReactNode> = {
  ok: <CheckCircle2 className="w-4 h-4 text-pos" />,
  warn: <AlertTriangle className="w-4 h-4 text-warm" />,
  error: <XCircle className="w-4 h-4 text-neg" />,
};
const STATUS_TONE: Record<CheckStatus, "good" | "warm" | "neg"> = { ok: "good", warn: "warm", error: "neg" };

export function DiagnosticsPanel() {
  const { data, isFetching, refetch, error } = useQuery({
    queryKey: ["nidp", "diag"],
    queryFn: () => http<DiagData>({ path: "/api/admin/nidp/diag", timeoutMs: 20_000 }).then((r) => r.data),
    staleTime: 30_000,
  });

  const checks = data ? buildChecks(data) : [];
  const allOk = checks.every((c) => c.status === "ok");
  const hasError = checks.some((c) => c.status === "error");

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
                <p className="text-xs text-ink-3">Connection status · secrets config · NIDP Query API health</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {data && (
                <Badge tone={allOk ? "good" : hasError ? "neg" : "warm"}>
                  {allOk ? "All healthy" : hasError ? "Errors" : "Warnings"}
                </Badge>
              )}
              <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
                {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              </Button>
            </div>
          </div>

          {error && <div className="mb-4"><NidpError err={error} /></div>}

          {data?.env.NIDP_QUERY_API_URL && (
            <div className="text-xs text-ink-3 mb-4 flex items-center gap-2">
              <Server className="w-3.5 h-3.5" />
              Query API: <code className="text-ink-2">{data.env.NIDP_QUERY_API_URL}</code>
            </div>
          )}

          <div className="space-y-2">
            {checks.map((check) => (
              <div key={check.name} className="flex items-center gap-3 rounded-lg border border-hairline p-3">
                {STATUS_ICON[check.status]}
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-ink">{check.name}</div>
                  {check.detail && <div className="text-xs text-ink-3 mt-0.5 truncate">{check.detail}</div>}
                </div>
                {check.latency != null && (
                  <span className="text-xs font-mono text-ink-3 shrink-0">{check.latency.toFixed(0)}ms</span>
                )}
                <Badge tone={STATUS_TONE[check.status]}>{check.status}</Badge>
              </div>
            ))}
            {!isFetching && !data && !error && (
              <div className="text-center text-sm text-ink-3 py-6">No diagnostic data returned.</div>
            )}
          </div>

          {data?.hint && (
            <div className="mt-4 text-xs text-ink-3 bg-surface-1 rounded-lg px-3 py-2">{data.hint}</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
