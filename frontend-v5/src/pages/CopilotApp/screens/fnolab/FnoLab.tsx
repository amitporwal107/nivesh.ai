/**
 * F&O lab (/app/tool/fnolab?screen=…) — the seven PRD §15.1 screens of the F&O AI trading design
 * (docs/ai_research/designs/Nivesh F&O Desk (1).html):
 *
 *   mi      01 Market Intelligence     MarketIntel.tsx
 *   prog    05 Strategy Programs       Programs.tsx
 *   replay  06 Historical Replay Lab   Replay.tsx
 *   shadow  08 Shadow Mode Monitor     Shadow.tsx
 *   live    09 Live Trading Desk       LiveDesk.tsx
 *   cert    11 Certification Center    Certification.tsx
 *   audit   12 Audit & Decision Replay Audit.tsx
 *
 * Each screen renders its own source cards and body; this shell renders the tab bar, the mode strip and the heading.
 * Only the design's "today" state is built (see parts.tsx). Nothing here places an order.
 */
import type { ComponentType } from "react";
import { useSearchParams } from "react-router-dom";
import { Pill, Screen, ScreenHeader } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { SEBI_FNO_NOTE } from "../trading/parts";
import { Audit } from "./Audit";
import { Certification } from "./Certification";
import { LiveDesk } from "./LiveDesk";
import { MarketIntel } from "./MarketIntel";
import { LAB_SCREENS, ModeBand, isLabScreen, type LabScreenId } from "./parts";
import { Programs } from "./Programs";
import { Replay } from "./Replay";
import { Shadow } from "./Shadow";

const BODY: Record<LabScreenId, ComponentType> = {
  mi: MarketIntel, prog: Programs, replay: Replay, shadow: Shadow, live: LiveDesk, cert: Certification, audit: Audit,
};

export default function FnoLabScreen() {
  const { mobile } = useCopilotShell();
  const [params, setParams] = useSearchParams();
  const raw = params.get("screen");
  const active: LabScreenId = isLabScreen(raw) ? raw : "mi";
  const meta = LAB_SCREENS.find((s) => s.id === active) ?? LAB_SCREENS[0];
  const Body = BODY[active];

  const pick = (id: LabScreenId) => {
    const next = new URLSearchParams(params);
    next.set("screen", id);
    setParams(next, { replace: true });
  };

  return (
    <Screen testId="screen-tool-fnolab" width={1180}>
      <ScreenHeader
        eyebrow="F&O lab · NSE F&O"
        pills={<><Pill tone="mint">Trader mode</Pill><Pill tone="indigo">No orders</Pill></>}
        title={<>From market reading to <em>governed</em> execution.</>}
        sub="The seven screens of the F&O AI trading design. Each shows what the system can do today, with its sources, and names the backlog item for anything not built yet."
      />

      <div role="tablist" aria-label="F&O lab screens" className="cp-scroll flex overflow-x-auto" style={{ gap: mobile ? 16 : 22, borderBottom: "1px solid var(--cp-line)" }}>
        {LAB_SCREENS.map((s) => {
          const on = s.id === active;
          return (
            <button
              key={s.id}
              type="button"
              role="tab"
              id={`fnolab-tab-${s.id}`}
              data-testid={`fnolab-tab-${s.id}`}
              aria-selected={on}
              aria-controls="fnolab-panel"
              onClick={() => pick(s.id)}
              style={{ flex: "none", padding: "10px 0 12px", border: 0, borderBottom: `2px solid ${on ? "var(--mint)" : "transparent"}`, background: "none", fontFamily: "var(--sans)", fontSize: 14, whiteSpace: "nowrap", cursor: "pointer", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)" }}
            >
              {mobile ? s.short : s.label}
            </button>
          );
        })}
      </div>

      <div role="tabpanel" id="fnolab-panel" aria-labelledby={`fnolab-tab-${active}`} data-testid={`fnolab-screen-${active}`} className="flex flex-col min-w-0" style={{ gap: 14 }}>
        <ModeBand mode={meta.mode} />
        <div className="flex flex-col" style={{ gap: 6 }}>
          <h2 className="m-0" style={{ fontFamily: "var(--mono)", fontWeight: 400, fontSize: mobile ? 17 : 20, letterSpacing: "0.12em", textTransform: "uppercase" }}>
            <span style={{ color: "var(--mint)" }}>{meta.n}</span> · {meta.label}
          </h2>
          <span style={{ fontSize: 13.5, color: "var(--cp-ink-3)" }}>{meta.sub}</span>
        </div>
        <Body />
      </div>

      <span data-testid="fnolab-sebi" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-danger)" }}>
        {SEBI_FNO_NOTE} Nivesh places no orders; live access is earned through evidence and authorisation, never through model confidence.
      </span>
    </Screen>
  );
}
