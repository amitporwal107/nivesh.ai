import React, { useState, useEffect } from "react";
import axios from "axios";
import { Card } from "@/components/ui/card";
import { FileText, ShieldCheck, Sparkles } from "lucide-react";
import CasConnectButton from "@/components/CasConnectButton";
import ClaudeCasUploadButton from "@/components/ClaudeCasUploadButton";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * ClientCasUpload — onboarding CTA rendered when an active CLIENT profile
 * has no portfolio yet. Honours the admin-toggled CAS parser provider —
 *   - casparser_api → CasConnectButton (hosted SDK widget)
 *   - claude_vision / nivesh_cas_parser → ClaudeCasUploadButton (raw
 *     PDF upload to /portfolio/upload-raw, dispatched server-side).
 */
export default function ClientCasUpload({ clientName, onImported }) {
  const [casProvider, setCasProvider] = useState("casparser_api");
  useEffect(() => {
    axios.get(`${API}/cas-parser-provider/active`, { withCredentials: true })
      .then((r) => setCasProvider(r.data?.provider || "casparser_api"))
      .catch(() => { /* keep default */ });
  }, []);

  const isClaude = casProvider === "claude_vision";
  const isNivesh = casProvider === "nivesh_cas_parser";
  const isApi = casProvider === "casparser_api";

  return (
    <Card
      data-testid="client-cas-upload"
      className="p-6 border-2 border-dashed border-indigo-300 bg-gradient-to-br from-indigo-50/60 to-white dark:from-indigo-900/10 dark:to-slate-900"
    >
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-xl bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center flex-shrink-0">
          {isApi
            ? <FileText className="w-5 h-5 text-indigo-700 dark:text-indigo-300" />
            : <Sparkles className="w-5 h-5 text-indigo-700 dark:text-indigo-300" />}
        </div>
        <div>
          <h3 className="text-lg font-bold text-slate-800 dark:text-slate-100">
            Onboard {clientName}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            {isClaude
              ? <>Upload {clientName}&apos;s CAS PDF — <strong>Claude Vision</strong> extracts holdings, transactions, and SIPs in ~60s.</>
              : isNivesh
                ? <>Upload {clientName}&apos;s CAS PDF — <strong>Nivesh Parser</strong> (Google Document AI) extracts holdings, transactions, and SIPs in ~15s; works on scanned PDFs.</>
                : <>Upload {clientName}&apos;s CAS (PDF, Gmail inbox, or live CDSL OTP fetch). The holdings are stored against {clientName}&apos;s profile only — your own portfolio is unaffected.</>}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {isApi ? (
          <CasConnectButton
            onSuccess={onImported}
            label={`Launch CAS Connect for ${clientName}`}
            testId="client-cas-connect-btn"
            className="bg-indigo-600 hover:bg-indigo-700"
          />
        ) : (
          <ClaudeCasUploadButton
            onSuccess={onImported}
            label={isNivesh
              ? `Upload ${clientName}'s CAS · Nivesh Parser`
              : `Upload ${clientName}'s CAS · Claude Vision`}
            testId={isNivesh ? "client-nivesh-cas-btn" : "client-claude-cas-btn"}
            className={isNivesh
              ? "bg-emerald-600 hover:bg-emerald-700"
              : "bg-indigo-600 hover:bg-indigo-700"}
          />
        )}
        <span className="text-[11px] text-slate-500 flex items-center gap-1">
          <ShieldCheck className="w-3 h-3 text-emerald-600" />
          Read-only · No transactions · Data encrypted
        </span>
      </div>
    </Card>
  );
}
