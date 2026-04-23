import React, { useRef, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Upload, FileText, CheckCircle2, Loader2, Lock, AlertTriangle,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * ClientCasUpload — prominent onboarding CTA shown when a CLIENT profile
 * is active but has no portfolio yet. Reuses the exact same upload
 * endpoints the retail onboarding uses; because the session carries
 * `active_profile_id`, the backend silently stores the holdings under
 * the client's shadow user_id — no new route needed.
 *
 * Flow:
 *   1. MFD picks a PDF (drag-drop or file picker)
 *   2. Optional CAS password field
 *   3. POST /api/portfolio/upload (or -raw for >4MB) → task_id
 *   4. Poll /api/portfolio/upload-status/{task_id} until done
 *   5. Toast + `onImported()` callback so the parent re-fetches the client's
 *      portfolio + priority queue.
 */
export default function ClientCasUpload({ clientName, onImported }) {
  const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState(null);   // {status, message, count}
  const [dragging, setDragging] = useState(false);

  const pollStatus = useCallback(async (taskId) => {
    const deadline = Date.now() + 120_000; // 2 min
    while (Date.now() < deadline) {
      try {
        const res = await axios.get(
          `${API}/portfolio/upload-status/${taskId}`,
          { withCredentials: true },
        );
        const s = res.data?.status;
        if (s === "done") {
          const count = res.data.count || 0;
          setStatus({ status: "done", count, message: `${count} holdings imported` });
          toast.success(`${clientName}'s portfolio imported — ${count} holdings`);
          onImported?.();
          return;
        }
        if (s === "error") {
          throw new Error(res.data?.message || "CAS parse failed");
        }
        setStatus({ status: "processing", message: res.data?.message || "Parsing CAS…" });
      } catch (e) {
        setStatus({ status: "error", message: e.response?.data?.detail || e.message });
        toast.error("Upload failed");
        setUploading(false);
        return;
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
    setStatus({ status: "error", message: "Upload timed out after 2 minutes" });
    setUploading(false);
  }, [clientName, onImported]);

  const handleFile = async (file) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      toast.error("Please upload a CAS PDF file");
      return;
    }
    setUploading(true);
    setStatus({ status: "processing", message: `Uploading ${file.name}…` });
    try {
      let res;
      // >4 MB → raw stream upload path (matches existing retail code)
      if (file.size > 4 * 1024 * 1024) {
        res = await axios.post(`${API}/portfolio/upload-raw`, file, {
          withCredentials: true,
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Filename": file.name,
            "X-Portfolio-Id": "",
            "X-Password": password || "",
          },
          timeout: 120000,
        });
      } else {
        const form = new FormData();
        form.append("file", file);
        form.append("password", password || "");
        res = await axios.post(`${API}/portfolio/upload`, form, {
          withCredentials: true,
          headers: { "Content-Type": "multipart/form-data" },
          timeout: 120000,
        });
      }
      if (res.data?.task_id) {
        setStatus({ status: "processing", message: "AI is parsing the statement…" });
        pollStatus(res.data.task_id);
      } else if (res.data?.count >= 0) {
        const count = res.data.count;
        setStatus({ status: "done", count, message: `${count} holdings imported` });
        toast.success(`${clientName}'s portfolio imported`);
        setUploading(false);
        onImported?.();
      }
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || "Upload failed";
      setStatus({ status: "error", message: msg });
      toast.error(msg);
      setUploading(false);
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  const onDrop = (e) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files?.[0];
    handleFile(f);
  };

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
            Upload {clientName}'s Consolidated Account Statement (CAS) to build
            their portfolio. The file gets stored against {clientName}'s profile only —
            your own portfolio is unaffected.
          </p>
        </div>
      </div>

      <div
        onDragEnter={(e) => { e.preventDefault(); setDragging(true); }}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`rounded-xl p-6 border-2 border-dashed transition-colors text-center cursor-pointer ${
          dragging
            ? "border-indigo-500 bg-indigo-50"
            : uploading
              ? "border-slate-200 bg-slate-50 dark:bg-slate-800 cursor-wait"
              : "border-slate-300 dark:border-slate-700 hover:border-indigo-400 hover:bg-indigo-50/50 dark:hover:bg-indigo-900/20"
        }`}
        onClick={() => !uploading && fileRef.current?.click()}
        data-testid="client-cas-dropzone"
      >
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={(e) => handleFile(e.target.files?.[0])}
          data-testid="client-cas-file-input"
        />
        {uploading && status?.status === "processing" ? (
          <>
            <Loader2 className="w-8 h-8 mx-auto mb-3 text-indigo-600 animate-spin" />
            <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              {status.message}
            </div>
            <div className="text-[11px] text-slate-500 mt-1">
              This usually takes 10-30 seconds.
            </div>
          </>
        ) : status?.status === "done" ? (
          <>
            <CheckCircle2 className="w-8 h-8 mx-auto mb-3 text-emerald-600" />
            <div className="text-sm font-bold text-emerald-700">
              {status.count} holdings imported for {clientName}
            </div>
            <div className="text-[11px] text-slate-500 mt-1">
              Open Portfolio or Insights to review.
            </div>
          </>
        ) : status?.status === "error" ? (
          <>
            <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-rose-600" />
            <div className="text-sm font-semibold text-rose-700">
              {status.message}
            </div>
            <div className="text-[11px] text-slate-500 mt-1">
              Click to retry — if the CAS is password-protected, enter the password first.
            </div>
          </>
        ) : (
          <>
            <Upload className="w-8 h-8 mx-auto mb-3 text-indigo-600" />
            <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              Drop the CAS PDF here, or <span className="text-indigo-600 underline">click to browse</span>
            </div>
            <div className="text-[11px] text-slate-500 mt-1">
              Typically <code>~NSDL.PDF</code> or <code>~CDSL.PDF</code> from the depository email.
            </div>
          </>
        )}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <Lock className="w-3.5 h-3.5 text-slate-400" />
        <Input
          type="password"
          placeholder="CAS password (if protected)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={uploading}
          className="h-8 text-xs max-w-xs"
          data-testid="client-cas-password"
        />
        <div className="text-[10px] text-slate-400">
          PAN-based password — used only for this parse, never stored.
        </div>
      </div>

      <div className="mt-3 text-[10px] text-slate-400 leading-relaxed">
        Need the statement? Your client can request one at{" "}
        <a className="underline" href="https://www.cdslindia.com/CAS/LoginCAS.aspx" target="_blank" rel="noreferrer">CDSL</a>
        {" · "}
        <a className="underline" href="https://nsdlcas.nsdl.com/" target="_blank" rel="noreferrer">NSDL</a>.
      </div>
    </Card>
  );
}
