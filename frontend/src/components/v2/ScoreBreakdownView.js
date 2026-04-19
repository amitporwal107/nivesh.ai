import React, { useState } from "react";
import { ChevronDown, ChevronUp, TrendingDown, TrendingUp, BarChart3, Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";

const ScoreBreakdownView = ({ action }) => {
  const [expanded, setExpanded] = useState(false);

  if (!action.score_breakdown) {
    return null;
  }

  const scores = action.score_breakdown;
  const fundamentals = action.fundamentals;
  const totalScore = action.exit_score || action.add_score;

  const getScoreColor = (score) => {
    if (score >= 7) return "text-red-600";
    if (score >= 5) return "text-amber-600";
    return "text-emerald-600";
  };

  const getScoreLabel = (score) => {
    if (score >= 7) return "Poor";
    if (score >= 5) return "Fair";
    if (score >= 3) return "Good";
    return "Excellent";
  };

  return (
    <Card className="p-4 border-slate-200 bg-slate-50">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-slate-600" />
          <h4 className="text-sm font-semibold text-slate-900">Score Breakdown</h4>
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

      {/* Collapsed View - Overall Score */}
      {!expanded && (
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-600">Overall {action.type} Score:</span>
          <div className="flex items-center gap-2">
            <span className={`text-lg font-bold ${getScoreColor(totalScore)}`}>
              {totalScore.toFixed(1)}/10
            </span>
            <Badge variant="outline" className={getScoreColor(totalScore)}>
              {getScoreLabel(totalScore)}
            </Badge>
          </div>
        </div>
      )}

      {/* Expanded View - Detailed Breakdown */}
      {expanded && (
        <div className="space-y-4">
          {/* Overall Score */}
          <div className="p-3 bg-white rounded-lg border border-slate-200">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-slate-700">Overall {action.type} Score</span>
              <span className={`text-2xl font-black ${getScoreColor(totalScore)}`}>
                {totalScore.toFixed(1)}/10
              </span>
            </div>
            <Progress value={totalScore * 10} className="h-2" />
            <p className="text-xs text-slate-600 mt-2">
              {getScoreLabel(totalScore)} - {action.confidence} confidence
            </p>
          </div>

          {/* Individual Components */}
          <div className="space-y-3">
            <h5 className="text-xs font-semibold text-slate-700 uppercase">Components</h5>
            
            {Object.entries(scores).map(([key, score]) => {
              const label = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
              const percentage = (score / 10) * 100;
              
              return (
                <div key={key} className="p-3 bg-white rounded-lg border border-slate-200">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-slate-700">{label}</span>
                    <span className={`text-lg font-bold ${getScoreColor(score)}`}>
                      {typeof score === 'number' ? score.toFixed(1) : score}
                    </span>
                  </div>
                  <Progress value={percentage} className="h-1.5" />
                  <p className="text-xs text-slate-600 mt-1">
                    {getComponentDescription(key, score)}
                  </p>
                </div>
              );
            })}
          </div>

          {/* Fundamentals (if available) */}
          {fundamentals && (
            <div className="p-4 bg-blue-50 rounded-lg border border-blue-200">
              <div className="flex items-center gap-2 mb-3">
                <Info className="w-4 h-4 text-blue-600" />
                <h5 className="text-sm font-semibold text-blue-900">Fundamental Data</h5>
                <Badge variant="outline" className="text-xs text-blue-700 border-blue-300">
                  Live from Groww
                </Badge>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {fundamentals.pe_ratio && (
                  <div>
                    <p className="text-xs text-blue-700">P/E Ratio</p>
                    <p className="text-sm font-semibold text-blue-900">{fundamentals.pe_ratio.toFixed(2)}</p>
                  </div>
                )}
                {fundamentals.roe && (
                  <div>
                    <p className="text-xs text-blue-700">ROE</p>
                    <p className="text-sm font-semibold text-blue-900">{fundamentals.roe.toFixed(2)}%</p>
                  </div>
                )}
                {fundamentals.debt_to_equity !== undefined && (
                  <div>
                    <p className="text-xs text-blue-700">Debt/Equity</p>
                    <p className="text-sm font-semibold text-blue-900">{fundamentals.debt_to_equity.toFixed(2)}</p>
                  </div>
                )}
                {fundamentals.market_cap && (
                  <div>
                    <p className="text-xs text-blue-700">Market Cap</p>
                    <p className="text-sm font-semibold text-blue-900">₹{(fundamentals.market_cap / 10000).toFixed(2)}T</p>
                  </div>
                )}
              </div>
              {fundamentals.cached_at && (
                <p className="text-xs text-blue-600 mt-3">
                  Updated: {new Date(fundamentals.cached_at).toLocaleString()}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
};

const getComponentDescription = (component, score) => {
  const descriptions = {
    quality: score >= 7 ? "Weak fundamentals" : score >= 5 ? "Average quality" : "Strong fundamentals",
    momentum: score >= 7 ? "Negative price trend" : score >= 5 ? "Sideways movement" : "Positive momentum",
    concentration: score >= 7 ? "High portfolio concentration" : score >= 5 ? "Moderate position" : "Well diversified",
    tax: score >= 7 ? "Significant tax impact" : score >= 5 ? "Moderate tax" : "Tax efficient",
    overlap: score >= 7 ? "High fund overlap" : score >= 5 ? "Some overlap" : "Low overlap",
    cost: score >= 7 ? "High expense ratio" : score >= 5 ? "Average cost" : "Low cost",
  };
  
  return descriptions[component] || `Score: ${score}/10`;
};

export default ScoreBreakdownView;
