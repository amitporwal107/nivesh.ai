import { Construction } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

export function NotAvailablePanel({ name, reason }: { name: string; reason?: string }) {
  return (
    <Card>
      <CardContent className="p-10 flex flex-col items-center gap-3 text-center">
        <Construction className="w-8 h-8 text-ink-3" />
        <div>
          <div className="text-sm font-medium text-ink">{name} — not available</div>
          <div className="text-xs text-ink-3 mt-1">
            {reason ?? "This endpoint is not implemented in the current backend version."}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
