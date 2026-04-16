import React, { useState, useEffect } from "react";
import axios from "axios";
import { Shield, ArrowRight, ArrowLeft, CheckCircle2, TrendingDown, Clock, AlertTriangle, Landmark, BookOpen, Target } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { motion, AnimatePresence } from "framer-motion";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const QUESTIONS = [
  {
    id: "market_drop",
    icon: TrendingDown,
    question: "If the market drops 20% tomorrow, what would you do?",
    subtitle: "This helps us understand your reaction to volatility",
    options: [
      { value: "buy_more", label: "Buy more at lower prices", desc: "See it as an opportunity" },
      { value: "hold", label: "Hold and wait it out", desc: "Stay the course patiently" },
      { value: "sell_some", label: "Sell some to limit losses", desc: "Reduce exposure partially" },
      { value: "sell_all", label: "Sell everything immediately", desc: "Protect capital at all costs" },
    ],
  },
  {
    id: "investment_horizon",
    icon: Clock,
    question: "What is your investment time horizon?",
    subtitle: "How long can you keep your money invested?",
    options: [
      { value: "10yr_plus", label: "10+ years", desc: "Long-term wealth building" },
      { value: "5_10yr", label: "5-10 years", desc: "Medium to long term goals" },
      { value: "3_5yr", label: "3-5 years", desc: "Medium term planning" },
      { value: "1_3yr", label: "1-3 years", desc: "Short to medium term" },
      { value: "less_1yr", label: "Less than 1 year", desc: "Need money soon" },
    ],
  },
  {
    id: "loss_tolerance",
    icon: AlertTriangle,
    question: "What is the maximum loss you can tolerate in a year?",
    subtitle: "Be honest - this determines your allocation",
    options: [
      { value: "up_to_50", label: "Up to 50%", desc: "High risk for high reward" },
      { value: "up_to_25", label: "Up to 25%", desc: "Moderate comfort with losses" },
      { value: "up_to_10", label: "Up to 10%", desc: "Prefer limited downside" },
      { value: "none", label: "I can't tolerate any loss", desc: "Capital preservation is priority" },
    ],
  },
  {
    id: "income_stability",
    icon: Landmark,
    question: "How stable is your primary income source?",
    subtitle: "This affects how much risk you can afford",
    options: [
      { value: "very_stable", label: "Very stable", desc: "Government job, established business" },
      { value: "stable", label: "Stable", desc: "Salaried in a good company" },
      { value: "moderate", label: "Moderately stable", desc: "Freelance / variable income" },
      { value: "unstable", label: "Unstable", desc: "Irregular or uncertain income" },
    ],
  },
  {
    id: "investment_knowledge",
    icon: BookOpen,
    question: "How would you rate your investment knowledge?",
    subtitle: "No wrong answers - be honest with yourself",
    options: [
      { value: "expert", label: "Expert", desc: "Active trader, deep market knowledge" },
      { value: "advanced", label: "Advanced", desc: "Understand markets, track regularly" },
      { value: "intermediate", label: "Intermediate", desc: "Know basics of MFs, stocks" },
      { value: "beginner", label: "Beginner", desc: "Just starting out" },
    ],
  },
  {
    id: "goal_priority",
    icon: Target,
    question: "What's your primary investment goal?",
    subtitle: "This shapes your recommended portfolio strategy",
    options: [
      { value: "aggressive_growth", label: "Aggressive Growth", desc: "Maximize returns, accept high volatility" },
      { value: "growth", label: "Steady Growth", desc: "Good returns with manageable risk" },
      { value: "income", label: "Regular Income", desc: "Generate dividends/interest" },
      { value: "safety", label: "Capital Safety", desc: "Protect what I have" },
    ],
  },
];

const categoryColors = {
  "Aggressive": { bg: "bg-red-50 dark:bg-red-900/20", text: "text-red-600 dark:text-red-400", bar: "bg-red-500" },
  "Moderately Aggressive": { bg: "bg-orange-50 dark:bg-orange-900/20", text: "text-orange-600 dark:text-orange-400", bar: "bg-orange-500" },
  "Moderate": { bg: "bg-amber-50 dark:bg-amber-900/20", text: "text-amber-600 dark:text-amber-400", bar: "bg-amber-500" },
  "Moderately Conservative": { bg: "bg-blue-50 dark:bg-blue-900/20", text: "text-blue-600 dark:text-blue-400", bar: "bg-blue-500" },
  "Conservative": { bg: "bg-emerald-50 dark:bg-emerald-900/20", text: "text-emerald-600 dark:text-emerald-400", bar: "bg-emerald-500" },
};

const allocationMap = {
  "Aggressive": { equity: 80, debt: 10, gold: 5, cash: 5 },
  "Moderately Aggressive": { equity: 65, debt: 20, gold: 10, cash: 5 },
  "Moderate": { equity: 50, debt: 30, gold: 10, cash: 10 },
  "Moderately Conservative": { equity: 30, debt: 45, gold: 15, cash: 10 },
  "Conservative": { equity: 15, debt: 55, gold: 15, cash: 15 },
};

const RiskProfileView = ({ onComplete, existingProfile }) => {
  const [currentStep, setCurrentStep] = useState(0);
  const [answers, setAnswers] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(existingProfile || null);

  const handleAnswer = (questionId, value) => {
    setAnswers((prev) => ({ ...prev, [questionId]: value }));
  };

  const handleNext = () => {
    if (currentStep < QUESTIONS.length - 1) {
      setCurrentStep((prev) => prev + 1);
    }
  };

  const handleBack = () => {
    if (currentStep > 0) {
      setCurrentStep((prev) => prev - 1);
    }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const payload = {
        answers: Object.entries(answers).map(([question_id, answer]) => ({ question_id, answer })),
      };
      const res = await axios.post(`${API}/user/risk-profile`, payload, { withCredentials: true });
      setResult(res.data.risk_profile);
    } catch (err) {
      console.error("Failed to save risk profile", err);
    } finally {
      setSubmitting(false);
    }
  };

  const currentQ = QUESTIONS[currentStep];
  const isLastStep = currentStep === QUESTIONS.length - 1;
  const canProceed = answers[currentQ?.id];
  const allAnswered = QUESTIONS.every((q) => answers[q.id]);

  // Show results
  if (result) {
    const colors = categoryColors[result.category] || categoryColors["Moderate"];
    const allocation = allocationMap[result.category] || allocationMap["Moderate"];
    return (
      <div className="max-w-2xl mx-auto" data-testid="risk-profile-result">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
          <div className="text-center mb-8">
            <div className={`w-16 h-16 ${colors.bg} rounded-2xl flex items-center justify-center mx-auto mb-4`}>
              <Shield className={`w-8 h-8 ${colors.text}`} strokeWidth={1.5} />
            </div>
            <h2 className="text-2xl font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
              Your Risk Profile
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">Based on your responses</p>
          </div>

          <Card className="p-6 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 mb-6">
            <div className="text-center mb-6">
              <span className={`text-3xl font-semibold ${colors.text}`} style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="risk-category">
                {result.category}
              </span>
              <div className="mt-3 w-full bg-slate-100 dark:bg-slate-800 rounded-full h-3 overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${100 - result.score}%` }}
                  transition={{ duration: 0.8, delay: 0.3 }}
                  className={`h-full rounded-full ${colors.bar}`}
                />
              </div>
              <div className="flex justify-between text-xs text-slate-400 mt-1">
                <span>Aggressive</span>
                <span>Conservative</span>
              </div>
            </div>

            <div className="border-t border-slate-100 dark:border-slate-800 pt-6">
              <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-4">Suggested Asset Allocation</h3>
              <div className="grid grid-cols-4 gap-3">
                {Object.entries(allocation).map(([asset, pct]) => (
                  <div key={asset} className="text-center">
                    <div className="text-2xl font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                      {pct}%
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400 capitalize mt-1">{asset}</div>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          <div className="flex justify-center gap-3">
            <Button
              data-testid="retake-risk-profile"
              variant="outline"
              onClick={() => { setResult(null); setCurrentStep(0); setAnswers({}); }}
              className="rounded-xl"
            >
              Retake Assessment
            </Button>
            {onComplete && (
              <Button
                data-testid="risk-profile-continue"
                onClick={() => onComplete(result)}
                className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl"
              >
                Continue to Dashboard
                <ArrowRight className="w-4 h-4 ml-2" />
              </Button>
            )}
          </div>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto" data-testid="risk-profile-questionnaire">
      {/* Progress */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-slate-500 dark:text-slate-400">
            Question {currentStep + 1} of {QUESTIONS.length}
          </span>
          <span className="text-sm font-medium text-emerald-600">
            {Math.round(((currentStep + (canProceed ? 1 : 0)) / QUESTIONS.length) * 100)}%
          </span>
        </div>
        <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-2 overflow-hidden">
          <motion.div
            className="h-full rounded-full bg-emerald-500"
            animate={{ width: `${((currentStep + (canProceed ? 1 : 0)) / QUESTIONS.length) * 100}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>
      </div>

      {/* Question */}
      <AnimatePresence mode="wait">
        <motion.div
          key={currentStep}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -20 }}
          transition={{ duration: 0.25 }}
        >
          <div className="text-center mb-8">
            <div className="w-12 h-12 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl flex items-center justify-center mx-auto mb-4">
              <currentQ.icon className="w-6 h-6 text-emerald-600" strokeWidth={1.5} />
            </div>
            <h2
              className="text-xl sm:text-2xl font-medium text-slate-900 dark:text-white mb-2"
              style={{ fontFamily: "'Outfit', sans-serif" }}
              data-testid="risk-question-title"
            >
              {currentQ.question}
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">{currentQ.subtitle}</p>
          </div>

          <div className="space-y-3 mb-8">
            {currentQ.options.map((opt) => (
              <Card
                key={opt.value}
                data-testid={`risk-option-${opt.value}`}
                onClick={() => handleAnswer(currentQ.id, opt.value)}
                className={`cursor-pointer p-4 rounded-xl border-2 transition-all duration-200 ${
                  answers[currentQ.id] === opt.value
                    ? "border-emerald-500 bg-emerald-50/50 dark:bg-emerald-900/20 dark:border-emerald-600"
                    : "border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-200 dark:hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                    answers[currentQ.id] === opt.value
                      ? "border-emerald-500 bg-emerald-500"
                      : "border-slate-300 dark:border-slate-600"
                  }`}>
                    {answers[currentQ.id] === opt.value && (
                      <CheckCircle2 className="w-4 h-4 text-white" />
                    )}
                  </div>
                  <div>
                    <div className="font-medium text-slate-900 dark:text-white text-sm">{opt.label}</div>
                    <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{opt.desc}</div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </motion.div>
      </AnimatePresence>

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <Button
          data-testid="risk-back-button"
          variant="outline"
          onClick={handleBack}
          disabled={currentStep === 0}
          className="rounded-xl"
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back
        </Button>

        {isLastStep && allAnswered ? (
          <Button
            data-testid="risk-submit-button"
            onClick={handleSubmit}
            disabled={submitting}
            className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl"
          >
            {submitting ? (
              <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : (
              <>
                See My Risk Profile
                <CheckCircle2 className="w-4 h-4 ml-2" />
              </>
            )}
          </Button>
        ) : (
          <Button
            data-testid="risk-next-button"
            onClick={handleNext}
            disabled={!canProceed}
            className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl disabled:opacity-40"
          >
            Next
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        )}
      </div>
    </div>
  );
};

export default RiskProfileView;
