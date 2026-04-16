import React, { useState } from "react";
import axios from "axios";
import { TrendingUp, Briefcase, Sprout, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { motion } from "framer-motion";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const OnboardingView = ({ onComplete }) => {
  const [selected, setSelected] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const options = [
    {
      id: "existing_investor",
      icon: Briefcase,
      title: "I have an existing portfolio",
      desc: "Upload your CAS statement, CSV, or Excel to get AI-powered analysis of your current investments.",
      color: "emerald",
    },
    {
      id: "new_investor",
      icon: Sprout,
      title: "I'm new to investing",
      desc: "Answer a few questions about your goals and risk tolerance. Get a personalized investment plan.",
      color: "blue",
    },
  ];

  const handleContinue = async () => {
    if (!selected) return;
    setSubmitting(true);
    try {
      await axios.post(`${API}/user/journey`, { journey_type: selected }, { withCredentials: true });
      onComplete(selected);
    } catch (err) {
      console.error("Failed to save journey", err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 flex items-center justify-center p-4" data-testid="onboarding-view">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="max-w-2xl w-full"
      >
        <div className="text-center mb-10">
          <div className="w-12 h-12 bg-emerald-600 rounded-2xl flex items-center justify-center mx-auto mb-6">
            <TrendingUp className="w-6 h-6 text-white" strokeWidth={2.5} />
          </div>
          <h1
            className="text-3xl sm:text-4xl font-medium tracking-tight text-slate-900 dark:text-white"
            style={{ fontFamily: "'Outfit', sans-serif" }}
            data-testid="onboarding-title"
          >
            Where are you in your
            <br />
            <span className="text-emerald-600">investment journey?</span>
          </h1>
          <p className="mt-4 text-base text-slate-500 dark:text-slate-400 max-w-md mx-auto">
            This helps us personalize your experience and give you the most relevant advice.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
          {options.map((opt, i) => (
            <motion.div
              key={opt.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.1 * i }}
            >
              <Card
                data-testid={`journey-option-${opt.id}`}
                onClick={() => setSelected(opt.id)}
                className={`cursor-pointer p-6 rounded-2xl border-2 transition-all duration-200 hover:-translate-y-1 hover:shadow-lg ${
                  selected === opt.id
                    ? opt.color === "emerald"
                      ? "border-emerald-500 bg-emerald-50/50 dark:bg-emerald-900/20 dark:border-emerald-600"
                      : "border-blue-500 bg-blue-50/50 dark:bg-blue-900/20 dark:border-blue-600"
                    : "border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-200 dark:hover:border-slate-700"
                }`}
              >
                <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-4 ${
                  selected === opt.id
                    ? opt.color === "emerald"
                      ? "bg-emerald-100 dark:bg-emerald-800"
                      : "bg-blue-100 dark:bg-blue-800"
                    : "bg-slate-100 dark:bg-slate-800"
                }`}>
                  <opt.icon className={`w-6 h-6 ${
                    selected === opt.id
                      ? opt.color === "emerald"
                        ? "text-emerald-600"
                        : "text-blue-600"
                      : "text-slate-500 dark:text-slate-400"
                  }`} strokeWidth={1.5} />
                </div>
                <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  {opt.title}
                </h3>
                <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
                  {opt.desc}
                </p>
              </Card>
            </motion.div>
          ))}
        </div>

        <div className="flex justify-center">
          <Button
            data-testid="onboarding-continue-button"
            onClick={handleContinue}
            disabled={!selected || submitting}
            className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl h-12 px-8 text-base disabled:opacity-40"
          >
            {submitting ? (
              <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : (
              <>
                Continue
                <ArrowRight className="w-5 h-5 ml-2" />
              </>
            )}
          </Button>
        </div>
      </motion.div>
    </div>
  );
};

export default OnboardingView;
