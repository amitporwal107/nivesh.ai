import React from "react";
import { Card } from "@/components/ui/card";
import { TrendingUp, DollarSign, PieChart } from "lucide-react";

const PlanSummary = ({ plan }) => {
  const formatAmount = (amount) => {
    return new Intl.NumberFormat('en-IN', { 
      style: 'currency', 
      currency: 'INR',
      maximumFractionDigits: 0 
    }).format(amount);
  };

  return (
    <Card className="p-5 sm:p-6 border-slate-200 mb-6">
      <h3 className="text-lg font-bold text-slate-900 mb-4 flex items-center gap-2">
        <PieChart className="w-5 h-5" />
        Plan Summary
      </h3>

      <div className="space-y-4">
        {/* Freed Capital */}
        {plan.freed_capital > 0 && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <DollarSign className="w-5 h-5 text-slate-600" />
              <span className="text-sm font-medium text-slate-700">Freed Capital (Post-Tax)</span>
            </div>
            <span className="text-lg font-bold text-emerald-600">
              {formatAmount(plan.post_tax_proceeds || plan.freed_capital)}
            </span>
          </div>
        )}

        {/* Tax Impact */}
        {plan.total_tax_impact && (
          <div className="p-4 bg-slate-50 rounded-lg">
            <p className="text-sm font-semibold text-slate-700 mb-2">Total Tax Impact</p>
            <div className="space-y-1 text-sm text-slate-600">
              {plan.total_tax_impact.total_ltcg !== undefined && (
                <div className="flex justify-between">
                  <span>LTCG:</span>
                  <span>{formatAmount(plan.total_tax_impact.total_ltcg)}</span>
                </div>
              )}
              {plan.total_tax_impact.total_stcg !== undefined && (
                <div className="flex justify-between">
                  <span>STCG:</span>
                  <span>{formatAmount(plan.total_tax_impact.total_stcg)}</span>
                </div>
              )}
              {plan.total_tax_impact.exemption_used !== undefined && (
                <div className="flex justify-between text-emerald-600">
                  <span>Exemption Used:</span>
                  <span>{formatAmount(plan.total_tax_impact.exemption_used)}</span>
                </div>
              )}
              {plan.total_tax_impact.total_tax !== undefined && (
                <div className="flex justify-between font-semibold text-slate-900 pt-2 border-t border-slate-200">
                  <span>Total Tax:</span>
                  <span>{formatAmount(plan.total_tax_impact.total_tax)}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Reinvestment Plan */}
        {plan.reinvestment_plan && (
          <div className="p-4 bg-blue-50 rounded-lg border border-blue-200">
            <p className="text-sm font-semibold text-slate-700 mb-2">Suggested Reinvestment</p>
            <div className="space-y-2">
              {plan.reinvestment_plan.allocations?.map((alloc, idx) => (
                <div key={idx} className="flex items-center justify-between text-sm">
                  <span className="text-slate-700 capitalize">{alloc.asset_class}</span>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-900">
                      {formatAmount(alloc.amount)}
                    </span>
                    <span className="text-xs text-slate-500">
                      ({alloc.percentage.toFixed(1)}%)
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Plan Metadata */}
        <div className="pt-4 border-t border-slate-200 text-xs text-slate-500">
          <div className="flex items-center justify-between">
            <span>Source:</span>
            <span className="capitalize">{plan.metadata?.source || 'Auto-generated'}</span>
          </div>
          {plan.metadata?.portfolio_value_at_creation && (
            <div className="flex items-center justify-between mt-1">
              <span>Portfolio Value at Creation:</span>
              <span>{formatAmount(plan.metadata.portfolio_value_at_creation)}</span>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
};

export default PlanSummary;
