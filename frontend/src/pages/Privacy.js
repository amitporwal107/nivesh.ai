import React from "react";
import { Link } from "react-router-dom";
import { TrendingUp, ArrowLeft, ShieldCheck, Lock, Eye, Database, UserCheck, Mail } from "lucide-react";

/**
 * Privacy Statement — concise, India/SEBI-aware, plain English.
 * Linked from the landing page footer. No auth required.
 */
const Privacy = () => {
  const lastUpdated = "April 2026";

  const sections = [
    {
      icon: Eye,
      title: "1. What we collect",
      body: [
        "Your Google account profile (name, email, avatar) used only to sign you in.",
        "Your portfolio data — either (a) the contents of the CAS PDF you upload, (b) the holdings returned by CDSL OTP / Gmail CAS import via CAS Parser, or (c) data you enter manually.",
        "Usage data: pages viewed, features used, anonymised error reports — to improve the product.",
      ],
    },
    {
      icon: Lock,
      title: "2. What we never do",
      body: [
        "We never place trades on your behalf. All integrations are strictly read-only.",
        "We never sell, rent, or share your personal or portfolio data with third parties for marketing.",
        "We never store your CAS password — it is used only to open the PDF in memory and is discarded immediately.",
      ],
    },
    {
      icon: Database,
      title: "3. How we store it",
      body: [
        "Portfolio data is stored encrypted in managed MongoDB and PostgreSQL clusters hosted in Indian data centres where available.",
        "Access is limited to authenticated sessions bound to your Google account.",
        "Backups are encrypted at rest and rotated on a regular schedule.",
      ],
    },
    {
      icon: UserCheck,
      title: "4. Your rights",
      body: [
        "You can delete all your data at any time from the dashboard — the deletion is immediate and irreversible.",
        "You can export your holdings as CSV from the Portfolio page.",
        "You can revoke Gmail / CAS Connect access from your Google Account’s security settings.",
      ],
    },
    {
      icon: ShieldCheck,
      title: "5. Security & compliance",
      body: [
        "All traffic is TLS 1.2+ encrypted end-to-end.",
        "AI-generated insights are intended for educational purposes only and are not personalised investment advice under SEBI (Investment Advisers) Regulations, 2013.",
        "For personalised advice, please consult a SEBI-registered investment adviser.",
      ],
    },
    {
      icon: Mail,
      title: "6. Contact",
      body: [
        "Questions, takedown requests, or data-deletion queries: privacy@nivesh.ai",
        "We aim to respond within 72 hours.",
      ],
    },
  ];

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950" data-testid="privacy-page">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-white/80 dark:bg-slate-950/80 backdrop-blur-xl border-b border-slate-100 dark:border-slate-800">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2" data-testid="privacy-home-link">
            <div className="w-8 h-8 bg-emerald-600 rounded-xl flex items-center justify-center">
              <TrendingUp className="w-4 h-4 text-white" strokeWidth={2.5} />
            </div>
            <span className="text-lg font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
              nivesh.ai
            </span>
          </Link>
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-emerald-600 transition-colors"
            data-testid="privacy-back-link"
          >
            <ArrowLeft className="w-4 h-4" /> Back to home
          </Link>
        </div>
      </nav>

      {/* Content */}
      <main className="pt-28 pb-20 px-4 sm:px-6 lg:px-8 max-w-3xl mx-auto">
        <p className="text-xs font-bold tracking-[0.15em] uppercase text-emerald-600 mb-4" data-testid="privacy-eyebrow">
          Privacy statement
        </p>
        <h1
          className="text-4xl sm:text-5xl font-medium tracking-tight text-slate-900 dark:text-white leading-tight"
          style={{ fontFamily: "'Outfit', sans-serif" }}
          data-testid="privacy-heading"
        >
          Your data stays safe. <span className="text-emerald-600">Always.</span>
        </h1>
        <p className="mt-4 text-base text-slate-500 dark:text-slate-400 leading-relaxed">
          This page explains what we collect, why we collect it, and the controls you have. It is written in plain English — no legal wall of text.
        </p>
        <p className="mt-2 text-xs text-slate-400 dark:text-slate-500" data-testid="privacy-last-updated">
          Last updated: {lastUpdated}
        </p>

        <div className="mt-10 space-y-6">
          {sections.map((s, i) => (
            <section
              key={s.title}
              data-testid={`privacy-section-${i}`}
              className="rounded-2xl border border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 sm:p-7"
            >
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center">
                  <s.icon className="w-5 h-5 text-emerald-600" strokeWidth={1.75} />
                </div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  {s.title}
                </h2>
              </div>
              <ul className="space-y-2.5 pl-1">
                {s.body.map((line, j) => (
                  <li key={j} className="flex gap-2.5 text-sm text-slate-600 dark:text-slate-300 leading-relaxed">
                    <span className="text-emerald-500 mt-1 flex-shrink-0">•</span>
                    <span>{line}</span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>

        <div className="mt-10 text-center text-xs text-slate-400 dark:text-slate-500">
          Investment in securities market are subject to market risks. AI-generated guidance for educational purposes only.
        </div>
      </main>
    </div>
  );
};

export default Privacy;
