/**
 * Tool registry — what the Copilot can call.
 * Design: frontend-v5/design/nivesh-copilot/NVOps.dc.html, page === 'tools'.
 *
 * The design's table (tool, service, version, freshness, timeout, p95, 7-day
 * success, and a contract per tool) has no backend: the tools are Python
 * modules under backend/services/copilot_tools and nothing lists them or
 * records their calls. That block says so.
 *
 * What the backend does expose is the layer above the tools — the specialist
 * agents the intent router picks between (GET /api/copilot/agents). They are
 * shown as what they are, not as a stand-in for the tool list.
 */
import { useState } from "react";
import {
  AskChips, Btn, DataTable, EmptyBlock, Eyebrow, Footnote, LoadingBlock, NotConnected,
  Screen, Section, fmtNum, type Column,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { LoadFailed, OpsHeader, OpsTabs } from "./internal/shared";
import { useCopilotAgents, type CopilotAgent } from "./internal/use-internal-data";

const COLUMNS: Column<CopilotAgent>[] = [
  {
    key: "id", header: "Agent", width: "minmax(0,1.2fr)",
    render: (a) => <span data-testid="tools-agent-row" data-agent={a.id} style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--cp-ink)" }}>{a.id}</span>,
  },
  { key: "label", header: "Name", width: "minmax(0,1.2fr)", render: (a) => <span data-testid="tools-agent-label">{a.label}</span> },
  { key: "does", header: "Handles", width: "minmax(0,2.2fr)", render: (a) => <span title={a.one_liner ?? undefined}>{a.one_liner || "—"}</span> },
  {
    key: "triggers", header: "Trigger patterns", width: "110px", align: "right", num: true,
    render: (a) => <span data-testid="tools-agent-triggers">{fmtNum(a.triggers?.length ?? 0)}</span>,
  },
  {
    key: "starters", header: "Starters", width: "80px", align: "right", num: true,
    render: (a) => fmtNum(a.default_suggestions?.length ?? 0),
  },
];

function AgentDetail({ agent }: { agent: CopilotAgent }) {
  const triggers = agent.triggers ?? [];
  const starters = agent.default_suggestions ?? [];
  return (
    <div data-testid="tools-agent-detail" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,260px),1fr))", gap: 16, padding: "14px 16px 18px", background: "var(--bg-2)", borderTop: "1px solid var(--cp-line)" }}>
      <div className="flex flex-col min-w-0" style={{ gap: 6 }}>
        <Eyebrow>Routes here when a question matches</Eyebrow>
        {triggers.length === 0 ? (
          <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>No patterns are defined for this agent.</span>
        ) : (
          triggers.map((t) => (
            <code key={t} style={{ fontFamily: "var(--mono)", fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{t}</code>
          ))
        )}
      </div>
      <div className="flex flex-col min-w-0" style={{ gap: 6 }}>
        {starters.length === 0
          ? <><Eyebrow>Starter questions</Eyebrow><span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>None defined.</span></>
          : <AskChips title="Starter questions · ask one" items={starters} />}
      </div>
    </div>
  );
}

export default function OpsToolsScreen() {
  const { go } = useCopilotShell();
  const agents = useCopilotAgents();
  const [openId, setOpenId] = useState<string | null>(null);
  const rows = agents.data ?? [];
  const open = rows.find((a) => a.id === openId) ?? null;

  return (
    <Screen testId="screen-ops-tools">
      <OpsHeader
        title="Tool registry"
        sub="What the Copilot can call when it answers. The tools themselves are not listed by the backend yet; the Copilot’s routing agents are."
      />
      <OpsTabs current="ops/tools" />

      <NotConnected
        testId="tools-registry-not-connected"
        title="The Copilot’s tools are not listed anywhere yet"
        body="The tools exist as code (backend/services/copilot_tools) and run inside the chat pipeline, but no endpoint returns their names, contracts or versions, or reports how often and how fast they run. This table stays empty until one does."
        needs={[
          "A registry endpoint for the tools the chat pipeline can call (name, owning service, version)",
          "A declared contract per tool: input schema, output schema, permissions, error codes, cache and retry rules",
          "A freshness and timeout setting per tool that the pipeline enforces",
          "Per-call telemetry (duration and outcome) to report p95 latency and the 7-day success rate",
        ]}
        action={<Btn onClick={() => go("builder")}>Draft a tool definition ›</Btn>}
      />

      <div className="flex flex-col" style={{ gap: 10 }}>
        {agents.isPending && <LoadingBlock label="Loading routing agents" rows={4} />}
        {agents.isError && <LoadFailed what="The routing agents" error={agents.error} onRetry={() => agents.refetch()} />}
        {agents.data && rows.length === 0 && (
          <div data-testid="tools-agents-empty">
            <EmptyBlock title="No routing agents are defined" body="The backend returned an empty agent list." />
          </div>
        )}
        {rows.length > 0 && (
          <Section
            flush
            title={<>Routing agents · <span data-testid="tools-agent-count">{rows.length}</span></>}
            note="Select a row for its patterns"
          >
            <DataTable
              columns={COLUMNS}
              rows={rows}
              rowKey={(a) => a.id}
              minWidth={720}
              onRowClick={(a) => setOpenId((cur) => (cur === a.id ? null : a.id))}
            />
            {open && <AgentDetail agent={open} />}
          </Section>
        )}
        {rows.length > 0 && (
          <Footnote>These are agents, not tools: the intent router matches each question to one of them by its patterns</Footnote>
        )}
      </div>
    </Screen>
  );
}
