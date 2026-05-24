/**
 * V4 Risk Dashboard — beta, sharpe, volatility, risk drivers.
 * Endpoint: GET /api/portfolio/risk-analytics
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api from "../api/client";
import {
  DashboardShell,
  SectionHeader,
  StatTile,
  EmptyState,
  Skeleton,
  formatInr,
} from "../components/DashboardShell";

const RISK_TONE = {
  LOW:      "var(--v4-moss)",
  MODERATE: "var(--v4-gold)",
  HIGH:     "var(--v4-rust)",
  VERY_HIGH: "var(--v4-rust)",
  UNKNOWN:  "var(--v4-ink-faint)",
};

const IMPACT_TONE = {
  high:   "var(--v4-rust)",
  medium: "var(--v4-gold)",
  low:    "var(--v4-moss)",
};

export default function Risk() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    api.get("/api/portfolio/risk-analytics")
      .then(setData)
      .catch(setErr)
      .finally(() => setLoading(false));
  }, [user]);

  if (authLoading) return null;
  if (!user) { navigate("/onboarding", { replace: true }); return null; }

  const riskTone = RISK_TONE[data?.risk_rating] || "var(--v4-ink-faint)";

  return (
    <DashboardShell>
      <div style={pageTitleStyle}>
        <div style={{ fontFamily: "var(--v4-display)", fontSize: 30, color: "var(--v4-ink)", marginBottom: 6 }}>
          Risk
        </div>
        <div style={{ fontSize: 13, color: "var(--v4-ink-dim)" }}>
          Volatility, beta, and key risk drivers for your portfolio.
        </div>
      </div>

      {loading && (
        <div style={gridStyle}>
          {[...Array(5)].map((_, i) => <Skeleton key={i} height={90} />)}
        </div>
      )}

      {!loading && err && (
        <EmptyState icon="⚡" title="Could not load data" sub={err.message || String(err)} />
      )}

      {!loading && data?.empty && (
        <EmptyState
          title="No portfolio data"
          sub="Upload a CAS statement from Onboarding to see risk analytics."
        />
      )}

      {!loading && data && !data.empty && (
        <>
          {/* Hero stats row */}
          <div style={gridStyle}>
            <StatTile
              label="Risk rating"
              value={data.risk_rating || "—"}
              tone={riskTone}
            />
            {data.risk_score != null && (
              <StatTile
                label="Risk score"
                value={Number(data.risk_score).toFixed(1)}
                sub="out of 100"
                tone={riskTone}
              />
            )}
            <StatTile
              label="Portfolio beta"
              value={data.weighted_beta != null ? Number(data.weighted_beta).toFixed(2) : "—"}
              sub="vs market (1.0 = market)"
              tone={data.weighted_beta > 1.2 ? "var(--v4-rust)" : data.weighted_beta > 0.8 ? "var(--v4-gold)" : "var(--v4-moss)"}
            />
            <StatTile
              label="Sharpe ratio"
              value={data.weighted_sharpe != null ? Number(data.weighted_sharpe).toFixed(2) : "—"}
              sub="risk-adjusted return"
              tone={data.weighted_sharpe > 1 ? "var(--v4-moss)" : data.weighted_sharpe > 0 ? "var(--v4-gold)" : "var(--v4-rust)"}
            />
            <StatTile
              label="Volatility"
              value={data.weighted_volatility != null ? `${(Number(data.weighted_volatility) * 100).toFixed(1)}%` : "—"}
              sub="annualised std deviation"
            />
          </div>

          {/* Asset allocation */}
          {(data.equity_pct > 0 || data.debt_pct > 0) && (
            <section style={{ marginTop: 36 }}>
              <SectionHeader>Asset allocation</SectionHeader>
              <div style={allocationStyle}>
                <AllocationBar label="Equity" pct={data.equity_pct} tone="var(--v4-saffron)" />
                <AllocationBar label="Debt" pct={data.debt_pct} tone="var(--v4-indigo)" />
                {data.gold_pct > 0 && <AllocationBar label="Gold" pct={data.gold_pct} tone="var(--v4-gold)" />}
                {data.other_pct > 0 && <AllocationBar label="Other" pct={data.other_pct} tone="var(--v4-ink-faint)" />}
              </div>
            </section>
          )}

          {/* Risk drivers */}
          {data.risk_drivers?.length > 0 && (
            <section style={{ marginTop: 36 }}>
              <SectionHeader>Risk drivers</SectionHeader>
              <div style={driversListStyle}>
                {data.risk_drivers.map((d, i) => (
                  <DriverRow key={i} driver={d} />
                ))}
              </div>
            </section>
          )}

          {/* Fund breakdown */}
          {data.fund_breakdown?.length > 0 && (
            <section style={{ marginTop: 36 }}>
              <SectionHeader>Fund-level risk</SectionHeader>
              <div style={fundListStyle}>
                {data.fund_breakdown.slice(0, 10).map((f, i) => (
                  <FundRiskRow key={i} fund={f} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </DashboardShell>
  );
}

function AllocationBar({ label, pct, tone }) {
  const p = Number(pct || 0);
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={{ fontSize: 13, color: "var(--v4-ink)" }}>{label}</span>
        <span style={{ fontFamily: "var(--v4-display)", fontSize: 13, color: tone }}>{p.toFixed(1)}%</span>
      </div>
      <div style={{ height: 6, borderRadius: 3, background: "var(--v4-line-strong)" }}>
        <div style={{ height: "100%", width: `${Math.min(p, 100)}%`, background: tone, borderRadius: 3, transition: "width 0.5s var(--v4-ease)" }} />
      </div>
    </div>
  );
}

function DriverRow({ driver }) {
  const impact = String(driver.impact || "medium").toLowerCase();
  const tone = IMPACT_TONE[impact] || IMPACT_TONE.medium;
  return (
    <div style={driverRowStyle}>
      <div style={{ width: 4, background: tone, borderRadius: 4, alignSelf: "stretch" }} />
      <div style={{ flex: 1 }}>
        <div style={{ fontFamily: "var(--v4-display)", fontSize: 14, color: "var(--v4-ink)", marginBottom: 3 }}>
          {driver.label || driver.type || "Risk factor"}
        </div>
        {driver.detail && (
          <div style={{ fontSize: 12, color: "var(--v4-ink-dim)", lineHeight: 1.5 }}>{driver.detail}</div>
        )}
      </div>
      <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: tone, letterSpacing: 1, textTransform: "uppercase", flexShrink: 0 }}>
        {impact}
      </div>
    </div>
  );
}

function FundRiskRow({ fund }) {
  const beta = fund.beta != null ? Number(fund.beta).toFixed(2) : "—";
  const vol = fund.volatility != null ? `${(Number(fund.volatility) * 100).toFixed(1)}%` : "—";
  return (
    <div style={fundRowStyle}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: "var(--v4-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {fund.name || fund.scheme_name || "—"}
        </div>
        {fund.category && (
          <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-faint)", marginTop: 2 }}>
            {fund.category}
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 24, flexShrink: 0 }}>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-faint)", marginBottom: 2 }}>BETA</div>
          <div style={{ fontFamily: "var(--v4-display)", fontSize: 13, color: "var(--v4-ink)" }}>{beta}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-faint)", marginBottom: 2 }}>VOL</div>
          <div style={{ fontFamily: "var(--v4-display)", fontSize: 13, color: "var(--v4-ink)" }}>{vol}</div>
        </div>
        {fund.weight_pct != null && (
          <div style={{ textAlign: "right" }}>
            <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: "var(--v4-ink-faint)", marginBottom: 2 }}>WT</div>
            <div style={{ fontFamily: "var(--v4-display)", fontSize: 13, color: "var(--v4-ink)" }}>{Number(fund.weight_pct).toFixed(1)}%</div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Styles ─── */

const pageTitleStyle = { marginBottom: 32 };

const gridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 14,
  marginBottom: 14,
};

const allocationStyle = {
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-lg)",
  padding: "20px 22px",
};

const driversListStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 10,
};

const driverRowStyle = {
  display: "flex",
  gap: 14,
  alignItems: "flex-start",
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-md)",
  padding: "14px 18px",
};

const fundListStyle = {
  display: "flex",
  flexDirection: "column",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-md)",
  overflow: "hidden",
};

const fundRowStyle = {
  display: "flex",
  alignItems: "center",
  gap: 16,
  padding: "12px 16px",
  borderBottom: "1px solid var(--v4-line)",
  background: "var(--v4-s1)",
};
