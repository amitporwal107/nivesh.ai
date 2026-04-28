import React, { useState, useRef } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Sparkles, Loader2, Upload, X, FileText, KeyRound } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * ClaudeCasUploadButton — drop-in alternative to <CasConnectButton/>.
 *
 * Same prop signature so the wizard can swap one for the other:
 *   <ClaudeCasUploadButton onSuccess={...} label="..." testId="..." />
 *
 * Flow:
 *   1. Click → opens a modal with a PDF picker + password field.
 *   2. POST file bytes to /api/portfolio/upload-raw (streams the PDF; the
 *      backend routes the parse through the active provider — Claude
 *      Vision when admin selected `claude_vision` in /admin/cas-config).
 *   3. Poll /api/portfolio/upload-status/{task_id} every 1.5s until done.
 *   4. Call onSuccess(result) once parsing completes.
 *
 * Note: this widget does NOT depend on the casparser.in SDK, so it's the
 * "alternative SDK" to use when you've toggled the provider to Claude.
 */
export default function ClaudeCasUploadButton({
  onSuccess,
  className = "",
  variant = "default",
  size = "default",
  label = "Upload CAS via Claude Vision",
  testId = "claude-cas-upload-btn",
  portfolioId = "",
}) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState(null);
  const [password, setPassword] = useState("");
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState(""); // upload | parsing | done | error
  const [progressMsg, setProgressMsg] = useState("");
  const fileRef = useRef(null);

  const reset = () => {
    setFile(null);
    setPassword("");
    setUploading(false);
    setStatus("");
    setProgressMsg("");
  };

  const close = () => {
    if (uploading) return;
    setOpen(false);
    reset();
  };

  const upload = async () => {
    if (!file) {
      toast.error("Pick a CAS PDF first");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      toast.error("Only PDF files are supported");
      return;
    }
    setUploading(true);
    setStatus("upload");
    setProgressMsg("Uploading PDF…");
    try {
      const res = await axios.post(`${API}/portfolio/upload-raw`, file, {
        withCredentials: true,
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Filename": file.name,
          "X-Portfolio-Id": portfolioId || "",
          "X-Password": password || "",
        },
        timeout: 60000,
      });
      const taskId = res.data?.task_id;
      if (!taskId) {
        // Synchronous response (CSV/XLSX) — no polling needed
        setStatus("done");
        toast.success(res.data?.message || "Imported");
        if (onSuccess) onSuccess(res.data);
        setTimeout(() => { setOpen(false); reset(); }, 500);
        return;
      }
      // Poll
      setStatus("parsing");
      setProgressMsg("Claude Vision is reading your CAS… (30-90s)");
      const deadline = Date.now() + 4 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 1500));
        try {
          const s = await axios.get(`${API}/portfolio/upload-status/${taskId}`, { withCredentials: true });
          const st = s.data?.status;
          if (st === "completed") {
            setStatus("done");
            setProgressMsg(s.data?.message || "Done");
            toast.success(s.data?.message || `${s.data?.count || 0} holdings imported`);
            if (onSuccess) onSuccess(s.data);
            setTimeout(() => { setOpen(false); reset(); }, 700);
            return;
          }
          if (st === "failed" || st === "error") {
            throw new Error(s.data?.message || "Parsing failed");
          }
          if (s.data?.message) setProgressMsg(s.data.message);
        } catch (pollErr) {
          if (pollErr.message?.includes("Parsing failed")) throw pollErr;
          // Transient polling errors → keep going
        }
      }
      throw new Error("Parsing timed out after 4 minutes");
    } catch (err) {
      setStatus("error");
      const msg = err?.response?.data?.detail || err?.message || "Upload failed";
      setProgressMsg(msg);
      toast.error(msg);
    } finally {
      setUploading(false);
    }
  };

  return (
    <>
      <Button
        onClick={() => setOpen(true)}
        disabled={uploading}
        variant={variant}
        size={size}
        className={className}
        data-testid={testId}
      >
        <Sparkles className="w-4 h-4 mr-2" /> {label}
      </Button>

      {open && (
        <div
          className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={close}
          data-testid="claude-cas-upload-modal"
        >
          <div
            className="bg-white dark:bg-slate-900 rounded-xl shadow-2xl max-w-md w-full overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-700">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-indigo-500" />
                <span className="text-sm font-bold text-slate-800 dark:text-slate-100">
                  Claude Vision · CAS Import
                </span>
              </div>
              <button
                onClick={close}
                disabled={uploading}
                className="text-slate-400 hover:text-slate-600 disabled:opacity-30"
                data-testid="claude-cas-close-btn"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-5 space-y-4">
              {/* File picker */}
              <div>
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5 flex items-center gap-1.5">
                  <FileText className="w-3 h-3" /> CAS PDF
                </label>
                <div
                  onClick={() => fileRef.current?.click()}
                  className="border-2 border-dashed border-slate-300 dark:border-slate-600 rounded-lg p-4 text-center cursor-pointer hover:border-indigo-400 transition-colors"
                  data-testid="claude-cas-dropzone"
                >
                  {file ? (
                    <>
                      <FileText className="w-6 h-6 text-indigo-500 mx-auto mb-1" />
                      <div className="text-xs font-semibold text-slate-700 dark:text-slate-200">{file.name}</div>
                      <div className="text-[10px] text-slate-500">{(file.size / 1024).toFixed(0)} KB</div>
                    </>
                  ) : (
                    <>
                      <Upload className="w-6 h-6 text-slate-400 mx-auto mb-1" />
                      <div className="text-xs text-slate-600 dark:text-slate-300">Click to select a CAS PDF</div>
                      <div className="text-[10px] text-slate-400 mt-0.5">NSDL · CDSL · CAMS · KFintech</div>
                    </>
                  )}
                </div>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  className="hidden"
                  data-testid="claude-cas-file-input"
                />
              </div>

              {/* Password */}
              <div>
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5 flex items-center gap-1.5">
                  <KeyRound className="w-3 h-3" /> PDF password (PAN)
                </label>
                <input
                  type="text"
                  value={password}
                  onChange={(e) => setPassword(e.target.value.toUpperCase())}
                  placeholder="ABCDE1234F"
                  maxLength={10}
                  className="w-full h-9 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 text-sm font-mono text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-300"
                  data-testid="claude-cas-password-input"
                  disabled={uploading}
                />
                <p className="text-[10px] text-slate-400 mt-1">
                  Required for password-protected NSDL / CDSL CAS PDFs.
                </p>
              </div>

              {/* Status */}
              {status && (
                <div
                  className={`text-xs rounded-lg p-2.5 flex items-center gap-2 ${
                    status === "error"
                      ? "bg-rose-50 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300"
                      : status === "done"
                        ? "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300"
                        : "bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300"
                  }`}
                  data-testid="claude-cas-status"
                >
                  {status !== "done" && status !== "error" && <Loader2 className="w-3 h-3 animate-spin" />}
                  <span className="flex-1">{progressMsg}</span>
                </div>
              )}

              <Button
                onClick={upload}
                disabled={!file || uploading}
                className="w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg h-10"
                data-testid="claude-cas-submit-btn"
              >
                {uploading ? (
                  <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Parsing…</>
                ) : (
                  <><Sparkles className="w-4 h-4 mr-2" /> Parse with Claude Vision</>
                )}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
