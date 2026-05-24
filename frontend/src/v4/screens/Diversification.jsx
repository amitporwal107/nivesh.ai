/**
 * V4 Diversification Dashboard — fund overlap heatmap.
 * Endpoint: GET /api/portfolio/exposure/fund-overlap/matrix
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
} from "../components/DashboardShell";

export default function Diversification() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    api.get("/api/portfolio/exposure/fund-overlap/matrix")
      .then(setData)
      .catch(setErr)
      .finally(() => setLoading(false));
  }, [user]);

  if (authLoading) return null;
  if (!user) { navigate("/onboarding", { replace: true }); return null; }

  const pairs = data?.pairs || [];
  const highPairs = data?.high_pairs || 0;
  const maxPct = data?.max_pct || 0;
  const coveragePct = data?.coverage_pct || 0;

  return (
    <DashboardShell>
      <div style={pageTitleStyle}>
        <div style={{ fontFamily: "var(--v4-display)", fontSize: 30, color: "var(--v4-ink)", marginBottom: 6 }}>
          Diversification
        </div>
        <div style={{ fontSize: 13, color: "var(--v4-ink-dim)" }}>
          Pairwise overlap between your mutual funds — duplicate exposure you might not know about.
        </div>
      </div>

      {loading && (
        <div style={gridStyle}>
          {[...Array(4)].map((_, i) => <Skeleton key={i} height={90} />)}
        </div>
      )}

      {!loading && err && (
        <EmptyState icon="⚡" title="Could not load data" sub={err.message || String(err)} />
      )}

      {!loading && data?.empty && (
        <EmptyState
          title="Need at least 2 mutual funds"
          sub="Add more funds to your portfolio to see overlap analysis. Upload a CAS from Onboarding."
        />
      )}

      {!loading && data && !data.empty && (
        <>
          <div style={gridStyle}>
            <StatTile
              label="Highest overlap"
              value={`${maxPct.toFixed(1)}%`}
              tone={maxPct > 65 ? "var(--v4-rust)" : maxPct > 40 ? "var(--v4-gold)" : "var(--v4-moss)"}
            />
            <StatTile
              label="High-overlap pairs"
              value={highPairs}
              sub="overlap ≥ 65%"
              tone={highPairs > 0 ? "var(--v4-rust)" : "var(--v4-moss)"}
            />
            <StatTile
              label="Fund pairs analysed"
              value={pairs.length}
            />
            <StatTile
              label="AUM coverage"
              value={`${coveragePct.toFixed(0)}%`}
              sub="have stock-level data"
              tone={coveragePct > 70 ? "var(--v4-moss)" : "var(--v4-gold)"}
            />
          </div>

          {pairs.length === 0 ? (
            <EmptyState title="No overlap data available" sub="Fund look-through data is being loaded for your holdings." />
          ) : (
            <section style={{ marginTop: 36 }}>
              <SectionHeader>Fund pair overlap</SectionHeader>
              <div style={overlapListStyle}>
                {pairs.map((pair, i) => (
                  <OverlapRow key={i} pair={pair} />
                ))}
              </div>
            </section>
          )}

          <section style={{ marginTop: 32 }}>
            <div style={noteStyle}>
              Overlap = % of shared underlying stocks (by weight). Two funds with 70%+ overlap are essentially
              the same bet. Consider consolidating into one.
            </div>
          </section>
        </>
      )}
    </DashboardShell>
  );
}

function OverlapRow({ pair }) {
  const pct = Number(pair.overlap_pct || 0);
  const tone =
    pct >= 65 ? "var(--v4-rust)" :
    pct >= 40 ? "var(--v4-gold)" :
    "var(--v4-moss)";
  const label =
    pct >= 65 ? "HIGH" :
    pct >= 40 ? "MED" : "LOW";

  return (
    <div style={overlapRowStyle}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: "var(--v4-ink)", marginBottom: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {pair.fund_a || pair.a || "Fund A"}
        </div>
        <div style={{ fontSize: 11, color: "var(--v4-ink-mute)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          vs {pair.fund_b || pair.b || "Fund B"}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <div style={{ width: 80 }}>
          <div style={{ height: 4, borderRadius: 2, background: "var(--v4-line-strong)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${pct}%`, background: tone, borderRadius: 2, transition: "width 0.4s var(--v4-ease)" }} />
          </div>
        </div>
        <div style={{ fontFamily: "var(--v4-display)", fontSize: 15, color: tone, width: 52, textAlign: "right" }}>
          {pct.toFixed(1)}%
        </div>
        <div style={{ fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 1, color: tone, width: 34 }}>
          {label}
        </div>
      </div>
    </div>
  );
}

/* ─── Styles ─── */

const pageTitleStyle = { marginBottom: 32 };

const gridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
  gap: 14,
  marginBottom: 14,
};

const overlapListStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 0,
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-lg)",
  overflow: "hidden",
};

const overlapRowStyle = {
  display: "flex",
  alignItems: "center",
  gap: 14,
  padding: "14px 18px",
  borderBottom: "1px solid var(--v4-line)",
};

const noteStyle = {
  fontFamily: "var(--v4-mono)",
  fontSize: 10,
  letterSpacing: 0.4,
  color: "var(--v4-ink-faint)",
  lineHeight: 1.6,
  padding: "14px 18px",
  background: "var(--v4-s1)",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-md)",
};
