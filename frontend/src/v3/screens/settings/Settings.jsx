import React, { useState } from "react";
import { useOutletContext, useNavigate } from "react-router-dom";
import { ChevronRight, Bell, Lock, Smartphone, FileText, HelpCircle, LogOut } from "lucide-react";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { useAuth } from "@/context/AuthContext";

export default function Settings() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const { logout } = useAuth() || {};
  const [pushOn, setPushOn] = useState(true);
  const [emailOn, setEmailOn] = useState(false);

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Settings" title="Preferences" />
      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 40 }}>
        <SettingsGroup title="Notifications">
          <ToggleRow icon={Bell} label="Push notifications" sub="Daily brief + alerts" value={pushOn} onChange={setPushOn} />
          <ToggleRow icon={Bell} label="Email summaries" sub="Weekly portfolio email" value={emailOn} onChange={setEmailOn} />
        </SettingsGroup>

        <SettingsGroup title="Account">
          <LinkRow icon={Lock} label="Security" sub="2FA · sessions · passkeys" onClick={() => {}} />
          <LinkRow icon={Smartphone} label="Connected accounts" sub="CAS · brokerage · bank" onClick={() => {}} />
          <LinkRow icon={FileText} label="Documents & reports" sub="Statements · tax · KYC" onClick={() => {}} />
        </SettingsGroup>

        <SettingsGroup title="Persona & data">
          <LinkRow icon={Bell} label="Switch persona" sub="Change how we frame answers" onClick={() => navigate("/profile")} />
          <LinkRow icon={FileText} label="Data privacy" sub="What we store and why" onClick={() => {}} />
        </SettingsGroup>

        <SettingsGroup title="Support">
          <LinkRow icon={HelpCircle} label="Help center" onClick={() => {}} />
          <LinkRow icon={FileText} label="Terms & disclosures" onClick={() => {}} />
          <LinkRow icon={LogOut} label="Sign out" danger onClick={logout || (() => { window.location.href = "/"; })} />
        </SettingsGroup>
      </div>
    </ScreenContainer>
  );
}

function SettingsGroup({ title, children }) {
  return (
    <section>
      <SectionHead title={title} />
      <div style={{ display: "flex", flexDirection: "column", gap: 1, background: "var(--v3-line)", border: "1px solid var(--v3-line)", borderRadius: 14, overflow: "hidden" }}>
        {children}
      </div>
    </section>
  );
}

function LinkRow({ icon: Icon, label, sub, onClick, danger = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        textAlign: "left",
        background: "var(--v3-bg-2)",
        padding: "14px 16px",
        display: "flex",
        alignItems: "center",
        gap: 14,
        cursor: "pointer",
        border: "none",
        width: "100%",
      }}
    >
      <span
        style={{
          width: 32,
          height: 32,
          borderRadius: 10,
          background: "var(--v3-bg-3)",
          display: "grid",
          placeItems: "center",
          color: danger ? "var(--v3-crimson)" : "var(--v3-ink-2)",
          flexShrink: 0,
        }}
      >
        <Icon size={16} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ color: danger ? "var(--v3-crimson)" : "var(--v3-ink-1)", fontSize: 14, fontWeight: 500 }}>{label}</div>
        {sub && <div style={{ color: "var(--v3-ink-3)", fontSize: 12, marginTop: 2 }}>{sub}</div>}
      </div>
      <ChevronRight size={16} style={{ color: "var(--v3-ink-3)" }} />
    </button>
  );
}

function ToggleRow({ icon: Icon, label, sub, value, onChange }) {
  return (
    <div
      style={{
        background: "var(--v3-bg-2)",
        padding: "14px 16px",
        display: "flex",
        alignItems: "center",
        gap: 14,
      }}
    >
      <span style={{ width: 32, height: 32, borderRadius: 10, background: "var(--v3-bg-3)", display: "grid", placeItems: "center", color: "var(--v3-ink-2)", flexShrink: 0 }}>
        <Icon size={16} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ color: "var(--v3-ink-1)", fontSize: 14, fontWeight: 500 }}>{label}</div>
        {sub && <div style={{ color: "var(--v3-ink-3)", fontSize: 12, marginTop: 2 }}>{sub}</div>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        onClick={() => onChange(!value)}
        style={{
          width: 44,
          height: 26,
          padding: 3,
          borderRadius: 999,
          background: value ? "var(--v3-saffron)" : "var(--v3-bg-3)",
          border: "1px solid var(--v3-line)",
          cursor: "pointer",
          transition: "background var(--v3-dur) var(--v3-ease)",
          position: "relative",
        }}
      >
        <span
          style={{
            display: "block",
            width: 18,
            height: 18,
            borderRadius: 999,
            background: value ? "var(--v3-saffron-ink)" : "var(--v3-ink-2)",
            transform: value ? "translateX(18px)" : "translateX(0)",
            transition: "transform var(--v3-dur) var(--v3-ease)",
          }}
        />
      </button>
    </div>
  );
}
