import { ExternalLink, RefreshCw } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useState } from "react";

const GRAFANA_URL = "https://data.niveshcopilot.com/grafana/d/feed-health?orgId=1&kiosk=tv";

export function GrafanaEmbed() {
  const [key, setKey] = useState(0);

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold text-ink">Grafana — Live Feed Health</h2>
            <p className="text-xs text-ink-3 mt-0.5">Job-health dashboard embedded from the NIDP VM Grafana instance.</p>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => setKey((k) => k + 1)}>
              <RefreshCw className="w-3.5 h-3.5" />
            </Button>
            <a href="https://data.niveshcopilot.com/grafana" target="_blank" rel="noreferrer">
              <Button size="sm" variant="outline">
                <ExternalLink className="w-3.5 h-3.5" /> Open
              </Button>
            </a>
          </div>
        </div>
        <div className="rounded-lg overflow-hidden border border-hairline" style={{ height: "600px" }}>
          <iframe
            key={key}
            src={GRAFANA_URL}
            className="w-full h-full"
            title="NIDP Grafana Dashboard"
            frameBorder="0"
          />
        </div>
      </CardContent>
    </Card>
  );
}
