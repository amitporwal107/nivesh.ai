import React, { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  Briefcase, Users, UserPlus, Upload, Sparkles, TrendingUp,
  CheckCircle2, Lock, ShieldCheck, ArrowRight, ArrowLeft, Loader2,
  AlertTriangle, FileText, Zap, Activity, RefreshCw, LifeBuoy,
} from "lucide-react";
import PriorityChip from "./PriorityChip";
import CasConnectButton from "@/components/CasConnectButton";
import ClaudeCasUploadButton from "@/components/ClaudeCasUploadButton";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * MfdOnboardingWizard — full-screen 6-step activation wizard.
 *
 * Per product PRD, the success metric is: MFD uploads first client and
 * sees a score + recommendation + priority. Every step is purposely
 * low-friction (no PAN, no KYC, no firm docs). Each step renders a
 * persistent "Trust strip" (read-only · no transactions · encrypted) so
 * the MFD never has to guess about data safety.
 *
 * Steps:
 *   1. firm       — Firm name + client count range (skippable)
 *   2. add_client — Client name + AUM + tags
 *   3. upload     — Drop CAS PDF (reuses retail /portfolio/upload path)
 *   4. processing — Polled status with animated stepper
 *   5. first_value — Client snapshot + priority chip + top insight + CTA
 *   6. dashboard_intro — Preview table + "Go to Client Dashboard"
 *
 * Trigger: `Dashboard.js` renders this full-screen when
 *   workspace.type === 'ADVISORY' && !workspace.mfd_onboarding_completed.
 */

const STEPS = ["firm", "add_client", "upload", "processing", "first_value", "dashboard_intro"];

const CLIENT_RANGE_OPTIONS = [
  { id: "<100",    label: "Less than 100" },
  { id: "100-500", label: "100 – 500" },
  { id: "500+",    label: "500+" },
];

const SUGGESTED_TAGS = ["Retail", "HNI", "Ultra-HNI", "Conservative", "Moderate", "Aggressive"];


export default function MfdOnboardingWizard({ onComplete }) {
  const [step, setStep] = useState("firm");
  const [firm, setFirm] = useState({
    firm_name: "", client_count_range: null,
    advisor_name: "", advisor_mobile: "", advisor_email: "", arn_or_ria: "",
  });
  const [savingFirm, setSavingFirm] = useState(false);

  // Step 2: client identity
  const [client, setClient] = useState({
    name: "", aum_rs: "", tags: [], tag_input: "", email: "", mobile: "",
  });
  const [createdProfile, setCreatedProfile] = useState(null);
  const [creatingClient, setCreatingClient] = useState(false);

  // Step 3-4: CAS upload + polling
  const fileRef = useRef(null);
  const [password, setPassword] = useState("");
  const [uploadTask, setUploadTask] = useState(null);
  const [uploadError, setUploadError] = useState(null);
  const [processingStages, setProcessingStages] = useState([
    { id: "parse",   label: "Parsing portfolio",  status: "pending" },
    { id: "score",   label: "Calculating scores", status: "pending" },
    { id: "insight", label: "Generating insights", status: "pending" },
  ]);

  // Step 5: the wow moment
  const [analysis, setAnalysis] = useState(null);

  // Active CAS parser provider — read once on mount so Step 3 shows the
  // right widget (CasConnectButton vs ClaudeCasUploadButton).
  const [casProvider, setCasProvider] = useState("casparser_api");
  useEffect(() => {
    axios.get(`${API}/cas-parser-provider/active`, { withCredentials: true })
      .then((r) => setCasProvider(r.data?.provider || "casparser_api"))
      .catch(() => { /* keep default */ });
  }, []);

  // ── STEP 1 · Firm setup ------------------------------------------------
  const saveFirm = async (skip = false) => {
    if (!skip) {
      // Mandatory fields (for the Client CAS invite flow downstream)
      if (!firm.advisor_name.trim()) { toast.error("Your name is required"); return; }
      if (!/^\d{10,}$/.test(firm.advisor_mobile.replace(/\D/g, ""))) {
        toast.error("Enter a valid mobile number (≥10 digits)"); return;
      }
      if (!/^\S+@\S+\.\S+$/.test(firm.advisor_email.trim())) {
        toast.error("Enter a valid email address"); return;
      }
      if (!firm.firm_name.trim()) { toast.error("Firm name is required"); return; }
      if (!firm.client_count_range) { toast.error("Pick your book size"); return; }
    }
    setSavingFirm(true);
    try {
      await axios.patch(`${API}/mfd/workspace`, {
        mode: "ADVISORY",
        firm_name:          skip ? null : (firm.firm_name || null),
        client_count_range: skip ? null : firm.client_count_range,
        advisor_name:       skip ? null : (firm.advisor_name.trim() || null),
        advisor_mobile:     skip ? null : (firm.advisor_mobile || null),
        advisor_email:      skip ? null : (firm.advisor_email.trim().toLowerCase() || null),
        arn_or_ria:         skip ? null : (firm.arn_or_ria.trim().toUpperCase() || null),
      }, { withCredentials: true });
      setStep("add_client");
    } catch (e) {
      toast.error("Could not save firm details");
    } finally {
      setSavingFirm(false);
    }
  };

  // ── STEP 2 · Create first client profile ------------------------------
  const addTag = (t) => {
    const clean = t.trim();
    if (!clean || client.tags.includes(clean) || client.tags.length >= 5) return;
    setClient({ ...client, tags: [...client.tags, clean], tag_input: "" });
  };

  const createClient = async () => {
    if (!client.name.trim()) {
      toast.error("Client name is required");
      return;
    }
    if (!/^\d{10,}$/.test(client.mobile.replace(/\D/g, ""))) {
      toast.error("Client mobile is required (≥10 digits) — we need it to send the CAS invite link");
      return;
    }
    if (!/^\S+@\S+\.\S+$/.test(client.email.trim())) {
      toast.error("Client email is required — we'll email a backup link");
      return;
    }
    setCreatingClient(true);
    try {
      const res = await axios.post(`${API}/mfd/profiles`, {
        name: client.name.trim(),
        aum_rs: client.aum_rs ? Number(client.aum_rs) : null,
        tags: client.tags.length ? client.tags : null,
        email:  client.email.trim(),
        mobile: client.mobile.trim(),
      }, { withCredentials: true });
      setCreatedProfile(res.data);
      // Activate impersonation so the CAS upload lands on this profile.
      await axios.post(`${API}/mfd/profiles/${res.data.profile_id}/activate`, {},
                       { withCredentials: true });
      setStep("upload");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not create client");
    } finally {
      setCreatingClient(false);
    }
  };

  // ── STEP 3 · CAS Connect widget handler -------------------------------
  // We no longer need our own dropzone / password field / polling — the
  // CAS Parser widget handles PDF upload, Gmail inbox fetch, and CDSL OTP
  // in one modal and returns parsed data directly. On success the backend
  // has already persisted holdings under the impersonated client's shadow
  // user_id, so we just need to animate the stages and fetch the profile.
  const onCasConnected = async (importResult) => {
    setUploadError(null);
    setStep("processing");
    setStage("parse", "done");
    setStage("score", "active");
    await new Promise((r) => setTimeout(r, 500));
    setStage("score", "done");
    setStage("insight", "active");
    await new Promise((r) => setTimeout(r, 400));
    await completeProcessing();
  };

  // ── STEP 3-4 · Upload + polling (legacy path, kept as fallback) -------
  const setStage = (id, status) =>
    setProcessingStages((cur) =>
      cur.map((s) => (s.id === id ? { ...s, status } : s)));

  const startUpload = async (file) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      toast.error("Please upload a CAS PDF"); return;
    }
    setUploadError(null);
    setStep("processing");
    setStage("parse", "active");
    try {
      let res;
      if (file.size > 4 * 1024 * 1024) {
        res = await axios.post(`${API}/portfolio/upload-raw`, file, {
          withCredentials: true,
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Filename": file.name,
            "X-Portfolio-Id": "",
            "X-Password": password || "",
          },
          timeout: 180000,
        });
      } else {
        const form = new FormData();
        form.append("file", file);
        form.append("password", password || "");
        res = await axios.post(`${API}/portfolio/upload`, form, {
          withCredentials: true,
          headers: { "Content-Type": "multipart/form-data" },
          timeout: 180000,
        });
      }
      if (res.data?.task_id) {
        setUploadTask(res.data.task_id);
      } else if (res.data?.count >= 0) {
        // Inline completion (no task) — jump straight to value screen.
        completeProcessing();
      }
    } catch (e) {
      handleCasFailure(e.response?.data?.detail || e.message || "Upload failed");
    }
  };

  const pollProcessing = useCallback(async () => {
    if (!uploadTask) return;
    const deadline = Date.now() + 180_000;
    while (Date.now() < deadline) {
      try {
        const res = await axios.get(
          `${API}/portfolio/upload-status/${uploadTask}`,
          { withCredentials: true },
        );
        const s = res.data?.status;
        if (s === "done") {
          setStage("parse", "done");
          setStage("score", "active");
          await new Promise((r) => setTimeout(r, 600));
          setStage("score", "done");
          setStage("insight", "active");
          await completeProcessing();
          return;
        }
        if (s === "error") {
          handleCasFailure(res.data?.message || "Could not read CAS clearly");
          return;
        }
      } catch (e) {
        handleCasFailure(e.response?.data?.detail || e.message || "Polling failed");
        return;
      }
      await new Promise((r) => setTimeout(r, 1800));
    }
    handleCasFailure("Processing timed out after 3 minutes");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploadTask]);

  useEffect(() => { if (uploadTask) pollProcessing(); }, [uploadTask, pollProcessing]);

  const completeProcessing = async () => {
    try {
      // Fetch the fresh profile (now with priority + snapshot).
      const res = await axios.get(
        `${API}/mfd/profiles/${createdProfile.profile_id}`,
        { withCredentials: true });
      setStage("insight", "done");
      setAnalysis(res.data);
      setTimeout(() => setStep("first_value"), 500);
    } catch (e) {
      handleCasFailure("Could not load analysis — please try again");
    }
  };

  const handleCasFailure = (msg) => {
    setUploadError(msg);
    setStep("upload");
    toast.error("Couldn't read the CAS clearly");
  };

  // ── Completion --------------------------------------------------------
  const finishWizard = async () => {
    try {
      await axios.patch(`${API}/mfd/workspace`, {
        mfd_onboarding_completed: true,
      }, { withCredentials: true });
      // Leave impersonation ON — the MFD is inside the new client already.
      onComplete?.(createdProfile);
    } catch (e) {
      toast.error("Could not complete onboarding");
    }
  };

  const exitToClients = async () => {
    try {
      await axios.patch(`${API}/mfd/workspace`, {
        mfd_onboarding_completed: true,
      }, { withCredentials: true });
      await axios.post(`${API}/mfd/profiles/deactivate`, {},
                       { withCredentials: true });
      onComplete?.(null);
    } catch (e) {
      toast.error("Could not open dashboard");
    }
  };

  // ── Layout ------------------------------------------------------------
  const stepIdx = STEPS.indexOf(step);

  return (
    <div
      data-testid="mfd-onboarding-wizard"
      className="fixed inset-0 z-50 bg-gradient-to-br from-slate-50 via-white to-indigo-50/40 dark:from-slate-950 dark:via-slate-900 dark:to-indigo-950/30 overflow-y-auto"
    >
      <div className="max-w-3xl mx-auto px-6 py-10">
        {/* Header / progress */}
        <div className="flex items-center gap-2 mb-8">
          <div className="w-8 h-8 rounded-lg bg-indigo-600 text-white flex items-center justify-center">
            <Briefcase className="w-4 h-4" />
          </div>
          <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Nivesh Advisor — Setup
          </div>
          <div className="ml-auto text-[11px] text-slate-500 tabular-nums">
            Step {Math.min(stepIdx + 1, STEPS.length)} of {STEPS.length}
          </div>
        </div>

        <div className="h-1 rounded-full bg-slate-100 dark:bg-slate-800 mb-8">
          <div
            className="h-full bg-indigo-600 transition-all duration-500 rounded-full"
            style={{ width: `${((stepIdx + 1) / STEPS.length) * 100}%` }}
          />
        </div>

        {step === "firm" && (
          <FirmStep
            firm={firm} setFirm={setFirm}
            saving={savingFirm}
            onNext={() => saveFirm(false)}
            onSkip={() => saveFirm(true)}
          />
        )}

        {step === "add_client" && (
          <AddClientStep
            client={client} setClient={setClient}
            addTag={addTag}
            creating={creatingClient}
            onBack={() => setStep("firm")}
            onNext={createClient}
          />
        )}

        {step === "upload" && (
          <UploadStep
            client={createdProfile}
            onCasSuccess={onCasConnected}
            onSkip={exitToClients}
            error={uploadError}
            provider={casProvider}
          />
        )}

        {step === "processing" && (
          <ProcessingStep stages={processingStages} clientName={createdProfile?.name} />
        )}

        {step === "first_value" && (
          <FirstValueStep
            profile={analysis}
            onViewFull={finishWizard}
          />
        )}

        {step === "dashboard_intro" && (
          <DashboardIntroStep
            profile={analysis}
            onEnter={exitToClients}
          />
        )}

        <TrustStrip />
      </div>
    </div>
  );
}

// ── STEP 1 ─ Firm Setup ─────────────────────────────────────────────────
const FirmStep = ({ firm, setFirm, saving, onNext, onSkip }) => (
  <div className="space-y-6" data-testid="step-firm">
    <div>
      <div className="text-[10px] uppercase tracking-wider text-indigo-600 font-bold mb-1">
        Advisor setup
      </div>
      <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-50">
        Tell us about your practice
      </h1>
      <p className="text-sm text-slate-600 dark:text-slate-400 mt-2">
        We need these to power client onboarding invites — your name and mobile
        appear on the secure link clients use to share their CAS.
      </p>
    </div>

    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <Label htmlFor="advisor-name" className="text-xs">Your name *</Label>
          <Input
            id="advisor-name"
            data-testid="advisor-name-input"
            value={firm.advisor_name}
            onChange={(e) => setFirm({ ...firm, advisor_name: e.target.value })}
            placeholder="Priyanka Sharma"
            className="mt-1"
            autoFocus
          />
        </div>
        <div>
          <Label htmlFor="advisor-mobile" className="text-xs">Mobile (WhatsApp) *</Label>
          <Input
            id="advisor-mobile"
            data-testid="advisor-mobile-input"
            value={firm.advisor_mobile}
            onChange={(e) => setFirm({ ...firm, advisor_mobile: e.target.value })}
            placeholder="98xxxxxxxx"
            inputMode="tel"
            className="mt-1 font-mono tabular-nums"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <Label htmlFor="advisor-email" className="text-xs">Email *</Label>
          <Input
            id="advisor-email"
            data-testid="advisor-email-input"
            value={firm.advisor_email}
            onChange={(e) => setFirm({ ...firm, advisor_email: e.target.value })}
            placeholder="you@firm.com"
            type="email"
            className="mt-1"
          />
        </div>
        <div>
          <Label htmlFor="advisor-arn" className="text-xs">
            ARN / RIA <span className="text-slate-400">· optional</span>
          </Label>
          <Input
            id="advisor-arn"
            data-testid="advisor-arn-input"
            value={firm.arn_or_ria}
            onChange={(e) => setFirm({ ...firm, arn_or_ria: e.target.value.toUpperCase() })}
            placeholder="ARN-12345"
            className="mt-1 font-mono"
          />
        </div>
      </div>

      <div>
        <Label htmlFor="firm-name" className="text-xs">Firm name *</Label>
        <Input
          id="firm-name"
          data-testid="firm-name-input"
          value={firm.firm_name}
          onChange={(e) => setFirm({ ...firm, firm_name: e.target.value })}
          placeholder="Sharma Wealth Advisors"
          className="mt-1"
        />
      </div>

      <div>
        <Label className="text-xs">How many clients do you manage? *</Label>
        <div className="grid grid-cols-3 gap-2 mt-2">
          {CLIENT_RANGE_OPTIONS.map((o) => (
            <button
              key={o.id}
              type="button"
              data-testid={`firm-range-${o.id}`}
              onClick={() => setFirm({ ...firm, client_count_range: o.id })}
              className={`rounded-lg border p-3 text-sm transition-colors ${
                firm.client_count_range === o.id
                  ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 ring-1 ring-indigo-300"
                  : "border-slate-200 dark:border-slate-700 hover:border-indigo-300"
              }`}
            >
              <div className="font-semibold">{o.label}</div>
            </button>
          ))}
        </div>
      </div>
    </div>

    <div className="flex items-center gap-3 pt-4">
      <Button
        variant="ghost" size="sm"
        onClick={onSkip} disabled={saving}
        data-testid="firm-skip-btn"
        className="text-slate-500"
      >
        Skip for now
      </Button>
      <div className="flex-1" />
      <Button
        onClick={onNext} disabled={saving}
        data-testid="firm-continue-btn"
        className="bg-indigo-600 hover:bg-indigo-700"
      >
        {saving ? "Saving…" : <>Continue <ArrowRight className="w-4 h-4 ml-1" /></>}
      </Button>
    </div>
  </div>
);

// ── STEP 2 ─ Add First Client ───────────────────────────────────────────
const AddClientStep = ({ client, setClient, addTag, creating, onBack, onNext }) => (
  <div className="space-y-6" data-testid="step-add-client">
    <div>
      <div className="text-[10px] uppercase tracking-wider text-indigo-600 font-bold mb-1 flex items-center gap-1.5">
        <UserPlus className="w-3 h-3" /> Activation step
      </div>
      <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-50">
        Let's analyze your first client
      </h1>
      <p className="text-sm text-slate-600 dark:text-slate-400 mt-2">
        Add a client and upload their CAS to instantly see portfolio health,
        risks, and recommendations — powered by the Nivesh AI engine.
      </p>
    </div>

    <div className="space-y-4">
      <div>
        <Label htmlFor="client-name" className="text-xs">Client name *</Label>
        <Input
          id="client-name" data-testid="client-name-input"
          value={client.name}
          onChange={(e) => setClient({ ...client, name: e.target.value })}
          placeholder="Rahul Sharma"
          className="mt-1" autoFocus
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <Label htmlFor="client-mobile" className="text-xs">Mobile (WhatsApp) *</Label>
          <Input
            id="client-mobile" data-testid="client-mobile-input"
            value={client.mobile}
            onChange={(e) => setClient({ ...client, mobile: e.target.value })}
            placeholder="98xxxxxxxx"
            inputMode="tel"
            className="mt-1 font-mono tabular-nums"
          />
        </div>
        <div>
          <Label htmlFor="client-email" className="text-xs">Email *</Label>
          <Input
            id="client-email" data-testid="client-email-input"
            type="email"
            value={client.email}
            onChange={(e) => setClient({ ...client, email: e.target.value })}
            placeholder="rahul@example.com"
            className="mt-1"
          />
        </div>
      </div>
      <div className="text-[10px] text-slate-500 -mt-2">
        Used to send your client the secure CAS-sharing link. Mobile = WhatsApp, Email = backup.
      </div>

      <div>
        <Label htmlFor="client-aum" className="text-xs">
          AUM (₹) <span className="text-slate-400">· optional, feeds priority engine</span>
        </Label>
        <Input
          id="client-aum" data-testid="client-aum-input"
          type="number"
          value={client.aum_rs}
          onChange={(e) => setClient({ ...client, aum_rs: e.target.value })}
          placeholder="2500000"
          className="mt-1 font-mono tabular-nums"
        />
        {client.aum_rs && Number(client.aum_rs) > 0 && (
          <div className="text-[10px] text-slate-500 mt-1">
            ≈ {formatRs(Number(client.aum_rs))}
          </div>
        )}
      </div>

      <div>
        <Label className="text-xs">Tags <span className="text-slate-400">· optional, up to 5</span></Label>
        <div className="flex flex-wrap gap-1.5 mt-1 mb-1.5 min-h-[26px]">
          {client.tags.map((t) => (
            <Badge
              key={t} variant="outline"
              className="text-[10px] gap-1 pr-1"
              data-testid={`wizard-tag-${t}`}
            >
              {t}
              <button
                onClick={() => setClient({ ...client, tags: client.tags.filter((x) => x !== t) })}
                className="hover:bg-slate-200 rounded-full p-0.5"
                aria-label={`Remove ${t}`}
              >×</button>
            </Badge>
          ))}
        </div>
        <div className="flex gap-2">
          <Input
            data-testid="client-tag-input"
            value={client.tag_input}
            onChange={(e) => setClient({ ...client, tag_input: e.target.value })}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); addTag(client.tag_input); }
            }}
            placeholder="Add a tag and press Enter"
            className="text-xs h-8"
          />
        </div>
        <div className="flex flex-wrap gap-1 mt-1.5">
          {SUGGESTED_TAGS.filter((t) => !client.tags.includes(t)).map((t) => (
            <button
              key={t} type="button"
              onClick={() => addTag(t)}
              className="text-[10px] px-2 py-0.5 rounded-full border border-dashed border-slate-300 text-slate-500 hover:border-indigo-400 hover:text-indigo-700"
              data-testid={`client-tag-suggest-${t}`}
            >+ {t}</button>
          ))}
        </div>
      </div>
    </div>

    <div className="flex items-center gap-2 pt-4">
      <Button
        variant="outline" size="sm" onClick={onBack} disabled={creating}
        data-testid="client-back-btn"
      >
        <ArrowLeft className="w-3 h-3 mr-1" /> Back
      </Button>
      <div className="flex-1" />
      <Button
        size="sm" onClick={onNext}
        disabled={creating || !client.name.trim()}
        data-testid="client-continue-btn"
        className="bg-indigo-600 hover:bg-indigo-700"
      >
        {creating ? "Creating…" : <>Create & analyze <ArrowRight className="w-4 h-4 ml-1" /></>}
      </Button>
    </div>
  </div>
);

// ── STEP 3 ─ Upload (via CAS Connect widget OR Claude Vision) ──────────
const UploadStep = ({ client, onCasSuccess, onSkip, error, provider }) => (
  <div className="space-y-5" data-testid="step-upload">
    <div>
      <div className="text-[10px] uppercase tracking-wider text-indigo-600 font-bold mb-1 flex items-center gap-1.5">
        <Upload className="w-3 h-3" /> Step 3 of 6
      </div>
      <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-50">
        Import {client?.name}'s portfolio
      </h1>
      <p className="text-sm text-slate-600 dark:text-slate-400 mt-2">
        {provider === "claude_vision" ? (
          <>Upload {client?.name}'s CAS PDF — <strong>Claude Vision</strong> will parse holdings, transactions, and SIPs.</>
        ) : provider === "nivesh_cas_parser" ? (
          <>Upload {client?.name}'s CAS PDF — <strong>Nivesh Parser</strong> (Google Document AI) extracts holdings, transactions, and SIPs.</>
        ) : (
          <>Launch <strong>CAS Connect</strong> to import {client?.name}'s portfolio — the widget handles PDF upload, Gmail auto-fetch, and CDSL OTP in one place.</>
        )}
      </p>
    </div>

    {error && (
      <div
        data-testid="cas-error-banner"
        className="rounded-lg border border-rose-200 bg-rose-50 dark:bg-rose-900/20 dark:border-rose-800 p-3 flex items-start gap-2"
      >
        <AlertTriangle className="w-4 h-4 text-rose-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <div className="text-sm font-semibold text-rose-800 dark:text-rose-300">
            Couldn't import the portfolio
          </div>
          <div className="text-xs text-rose-700 dark:text-rose-400 mt-0.5">{error}</div>
          <div className="mt-2 flex items-center gap-2">
            <a
              href="mailto:support@nivesh.ai?subject=CAS upload help"
              data-testid="cas-support-link"
              className="text-xs text-indigo-700 underline"
            >
              <LifeBuoy className="w-3 h-3 inline -mt-0.5 mr-0.5" />
              Contact support
            </a>
          </div>
        </div>
      </div>
    )}

    <Card className="p-6 rounded-xl border-2 border-indigo-200 bg-gradient-to-br from-indigo-50/60 via-white to-white dark:from-indigo-900/20 dark:via-slate-900 dark:to-slate-900 text-center">
      <div className="w-12 h-12 mx-auto rounded-xl bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center mb-3">
        <Sparkles className="w-6 h-6 text-indigo-600" strokeWidth={1.5} />
      </div>
      {provider === "claude_vision" ? (
        <>
          <div className="text-base font-semibold text-slate-900 dark:text-slate-100">
            Claude Vision · AI-powered CAS parser
          </div>
          <div className="text-xs text-slate-500 mt-1 mb-5">
            Drop a PDF · enter the password · Anthropic Claude Sonnet 4.5
            extracts holdings, transactions and folios in ~60 seconds.
          </div>
          <ClaudeCasUploadButton
            onSuccess={onCasSuccess}
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl h-11 px-6"
            label={`Upload ${client?.name || "client"}'s CAS PDF`}
            testId="wizard-claude-cas-btn"
          />
        </>
      ) : provider === "nivesh_cas_parser" ? (
        <>
          <div className="text-base font-semibold text-slate-900 dark:text-slate-100">
            Nivesh Parser · Google Document AI
          </div>
          <div className="text-xs text-slate-500 mt-1 mb-5">
            Drop a PDF · enter the password · Google Document AI extracts
            holdings, transactions and folios in ~15 seconds — works on
            scanned PDFs too.
          </div>
          <ClaudeCasUploadButton
            onSuccess={onCasSuccess}
            className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl h-11 px-6"
            label={`Upload ${client?.name || "client"}'s CAS PDF`}
            testId="wizard-nivesh-cas-btn"
          />
        </>
      ) : (
        <>
          <div className="text-base font-semibold text-slate-900 dark:text-slate-100">
            One widget · three import paths
          </div>
          <div className="text-xs text-slate-500 mt-1 mb-5">
            PDF upload · Gmail inbox fetch · CDSL OTP — no password field needed,
            the widget asks for it inline when required.
          </div>
          <CasConnectButton
            onSuccess={onCasSuccess}
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl h-11 px-6"
            label={`Launch CAS Connect for ${client?.name || "client"}`}
            testId="wizard-cas-connect-btn"
          />
        </>
      )}
    </Card>

    {/* Skip — let MFDs finish onboarding without importing a portfolio yet.
        Useful when the client's CAS isn't ready, or when the MFD is just
        exploring the product. They can import later from Client 360. */}
    <div className="flex flex-col items-center gap-1.5 pt-1">
      <Button
        variant="ghost"
        onClick={onSkip}
        data-testid="skip-cas-import-btn"
        className="text-xs text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 h-8"
      >
        Skip for now — I'll import later
      </Button>
      <span className="text-[10px] text-slate-400">
        You can re-launch CAS Connect any time from this client's profile.
      </span>
    </div>
  </div>
);

// ── STEP 4 ─ Processing ─────────────────────────────────────────────────
const ProcessingStep = ({ stages, clientName }) => (
  <div className="space-y-6 py-6" data-testid="step-processing">
    <div className="text-center">
      <div className="w-16 h-16 rounded-2xl bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center mx-auto mb-4">
        <Sparkles className="w-7 h-7 text-indigo-600 animate-pulse" />
      </div>
      <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-50">
        Analyzing {clientName}'s portfolio…
      </h1>
      <p className="text-sm text-slate-600 dark:text-slate-400 mt-2">
        Powered by the Nivesh AI engine. This usually takes 20-40 seconds.
      </p>
    </div>

    <div className="max-w-md mx-auto space-y-3" data-testid="processing-stages">
      {stages.map((s) => (
        <div
          key={s.id}
          data-testid={`stage-${s.id}`}
          className={`rounded-lg border p-3 flex items-center gap-3 transition-colors ${
            s.status === "done"
              ? "border-emerald-200 bg-emerald-50 dark:bg-emerald-900/20 dark:border-emerald-800"
              : s.status === "active"
                ? "border-indigo-300 bg-indigo-50 dark:bg-indigo-900/20 dark:border-indigo-700 ring-1 ring-indigo-200"
                : "border-slate-200 dark:border-slate-700 opacity-60"
          }`}
        >
          <div className="w-7 h-7 rounded-full flex items-center justify-center">
            {s.status === "done" ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-600" />
            ) : s.status === "active" ? (
              <Loader2 className="w-5 h-5 text-indigo-600 animate-spin" />
            ) : (
              <div className="w-3 h-3 rounded-full border-2 border-slate-300" />
            )}
          </div>
          <div className="text-sm font-semibold">{s.label}</div>
        </div>
      ))}
    </div>
  </div>
);

// ── STEP 5 ─ First Value (WOW moment) ───────────────────────────────────
const FirstValueStep = ({ profile, onViewFull }) => {
  const score = profile?.portfolio_score;
  const riskScore = profile?.risk_score;
  const priority = profile?.priority;
  const rec = (profile?.recommendation_count || 0);

  return (
    <div className="space-y-6" data-testid="step-first-value">
      <div>
        <div className="text-[10px] uppercase tracking-wider text-emerald-600 font-bold mb-1 flex items-center gap-1.5">
          <Zap className="w-3 h-3" /> Analysis ready
        </div>
        <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-50">
          Here's {profile?.name}'s snapshot
        </h1>
        <p className="text-sm text-slate-600 dark:text-slate-400 mt-2">
          Your first client is onboarded. This is exactly what you'll see in the full dashboard.
        </p>
      </div>

      <Card className="p-5 border-2 border-indigo-200 bg-gradient-to-br from-indigo-50/60 to-white dark:from-indigo-900/20">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-full bg-indigo-600 text-white flex items-center justify-center text-lg font-bold flex-shrink-0">
            {profile?.name?.slice(0, 1).toUpperCase()}
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="text-lg font-bold">{profile?.name}</div>
              {priority && <PriorityChip priority={priority} />}
            </div>
            <div className="text-xs text-slate-500 mt-0.5">
              AUM {profile?.aum_rs ? formatRs(profile.aum_rs) : "—"}
              {profile?.tags?.length ? ` · ${profile.tags.join(" · ")}` : ""}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 mt-4">
          <StatBig label="Portfolio score" value={score != null ? Math.round(score) : "—"}
                   tone={score < 60 ? "rose" : score < 80 ? "amber" : "emerald"} />
          <StatBig label="Risk score" value={riskScore != null ? Math.round(riskScore) : "—"}
                   tone={riskScore >= 60 ? "rose" : riskScore >= 40 ? "amber" : "emerald"} />
          <StatBig label="Pending actions" value={rec || "—"}
                   tone={rec > 0 ? "amber" : "slate"} />
        </div>
      </Card>

      <Card className="p-4 border-amber-200 bg-amber-50/50 dark:bg-amber-900/20 dark:border-amber-800">
        <div className="flex items-start gap-2">
          <Sparkles className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <div className="text-xs font-bold text-amber-900 dark:text-amber-300 mb-1">
              Top insight
            </div>
            <div className="text-sm text-slate-700 dark:text-slate-200">
              {priority?.reasons?.[0] || "We'll surface concrete recommendations once the engine finishes scoring every holding."}
            </div>
          </div>
        </div>
      </Card>

      <div className="flex items-center gap-2 pt-4">
        <div className="flex-1" />
        <Button
          onClick={onViewFull}
          data-testid="first-value-cta"
          className="bg-indigo-600 hover:bg-indigo-700"
        >
          View full analysis <ArrowRight className="w-4 h-4 ml-1" />
        </Button>
      </div>
    </div>
  );
};

// ── STEP 6 ─ Dashboard Intro ────────────────────────────────────────────
const DashboardIntroStep = ({ profile, onEnter }) => (
  <div className="space-y-6" data-testid="step-dashboard-intro">
    <div>
      <div className="text-[10px] uppercase tracking-wider text-indigo-600 font-bold mb-1 flex items-center gap-1.5">
        <Users className="w-3 h-3" /> You're all set
      </div>
      <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-50">
        Now manage all your clients in one place
      </h1>
      <p className="text-sm text-slate-600 dark:text-slate-400 mt-2">
        The dashboard shows every client sorted by action priority — so you always know who to open first.
      </p>
    </div>

    <Card className="overflow-hidden border-2 border-indigo-100">
      <div className="grid grid-cols-12 px-4 py-2 bg-slate-50 dark:bg-slate-800 text-[10px] uppercase tracking-wider font-semibold text-slate-500 border-b">
        <div className="col-span-5">Client</div>
        <div className="col-span-2 text-right">AUM</div>
        <div className="col-span-2 text-right">Quality</div>
        <div className="col-span-3">Priority</div>
      </div>
      <div className="px-4 py-3 grid grid-cols-12 items-center">
        <div className="col-span-5 flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-[11px] font-bold">
            {profile?.name?.slice(0, 1).toUpperCase()}
          </div>
          <div className="text-sm font-semibold">{profile?.name}</div>
        </div>
        <div className="col-span-2 text-right tabular-nums text-sm">
          {profile?.aum_rs ? formatRs(profile.aum_rs) : "—"}
        </div>
        <div className="col-span-2 text-right text-sm font-semibold">
          {profile?.portfolio_score != null ? Math.round(profile.portfolio_score) : "—"}
        </div>
        <div className="col-span-3">
          {profile?.priority && <PriorityChip priority={profile.priority} />}
        </div>
      </div>
      <div className="px-4 py-3 border-t border-dashed border-slate-200 text-xs text-slate-500 text-center bg-slate-50/60">
        + Add more clients to see priority insights across your book
      </div>
    </Card>

    <div className="flex items-center gap-2 pt-4">
      <div className="flex-1" />
      <Button
        onClick={onEnter}
        data-testid="dashboard-intro-cta"
        className="bg-indigo-600 hover:bg-indigo-700"
      >
        Go to Client Dashboard <ArrowRight className="w-4 h-4 ml-1" />
      </Button>
    </div>
  </div>
);

// ── Trust-building strip — on every step ────────────────────────────────
const TrustStrip = () => (
  <div
    data-testid="trust-strip"
    className="mt-10 flex items-center justify-center gap-4 text-[11px] text-slate-500"
  >
    <span className="flex items-center gap-1">
      <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" /> Read-only access
    </span>
    <span className="flex items-center gap-1">
      <Activity className="w-3.5 h-3.5 text-emerald-600" /> No transactions
    </span>
    <span className="flex items-center gap-1">
      <Lock className="w-3.5 h-3.5 text-emerald-600" /> Data encrypted
    </span>
    <span className="flex items-center gap-1">
      <TrendingUp className="w-3.5 h-3.5 text-emerald-600" /> No PAN / KYC needed
    </span>
  </div>
);

// ── utils ───────────────────────────────────────────────────────────────
function formatRs(n) {
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}

const StatBig = ({ label, value, tone }) => {
  const tones = {
    rose:    "text-rose-600",
    amber:   "text-amber-600",
    emerald: "text-emerald-600",
    slate:   "text-slate-600",
  };
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-3 text-center">
      <div className="text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`text-2xl font-bold tabular-nums mt-0.5 ${tones[tone] || "text-slate-800"}`}>
        {value}
      </div>
    </div>
  );
};
