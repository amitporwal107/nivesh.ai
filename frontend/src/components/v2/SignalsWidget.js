import React, { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const SignalsWidget = ({ signals }) => {
  const [expanded, setExpanded] = useState(false);

  if (!signals || signals.length === 0) return null;

  const getSeverityColor = (severity) => {
    if (severity === "HIGH") return "bg-red-100 text-red-800 border-red-300";
    if (severity === "MEDIUM") return "bg-amber-100 text-amber-800 border-amber-300";
    return "bg-blue-100 text-blue-800 border-blue-300";
  };

  const getSeverityIcon = (severity) => {
    if (severity === "HIGH") return "🔴";
    if (severity === "MEDIUM") return "🟡";
    return "🔵";
  };

  return (
    <Card className="p-5 sm:p-6 border-slate-200 mb-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-slate-600" />
          <h3 className="text-lg font-bold text-slate-900">Portfolio Signals</h3>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? (
            <ChevronUp className="w-4 h-4" />
          ) : (
            <ChevronDown className="w-4 h-4" />
          )}
        </Button>
      </div>

      {/* Collapsed View */}
      {!expanded && (
        <div className="space-y-2">
          <p className="text-sm text-slate-600 mb-3">
            {signals.length} signal{signals.length !== 1 ? 's' : ''} detected:
          </p>
          {signals.slice(0, 3).map((signal) => (
            <div key={signal.signal_id} className="flex items-start gap-2">
              <span className="text-lg mt-0.5">{getSeverityIcon(signal.severity)}</span>
              <div className="flex-1">
                <p className="text-sm font-medium text-slate-900">{signal.title}</p>
                <p className="text-xs text-slate-600">{signal.impact}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Expanded View */}
      {expanded && (
        <div className="space-y-4">
          {signals.map((signal) => (
            <div
              key={signal.signal_id}
              className={`p-4 rounded-lg border-2 ${getSeverityColor(signal.severity)}`}
            >
              <div className="flex items-start gap-3 mb-3">
                <span className="text-2xl">{getSeverityIcon(signal.severity)}</span>
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant="outline" className="text-xs">
                      {signal.severity}
                    </Badge>
                  </div>
                  <h4 className="text-base font-bold text-slate-900 mb-1">
                    {signal.title}
                  </h4>
                  <p className="text-sm text-slate-600 mb-2">
                    {signal.description}
                  </p>
                </div>
              </div>

              {/* Impact */}
              <div className="mb-3">
                <p className="text-sm font-semibold text-slate-700 mb-1">Impact:</p>
                <p className="text-sm text-slate-600">{signal.impact}</p>
              </div>

              {/* Affected Assets */}
              {signal.affected_assets && signal.affected_assets.length > 0 && (
                <div>
                  <p className="text-sm font-semibold text-slate-700 mb-1">Affected Assets:</p>
                  <ul className="text-sm text-slate-600 space-y-1">
                    {signal.affected_assets.slice(0, 3).map((asset, idx) => (
                      <li key={idx} className="flex items-start gap-2">
                        <span className="text-slate-400">•</span>
                        <span className="break-words">{asset}</span>
                      </li>
                    ))}
                    {signal.affected_assets.length > 3 && (
                      <li className="text-xs text-slate-500">
                        +{signal.affected_assets.length - 3} more
                      </li>
                    )}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
};

export default SignalsWidget;
