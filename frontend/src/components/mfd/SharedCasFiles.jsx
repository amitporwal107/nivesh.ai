import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Download, RefreshCw, Loader2, FileText, AlertTriangle,
  CheckCircle2, KeyRound, Trash2, Mail, Upload, Clock,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * SharedCasFiles — MFD-side audit + recovery view for raw client-shared
 * CAS PDFs. Lists every file the client uploaded (Gmail import OR
 * direct upload). For each file:
 *   - Download the original PDF
 *   - See parse status + holdings count
 *   - Re-parse with a custom password if the auto-parse failed (PAN
 *     mismatch on NSDL CASes, etc.)
 *   - Delete the stored copy
 *
 * Pass `profileId` to scope to one client; omit for workspace-wide.
 */
export default function SharedCasFiles({ profileId = null, compact = false }) {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [reparseFor, setReparseFor] = useState(null); // file_id pending password input
  const [pwInput, setPwInput] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const url = profileId
        ? `${API}/mfd/profiles/${profileId}/cas-uploads`
        : `${API}/mfd/cas-uploads`;
      const { data } = await axios.get(url, { withCredentials: true });
      setFiles(data.files || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load shared files");
    } finally {
      setLoading(false);
    }
  }, [profileId]);

  useEffect(() => { load(); }, [load]);

  // Auto-poll when something is actively processing
  useEffect(() => {
    if (!files.some((f) => f.status === "processing")) return;
    const t = setInterval(load, 3500);
    return () => clearInterval(t);
  }, [files, load]);

  const download = async (file) => {
    setBusyId(file.file_id);
    try {
      const res = await axios.get(`${API}/mfd/cas-uploads/${file.file_id}/download`, {
        withCredentials: true,
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = file.filename || "cas.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => window.URL.revokeObjectURL(url), 1000);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Download failed");
    } finally {
      setBusyId(null);
    }
  };

  const reparse = async (file, customPw = null) => {
    setBusyId(file.file_id);
    try {
      await axios.post(
        `${API}/mfd/cas-uploads/${file.file_id}/reparse`,
        { password: customPw || null },
        { withCredentials: true },
      );
      toast.success("Re-parse queued — refreshing in a few seconds");
      setReparseFor(null);
      setPwInput("");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Re-parse failed");
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (file) => {
    if (!window.confirm(`Delete the stored copy of "${file.filename}"? Already-imported holdings will not be touched.`)) return;
    setBusyId(file.file_id);
    try {
      await axios.delete(`${API}/mfd/cas-uploads/${file.file_id}`, { withCredentials: true });
      toast.success("File removed");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    } finally {
      setBusyId(null);
    }
  };

  if (loading && files.length === 0) {
    return (
      <div className="flex items-center justify-center py-6 text-xs text-slate-500" data-testid="cas-files-loading">
        <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading shared files…
      </div>
    );
  }

  if (!loading && files.length === 0) {
    return (
      <div className="text-center py-6 text-xs text-slate-500 border border-dashed border-slate-200 dark:border-slate-700 rounded-lg" data-testid="cas-files-empty">
        <FileText className="w-6 h-6 mx-auto mb-1.5 text-slate-300" />
        No CAS PDFs shared yet. Once your client uploads via the invite link, they'll appear here.
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="cas-files-list">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500">
          Shared CAS files {files.length > 0 && <span className="text-slate-400">({files.length})</span>}
        </span>
        <button type="button" onClick={load}
                className="text-[10px] text-indigo-600 hover:underline flex items-center gap-1"
                data-testid="cas-files-refresh">
          <RefreshCw className={`w-2.5 h-2.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {files.map((f) => (
        <FileRow
          key={f.file_id}
          file={f}
          compact={compact}
          isBusy={busyId === f.file_id}
          isReparseOpen={reparseFor === f.file_id}
          pwInput={pwInput}
          onPwChange={setPwInput}
          onDownload={() => download(f)}
          onReparseQuick={() => reparse(f, null)}
          onReparseToggle={() => {
            setReparseFor(reparseFor === f.file_id ? null : f.file_id);
            setPwInput("");
          }}
          onReparseSubmit={() => reparse(f, pwInput.trim() || null)}
          onDelete={() => remove(f)}
        />
      ))}
    </div>
  );
}

function FileRow({
  file, compact, isBusy, isReparseOpen, pwInput, onPwChange,
  onDownload, onReparseQuick, onReparseToggle, onReparseSubmit, onDelete,
}) {
  const tone = STATUS_TONES[file.status] || STATUS_TONES.processing;
  const Icon = tone.icon;
  const sizeKb = file.file_size ? `${(file.file_size / 1024).toFixed(0)} KB` : "";
  const SourceIcon = file.source === "gmail" ? Mail : Upload;
  return (
    <div
      data-testid={`cas-file-row-${file.file_id}`}
      className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden bg-white dark:bg-slate-900"
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <div className={`w-6 h-6 shrink-0 rounded-md flex items-center justify-center ${tone.bg}`} title={tone.label}>
          <Icon className={`w-3 h-3 ${tone.fg}`} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[12px] font-semibold text-slate-800 dark:text-slate-100 truncate" title={file.filename}>
              {file.filename || "cas.pdf"}
            </span>
            <SourceIcon className="w-3 h-3 text-slate-400 shrink-0" title={file.source} />
          </div>
          <div className="text-[10px] text-slate-500 flex items-center flex-wrap gap-x-2 gap-y-0.5">
            <span>{tone.label}</span>
            {file.holdings_count > 0 && (
              <span className="text-emerald-600 font-semibold">· {file.holdings_count} holdings</span>
            )}
            {sizeKb && <span>· {sizeKb}</span>}
            {file.stored_at && <span>· {fmtDate(file.stored_at)}</span>}
            {!compact && file.client_name && <span className="truncate">· {file.client_name}</span>}
            {(file.reparse_count || 0) > 0 && <span>· re-parsed {file.reparse_count}×</span>}
          </div>
          {file.status === "error" && file.error && (
            <div className="text-[10px] text-rose-600 mt-1 flex items-start gap-1" data-testid={`cas-file-error-${file.file_id}`}>
              <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
              <span className="leading-tight">{file.error}</span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button type="button" size="sm" variant="ghost"
                  className="h-7 w-7 p-0" title="Download original"
                  onClick={onDownload} disabled={isBusy || !file.is_downloadable}
                  data-testid={`cas-file-download-${file.file_id}`}>
            {isBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
          </Button>
          {file.status === "error" ? (
            <Button type="button" size="sm" variant="outline"
                    className="h-7 text-[10px] px-2" title="Re-parse with custom password"
                    onClick={onReparseToggle} disabled={isBusy}
                    data-testid={`cas-file-reparse-toggle-${file.file_id}`}>
              <KeyRound className="w-3 h-3 mr-1" /> Re-parse
            </Button>
          ) : (
            <Button type="button" size="sm" variant="ghost"
                    className="h-7 w-7 p-0" title="Re-run parse (uses PAN)"
                    onClick={onReparseQuick} disabled={isBusy || file.status === "processing"}
                    data-testid={`cas-file-reparse-${file.file_id}`}>
              <RefreshCw className="w-3.5 h-3.5" />
            </Button>
          )}
          <Button type="button" size="sm" variant="ghost"
                  className="h-7 w-7 p-0 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950"
                  title="Delete stored copy" onClick={onDelete} disabled={isBusy}
                  data-testid={`cas-file-delete-${file.file_id}`}>
            <Trash2 className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>

      {isReparseOpen && (
        <div className="px-3 py-2 border-t border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 space-y-2"
             data-testid={`cas-file-reparse-form-${file.file_id}`}>
          <div className="text-[10px] text-slate-500">
            Try a different password. Common patterns:
            <span className="font-mono ml-1">PAN</span> ·
            <span className="font-mono ml-1">DDMMYYYY</span> (DOB) ·
            <span className="font-mono ml-1">PAN+DOB</span>.
            {file.client_pan && (
              <span> Client PAN on file: <span className="font-mono font-bold">{file.client_pan}</span></span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Input
              type="text"
              autoFocus
              placeholder={file.client_pan ? `Default: ${file.client_pan}` : "Custom password"}
              value={pwInput}
              onChange={(e) => onPwChange(e.target.value)}
              className="h-7 text-xs font-mono"
              data-testid={`cas-file-pw-input-${file.file_id}`}
            />
            <Button type="button" size="sm" onClick={onReparseSubmit}
                    disabled={isBusy} className="h-7 text-[11px]"
                    data-testid={`cas-file-reparse-submit-${file.file_id}`}>
              {isBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : "Re-parse"}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={onReparseToggle}
                    className="h-7 text-[11px]" data-testid={`cas-file-reparse-cancel-${file.file_id}`}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

const STATUS_TONES = {
  processing: { bg: "bg-amber-100 dark:bg-amber-950", fg: "text-amber-700", icon: Clock, label: "Parsing…" },
  completed:  { bg: "bg-emerald-100 dark:bg-emerald-950", fg: "text-emerald-700", icon: CheckCircle2, label: "Imported" },
  error:      { bg: "bg-rose-100 dark:bg-rose-950", fg: "text-rose-700", icon: AlertTriangle, label: "Parse failed" },
};

function fmtDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch { return iso.slice(0, 10); }
}
