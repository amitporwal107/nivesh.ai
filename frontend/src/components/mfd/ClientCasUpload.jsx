import React from "react";
import { Card } from "@/components/ui/card";
import { FileText, ShieldCheck } from "lucide-react";
import CasUploadButton from "@/components/CasUploadButton";

/**
 * ClientCasUpload — onboarding CTA rendered when an active CLIENT
 * profile has no portfolio yet. Wraps the provider-agnostic
 * `CasUploadButton`. Backend dispatches across the parser chain
 * (Nivesh → Claude Vision → casparser.in) silently.
 */
export default function ClientCasUpload({ clientName, onImported }) {
  return (
    <Card
      data-testid="client-cas-upload"
      className="p-6 border-2 border-dashed border-indigo-300 bg-gradient-to-br from-indigo-50/60 to-white dark:from-indigo-900/10 dark:to-slate-900"
    >
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-xl bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center flex-shrink-0">
          <FileText className="w-5 h-5 text-indigo-700 dark:text-indigo-300" />
        </div>
        <div>
          <h3 className="text-lg font-bold text-slate-800 dark:text-slate-100">
            Onboard {clientName}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Upload {clientName}&apos;s CAS PDF — we&apos;ll extract every holding,
            transaction and SIP automatically. Holdings are stored against
            {" "}{clientName}&apos;s profile only — your own portfolio is
            unaffected.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <CasUploadButton
          onSuccess={onImported}
          label={`Upload ${clientName}'s CAS PDF`}
          testId="client-cas-upload-btn"
          className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl"
        />
        <span className="text-[11px] text-slate-500 flex items-center gap-1">
          <ShieldCheck className="w-3 h-3 text-emerald-600" />
          Read-only · No transactions · Data encrypted
        </span>
      </div>
    </Card>
  );
}
