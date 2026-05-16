import React, { useState, useEffect } from "react";
import axios from "axios";
import {
  Mail, Link2, Unlink, Search, Download, AlertCircle,
  FileText, Shield, RefreshCw, Check, Lock, ChevronDown, ChevronUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const CONFIDENCE_COLORS = {
  high: { bg: "bg-emerald-50 dark:bg-emerald-900/20", text: "text-emerald-600", label: "High" },
  medium: { bg: "bg-amber-50 dark:bg-amber-900/20", text: "text-amber-600", label: "Medium" },
  low: { bg: "bg-red-50 dark:bg-red-900/20", text: "text-red-500", label: "Low" },
};

const getConfLevel = (c) => c >= 0.7 ? "high" : c >= 0.4 ? "medium" : "low";

const GmailImport = ({ onRefresh }) => {
  const [connected, setConnected] = useState(false);
  const [connectedAt, setConnectedAt] = useState(null);
  const [lastImport, setLastImport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [emails, setEmails] = useState([]);
  const [scanned, setScanned] = useState(false);
  const [importingId, setImportingId] = useState(null);
  const [pollTaskId, setPollTaskId] = useState(null);
  const [passwordMap, setPasswordMap] = useState({});
  const [expandedEmail, setExpandedEmail] = useState(null);

  useEffect(() => {
    checkStatus();
    // Check URL params for callback result
    const params = new URLSearchParams(window.location.search);
    if (params.get("gmail") === "connected") {
      toast.success("Gmail connected successfully!");
      window.history.replaceState({}, "", window.location.pathname);
    }
    if (params.get("gmail_error")) {
      toast.error(`Gmail connection failed: ${params.get("gmail_error")}`);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  // Poll for import task
  useEffect(() => {
    if (!pollTaskId) return;
    const interval = setInterval(async () => {
      try {
        const res = await axios.get(`${API}/portfolio/upload-status/${pollTaskId}`, { withCredentials: true });
        if (res.data.status === "completed") {
          clearInterval(interval);
          toast.success(res.data.message || "Import complete!");
          setPollTaskId(null);
          setImportingId(null);
          onRefresh();
          // Mark as imported in local state
          setEmails(prev => prev.map(e => e.message_id === importingId ? { ...e, already_imported: true } : e));
        } else if (res.data.status === "error") {
          clearInterval(interval);
          toast.error(res.data.message || "Import failed");
          setPollTaskId(null);
          setImportingId(null);
        }
      } catch {}
    }, 5000);
    return () => clearInterval(interval);
  }, [pollTaskId, importingId, onRefresh]);

  const checkStatus = async () => {
    try {
      const res = await axios.get(`${API}/gmail/status`, { withCredentials: true });
      setConnected(res.data.connected);
      setConnectedAt(res.data.connected_at);
      setLastImport(res.data.last_import || null);
    } catch {} finally {
      setLoading(false);
    }
  };

  const connect = async () => {
    try {
      const res = await axios.get(`${API}/gmail/connect`, {
        params: { return_to: window.location.pathname },
        withCredentials: true,
      });
      window.location.href = res.data.auth_url;
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to connect Gmail");
    }
  };

  const disconnect = async () => {
    if (!window.confirm("Disconnect Gmail? You can reconnect anytime.")) return;
    try {
      await axios.post(`${API}/gmail/disconnect`, {}, { withCredentials: true });
      setConnected(false);
      setEmails([]);
      setScanned(false);
      toast.success("Gmail disconnected");
    } catch {}
  };

  const scan = async () => {
    setScanning(true);
    try {
      const res = await axios.post(`${API}/gmail/scan`, {}, { withCredentials: true });
      setEmails(res.data.emails || []);
      setScanned(true);
      if (res.data.emails.length === 0) {
        toast.info("No CAS emails found in your Gmail");
      } else {
        toast.success(`Found ${res.data.emails.length} CAS email(s)!`);
      }
    } catch (err) {
      const detail = err.response?.data?.detail || "Scan failed";
      if (err.response?.status === 401) {
        setConnected(false);
        toast.error("Gmail session expired. Please reconnect.");
      } else {
        toast.error(detail);
      }
    } finally {
      setScanning(false);
    }
  };

  const importEmail = async (email, attachment) => {
    const key = `${email.message_id}_${attachment.attachment_id}`;
    setImportingId(email.message_id);
    try {
      const res = await axios.post(`${API}/gmail/import`, {
        message_id: email.message_id,
        attachment_id: attachment.attachment_id,
        filename: attachment.filename,
        password: passwordMap[key] || "",
      }, { withCredentials: true });
      setPollTaskId(res.data.task_id);
      toast.info("Importing CAS from Gmail...");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Import failed");
      setImportingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-20">
        <div className="w-5 h-5 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl" data-testid="gmail-import">
      <CardContent className="p-6">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 rounded-xl bg-red-50 dark:bg-red-900/20 flex items-center justify-center">
            <Mail className="w-5 h-5 text-red-500" strokeWidth={1.5} />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
              Gmail Auto-Import
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {connected ? (
                <>
                  Connected — scan your inbox for CAS statements
                  {lastImport && (
                    <span className="block text-[10px] text-slate-400 mt-0.5">
                      Last import: <strong>{lastImport.filename || "CAS"}</strong> on{" "}
                      {new Date(lastImport.imported_at).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}
                      {lastImport.count > 0 && ` (${lastImport.count} holdings)`}
                    </span>
                  )}
                </>
              ) : "Connect Gmail to auto-detect CAS emails"}
            </p>
          </div>
          {connected ? (
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 text-emerald-600">
                Connected
              </span>
              <Button variant="ghost" size="sm" onClick={disconnect} className="text-slate-400 hover:text-red-500 h-8 px-2" data-testid="gmail-disconnect">
                <Unlink className="w-3.5 h-3.5" />
              </Button>
            </div>
          ) : (
            <Button onClick={connect} className="bg-red-500 hover:bg-red-600 text-white rounded-xl" data-testid="gmail-connect">
              <Link2 className="w-4 h-4 mr-2" /> Connect Gmail
            </Button>
          )}
        </div>

        {connected && (
          <div className="space-y-4">
            {/* Scan Button */}
            <Button
              onClick={scan}
              disabled={scanning}
              className="w-full bg-slate-50 dark:bg-slate-700 hover:bg-slate-100 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-600 rounded-xl h-11"
              data-testid="gmail-scan"
            >
              {scanning ? (
                <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Search className="w-4 h-4 mr-2" />
              )}
              {scanning ? "Scanning inbox..." : scanned ? "Scan Again" : "Scan for CAS Emails"}
            </Button>

            {/* Results */}
            {scanned && emails.length === 0 && (
              <div className="text-center py-6">
                <Mail className="w-10 h-10 text-slate-300 mx-auto mb-3" />
                <p className="text-sm text-slate-500 dark:text-slate-400">No CAS emails found in your inbox.</p>
                <p className="text-xs text-slate-400 mt-1">We look for emails from NSDL, CDSL, CAMS, and KFintech.</p>
              </div>
            )}

            {emails.length > 0 && (
              <div className="space-y-2" data-testid="gmail-email-list">
                <p className="text-xs font-bold tracking-wider uppercase text-slate-400">
                  {emails.length} CAS email{emails.length > 1 ? "s" : ""} found
                </p>
                {emails.map((email, i) => {
                  const conf = getConfLevel(email.confidence);
                  const confCfg = CONFIDENCE_COLORS[conf];
                  const isExpanded = expandedEmail === i;

                  return (
                    <motion.div
                      key={email.message_id}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.05 }}
                      className={`rounded-xl border transition-all ${
                        email.already_imported
                          ? "border-emerald-200 dark:border-emerald-800 bg-emerald-50/30 dark:bg-emerald-900/10"
                          : "border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50"
                      }`}
                      data-testid={`gmail-email-${i}`}
                    >
                      <div
                        className="p-4 cursor-pointer flex items-center gap-3"
                        onClick={() => setExpandedEmail(isExpanded ? null : i)}
                      >
                        <FileText className="w-5 h-5 text-red-400 flex-shrink-0" strokeWidth={1.5} />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-slate-900 dark:text-white truncate">{email.subject}</p>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-xs text-slate-400 truncate">{email.sender}</span>
                            <span className="text-[10px] text-slate-400">{email.date}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          <span className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${confCfg.bg} ${confCfg.text}`}>
                            {confCfg.label}
                          </span>
                          {email.already_imported && (
                            <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600">
                              Imported
                            </span>
                          )}
                          {isExpanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
                        </div>
                      </div>

                      <AnimatePresence>
                        {isExpanded && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: "auto", opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            className="overflow-hidden"
                          >
                            <div className="px-4 pb-4 border-t border-slate-100 dark:border-slate-700 pt-3 space-y-3">
                              {email.attachments.map((att, ai) => {
                                const key = `${email.message_id}_${att.attachment_id}`;
                                const isImporting = importingId === email.message_id;
                                return (
                                  <div key={ai} className="flex items-center gap-3 bg-white dark:bg-slate-800 rounded-lg p-3 border border-slate-100 dark:border-slate-700">
                                    <FileText className="w-4 h-4 text-slate-400 flex-shrink-0" />
                                    <div className="flex-1 min-w-0">
                                      <p className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate">{att.filename}</p>
                                      <p className="text-[10px] text-slate-400">{(att.size / 1024).toFixed(0)} KB</p>
                                    </div>
                                    <div className="flex items-center gap-2">
                                      <div className="flex flex-col gap-0.5">
                                        <div className="flex items-center gap-1">
                                          <Lock className="w-3 h-3 text-slate-400 flex-shrink-0" />
                                          <input
                                            type="password"
                                            placeholder="PDF password"
                                            autoComplete="new-password"
                                            value={passwordMap[key] || ""}
                                            onChange={(e) => setPasswordMap(prev => ({ ...prev, [key]: e.target.value }))}
                                            className="w-28 text-xs bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-2 py-1 text-slate-700 dark:text-slate-300 placeholder:text-slate-400"
                                            data-testid={`gmail-password-${i}-${ai}`}
                                          />
                                        </div>
                                        <p className="text-[9px] text-slate-400 pl-4">PAN in UPPERCASE</p>
                                      </div>
                                      {email.already_imported ? (
                                        <span className="flex items-center gap-1 text-xs text-emerald-600">
                                          <Check className="w-3 h-3" /> Done
                                        </span>
                                      ) : (
                                        <Button
                                          size="sm"
                                          onClick={() => importEmail(email, att)}
                                          disabled={isImporting}
                                          className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg h-7 text-xs px-3"
                                          data-testid={`gmail-import-${i}-${ai}`}
                                        >
                                          {isImporting ? (
                                            <RefreshCw className="w-3 h-3 animate-spin" />
                                          ) : (
                                            <>
                                              <Download className="w-3 h-3 mr-1" /> Import
                                            </>
                                          )}
                                        </Button>
                                      )}
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </motion.div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Security note */}
        <div className="mt-4 flex items-start gap-2 text-[10px] text-slate-400 dark:text-slate-500">
          <Shield className="w-3 h-3 mt-0.5 flex-shrink-0" />
          <span>Gmail access is read-only. We only scan for CAS-related emails and never modify your inbox. You can disconnect at any time.</span>
        </div>
      </CardContent>
    </Card>
  );
};

export default GmailImport;
