import { ExternalLink, RefreshCw, Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { apiConfig } from "@/services/api/config";

interface NidpDiag {
  grafana_url?: string;
  grafana_embed_url?: string;
}

function useNidpDiag() {
  return useQuery({
    queryKey: ["nidp", "diag"],
    queryFn: () => http<NidpDiag>({ path: "/api/admin/nidp/diag", timeoutMs: 15_000 }).then((r) => r.data).catch(() => ({} as NidpDiag)),
    staleTime: 5 * 60_000,
  });
}

export function GrafanaEmbed() {
  const [iframeKey, setIframeKey] = useState(0);
  const { data: diag, isPending } = useNidpDiag();

  // grafana_embed_url is a same-origin proxy path (/api/admin/nidp/grafana/...)
  // which avoids mixed-content blocks when the Grafana VM serves plain HTTP.
  const embedSrc = diag?.grafana_embed_url
    ? `${apiConfig.baseUrl}${diag.grafana_embed_url}`
    : null;
  const openUrl = diag?.grafana_url ?? null;

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold text-ink">Grafana — Live Feed Health</h2>
            <p className="text-xs text-ink-3 mt-0.5">
              Job-health dashboard proxied from the NIDP VM Grafana instance.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => setIframeKey((k) => k + 1)} disabled={isPending}>
              <RefreshCw className="w-3.5 h-3.5" />
            </Button>
            {openUrl && (
              <a href={openUrl} target="_blank" rel="noreferrer">
                <Button size="sm" variant="outline">
                  <ExternalLink className="w-3.5 h-3.5" /> Open
                </Button>
              </a>
            )}
          </div>
        </div>

        <div className="rounded-lg overflow-hidden border border-hairline" style={{ height: "620px" }}>
          {isPending ? (
            <div className="w-full h-full flex items-center justify-center bg-surface-1">
              <Loader2 className="w-6 h-6 text-ink-3 animate-spin" />
            </div>
          ) : embedSrc ? (
            <iframe
              key={iframeKey}
              src={embedSrc}
              className="w-full h-full"
              title="NIDP Grafana Dashboard"
              frameBorder="0"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-surface-1 text-sm text-ink-3">
              Grafana URL not available — check NIDP_GRAFANA_URL config.
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
