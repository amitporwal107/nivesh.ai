import React, { useState } from "react";
import { CheckCircle2, XCircle, TrendingDown, TrendingUp, AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

const ActionCard = ({ action, priority, onComplete, onSkip }) => {
  const [showDetails, setShowDetails] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [completionNote, setCompletionNote] = useState("");

  const getActionColor = () => {
    if (action.status === "COMPLETED") return "bg-emerald-50 border-emerald-200";
    if (action.status === "SKIPPED") return "bg-slate-50 border-slate-200";
    if (action.type === "EXIT") return "bg-red-50 border-red-200";
    if (action.type === "ADD") return "bg-emerald-50 border-emerald-200";
    return "bg-amber-50 border-amber-200";
  };

  const getActionIcon = () => {
    if (action.status === "COMPLETED") return <CheckCircle2 className="w-6 h-6 text-emerald-600" />;
    if (action.status === "SKIPPED") return <XCircle className="w-6 h-6 text-slate-400" />;
    if (action.type === "EXIT") return <TrendingDown className="w-6 h-6 text-red-600" />;
    if (action.type === "ADD") return <TrendingUp className="w-6 h-6 text-emerald-600" />;
    return <AlertTriangle className="w-6 h-6 text-amber-600" />;
  };

  const getActionBadge = () => {
    if (action.type === "EXIT") return <Badge className="bg-red-600 text-white">EXIT</Badge>;
    if (action.type === "ADD") return <Badge className="bg-emerald-600 text-white">ADD</Badge>;
    return <Badge className="bg-amber-500 text-slate-900">SWITCH</Badge>;
  };

  const handleComplete = () => {
    onComplete(completionNote.trim() || null);
    setDialogOpen(false);
    setCompletionNote("");
  };

  const formatAmount = (amount) => {
    return new Intl.NumberFormat('en-IN', { 
      style: 'currency', 
      currency: 'INR',
      maximumFractionDigits: 0 
    }).format(amount);
  };

  const isPending = action.status === "PENDING";

  return (
    <Card className={`p-5 sm:p-6 border-2 ${getActionColor()}`}>
      {/* Header */}
      <div className="flex items-start gap-3 mb-4">
        <div className="mt-1">{getActionIcon()}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            {getActionBadge()}
            <Badge variant="outline" className="text-xs">
              Priority {priority}
            </Badge>
          </div>
          <h3 className="text-xl font-bold text-slate-900 tracking-tight">
            {action.type} {action.asset_type === "equity" ? "Stock" : "Fund"}
          </h3>
          <p className="text-sm text-slate-600 mt-1 break-words">
            {action.asset_name}
          </p>
        </div>
      </div>

      {/* Amount */}
      <div className="mb-4">
        <p className="text-5xl font-black tracking-tighter text-slate-900">
          {formatAmount(action.amount)}
        </p>
        {action.confidence && (
          <p className="text-sm text-slate-600 mt-1">
            Confidence: <span className="font-semibold">{action.confidence}</span>
          </p>
        )}
      </div>

      {/* Reason */}
      <div className="mb-4">
        <p className="text-sm font-semibold text-slate-700 mb-1">Why {action.type}?</p>
        <p className="text-sm text-slate-600">{action.reason_text}</p>
      </div>

      {/* Tax Impact (for EXIT actions) */}
      {action.tax_impact && showDetails && (
        <div className="mb-4 p-4 bg-white rounded-lg border border-slate-200">
          <p className="text-sm font-semibold text-slate-700 mb-2">Tax Impact</p>
          <div className="space-y-1 text-sm text-slate-600">
            {action.tax_impact.holding_period_years && (
              <p>Holding period: {action.tax_impact.holding_period_years} years</p>
            )}
            {action.tax_impact.capital_gain !== undefined && (
              <p>Capital gain: {formatAmount(action.tax_impact.capital_gain)}</p>
            )}
            {action.tax_impact.tax_liability !== undefined && (
              <p className="font-semibold">
                Tax liability: {formatAmount(action.tax_impact.tax_liability)}
              </p>
            )}
            {action.tax_impact.post_tax_proceeds && (
              <p>Post-tax proceeds: {formatAmount(action.tax_impact.post_tax_proceeds)}</p>
            )}
          </div>
        </div>
      )}

      {/* Status Display */}
      {action.status === "COMPLETED" && (
        <div className="mb-4 p-3 bg-emerald-100 rounded-lg">
          <div className="flex items-center gap-2 mb-1">
            <CheckCircle2 className="w-4 h-4 text-emerald-700" />
            <p className="text-sm font-semibold text-emerald-700">Completed</p>
          </div>
          {action.completed_at && (
            <p className="text-xs text-emerald-600">
              {new Date(action.completed_at).toLocaleDateString()}
            </p>
          )}
          {action.completion_note && (
            <p className="text-sm text-emerald-700 mt-1">
              Note: {action.completion_note}
            </p>
          )}
        </div>
      )}

      {action.status === "SKIPPED" && (
        <div className="mb-4 p-3 bg-slate-100 rounded-lg">
          <div className="flex items-center gap-2">
            <XCircle className="w-4 h-4 text-slate-500" />
            <p className="text-sm font-semibold text-slate-600">Skipped</p>
          </div>
        </div>
      )}

      {/* Actions */}
      {isPending && (
        <div className="flex flex-col gap-3">
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button
                className="w-full min-h-[56px] text-lg bg-slate-900 hover:bg-slate-800"
              >
                <CheckCircle2 className="w-5 h-5 mr-2" />
                Mark as Done
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Mark Action as Completed</DialogTitle>
              </DialogHeader>
              <div className="py-4">
                <p className="text-sm text-slate-600 mb-3">
                  Add an optional note about how you completed this action:
                </p>
                <Textarea
                  placeholder="e.g., Sold via Zerodha app"
                  value={completionNote}
                  onChange={(e) => setCompletionNote(e.target.value)}
                  rows={3}
                />
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDialogOpen(false)}>
                  Cancel
                </Button>
                <Button onClick={handleComplete}>
                  Complete Action
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={onSkip}
              className="flex-1 min-h-[48px]"
            >
              Skip This Action
            </Button>
            <Button
              variant="ghost"
              onClick={() => setShowDetails(!showDetails)}
              className="min-h-[48px] px-4"
            >
              {showDetails ? (
                <ChevronUp className="w-5 h-5" />
              ) : (
                <ChevronDown className="w-5 h-5" />
              )}
            </Button>
          </div>
        </div>
      )}

      {!isPending && (
        <Button
          variant="ghost"
          onClick={() => setShowDetails(!showDetails)}
          className="w-full"
        >
          {showDetails ? "Hide Details" : "View Details"}
          {showDetails ? (
            <ChevronUp className="w-4 h-4 ml-2" />
          ) : (
            <ChevronDown className="w-4 h-4 ml-2" />
          )}
        </Button>
      )}
    </Card>
  );
};

export default ActionCard;
