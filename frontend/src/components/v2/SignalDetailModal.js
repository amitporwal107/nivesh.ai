import React, { useState } from "react";
import { X, AlertTriangle, TrendingUp, ArrowRight, Info } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

const SignalDetailModal = ({ signal, open, onClose }) => {
  if (!signal || !signal.details) {
    return null;
  }

  const details = signal.details;
  const formatAmount = (amount) => {
    return new Intl.NumberFormat('en-IN', { 
      style: 'currency', 
      currency: 'INR',
      maximumFractionDigits: 0 
    }).format(amount);
  };

  const getSeverityColor = () => {
    if (signal.severity === "HIGH") return "bg-red-100 text-red-800 border-red-300";
    if (signal.severity === "MEDIUM") return "bg-amber-100 text-amber-800 border-amber-300";
    return "bg-blue-100 text-blue-800 border-blue-300";
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-6 h-6 text-red-600 mt-1" />
            <div className="flex-1">
              <DialogTitle className="text-2xl font-bold text-slate-900">
                {signal.title}
              </DialogTitle>
              <div className="flex items-center gap-2 mt-2">
                <Badge className={getSeverityColor()}>
                  {signal.severity} SEVERITY
                </Badge>
              </div>
            </div>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-slate-600"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </DialogHeader>

        <div className="py-6 space-y-6">
          {/* Description */}
          <div>
            <h3 className="text-sm font-semibold text-slate-700 mb-2">What's happening?</h3>
            <p className="text-base text-slate-900">{signal.description}</p>
            <p className="text-sm text-red-600 mt-2 font-medium">
              Impact: {signal.impact}
            </p>
          </div>

          {/* Overlap Details */}
          {details.top_overlap_pairs && (
            <Card className="p-5 bg-red-50 border-red-200">
              <h3 className="text-sm font-semibold text-slate-900 mb-4 flex items-center gap-2">
                <Info className="w-4 h-4 text-red-600" />
                Overlapping Fund Pairs
              </h3>
              <div className="space-y-4">
                {details.top_overlap_pairs.map((pair, idx) => (
                  <div key={idx} className="p-4 bg-white rounded-lg border border-red-200">
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex-1">
                        <p className="text-sm font-semibold text-slate-900">{pair.fund_a}</p>
                        <div className="flex items-center gap-2 my-2">
                          <div className="h-px flex-1 bg-slate-300"></div>
                          <Badge variant="outline" className="text-red-700 border-red-300">
                            {pair.overlap_pct.toFixed(1)}% overlap
                          </Badge>
                          <div className="h-px flex-1 bg-slate-300"></div>
                        </div>
                        <p className="text-sm font-semibold text-slate-900">{pair.fund_b}</p>
                      </div>
                    </div>
                    {pair.shared_stocks > 0 && (
                      <p className="text-xs text-slate-600">
                        Sharing {pair.shared_stocks} common stocks
                      </p>
                    )}
                    {pair.recommendation && (
                      <p className="text-xs text-red-700 mt-2 font-medium">
                        💡 {pair.recommendation}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Rebalancing Strategy */}
          {details.rebalancing_strategy && (
            <Card className="p-5 bg-emerald-50 border-emerald-200">
              <h3 className="text-sm font-semibold text-emerald-900 mb-4 flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-emerald-600" />
                Recommended Rebalancing Strategy
              </h3>
              <div className="space-y-3">
                {details.rebalancing_strategy.exit_amount > 0 && (
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-slate-700">Exit from overlapping funds:</span>
                    <span className="text-sm font-bold text-slate-900">
                      {formatAmount(details.rebalancing_strategy.exit_amount)}
                    </span>
                  </div>
                )}
                {details.rebalancing_strategy.debt_allocation > 0 && (
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-slate-700">Reallocate to Debt Funds:</span>
                    <span className="text-sm font-bold text-emerald-700">
                      {formatAmount(details.rebalancing_strategy.debt_allocation)}
                    </span>
                  </div>
                )}
                {details.rebalancing_strategy.gold_allocation > 0 && (
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-slate-700">Reallocate to Gold ETF:</span>
                    <span className="text-sm font-bold text-emerald-700">
                      {formatAmount(details.rebalancing_strategy.gold_allocation)}
                    </span>
                  </div>
                )}
                {details.rebalancing_strategy.equity_reallocation > 0 && (
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-slate-700">Diversify to low-overlap equity:</span>
                    <span className="text-sm font-bold text-emerald-700">
                      {formatAmount(details.rebalancing_strategy.equity_reallocation)}
                    </span>
                  </div>
                )}
              </div>
            </Card>
          )}

          {/* Portfolio Health Improvement */}
          {details.portfolio_improvement && (
            <Card className="p-5 bg-blue-50 border-blue-200">
              <h3 className="text-sm font-semibold text-blue-900 mb-4">Expected Portfolio Health Improvement</h3>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-700">Current Max Overlap:</span>
                  <Badge variant="outline" className="text-red-700 border-red-300">
                    {details.portfolio_improvement.current_overlap}
                  </Badge>
                </div>
                <div className="flex items-center justify-center py-2">
                  <ArrowRight className="w-5 h-5 text-blue-600" />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-700">Projected Max Overlap:</span>
                  <Badge variant="outline" className="text-emerald-700 border-emerald-300">
                    {details.portfolio_improvement.projected_overlap}
                  </Badge>
                </div>
                <div className="mt-4 p-3 bg-white rounded-lg">
                  <p className="text-sm text-slate-700 mb-2">
                    ✅ {details.portfolio_improvement.diversification_gain}
                  </p>
                  <p className="text-sm text-slate-700">
                    ✅ {details.portfolio_improvement.risk_reduction}
                  </p>
                </div>
              </div>
            </Card>
          )}
        </div>

        <div className="flex justify-end">
          <Button onClick={onClose} className="min-h-[48px] px-8">
            Got It
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default SignalDetailModal;
